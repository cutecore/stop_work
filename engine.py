"""单一电量：操作 15 分钟耗光，停手 30 分钟充满。"""

from __future__ import annotations

import math
from dataclasses import dataclass

WORK_MINUTES = 15
REST_MINUTES = 30
WORK_SECONDS = WORK_MINUTES * 60
REST_SECONDS = REST_MINUTES * 60
# 停手没满这段时间，仍算在使用电脑。
IDLE_AFTER = 3.0
# 低于此电量视为掏空（仍可继续操作，但会告警）。
EMPTY_EPS = 0.002
FULL_EPS = 0.002


def format_duration(seconds: float) -> str:
    """倒计时用进位，避免还剩零点几秒时提前显示 00:00。"""
    if not math.isfinite(seconds) or seconds <= 0:
        return "00:00"
    total = int(math.ceil(seconds - 1e-9))
    return _format_total(total)


def format_elapsed(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds <= 0:
        return "00:00"
    total = int(math.floor(seconds + 1e-9))
    return _format_total(total)


def _format_total(total: int) -> str:
    total = max(0, total)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def split_interval(
    prev: float,
    now: float,
    last_input: float,
    idle_after: float = IDLE_AFTER,
) -> tuple[float, float]:
    """把一段时间拆成「仍算在操作」和「已经离开」。

    长时间没有采样时，一次输入只能证明其后 idle_after 秒在操作，
    更早的空档算作休息，避免睡眠或卡住被记成连续工作。
    """
    dt = now - prev
    if dt <= 0:
        return 0.0, 0.0
    active_until = last_input + idle_after
    if dt <= idle_after:
        if active_until <= prev:
            active = 0.0
        else:
            active = min(now, active_until) - prev
        active = min(max(0.0, active), dt)
        return active, dt - active

    if active_until <= prev:
        active = 0.0
    elif last_input >= now - idle_after:
        active = idle_after
    else:
        active = min(idle_after, max(0.0, min(now, active_until) - prev))
    active = min(max(0.0, active), dt)
    return active, dt - active


@dataclass(frozen=True)
class View:
    kind: str
    level: float
    work_goal: float
    rest_goal: float

    @property
    def battery(self) -> float:
        return self.level

    @property
    def hero_seconds(self) -> float:
        if self.kind == "rest":
            return max(0.0, (1.0 - self.level) * self.rest_goal)
        return max(0.0, self.level * self.work_goal)


class Engine:
    def __init__(
        self,
        work_seconds: float = WORK_SECONDS,
        rest_seconds: float = REST_SECONDS,
        idle_after: float = IDLE_AFTER,
    ) -> None:
        self.work_seconds = float(work_seconds)
        self.rest_seconds = float(rest_seconds)
        self.idle_after = float(idle_after)
        self.battery = 1.0
        self.last_input = 0.0
        self._last_now: float | None = None
        self._emptied = False

    def start(self, now: float, battery: float = 1.0) -> None:
        self.battery = max(0.0, min(1.0, float(battery)))
        self.last_input = now - self.idle_after
        self._last_now = now
        self._emptied = False

    def poll(self, now: float, last_seen: float | None) -> None:
        if last_seen is not None and last_seen > self.last_input:
            self.last_input = last_seen
        if self._last_now is None:
            self._last_now = now
            return
        prev = self._last_now
        self._last_now = now
        active, idle = split_interval(prev, now, self.last_input, self.idle_after)
        self.advance(active, idle)

    def advance(self, active_seconds: float, idle_seconds: float = 0.0) -> None:
        self._apply_active(max(0.0, active_seconds))
        self._apply_idle(max(0.0, idle_seconds))

    def consume_emptied(self) -> bool:
        hit = self._emptied
        self._emptied = False
        return hit

    def view(self, now: float) -> View:
        level = self.battery
        active = (now - self.last_input) < self.idle_after
        if active:
            kind = "empty" if level <= EMPTY_EPS else "work"
        elif level >= 1.0 - FULL_EPS:
            kind = "paused"
        else:
            kind = "rest"
        return View(
            kind=kind,
            level=level,
            work_goal=self.work_seconds,
            rest_goal=self.rest_seconds,
        )

    def _apply_active(self, seconds: float) -> None:
        if seconds <= 0 or self.work_seconds <= 0:
            return
        before = self.battery
        self.battery = max(0.0, self.battery - seconds / self.work_seconds)
        if before > EMPTY_EPS and self.battery <= EMPTY_EPS:
            self.battery = 0.0
            self._emptied = True

    def _apply_idle(self, seconds: float) -> None:
        if seconds <= 0 or self.rest_seconds <= 0:
            return
        self.battery = min(1.0, self.battery + seconds / self.rest_seconds)
        if self.battery >= 1.0 - FULL_EPS:
            self.battery = 1.0
