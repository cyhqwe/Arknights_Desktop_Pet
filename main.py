"""明日方舟 维什戴尔 桌面宠物 — 入口。

运行:
    D:\\Python\\newinstaller\\Miniconda\\python.exe main.py
"""
from __future__ import annotations

import signal
import sys

from PySide6.QtWidgets import QApplication

from pet.behavior import start_duration_loader
from pet.config import Config
from pet.window import PetWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    # Ctrl+C:干净退出,而不是让 KeyboardInterrupt 在 Qt 回调里抛 traceback
    def _sigint_handler(signum, frame):
        app.quit()

    signal.signal(signal.SIGINT, _sigint_handler)

    cfg = Config.load()
    win = PetWindow(cfg)
    win.show()

    # 动画元数据:优先读本地缓存(0 解码、即时可用);缓存缺失/文件变化才后台测量一次并写缓存
    from pet import media_cache

    cached = media_cache.load()
    if cached is not None:
        win._behavior.set_media(*cached)
    else:
        def _on_measured(durations: dict, content: dict) -> None:
            win._behavior.measure_ready.emit((durations, content))
            media_cache.save(durations, content)

        start_duration_loader(_on_measured)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
