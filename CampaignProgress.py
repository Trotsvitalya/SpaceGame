"""Campaign progress persistence, separate from settings and leaderboards.

The file is treated as untrusted input: unknown mission ids, wrong types and
truncated JSON are repaired to a valid state instead of crashing the game.
Completing a mission for the first time grants a permanent starting-salvage
bonus and unlocks the next mission.  Replays only update the best result.
"""

from __future__ import annotations

import os

from Balance import DIFFICULTY_ORDER
from CampaignData import MISSION_IDS, MISSION_BY_ID, next_mission_id
from GameData import SHIP_ORDER
from utils import config_dir, read_json, write_json

CAMPAIGN_VERSION = 1
MAX_SALVAGE_BONUS = 500


def _campaign_path():
    return os.path.join(config_dir(), "campaign.json")


def _clean_ids(values, allowed):
    cleaned = []
    if not isinstance(values, list):
        return cleaned
    for value in values:
        if isinstance(value, str) and value in allowed and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _clean_int(value, default=0, low=0, high=10 ** 9):
    if isinstance(value, bool):
        return default
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _clean_time(value, default=0.0):
    if isinstance(value, bool):
        return default
    try:
        return max(0.0, min(10 ** 7, float(value)))
    except (TypeError, ValueError):
        return default


class CampaignProgress:
    VERSION = CAMPAIGN_VERSION

    def __init__(self, data=None, path=None):
        self.path = path or _campaign_path()
        data = data if isinstance(data, dict) else {}

        self.completed = _clean_ids(data.get("completed"), MISSION_IDS)
        self.unlocked = _clean_ids(data.get("unlocked"), MISSION_IDS)
        if not self.unlocked:
            self.unlocked = [MISSION_IDS[0]]

        # A completed mission must be unlocked, and finishing a mission
        # unlocks the next one even if the save was hand-edited.
        for mission_id in self.completed:
            if mission_id not in self.unlocked:
                self.unlocked.append(mission_id)
            following = next_mission_id(mission_id)
            if following and following not in self.unlocked:
                self.unlocked.append(following)
        self.unlocked.sort(key=MISSION_IDS.index)

        self.best = {}
        raw_best = data.get("best")
        if isinstance(raw_best, dict):
            for mission_id, entry in raw_best.items():
                if mission_id not in MISSION_IDS or not isinstance(entry, dict):
                    continue
                self.best[mission_id] = {
                    "score": _clean_int(entry.get("score", 0)),
                    "kills": _clean_int(entry.get("kills", 0)),
                    "time": _clean_time(entry.get("time", 0.0)),
                }

        self.ship = data.get("ship") if data.get("ship") in SHIP_ORDER else "fighter"
        self.difficulty = (data.get("difficulty")
                           if data.get("difficulty") in DIFFICULTY_ORDER
                           else "normal")
        self.salvage_bonus = _clean_int(
            data.get("salvage_bonus", 0), 0, 0, MAX_SALVAGE_BONUS
        )
        self.last_mission = (data.get("last_mission")
                             if data.get("last_mission") in MISSION_IDS
                             else None)

    # ------------------------------------------------------------ lifecycle
    @classmethod
    def load(cls, path=None):
        path = path or _campaign_path()
        raw = read_json(path, {})
        progress = cls(raw, path=path)
        if not raw:
            progress.save()
        return progress

    def save(self, path=None):
        return write_json(path or self.path, self.as_dict())

    def as_dict(self):
        return {
            "version": self.VERSION,
            "completed": list(self.completed),
            "unlocked": list(self.unlocked),
            "best": {key: dict(value) for key, value in self.best.items()},
            "ship": self.ship,
            "difficulty": self.difficulty,
            "salvage_bonus": int(self.salvage_bonus),
            "last_mission": self.last_mission,
        }

    def copy(self):
        return CampaignProgress(self.as_dict(), path=self.path)

    # -------------------------------------------------------------- queries
    def is_unlocked(self, mission_id):
        return mission_id in self.unlocked

    def is_completed(self, mission_id):
        return mission_id in self.completed

    def best_for(self, mission_id):
        return self.best.get(mission_id)

    def completed_count(self):
        return len(self.completed)

    def total_count(self):
        return len(MISSION_IDS)

    def progress_ratio(self):
        return self.completed_count() / max(1, self.total_count())

    def next_open_mission(self):
        for mission_id in MISSION_IDS:
            if self.is_unlocked(mission_id) and not self.is_completed(mission_id):
                return mission_id
        return MISSION_IDS[-1]

    # ------------------------------------------------------------- mutations
    def begin_mission(self, mission_id, ship=None, difficulty=None):
        """Remember the player's choices before launching a mission."""
        if mission_id in MISSION_IDS:
            self.last_mission = mission_id
        if ship in SHIP_ORDER:
            self.ship = ship
        if difficulty in DIFFICULTY_ORDER:
            self.difficulty = difficulty
        self.save()

    def complete_mission(self, mission_id, score=0, kills=0, time=0.0,
                         reward=0):
        """Record a clear. Returns a small summary for the victory screen."""
        mission = MISSION_BY_ID.get(mission_id)
        if mission is None:
            return {
                "first_completion": False, "next_mission": None,
                "salvage_bonus": self.salvage_bonus,
            }

        first = mission_id not in self.completed
        if first:
            self.completed.append(mission_id)
            self.completed.sort(key=MISSION_IDS.index)
            self.salvage_bonus = _clean_int(
                self.salvage_bonus + max(0, int(reward)),
                0, 0, MAX_SALVAGE_BONUS,
            )

        previous = self.best.get(mission_id)
        entry = {
            "score": max(0, int(score)),
            "kills": max(0, int(kills)),
            "time": _clean_time(time),
        }
        if previous is None or entry["score"] > previous.get("score", 0):
            self.best[mission_id] = entry

        following = next_mission_id(mission_id)
        if following and following not in self.unlocked:
            self.unlocked.append(following)
            self.unlocked.sort(key=MISSION_IDS.index)

        self.last_mission = following or mission_id
        self.save()
        return {
            "first_completion": first,
            "next_mission": following,
            "salvage_bonus": self.salvage_bonus,
            "best": self.best.get(mission_id),
        }

    def summary(self):
        return {
            "completed": list(self.completed),
            "unlocked": list(self.unlocked),
            "salvage_bonus": self.salvage_bonus,
            "ship": self.ship,
            "difficulty": self.difficulty,
            "ratio": round(self.progress_ratio(), 3),
        }
