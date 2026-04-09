"""YouTube 다운로드 유틸리티 (yt-dlp)"""
from __future__ import annotations

import os
import re
import subprocess
import glob
import time
from pathlib import Path
from typing import Callable, Optional


def sanitize_filename(filename: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    sanitized = re.sub(r'[\000-\010\013\014\016-\037]', '', sanitized)
    sanitized = sanitized.strip()
    sanitized = re.sub(r'\s+', ' ', sanitized)
    if sanitized.endswith('.'):
        sanitized = sanitized[:-1].strip()
    if not sanitized:
        sanitized = "untitled"
    return sanitized


def get_video_info(url: str) -> dict:
    """yt-dlp로 영상 메타데이터 가져오기 (다운로드 없이)."""
    import yt_dlp
    with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'nocheckcertificate': True}) as ydl:
        info = ydl.extract_info(url, download=False)
    return info


def download_video_audio(
    url: str,
    save_path: str | Path,
    safe_title: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> tuple[Path | None, Path | None]:
    """YouTube 영상+오디오 다운로드. (video_path, audio_path) 반환."""
    import yt_dlp

    log = log_fn or print
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)

    video_path = None
    audio_path = None

    # ── 비디오 다운로드 ──
    video_out_tmpl = str(save_path / f'{safe_title}_video.%(ext)s')
    video_opts = {
        'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/'
                  'bestvideo[ext=mp4][height<=1080]/'
                  'best[ext=mp4][height<=1080]/'
                  'bestvideo+bestaudio/best',
        'outtmpl': video_out_tmpl,
        'merge_output_format': 'mp4',
        'quiet': False,
        'nocheckcertificate': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 30,
    }
    try:
        log("  비디오 다운로드 중...")
        with yt_dlp.YoutubeDL(video_opts) as ydl:
            ydl.download([url])
        time.sleep(1)
        expected = save_path / f"{safe_title}_video.mp4"
        if expected.exists():
            video_path = expected
        else:
            found = glob.glob(str(save_path / f"{safe_title}_video.*"))
            for f in found:
                if '.part' not in f:
                    video_path = Path(f)
                    break
    except Exception as e:
        log(f"  비디오 다운로드 실패: {e}")

    # ── 오디오 다운로드 (mp3) ──
    audio_out_tmpl = str(save_path / f'{safe_title}_audio.%(ext)s')
    audio_opts = {
        'format': 'bestaudio/best',
        'outtmpl': audio_out_tmpl,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'quiet': False,
        'nocheckcertificate': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 30,
    }
    try:
        log("  오디오 다운로드 중...")
        with yt_dlp.YoutubeDL(audio_opts) as ydl:
            ydl.download([url])
        expected_audio = save_path / f"{safe_title}_audio.mp3"
        if expected_audio.exists():
            audio_path = expected_audio
    except Exception as e:
        log(f"  오디오 다운로드 실패: {e}")

    return video_path, audio_path


def download_audio_only(
    url: str,
    save_path: str | Path,
    safe_title: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Path | None:
    """오디오만 다운로드 (자막 생성용)."""
    import yt_dlp

    log = log_fn or print
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)

    audio_out_tmpl = str(save_path / f'{safe_title}_audio.%(ext)s')
    audio_opts = {
        'format': 'bestaudio/best',
        'outtmpl': audio_out_tmpl,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'quiet': False,
        'nocheckcertificate': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 30,
    }
    try:
        log("  오디오 다운로드 중...")
        with yt_dlp.YoutubeDL(audio_opts) as ydl:
            ydl.download([url])
        expected_audio = save_path / f"{safe_title}_audio.mp3"
        if expected_audio.exists():
            return expected_audio
    except Exception as e:
        log(f"  오디오 다운로드 실패: {e}")

    return None


def get_media_duration(file_path: str | Path) -> float:
    """ffprobe로 미디어 길이(초) 반환."""
    file_path = str(file_path)
    if not os.path.exists(file_path):
        return 0.0
    command = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return 0.0


def get_stream_info(file_path: str | Path, stream_type: str) -> bool:
    """파일에 특정 스트림(video/audio)이 있는지 확인."""
    file_path = str(file_path)
    if not os.path.exists(file_path):
        return False
    command = [
        'ffprobe', '-v', 'error', '-select_streams', stream_type[0],
        '-show_entries', 'stream=codec_type',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True,
        )
        return stream_type in result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
