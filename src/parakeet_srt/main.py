# src/parakeet_srt/main.py
"""진입점: CLI 또는 GUI 모드"""
from __future__ import annotations

import os
import platform
import sys
import argparse


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

    # CLI 모드
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
    """PyQt6 GUI를 실행한다.

    ★ 핵심: Windows에서 PyQt6를 먼저 import하면 torch의 c10.dll 로드가
    실패하는 버그가 있다 (PyTorch 2.9.0+, pytorch/pytorch#166628).
    따라서 반드시 torch를 PyQt6보다 먼저 import해야 한다.
    """
    import traceback

    try:
        # ────────────────────────────────────────────────
        # ★ Step 1: torch를 PyQt6보다 먼저 import (DLL 충돌 방지)
        # ────────────────────────────────────────────────
        print("PyTorch 로딩 중...")
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        warnings.filterwarnings("ignore", message=".*Megatron.*")
        warnings.filterwarnings("ignore", message=".*RequestsDependencyWarning.*")

        import logging
        logging.getLogger("nemo_logger").setLevel(logging.ERROR)

        import torch
        try:
            import torchaudio  # noqa: F401
        except Exception:
            pass

        device = "CUDA" if torch.cuda.is_available() else "CPU"
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"
        torch_info = f"PyTorch 준비 완료 ({device} | {gpu})"
        print(torch_info)

        # ────────────────────────────────────────────────
        # ★ Step 2: 그 다음에 PyQt6 import 및 GUI 실행
        # ────────────────────────────────────────────────
        from PyQt6.QtWidgets import QApplication
        from .main_window import MainWindow

        app = QApplication(sys.argv)
        window = MainWindow()

        # 상태 표시
        if hasattr(window, 'queue_panel') and window.queue_panel:
            window.queue_panel.status_label.setText(torch_info)

        window.show()
        sys.exit(app.exec())

    except Exception:
        traceback.print_exc()
        print("\n[ERROR] GUI 실행 중 오류가 발생했습니다.")
        try:
            input("Press Enter to exit...")
        except EOFError:
            pass


if __name__ == "__main__":
    main()
