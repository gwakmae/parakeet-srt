# C:/Users/Public/Documents/Python_Code/자막작업/parakeet-srt/src/parakeet_srt/workers.py
"""백그라운드 워커: yt-dlp 업데이트 전용
(파일 변환 / YouTube 작업은 job_queue.py의 _JobRunnerWorker로 이전)"""
from __future__ import annotations

from PyQt6.QtCore import QRunnable, pyqtSlot

from .worker_signals import WorkerSignals


# ══════════════════════════════════════════════
# yt-dlp 업데이트 워커
# ══════════════════════════════════════════════
class YtdlpUpdateWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        import sys
        import subprocess

        python = sys.executable

        # 1) pip가 있는지 확인
        try:
            subprocess.run(
                [python, "-m", "pip", "--version"],
                check=True, capture_output=True, text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.signals.progress.emit("pip가 없어 설치 중...")
            try:
                subprocess.run(
                    [python, "-m", "ensurepip", "--upgrade"],
                    check=True, capture_output=True, text=True,
                )
            except Exception as e:
                self.signals.finished.emit(
                    [],
                    [f"pip 설치 실패: {e}\n\n수동으로 설치하세요:\n{python} -m ensurepip --upgrade"],
                )
                return

        # 2) yt-dlp 업데이트
        try:
            result = subprocess.run(
                [python, "-m", "pip", "install", "--upgrade", "yt-dlp", "--no-cache-dir"],
                check=True, capture_output=True, text=True,
                encoding='utf-8', errors='ignore',
            )
            msg = "yt-dlp가 최신 버전으로 업데이트되었습니다.\n\n" + result.stdout
            self.signals.finished.emit([msg], [])

        except subprocess.CalledProcessError as e:
            msg = "yt-dlp 업데이트 실패.\n\n" + (e.stderr or str(e))
            self.signals.finished.emit([], [msg])

        except Exception as e:
            self.signals.finished.emit([], [f"예상치 못한 오류: {e}"])
