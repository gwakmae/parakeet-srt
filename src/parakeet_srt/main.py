# src/parakeet_srt/main.py
"""진입점: CLI 또는 GUI 모드"""
from __future__ import annotations

import os
import platform
import sys
import argparse


def _preload_c10_dll():
    """PyTorch 2.9.x Windows 버그 대응: c10.dll 사전 로드."""
    if platform.system() != "Windows":
        return
    import ctypes
    from importlib.util import find_spec
    try:
        _spec = find_spec("torch")
        if _spec and _spec.origin:
            _dll = os.path.join(os.path.dirname(_spec.origin), "lib", "c10.dll")
            if os.path.exists(_dll):
                ctypes.CDLL(os.path.normpath(_dll))
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Parakeet TDT 0.6B v3 — English subtitle generator"
    )
    parser.add_argument(
        "inputs", nargs="*",
        help="오디오/비디오 파일 경로 (없으면 GUI 실행)",
    )
    parser.add_argument("--gui", action="store_true", help="GUI 모드로 실행")
    parser.add_argument("-o", "--output-dir", default="./output")
    parser.add_argument("--max-chars", type=int, default=42)
    parser.add_argument("--max-lines", type=int, default=2)
    parser.add_argument("--min-gap", type=int, default=100)
    parser.add_argument("--disable-spacy", action="store_true")
    parser.add_argument("--pause-split", type=float, default=0.45)
    parser.add_argument("--strong-pause", type=float, default=0.75)
    parser.add_argument("--target-cps", type=float, default=17.0)
    args = parser.parse_args()

    if args.gui or not args.inputs:
        launch_gui()
        return

    # CLI 모드 — torch 필요하므로 여기서 동기 로드
    _preload_c10_dll()
    import torch          # noqa: F401
    import torchaudio     # noqa: F401

    import time
    from pathlib import Path
    from .audio_utils import ensure_wav_16k_mono, split_audio_chunks
    from .config import Config
    from .srt_generator import write_srt
    from .subtitle_formatter import format_segments_to_blocks
    from .transcriber import ParakeetTranscriber

    cfg = Config(
        output_dir=Path(args.output_dir),
        max_chars_per_line=args.max_chars,
        max_lines_per_sub=args.max_lines,
        min_gap_ms=args.min_gap,
        enable_spacy=not args.disable_spacy,
        pause_split_sec=args.pause_split,
        strong_pause_split_sec=args.strong_pause,
        target_cps=args.target_cps,
    )
    transcriber = ParakeetTranscriber(cfg)

    t0 = time.perf_counter()
    results = []

    try:
        for p in args.inputs:
            path = Path(p)
            if not path.exists():
                print(f"[SKIP] 파일 없음: {p}", file=sys.stderr)
                continue

            print(f"\n{'=' * 60}\n[Input] {path.name}")
            wav = ensure_wav_16k_mono(path, cfg)
            chunks = split_audio_chunks(wav, cfg)
            print(f"[Chunks] {len(chunks)} chunk(s)")

            all_segments = []
            for chunk_path, offset in chunks:
                result = transcriber.transcribe_file(chunk_path, offset=offset)
                all_segments.extend(result.segments)

            blocks = format_segments_to_blocks(all_segments, cfg)
            srt_path = cfg.output_dir / f"{path.stem}.srt"
            write_srt(blocks, srt_path)
            print(f"[Output] {srt_path}  ({len(blocks)} subtitles)")
            results.append(srt_path)

    finally:
        transcriber.release_model()

    elapsed = time.perf_counter() - t0
    print(f"\n{'=' * 60}\n[Done] {len(results)} file(s) in {elapsed:.1f}s")


def launch_gui():
    # ★ c10.dll만 먼저 로드 (가벼움), torch는 로드하지 않음
    _preload_c10_dll()

    from PyQt6.QtWidgets import QApplication
    from .main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    # ★ UI가 뜬 후 백그라운드에서 torch 프리로드
    from PyQt6.QtCore import QThreadPool, QRunnable, pyqtSlot

    class _TorchPreloader(QRunnable):
        def __init__(self, status_callback):
            super().__init__()
            self.status_callback = status_callback
            self.setAutoDelete(True)

        @pyqtSlot()
        def run(self):
            try:
                self.status_callback("PyTorch 로딩 중...")
                import torch          # noqa: F401
                import torchaudio     # noqa: F401

                device = "CUDA" if torch.cuda.is_available() else "CPU"
                gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"
                self.status_callback(f"PyTorch 준비 완료 ({device} | {gpu})")
            except Exception as e:
                self.status_callback(f"PyTorch 로드 실패: {e}")

    def _update_status(msg: str):
        # 시그널을 통해 메인 스레드에서 UI 업데이트
        if hasattr(window, 'queue_panel') and window.queue_panel:
            window.queue_panel.status_label.setText(msg)

    preloader = _TorchPreloader(_update_status)
    QThreadPool.globalInstance().start(preloader)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
