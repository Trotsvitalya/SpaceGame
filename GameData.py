"""Static design data for SpaceGame 2.0.

Keeping the numbers and identifiers in one place makes the ships, weapons,
upgrades and space zones easy to tune without touching gameplay code.  All
human-readable strings live in ``Localization.py`` and are referenced here by
key.
"""

from __future__ import annotations

SHIP_ORDER = ("fighter", "interceptor", "tank", "engineer")

SHIPS = {
    "fighter": {
        "name": "ship_fighter",
        "role": "ship_role_fighter",
        "desc": "ship_fighter_desc",
        "speed": 390.0,
        "acceleration": 3200.0,
        "life": 3,
        "max_life": 5,
        "fire_interval": 0.17,
        "hit_radius": 19.0,
        "weapon": "pulse",
        "passive": "balanced",
        "accent": (74, 190, 255),
        "stats": (3, 3, 3, 2),
    },
    "interceptor": {
        "name": "ship_interceptor",
        "role": "ship_role_interceptor",
        "desc": "ship_interceptor_desc",
        "speed": 470.0,
        "acceleration": 4100.0,
        "life": 3,
        "max_life": 5,
        "fire_interval": 0.105,
        "hit_radius": 15.0,
        "weapon": "burst",
        "passive": "agile",
        "accent": (255, 104, 208),
        "stats": (5, 4, 1, 3),
    },
    "tank": {
        "name": "ship_tank",
        "role": "ship_role_tank",
        "desc": "ship_tank_desc",
        "speed": 305.0,
        "acceleration": 2450.0,
        "life": 5,
        "max_life": 7,
        "fire_interval": 0.36,
        "hit_radius": 26.0,
        "weapon": "lance",
        "passive": "armored",
        "accent": (255, 168, 72),
        "stats": (1, 1, 5, 2),
    },
    "engineer": {
        "name": "ship_engineer",
        "role": "ship_role_engineer",
        "desc": "ship_engineer_desc",
        "speed": 350.0,
        "acceleration": 2900.0,
        "life": 3,
        "max_life": 6,
        "fire_interval": 0.235,
        "hit_radius": 21.0,
        "weapon": "spread",
        "passive": "salvager",
        "accent": (92, 255, 190),
        "stats": (3, 2, 3, 5),
    },
}

WEAPONS = {
    "pulse": {
        "name": "weapon_pulse",
        "desc": "weapon_pulse_desc",
        "sprite": "player_pulse",
        "color": (120, 226, 255),
        "sound": "shot",
        # level -> (dx, dy, vx, vy, damage_scale, radius, pierce, splash)
        "pattern": {
            1: ((0, 0, 0, -940, 1.0, 8.0, 0, 0),),
            2: ((-12, 8, -30, -950, 0.9, 8.0, 0, 0),
                (12, 8, 30, -950, 0.9, 8.0, 0, 0)),
            3: ((0, -4, 0, -980, 1.0, 8.0, 0, 0),
                (-19, 10, -105, -930, 0.85, 7.0, 0, 0),
                (19, 10, 105, -930, 0.85, 7.0, 0, 0)),
        },
    },
    "burst": {
        "name": "weapon_burst",
        "desc": "weapon_burst_desc",
        "sprite": "player_burst",
        "color": (255, 238, 132),
        "sound": "shot_burst",
        "pattern": {
            1: ((0, 2, 0, -1060, 0.8, 5.5, 0, 0),),
            2: ((-8, 6, -18, -1060, 0.75, 5.5, 0, 0),
                (8, 6, 18, -1060, 0.75, 5.5, 0, 0)),
            3: ((-14, 8, -52, -1040, 0.7, 5.0, 0, 0),
                (0, 2, 0, -1080, 0.8, 5.5, 0, 0),
                (14, 8, 52, -1040, 0.7, 5.0, 0, 0)),
        },
    },
    "lance": {
        "name": "weapon_lance",
        "desc": "weapon_lance_desc",
        "sprite": "player_lance",
        "color": (214, 132, 255),
        "sound": "shot_lance",
        "pattern": {
            1: ((0, -6, 0, -1240, 4.0, 11.0, 2, 0),),
            2: ((0, -6, 0, -1240, 4.0, 11.0, 2, 0),
                (-23, 10, -35, -980, 0.8, 6.0, 0, 0),
                (23, 10, 35, -980, 0.8, 6.0, 0, 0)),
            3: ((-10, -6, -12, -1250, 3.2, 10.0, 2, 0),
                (10, -6, 12, -1250, 3.2, 10.0, 2, 0),
                (-26, 12, -70, -1010, 0.9, 6.0, 0, 0),
                (26, 12, 70, -1010, 0.9, 6.0, 0, 0)),
        },
    },
    "spread": {
        "name": "weapon_spread",
        "desc": "weapon_spread_desc",
        "sprite": "player_spread",
        "color": (255, 166, 88),
        "sound": "shot_spread",
        "pattern": {
            1: ((-10, 4, -95, -900, 0.85, 7.0, 0, 0),
                (10, 4, 95, -900, 0.85, 7.0, 0, 0)),
            2: ((-16, 6, -165, -910, 0.8, 6.5, 0, 0),
                (0, 0, 0, -950, 0.9, 7.0, 0, 0),
                (16, 6, 165, -910, 0.8, 6.5, 0, 0)),
            3: ((-22, 8, -235, -880, 0.75, 6.0, 0, 0),
                (-10, 4, -118, -920, 0.8, 6.5, 0, 0),
                (0, 0, 0, -960, 0.9, 7.0, 0, 0),
                (10, 4, 118, -920, 0.8, 6.5, 0, 0),
                (22, 8, 235, -880, 0.75, 6.0, 0, 0)),
        },
    },
}

WEAPON_ORDER = ("pulse", "burst", "lance", "spread")

# Upgrade costs are paid in salvage.  Levels are capped so a run cannot turn
# into an unbounded stat stack.
UPGRADES = {
    "damage": {
        "name": "upgrade_damage",
        "desc": "upgrade_damage_desc",
        "max": 3,
        "costs": (8, 16, 28),
        "icon": "damage",
        "color": (255, 198, 82),
    },
    "firerate": {
        "name": "upgrade_firerate",
        "desc": "upgrade_firerate_desc",
        "max": 3,
        "costs": (9, 18, 30),
        "icon": "rapid",
        "color": (120, 255, 180),
    },
    "hull": {
        "name": "upgrade_hull",
        "desc": "upgrade_hull_desc",
        "max": 3,
        "costs": (12, 22, 34),
        "icon": "hull",
        "color": (255, 92, 124),
    },
    "multishot": {
        "name": "upgrade_multishot",
        "desc": "upgrade_multishot_desc",
        "max": 2,
        "costs": (18, 34),
        "icon": "weapon",
        "color": (196, 130, 255),
    },
    "engine": {
        "name": "upgrade_engine",
        "desc": "upgrade_engine_desc",
        "max": 3,
        "costs": (8, 15, 24),
        "icon": "engine",
        "color": (86, 214, 255),
    },
    "salvage": {
        "name": "upgrade_salvage",
        "desc": "upgrade_salvage_desc",
        "max": 3,
        "costs": (10, 18, 28),
        "icon": "salvage",
        "color": (255, 214, 120),
    },
    "shield": {
        "name": "upgrade_shield",
        "desc": "upgrade_shield_desc",
        "max": 2,
        "costs": (16, 30),
        "icon": "shield",
        "color": (80, 190, 255),
    },
}

UPGRADE_ORDER = ("damage", "firerate", "hull", "multishot", "engine",
                 "salvage", "shield")

# Space zones.  A new zone starts every five waves and changes both the
# backdrop and the enemy composition.
ZONES = (
    {
        "id": "core",
        "name": "zone_core",
        "planet": "azure",
        "tint": (150, 190, 255),
        "accent": (92, 218, 255),
        "stars": (210, 235, 255),
        "meme_stars": (255, 220, 255),
        "enemies": ("scout", "asteroid", "fighter", "asteroid", "bomber"),
    },
    {
        "id": "nebula",
        "name": "zone_nebula",
        "planet": "verdant",
        "tint": (120, 255, 210),
        "accent": (86, 255, 190),
        "stars": (198, 255, 236),
        "meme_stars": (255, 235, 190),
        "enemies": ("fighter", "raider", "asteroid", "scout", "elite"),
    },
    {
        "id": "ember",
        "name": "zone_ember",
        "planet": "ember",
        "tint": (255, 160, 110),
        "accent": (255, 150, 86),
        "stars": (255, 224, 196),
        "meme_stars": (255, 200, 220),
        "enemies": ("bomber", "fighter", "elite", "raider", "scout"),
    },
    {
        "id": "void",
        "name": "zone_void",
        "planet": "azure",
        "tint": (170, 140, 255),
        "accent": (196, 140, 255),
        "stars": (224, 210, 255),
        "meme_stars": (255, 170, 240),
        "enemies": ("raider", "elite", "fighter", "bomber", "scout"),
    },
)

ZONE_WAVES = 5


def zone_index_for_wave(wave):
    return max(0, (max(1, int(wave)) - 1) // ZONE_WAVES) % len(ZONES)


def zone_for_wave(wave):
    return ZONES[zone_index_for_wave(wave)]


def boss_kind_for_wave(wave):
    """The sentinel returns every tenth wave, the dreadnought in between."""
    return "sentinel" if max(1, int(wave)) % 10 == 0 else "dreadnought"


def boss_hp_for_wave(wave):
    """Legacy helper: bounded boss health using the Normal preset."""
    from Balance import Balance
    return Balance("normal").boss_hp(wave)


def upgrade_available(key, levels):
    spec = UPGRADES.get(key)
    if spec is None:
        return False
    return levels.get(key, 0) < spec["max"]


def upgrade_cost(key, level):
    spec = UPGRADES[key]
    return spec["costs"][min(level, len(spec["costs"]) - 1)]
