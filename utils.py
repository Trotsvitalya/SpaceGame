"""Small shared helpers for SpaceGame.

The game logic always runs on a fixed virtual canvas (1280x720), independent of
the actual window size.  This module also holds safe JSON helpers so a broken
settings/leaderboard file can never crash the game.
"""

from __future__ import annotations

import json
import math
import os
import tempfile

VW = 1280
VH = 720
ROOT = os.path.dirname(os.path.abspath(__file__))


def clamp(value, low, high):
    return low if value < low else high if value > high else value


def lerp(a, b, t):
    return a + (b - a) * t


def approach(current, target, delta):
    if current < target:
        return min(current + delta, target)
    if current > target:
        return max(current - delta, target)
    return target


def normalize(x, y):
    length = math.hypot(x, y)
    if length <= 0.00001:
        return 0.0, 0.0
    return x / length, y / length


def circle_hit(x1, y1, r1, x2, y2, r2):
    dx = x1 - x2
    dy = y1 - y2
    reach = r1 + r2
    return dx * dx + dy * dy <= reach * reach


def segment_circle_hit(x1, y1, x2, y2, cx, cy, radius):
    """Return True when the segment (x1,y1)-(x2,y2) touches a circle.

    Used for fast bullets so they cannot tunnel through enemies on a slow
    frame.  All values are in virtual pixels.
    """
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.00001:
        return circle_hit(x1, y1, 0, cx, cy, radius)
    t = ((cx - x1) * dx + (cy - y1) * dy) / length_sq
    t = clamp(t, 0.0, 1.0)
    nx = x1 + dx * t
    ny = y1 + dy * t
    ddx = nx - cx
    ddy = ny - cy
    return ddx * ddx + ddy * ddy <= radius * radius


def config_dir():
    """Directory used for settings.json / scores.json.

    ``SPACEGAME_CONFIG_DIR`` lets the automated tests use a temporary folder
    without touching the player's real configuration.
    """
    override = os.environ.get("SPACEGAME_CONFIG_DIR")
    if override:
        try:
            os.makedirs(override, exist_ok=True)
        except OSError:
            return ROOT
        return override
    return ROOT


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError, TypeError):
        return default


def write_json(path, data):
    """Atomically write JSON, returning False instead of raising on failure."""
    directory = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".spacegame-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
            return True
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except (OSError, ValueError, TypeError):
        return False


def format_score(value):
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def format_time(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
