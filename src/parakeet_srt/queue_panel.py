# C:/Users/Public/Documents/Python_Code/자막작업/parakeet-srt/src/parakeet_srt/queue_panel.py
"""작업 큐 상태 패널 위젯"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor

from .job_queue import JobQueueManager, Job


# 상태별 색상
_STATUS_COLORS = {
    "대기": QColor(200, 200, 200),
    "진행중": QColor(135, 206, 250),   # light blue
    "완료": QColor(144, 238, 144),     # light green
    "실패": QColor(255, 160, 160),     # light red
    "취소": QColor(255, 200, 150),     # light orange
}


def _open_folder_in_explorer(folder_path: str) -> None:
    """OS 기본 파일 탐색기로 폴더를 연다."""
    folder = Path(folder_path)
    if not folder.exists():
        return
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as e:
        print(f"폴더 열기 실패: {e}")


class QueuePanel(QWidget):
    """큐에 등록된 작업 목록을 표시하는 패널."""

    def __init__(self, queue_manager: JobQueueManager, parent=None):
        super().__init__(parent)
        self.queue_manager = queue_manager
        self._job_rows: dict[int, int] = {}   # job_id → row index
        self._all_results: list[tuple[int, str, list, list]] = []  # history

        self._create_widgets()
        self._connect_signals()

    def _create_widgets(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 헤더
        header = QHBoxLayout()
        self.title_label = QLabel("작업 큐")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(self.title_label)
        header.addStretch()

        self.cancel_current_btn = QPushButton("현재 작업 취소")
        self.cancel_current_btn.setEnabled(False)
        self.cancel_all_btn = QPushButton("전체 취소")
        self.cancel_all_btn.setEnabled(False)
        self.clear_history_btn = QPushButton("기록 정리")

        header.addWidget(self.cancel_current_btn)
        header.addWidget(self.cancel_all_btn)
        header.addWidget(self.clear_history_btn)
        layout.addLayout(header)

        # 큐 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "유형", "설명", "상태"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(180)
        layout.addWidget(self.table)

        # 상태
        self.status_label = QLabel("대기 중...")
        layout.addWidget(self.status_label)

    def _connect_signals(self):
        qm = self.queue_manager

        qm.signals.job_started.connect(self._on_job_started)
        qm.signals.job_progress.connect(self._on_job_progress)
        qm.signals.job_finished.connect(self._on_job_finished)
        qm.signals.job_error.connect(self._on_job_error)
        qm.signals.queue_empty.connect(self._on_queue_empty)
        qm.signals.model_status.connect(self._on_model_status)
        qm.signals.open_folder.connect(self._on_open_folder)

        self.cancel_current_btn.clicked.connect(self._cancel_current)
        self.cancel_all_btn.clicked.connect(self._cancel_all)
        self.clear_history_btn.clicked.connect(self._clear_history)

    # ── 작업 추가 시 호출 (외부에서) ──
    def add_job_row(self, job: Job, description: str):
        """테이블에 작업 행 추가."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._job_rows[job.job_id] = row

        id_item = QTableWidgetItem(str(job.job_id))
        id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, id_item)

        type_label = "YouTube" if job.job_type == "youtube" else "파일 변환"
        self.table.setItem(row, 1, QTableWidgetItem(type_label))
        self.table.setItem(row, 2, QTableWidgetItem(description))

        status_item = QTableWidgetItem(job.status)
        status_item.setBackground(_STATUS_COLORS.get(job.status, QColor(255, 255, 255)))
        self.table.setItem(row, 3, status_item)

        self._update_buttons()

    def _update_status(self, job_id: int, status: str):
        """특정 작업의 상태 셀 업데이트."""
        row = self._job_rows.get(job_id)
        if row is not None and row < self.table.rowCount():
            item = QTableWidgetItem(status)
            item.setBackground(_STATUS_COLORS.get(status, QColor(255, 255, 255)))
            self.table.setItem(row, 3, item)

    def _update_buttons(self):
        is_running = self.queue_manager.is_running
        self.cancel_current_btn.setEnabled(is_running)
        self.cancel_all_btn.setEnabled(is_running or any(
            j.status == "대기" for j in self.queue_manager.queue
        ))

    # ── 시그널 핸들러 ──
    @pyqtSlot(int)
    def _on_job_started(self, job_id: int):
        self._update_status(job_id, "진행중")
        self._update_buttons()
        self.title_label.setText(f"작업 큐 (진행: #{job_id})")

    @pyqtSlot(int, str)
    def _on_job_progress(self, job_id: int, msg: str):
        self.status_label.setText(f"[#{job_id}] {msg}")

    @pyqtSlot(int, list, list)
    def _on_job_finished(self, job_id: int, success: list, failure: list):
        status = "완료" if success and not failure else ("실패" if failure and not success else "완료")
        self._update_status(job_id, status)
        self._all_results.append((job_id, status, success, failure))
        self._update_buttons()

    @pyqtSlot(int, str)
    def _on_job_error(self, job_id: int, msg: str):
        self._update_status(job_id, "실패")
        self._all_results.append((job_id, "실패", [], [msg]))
        self._update_buttons()
        self.status_label.setText(f"[#{job_id}] 오류: {msg}")

    @pyqtSlot()
    def _on_queue_empty(self):
        self.title_label.setText("작업 큐")
        self.status_label.setText("모든 작업 완료. 모델 해제됨.")
        self._update_buttons()

        # 전체 결과 요약
        if self._all_results:
            self._show_summary()

    @pyqtSlot(str)
    def _on_model_status(self, msg: str):
        self.status_label.setText(msg)

    @pyqtSlot(str)
    def _on_open_folder(self, folder_path: str):
        """작업 완료 후 출력 폴더를 파일 탐색기로 연다."""
        _open_folder_in_explorer(folder_path)

    # ── 버튼 동작 ──
    @pyqtSlot()
    def _cancel_current(self):
        self.queue_manager.cancel_current()
        if self.queue_manager.current_job:
            self._update_status(self.queue_manager.current_job.job_id, "취소")

    @pyqtSlot()
    def _cancel_all(self):
        # 대기 중인 것들 상태 업데이트
        for job in self.queue_manager.queue:
            if job.status == "대기":
                self._update_status(job.job_id, "취소")
        self.queue_manager.cancel_all()
        self._update_buttons()

    @pyqtSlot()
    def _clear_history(self):
        """완료/실패/취소된 행 제거."""
        rows_to_remove = []
        for row in range(self.table.rowCount()):
            status_item = self.table.item(row, 3)
            if status_item and status_item.text() in ("완료", "실패", "취소"):
                rows_to_remove.append(row)

        for row in sorted(rows_to_remove, reverse=True):
            # job_rows 매핑 업데이트
            for jid, r in list(self._job_rows.items()):
                if r == row:
                    del self._job_rows[jid]
                    break
            self.table.removeRow(row)

        # 행 번호 재매핑
        self._rebuild_row_map()
        self._all_results.clear()

    def _rebuild_row_map(self):
        new_map = {}
        for row in range(self.table.rowCount()):
            id_item = self.table.item(row, 0)
            if id_item:
                try:
                    jid = int(id_item.text())
                    new_map[jid] = row
                except ValueError:
                    pass
        self._job_rows = new_map

    def _show_summary(self):
        """큐 완료 시 전체 결과 팝업."""
        all_success = []
        all_failure = []
        for job_id, status, success, failure in self._all_results:
            all_success.extend(success)
            all_failure.extend(failure)

        summary = "--- 전체 작업 결과 ---\n\n"
        if all_success:
            summary += "✅ 성공:\n" + "\n".join(f"- {s}" for s in all_success) + "\n\n"
        if all_failure:
            summary += "❌ 실패:\n" + "\n".join(f"- {f}" for f in all_failure) + "\n"
        if not all_success and not all_failure:
            summary = "처리된 항목이 없습니다."

        QMessageBox.information(self, "전체 작업 완료", summary)
