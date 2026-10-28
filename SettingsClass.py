"""Persistent settings and leaderboard storage.

Both files are treated as untrusted input.  Missing, truncated or hand-edited
files fall back to defaults instead of raising.
"""

from __future__ import annotations

import copy
import datetime
import os

from utils import clamp, config_dir, read_json, write_json


def _settings_path():
    """Resolve at call time so SPACEGAME_CONFIG_DIR can be set late (tests)."""
    return os.path.join(config_dir(), "settings.json")


def _scores_path():
    return os.path.join(config_dir(), "scores.json")


SETTINGS_PATH = _settings_path()
SCORES_PATH = _scores_path()

DEFAULT_SETTINGS = {
    "version": 4,
    "music_volume": 0.55,
    "sfx_volume": 0.7,
    "muted": False,
    "fullscreen": False,
    "language": "uk",
    "mode": "normal",
    "screen_shake": True,
    "show_fps": False,
    "ship": "fighter",
    "effects_quality": 2,
    "reduced_flash": False,
    "auto_pause": True,
}


def _as_float(value, default, low=0.0, high=1.0):
    if isinstance(value, bool):
        return default
    try:
        return clamp(float(value), low, high)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default):
    return value if isinstance(value, bool) else default


def _as_language(value, default="uk"):
    return value if value in ("uk", "en") else default


def _as_mode(value, default="normal"):
    return value if value in ("normal", "meme") else default


def _as_ship(value, default="fighter"):
    from GameData import SHIP_ORDER
    return value if value in SHIP_ORDER else default


def _as_quality(value, default=2):
    if isinstance(value, bool):
        return default
    try:
        return max(0, min(2, int(value)))
    except (TypeError, ValueError):
        return default


class Settings:
    """Mutable settings object with crash-proof loading/saving."""

    def __init__(self, data=None):
        data = data if isinstance(data, dict) else {}
        self.version = 4
        self.music_volume = _as_float(data.get("music_volume"), DEFAULT_SETTINGS["music_volume"])
        self.sfx_volume = _as_float(data.get("sfx_volume"), DEFAULT_SETTINGS["sfx_volume"])
        self.muted = _as_bool(data.get("muted"), DEFAULT_SETTINGS["muted"])
        self.fullscreen = _as_bool(data.get("fullscreen"), DEFAULT_SETTINGS["fullscreen"])
        self.language = _as_language(data.get("language"))
        self.mode = _as_mode(data.get("mode"))
        self.screen_shake = _as_bool(data.get("screen_shake"), DEFAULT_SETTINGS["screen_shake"])
        self.show_fps = _as_bool(data.get("show_fps"), DEFAULT_SETTINGS["show_fps"])
        self.ship = _as_ship(data.get("ship"), DEFAULT_SETTINGS["ship"])
        self.effects_quality = _as_quality(
            data.get("effects_quality"), DEFAULT_SETTINGS["effects_quality"]
        )
        self.reduced_flash = _as_bool(
            data.get("reduced_flash"), DEFAULT_SETTINGS["reduced_flash"]
        )
        self.auto_pause = _as_bool(data.get("auto_pause"), DEFAULT_SETTINGS["auto_pause"])

    @classmethod
    def load(cls, path=None):
        path = path or _settings_path()
        raw = read_json(path, {})
        settings = cls(raw)
        if not raw:
            # Missing or unreadable file: create a valid one, but never fail.
            settings.save(path)
        return settings

    def as_dict(self):
        return {
            "version": self.version,
            "music_volume": round(self.music_volume, 3),
            "sfx_volume": round(self.sfx_volume, 3),
            "muted": self.muted,
            "fullscreen": self.fullscreen,
            "language": self.language,
            "mode": self.mode,
            "screen_shake": self.screen_shake,
            "show_fps": self.show_fps,
            "ship": self.ship,
            "effects_quality": self.effects_quality,
            "reduced_flash": self.reduced_flash,
            "auto_pause": self.auto_pause,
        }

    def save(self, path=None):
        return write_json(path or _settings_path(), self.as_dict())

    def copy(self):
        return Settings(copy.deepcopy(self.as_dict()))

    def toggle_language(self):
        self.language = "en" if self.language == "uk" else "uk"
        return self.language

    def cycle_language(self, step=1):
        languages = ("uk", "en")
        try:
            index = languages.index(self.language)
        except ValueError:
            index = 0
        self.language = languages[(index + step) % len(languages)]
        return self.language


class Leaderboard:
    """Top ten scores for each game mode."""

    def __init__(self, data=None, path=None):
        self.path = path or _scores_path()
        data = data if isinstance(data, dict) else {}
        # Tolerate the old flat format by moving it into the normal board.
        if "scores" in data and "normal" not in data:
            data = {"normal": data.get("scores", []), "meme": []}
        self.boards = {
            "normal": self._clean(data.get("normal")),
            "meme": self._clean(data.get("meme")),
        }

    @staticmethod
    def _clean(entries):
        cleaned = []
        if not isinstance(entries, list):
            return cleaned
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                score = max(0, int(entry.get("score", 0)))
            except (TypeError, ValueError):
                continue
            try:
                wave = max(1, int(entry.get("wave", 1)))
            except (TypeError, ValueError):
                wave = 1
            try:
                kills = max(0, int(entry.get("kills", 0)))
            except (TypeError, ValueError):
                kills = 0
            date = entry.get("date", "")
            if not isinstance(date, str):
                date = ""
            cleaned.append({"score": score, "wave": wave, "kills": kills, "date": date[:19]})
        cleaned.sort(key=lambda item: item["score"], reverse=True)
        return cleaned[:10]

    @classmethod
    def load(cls, path=None):
        path = path or _scores_path()
        return cls(read_json(path, {}), path=path)

    def best(self, mode):
        board = self.boards.get(mode) or []
        return board[0]["score"] if board else 0

    def board(self, mode):
        return self.boards.get(mode if mode in self.boards else "normal", [])

    def add(self, mode, score, wave, kills):
        """Add a result and return (rank_or_None, is_new_record, best_before)."""
        mode = mode if mode in self.boards else "normal"
        score = max(0, int(score))
        best_before = self.best(mode)
        if score <= 0:
            return None, False, best_before
        entry = {
            "score": score,
            "wave": max(1, int(wave)),
            "kills": max(0, int(kills)),
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        board = self.boards[mode]
        board.append(entry)
        board.sort(key=lambda item: item["score"], reverse=True)
        del board[10:]
        try:
            rank = board.index(entry) + 1
        except ValueError:
            rank = None
        self.save()
        return rank, score > best_before, best_before

    def as_dict(self):
        return {"version": 2, "normal": self.boards["normal"], "meme": self.boards["meme"]}

    def save(self):
        return write_json(self.path, self.as_dict())
