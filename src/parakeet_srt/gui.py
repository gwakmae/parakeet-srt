# C:/Users/Public/Documents/Python_Code/자막작업/parakeet-srt/src/parakeet_srt/gui.py
"""Legacy GUI 모듈 — 더 이상 사용하지 않음.
PyQt6 기반 GUI는 main.py → main_window.py를 통해 실행됩니다.
"""


def launch_gui():
    """하위 호환용 — PyQt6 GUI로 리다이렉트."""
    from .main import launch_gui as _launch
    _launch()
