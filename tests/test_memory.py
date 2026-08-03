"""内存稳定性:反复切换动作/播放语音 40 秒,验证 RSS 不持续增长;并验证动作+语音组合释放逻辑。

运行:python tests/test_memory.py
"""
import ctypes
import sys
import time
from pathlib import Path
from ctypes import wintypes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.window import PetWindow


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_psapi = ctypes.WinDLL("psapi")
_psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
_psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_HANDLE = _kernel32.GetCurrentProcess()


def rss_mb() -> float:
    c = _PMC()
    c.cb = ctypes.sizeof(c)
    if not _psapi.GetProcessMemoryInfo(_HANDLE, ctypes.byref(c), c.cb):
        return 0.0
    return c.WorkingSetSize / 1024 / 1024


class FakeAudio:
    def __init__(self):
        self.current = None
        self.until = 0.0
        self.dur = {"戳一下": 2, "信赖触摸": 11, "交谈1": 5}

    def play(self, name):
        self.current = name
        self.until = time.monotonic() + self.dur.get(name, 1.0)

    def stop(self):
        self.current = None
        self.until = 0.0

    def is_playing(self):
        return self.current is not None and time.monotonic() < self.until

    def current_name(self):
        return self.current if self.is_playing() else None

    def duration_of(self, name):
        return self.dur.get(name, 1.0)


def main() -> int:
    app = QApplication([])
    win = PetWindow(Config.load())
    win._audio = FakeAudio()
    win.show()
    app.processEvents()

    samples = []
    result = {"ok": False}
    start = time.monotonic()

    def stress():
        if time.monotonic() - start < 36:
            win._behavior.on_click()
            win._behavior._state_until = 0
            win._behavior._tick()
            QTimer.singleShot(2000, stress)
        else:
            finish()

    def sample():
        samples.append((round(time.monotonic() - start), round(rss_mb(), 1)))
        QTimer.singleShot(4000, sample)

    def finish():
        samples.append((round(time.monotonic() - start), round(rss_mb(), 1)))
        combo_tracked = win._combo is not None
        if win._combo:
            win._combo = (win._combo[0], win._combo[1], 0.0)
            win._check_combo_release()
        combo_cleared = win._combo is None

        print("memory samples (s, MB):", samples)
        first = samples[0][1]
        peak = max(v for _, v in samples)
        last = samples[-1][1]
        growth = last - first
        print(f"first={first}MB peak={peak}MB last={last}MB growth={growth:.1f}MB")
        print("combo tracked during stress:", combo_tracked, "| cleared after completion:", combo_cleared)
        result["ok"] = (first > 0 and growth < 30 and combo_tracked and combo_cleared)
        print("MEMORY TEST:", "PASS" if result["ok"] else "FAIL")

        c = Config.load()
        c.birthday = ""
        c.skin = "超新星"
        c.size_percent = 100
        c.always_on_top = True
        c.save()
        win.close()
        app.quit()

    QTimer.singleShot(1000, stress)
    QTimer.singleShot(1000, sample)
    QTimer.singleShot(50000, finish)
    app.exec()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
