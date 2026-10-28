"""Data-driven mission definitions for the SpaceGame 2.1 campaign.

A mission only describes *what* should happen; the shared combat systems in
:mod:`GameProcessClass` still run the waves, enemies, bosses and rewards.  New
missions can therefore be added here without touching the game loop.

Mission keys
------------
``id``            stable identifier used by the save file.
``zone``          index into :data:`GameData.ZONES`.
``waves``         normal waves to survive before the boss (or victory).
``boss``          boss kind (``dreadnought``/``sentinel``) or ``None``.
``boss_wave``     wave number used for boss health/kind scaling.
``boss_scale``    optional health multiplier for the final encounter.
``enemies``       enemy pool used while the mission is running.
``asteroid_ratio`` chance that a spawn is an asteroid.
``max_elites``    simultaneous elite cap (campaign is deliberately gentle).
``reward_salvage`` persistent starting-salvage bonus granted on first clear.
``story``         localization keys shown as skippable in-game story cards.
"""

from __future__ import annotations

from Localization import tr

ZONE_NAMES = ("zone_core", "zone_nebula", "zone_ember", "zone_void")


def _mission(mission_id, zone, waves, enemies, asteroid_ratio,
             reward_salvage, story, boss=None, boss_wave=5, boss_scale=1.0,
             max_elites=1):
    return {
        "id": mission_id,
        "zone": zone,
        "waves": waves,
        "boss": boss,
        "boss_wave": boss_wave,
        "boss_scale": boss_scale,
        "enemies": tuple(enemies),
        "asteroid_ratio": asteroid_ratio,
        "max_elites": max_elites,
        "reward_salvage": reward_salvage,
        "story": tuple(story),
        "name_key": "mission_%s_name" % mission_id,
        "brief_key": "mission_%s_brief" % mission_id,
    }


MISSIONS = (
    _mission(
        "m01", 0, 2,
        ("asteroid", "scout"), 0.55, 6,
        ("mission_m01_story1", "mission_m01_story2"),
    ),
    _mission(
        "m02", 0, 3,
        ("asteroid", "scout", "fighter"), 0.38, 8,
        ("mission_m02_story1", "mission_m02_story2"),
    ),
    _mission(
        "m03", 0, 3,
        ("asteroid", "scout", "fighter", "bomber"), 0.30, 12,
        ("mission_m03_story1", "mission_m03_story2"),
        boss="dreadnought", boss_wave=5,
    ),
    _mission(
        "m04", 1, 3,
        ("asteroid", "fighter", "raider"), 0.28, 10,
        ("mission_m04_story1", "mission_m04_story2"),
    ),
    _mission(
        "m05", 1, 4,
        ("asteroid", "fighter", "raider", "elite"), 0.22, 14,
        ("mission_m05_story1", "mission_m05_story2"),
    ),
    _mission(
        "m06", 1, 3,
        ("asteroid", "fighter", "raider", "elite"), 0.22, 16,
        ("mission_m06_story1", "mission_m06_story2"),
        boss="sentinel", boss_wave=10,
    ),
    _mission(
        "m07", 2, 3,
        ("asteroid", "bomber", "fighter", "raider"), 0.25, 14,
        ("mission_m07_story1", "mission_m07_story2"),
    ),
    _mission(
        "m08", 2, 4,
        ("asteroid", "bomber", "fighter", "raider", "elite"), 0.18, 18,
        ("mission_m08_story1", "mission_m08_story2"),
        boss="dreadnought", boss_wave=15, boss_scale=1.1,
    ),
    _mission(
        "m09", 3, 4,
        ("asteroid", "raider", "elite", "scout"), 0.18, 18,
        ("mission_m09_story1", "mission_m09_story2"),
        max_elites=2,
    ),
    _mission(
        "m10", 3, 3,
        ("asteroid", "raider", "elite", "fighter"), 0.16, 24,
        ("mission_m10_story1", "mission_m10_story2", "mission_m10_story3"),
        boss="sentinel", boss_wave=20, boss_scale=1.25, max_elites=2,
    ),
)

MISSION_IDS = tuple(mission["id"] for mission in MISSIONS)
MISSION_BY_ID = {mission["id"]: mission for mission in MISSIONS}


def mission_by_id(mission_id):
    return MISSION_BY_ID.get(mission_id)


def mission_index(mission_id):
    try:
        return MISSION_IDS.index(mission_id)
    except ValueError:
        return -1


def next_mission_id(mission_id):
    index = mission_index(mission_id)
    if index < 0 or index + 1 >= len(MISSION_IDS):
        return None
    return MISSION_IDS[index + 1]


def first_mission_id(progress=None):
    if progress is not None:
        for mission_id in MISSION_IDS:
            if progress.is_unlocked(mission_id) and not progress.is_completed(mission_id):
                return mission_id
        for mission_id in reversed(MISSION_IDS):
            if progress.is_unlocked(mission_id):
                return mission_id
    return MISSION_IDS[0]


def mission_name(language, mission):
    return tr(language, mission["name_key"])


def mission_objective(language, mission):
    if mission["boss"]:
        return tr(language, "mission_objective_boss", waves=mission["waves"])
    return tr(language, "mission_objective_survive", waves=mission["waves"])


def mission_zone_name(language, mission):
    return tr(language, ZONE_NAMES[max(0, min(len(ZONE_NAMES) - 1, mission["zone"]))])
