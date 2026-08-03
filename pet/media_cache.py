"""动画元数据缓存:时长 + 画面内容比例。

测量一次后写入本地 JSON;后续启动校验文件未变则直接读缓存,
不再后台解码(释放测量内存、启动即时可用)。文件变化(增删改)自动重测。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .config import RES_DIR, SKINS

CACHE_PATH = RES_DIR / "_pet_media_cache.json"


def _file_sigs() -> dict[str, tuple[int, float]]:
    """当前所有动画文件的 (大小, 修改时间) 签名。"""
    sigs: dict[str, tuple[int, float]] = {}
    for skin, actions in SKINS.items():
        for action, fname in actions.items():
            p = RES_DIR / fname
            try:
                st = p.stat()
                sigs[f"{skin}:{action}"] = (st.st_size, st.st_mtime)
            except OSError:
                sigs[f"{skin}:{action}"] = (-1, -1.0)
    return sigs


def load() -> tuple[dict[str, float], dict[tuple[str, str], tuple[float, float]]] | None:
    """缓存有效(文件未变)则返回 (durations, content),否则 None。"""
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        saved_sigs = {k: (v[0], v[1]) for k, v in data["files"].items()}
        if saved_sigs != _file_sigs():
            return None
        durations = {k: float(v) for k, v in data["durations"].items()}
        content = {
            (k.split(":", 1)[0], k.split(":", 1)[1]): (float(v[0]), float(v[1]))
            for k, v in data["content"].items()
        }
        return durations, content
    except Exception:
        return None


def save(durations: dict[str, float], content: dict[tuple[str, str], tuple[float, float]]) -> None:
    """把测量结果连同文件签名写入缓存。"""
    data = {
        "files": _file_sigs(),
        "durations": durations,
        "content": {f"{s}:{a}": [b, c] for (s, a), (b, c) in content.items()},
    }
    try:
        CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def invalidate() -> None:
    try:
        CACHE_PATH.unlink()
    except OSError:
        pass
