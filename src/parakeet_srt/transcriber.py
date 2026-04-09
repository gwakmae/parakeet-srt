# C:/Users/Public/Documents/Python_Code/자막작업/parakeet-srt/src/parakeet_srt/transcriber.py
"""Parakeet TDT 0.6B v3 모델 로드 및 전사"""
from __future__ import annotations

import gc
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import Config


# ── Windows TemporaryDirectory 파일잠금 우회 ──
class _WindowsSafeTempDir:
    def __init__(self, *args, **kwargs):
        self._dir = tempfile.mkdtemp(*args, **kwargs)
        self.name = self._dir

    def __enter__(self):
        return self.name

    def __exit__(self, *args):
        try:
            shutil.rmtree(self._dir, ignore_errors=True)
        except Exception:
            pass

    def cleanup(self):
        try:
            shutil.rmtree(self._dir, ignore_errors=True)
        except Exception:
            pass


tempfile.TemporaryDirectory = _WindowsSafeTempDir  # type: ignore[assignment]


@dataclass
class WordStamp:
    word: str
    start: float
    end: float


@dataclass
class SegmentStamp:
    text: str
    start: float
    end: float
    words: list[WordStamp]


@dataclass
class TranscribeResult:
    text: str
    segments: list[SegmentStamp]


class ParakeetTranscriber:
    """Parakeet TDT 모델을 로드하고 타임스탬프 포함 전사를 수행."""

    def __init__(
        self,
        cfg: Config,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.cfg = cfg
        self._model = None
        self._device = "cpu"
        self._log_fn = log_fn or print

    def _log(self, msg: str):
        self._log_fn(msg)

    def load_model(self) -> None:
        if self._model is not None:
            return

        import torch
        import nemo.collections.asr as nemo_asr

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        gpu_name = torch.cuda.get_device_name(0) if self._device == "cuda" else "N/A"
        self._log(f"[Parakeet] Device: {self._device.upper()}")
        self._log(f"[Parakeet] GPU: {gpu_name}")
        self._log(f"[Parakeet] Loading {self.cfg.model_name} ...")

        self._model = nemo_asr.models.ASRModel.from_pretrained(
            model_name=self.cfg.model_name
        )
        self._model = self._model.to(self._device)

        decoding_cfg = self._model.cfg.decoding
        decoding_cfg.greedy.max_symbols = 10
        decoding_cfg.strategy = "greedy"
        self._model.change_decoding_strategy(decoding_cfg)

        self._model.change_attention_model(
            self_attention_model="rel_pos_local_attn",
            att_context_size=[256, 256],
        )

        vram = ""
        if self._device == "cuda":
            import torch
            alloc = torch.cuda.memory_allocated() / 1024**3
            vram = f" | VRAM: {alloc:.1f} GB"
        self._log(f"[Parakeet] Model loaded.{vram}")

    def release_model(self) -> None:
        """모델과 관련 CUDA 리소스를 완전히 해제."""
        if self._model is None:
            self._log("[Parakeet] 해제할 모델 없음.")
            return

        import torch

        self._log("[Parakeet] 모델 해제 시작...")

        # 1. 모델을 CPU로 이동 (VRAM에서 즉시 해제)
        try:
            self._model.cpu()
        except Exception:
            pass

        # 2. 모델 내부 참조가 있을 수 있는 속성들 정리
        try:
            if hasattr(self._model, 'preprocessor'):
                self._model.preprocessor = None
            if hasattr(self._model, 'encoder'):
                self._model.encoder = None
            if hasattr(self._model, 'decoder'):
                self._model.decoder = None
            if hasattr(self._model, 'joint'):
                self._model.joint = None
        except Exception:
            pass

        # 3. 모델 객체 삭제
        del self._model
        self._model = None

        # 4. 강제 GC (순환 참조 대응 — 2회)
        gc.collect()
        gc.collect()

        # 5. CUDA 메모리 완전 해제
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            torch.cuda.synchronize()

            allocated = torch.cuda.memory_allocated() / 1024**3
            reserved = torch.cuda.memory_reserved() / 1024**3
            self._log(
                f"[Parakeet] 모델 해제 완료 — "
                f"VRAM 할당: {allocated:.2f}GB, 예약: {reserved:.2f}GB"
            )
        else:
            self._log("[Parakeet] 모델 해제 완료 (CPU 모드).")

    def transcribe_file(
        self,
        wav_path: str | Path,
        offset: float = 0.0,
    ) -> TranscribeResult:
        self.load_model()

        wav_path = Path(wav_path).resolve()

        output = self._model.transcribe(
            [str(wav_path)],
            timestamps=True,
        )

        if not output:
            return TranscribeResult(text="", segments=[])

        result = output[0]
        timestamp = self._safe_timestamp_dict(getattr(result, "timestamp", None))

        raw_words = timestamp.get("word") or []
        raw_segments = timestamp.get("segment") or []

        word_stamps: list[WordStamp] = []
        for w in raw_words:
            word = self._get_field(w, "word", "")
            start = self._get_field(w, "start", None)
            end = self._get_field(w, "end", None)
            if start is None or end is None:
                continue

            token = str(word).strip()
            if not token:
                continue

            word_stamps.append(
                WordStamp(
                    word=token,
                    start=float(start) + offset,
                    end=float(end) + offset,
                )
            )

        segments: list[SegmentStamp] = []
        for seg in raw_segments:
            seg_text = str(self._get_field(seg, "segment", "")).strip()
            seg_start = self._get_field(seg, "start", None)
            seg_end = self._get_field(seg, "end", None)
            if seg_start is None or seg_end is None:
                continue

            seg_start = float(seg_start) + offset
            seg_end = float(seg_end) + offset

            seg_words = [
                w for w in word_stamps
                if not (w.end < seg_start - 0.08 or w.start > seg_end + 0.08)
            ]

            segments.append(
                SegmentStamp(
                    text=seg_text,
                    start=seg_start,
                    end=seg_end,
                    words=seg_words,
                )
            )

        # 혹시 segment timestamp가 비어 있으면 word 기준 fallback
        if not segments and word_stamps:
            text = " ".join(w.word for w in word_stamps).strip()
            segments = [
                SegmentStamp(
                    text=text,
                    start=word_stamps[0].start,
                    end=word_stamps[-1].end,
                    words=word_stamps,
                )
            ]

        text = str(getattr(result, "text", "") or "").strip()
        if not text and segments:
            text = " ".join(seg.text for seg in segments if seg.text).strip()

        return TranscribeResult(text=text, segments=segments)

    @staticmethod
    def _safe_timestamp_dict(obj) -> dict:
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        try:
            return dict(obj)
        except Exception:
            return {}

    @staticmethod
    def _get_field(obj, key: str, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
