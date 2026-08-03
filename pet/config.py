"""配置读写:生日、皮肤、置顶、大小、窗口位置等,持久化为 JSON。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# 项目根目录(本文件位于 <root>/pet/config.py)
ROOT_DIR = Path(__file__).resolve().parent.parent
RES_DIR = ROOT_DIR / "resources" / "Wis'adel"
CONFIG_PATH = ROOT_DIR / "config.json"

DEFAULT_SIZE_PERCENT = 100
SIZE_PERCENTS = [50, 75, 100, 125, 150, 200, 250, 300]

# 皮肤定义:名称 -> 动作文件模板(动作名 -> 文件名)
SKIN_ACTIONS = ("Interact", "Move", "Relax", "Sit", "Sleep", "Special")
SKINS = {
    "超新星": {a: f"维什戴尔-超新星-基建-{a}-x1.webm" for a in SKIN_ACTIONS},
    "绝对主角": {a: f"维什戴尔-绝对主角-基建-{a}-x1.webm" for a in SKIN_ACTIONS},
}
SKIN_NAMES = list(SKINS.keys())

# 语音:双语言(JP 日文原版 / zh-CN 中文版),文件命名 {语音名}-{语言}.wav
VOICE_LANGS = ("JP", "zh-CN")
VOICE_NAMES = (
    "生日", "周年庆典", "新年祝福", "问候",
    "交谈1", "交谈2", "交谈3", "戳一下", "信赖触摸", "任命助理", "闲置",
)
DEFAULT_LANG = "JP"


def voice_filename(name: str, lang: str) -> str:
    return f"{name}-{lang}.wav"

# 周年庆典 / 新年 日期区间 (月, 起始日, 结束日)
ANNIVERSARY = (5, 1, 4)   # 5月1日-5月4日
NEW_YEAR = (1, 1, 4)      # 1月1日-1月4日

# 坐/睡姿吸附到窗口顶部时的垂直偏移(单位:**物理屏幕像素**,以 100% 尺寸为基准;
# 应用时按 DPR 换算为 Qt 逻辑像素,并按窗口缩放比例自适应;正值=向下沉入窗口)。
# 效果:角色“坐/睡”在窗口顶边上,按缩放保持同样比例。
DOCK_DY = {
    ("超新星", "Sit"): 50,
    ("超新星", "Sleep"): 20,
    ("绝对主角", "Sit"): 20,
    ("绝对主角", "Sleep"): 20,
}

# 空闲随机语音池(排除 生日/周年庆典/新年祝福)
IDLE_VOICE_POOL = ["交谈1", "交谈2", "交谈3", "任命助理", "信赖触摸", "戳一下", "问候", "闲置"]


@dataclass
class Config:
    birthday: str = ""               # "MM-DD",空表示未设置
    skin: str = "超新星"
    always_on_top: bool = True
    size_percent: int = DEFAULT_SIZE_PERCENT
    x: int | None = None             # 窗口位置,None 表示首次启动自动放置
    y: int | None = None
    idle_voice_enabled: bool = True  # 空闲随机语音开关
    language: str = DEFAULT_LANG     # 语音语言: JP / zh-CN
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            if CONFIG_PATH.exists():
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if data.get("birthday"):
                    cfg.birthday = str(data["birthday"])
                if data.get("skin") in SKIN_NAMES:
                    cfg.skin = data["skin"]
                if isinstance(data.get("always_on_top"), bool):
                    cfg.always_on_top = data["always_on_top"]
                if data.get("size_percent") in SIZE_PERCENTS:
                    cfg.size_percent = data["size_percent"]
                if isinstance(data.get("x"), (int, float)):
                    cfg.x = int(data["x"])
                if isinstance(data.get("y"), (int, float)):
                    cfg.y = int(data["y"])
                if isinstance(data.get("idle_voice_enabled"), bool):
                    cfg.idle_voice_enabled = data["idle_voice_enabled"]
                if data.get("language") in VOICE_LANGS:
                    cfg.language = data["language"]
                if isinstance(data.get("extra"), dict):
                    cfg.extra = data["extra"]
        except Exception:
            pass  # 配置损坏时使用默认值
        return cfg

    def save(self) -> None:
        data = {
            "birthday": self.birthday,
            "skin": self.skin,
            "always_on_top": self.always_on_top,
            "size_percent": self.size_percent,
            "x": self.x,
            "y": self.y,
            "idle_voice_enabled": self.idle_voice_enabled,
            "language": self.language,
            "extra": self.extra,
        }
        try:
            CONFIG_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def is_birthday_today(self, month: int, day: int) -> bool:
        if not self.birthday:
            return False
        try:
            m, d = (int(p) for p in self.birthday.split("-"))
        except ValueError:
            return False
        return m == month and d == day

    @staticmethod
    def in_date_range(month: int, day: int, spec: tuple) -> bool:
        m, start, end = spec
        return m == month and start <= day <= end
