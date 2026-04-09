"""SubtitleBlock → SRT/TXT 파일 생성"""
from __future__ import annotations

import re
from pathlib import Path

from .subtitle_formatter import SubtitleBlock


def seconds_to_srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    h = total_ms // 3_600_000
    rem = total_ms % 3_600_000
    m = rem // 60_000
    rem %= 60_000
    s = rem // 1000
    ms = rem % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(blocks: list[SubtitleBlock], output_path: str | Path) -> Path:
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


def srt_to_plain_text(srt_path: str | Path) -> str:
    """SRT 파일에서 순수 텍스트만 추출."""
    srt_path = Path(srt_path)
    srt_content = srt_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}.*?\n'
        r'(.*?)\n\n',
        re.DOTALL | re.MULTILINE
    )
    text_blocks = pattern.findall(srt_content + "\n\n")
    clean_lines = []
    for block in text_blocks:
        cleaned = re.sub(r'<.*?>', '', block)
        cleaned = cleaned.replace('\n', ' ').strip()
        if cleaned:
            clean_lines.append(cleaned)
    return '\n'.join(clean_lines)


def write_txt(srt_path: str | Path) -> Path | None:
    """SRT 파일 옆에 같은 이름으로 .txt 생성."""
    srt_path = Path(srt_path)
    txt_path = srt_path.with_suffix('.txt')
    try:
        content = srt_to_plain_text(srt_path)
        txt_path.write_text(content, encoding="utf-8")
        return txt_path
    except Exception as e:
        print(f"TXT 변환 실패: {e}")
        return None
