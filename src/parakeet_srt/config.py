# src/parakeet_srt/config.py
"""프로젝트 전역 설정"""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # ── 모델 ──
    model_name: str = "nvidia/parakeet-tdt-0.6b-v3"

    # ── 오디오 전처리 ──
    sample_rate: int = 16_000
    mono: bool = True
    max_chunk_seconds: float = 1200.0

    # ── SRT 포맷 기본값 ──
    max_chars_per_line: int = 42
    max_lines_per_sub: int = 2
    min_gap_ms: int = 100

    # ── 자동 영어 자막 포매팅 파라미터 ──
    min_sub_duration_sec = 1.2
    max_sub_duration_sec = 6.2
    pause_split_sec = 0.65
    strong_pause_split_sec = 1.00
    target_cps = 15.5
    hard_cps = 18.5
    enable_spacy = False
    spacy_model: str = "en_core_web_sm"

    # ── 번역 ──
    translate_enabled: bool = False
    translate_ollama_url: str = "http://localhost:11434"
    translate_model: str = "translategemma:12b"
    translate_source_lang: str = "en"
    translate_target_lang: str = "ko"
    translate_batch_size: int = 5
    translate_temperature: float = 0.1

    # ── 출력 ──
    output_dir: Path = field(default_factory=lambda: Path("./output"))

    def __post_init__(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def max_chars_per_sub(self) -> int:
        return self.max_chars_per_line * self.max_lines_per_sub
