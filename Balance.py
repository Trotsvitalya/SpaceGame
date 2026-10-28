"""Data-driven difficulty tuning and run metrics for SpaceGame 2.1.

Every endless-mode scaling curve here is *saturating*: it ramps quickly over
the first few waves and then approaches a finite ceiling.  Unbounded linear
growth was the main reason the run became unfair after the first boss, because
enemy health, speed, fire rate and projectile speed all kept climbing forever
while the player's own power plateaued.

The presets only change the ceiling, the ramp speed and a handful of
quality-of-life values, so all four ships share one predictable ruleset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DIFFICULTY_ORDER = ("story", "normal", "hard")
DEFAULT_DIFFICULTY = "normal"


def _ramp(wave, tau):
    """Return 0..1, approaching 1 with time constant ``tau`` waves."""
    wave = max(1, int(wave))
    if tau <= 0:
        return 1.0
    return 1.0 - math.exp(-(wave - 1) / float(tau))


@dataclass(frozen=True)
class DifficultySpec:
    key: str
    label_key: str
    desc_key: str

    # Endless-wave ceilings (multipliers) and ramp constants (waves).
    hp_cap: float
    hp_tau: float
    speed_cap: float
    speed_tau: float
    fire_cap: float
    fire_tau: float
    bullet_cap: float
    bullet_tau: float

    # Spawn interval in seconds: floor + (start - floor) * exp(...)
    spawn_start: float
    spawn_floor: float
    spawn_tau: float

    # Boss tuning.
    boss_hp_scale: float
    boss_fire_scale: float

    # Hazards and reaction time.
    telegraph_scale: float
    max_zones: int
    max_beams: int

    # Rewards and recovery.
    drop_scale: float
    salvage_scale: float
    post_boss_heal: int
    post_boss_grace: float


DIFFICULTY = {
    "story": DifficultySpec(
        key="story",
        label_key="difficulty_story",
        desc_key="difficulty_story_desc",
        hp_cap=1.8, hp_tau=14.0,
        speed_cap=1.15, speed_tau=18.0,
        fire_cap=0.18, fire_tau=18.0,
        bullet_cap=1.20, bullet_tau=14.0,
        spawn_start=1.50, spawn_floor=1.05, spawn_tau=10.0,
        boss_hp_scale=0.75, boss_fire_scale=1.12,
        telegraph_scale=1.25, max_zones=2, max_beams=1,
        drop_scale=1.25, salvage_scale=1.20,
        post_boss_heal=2, post_boss_grace=3.5,
    ),
    "normal": DifficultySpec(
        key="normal",
        label_key="difficulty_normal",
        desc_key="difficulty_normal_desc",
        hp_cap=2.4, hp_tau=16.0,
        speed_cap=1.24, speed_tau=18.0,
        fire_cap=0.22, fire_tau=18.0,
        bullet_cap=1.30, bullet_tau=14.0,
        spawn_start=1.42, spawn_floor=0.88, spawn_tau=10.0,
        boss_hp_scale=1.0, boss_fire_scale=1.0,
        telegraph_scale=1.0, max_zones=3, max_beams=2,
        drop_scale=1.0, salvage_scale=1.0,
        post_boss_heal=1, post_boss_grace=3.0,
    ),
    "hard": DifficultySpec(
        key="hard",
        label_key="difficulty_hard",
        desc_key="difficulty_hard_desc",
        hp_cap=3.1, hp_tau=12.0,
        speed_cap=1.35, speed_tau=14.0,
        fire_cap=0.28, fire_tau=14.0,
        bullet_cap=1.42, bullet_tau=12.0,
        spawn_start=1.32, spawn_floor=0.72, spawn_tau=9.0,
        boss_hp_scale=1.25, boss_fire_scale=0.92,
        telegraph_scale=0.90, max_zones=4, max_beams=3,
        drop_scale=0.85, salvage_scale=1.10,
        post_boss_heal=1, post_boss_grace=2.2,
    ),
}


class Balance:
    """Resolve every combat scaling value for one difficulty preset."""

    def __init__(self, difficulty=DEFAULT_DIFFICULTY):
        if difficulty not in DIFFICULTY:
            difficulty = DEFAULT_DIFFICULTY
        self.difficulty = difficulty
        self.spec = DIFFICULTY[difficulty]

    # ------------------------------------------------------------ endless
    def enemy_hp(self, wave):
        spec = self.spec
        return 1.0 + (spec.hp_cap - 1.0) * _ramp(wave, spec.hp_tau)

    def enemy_speed(self, wave):
        spec = self.spec
        return 1.0 + (spec.speed_cap - 1.0) * _ramp(wave, spec.speed_tau)

    def asteroid_speed(self, wave):
        # Asteroids are slower than ships, but obey the same ceiling.
        return 1.0 + (self.spec.speed_cap - 1.0) * 0.65 * _ramp(
            wave, self.spec.speed_tau
        )

    def enemy_fire(self, wave):
        """Multiplier for the interval between enemy shots (>1 is slower)."""
        spec = self.spec
        return 1.0 - spec.fire_cap * _ramp(wave, spec.fire_tau)

    def bullet_speed(self, wave):
        spec = self.spec
        return 1.0 + (spec.bullet_cap - 1.0) * _ramp(wave, spec.bullet_tau)

    def spawn_interval(self, wave):
        """Average seconds between enemy spawns (before jitter)."""
        spec = self.spec
        return spec.spawn_floor + (spec.spawn_start - spec.spawn_floor) * math.exp(
            -(max(1, int(wave)) - 1) / spec.spawn_tau
        )

    # --------------------------------------------------------------- boss
    def boss_hp(self, wave):
        # Boss health grows for the first twelve boss waves, then plateaus.
        base = 95 + 11 * min(12, max(1, int(wave)))
        return max(1, int(round(base * self.spec.boss_hp_scale)))

    def boss_bullet_speed(self, base, wave):
        return base * self.bullet_speed(wave)

    def boss_attack_delay(self, base):
        # Never let the hardest preset reduce recovery below one second.
        return max(0.95, base * self.spec.boss_fire_scale)

    def telegraph(self, seconds):
        return max(0.95, seconds * self.spec.telegraph_scale)

    # ---------------------------------------------------------- gameplay
    @property
    def max_zones(self):
        return self.spec.max_zones

    @property
    def max_beams(self):
        return self.spec.max_beams

    def drop_chance(self, base):
        return max(0.02, base * self.spec.drop_scale)

    def salvage(self, amount):
        return max(0, int(round(amount * self.spec.salvage_scale)))

    @property
    def post_boss_heal(self):
        return self.spec.post_boss_heal

    @property
    def post_boss_grace(self):
        return self.spec.post_boss_grace

    def summary(self):
        return {
            "difficulty": self.difficulty,
            "max_zones": self.max_zones,
            "max_beams": self.max_beams,
            "post_boss_heal": self.post_boss_heal,
            "post_boss_grace": self.post_boss_grace,
            "enemy_hp_ceiling": round(self.enemy_hp(10_000), 3),
            "enemy_speed_ceiling": round(self.enemy_speed(10_000), 3),
            "bullet_speed_ceiling": round(self.bullet_speed(10_000), 3),
            "spawn_floor": round(self.spawn_interval(10_000), 3),
        }


class BalanceMetrics:
    """Lightweight run counters used by the reproducible balance scenarios.

    The object intentionally stores plain numbers so a scenario can print a
    stable report without reaching into rendering or audio state.
    """

    def __init__(self):
        self.enemy_spawns = {}
        self.powerups_spawned = {}
        self.damage_taken = 0
        self.max_zones = 0
        self.max_beams = 0
        self.bosses = 0
        self.waves = []
        self.spawn_times = []

    def note_spawn(self, kind, at=None):
        kind = str(kind)
        self.enemy_spawns[kind] = self.enemy_spawns.get(kind, 0) + 1
        if at is not None:
            self.spawn_times.append(round(float(at), 3))

    def note_powerup(self, kind):
        kind = str(kind)
        self.powerups_spawned[kind] = self.powerups_spawned.get(kind, 0) + 1

    def note_damage(self, amount=1):
        self.damage_taken += max(0, int(amount))

    def note_hazards(self, zones, beams):
        self.max_zones = max(self.max_zones, int(zones))
        self.max_beams = max(self.max_beams, int(beams))

    def note_boss(self):
        self.bosses += 1

    def note_wave(self, wave, duration):
        self.waves.append({"wave": int(wave), "duration": round(float(duration), 3)})

    @property
    def total_spawns(self):
        return sum(self.enemy_spawns.values())

    @property
    def total_powerups(self):
        return sum(self.powerups_spawned.values())

    def spawn_rate(self):
        if len(self.spawn_times) < 2:
            return 0.0
        span = self.spawn_times[-1] - self.spawn_times[0]
        if span <= 0:
            return 0.0
        return round((len(self.spawn_times) - 1) / span, 3)

    def summary(self):
        return {
            "spawns": dict(sorted(self.enemy_spawns.items())),
            "total_spawns": self.total_spawns,
            "spawn_rate_per_s": self.spawn_rate(),
            "powerups": dict(sorted(self.powerups_spawned.items())),
            "total_powerups": self.total_powerups,
            "damage_taken": self.damage_taken,
            "max_concurrent_zones": self.max_zones,
            "max_concurrent_beams": self.max_beams,
            "bosses": self.bosses,
            "waves": list(self.waves),
        }
