# C:/Users/Public/Documents/Python_Code/자막작업/parakeet-srt/src/parakeet_srt/job_queue.py
"""작업 큐 매니저 — 작업 중에도 새 작업을 추가하고 순차 실행"""
from __future__ import annotations

import gc
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot

from .audio_utils import cleanup_temp
from .config import Config
from .transcriber import ParakeetTranscriber
from .worker_signals import WorkerSignals


@dataclass
class Job:
    """큐에 들어가는 하나의 작업 단위."""
    job_id: int
    job_type: str                   # "youtube" | "file"
    params: dict = field(default_factory=dict)
    status: str = "대기"             # 대기 | 진행중 | 완료 | 실패 | 취소


class JobQueueSignals(QObject):
    """큐 매니저 → UI 시그널."""
    job_started = pyqtSignal(int)              # job_id
    job_progress = pyqtSignal(int, str)        # job_id, message
    job_finished = pyqtSignal(int, list, list)  # job_id, success_list, failure_list
    job_error = pyqtSignal(int, str)           # job_id, error_msg
    queue_empty = pyqtSignal()                 # 모든 작업 완료
    model_status = pyqtSignal(str)             # 모델 상태 메시지
    open_folder = pyqtSignal(str)              # 완료 후 열어야 할 폴더 경로


class _ModelLoaderWorker(QRunnable):
    """모델 로딩을 백그라운드에서 수행하는 QRunnable."""

    class Signals(QObject):
        finished = pyqtSignal(bool, str)  # success, error_message

    def __init__(self, transcriber: ParakeetTranscriber):
        super().__init__()
        self.transcriber = transcriber
        self.signals = self.Signals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            self.transcriber.load_model()
            self.signals.finished.emit(True, "")
        except Exception as e:
            self.signals.finished.emit(False, str(e))


class _JobRunnerWorker(QRunnable):
    """실제 작업을 수행하는 QRunnable.
    큐 매니저가 하나씩 꺼내서 실행한다.
    모델(transcriber)은 외부에서 주입받아 재사용."""

    def __init__(
        self,
        job: Job,
        transcriber: ParakeetTranscriber,
        signals: JobQueueSignals,
    ):
        super().__init__()
        self.job = job
        self.transcriber = transcriber
        self.signals = signals
        self.is_cancelled = False
        self.setAutoDelete(True)

    def cancel(self):
        self.is_cancelled = True

    def _log(self, msg: str):
        self.signals.job_progress.emit(self.job.job_id, msg)

    @pyqtSlot()
    def run(self):
        job = self.job
        job.status = "진행중"
        self.signals.job_started.emit(job.job_id)

        try:
            if job.job_type == "youtube":
                success, failure = self._run_youtube()
            elif job.job_type == "file":
                success, failure = self._run_file()
            else:
                raise ValueError(f"알 수 없는 작업 타입: {job.job_type}")

            if self.is_cancelled:
                job.status = "취소"
            else:
                job.status = "완료" if not failure else ("실패" if not success else "완료")

            self.signals.job_finished.emit(job.job_id, success, failure)

        except Exception as e:
            job.status = "실패"
            self.signals.job_error.emit(job.job_id, str(e))
            traceback.print_exc()

        finally:
            cleanup_temp()

    # ── YouTube 작업 ──
    def _run_youtube(self) -> tuple[list[str], list[str]]:
        import shutil
        import tempfile

        from .audio_utils import ensure_wav_16k_mono, split_audio_chunks
        from .srt_generator import write_srt, write_txt, srt_to_plain_text
        from .subtitle_formatter import format_segments_to_blocks
        from .ai_prompts import create_ai_prompt_file
        from .media_editor import (
            prepare_include_ranges, create_muted_audio,
            trim_and_concat_media, remap_blocks_from_zero,
        )
        from .youtube_utils import (
            sanitize_filename, get_video_info,
            download_video_audio, download_audio_only,
            get_media_duration,
        )

        params = self.job.params
        urls = params["urls"]
        save_folder = Path(params["save_folder"])
        options = params["options"]
        cfg_overrides = params.get("cfg_overrides", {})

        cfg = self.transcriber.cfg
        for k, v in cfg_overrides.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

        save_folder.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="parakeet_yt_"))
        success, failure = [], []

        try:
            total = len(urls)
            for i, url in enumerate(urls):
                if self.is_cancelled:
                    break

                self._log(f"\n{'═' * 50}\n[{i+1}/{total}] {url}")
                safe_title = "unknown"

                try:
                    self._log("  영상 정보 가져오는 중...")
                    info = get_video_info(url)
                    safe_title = sanitize_filename(info.get('title', 'video'))
                    self._log(f"  Title: {safe_title}")

                    need_video = options.get("save_media") or options.get("cut_edit")
                    if need_video:
                        video_path, audio_path = download_video_audio(url, temp_dir, safe_title, self._log)
                    else:
                        video_path = None
                        audio_path = download_audio_only(url, temp_dir, safe_title, self._log)

                    if not audio_path:
                        raise FileNotFoundError("오디오 다운로드 실패")
                    if self.is_cancelled:
                        break

                    target_audio = audio_path
                    extract_ranges = options.get("extract_ranges", [])
                    extract_mode = options.get("extract_mode")

                    if extract_ranges and extract_mode:
                        self._log("  시간 범위 처리...")
                        duration = get_media_duration(audio_path)
                        if duration <= 0:
                            raise Exception("미디어 길이 확인 불가")
                        inc = prepare_include_ranges(duration, extract_ranges, extract_mode)
                        if not inc:
                            self._log("  유효 범위 없음, 스킵.")
                            continue
                        muted = create_muted_audio(audio_path, inc, temp_dir, duration)
                        if muted:
                            target_audio = muted

                    self._log("  전사 중...")
                    blocks = self._transcribe_to_blocks(Path(target_audio), cfg)
                    if self.is_cancelled or not blocks:
                        if not blocks:
                            self._log("  자막 없음.")
                        continue

                    if options.get("cut_edit") and blocks:
                        self._log("  자막 구간 컷편집...")
                        source = video_path or audio_path
                        ext = Path(source).suffix
                        cut_out = save_folder / f"{safe_title}_subtitled{ext}"
                        cut_result = trim_and_concat_media(str(source), blocks, str(cut_out))
                        if cut_result:
                            self._log(f"  ├─ Cut: {cut_out.name}")
                            blocks = remap_blocks_from_zero(blocks)
                        else:
                            self._log("  ├─ Cut 실패, 원본 타임스탬프 유지.")

                    srt_path = save_folder / f"{safe_title}.srt"
                    write_srt(blocks, srt_path)
                    self._log(f"  ├─ SRT: {srt_path.name} ({len(blocks)} subs)")

                    if options.get("save_media") and not options.get("cut_edit"):
                        if video_path and video_path.exists():
                            dest = save_folder / f"{safe_title}.mp4"
                            shutil.copy2(str(video_path), str(dest))
                            self._log(f"  ├─ Video: {dest.name}")
                        if audio_path and Path(audio_path).exists():
                            dest = save_folder / f"{safe_title}.mp3"
                            shutil.copy2(str(audio_path), str(dest))
                            self._log(f"  ├─ Audio: {dest.name}")

                    extras = self._post_process(
                        srt_path, save_folder, safe_title,
                        options.get("do_txt", False),
                        options.get("do_ai", False),
                        options.get("ai_source", "txt"),
                    )

                    msg = f"'{safe_title}' → SRT ({len(blocks)})"
                    if extras:
                        msg += f", {extras}"
                    success.append(msg)

                except Exception as e:
                    self._log(f"  └─ ERROR: {e}")
                    traceback.print_exc()
                    failure.append(f"'{safe_title}': {e}")

        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

        # 완료 후 폴더 열기 요청
        if options.get("open_folder") and success and not self.is_cancelled:
            self.signals.open_folder.emit(str(save_folder))

        return success, failure

    # ── 파일 변환 작업 ──
    def _run_file(self) -> tuple[list[str], list[str]]:
        from .srt_generator import write_srt
        from .subtitle_formatter import format_segments_to_blocks

        params = self.job.params
        file_paths = params["file_paths"]
        options = params["options"]
        cfg_overrides = params.get("cfg_overrides", {})

        cfg = self.transcriber.cfg
        for k, v in cfg_overrides.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

        success, failure = [], []
        total = len(file_paths)
        opened_folders: set[str] = set()  # 중복 열기 방지

        for i, fp in enumerate(file_paths):
            if self.is_cancelled:
                break

            input_path = Path(fp)
            output_dir = input_path.parent
            self._log(f"\n{'─' * 50}\n[{i+1}/{total}] {input_path.name}")

            try:
                blocks = self._transcribe_to_blocks(input_path, cfg)
                if self.is_cancelled or not blocks:
                    continue

                srt_path = output_dir / f"{input_path.stem}.srt"
                write_srt(blocks, srt_path)
                self._log(f"  ├─ SRT: {srt_path.name} ({len(blocks)} subs)")

                extras = self._post_process(
                    srt_path, output_dir, input_path.stem,
                    options.get("do_txt", False),
                    options.get("do_ai", False),
                    options.get("ai_source", "txt"),
                )
                msg = f"'{input_path.name}' → SRT ({len(blocks)})"
                if extras:
                    msg += f", {extras}"
                success.append(msg)

                # 출력 폴더 수집
                opened_folders.add(str(output_dir))

            except Exception as e:
                self._log(f"  └─ ERROR: {e}")
                traceback.print_exc()
                failure.append(f"'{input_path.name}': {e}")

        # 완료 후 폴더 열기 요청 (중복 제거)
        if options.get("open_folder") and success and not self.is_cancelled:
            for folder in opened_folders:
                self.signals.open_folder.emit(folder)

        return success, failure

    # ── 공통 헬퍼 ──
    def _transcribe_to_blocks(self, audio_path: Path, cfg: Config):
        from .audio_utils import ensure_wav_16k_mono, split_audio_chunks
        from .subtitle_formatter import format_segments_to_blocks

        wav = ensure_wav_16k_mono(audio_path, cfg)
        self._log("  ├─ Audio preprocessed")
        chunks = split_audio_chunks(wav, cfg)
        self._log(f"  ├─ {len(chunks)} chunk(s)")

        all_segments = []
        for chunk_path, offset in chunks:
            if self.is_cancelled:
                return []
            result = self.transcriber.transcribe_file(chunk_path, offset=offset)
            all_segments.extend(result.segments)
            self._log(f"  │   offset={offset:.1f}s → {len(result.segments)} segs")

        return format_segments_to_blocks(all_segments, cfg)

    def _post_process(
        self, srt_path: Path, output_dir: Path, stem: str,
        do_txt: bool, do_ai: bool, ai_source: str,
    ) -> str:
        from .srt_generator import write_txt, srt_to_plain_text
        from .ai_prompts import create_ai_prompt_file

        extras = []
        txt_content = None

        if do_txt or (do_ai and ai_source == "txt"):
            txt_path = write_txt(srt_path)
            if txt_path:
                if do_txt:
                    extras.append("TXT")
                    self._log(f"  ├─ TXT: {txt_path.name}")
                txt_content = txt_path.read_text(encoding="utf-8")
                if not do_txt:
                    txt_path.unlink(missing_ok=True)

        if do_ai:
            content = ""
            if ai_source == "srt":
                content = srt_path.read_text(encoding="utf-8")
            else:
                content = txt_content or srt_to_plain_text(srt_path)
            if content:
                prompt_path = output_dir / f"{stem}_prompt.txt"
                create_ai_prompt_file(str(prompt_path), content)
                extras.append("AI-Prompt")
                self._log(f"  ├─ AI Prompt: {prompt_path.name}")

        return ", ".join(extras)


class JobQueueManager(QObject):
    """작업 큐를 관리하며, 하나씩 순차 실행.
    모델은 첫 작업 시 로드하고, 큐가 비면 해제."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = JobQueueSignals()
        self._queue: list[Job] = []
        self._next_id: int = 1
        self._current_worker: _JobRunnerWorker | None = None
        self._current_job: Job | None = None
        self._is_running: bool = False
        self._model_loading: bool = False  # 모델 로딩 중 플래그

        # 모델을 큐 매니저가 관리
        self._cfg = Config()
        self._transcriber: ParakeetTranscriber | None = None

        # 시그널은 한 번만 연결 (중복 connect 방지)
        self.signals.job_finished.connect(self._on_job_finished)
        self.signals.job_error.connect(self._on_job_error)

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def queue(self) -> list[Job]:
        return list(self._queue)

    @property
    def current_job(self) -> Job | None:
        return self._current_job

    def add_job(self, job_type: str, params: dict) -> Job:
        """큐에 새 작업 추가. 작업 중이면 대기열에 들어감."""
        job = Job(
            job_id=self._next_id,
            job_type=job_type,
            params=params,
        )
        self._next_id += 1
        self._queue.append(job)

        # 현재 작업 중이 아니고 모델 로딩 중도 아니면 바로 시작
        if not self._is_running and not self._model_loading:
            self._process_next()

        return job

    def remove_job(self, job_id: int) -> bool:
        """대기 중인 작업 제거. 진행 중인 작업은 제거 불가."""
        for i, job in enumerate(self._queue):
            if job.job_id == job_id and job.status == "대기":
                self._queue.pop(i)
                return True
        return False

    def cancel_current(self):
        """현재 진행 중인 작업 취소."""
        if self._current_worker:
            self._current_worker.cancel()

    def cancel_all(self):
        """현재 작업 취소 + 대기열 모두 제거."""
        self.cancel_current()
        for job in self._queue:
            if job.status == "대기":
                job.status = "취소"
        self._queue.clear()

    def _ensure_transcriber_instance(self):
        """Transcriber 인스턴스만 생성 (모델 로드는 하지 않음)."""
        if self._transcriber is None:
            self._cfg = Config()
            self._transcriber = ParakeetTranscriber(
                self._cfg,
                log_fn=lambda msg: self.signals.model_status.emit(msg),
            )

    def _release_model(self):
        """모델 해제."""
        if self._transcriber:
            try:
                self._transcriber.release_model()
            except Exception as e:
                print(f"모델 해제 중 오류: {e}")
            self._transcriber = None

        gc.collect()
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
                torch.cuda.synchronize()
        except Exception:
            pass

    def _process_next(self):
        """대기열에서 다음 작업을 꺼내 실행."""
        # 대기 중인 작업 찾기
        next_job = None
        for job in self._queue:
            if job.status == "대기":
                next_job = job
                break

        if next_job is None:
            # 큐 비었음 → 모델 해제
            self._is_running = False
            self._current_job = None
            self._current_worker = None
            self._release_model()
            self.signals.queue_empty.emit()
            return

        self._is_running = True
        self._current_job = next_job

        # Transcriber 인스턴스 확보
        self._ensure_transcriber_instance()

        # 모델이 아직 로드되지 않았으면 백그라운드에서 로드
        if self._transcriber._model is None:
            self._model_loading = True
            self.signals.model_status.emit("모델 로드 중...")

            loader = _ModelLoaderWorker(self._transcriber)
            loader.signals.finished.connect(self._on_model_loaded)
            QThreadPool.globalInstance().start(loader)
            return

        # 모델이 이미 로드되어 있으면 바로 작업 실행
        self._start_job_worker(next_job)

    @pyqtSlot(bool, str)
    def _on_model_loaded(self, success: bool, error_msg: str):
        """모델 로딩 완료 콜백 (메인 스레드에서 실행됨)."""
        self._model_loading = False

        if not success:
            # 모델 로드 실패
            if self._current_job:
                self._current_job.status = "실패"
                self.signals.job_error.emit(
                    self._current_job.job_id, f"모델 로드 실패: {error_msg}"
                )
            return

        self.signals.model_status.emit("모델 로드 완료.")

        # 현재 작업이 아직 유효한지 확인 (취소되었을 수 있음)
        if self._current_job and self._current_job.status != "취소":
            self._start_job_worker(self._current_job)
        else:
            # 취소된 경우 다음 작업으로
            self._process_next()

    def _start_job_worker(self, job: Job):
        """실제 작업 워커를 시작."""
        worker = _JobRunnerWorker(job, self._transcriber, self.signals)
        self._current_worker = worker
        QThreadPool.globalInstance().start(worker)

    @pyqtSlot(int, list, list)
    def _on_job_finished(self, job_id: int, success: list, failure: list):
        """작업 완료 시 큐에서 제거하고 다음 작업 시작."""
        # 현재 진행 중인 작업이 맞는지 확인
        if self._current_job is None or self._current_job.job_id != job_id:
            return

        self._queue = [j for j in self._queue if j.job_id != job_id]
        self._current_worker = None
        self._current_job = None

        # 다음 작업
        self._process_next()

    @pyqtSlot(int, str)
    def _on_job_error(self, job_id: int, msg: str):
        """작업 에러 시 큐에서 제거하고 다음 작업 시작."""
        # 현재 진행 중인 작업이 맞는지 확인
        if self._current_job is not None and self._current_job.job_id != job_id:
            return

        self._queue = [j for j in self._queue if j.job_id != job_id]
        self._current_worker = None
        self._current_job = None

        # 다음 작업
        self._process_next()
