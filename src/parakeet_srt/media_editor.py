"""미디어 편집: 자막 구간 컷편집, 시간 범위 무음 처리"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .youtube_utils import get_stream_info


# ─── 시간 유틸 ───

def hms_to_seconds(hms_str: str) -> float:
    try:
        h, m, s = map(int, hms_str.split(':'))
        return float(h * 3600 + m * 60 + s)
    except (ValueError, IndexError):
        return 0.0


def seconds_to_hms(seconds: float) -> str:
    s_int = int(seconds)
    h = s_int // 3600
    m = (s_int % 3600) // 60
    s = s_int % 60
    return f"{h:02}:{m:02}:{s:02}"


def is_valid_time_format(time_str: str) -> bool:
    try:
        h, m, s = map(int, time_str.split(':'))
        return 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59
    except (ValueError, IndexError):
        return False


def parse_time_string(time_str: str) -> str:
    """숫자만 입력 → HH:MM:SS 포맷. '123458' → '12:34:58'"""
    if not time_str or not time_str.isdigit():
        return time_str
    padded = time_str.zfill(6)
    hours = padded[-6:-4]
    minutes = padded[-4:-2]
    seconds = padded[-2:]
    formatted = f"{hours}:{minutes}:{seconds}"
    if is_valid_time_format(formatted):
        return formatted
    return time_str


def merge_ranges(ranges_hms: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not ranges_hms:
        return []
    ranges_sec = sorted([(hms_to_seconds(s), hms_to_seconds(e)) for s, e in ranges_hms])
    merged = []
    current_start, current_end = ranges_sec[0]
    for next_start, next_end in ranges_sec[1:]:
        if next_start < current_end:
            current_end = max(current_end, next_end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = next_start, next_end
    merged.append((current_start, current_end))
    return [(seconds_to_hms(s), seconds_to_hms(e)) for s, e in merged]


def invert_ranges(total_duration_sec: float, exclude_ranges_hms: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not exclude_ranges_hms:
        return [("00:00:00", seconds_to_hms(total_duration_sec))]
    exclude_sec = sorted([(hms_to_seconds(s), hms_to_seconds(e)) for s, e in exclude_ranges_hms])
    include = []
    last_end = 0.0
    for start, end in exclude_sec:
        if start > last_end:
            include.append((last_end, start))
        last_end = end
    if last_end < total_duration_sec:
        include.append((last_end, total_duration_sec))
    return [(seconds_to_hms(s), seconds_to_hms(e)) for s, e in include]


def prepare_include_ranges(
    total_duration: float,
    user_ranges_hms: list[tuple[str, str]],
    mode: str,
) -> list[tuple[str, str]]:
    merged = merge_ranges(user_ranges_hms)
    if mode == 'include':
        return merged
    else:
        return invert_ranges(total_duration, merged)


# ─── 무음 처리 ───

def create_muted_audio(
    original_audio_path: str | Path,
    include_ranges_hms: list[tuple[str, str]],
    output_dir: str | Path,
    total_duration_sec: float,
) -> Path | None:
    """include 범위 이외를 무음 처리한 오디오 생성."""
    output_path = Path(output_dir) / "muted_audio.mp3"

    # include 외 구간 = mute 구간
    mute_ranges_sec = []
    last_end = 0.0
    for start_hms, end_hms in include_ranges_hms:
        start_sec = hms_to_seconds(start_hms)
        end_sec = hms_to_seconds(end_hms)
        if start_sec > last_end:
            mute_ranges_sec.append((last_end, start_sec))
        last_end = end_sec
    if last_end < total_duration_sec:
        mute_ranges_sec.append((last_end, total_duration_sec))

    if not mute_ranges_sec:
        shutil.copy2(str(original_audio_path), str(output_path))
        return output_path

    volume_filters = []
    for start, end in mute_ranges_sec:
        if end - start > 0.01:
            volume_filters.append(f"volume=enable='between(t,{start},{end})':volume=0")

    if not volume_filters:
        shutil.copy2(str(original_audio_path), str(output_path))
        return output_path

    filter_string = ",".join(volume_filters)
    command = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(original_audio_path),
        '-af', filter_string,
        '-acodec', 'libmp3lame', '-ab', '192k',
        str(output_path)
    ]

    try:
        subprocess.run(command, check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg mute audio 실패: {e}")
        return None


# ─── 자막 구간 컷편집 ───

def trim_and_concat_media(
    media_path: str | Path,
    subtitle_blocks,
    output_path: str | Path,
) -> Path | None:
    """자막 블록 타임스탬프 기반으로 미디어를 잘라서 합침."""
    from .subtitle_formatter import SubtitleBlock

    media_path = str(media_path)
    output_path = str(output_path)

    if not subtitle_blocks:
        return None

    has_video = get_stream_info(media_path, 'video')
    has_audio = get_stream_info(media_path, 'audio')
    if not has_video and not has_audio:
        return None

    filter_parts = []
    concat_streams = ""
    valid_count = 0

    for block in subtitle_blocks:
        start_sec = block.start
        end_sec = block.end
        if end_sec - start_sec <= 0.01:
            continue

        if has_video:
            filter_parts.append(
                f"[0:v]trim=start={start_sec}:end={end_sec},setpts=PTS-STARTPTS[v{valid_count}]"
            )
        if has_audio:
            filter_parts.append(
                f"[0:a]atrim=start={start_sec}:end={end_sec},asetpts=PTS-STARTPTS[a{valid_count}]"
            )

        if has_video:
            concat_streams += f"[v{valid_count}]"
        if has_audio:
            concat_streams += f"[a{valid_count}]"
        valid_count += 1

    if not filter_parts:
        return None

    if has_video and has_audio:
        concat_streams += f"concat=n={valid_count}:v=1:a=1[outv][outa]"
    elif has_video:
        concat_streams += f"concat=n={valid_count}:v=1:a=0[outv]"
    elif has_audio:
        concat_streams += f"concat=n={valid_count}:v=0:a=1[outa]"

    filter_complex = ";".join(filter_parts) + ";" + concat_streams
    command = ['ffmpeg', '-y', '-i', media_path, '-filter_complex', filter_complex]

    if has_video:
        command.extend(['-map', '[outv]'])
    if has_audio:
        command.extend(['-map', '[outa]'])
    if has_video:
        command.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '23'])
    if has_audio:
        command.extend(['-c:a', 'aac', '-b:a', '192k'])
    command.extend([output_path, '-loglevel', 'error'])

    try:
        subprocess.run(command, check=True)
        return Path(output_path)
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg concat filter 실패: {e}")
        return None


def remap_blocks_from_zero(blocks) -> list:
    """컷편집된 미디어에 맞게 자막 타임스탬프를 0부터 재정렬."""
    from .subtitle_formatter import SubtitleBlock

    remapped = []
    current_time = 0.0
    for i, block in enumerate(blocks, 1):
        duration = block.end - block.start
        if duration <= 0.01:
            continue
        remapped.append(SubtitleBlock(
            index=i,
            start=current_time,
            end=current_time + duration,
            text=block.text,
        ))
        current_time += duration
    return remapped
