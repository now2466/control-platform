from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Literal

from PIL import Image

from pinky_control_center.models import CameraFrame

CameraQuality = Literal["low", "default", "high"]
QUALITY_FPS: dict[CameraQuality, int] = {"low": 5, "default": 10, "high": 15}
QUALITY_SIZE: dict[CameraQuality, tuple[int, int]] = {"low": (320, 240), "default": (640, 480), "high": (1280, 720)}
VALID_ROBOT_IDS = frozenset(("robot_1", "robot_2"))


def encode_camera_frame(frame: CameraFrame) -> bytes:
    """Encode the documented metadata-length + JSON + JPEG WebSocket frame."""
    metadata = json.dumps({
        "frame_id": frame.frame_id,
        "captured_at": frame.captured_at.isoformat() if frame.captured_at else None,
        "received_at": frame.received_at.isoformat(),
        "width": frame.width,
        "height": frame.height,
    }, separators=(",", ":")).encode("utf-8")
    return len(metadata).to_bytes(4, "big") + metadata + frame.jpeg


class CameraService:
    """Fans each camera source out to independent latest-frame viewer queues."""

    def __init__(self, frame_source: Callable[[str], CameraFrame | None], clock: Callable[[], float] = time.monotonic) -> None:
        self._frame_source = frame_source
        self._clock = clock
        self._viewers: dict[str, set[_Viewer]] = {robot_id: set() for robot_id in VALID_ROBOT_IDS}
        self._workers: dict[str, asyncio.Task[None]] = {}

    @property
    def worker_count(self) -> int:
        return len(self._workers)

    def viewer_count(self, robot_id: str) -> int:
        return len(self._viewers.get(robot_id, ()))

    @asynccontextmanager
    async def subscribe(self, robot_id: str, quality: CameraQuality) -> AsyncIterator[asyncio.Queue[CameraFrame]]:
        if robot_id not in VALID_ROBOT_IDS:
            raise ValueError("unknown robot")
        viewer = _Viewer(quality)
        self._viewers[robot_id].add(viewer)
        self._ensure_worker(robot_id)
        try:
            yield viewer.queue
        finally:
            self._viewers[robot_id].discard(viewer)
            if not self._viewers[robot_id]:
                task = self._workers.pop(robot_id, None)
                if task:
                    task.cancel()

    def _ensure_worker(self, robot_id: str) -> None:
        if robot_id not in self._workers:
            self._workers[robot_id] = asyncio.create_task(self._produce(robot_id))

    async def _produce(self, robot_id: str) -> None:
        try:
            while self._viewers[robot_id]:
                frame = self._frame_source(robot_id)
                if frame is not None:
                    self.publish(frame)
                await asyncio.sleep(1 / QUALITY_FPS["high"])
        except asyncio.CancelledError:
            raise

    def publish(self, frame: CameraFrame) -> None:
        now = self._clock()
        for viewer in tuple(self._viewers[frame.robot_id]):
            if now - viewer.last_sent < 1 / QUALITY_FPS[viewer.quality]:
                continue
            viewer.last_sent = now
            rendered = _resize(frame, viewer.quality)
            if viewer.queue.full():
                viewer.queue.get_nowait()
            viewer.queue.put_nowait(rendered)

    async def close(self) -> None:
        tasks = list(self._workers.values())
        self._workers.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class _Viewer:
    def __init__(self, quality: CameraQuality) -> None:
        self.quality = quality
        self.queue: asyncio.Queue[CameraFrame] = asyncio.Queue(maxsize=1)
        self.last_sent = float("-inf")


def _resize(frame: CameraFrame, quality: CameraQuality) -> CameraFrame:
    target_width, target_height = QUALITY_SIZE[quality]
    if frame.width <= target_width and frame.height <= target_height:
        return frame
    with Image.open(BytesIO(frame.jpeg)) as image:
        image.thumbnail((target_width, target_height))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        return frame.model_copy(update={"width": image.width, "height": image.height, "jpeg": buffer.getvalue()})
