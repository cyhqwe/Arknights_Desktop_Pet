"""PyAV 视频解码线程:循环解码 VP8 webm,绿幕抠图,双缓冲发布 RGBA QImage。

内存优化:
- 线程侧复用两块 numpy 缓冲(渲染/发布交替),不再每帧新建数组,消除 30fps
  下每秒上百 MB 的分配;
- UI 侧在锁内拷贝当前缓冲(4MB/帧),避免跨线程写竞争;
- 切换视频源时旧容器立即关闭(av.open 的 with 块),动作资源即时释放。
"""
from __future__ import annotations

import time

import av
import numpy as np
from PySide6.QtCore import QMutex, QMutexLocker, QThread, QObject
from PySide6.QtGui import QImage

# 绿色色键参数(背景为纯绿 #00FF00):
# greenness = g - max(r, b)。greenness >= GREEN_K1 视为背景(alpha=0),
# <= GREEN_K0 完全保留(alpha=255),之间线性过渡。
GREEN_K0 = 40
GREEN_K1 = 110


def _render_into(frame: av.VideoFrame, buf: np.ndarray) -> None:
    """把一帧 yuv420p 绿幕抠图后写入 buf(HxWx4 RGBA,原地复用)。

    含“去绿边”:半透明过渡像素的绿色分量压到不高于红蓝,
    消除角色轮廓的绿色光晕。
    """
    rgb = frame.to_ndarray(format="rgb24")  # HxWx3 uint8
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    greenness = g - np.maximum(r, b)
    alpha = np.clip((GREEN_K1 - greenness) * (255.0 / (GREEN_K1 - GREEN_K0)), 0, 255).astype(np.uint8)
    buf[..., 0] = rgb[..., 0]
    buf[..., 1] = rgb[..., 1]
    buf[..., 2] = rgb[..., 2]
    buf[..., 3] = alpha
    # 去绿边
    edge = (alpha > 0) & (alpha < 255)
    if edge.any():
        re = buf[..., 0][edge].astype(np.int16)
        ge = buf[..., 1][edge].astype(np.int16)
        be = buf[..., 2][edge].astype(np.int16)
        buf[..., 1][edge] = np.minimum(ge, np.maximum(re, be)).astype(np.uint8)


class _DecodeThread(QThread):
    def __init__(self, owner: "VideoPlayer") -> None:
        super().__init__(owner)
        self._owner = owner

    def run(self) -> None:  # noqa: D102
        owner = self._owner
        while not owner._stop:
            src = owner._source
            if not src:
                time.sleep(0.02)
                continue
            try:
                with av.open(src) as container:
                    stream = container.streams.video[0]
                    anchor = time.monotonic()
                    first_pts = None
                    for frame in container.decode(stream):
                        if owner._stop or owner._source != src:
                            break
                        pts = frame.pts
                        tb = float(frame.time_base)
                        if first_pts is None:
                            first_pts = pts
                            anchor = time.monotonic()
                            delay = 0.0
                        else:
                            delay = (pts - first_pts) * tb
                        owner._publish(frame)
                        target = anchor + delay
                        while not owner._stop and owner._source == src:
                            now = time.monotonic()
                            if now >= target:
                                break
                            time.sleep(min(0.005, target - now))
            except Exception:
                # 文件损坏或解码失败:短暂暂停后重试,避免死循环刷屏
                time.sleep(0.5)


class VideoPlayer(QObject):
    """管理解码线程与双帧缓冲。set_source() 可随时切换,旧资源立即释放。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mutex = QMutex()
        self._source: str | None = None
        self._stop = False
        self._buffers: list[np.ndarray | None] = [None, None]
        self._latest_idx = 0
        self._write_idx = 1
        self._thread = _DecodeThread(self)
        self._thread.start()

    def set_source(self, path: str) -> None:
        with QMutexLocker(self._mutex):
            self._source = path

    def latest_frame(self) -> QImage | None:
        """返回当前最新帧的拷贝(锁内拷贝,线程不会写同一缓冲)。"""
        with QMutexLocker(self._mutex):
            buf = self._buffers[self._latest_idx]
            if buf is None:
                return None
            h, w = buf.shape[:2]
            img = QImage(buf.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
            return img.copy()

    def _publish(self, frame: av.VideoFrame) -> None:
        """渲染到写缓冲并交换(锁内完成)。"""
        with QMutexLocker(self._mutex):
            buf = self._buffers[self._write_idx]
            h, w = frame.height, frame.width
            if buf is None or buf.shape[0] != h or buf.shape[1] != w:
                buf = np.empty((h, w, 4), dtype=np.uint8)
                self._buffers[self._write_idx] = buf
            _render_into(frame, buf)
            self._latest_idx, self._write_idx = self._write_idx, self._latest_idx

    def stop(self) -> None:
        self._stop = True
        self._thread.wait(3000)
