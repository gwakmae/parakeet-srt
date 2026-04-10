# src/parakeet_srt/translator.py
"""Ollama 기반 SRT 자막 번역 모듈"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import requests

from .subtitle_formatter import SubtitleBlock
from .srt_generator import seconds_to_srt_time


# ── 언어 코드 매핑 ──
LANGUAGES = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
}


@dataclass
class TranslationConfig:
    """번역 설정."""
    enabled: bool = False
    ollama_url: str = "http://localhost:11434"
    model: str = "translategemma:12b"
    source_lang: str = "en"
    target_lang: str = "ko"
    batch_size: int = 5          # 한 번에 몇 줄씩 묶어서 번역
    temperature: float = 0.1
    timeout: int = 120           # 요청 타임아웃 (초)
    max_retries: int = 2         # 실패 시 재시도 횟수


def get_ollama_models(ollama_url: str = "http://localhost:11434") -> list[str]:
    """Ollama에 설치된 모델 목록을 가져온다."""
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        return sorted(models)
    except Exception:
        return []


def _build_prompt(
    source_lang: str,
    target_lang: str,
    texts: list[str],
    model: str,
) -> str:
    """모델에 맞는 번역 프롬프트를 생성한다."""
    src_name = LANGUAGES.get(source_lang, source_lang)
    tgt_name = LANGUAGES.get(target_lang, target_lang)

    # TranslateGemma 전용 프롬프트 (user-only, 지시문 + 빈줄2개 + 텍스트)
    if "translategemma" in model.lower():
        joined = "\n".join(texts)
        return (
            f"You are a professional {src_name} ({source_lang}) to "
            f"{tgt_name} ({target_lang}) translator. "
            f"Your goal is to accurately convey the meaning and nuances of "
            f"the original {src_name} text while adhering to {tgt_name} grammar, "
            f"vocabulary, and cultural sensitivities. "
            f"Produce only the {tgt_name} translation, without any additional "
            f"explanations or commentary. "
            f"Please translate the following {src_name} text into {tgt_name}:\n\n"
            f"{joined}"
        )

    # HY-MT / 일반 LLM 프롬프트
    numbered = "\n".join(f"[{i+1}] {t}" for i, t in enumerate(texts))
    return (
        f"You are a professional subtitle translator from {src_name} to {tgt_name}.\n"
        f"Translate each numbered line below. Keep the numbering format [N].\n"
        f"Output ONLY the translated lines, nothing else.\n\n"
        f"{numbered}"
    )


def _parse_response(
    response_text: str,
    original_texts: list[str],
    model: str,
) -> list[str]:
    """모델 응답에서 번역된 텍스트를 추출한다."""
    lines = [l.strip() for l in response_text.strip().split("\n") if l.strip()]

    # TranslateGemma: 줄 수가 입력과 같으면 그대로 매핑
    if "translategemma" in model.lower():
        if len(lines) >= len(original_texts):
            return lines[: len(original_texts)]
        # 줄 수가 다르면 전체를 하나로 합쳐서 균등 분배
        if len(lines) == 1 and len(original_texts) == 1:
            return lines
        # fallback: 원문 반환
        if not lines:
            return original_texts
        return lines + original_texts[len(lines):]

    # 번호 패턴 [1], [2], ... 파싱
    parsed = {}
    for line in lines:
        m = re.match(r"\[(\d+)\]\s*(.*)", line)
        if m:
            idx = int(m.group(1))
            parsed[idx] = m.group(2).strip()

    if len(parsed) >= len(original_texts):
        return [parsed.get(i + 1, original_texts[i]) for i in range(len(original_texts))]

    # fallback: 번호 없이 줄 수 매칭
    if len(lines) == len(original_texts):
        # 번호 제거 시도
        cleaned = []
        for line in lines:
            cleaned_line = re.sub(r"^\[?\d+\]?\s*", "", line).strip()
            cleaned.append(cleaned_line if cleaned_line else line)
        return cleaned

    # 최종 fallback
    if len(lines) >= len(original_texts):
        return lines[: len(original_texts)]

    return lines + original_texts[len(lines):]


def _call_ollama(
    prompt: str,
    config: TranslationConfig,
) -> str:
    """Ollama API에 번역 요청을 보낸다."""
    payload = {
        "model": config.model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": config.temperature,
        },
    }

    resp = requests.post(
        f"{config.ollama_url}/api/generate",
        json=payload,
        timeout=config.timeout,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def translate_blocks(
    blocks: list[SubtitleBlock],
    config: TranslationConfig,
    log_fn: Optional[Callable[[str], None]] = None,
) -> list[SubtitleBlock]:
    """SubtitleBlock 리스트를 번역하여 새 리스트를 반환한다.
    타임코드는 원본 그대로 유지한다."""
    log = log_fn or (lambda msg: None)

    if not blocks or not config.enabled:
        return []

    translated_blocks: list[SubtitleBlock] = []
    total = len(blocks)
    batch_size = max(1, config.batch_size)

    log(f"  ├─ 번역 시작: {total}개 자막, 배치 크기 {batch_size}")

    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        batch = blocks[batch_start:batch_end]
        texts = [b.text.replace("\n", " ") for b in batch]

        prompt = _build_prompt(
            config.source_lang,
            config.target_lang,
            texts,
            config.model,
        )

        translated_texts = None
        last_error = None

        for attempt in range(config.max_retries + 1):
            try:
                response = _call_ollama(prompt, config)
                translated_texts = _parse_response(response, texts, config.model)
                break
            except Exception as e:
                last_error = e
                if attempt < config.max_retries:
                    time.sleep(1)
                    log(f"  │   재시도 {attempt + 1}/{config.max_retries}...")

        if translated_texts is None:
            log(f"  │   ⚠ 배치 {batch_start+1}-{batch_end} 번역 실패: {last_error}")
            translated_texts = texts  # 원문 유지

        for i, block in enumerate(batch):
            t_text = translated_texts[i] if i < len(translated_texts) else block.text
            translated_blocks.append(SubtitleBlock(
                index=block.index,
                start=block.start,
                end=block.end,
                text=t_text,
            ))

        progress = min(batch_end, total)
        log(f"  │   [{progress}/{total}] 번역 완료")

    log(f"  ├─ 번역 완료: {len(translated_blocks)}개")
    return translated_blocks


def write_translated_srt(
    blocks: list[SubtitleBlock],
    output_path: str | Path,
) -> Path:
    """번역된 SubtitleBlock을 SRT 파일로 저장한다."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for block in blocks:
        lines.append(str(block.index))
        lines.append(
            f"{seconds_to_srt_time(block.start)} --> "
            f"{seconds_to_srt_time(block.end)}"
        )
        lines.append(block.text)
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
