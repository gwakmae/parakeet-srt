"""워커 스레드용 시그널 정의"""
from PyQt6.QtCore import QObject, pyqtSignal


class WorkerSignals(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(list, list)  # success_list, failure_list
    error = pyqtSignal(str)
