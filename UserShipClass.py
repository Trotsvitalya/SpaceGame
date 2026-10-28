"""The player's ship and its weapon classes.

Movement is velocity based (pixels per second) so handling is identical at any
frame rate.  Ships share one class but read their hull, engine and weapon
numbers from :mod:`GameData`, which keeps the archetypes genuinely different
without duplicating logic.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import pygame

from GameData import SHIPS, WEAPONS
from utils import clamp


class Shot(NamedTuple):
    """A single projectile request produced by :meth:`UserShip.fire_volley`."""

    x: float
    y: float
    vx: float
    vy: float
    kind: str = "pulse"
    speed: float = 940.0
    damage: float = 1.0
    radius: float = 8.0
    pierce: int = 0
    splash: float = 0.0


class UserShip:
    MAX_WEAPON_LEVEL = 3
    BASE_FIRE_INTERVAL = 0.17
    MAX_SPEED = 390.0
    ACCELERATION = 3200.0
    FRICTION = 3800.0

    def __init__(self, posX, posY, maxW, maxH, imageList=None,
                 imageBoomList=None, height=78, width=78, kind=None):
        self.kind = kind if kind in SHIPS else "fighter"
        stats = SHIPS[self.kind]
        self.maxW = maxW
        self.maxH = maxH
        self.width = width
        self.height = height
        self.posX = float(posX)
        self.posY = float(posY)
        self.vx = 0.0
        self.vy = 0.0
        self.currentDirection = 0
        self.speed = stats["speed"]
        self.acceleration = stats["acceleration"]
        self.base_speed = stats["speed"]
        self.base_acceleration = stats["acceleration"]

        self.max_life = stats["max_life"]
        self.life = stats["life"]
        self.weapon_class = stats["weapon"]
        self.weapon = WEAPONS[self.weapon_class]
        self.passive = stats["passive"]
        self.accent = stats["accent"]
        self.hit_radius = stats["hit_radius"]

        self.isBoom = False
        self.alive = True
        self.respawn_timer = 0.0
        self.invulnerable_timer = 2.0
        self.shield_timer = 0.0
        self.weapon_level = 1
        self.weapon_timer = 0.0
        self.rapid_timer = 0.0
        self.fire_cooldown = 0.0
        self.damage_flash = 0.0
        self.animation_time = 0.0
        self.bank = 0.0
        self.magnet_radius = 185.0 if self.passive == "salvager" else 0.0

        self.upgrades = {}
        self.extra_shots = 0
        self.fire_rate_mult = 1.0
        self.damage_bonus = 0.0
        self.salvage_mult = 1.25 if self.passive == "salvager" else 1.0
        self.speed_mult = 1.0
        self.start_shield_bonus = 4.0 if self.passive == "armored" else 0.0
        self._bank_cache = {}

        self.imageList = imageList or []
        self.imageBoomList = imageBoomList or []
        self.imageNum = 0
        self.image = self.imageList[0] if self.imageList else None
        self.timeTick = 0
        self.timeTickMax = 10
        self.flagCounter = 1

    # ------------------------------------------------------------- geometry
    @property
    def centerx(self):
        return self.posX + self.width * 0.5

    @property
    def centery(self):
        return self.posY + self.height * 0.5

    @property
    def rect(self):
        return pygame.Rect(int(self.posX), int(self.posY), self.width, self.height)

    @property
    def fire_interval(self):
        interval = self.weapon.get("interval", SHIPS[self.kind]["fire_interval"])
        interval *= self.fire_rate_mult
        if self.rapid_timer > 0:
            interval *= 0.45
        return max(0.045, interval)

    @property
    def start_shield(self):
        return 4.0 + self.start_shield_bonus

    @property
    def max_hp_visual(self):
        return max(1, self.max_life)

    def upgrade_level(self, key):
        return self.upgrades.get(key, 0)

    # --------------------------------------------------------------- update
    def update(self, dt, move_x=0.0, move_y=0.0):
        events = []
        length = math.hypot(move_x, move_y)
        if length > 0:
            move_x /= length
            move_y /= length

        target_vx = move_x * self.speed
        target_vy = move_y * self.speed
        acceleration = self.acceleration if length > 0 else self.FRICTION
        if self.vx < target_vx:
            self.vx = min(self.vx + acceleration * dt, target_vx)
        else:
            self.vx = max(self.vx - acceleration * dt, target_vx)
        if self.vy < target_vy:
            self.vy = min(self.vy + acceleration * dt, target_vy)
        else:
            self.vy = max(self.vy - acceleration * dt, target_vy)

        if self.alive:
            self.posX += self.vx * dt
            self.posY += self.vy * dt
            left_bound = 14
            right_bound = self.maxW - self.width - 14
            top_bound = 82
            bottom_bound = self.maxH - self.height - 100
            if self.posX < left_bound:
                self.posX = left_bound
                self.vx = 0
            elif self.posX > right_bound:
                self.posX = right_bound
                self.vx = 0
            if self.posY < top_bound:
                self.posY = top_bound
                self.vy = 0
            elif self.posY > bottom_bound:
                self.posY = bottom_bound
                self.vy = 0
        else:
            self.vx = self.vy = 0.0

        self.fire_cooldown = max(0.0, self.fire_cooldown - dt)
        self.invulnerable_timer = max(0.0, self.invulnerable_timer - dt)
        self.damage_flash = max(0.0, self.damage_flash - dt)

        if self.shield_timer > 0:
            self.shield_timer = max(0.0, self.shield_timer - dt)
            if self.shield_timer <= 0:
                events.append("shield_expired")
        if self.rapid_timer > 0:
            self.rapid_timer = max(0.0, self.rapid_timer - dt)
            if self.rapid_timer <= 0:
                events.append("rapid_expired")
        if self.weapon_timer > 0:
            self.weapon_timer = max(0.0, self.weapon_timer - dt)
            if self.weapon_timer <= 0:
                if self.weapon_level > 1:
                    self.weapon_level = 1
                    events.append("weapon_expired")
        elif self.weapon_level > 1:
            self.weapon_level = 1

        if not self.alive and self.life > 0:
            self.respawn_timer -= dt
            if self.respawn_timer <= 0:
                self.revive()
                events.append("respawned")

        self.currentDirection = 0
        if move_x > 0:
            self.currentDirection = 1
        elif move_x < 0:
            self.currentDirection = -1
        elif move_y < 0:
            self.currentDirection = 2
        elif move_y > 0:
            self.currentDirection = -2

        self.bank = clamp(-self.vx / max(1.0, self.speed), -1.0, 1.0) * 11.0
        self._update_image(dt)
        return events

    def _update_image(self, dt):
        if not self.imageList:
            return
        self.animation_time += dt
        frame_time = 0.075 if (abs(self.vx) + abs(self.vy) > 20) else 0.13
        if self.animation_time >= frame_time:
            self.animation_time = 0.0
            self.imageNum = (self.imageNum + 1) % len(self.imageList)
            self.image = self.imageList[self.imageNum]

    # -------------------------------------------------------- combat state
    def revive(self):
        self.alive = True
        self.isBoom = False
        self.posX = self.maxW * 0.5 - self.width * 0.5
        self.posY = self.maxH - self.height - 100
        self.vx = self.vy = 0.0
        self.invulnerable_timer = 2.4 + (0.8 if self.passive == "agile" else 0.0)
        self.respawn_timer = 0.0

    def take_hit(self):
        """Returns 'shield', 'dead', or 'none' (ignored while invulnerable)."""
        if not self.alive or self.invulnerable_timer > 0:
            return "none"
        self.damage_flash = 0.22
        if self.shield_timer > 0:
            self.shield_timer = 0.0
            self.invulnerable_timer = 0.9
            return "shield"
        self.life = max(0, self.life - 1)
        self.alive = False
        self.isBoom = True
        self.respawn_timer = 1.45
        self.weapon_level = 1
        self.weapon_timer = 0.0
        self.rapid_timer = 0.0
        self.shield_timer = 0.0
        return "dead"

    def can_fire(self):
        return self.alive and self.fire_cooldown <= 0 and self.invulnerable_timer < 99

    def fire_volley(self):
        """Consume the cooldown and return :class:`Shot` tuples."""
        if not self.can_fire():
            return []
        self.fire_cooldown = self.fire_interval
        y = self.posY + 4
        cx = self.centerx
        level = max(1, min(self.MAX_WEAPON_LEVEL, self.weapon_level))
        patterns = self.weapon["pattern"]
        entries = patterns.get(level, patterns[1])
        shots = []
        for dx, dy, vx, vy, damage_scale, radius, pierce, splash in entries:
            shots.append(Shot(
                cx + dx, y + dy, float(vx), float(vy),
                self.weapon_class, float(-vy or 940.0),
                damage_scale + self.damage_bonus, float(radius), int(pierce),
                float(splash),
            ))
        # Multishot upgrades add one angled pair per level, capped so the
        # screen does not turn into a solid wall of projectiles.
        for index in range(min(2, self.extra_shots)):
            offset = 10 + index * 7
            shots.append(Shot(
                cx - offset, y + 6, -55.0 - index * 20, -900.0,
                self.weapon_class, 900.0, 0.65 + self.damage_bonus, 6.0, 0, 0.0,
            ))
            shots.append(Shot(
                cx + offset, y + 6, 55.0 + index * 20, -900.0,
                self.weapon_class, 900.0, 0.65 + self.damage_bonus, 6.0, 0, 0.0,
            ))
        return shots

    def add_weapon(self):
        if self.weapon_level < self.MAX_WEAPON_LEVEL:
            self.weapon_level += 1
            self.weapon_timer = 18.0
            return True
        self.weapon_timer = 18.0
        return False

    def add_shield(self, seconds=12.0):
        self.shield_timer = max(self.shield_timer, seconds)

    def add_rapid(self, seconds=11.0):
        self.rapid_timer = max(self.rapid_timer, seconds)

    def heal(self):
        if self.life < self.max_life:
            self.life += 1
            return True
        return False

    # ----------------------------------------------------------- upgrades
    def apply_upgrade(self, key):
        from GameData import UPGRADES

        spec = UPGRADES.get(key)
        if spec is None:
            return False
        level = self.upgrades.get(key, 0)
        if level >= spec["max"]:
            return False
        self.upgrades[key] = level + 1
        if key == "damage":
            self.damage_bonus += 0.75
        elif key == "firerate":
            self.fire_rate_mult *= 0.88
        elif key == "hull":
            self.max_life += 1
            self.life = min(self.max_life, self.life + 1)
        elif key == "multishot":
            self.extra_shots += 1
        elif key == "engine":
            self.speed_mult *= 1.09
            self.speed = self.base_speed * self.speed_mult
            self.acceleration = self.base_acceleration * (1.0 + 0.05 * (level + 1))
        elif key == "salvage":
            self.salvage_mult += 0.2
            self.magnet_radius += 18.0
        elif key == "shield":
            self.start_shield_bonus += 6.0
            self.add_shield(6.0)
        return True

    # ---------------------------------------------------------------- draw
    def _banked(self, image, angle):
        rounded = int(round(angle / 3.0)) * 3
        if rounded == 0:
            return image
        key = (id(image), rounded)
        cached = self._bank_cache.get(key)
        if cached is not None:
            return cached
        result = pygame.transform.rotozoom(image, -rounded, 1.0)
        if len(self._bank_cache) > 48:
            self._bank_cache.clear()
        self._bank_cache[key] = result
        return result

    def draw(self, surface, resources, time, mode="normal"):
        if not self.alive or self.image is None:
            return
        if self.invulnerable_timer > 0 and self.shield_timer <= 0:
            if int(self.invulnerable_timer * 14) % 2 == 0:
                return
        center = (int(self.centerx), int(self.centery))

        # Engine flame behind the hull.  The generated sprites already contain
        # hot nozzles, so the procedural plume only needs to sell movement.
        base_y = self.posY + self.height - 12
        flame_length = 17 + math.sin(time * 31.0) * 4 + max(0.0, -self.vy) * 0.035
        flame_color = (255, 156, 62) if mode == "normal" else (255, 110, 210)
        flame_inner = (255, 246, 190) if mode == "normal" else (255, 245, 120)
        if self.passive == "salvager":
            flame_color = (96, 255, 196)
        elif self.passive == "agile":
            flame_color = (255, 118, 214)
        flicker = math.sin(time * 47.0) * 3
        offsets = (-14, 14) if self.kind != "tank" else (-24, -8, 8, 24)
        width = 7 if self.kind != "tank" else 5
        for offset in offsets:
            pygame.draw.polygon(surface, flame_color, [
                (center[0] + offset - width, base_y),
                (center[0] + offset + width, base_y),
                (center[0] + offset + flicker, base_y + flame_length),
            ])
            pygame.draw.polygon(surface, flame_inner, [
                (center[0] + offset - width * 0.45, base_y),
                (center[0] + offset + width * 0.45, base_y),
                (center[0] + offset + flicker * 0.5, base_y + flame_length * 0.55),
            ])

        image = self._banked(self.image, self.bank)
        rect = image.get_rect(center=center)
        if self.invulnerable_timer > 0:
            image.set_alpha(150)
        if self.damage_flash > 0:
            # A short additive flash makes the hit readable without hiding the
            # rest of the battlefield.
            flash = image.copy()
            flash.fill((120, 90, 70, 0), special_flags=pygame.BLEND_RGBA_ADD)
            surface.blit(flash, rect)
        else:
            surface.blit(image, rect)
        image.set_alpha(255)

        if self.shield_timer > 0:
            pulse = 0.78 + math.sin(time * 7.0) * 0.12
            radius = int(46 * pulse)
            glow_color = (80, 200, 255) if mode == "normal" else (255, 130, 220)
            glow = resources.glow(radius, glow_color, 100)
            surface.blit(glow, glow.get_rect(center=center))
            pygame.draw.circle(surface, glow_color, center, radius, 2)
            pygame.draw.circle(surface, (230, 250, 255), center, radius - 4, 1)
