"""行为状态机:空闲循环(Move/Relax/Special)、点击交互(Interact)、坐/睡(dock)。

驱动方式:一个 100ms 的 QTimer 检查状态切换;动作切换通过 action_changed 信号发出,
由 Window 决定加载对应皮肤的动作文件。语音通过 voice_requested 信号发出。
"""
from __future__ import annotations

import random
import threading

import av
import numpy as np

from PySide6.QtCore import QObject, QTimer, Signal

from .config import RES_DIR, SKIN_ACTIONS, SKINS
from .video_player import GREEN_K1

# 空闲循环时长范围(秒)
IDLE_MOVE_RANGE = (6.0, 14.0)
IDLE_RELAX_RANGE = (4.0, 9.0)
SPECIAL_CHANCE = 0.35          # 每轮空闲循环触发 Special 的概率
INTERACT_VOICE = (("戳一下", 0.7), ("信赖触摸", 0.3))

# 饱和度阈值:饱和度高于此值视为“角色本体”(彩色),低于此值视为脚下阴影/特效
SAT_THRESHOLD = 40


def _content_ratios(rgb) -> tuple[float, float]:
    """计算“角色本体周围”的 [底部比例, 水平中心比例](0~1)。

    背景为纯绿:用绿色优势度排除背景;再叠加饱和度过滤排除脚下的
    灰色阴影/特效(如超新星皮肤脚下有渐变光晕,会把边界拉低
    20~70px,导致角色本体悬空)。
    """
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    greenness = g - np.maximum(r, b)
    alpha_mask = greenness < GREEN_K1  # 非背景绿的内容
    mx = np.maximum(r, np.maximum(g, b))
    mn = np.minimum(r, np.minimum(g, b))
    mask = alpha_mask & ((mx - mn) > SAT_THRESHOLD)  # 角色本体(彩色非绿)
    ys, xs = np.where(mask)
    if ys.size == 0:
        # 兜底:整帧没有彩色像素时退回全部非背景绿内容
        ys, xs = np.where(alpha_mask)
        if ys.size == 0:
            return 0.8, 0.5
    return float(ys.max() / rgb.shape[0]), float(((xs.min() + xs.max()) / 2) / rgb.shape[1])


def measure_durations() -> tuple[dict[str, float], dict[tuple[str, str], tuple[float, float]]]:
    """解码全部视频(每 10 帧采样),返回:
    - {文件名动作键: 时长秒}
    - {(皮肤, 动作): (画面底部比例, 画面水平中心比例)}
    后台线程调用,不阻塞 UI。画面比例用于 dock 时按 .webm 内容对齐窗口顶边。
    """
    result: dict[str, float] = {}
    content: dict[tuple[str, str], tuple[float, float]] = {}
    for skin, actions in SKINS.items():
        for action, fname in actions.items():
            path = RES_DIR / fname
            try:
                with av.open(str(path)) as container:
                    stream = container.streams.video[0]
                    n = 0
                    last_pts = 0
                    bottoms: list[float] = []
                    centers: list[float] = []
                    for frame in container.decode(stream):
                        n += 1
                        last_pts = frame.pts
                        if n % 10 == 1:  # 每 10 帧采样,降低开销
                            rgb = frame.to_ndarray(format="rgb24")
                            b, c = _content_ratios(rgb)
                            bottoms.append(b)
                            centers.append(c)
                    if n:
                        tb = float(frame.time_base)
                        result[f"{skin}:{action}"] = last_pts * tb
                    content[(skin, action)] = (
                        float(np.median(bottoms)) if bottoms else 0.8,
                        float(np.median(centers)) if centers else 0.5,
                    )
            except Exception:
                result[f"{skin}:{action}"] = 3.0  # 兜底值
                content[(skin, action)] = (0.8, 0.5)
    return result, content


class BehaviorController(QObject):
    action_changed = Signal(str)   # Interact/Move/Relax/Sit/Sleep/Special
    voice_requested = Signal(str)  # 语音名
    measure_ready = Signal(object)  # (durations, content) 元组,后台测量完成

    def __init__(self, durations: dict[str, float] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._durations: dict[str, float] = durations or {}
        self._content: dict[tuple[str, str], tuple[float, float]] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._state: str | None = None
        self._state_until: float = 0.0
        self._docked = False
        self._docked_action: str | None = None
        self._pending_voice: str | None = None
        self._skin = "超新星"
        # 信号跨线程自动排队到 GUI 线程处理
        self.measure_ready.connect(self._on_measure_ready)

    def _on_measure_ready(self, payload: tuple) -> None:
        """后台测量完成(在 GUI 线程执行):更新时长与画面内容比例。"""
        durations, content = payload
        self._durations.update(durations)
        self.set_content(content)

    # ---------- 对外 API ----------
    def start(self) -> None:
        self._enter_idle_move()
        self._timer.start()

    def set_skin(self, skin: str) -> None:
        self._skin = skin

    def set_media(self, durations: dict[str, float], content: dict[tuple[str, str], tuple[float, float]]) -> None:
        """直接注入测量结果(缓存命中时调用,跳过后台解码)。"""
        self._durations.update(durations)
        self.set_content(content)

    def set_content(self, content: dict[tuple[str, str], tuple[float, float]]) -> None:
        """注入各皮肤/动作的画面内容比例(测量线程回调)。"""
        self._content.update(content)

    def content_ratios(self, skin: str, action: str) -> tuple[float, float]:
        """返回 (画面底部比例, 画面水平中心比例),用于按 .webm 内容对齐。"""
        return self._content.get((skin, action), (0.8, 0.5))

    def on_click(self) -> None:
        """单击角色:播放 Interact 完整一遍 + 随机语音。"""
        self._set_state("Interact", self._duration("Interact"))
        self._pending_voice = random.choices(
            [v for v, _ in INTERACT_VOICE], weights=[w for _, w in INTERACT_VOICE]
        )[0]
        self.voice_requested.emit(self._pending_voice)

    def set_docked(self, docked: bool) -> None:
        """是否"坐在/睡在"其他窗口上。进入时随机 Sit 或 Sleep。"""
        if docked == self._docked:
            return
        self._docked = docked
        if docked:
            action = random.choice(("Sit", "Sleep"))
            self._docked_action = action
            self._set_state(action, float("inf"))
        else:
            self._docked_action = None
            self._enter_idle_move()

    def resume_idle(self) -> None:
        """外部(如切换皮肤)请求恢复正常活动循环。"""
        if self._docked:
            self._set_state(self._docked_action or "Sit", float("inf"))
        else:
            self._enter_idle_move()

    def current_action(self) -> str | None:
        return self._state

    # ---------- 内部 ----------
    def _duration(self, action: str) -> float:
        key = f"{self._skin}:{action}"
        return self._durations.get(key, 5.0)

    def _set_state(self, action: str, duration: float) -> None:
        self._state = action
        self._state_until = _now() + duration
        self.action_changed.emit(action)

    def _enter_idle_move(self) -> None:
        if self._docked:
            self._set_state(self._docked_action or "Sit", float("inf"))
            return
        self._set_state("Move", random.uniform(*IDLE_MOVE_RANGE))

    def _enter_idle_relax(self) -> None:
        self._set_state("Relax", random.uniform(*IDLE_RELAX_RANGE))

    def _tick(self) -> None:
        if self._state is None or _now() < self._state_until:
            return
        # 当前状态时长已到,推进
        if self._docked:
            # dock 状态下 Interact 播放完要回到坐/睡姿势,而不是停在 Interact
            if self._state == "Interact":
                self._set_state(self._docked_action or "Sit", float("inf"))
            else:
                # 坐/睡状态保持(防止误触发时长到期)
                self._state_until = _now() + 3600
            return
        if self._state == "Interact":
            self._enter_idle_move()
        elif self._state == "Special":
            self._enter_idle_move()
        elif self._state == "Relax":
            if random.random() < SPECIAL_CHANCE:
                self._set_state("Special", self._duration("Special"))
            else:
                self._enter_idle_move()
        else:  # Move
            self._enter_idle_relax()


def _now() -> float:
    import time
    return time.monotonic()


def start_duration_loader(callback) -> None:
    """后台线程测量动画时长与画面内容比例,完成后在主线程回调(durations, content)。"""

    def worker() -> None:
        durations, content = measure_durations()
        callback(durations, content)

    threading.Thread(target=worker, daemon=True).start()
