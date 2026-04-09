# C:/Users/Public/Documents/Python_Code/자막작업/parakeet-srt/src/parakeet_srt/youtube_tab.py
"""YouTube 다운로드 탭 (PyQt6) — 큐 시스템 연동"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QPushButton, QFileDialog, QCheckBox, QComboBox,
    QRadioButton, QMessageBox, QButtonGroup, QApplication,
    QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSlot, QThreadPool

from .media_editor import is_valid_time_format, parse_time_string
from .workers import YtdlpUpdateWorker


class YouTubeTab(QWidget):
    """YouTube 탭. queue_manager와 queue_panel은 외부(MainWindow)에서 주입."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue_manager = None   # MainWindow에서 설정
        self.queue_panel = None     # MainWindow에서 설정
        self.update_worker = None
        self.extract_start_entries: list[QLineEdit] = []
        self.extract_end_entries: list[QLineEdit] = []

        default_dl = Path.home() / "Downloads"
        self.folder_path = str(default_dl if default_dl.is_dir() else Path.home())

        self._create_widgets()
        self._connect_signals()

    # ─── UI 구성 ───
    def _create_widgets(self):
        main = QVBoxLayout(self)

        # ── 1. URL 입력 + 목록 ──
        input_group = QGroupBox("① YouTube URL")
        input_layout = QVBoxLayout(input_group)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("YouTube URL 입력 후 추가")
        self.add_btn = QPushButton("목록에 추가")
        self.del_btn = QPushButton("선택 삭제")
        url_row.addWidget(QLabel("URL:"))
        url_row.addWidget(self.url_input, 1)
        url_row.addWidget(self.add_btn)
        url_row.addWidget(self.del_btn)
        input_layout.addLayout(url_row)

        self.queue_table = QTableWidget()
        self.queue_table.setColumnCount(2)
        self.queue_table.setHorizontalHeaderLabels(["URL", "상태"])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        input_layout.addWidget(self.queue_table)
        main.addWidget(input_group)

        # ── 저장 폴더 ──
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("저장 폴더 :"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setText(self.folder_path)
        self.folder_edit.setToolTip("경로를 직접 입력할 수 있습니다. 존재하지 않는 폴더는 자동 생성됩니다.")
        self.browse_btn = QPushButton("폴더 찾기")
        path_row.addWidget(self.folder_edit, 1)
        path_row.addWidget(self.browse_btn)
        main.addLayout(path_row)

        # ── 2. 옵션 ──
        opt_group = QGroupBox("② 옵션")
        opt_layout = QVBoxLayout(opt_group)

        row1 = QHBoxLayout()
        self.save_media_cb = QCheckBox("미디어 파일 저장")
        self.cut_edit_cb = QCheckBox("자막 구간만 컷편집 저장")
        self.extract_cb = QCheckBox("시간 직접 입력 추출")
        row1.addWidget(self.save_media_cb)
        row1.addWidget(self.cut_edit_cb)
        row1.addWidget(self.extract_cb)
        row1.addStretch()
        opt_layout.addLayout(row1)

        # 시간 입력 프레임 (숨김)
        self.extract_frame = QGroupBox("추출 범위 (HH:MM:SS)")
        self.extract_grid = QGridLayout(self.extract_frame)

        self.extract_mode_group = QButtonGroup(self)
        self.include_radio = QRadioButton("선택 구간만")
        self.exclude_radio = QRadioButton("선택 구간 제외")
        self.include_radio.setChecked(True)
        self.extract_mode_group.addButton(self.include_radio)
        self.extract_mode_group.addButton(self.exclude_radio)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.include_radio)
        mode_row.addWidget(self.exclude_radio)
        mode_row.addStretch()
        self.extract_grid.addLayout(mode_row, 0, 0, 1, 3)

        for i in range(5):
            self._add_range_row(i)

        self.add_range_btn = QPushButton("범위 추가")
        self.extract_grid.addWidget(self.add_range_btn, 10, 1)
        self.extract_frame.setVisible(False)
        opt_layout.addWidget(self.extract_frame)

        # 후처리
        row2 = QHBoxLayout()
        self.txt_cb = QCheckBox("TXT 파일 추출")
        self.ai_cb = QCheckBox("강의 노트용 AI 프롬프트 파일 생성")
        self.ai_source_combo = QComboBox()
        self.ai_source_combo.addItems(["순수 텍스트(TXT) 사용", "타임스탬프 포함(SRT) 사용"])
        self.ai_source_combo.setEnabled(False)
        row2.addWidget(self.txt_cb)
        row2.addWidget(QLabel("|"))
        row2.addWidget(self.ai_cb)
        row2.addWidget(self.ai_source_combo)
        row2.addStretch()
        opt_layout.addLayout(row2)

        # 완료 후 폴더 열기 옵션
        folder_open_row = QHBoxLayout()
        self.open_folder_cb = QCheckBox("완료 후 출력 폴더 열기")
        self.open_folder_cb.setChecked(True)  # 디폴트 켜짐
        folder_open_row.addWidget(self.open_folder_cb)
        folder_open_row.addStretch()
        opt_layout.addLayout(folder_open_row)

        main.addWidget(opt_group)

        # ── 3. 하단 버튼 ──
        bottom = QHBoxLayout()
        self.update_ytdlp_btn = QPushButton("yt-dlp 업데이트")
        self.start_btn = QPushButton("큐에 추가 & 시작")
        self.start_btn.setStyleSheet("padding: 10px; font-size: 14px; font-weight: bold;")
        bottom.addWidget(self.update_ytdlp_btn)
        bottom.addStretch()
        bottom.addWidget(self.start_btn)
        main.addLayout(bottom)

        self.status_label = QLabel("대기 중...")
        main.addWidget(self.status_label)

    def _add_range_row(self, index):
        row = index + 1
        self.extract_grid.addWidget(QLabel(f"{index+1}:"), row, 0)
        start_e = QLineEdit()
        start_e.setPlaceholderText("00:00:00")
        start_e.editingFinished.connect(lambda w=start_e: self._format_time(w))
        end_e = QLineEdit()
        end_e.setPlaceholderText("00:00:00")
        end_e.editingFinished.connect(lambda w=end_e: self._format_time(w))
        self.extract_grid.addWidget(start_e, row, 1)
        self.extract_grid.addWidget(end_e, row, 2)
        self.extract_start_entries.append(start_e)
        self.extract_end_entries.append(end_e)

    # ─── 시그널 연결 ───
    def _connect_signals(self):
        self.add_btn.clicked.connect(self._add_url)
        self.del_btn.clicked.connect(self._remove_selected)
        self.url_input.returnPressed.connect(self._add_url)
        self.browse_btn.clicked.connect(self._browse_folder)
        self.folder_edit.editingFinished.connect(self._on_folder_edited)
        self.extract_cb.toggled.connect(self.extract_frame.setVisible)
        self.add_range_btn.clicked.connect(self._add_new_range)
        self.ai_cb.toggled.connect(self.ai_source_combo.setEnabled)
        self.start_btn.clicked.connect(self._start_task)
        self.update_ytdlp_btn.clicked.connect(self._start_ytdlp_update)

    # ─── URL 관리 ───
    @pyqtSlot()
    def _add_url(self):
        url = self.url_input.text().strip()
        if not url:
            return
        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)
        self.queue_table.setItem(row, 0, QTableWidgetItem(url))
        self.queue_table.setItem(row, 1, QTableWidgetItem("대기"))
        self.url_input.clear()

    @pyqtSlot()
    def _remove_selected(self):
        rows = sorted(set(idx.row() for idx in self.queue_table.selectedIndexes()), reverse=True)
        for r in rows:
            self.queue_table.removeRow(r)

    @pyqtSlot()
    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.folder_path)
        if folder:
            self.folder_path = folder
            self.folder_edit.setText(self.folder_path)

    @pyqtSlot()
    def _on_folder_edited(self):
        text = self.folder_edit.text().strip()
        if text:
            self.folder_path = text

    @pyqtSlot()
    def _add_new_range(self):
        idx = len(self.extract_start_entries)
        self.extract_grid.removeWidget(self.add_range_btn)
        self._add_range_row(idx)
        self.extract_grid.addWidget(self.add_range_btn, idx + 2, 1)

    def _format_time(self, widget: QLineEdit):
        text = widget.text().strip().replace(":", "")
        if text.isdigit():
            widget.setText(parse_time_string(text))

    # ─── yt-dlp 업데이트 ───
    @pyqtSlot()
    def _start_ytdlp_update(self):
        reply = QMessageBox.question(
            self, "업데이트 확인",
            "yt-dlp 라이브러리를 최신 버전으로 업데이트하시겠습니까?\n"
            "인터넷 연결이 필요하며, 잠시 소요될 수 있습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return

        self.update_ytdlp_btn.setEnabled(False)
        self.status_label.setText("yt-dlp 업데이트 중...")

        self.update_worker = YtdlpUpdateWorker()
        self.update_worker.signals.finished.connect(self._on_ytdlp_update_finished)
        QThreadPool.globalInstance().start(self.update_worker)

    @pyqtSlot(list, list)
    def _on_ytdlp_update_finished(self, success_list, failure_list):
        self.update_ytdlp_btn.setEnabled(True)
        self.status_label.setText("대기 중...")
        self.update_worker = None

        if success_list:
            QMessageBox.information(self, "업데이트 성공", success_list[0])
        elif failure_list:
            QMessageBox.warning(self, "업데이트 실패", failure_list[0])

    # ─── 저장 폴더 유효성 검사 및 자동 생성 ───
    def _resolve_save_folder(self) -> Path | None:
        raw = self.folder_edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "입력 오류", "저장 폴더를 입력하세요.")
            return None

        save_folder = Path(raw)

        if not save_folder.exists():
            try:
                save_folder.mkdir(parents=True, exist_ok=True)
                self.folder_path = str(save_folder)
                self.status_label.setText(f"폴더 생성됨: {save_folder}")
            except Exception as e:
                QMessageBox.critical(
                    self, "폴더 생성 실패",
                    f"입력한 경로에 폴더를 생성할 수 없습니다.\n\n"
                    f"경로: {save_folder}\n오류: {e}"
                )
                return None
        else:
            self.folder_path = str(save_folder)

        return save_folder

    # ─── 메인 작업 실행 (큐에 추가) ───
    @pyqtSlot()
    def _start_task(self):
        count = self.queue_table.rowCount()
        if count == 0:
            QMessageBox.warning(self, "입력 오류", "URL을 추가하세요.")
            return

        save_folder = self._resolve_save_folder()
        if save_folder is None:
            return

        urls = [self.queue_table.item(i, 0).text() for i in range(count)]

        # 시간 범위
        extract_ranges = []
        extract_mode = None
        if self.extract_cb.isChecked():
            extract_mode = "include" if self.include_radio.isChecked() else "exclude"
            for i in range(len(self.extract_start_entries)):
                s = self.extract_start_entries[i].text().strip()
                e = self.extract_end_entries[i].text().strip()
                if s and e:
                    if not is_valid_time_format(s) or not is_valid_time_format(e):
                        QMessageBox.warning(self, "입력 오류", f"범위 {i+1}의 시간이 잘못되었습니다.")
                        return
                    extract_ranges.append((s, e))

        options = {
            "save_media": self.save_media_cb.isChecked() and not self.cut_edit_cb.isChecked(),
            "cut_edit": self.cut_edit_cb.isChecked(),
            "do_txt": self.txt_cb.isChecked(),
            "do_ai": self.ai_cb.isChecked(),
            "ai_source": "txt" if self.ai_source_combo.currentIndex() == 0 else "srt",
            "extract_ranges": extract_ranges,
            "extract_mode": extract_mode,
            "open_folder": self.open_folder_cb.isChecked(),
        }

        params = {
            "urls": urls,
            "save_folder": str(save_folder),
            "options": options,
            "cfg_overrides": {},
        }

        # 큐에 추가
        if self.queue_manager is None:
            QMessageBox.critical(self, "오류", "큐 매니저가 초기화되지 않았습니다.")
            return

        job = self.queue_manager.add_job("youtube", params)

        # 큐 패널에 행 추가
        desc = f"{len(urls)}개 URL → {save_folder.name}"
        if self.queue_panel:
            self.queue_panel.add_job_row(job, desc)

        # URL 목록 초기화
        self.queue_table.setRowCount(0)

        if self.queue_manager.is_running:
            self.status_label.setText(f"작업 #{job.job_id} 큐에 추가됨 (대기 중)")
        else:
            self.status_label.setText(f"작업 #{job.job_id} 시작...")

    def cancel_if_running(self):
        if self.queue_manager:
            self.queue_manager.cancel_all()
