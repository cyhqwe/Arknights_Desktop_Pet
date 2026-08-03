"""Win32 窗口检测(ctypes,无第三方依赖):找出桌宠下方最上层的应用窗口。

用于需求:把桌宠拖到其他软件窗口上方时,角色坐在/睡在窗口上;
并跟踪被吸附窗口的移动/关闭/最小化/最大化状态。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
GA_ROOT = 2
SW_SHOWMAXIMIZED = 3


class WINDOWPLACEMENT(ctypes.Structure):
    """ctypes.wintypes 中没有 WINDOWPLACEMENT,需自行定义。"""
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


# 需要忽略的系统窗口类名
IGNORED_CLASSES = {
    "Progman",        # 桌面
    "WorkerW",        # 桌面
    "Shell_TrayWnd",  # 任务栏
    "Shell_SecondaryTrayWnd",
}


def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def is_window_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def is_iconic(hwnd: int) -> bool:
    """窗口是否最小化。"""
    return bool(user32.IsIconic(hwnd))


def is_maximized(hwnd: int) -> bool:
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if not user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        return False
    return wp.showCmd == SW_SHOWMAXIMIZED


def is_fullscreen(hwnd: int) -> bool:
    """窗口覆盖主屏面积 95% 以上视为全屏。"""
    rect = get_window_rect(hwnd)
    if rect is None:
        return False
    w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
    if w <= 0 or h <= 0:
        return False
    screen_area = w * h
    win_area = (rect[2] - rect[0]) * (rect[3] - rect[1])
    return win_area >= screen_area * 0.95


def _acceptable(hwnd: int, px: int, py: int) -> bool:
    """判断 hwnd 是否可作为吸附目标(可见、非系统窗口、非最小化、尺寸足够、包含检测点)。"""
    if not hwnd:
        return False
    if not user32.IsWindowVisible(hwnd):
        return False
    if is_iconic(hwnd):
        return False  # 最小化窗口不可见,不能作为吸附目标
    cls = _get_class_name(hwnd)
    if cls in IGNORED_CLASSES:
        return False
    if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
        return False
    rect = get_window_rect(hwnd)
    if rect is None:
        return False
    left, top, right, bottom = rect
    if (right - left) < 80 or (bottom - top) < 40:
        return False
    return left <= px <= right and top <= py <= bottom


def find_window_below(px: int, py: int, exclude_hwnd: int) -> tuple[int, tuple[int, int, int, int]] | None:
    """返回屏幕坐标 (px, py) 处**最顶层**的应用窗口 (hwnd, rect)。

    优先用 WindowFromPoint 取该点最顶层的窗口(含子窗口)并提升到根窗口,
    保证吸附的是最上面的窗口而不是被遮挡的下层窗口。
    """
    # 1) 该点最顶层窗口(可能是子窗口),提升到根顶层窗口
    pt = wintypes.POINT(px, py)
    topmost = user32.WindowFromPoint(pt)
    if topmost:
        root = user32.GetAncestor(topmost, GA_ROOT) or topmost
        for candidate in (root, topmost):
            if candidate and candidate != exclude_hwnd and _acceptable(candidate, px, py):
                rect = get_window_rect(candidate)
                return candidate, rect

    # 2) 回退:EnumWindows 排除自身后按 z-order 找第一个匹配
    results: list[tuple[int, tuple[int, int, int, int]]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if hwnd == exclude_hwnd:
            return True
        if _acceptable(hwnd, px, py):
            rect = get_window_rect(hwnd)
            results.append((hwnd, rect))
        return True

    user32.EnumWindows(callback, 0)
    return results[0] if results else None
