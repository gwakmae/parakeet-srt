# C:/Users/Public/Documents/Python_Code/자막작업/parakeet-srt/src/parakeet_srt/main_window.py
"""메인 윈도우 (PyQt6) — YouTube 탭 + 파일 변환 탭 + 작업 큐"""
from __future__ import annotations

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTabWidget, QApplication
from PyQt6.QtCore import pyqtSlot

from .job_queue import JobQueueManager
from .queue_panel import QueuePanel
from .youtube_tab import YouTubeTab
from .converter_tab import ConverterTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parakeet SRT — English Subtitle Generator")
        self.setGeometry(100, 100, 880, 780)
        self.setMinimumSize(720, 600)

        # 중앙 큐 매니저 (모든 탭이 공유)
        self.queue_manager = JobQueueManager(self)

        self.youtube_tab = None
        self.converter_tab = None
        self.queue_panel = None

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # YouTube 탭
        self.youtube_tab = YouTubeTab()
        self.youtube_tab.queue_manager = self.queue_manager
        self.tab_widget.addTab(self.youtube_tab, "▶  YouTube 다운로드")

        # 파일 변환 탭
        self.converter_tab = ConverterTab()
        self.converter_tab.queue_manager = self.queue_manager
        self.tab_widget.addTab(self.converter_tab, "📁  파일 변환")

        # 큐 패널 (하단에 항상 표시)
        self.queue_panel = QueuePanel(self.queue_manager)
        self.youtube_tab.queue_panel = self.queue_panel
        self.converter_tab.queue_panel = self.queue_panel
        layout.addWidget(self.queue_panel)

        self.setCentralWidget(central)

    def closeEvent(self, event):
        if self.queue_manager:
            self.queue_manager.cancel_all()
        QApplication.instance().processEvents()
        super().closeEvent(event)
        event.accept()
