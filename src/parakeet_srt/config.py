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
    # local attention으로 최대 3시간 가능하지만, 안전하게 20분 단위 청크
    max_chunk_seconds: float = 1200.0  # 20분

    # ── SRT 포맷 기본값 ──
    # 일반 사용자는 건드리지 않아도 되게 자동 포맷팅 기준으로 설계
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

    # ── 출력 ──
    output_dir: Path = field(default_factory=lambda: Path("./output"))

    def __post_init__(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def max_chars_per_sub(self) -> int:
        return self.max_chars_per_line * self.max_lines_per_sub
