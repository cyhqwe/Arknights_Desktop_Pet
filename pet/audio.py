"""语音播放:Windows 原生 winsound 播放 wav,打断式播放,支持双语言切换。

为什么不用 QSoundEffect:Qt 6.11 的 FFmpeg 多媒体后端在某些 Windows 机器上
会出现状态正常(isPlaying=True)但实际无声的问题。winsound 走系统 API,
对 PCM wav 播放绝对可靠。本项目仅面向 Windows,故直接使用 winsound。
"""
from __future__ import annotations

import time
import wave
import winsound

from PySide6.QtCore import QObject

from . import pitch
from .config import DEFAULT_LANG, RES_DIR, VOICE_LANGS, VOICE_NAMES, voice_filename

# 绝对主角皮肤的搞笑腔调:变调比例(>1 音调升高)与变调文件缓存目录
PITCH_RATIO = 1.25
PITCHED_DIR = RES_DIR / "_pitched"


class AudioManager(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # 时长缓存:{(语言, 语音名): 秒}
        self._durations: dict[tuple[str, str], float] = {}
        for lang in VOICE_LANGS:
            for name in VOICE_NAMES:
                fname = voice_filename(name, lang)
                try:
                    with wave.open(str(RES_DIR / fname), "rb") as w:
                        self._durations[(lang, name)] = w.getnframes() / w.getframerate()
                except Exception:
                    self._durations[(lang, name)] = 3.0
        self._current: str | None = None
        self._until: float = 0.0
        self._skin = "超新星"
        self._lang: str = DEFAULT_LANG

    def set_skin(self, skin: str) -> None:
        """切换皮肤:绝对主角语音使用升高音调的搞笑腔调。"""
        self._skin = skin

    def set_language(self, lang: str) -> None:
        """切换语音语言:JP 日文 / zh-CN 中文。"""
        if lang in VOICE_LANGS:
            self._lang = lang
        self.stop()  # 切换语言时停掉正在播放的语音

    def language(self) -> str:
        return self._lang

    def _voice_path(self, name: str):
        """当前皮肤/语言对应的语音文件(绝对主角用变调版本,惰性生成)。"""
        base = RES_DIR / voice_filename(name, self._lang)
        if self._skin != "绝对主角":
            return base
        dst = PITCHED_DIR / f"{name}-{self._lang}_pitched.wav"
        if not dst.exists():
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                pitch.pitch_shift(base, dst, PITCH_RATIO)
            except Exception:
                return base  # 变调失败则回退原声
        return dst

    def play(self, name: str) -> None:
        """打断式播放指定语音。未知名称则忽略。"""
        if (self._lang, name) not in self._durations:
            return
        self.stop()
        winsound.PlaySound(
            str(self._voice_path(name)),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
        self._current = name
        self._until = time.monotonic() + self.duration_of(name)

    def stop(self) -> None:
        winsound.PlaySound(None, winsound.SND_PURGE)
        self._current = None
        self._until = 0.0

    def is_playing(self) -> bool:
        return self._current is not None and time.monotonic() < self._until

    def current_name(self) -> str | None:
        return self._current if self.is_playing() else None

    def duration_of(self, name: str) -> float:
        """当前语言下语音时长(秒),未知名称返回 0。"""
        return self._durations.get((self._lang, name), 0.0)
