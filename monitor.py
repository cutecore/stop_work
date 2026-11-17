"""监听全局键鼠。只记录最后一次操作的时间，不拦截输入。"""

from __future__ import annotations

import threading
import time


class ActivityMonitor:
    def __init__(self) -> None:
        self.error: str | None = None
        self._last: float | None = None
        self._lock = threading.Lock()
        self._listeners: list[object] = []
        self._started = False

    def last_input(self) -> float | None:
        with self._lock:
            return self._last

    def mark(self) -> None:
        now = time.monotonic()
        with self._lock:
            last = self._last
            if last is not None and now - last < 0.05:
                return
            self._last = now

    def start(self) -> None:
        self._started = True
        try:
            from pynput import keyboard, mouse
        except Exception as exc:  # pragma: no cover - import failure is environmental
            self.error = str(exc)
            return
        try:
            mouse_listener = mouse.Listener(
                on_move=lambda *_args: self.mark(),
                on_click=lambda *_args: self.mark(),
                on_scroll=lambda *_args: self.mark(),
            )
            key_listener = keyboard.Listener(on_press=lambda *_args: self.mark())
            mouse_listener.start()
            key_listener.start()
        except Exception as exc:  # pragma: no cover
            self.error = str(exc)
            return
        self._listeners = [mouse_listener, key_listener]
        if not self.healthy():
            self.error = self.error or "listener stopped"

    def healthy(self) -> bool:
        if self.error:
            return False
        if not self._started:
            return True
        return all(bool(getattr(listener, "is_alive", lambda: False)()) for listener in self._listeners)

    def stop(self) -> None:
        for listener in self._listeners:
            stop = getattr(listener, "stop", None)
            if stop is None:
                continue
            try:
                stop()
            except Exception:
                pass
        self._listeners = []
