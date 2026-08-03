"""核心回归测试:行为状态机 / dock 判定 / 内容对齐 / 多点探测 / DPI 转换 / measure 重对齐。

运行:python tests/test_regression.py
"""
import sys
import traceback
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import pet.win32_util as wu
from pet.config import Config, SKIN_ACTIONS, SKIN_NAMES, DOCK_DY
from pet.window import PetWindow

ALL_CONTENT = {(sk, a): (1.0, 0.5) for sk in SKIN_NAMES for a in SKIN_ACTIONS}
RECT = (100, 400, 800, 800)  # 窗口顶边 400,中点 500
results = []
errors = []


def record(name, ok, detail):
    results.append((name, ok, detail))


def run_tests(win):
    s = win.width()
    win._dpr = lambda: 1.0  # 固定 DPI=1,聚焦逻辑(DPI 转换单独测)
    win.cfg.skin = "超新星"
    win._behavior.set_skin("超新星")
    win._behavior.set_content(dict(ALL_CONTENT))
    win._behavior.resume_idle()

    # ---- 行为状态机 ----
    b = win._behavior
    seq = []
    b.action_changed.connect(seq.append)
    b._set_state("Move", 100)
    b._state_until = 0
    b._tick()
    record("move->relax", seq[-1] == "Relax", seq[-1])
    b._state_until = 0
    b._tick()
    record("relax->move/special", seq[-1] in ("Move", "Special"), seq[-1])

    # ---- dock 判定:画面底部落在窗口内(任意深度)即吸附 - 底部=400 在窗口 [400,800] 内 ----
    win._behavior._set_state("Move", 100)
    win.move(50, round(400 - 1.0 * s))
    with mock.patch.object(wu, "find_window_below", return_value=(1, RECT)), \
         mock.patch("pet.behavior.random.choice", return_value="Sit"):
        win._update_dock_after_drag()
    record("edge-docks", win._docked, win._docked)

    # ---- 吸附位置:窗口底部对齐顶边(比例 1.0)+ 坐姿下沉偏移,水平保持拖动位置 ----
    exp_y = 400 - s + DOCK_DY[("超新星", "Sit")]
    record("snapped-y", win.y() == exp_y, f"y={win.y()} expected={exp_y}")
    record("snapped-x-kept", win.x() == 50, f"x={win.x()}")

    # ---- 点击回坐姿 ----
    b._state_until = 0
    b._tick()
    record("dock-click-resnap", b.current_action() in ("Sit", "Sleep"), b.current_action())

    # ---- 画面底部在窗口上方(未接触)不吸附;完全在窗口 x 范围外不吸附 ----
    win._exit_dock()
    def finder_rect(px, py, excl):
        return (1, RECT) if RECT[0] <= px <= RECT[2] and RECT[1] <= py <= RECT[3] else None
    win.move(50, round(400 - 1.0 * s) - 300)  # 画面底部=100,窗口顶边 400 -> 上方
    with mock.patch.object(wu, "find_window_below", side_effect=finder_rect):
        win._update_dock_after_drag()
    record("above-window-no-dock", not win._docked, win._docked)
    win.move(-500, round(400 - 1.0 * s))  # 采样点 x<0,窗口 x 从 100 起
    with mock.patch.object(wu, "find_window_below", side_effect=finder_rect):
        win._update_dock_after_drag()
    record("outside-x-no-dock", not win._docked, win._docked)

    # ---- 画面底部略高于窗口顶边(悬空几像素),但窗口底部仍在窗口内 -> 也吸附 ----
    win._exit_dock()
    win._action = "Move"
    win._behavior.set_content({("超新星", "Move"): (0.8, 0.5)})
    win.move(50, round(400 - 0.8 * s) - 9)  # 画面底部 = 395(顶边上方 5)
    with mock.patch.object(wu, "find_window_below", side_effect=finder_rect):
        win._update_dock_after_drag()
    record("hover-above-docks", win._docked, win._docked)

    # ---- 窗口内任意深度都吸附(画面底部深入窗口中部也触发) ----
    win.move(50, round(400 - 1.0 * s) + 200)  # 画面底部=600,窗口内深处
    with mock.patch.object(wu, "find_window_below", return_value=(1, RECT)):
        win._update_dock_after_drag()
    record("any-depth-docks", win._docked, win._docked)

    # ---- 内容对齐数学:画面底部/中心比例;水平保持当前位置 ----
    win._exit_dock()
    win._action = "Sit"
    win._behavior.set_content({("超新星", "Sit"): (0.895, 0.432)})
    win.move(200, 300)
    win._move_to_dock_pos(RECT)
    exp_cy = round(400 - 0.895 * s + DOCK_DY[("超新星", "Sit")])
    record("content-y", win.y() == exp_cy, f"y={win.y()} expected={exp_cy}")
    record("content-x-kept", win.x() == 200, f"x={win.x()}")

    # ---- 多点探测:中心采样点在窗口外,左侧采样点在窗口内仍可触发 ----
    win._exit_dock()
    win._action = "Move"
    win._behavior.set_content({("超新星", "Move"): (1.0, 0.5)})
    win.move(660, round(400 - 1.0 * s))  # 0.2 采样=720 在 [100,800] 内;0.5 采样=810 在窗外
    with mock.patch.object(wu, "find_window_below", side_effect=finder_rect):
        win._update_dock_after_drag()
    record("multi-probe-anywhere", win._docked, win._docked)

    # ---- measure 完成重对齐 ----
    win._exit_dock()
    win._behavior._content.clear()
    win._behavior._set_state("Sit", float("inf"))
    win._behavior.set_content({("超新星", "Sit"): (0.8, 0.5), ("超新星", "Sleep"): (0.8, 0.5)})
    with mock.patch("pet.behavior.random.choice", return_value="Sit"):
        win._enter_dock(1, RECT)
    y_before = win.y()
    win._behavior.set_content({("超新星", "Sit"): (0.895, 0.432), ("超新星", "Sleep"): (0.895, 0.432)})
    win._on_measure_ready(None)
    exp_mr = round(400 - 0.895 * s + DOCK_DY[("超新星", "Sit")])
    record("measure-resnap", win.y() == exp_mr, f"y_before={y_before} y_after={win.y()} expected={exp_mr}")

    # ---- DPI 转换:物理->逻辑 ----
    win._dpr = lambda: 1.5
    win._action = "Sit"
    win._move_to_dock_pos((300, 300, 1200, 800))  # 物理 top=300 -> 逻辑 200
    exp_d = round(300 / 1.5 - 0.895 * s + DOCK_DY[("超新星", "Sit")] / 1.5)
    record("dpi-convert", win.y() == exp_d, f"y={win.y()} expected={exp_d}")
    win._dpr = lambda: 1.0

    # ---- 屏幕范围:Move 不越界 ----
    win._dpr = lambda: 1.0
    win._behavior.resume_idle()
    rect = win._screen_rect()
    win.move(rect.right() - 5, rect.bottom() - 5)
    win._direction = 1
    for _ in range(200):
        win._on_move_tick()
    in_b = rect.left() <= win.x() <= rect.right() - s and rect.top() <= win.y() <= rect.bottom() - s
    record("move-in-bounds", in_b, f"pos=({win.x()},{win.y()})")


def main() -> int:
    app = QApplication([])
    win = PetWindow(Config.load())
    win.show()
    app.processEvents()

    def check():
        try:
            run_tests(win)
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            c = Config.load()
            c.birthday = ""
            c.skin = "超新星"
            c.size_percent = 100
            c.always_on_top = True
            c.save()
            win.close()
            app.quit()

    QTimer.singleShot(1500, check)
    app.exec()

    if errors:
        print("ERRORS:\n", errors[0])
    for name, ok, detail in results:
        print(("PASS" if ok else "FAIL"), name, "|", detail)
    all_ok = bool(results) and all(ok for _, ok, _ in results) and not errors
    print("\nREGRESSION", "ALL PASSED" if all_ok else "FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
