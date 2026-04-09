"""오디오 전처리: 리샘플링, 모노 변환, 긴 오디오 청크 분할"""
import os
import subprocess
import tempfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

from .config import Config

# Windows 임시파일 충돌 방지용 전용 디렉토리
_TEMP_DIR = Path(tempfile.gettempdir()) / "parakeet_srt_tmp"
_TEMP_DIR.mkdir(exist_ok=True)


def _temp_path(suffix: str) -> Path:
    """충돌 없는 임시 파일 경로 생성 (파일을 미리 열지 않음)."""
    import uuid
    return _TEMP_DIR / f"{uuid.uuid4().hex}{suffix}"


def cleanup_temp():
    """임시 파일 정리."""
    if _TEMP_DIR.exists():
        for f in _TEMP_DIR.iterdir():
            try:
                f.unlink()
            except OSError:
                pass


def ensure_wav_16k_mono(input_path: str | Path, cfg: Config) -> Path:
    """입력 오디오를 16kHz 모노 WAV로 변환."""
    input_path = Path(input_path)
    try:
        info = sf.info(str(input_path))
        if (
            info.samplerate == cfg.sample_rate
            and info.channels == 1
            and input_path.suffix.lower() in (".wav", ".flac")
        ):
            return input_path
    except Exception:
        pass

    out_path = _temp_path(".wav")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-ar", str(cfg.sample_rate),
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(out_path),
        ],
        capture_output=True,
        check=True,
    )
    return out_path


def split_audio_chunks(
    wav_path: Path, cfg: Config
) -> list[tuple[Path, float]]:
    """긴 오디오를 max_chunk_seconds 단위로 분할."""
    audio, sr = librosa.load(str(wav_path), sr=cfg.sample_rate, mono=True)
    total_dur = len(audio) / sr

    if total_dur <= cfg.max_chunk_seconds:
        return [(wav_path, 0.0)]

    chunks: list[tuple[Path, float]] = []
    chunk_samples = int(cfg.max_chunk_seconds * sr)

    for i, start in enumerate(range(0, len(audio), chunk_samples)):
        chunk = audio[start : start + chunk_samples]
        offset = start / sr
        out_path = _temp_path(f"_chunk{i:03d}.wav")
        sf.write(str(out_path), chunk, sr, subtype="PCM_16")
        chunks.append((out_path, offset))

    return chunks
