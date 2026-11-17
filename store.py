"""把电量和窗口位置留在本机，关掉之后也不会清掉。"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from engine import REST_SECONDS, WORK_SECONDS


def data_dir() -> Path:
    override = os.environ.get("STOPWORK_DIR")
    if override:
        path = Path(override)
    else:
        root = os.environ.get("APPDATA") or str(Path.home())
        path = Path(root) / "StopWork"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path() -> Path:
    return data_dir() / "state.json"


def log(message: str) -> None:
    try:
        path = data_dir() / "log.txt"
        if path.exists() and path.stat().st_size > 256_000:
            path.unlink(missing_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")
    except OSError:
        pass


def load_state() -> dict:
    raw: object = {}
    try:
        raw = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        raw = {}
    data = raw if isinstance(raw, dict) else {}
    return {
        "battery": _battery_from(data),
        "x": _optional_int(data.get("x")),
        "y": _optional_int(data.get("y")),
    }


def save_state(battery: float, x: int, y: int) -> None:
    payload = {
        "v": 3,
        "battery": max(0.0, min(1.0, float(battery))),
        "x": int(x),
        "y": int(y),
    }
    path = state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, path)


def _battery_from(data: dict) -> float:
    if "battery" in data:
        return _number(data.get("battery"), 0.0, 1.0)
    # 旧版：工作进度 + 休息亏欠 → 折成一格电量。
    work = _number(data.get("work_elapsed"), 0.0, WORK_SECONDS)
    debt = _number(data.get("debt"), 0.0, 100 * 3600)
    if WORK_SECONDS <= 0:
        level = 1.0
    else:
        level = 1.0 - work / WORK_SECONDS
    if debt > 0 and REST_SECONDS > 0:
        level -= min(1.0, debt / REST_SECONDS)
    return max(0.0, min(1.0, level))


def _number(value: object, low: float, high: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return low
    if not math.isfinite(number):
        return low
    return min(high, max(low, number))


def _optional_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not -100_000 <= number <= 100_000:
        return None
    return number
