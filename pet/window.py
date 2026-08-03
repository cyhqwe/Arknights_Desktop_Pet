"""主窗口:透明、无边框、置顶的桌面宠物窗口。

职责:
- 绘制视频帧(平滑缩放、朝向翻转)
- 左键拖动 / 单击触发交互 / 滚轮缩放
- 右键菜单:调整大小、设置生日、问候、交谈、切换皮肤、置顶开关、退出
- 启动节日播报(生日/周年庆典/新年)
- 空闲随机语音
- dock 检测:拖到其他窗口上方时坐/睡并吸附
- Move 动作时窗口在桌面上左右移动
"""
from __future__ import annotations

import datetime
import random
import time

from PySide6.QtCore import Qt, QTimer, QRect, QPoint
from PySide6.QtGui import QAction, QActionGroup, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .audio import AudioManager
from .behavior import BehaviorController
from .config import (
    ANNIVERSARY,
    CONFIG_PATH,
    DOCK_DY,
    IDLE_VOICE_POOL,
    NEW_YEAR,
    RES_DIR,
    SIZE_PERCENTS,
    SKIN_ACTIONS,
    SKIN_NAMES,
    SKINS,
    VOICE_LANGS,
    Config,
)
from .video_player import VideoPlayer
from . import win32_util

BASE_SIZE = 300          # 100% 时的窗口边长(px)
MOVE_SPEED = 48          # Move 状态下水平移动速度(px/s,按 100% 尺寸)
IDLE_VOICE_MIN_S = 60    # 空闲语音最小间隔(秒)
IDLE_VOICE_MAX_S = 180
CLICK_THRESHOLD = 6        # 判定单击的最大拖动位移(px)
DOCK_POLL_MS = 80          # dock 跟随检测间隔(毫秒)


class BirthdayDialog(QDialog):
    """设置生日:日历 + 确定/取消/清除生日。"""

    def __init__(self, birthday: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置生日")
        self.setModal(True)
        layout = QVBoxLayout(self)
        hint = QLabel("选择生日(仅比较月-日):")
        layout.addWidget(hint)
        self.calendar = QCalendarWidget(self)
        if birthday:
            try:
                m, d = (int(p) for p in birthday.split("-"))
                self.calendar.setSelectedDate(
                    self.calendar.selectedDate().__class__(2024, m, d)
                )
            except Exception:
                pass
        layout.addWidget(self.calendar)
        buttons = QDialogButtonBox(self)
        ok_btn = buttons.addButton("确定", QDialogButtonBox.ButtonRole.AcceptRole)
        clear_btn = buttons.addButton("清除生日", QDialogButtonBox.ButtonRole.ResetRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        clear_btn.clicked.connect(self._clear)
        self._cleared = False

    def _clear(self) -> None:
        self._cleared = True
        self.accept()

    def result_birthday(self) -> str:
        if self._cleared:
            return ""
        d = self.calendar.selectedDate()
        return f"{d.month():02d}-{d.day():02d}"


class PetWindow(QWidget):
    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self._audio = AudioManager(self)
        self._audio.set_skin(cfg.skin)        # 启动即同步语音腔调(绝对主角=变调)
        self._audio.set_language(cfg.language)  # 启动即同步语音语言
        self._player = VideoPlayer(self)
        self._behavior = BehaviorController(parent=self)
        self._action = "Move"

        # 窗口属性:无边框、置顶、不占任务栏、背景透明
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if cfg.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # Tool 窗口默认不参与 quitOnLastWindowClosed,必须显式开启,否则退出程序后进程不结束
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMouseTracking(True)

        self._drag_offset: QPoint | None = None
        self._press_global: QPoint | None = None
        self._moved_total = 0
        self._direction = 1          # 1=向右, -1=向左
        self._docked = False
        self._docked_target: tuple[int, tuple[int, int, int, int]] | None = None
        self._dock_x_offset: float | None = None  # 吸附时画面中心相对窗口顶边中点的水平偏移

        # 行为信号
        self._behavior.action_changed.connect(self._on_action_changed)
        self._behavior.voice_requested.connect(self._play_voice)
        # 后台测量完成(画面比例精确化)后,若正处于吸附状态则重新对齐
        self._behavior.measure_ready.connect(self._on_measure_ready)
        self._behavior.start()

        # 动作+语音组合生命周期:两者都完成后确认旧资源已释放
        self._combo: tuple[str | None, str | None, float] | None = None
        self._combo_timer = QTimer(self)
        self._combo_timer.setInterval(1000)
        self._combo_timer.timeout.connect(self._check_combo_release)
        self._combo_timer.start()

        # 动画帧刷新(30fps)
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(33)
        self._frame_timer.timeout.connect(self.update)
        self._frame_timer.start()

        # Move 移动 + dock 跟随检测(50ms)
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(50)
        self._move_timer.timeout.connect(self._on_move_tick)
        self._move_timer.start()

        # 空闲语音
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._on_idle_voice)
        self._schedule_idle_voice()

        # 初始尺寸与位置
        self._apply_size()
        if cfg.x is not None and cfg.y is not None:
            self.move(cfg.x, cfg.y)
        else:
            self._place_initial()

        # 加载皮肤与当前动作
        self._player.set_source(str(RES_DIR / SKINS[self.cfg.skin]["Move"]))

        # 启动播报(生日/节日)
        self._play_startup_voices()

    # ---------- 尺寸 / 位置 ----------
    def _current_size(self) -> int:
        return max(60, round(BASE_SIZE * self.cfg.size_percent / 100))

    def _apply_size(self) -> None:
        s = self._current_size()
        center = self.frameGeometry().center() if self.isVisible() else None
        self.resize(s, s)
        if center is not None and self.isVisible():
            self.move(center.x() - s // 2, center.y() - s // 2)

    def _place_initial(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        s = self._current_size()
        self.move(screen.right() - s - 40, screen.bottom() - s - 40)

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        img = self._player.latest_frame()
        if img is None:
            return
        w, h = self.width(), self.height()
        if self._direction < 0:
            painter.save()
            painter.translate(w, 0)
            painter.scale(-1, 1)
        painter.drawImage(QRect(0, 0, w, h), img, QRect(0, 0, img.width(), img.height()))
        if self._direction < 0:
            painter.restore()

    # ---------- 行为回调 ----------
    # ---------- 动作+语音组合释放 ----------
    def _play_voice(self, name: str) -> None:
        """播放语音并记录到当前组合(动作+语音绑定)。"""
        self._audio.play(name)
        self._note_voice(name)

    def _note_action(self, action: str) -> None:
        """动作切换:记录新动作的预期结束时刻(旧的视频容器已即时关闭释放)。"""
        now = time.monotonic()
        dur = self._behavior._durations.get(f"{self.cfg.skin}:{action}", 5.0)
        voice = self._audio.current_name()
        self._combo = (action, voice, now + dur)

    def _note_voice(self, name: str) -> None:
        """语音播放:组合完成时刻取动作与语音中较晚者(都播完才算完成)。"""
        now = time.monotonic()
        v_end = now + self._audio.duration_of(name)
        if self._combo is not None:
            act, _, end = self._combo
            self._combo = (act, name, max(end, v_end))
        else:
            self._combo = (None, name, v_end)

    def _check_combo_release(self) -> None:
        """组合(动作+语音)都播完后:确认旧资源已释放,清除跟踪。

        实际资源(视频容器/帧缓冲/语音)在切换时已即时释放,
        此处保证“动作没做完或语音没播完就不算完成”,组合完成后清理记录。
        """
        if self._combo is not None and time.monotonic() >= self._combo[2]:
            self._combo = None

    def _on_action_changed(self, action: str) -> None:
        self._action = action
        self._player.set_source(str(RES_DIR / SKINS[self.cfg.skin][action]))
        self._note_action(action)
        # dock 状态下动作切换(如点击 Interact、坐/睡)导致画面脚底变化,重新对齐窗口顶边
        if self._docked and self._docked_target is not None:
            self._move_to_dock_pos(self._docked_target[1])

    # ---------- 鼠标事件 ----------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self._moved_total = 0
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            gp = event.globalPosition().toPoint()
            new_pos = gp - self._drag_offset
            # 拖动也限制在屏幕可用范围内,防止把角色拖出屏幕后“消失”
            rect = self._screen_rect()
            s = self._current_size()
            x = max(rect.left(), min(new_pos.x(), rect.right() - s))
            y = max(rect.top(), min(new_pos.y(), rect.bottom() - s))
            self.move(x, y)
            if self._press_global is not None:
                self._moved_total = (gp - self._press_global).manhattanLength()
                # 确定是拖动(位移超过单击阈值)且正坐在/睡在窗口上:站起来跟随拖动
                if self._moved_total > CLICK_THRESHOLD and self._docked:
                    self._exit_dock()
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            was_click = (
                self._press_global is not None and self._moved_total <= CLICK_THRESHOLD
            )
            self._press_global = None
            self._drag_offset = None
            if was_click:
                self._behavior.on_click()
            else:
                # 拖动结束:检测是否被拖到其他窗口上方,是则坐下/睡下
                self._update_dock_after_drag()
            event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        # 滚轮缩放:向上放大、向下缩小,10% 一档
        delta = 10 if event.angleDelta().y() > 0 else -10
        new = min(300, max(30, self.cfg.size_percent + delta))
        if new != self.cfg.size_percent:
            self.cfg.size_percent = new
            self.cfg.save()
            self._apply_size()
        event.accept()

    # ---------- 右键菜单 ----------
    def _build_menu(self) -> QMenu:
        menu = QMenu(self)

        # 调整大小
        size_menu = menu.addMenu("调整大小")
        group = QActionGroup(self)
        for p in SIZE_PERCENTS:
            act = QAction(f"{p}%", self)
            act.setCheckable(True)
            act.setChecked(self.cfg.size_percent == p)
            act.triggered.connect(lambda _=False, pct=p: self._set_size(pct))
            group.addAction(act)
            size_menu.addAction(act)

        # 设置生日
        birthday_act = menu.addAction("设置生日")
        birthday_act.triggered.connect(self._open_birthday_dialog)

        # 问候
        greet_act = menu.addAction("问候")
        greet_act.triggered.connect(lambda: self._audio.play("问候"))

        # 交谈(随机一条)
        talk_act = menu.addAction("交谈")
        talk_act.triggered.connect(
            lambda: self._audio.play(random.choice(("交谈1", "交谈2", "交谈3")))
        )

        # 切换皮肤
        skin_menu = menu.addMenu("切换皮肤")
        skin_group = QActionGroup(self)
        for name in SKIN_NAMES:
            act = QAction(name, self)
            act.setCheckable(True)
            act.setChecked(self.cfg.skin == name)
            act.triggered.connect(lambda _=False, n=name: self._switch_skin(n))
            skin_group.addAction(act)
            skin_menu.addAction(act)

        # 切换语言
        lang_menu = menu.addMenu("切换语言")
        lang_group = QActionGroup(self)
        lang_labels = {"JP": "日文 (JP)", "zh-CN": "中文 (zh-CN)"}
        for lang in VOICE_LANGS:
            act = QAction(lang_labels.get(lang, lang), self)
            act.setCheckable(True)
            act.setChecked(self.cfg.language == lang)
            act.triggered.connect(lambda _=False, l=lang: self._switch_language(l))
            lang_group.addAction(act)
            lang_menu.addAction(act)

        # 置顶开关
        top_act = QAction("置顶", self)
        top_act.setCheckable(True)
        top_act.setChecked(self.cfg.always_on_top)
        top_act.toggled.connect(self._toggle_on_top)
        menu.addAction(top_act)

        menu.addSeparator()
        quit_act = menu.addAction("退出程序")
        quit_act.triggered.connect(self.close)
        return menu

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = self._build_menu()
        menu.exec(event.globalPos())

    def _set_size(self, percent: int) -> None:
        self.cfg.size_percent = percent
        self.cfg.save()
        self._apply_size()

    def _open_birthday_dialog(self) -> None:
        dlg = BirthdayDialog(self.cfg.birthday, self)
        if dlg.exec():
            self.cfg.birthday = dlg.result_birthday()
            self.cfg.save()

    def _switch_skin(self, name: str) -> None:
        if name == self.cfg.skin:
            return
        self.cfg.skin = name
        self.cfg.save()
        self._behavior.set_skin(name)
        self._audio.set_skin(name)
        self._player.set_source(str(RES_DIR / SKINS[name][self._action]))
        # 切换皮肤后恢复正常活动循环(而非停留在当前动作)
        self._behavior.resume_idle()

    def _switch_language(self, lang: str) -> None:
        """切换语音语言(JP 日文 / zh-CN 中文),持久化并停掉当前语音。"""
        if lang == self.cfg.language:
            return
        self.cfg.language = lang
        self.cfg.save()
        self._audio.set_language(lang)

    def _toggle_on_top(self, checked: bool) -> None:
        self.cfg.always_on_top = checked
        self.cfg.save()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    # ---------- Move 移动与 dock ----------
    def _dpr(self) -> float:
        """窗口的 DPI 缩放系数(物理像素 = 逻辑像素 × dpr)。"""
        return max(1.0, self.devicePixelRatioF())

    def _screen_rect(self):
        """桌宠当前所在屏幕的可用区域(排除任务栏),作为活动范围。"""
        scr = self.screen()
        if scr is None:
            scr = QApplication.primaryScreen()
        return scr.availableGeometry()

    def _on_move_tick(self) -> None:
        # dock 状态下跟踪被吸附窗口:跟随移动,窗口关闭/最小化/最大化/全屏时脱离
        self._follow_docked_window()
        # Move 状态下左右移动,并始终限制在屏幕可用范围内(不跑出屏幕)
        if self._action == "Move" and not self._docked:
            speed = MOVE_SPEED * self.cfg.size_percent / 100
            step = speed * 0.05  # 50ms 定时器
            rect = self._screen_rect()
            s = self._current_size()
            new_x = self.x() + self._direction * step
            # 左右边界:越界则夹回边界并反向
            if new_x < rect.left():
                new_x = rect.left()
                self._direction = 1
            elif new_x + s > rect.right():
                new_x = rect.right() - s
                self._direction = -1
            # 上下边界:若窗口在屏幕外(如曾被拖出),拉回范围内
            new_y = self.y()
            if new_y < rect.top():
                new_y = rect.top()
            elif new_y + s > rect.bottom():
                new_y = rect.bottom() - s
            self.move(round(new_x), round(new_y))

    def _follow_docked_window(self) -> None:
        """跟踪被吸附窗口:移动则跟随;关闭/最小化/最大化/全屏则脱离吸附。"""
        if not self._docked or self._docked_target is None:
            return
        try:
            hwnd, _ = self._docked_target
            # 窗口已关闭或最小化 → 脱离
            if not win32_util.is_window_visible(hwnd) or win32_util.is_iconic(hwnd):
                self._exit_dock()
                return
            # 最大化 / 全屏 → 脱离
            if win32_util.is_maximized(hwnd) or win32_util.is_fullscreen(hwnd):
                self._exit_dock()
                return
            rect = win32_util.get_window_rect(hwnd)
            if rect is None:
                self._exit_dock()
                return
            # 窗口位置/大小变化 → 角色跟随,保持底部对齐窗口顶边
            if rect != self._docked_target[1]:
                self._docked_target = (hwnd, rect)
                self._move_to_dock_pos(rect)
        except Exception:
            # Win32 调用失败(如句柄失效)时安全脱离,避免定时器刷屏
            self._exit_dock()

    def _on_measure_ready(self, _payload) -> None:
        """后台测量完成后(GUI 线程):若已吸附,按精确的画面比例重新对齐窗口顶边。"""
        if self._docked and self._docked_target is not None:
            self._move_to_dock_pos(self._docked_target[1])

    def _update_dock_after_drag(self) -> None:
        """拖动松手后:角色画面底部到窗口底部区间内任一点落在窗口上,即吸附到该窗口顶端。

        覆盖“角色悬空在窗口顶边上方”(画面底部未落进窗口)的情况——
        只要角色窗口底部或画面底部进入窗口,松手后都重新坐下。
        """
        s = self._current_size()
        dpr = self._dpr()
        bottom_ratio, _ = self._behavior.content_ratios(self.cfg.skin, self._action)
        py_bottom = self.y() + bottom_ratio * s + 4   # 画面底部(逻辑)
        py_win = self.y() + s                          # 窗口底部(逻辑)
        own = int(self.winId())
        for fy in (0.0, 0.5, 1.0):
            py_log = py_bottom + (py_win - py_bottom) * fy
            py_phys = round(py_log * dpr)
            for fx in (0.20, 0.35, 0.50, 0.65, 0.80):
                px_phys = round((self.x() + fx * s) * dpr)
                found = win32_util.find_window_below(px_phys, py_phys, own)
                if found:
                    hwnd, rect_phys = found
                    if not self._docked:
                        self._enter_dock(hwnd, rect_phys)
                    return
        if self._docked:
            self._exit_dock()

    def _move_to_dock_pos(self, win_rect: tuple[int, int, int, int]) -> None:
        """吸附到窗口顶端:画面底部踩窗口顶边(坐/睡姿按皮肤下沉),水平位置跟随拖动。

        win_rect 为 Win32 物理坐标,先转 Qt 逻辑坐标。
        """
        dpr = self._dpr()
        left = win_rect[0] / dpr
        top = win_rect[1] / dpr
        right = win_rect[2] / dpr
        s = self._current_size()
        bottom_ratio, center_ratio = self._behavior.content_ratios(self.cfg.skin, self._action)
        # DOCK_DY 是 100% 尺寸下的物理像素偏移:按窗口缩放比例自适应,再转逻辑像素
        dock_dy = DOCK_DY.get((self.cfg.skin, self._action), 0) * (s / BASE_SIZE) / dpr
        new_y = round(top - bottom_ratio * s + dock_dy)
        mid_x = (left + right) / 2
        # 首次吸附:记录画面中心相对窗口顶边中点的水平偏移(跟随拖动位置)
        if self._dock_x_offset is None:
            center_log = self.x() + center_ratio * s
            self._dock_x_offset = center_log - mid_x
        # 保持偏移并夹在窗口范围内(留 10% 边距)
        margin = 0.10 * s
        new_center = mid_x + self._dock_x_offset
        new_center = max(left + margin, min(right - margin, new_center))
        new_x = round(new_center - center_ratio * s)
        self.move(new_x, new_y)

    def _enter_dock(self, hwnd: int, win_rect: tuple[int, int, int, int]) -> None:
        self._docked = True
        self._docked_target = (hwnd, win_rect)
        self._dock_x_offset = None  # 重新记录相对偏移
        self._behavior.set_docked(True)
        self._move_to_dock_pos(win_rect)

    def _exit_dock(self) -> None:
        self._docked = False
        self._docked_target = None
        self._dock_x_offset = None
        self._behavior.set_docked(False)

    # ---------- 空闲语音 ----------
    def _schedule_idle_voice(self) -> None:
        if not self.cfg.idle_voice_enabled:
            return
        self._idle_timer.start(random.randint(IDLE_VOICE_MIN_S, IDLE_VOICE_MAX_S) * 1000)

    def _on_idle_voice(self) -> None:
        if not self.cfg.idle_voice_enabled:
            return
        if not self._audio.is_playing():
            name = random.choice(IDLE_VOICE_POOL)
            self._audio.play(name)
        self._schedule_idle_voice()

    # ---------- 启动播报 ----------
    def _play_startup_voices(self) -> None:
        now = datetime.date.today()
        month, day = now.month, now.day
        is_birthday = self.cfg.is_birthday_today(month, day)
        in_anniv = Config.in_date_range(month, day, ANNIVERSARY)
        in_newyear = Config.in_date_range(month, day, NEW_YEAR)

        if is_birthday:
            QTimer.singleShot(800, lambda: self._audio.play("生日"))
            if in_anniv:
                QTimer.singleShot(5800, lambda: self._audio.play("周年庆典"))
            elif in_newyear:
                QTimer.singleShot(5800, lambda: self._audio.play("新年祝福"))
        elif in_anniv:
            QTimer.singleShot(800, lambda: self._audio.play("周年庆典"))
        elif in_newyear:
            QTimer.singleShot(800, lambda: self._audio.play("新年祝福"))

    # ---------- 关闭 ----------
    def closeEvent(self, event) -> None:  # noqa: N802
        self.cfg.x = self.x()
        self.cfg.y = self.y()
        self.cfg.save()
        self._player.stop()
        super().closeEvent(event)
