"""真实环境端到端:等待后台测量完成,真实 dock 到窗口,验证画面(角色本体)底部精确对齐窗口顶边。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import pet.win32_util as wu
from pet.behavior import start_duration_loader
from pet.config import Config, DOCK_DY
from pet.window import PetWindow


def main() -> int:
    app = QApplication([])
    win = PetWindow(Config.load())
    win.show()
    app.processEvents()
    state = {"measured": False, "ok": None}

    def do_dock():
        dpr = win._dpr()
        s = win.width()
        win._behavior.resume_idle()
        r = wu.find_window_below(960, 540, int(win.winId()))
        if r is None:
            print("no real window at center - SKIP")
            state["ok"] = True
            finish()
            return
        hwnd, rect = r
        top_log = rect[1] / dpr
        b_move, _c = win._behavior.content_ratios(win.cfg.skin, "Move")
        win.move(200, round(top_log - b_move * s))
        win._update_dock_after_drag()
        action = win._behavior.current_action()
        print(f"docked={win._docked} action={action} win._action={win._action} skin={win.cfg.skin}")
        if win._docked:
            b, c2 = win._behavior.content_ratios(win.cfg.skin, win._action)
            exp_y = round(top_log - b * s + DOCK_DY.get((win.cfg.skin, win._action), 0) / dpr)
            # 画面中心应落在窗口水平范围内(窗口透明区域可略超出)
            left_log = rect[0] / dpr
            right_log = rect[2] / dpr
            center_log = win.x() + c2 * s
            x_ok = left_log + 10 <= center_log <= right_log - 10
            aligned = abs(win.y() - exp_y) <= 2 and x_ok
            print(f"y={win.y()} expected={exp_y} | center={center_log:.0f} (win {left_log:.0f}-{right_log:.0f}) | ALIGNED: {'YES' if aligned else 'NO'}")
            state["ok"] = aligned
        else:
            state["ok"] = False
        finish()

    def finish():
        c = Config.load()
        c.birthday = ""
        c.skin = "超新星"
        c.size_percent = 100
        c.always_on_top = True
        c.save()
        win.close()
        app.quit()

    def poll():
        if win._behavior._content:
            state["measured"] = True
            print("MEASURE DONE via signal, content:", len(win._behavior._content))
            do_dock()
        else:
            QTimer.singleShot(500, poll)

    start_duration_loader(lambda d, c: win._behavior.measure_ready.emit((d, c)))
    QTimer.singleShot(500, poll)
    QTimer.singleShot(40000, finish)  # 兜底
    app.exec()
    print("E2E DONE, measured:", state["measured"], "result:", state["ok"])
    return 0 if state["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
