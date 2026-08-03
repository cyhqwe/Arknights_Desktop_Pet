"""音频变调:wav PCM 线性插值重采样(音调升高,带轻微变速),生成新 wav。

用于“绝对主角”皮肤的搞笑腔调:ratio>1 音调升高(如 1.25 = +25%),
时长相应变短(变快),符合搞怪语气。仅依赖标准库 + numpy。
"""
from __future__ import annotations

import wave

import numpy as np


def pitch_shift(src: str, dst: str, ratio: float = 1.25) -> None:
    """把 src 的 wav 重采样生成 dst。ratio>1 音调升高。"""
    with wave.open(str(src), "rb") as w:
        params = w.getparams()
        nframes = w.getnframes()
        channels = params.nchannels
        data = np.frombuffer(w.readframes(nframes), dtype=np.int16).astype(np.float32)
    if channels > 1:
        data = data.reshape(-1, channels)

    n_out = max(1, int(nframes / ratio))
    idx = np.linspace(0, nframes - 1, n_out)
    x0 = idx.astype(np.int64)
    x1 = np.minimum(x0 + 1, nframes - 1)
    if channels > 1:
        frac = (idx - x0)[..., None]
    else:
        frac = idx - x0
    resampled = (data[x0] * (1 - frac) + data[x1] * frac).astype(np.int16)

    with wave.open(str(dst), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(resampled.tobytes())
