# C:/Users/Public/Documents/Python_Code/자막작업/parakeet-srt/src/parakeet_srt/converter_tab.py
"""파일 변환 탭 (PyQt6) — 큐 시스템 연동"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QFileDialog, QCheckBox, QComboBox,
    QMessageBox, QApplication, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSpinBox, QDoubleSpinBox, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSlot


SUPPORTED_EXTS = (
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma",
)


class ConverterTab(QWidget):
    """파일 변환 탭. queue_manager와 queue_panel은 외부(MainWindow)에서 주입."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue_manager = None   # MainWindow에서 설정
        self.queue_panel = None     # MainWindow에서 설정
        self._adv_visible = False
        self._create_widgets()
        self._connect_signals()

    def _create_widgets(self):
        main = QVBoxLayout(self)

        # ── 1. 파일 목록 ──
        file_group = QGroupBox("① 파일 목록")
        file_layout = QVBoxLayout(file_group)

        btn_row = QHBoxLayout()
        self.add_files_btn = QPushButton("파일 추가")
        self.add_folder_btn = QPushButton("폴더 추가")
        self.remove_btn = QPushButton("선택 삭제")
        self.clear_btn = QPushButton("목록 초기화")
        btn_row.addWidget(self.add_files_btn)
        btn_row.addWidget(self.add_folder_btn)
        btn_row.addWidget(self.remove_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        file_layout.addLayout(btn_row)

        self.file_table = QTableWidget()
        self.file_table.setColumnCount(2)
        self.file_table.setHorizontalHeaderLabels(["파일명", "상태"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        file_layout.addWidget(self.file_table)

        main.addWidget(file_group)

        # ── 2. 설정 ──
        settings_group = QGroupBox("② 설정")
        settings_layout = QVBoxLayout(settings_group)

        info_label = QLabel("출력: 원본 파일과 같은 폴더에 저장됩니다.")
        info_label.setStyleSheet("color: #2b6cb0;")
        settings_layout.addWidget(info_label)

        # 후처리
        post_row = QHBoxLayout()
        self.txt_cb = QCheckBox("TXT 파일 추출")
        self.ai_cb = QCheckBox("강의 노트용 AI 프롬프트 생성")
        self.ai_source_combo = QComboBox()
        self.ai_source_combo.addItems(["순수 텍스트(TXT) 사용", "타임스탬프 포함(SRT) 사용"])
        self.ai_source_combo.setEnabled(False)
        post_row.addWidget(self.txt_cb)
        post_row.addWidget(QLabel("|"))
        post_row.addWidget(self.ai_cb)
        post_row.addWidget(self.ai_source_combo)
        post_row.addStretch()
        settings_layout.addLayout(post_row)

        # 완료 후 폴더 열기 옵션
        folder_row = QHBoxLayout()
        self.open_folder_cb = QCheckBox("완료 후 출력 폴더 열기")
        self.open_folder_cb.setChecked(True)  # 디폴트 켜짐
        folder_row.addWidget(self.open_folder_cb)
        folder_row.addStretch()
        settings_layout.addLayout(folder_row)

        # Advanced 토글
        adv_btn_row = QHBoxLayout()
        adv_btn_row.addStretch()
        self.adv_btn = QPushButton("Show Advanced ▾")
        adv_btn_row.addWidget(self.adv_btn)
        settings_layout.addLayout(adv_btn_row)

        # Advanced 프레임
        self.adv_frame = QFrame()
        adv_grid = QGridLayout(self.adv_frame)

        adv_grid.addWidget(QLabel("Max chars/line:"), 0, 0)
        self.max_chars_spin = QSpinBox()
        self.max_chars_spin.setRange(20, 80)
        self.max_chars_spin.setValue(42)
        adv_grid.addWidget(self.max_chars_spin, 0, 1)

        adv_grid.addWidget(QLabel("Max lines/sub:"), 0, 2)
        self.max_lines_spin = QSpinBox()
        self.max_lines_spin.setRange(1, 4)
        self.max_lines_spin.setValue(2)
        adv_grid.addWidget(self.max_lines_spin, 0, 3)

        adv_grid.addWidget(QLabel("Min gap (ms):"), 0, 4)
        self.min_gap_spin = QSpinBox()
        self.min_gap_spin.setRange(0, 500)
        self.min_gap_spin.setValue(100)
        adv_grid.addWidget(self.min_gap_spin, 0, 5)

        adv_grid.addWidget(QLabel("Pause split (sec):"), 1, 0)
        self.pause_split_spin = QDoubleSpinBox()
        self.pause_split_spin.setRange(0.2, 1.2)
        self.pause_split_spin.setSingleStep(0.05)
        self.pause_split_spin.setValue(0.65)
        adv_grid.addWidget(self.pause_split_spin, 1, 1)

        adv_grid.addWidget(QLabel("Strong pause (sec):"), 1, 2)
        self.strong_pause_spin = QDoubleSpinBox()
        self.strong_pause_spin.setRange(0.3, 1.5)
        self.strong_pause_spin.setSingleStep(0.05)
        self.strong_pause_spin.setValue(1.0)
        adv_grid.addWidget(self.strong_pause_spin, 1, 3)

        adv_grid.addWidget(QLabel("Target CPS:"), 1, 4)
        self.target_cps_spin = QDoubleSpinBox()
        self.target_cps_spin.setRange(10.0, 24.0)
        self.target_cps_spin.setSingleStep(0.5)
        self.target_cps_spin.setValue(15.5)
        adv_grid.addWidget(self.target_cps_spin, 1, 5)

        self.spacy_cb = QCheckBox("Use spaCy refinement")
        adv_grid.addWidget(self.spacy_cb, 2, 0, 1, 3)

        self.adv_frame.setVisible(False)
        settings_layout.addWidget(self.adv_frame)

        main.addWidget(settings_group)

        # ── 3. 실행 ──
        self.start_btn = QPushButton("▶ 큐에 추가 & 시작")
        self.start_btn.setStyleSheet("padding: 10px; font-size: 14px; font-weight: bold;")
        main.addWidget(self.start_btn)

        self.status_label = QLabel("대기 중...")
        main.addWidget(self.status_label)

    def _connect_signals(self):
        self.add_files_btn.clicked.connect(self._add_files)
        self.add_folder_btn.clicked.connect(self._add_folder)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn.clicked.connect(lambda: self.file_table.setRowCount(0))
        self.adv_btn.clicked.connect(self._toggle_advanced)
        self.ai_cb.toggled.connect(self.ai_source_combo.setEnabled)
        self.start_btn.clicked.connect(self._start_task)

    # ─── 슬롯 ───
    @pyqtSlot()
    def _add_files(self):
        exts = " ".join(f"*{e}" for e in SUPPORTED_EXTS)
        files, _ = QFileDialog.getOpenFileNames(
            self, "파일 선택", os.path.expanduser("~"),
            f"미디어 파일 ({exts});;모든 파일 (*.*)"
        )
        existing = set()
        for r in range(self.file_table.rowCount()):
            item = self.file_table.item(r, 0)
            if item:
                existing.add(item.data(Qt.ItemDataRole.UserRole))

        for f in files:
            if f not in existing:
                row = self.file_table.rowCount()
                self.file_table.insertRow(row)
                name_item = QTableWidgetItem(os.path.basename(f))
                name_item.setData(Qt.ItemDataRole.UserRole, f)
                self.file_table.setItem(row, 0, name_item)
                self.file_table.setItem(row, 1, QTableWidgetItem("대기"))

    @pyqtSlot()
    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if not folder:
            return
        existing = set()
        for r in range(self.file_table.rowCount()):
            item = self.file_table.item(r, 0)
            if item:
                existing.add(item.data(Qt.ItemDataRole.UserRole))

        for f in sorted(Path(folder).iterdir()):
            if f.suffix.lower() in SUPPORTED_EXTS and str(f) not in existing:
                row = self.file_table.rowCount()
                self.file_table.insertRow(row)
                name_item = QTableWidgetItem(f.name)
                name_item.setData(Qt.ItemDataRole.UserRole, str(f))
                self.file_table.setItem(row, 0, name_item)
                self.file_table.setItem(row, 1, QTableWidgetItem("대기"))

    @pyqtSlot()
    def _remove_selected(self):
        rows = sorted(set(idx.row() for idx in self.file_table.selectedIndexes()), reverse=True)
        for r in rows:
            self.file_table.removeRow(r)

    @pyqtSlot()
    def _toggle_advanced(self):
        self._adv_visible = not self._adv_visible
        self.adv_frame.setVisible(self._adv_visible)
        self.adv_btn.setText("Hide Advanced ▴" if self._adv_visible else "Show Advanced ▾")

    @pyqtSlot()
    def _start_task(self):
        count = self.file_table.rowCount()
        if count == 0:
            QMessageBox.warning(self, "입력 오류", "파일을 추가하세요.")
            return

        file_paths = []
        for r in range(count):
            item = self.file_table.item(r, 0)
            if item:
                file_paths.append(item.data(Qt.ItemDataRole.UserRole))

        options = {
            "do_txt": self.txt_cb.isChecked(),
            "do_ai": self.ai_cb.isChecked(),
            "ai_source": "txt" if self.ai_source_combo.currentIndex() == 0 else "srt",
            "open_folder": self.open_folder_cb.isChecked(),
        }

        cfg_overrides = {
            "max_chars_per_line": self.max_chars_spin.value(),
            "max_lines_per_sub": self.max_lines_spin.value(),
            "min_gap_ms": self.min_gap_spin.value(),
            "pause_split_sec": self.pause_split_spin.value(),
            "strong_pause_split_sec": self.strong_pause_spin.value(),
            "target_cps": self.target_cps_spin.value(),
            "enable_spacy": self.spacy_cb.isChecked(),
        }

        params = {
            "file_paths": file_paths,
            "options": options,
            "cfg_overrides": cfg_overrides,
        }

        if self.queue_manager is None:
            QMessageBox.critical(self, "오류", "큐 매니저가 초기화되지 않았습니다.")
            return

        job = self.queue_manager.add_job("file", params)

        # 큐 패널에 행 추가
        desc = f"{len(file_paths)}개 파일"
        if self.queue_panel:
            self.queue_panel.add_job_row(job, desc)

        # 파일 목록 초기화
        self.file_table.setRowCount(0)

        if self.queue_manager.is_running:
            self.status_label.setText(f"작업 #{job.job_id} 큐에 추가됨 (대기 중)")
        else:
            self.status_label.setText(f"작업 #{job.job_id} 시작...")

    def cancel_if_running(self):
        if self.queue_manager:
            self.queue_manager.cancel_all()
