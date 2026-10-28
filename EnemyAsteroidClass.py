"""Enemies: asteroids, five ship archetypes and two multi-phase bosses.

The generated art is optional.  Every enemy keeps a procedural fallback so the
game still runs if ``assets/images`` is incomplete, which also keeps the asset
tests and headless smoke tests independent from the build tool.
"""

from __future__ import annotations

import math
import random

import pygame

from Balance import Balance
from GameData import boss_kind_for_wave
from utils import VH, VW, clamp

_NORMAL_BALANCE = Balance("normal")


class EnemyAsteroid:
    """A drifting, rotating asteroid.

    The original constructor signature is preserved, so existing callers can
    still create asteroids from raw image surfaces.
    """

    def __init__(self, maxW, maxH, image, imageBoomList=None, x=None, y=None,
                 radius=None, speed_scale=1.0, level="large", resources=None,
                 rot_index=None):
        self.maxW = maxW
        self.maxH = maxH
        self.level = level
        self.kind = "asteroid"
        self.resources = resources
        self.rot_index = rot_index
        if radius is None:
            radius = random.randint(30, 48) if level == "large" else random.randint(17, 24)
        self.radius = radius
        self.posX = float(random.randint(30, max(31, maxW - 30)) if x is None else x)
        self.posY = float(-radius - random.randint(0, 120) if y is None else y)
        self.vx = random.uniform(-78, 78) * speed_scale
        self.vy = random.uniform(72, 142) * speed_scale
        self.spin = random.uniform(-55, 55)
        self.angle = random.uniform(0, 360)
        self.hp = 2 if level == "large" else 1
        self.max_hp = self.hp
        self.score = 100 if level == "large" else 60
        self.hit_radius = radius * 0.84
        self.alive = True
        self.flash_timer = 0.0
        self.imageBoomList = imageBoomList or []
        self.base_image = image
        target = max(8, int(radius * 2))
        try:
            if image.get_width() != target:
                self.base_image = pygame.transform.smoothscale(image, (target, target))
        except (pygame.error, AttributeError):
            self.base_image = image

    def update(self, dt, game=None):
        self.posX += self.vx * dt
        self.posY += self.vy * dt
        self.angle = (self.angle + self.spin * dt) % 360
        if self.posX < self.radius:
            self.posX = self.radius
            self.vx = abs(self.vx)
        elif self.posX > self.maxW - self.radius:
            self.posX = self.maxW - self.radius
            self.vx = -abs(self.vx)
        self.flash_timer = max(0.0, self.flash_timer - dt)
        if self.posY > self.maxH + self.radius + 90:
            self.alive = False

    def damage(self, amount):
        self.hp -= amount
        self.flash_timer = 0.08
        if self.hp <= 0:
            self.alive = False
            return True
        return False

    def draw(self, surface, resources=None):
        resources = resources or self.resources
        if resources is not None and self.rot_index is not None:
            image = resources.asteroid_rot(self.rot_index, self.radius, self.angle)
        else:
            image = pygame.transform.rotozoom(self.base_image, self.angle, 1.0)
        rect = image.get_rect(center=(int(self.posX), int(self.posY)))
        if self.flash_timer > 0:
            if resources is not None:
                glow = resources.glow(int(self.radius * 1.2), (255, 245, 220), 120)
                surface.blit(glow, glow.get_rect(center=rect.center))
            image.set_alpha(150)
        surface.blit(image, rect)
        image.set_alpha(255)


class EnemyShip:
    """Five distinct enemy behaviours built on one shared state machine.

    ``scout`` dives and snaps off aimed shots, ``fighter`` hovers and strafes,
    ``bomber`` suppresses the lane with a wide spread, ``raider`` races across
    the screen with rapid bursts and ``elite`` is a heavy artillery platform
    that telegraphs circular danger zones.
    """

    STATS = {
        "scout": {"radius": 22, "hp": 2, "score": 150, "speed": 158.0,
                  "target_y": -90.0, "fire": (1.15, 2.0)},
        "fighter": {"radius": 28, "hp": 4, "score": 250, "speed": 126.0,
                    "target_y": 126.0, "fire": (1.35, 2.35)},
        "bomber": {"radius": 36, "hp": 8, "score": 420, "speed": 84.0,
                   "target_y": 98.0, "fire": (1.75, 2.9)},
        "raider": {"radius": 25, "hp": 3, "score": 300, "speed": 215.0,
                   "target_y": 150.0, "fire": (0.85, 1.55)},
        "elite": {"radius": 42, "hp": 14, "score": 760, "speed": 68.0,
                  "target_y": 156.0, "fire": (1.9, 2.8)},
    }

    def __init__(self, kind, mode, resources, x=None, y=-70, wave=1,
                 balance=None):
        stats = self.STATS.get(kind, self.STATS["scout"])
        balance = balance or _NORMAL_BALANCE
        self.kind = kind if kind in self.STATS else "scout"
        self.mode = mode
        self.balance = balance
        self.radius = stats["radius"]
        self.hit_radius = self.radius * 0.74
        self.max_hp = max(1, int(round(stats["hp"] * balance.enemy_hp(wave))))
        self.hp = self.max_hp
        self.score = stats["score"]
        self.wave = wave
        self.posX = float(x if x is not None else random.randint(80, VW - 80))
        self.posY = float(y)
        self.start_x = self.posX
        self.base_x = self.posX
        self.target_y = stats["target_y"]
        self.vy = stats["speed"] * balance.enemy_speed(wave)
        self.phase = random.uniform(0, math.tau)
        self.time = 0.0
        self.drift = random.uniform(-55, 55)
        self.fire_timer = random.uniform(*stats["fire"])
        self.fire_range = stats["fire"]
        self.alive = True
        self.flash_timer = 0.0
        self.entered = False
        self.charge = 0.0
        self.attack_index = 0
        self.anim_timer = random.uniform(0.0, 0.2)
        self.frame_index = 0
        self._draw_cache = {}

        frames = resources.enemy_frames(self.kind) if resources is not None else None
        if frames:
            self.frames = frames
        else:
            sprite = resources.enemy_sprite(self.kind, mode) if resources is not None else None
            if sprite is None:
                sprite = pygame.Surface((self.radius * 2, self.radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(sprite, (220, 90, 110), (self.radius, self.radius),
                                   self.radius)
            self.frames = [sprite]
        self.image = self.frames[0]

    # --------------------------------------------------------------- update
    def update(self, dt, game):
        self.time += dt
        self.flash_timer = max(0.0, self.flash_timer - dt)
        self.charge = max(0.0, self.charge - dt)
        self.fire_timer -= dt
        self._animate(dt)

        if self.kind == "scout":
            self.posY += self.vy * dt
            self.base_x += self.drift * dt
            if self.base_x < 70:
                self.base_x = 70
                self.drift = abs(self.drift)
            elif self.base_x > VW - 70:
                self.base_x = VW - 70
                self.drift = -abs(self.drift)
            self.posX = self.base_x + math.sin(self.time * 2.8 + self.phase) * 54
            if self.posY > 20:
                self.entered = True
        elif self.kind == "fighter":
            if self.posY < self.target_y:
                self.posY += self.vy * dt
            else:
                self.entered = True
                self.posY = self.target_y + math.sin(self.time * 1.7 + self.phase) * 16
                self.posX += math.sin(self.time * 1.15 + self.phase) * 76 * dt
                self.posX = clamp(self.posX, 70, VW - 70)
        elif self.kind == "bomber":
            if self.posY < self.target_y:
                self.posY += self.vy * dt
            else:
                self.entered = True
                self.posY = self.target_y + math.sin(self.time * 0.9 + self.phase) * 12
                self.posX += self.drift * 0.5 * dt
                if self.posX < 85:
                    self.posX = 85
                    self.drift = abs(self.drift)
                elif self.posX > VW - 85:
                    self.posX = VW - 85
                    self.drift = -abs(self.drift)
        elif self.kind == "raider":
            # Fast diagonal pass, then a wide arc back up and out.
            if self.posY < self.target_y and not self.entered:
                self.posY += self.vy * dt
                if self.posY >= self.target_y:
                    self.entered = True
                    self.vy *= 0.55
            else:
                self.entered = True
                self.posY = min(VH + 120, self.posY + self.vy * 0.42 * dt)
                self.posX += self.drift * 2.1 * dt
                if self.posX < 50:
                    self.posX = 50
                    self.drift = abs(self.drift)
                elif self.posX > VW - 50:
                    self.posX = VW - 50
                    self.drift = -abs(self.drift)
                if self.posY > VH + 100:
                    self.alive = False
        else:  # elite
            if self.posY < self.target_y:
                self.posY += self.vy * dt
            else:
                self.entered = True
                self.posY = self.target_y + math.sin(self.time * 0.7 + self.phase) * 18
                self.posX = (self.start_x + math.sin(self.time * 0.62 + self.phase) * 170)
                self.posX = clamp(self.posX, 100, VW - 100)

        if self.posY > VH + 140 or self.posX < -180 or self.posX > VW + 180:
            self.alive = False

        chainsaw_chasing = getattr(game, "chainsaw_chasing", False)
        if chainsaw_chasing and self.fire_timer <= 0:
            self.fire_timer = self.fire_range[1]
        if (self.fire_timer <= 0 and self.posY > 24 and self.entered
                and not chainsaw_chasing):
            self._fire(game)
            low, high = self.fire_range
            self.fire_timer = random.uniform(low, high) * self.balance.enemy_fire(
                self.wave
            )

    def _animate(self, dt):
        if len(self.frames) <= 1:
            return
        self.anim_timer += dt
        if self.anim_timer >= 0.15:
            self.anim_timer = 0.0
            self.frame_index = (self.frame_index + 1) % len(self.frames)
            self.image = self.frames[self.frame_index]

    # ---------------------------------------------------------------- fire
    def _fire(self, game):
        player = game.target_player(self.posX, self.posY)
        event = getattr(game, "meme_event", None)
        if event is not None and event.kind == "straw_boat":
            tx, ty, _progress = event._boat_position()
            boat_is_target = True
        else:
            tx = player.centerx if player.alive else VW * 0.5
            ty = player.centery if player.alive else VH
            boat_is_target = False
        base_angle = math.atan2(ty - self.posY, tx - self.posX)
        nose_y = self.posY + self.radius * 0.7
        speed = self.balance.bullet_speed(self.wave) * (
            320.0 if self.mode == "normal" else 340.0
        )

        if self.kind == "scout":
            game.spawn_enemy_bullet(self.posX, nose_y, base_angle, speed)
            game.effects.hit_sparks(self.posX, nose_y, game.enemy_bullet_color, count=3)
        elif self.kind == "fighter":
            for offset in (-0.20, 0.0, 0.20):
                game.spawn_enemy_bullet(self.posX, nose_y, base_angle + offset, speed * 0.95)
            game.effects.hit_sparks(self.posX, nose_y, game.enemy_bullet_color, count=5)
            game.audio.play("enemy_shot", 0.35, throttle_ms=60)
        elif self.kind == "bomber":
            for offset in (-0.5, -0.25, 0.0, 0.25, 0.5):
                game.spawn_enemy_bullet(
                    self.posX, nose_y,
                    (base_angle if boat_is_target else math.pi / 2) + offset,
                    speed * 0.78,
                    radius=7.0,
                )
            game.effects.hit_sparks(self.posX, nose_y, game.enemy_bullet_color, count=6)
            game.audio.play("enemy_shot", 0.45, throttle_ms=60)
        elif self.kind == "raider":
            self.attack_index += 1
            for offset in (-0.10, 0.10):
                game.spawn_enemy_bullet(
                    self.posX, nose_y, base_angle + offset, speed * 1.25,
                    radius=5.0,
                )
            game.effects.hit_sparks(self.posX, nose_y, game.enemy_bullet_color, count=4)
            game.audio.play("enemy_shot", 0.3, throttle_ms=45)
        else:  # elite
            self.attack_index += 1
            if self.attack_index % 3 == 0:
                # Telegraphed danger zone under the player's current position.
                self.charge = 0.85
                warn = self.balance.telegraph(1.20)
                game.spawn_danger_zone(
                    clamp(tx, 80, VW - 80), clamp(ty, 120, VH - 120),
                    radius=104, warn=warn, duration=1.5,
                )
                game.effects.ring(self.posX, self.posY, game.palette["danger"], 90, 0.5, 3)
                game.audio.play("boss_warn", 0.3, throttle_ms=350)
            else:
                total = 10
                for index in range(total):
                    angle = (base_angle if boat_is_target else self.time * 0.4)
                    angle += index / total * math.tau
                    game.spawn_enemy_bullet(
                        self.posX, self.posY, angle, speed * 0.7,
                        radius=6.0, kind="enemy_plasma",
                    )
                game.effects.hit_sparks(self.posX, nose_y, game.enemy_bullet_color, count=8)
                game.audio.play("enemy_shot", 0.5, throttle_ms=80)

    def damage(self, amount):
        self.hp -= amount
        self.flash_timer = 0.08
        if self.hp <= 0:
            self.alive = False
            return True
        return False

    def draw(self, surface, resources=None):
        tilt = -math.sin(self.time * 1.6 + self.phase) * 3.2
        step = int(round(tilt / 2.0)) * 2
        key = (self.frame_index, step)
        image = self._draw_cache.get(key)
        if image is None:
            image = self.image if step == 0 else pygame.transform.rotozoom(self.image, step, 1.0)
            if len(self._draw_cache) > 18:
                self._draw_cache.clear()
            self._draw_cache[key] = image
        rect = image.get_rect(center=(int(self.posX), int(self.posY)))
        if self.flash_timer > 0:
            if resources is not None:
                glow = resources.glow(int(self.radius * 1.4), (255, 255, 255), 140)
                surface.blit(glow, glow.get_rect(center=rect.center))
            image.set_alpha(145)
        surface.blit(image, rect)
        image.set_alpha(255)


class BossEnemy:
    """A multi-phase capital ship with telegraphed beams and danger zones.

    ``dreadnought`` alternates aimed fans and rings, adds a sweeping beam in
    phase two and zone barrages in phase three.  ``sentinel`` spins spiral
    volleys and crosses the arena with rotating beams.
    """

    KINDS = {
        "dreadnought": {
            "radius": 96,
            "hit_radius": 78,
            "name": "boss_dreadnought",
            "color": (255, 104, 84),
        },
        "sentinel": {
            "radius": 86,
            "hit_radius": 70,
            "name": "boss_sentinel",
            "color": (196, 134, 255),
        },
    }

    def __init__(self, mode, resources, wave, kind=None, balance=None):
        self.mode = mode
        self.resources = resources
        self.wave = wave
        self.balance = balance or _NORMAL_BALANCE
        self.kind = kind if kind in self.KINDS else boss_kind_for_wave(wave)
        stats = self.KINDS[self.kind]
        self.radius = stats["radius"]
        self.hit_radius = stats["hit_radius"]
        self.name_key = stats["name"]
        self.base_color = stats["color"]
        self.max_hp = self.balance.boss_hp(wave)
        self.hp = self.max_hp
        self.score = 2600 + wave * 130
        self.posX = VW * 0.5
        self.posY = -190.0
        self.target_y = 208.0 if self.kind == "dreadnought" else 198.0
        self.time = 0.0
        self.entered = False
        self.alive = True
        self.flash_timer = 0.0
        self.phase = 1
        self.phase_flash = 0.0
        self.charge = 0.0
        self.attack_timer = 1.5
        self.attack_index = 0
        self.attack_cycle = 0
        self.last_attack = None
        self._spawned = set()
        self.anim_timer = 0.0
        self.frame_index = 0
        self._draw_cache = {}

        frames = resources.boss_frames(self.kind) if resources is not None else None
        if frames:
            self.frames = frames
        else:
            sprite = resources.enemy_sprite("boss", mode) if resources is not None else None
            if sprite is None:
                sprite = pygame.Surface((260, 190), pygame.SRCALPHA)
                pygame.draw.ellipse(sprite, (220, 90, 110), sprite.get_rect())
            self.frames = [pygame.transform.smoothscale(sprite, (330, 248))]
        self.image = self.frames[0]

    # -------------------------------------------------------------- helpers
    @property
    def ratio(self):
        return self.hp / max(1, self.max_hp)

    @property
    def enraged(self):
        return self.phase >= 3

    def phase_key(self):
        return f"boss_phase_{self.phase}"

    def _aim_angle(self, game):
        event = getattr(game, "meme_event", None)
        if event is not None and event.kind == "straw_boat":
            target_x, target_y, _progress = event._boat_position()
        else:
            player = game.target_player(self.posX, self.posY)
            target_x = player.centerx if player.alive else VW * 0.5
            target_y = player.centery if player.alive else VH
        return math.atan2(target_y - self.posY, target_x - self.posX)

    def _animate(self, dt):
        if len(self.frames) <= 1:
            return
        self.anim_timer += dt
        if self.anim_timer >= 0.34:
            self.anim_timer = 0.0
            self.frame_index = (self.frame_index + 1) % len(self.frames)
            self.image = self.frames[self.frame_index]

    # --------------------------------------------------------------- update
    def update(self, dt, game):
        events = []
        self.time += dt
        self.flash_timer = max(0.0, self.flash_timer - dt)
        self.charge = max(0.0, self.charge - dt)
        self.phase_flash = max(0.0, self.phase_flash - dt)
        self._animate(dt)

        if not self.entered:
            self.posY += (128.0 if self.kind == "dreadnought" else 106.0) * dt
            if self.posY >= self.target_y:
                self.posY = self.target_y
                self.entered = True
                self.attack_timer = 1.2
            return events

        new_phase = 1 if self.ratio > 0.66 else 2 if self.ratio > 0.33 else 3
        if new_phase != self.phase:
            self.phase = new_phase
            self.phase_flash = 1.1
            self.attack_timer = min(self.attack_timer, 0.45)
            events.append(f"phase{new_phase}")
            if self.phase >= 2 and "minions" not in self._spawned:
                self._spawned.add("minions")
                game.spawn_boss_minions(self)
                events.append("minions")

        if self.kind == "dreadnought":
            self.posX = VW * 0.5 + math.sin(self.time * 0.62) * (VW * 0.5 - 210)
            self.posY = self.target_y + math.sin(self.time * 1.05) * 18
        else:
            self.posX = VW * 0.5 + math.sin(self.time * 0.48) * (VW * 0.5 - 230)
            self.posY = self.target_y + math.sin(self.time * 0.85) * 24

        self.attack_timer -= dt
        if self.attack_timer <= 0:
            self._choose_attack(game, events)
        return events

    # --------------------------------------------------------------- attacks
    def _choose_attack(self, game, events):
        p = self.phase
        if self.kind == "dreadnought":
            pools = {
                1: ("fan", "aimed"),
                2: ("fan", "ring", "beam_sweep"),
                3: ("ring", "beam_sweep", "zones", "aimed"),
            }
            pool = pools[min(3, p)]
        else:
            pools = {
                1: ("spiral", "aimed"),
                2: ("spiral", "cross_beam", "zones"),
                3: ("spiral", "cross_beam", "zones", "ring"),
            }
            pool = pools[min(3, p)]

        if len(pool) > 1 and pool[self.attack_cycle % len(pool)] == self.last_attack:
            self.attack_cycle += 1
        attack = pool[self.attack_cycle % len(pool)]
        self.attack_cycle += 1
        self.last_attack = attack
        getattr(self, "_attack_" + attack)(game, events)
        base = {1: 2.05, 2: 1.65, 3: 1.28}[p]
        if attack in ("beam_sweep", "cross_beam", "zones"):
            base += 0.75
        if attack == "ring":
            base += 0.25
        self.attack_timer = self.balance.boss_attack_delay(base) * random.uniform(0.9, 1.1)

    def _bullet_speed(self):
        return self.balance.boss_bullet_speed(
            300.0 if self.mode == "normal" else 320.0, self.wave
        )

    def _attack_fan(self, game, events):
        base = self._aim_angle(game)
        speed = self._bullet_speed()
        for offset in (-0.5, -0.25, 0.0, 0.25, 0.5):
            game.spawn_enemy_bullet(self.posX, self.posY + 76, base + offset, speed,
                                    radius=8.0, kind="enemy_plasma")
        game.effects.hit_sparks(self.posX, self.posY + 76,
                                game.enemy_bullet_color, count=8)
        game.effects.ring(self.posX, self.posY + 60, game.enemy_bullet_color, 60, 0.35, 2)
        game.audio.play("enemy_shot", 0.55, throttle_ms=80)

    def _attack_aimed(self, game, events):
        player = game.target_player(self.posX, self.posY)
        event = getattr(game, "meme_event", None)
        boat_is_target = event is not None and event.kind == "straw_boat"
        if not player.alive and not boat_is_target:
            self._attack_fan(game, events)
            return
        base = self._aim_angle(game)
        for offset in (-0.08, 0.0, 0.08):
            game.spawn_enemy_bullet(self.posX, self.posY + 70, base + offset,
                                    self._bullet_speed() * 1.2, radius=6.0,
                                    kind="enemy_orb")

    def _attack_ring(self, game, events):
        total = 16 if self.phase < 3 else 22
        speed = self._bullet_speed() * 0.72
        event = getattr(game, "meme_event", None)
        base_angle = (self._aim_angle(game)
                      if event is not None and event.kind == "straw_boat"
                      else self.time * 0.45)
        for index in range(total):
            angle = base_angle + index / total * math.tau
            game.spawn_enemy_bullet(self.posX, self.posY, angle, speed,
                                    radius=7.0, kind="enemy_plasma")
        game.effects.ring(self.posX, self.posY, game.enemy_bullet_color, 140, 0.55, 3)
        game.audio.play("enemy_shot", 0.65, throttle_ms=80)

    def _attack_spiral(self, game, events):
        arms = 3 if self.phase < 3 else 4
        speed = self._bullet_speed() * 0.66
        event = getattr(game, "meme_event", None)
        base_angle = (self._aim_angle(game)
                      if event is not None and event.kind == "straw_boat"
                      else self.time * 1.9)
        for index in range(arms):
            angle = base_angle + index * math.tau / arms
            game.spawn_enemy_bullet(self.posX, self.posY, angle, speed,
                                    radius=6.5, kind="enemy_orb")
            game.spawn_enemy_bullet(self.posX, self.posY, angle + math.pi, speed,
                                    radius=6.5, kind="enemy_orb")
        game.audio.play("enemy_shot", 0.4, throttle_ms=70)

    def _attack_beam_sweep(self, game, events):
        self.charge = 1.15
        base = math.pi / 2
        for direction in (-1, 1):
            game.spawn_beam(
                self.posX + direction * 54, self.posY + 66,
                base + direction * 0.42, warn=self.balance.telegraph(1.20),
                duration=0.55,
                width=22.0, sweep=direction * 0.42,
                color=(255, 120, 100) if self.mode == "normal" else (255, 140, 230),
            )
        events.append("beam")
        game.audio.play("boss_warn", 0.55, throttle_ms=260)

    def _attack_cross_beam(self, game, events):
        self.charge = 1.15
        for index in range(4):
            angle = self.time * 0.4 + index * math.pi / 2
            game.spawn_beam(
                self.posX, self.posY, angle, warn=self.balance.telegraph(1.25),
                duration=0.4,
                width=16.0, sweep=0.22 if index % 2 else -0.22,
                color=(200, 140, 255) if self.mode == "normal" else (255, 120, 230),
            )
        events.append("beam")
        game.audio.play("boss_warn", 0.5, throttle_ms=260)

    def _attack_zones(self, game, events):
        self.charge = 1.1
        event = getattr(game, "meme_event", None)
        if event is not None and event.kind == "straw_boat":
            target_x, target_y, _progress = event._boat_position()
        else:
            player = game.target_player(self.posX, self.posY)
            target_x, target_y = player.centerx, player.centery
        targets = [
            (target_x, target_y),
            (target_x + 220, target_y - 110),
            (target_x - 220, target_y - 110),
        ]
        for x, y in targets:
            game.spawn_danger_zone(
                clamp(x, 80, VW - 80), clamp(y, 120, VH - 130),
                radius=random.uniform(74, 100),
                warn=self.balance.telegraph(1.25), duration=1.6,
            )
        events.append("zones")
        game.audio.play("boss_warn", 0.45, throttle_ms=240)

    # ---------------------------------------------------------------- damage
    def damage(self, amount):
        self.hp -= amount
        self.flash_timer = 0.06
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
            return True
        return False

    def draw(self, surface, resources=None):
        pulse = 0.7 + math.sin(self.time * 4.2) * 0.3
        color = self.base_color
        if resources is not None:
            glow = resources.glow(120, color, int(45 + pulse * 65))
            surface.blit(glow, glow.get_rect(center=(int(self.posX), int(self.posY))))
        image = self.image
        if self.phase_flash > 0:
            key = ("flash", self.frame_index)
            image = self._draw_cache.get(key)
            if image is None:
                image = self.image.copy()
                image.fill((130, 90, 80, 0), special_flags=pygame.BLEND_RGBA_ADD)
                self._draw_cache[key] = image
        rect = image.get_rect(center=(int(self.posX), int(self.posY)))
        surface.blit(image, rect)

        if self.flash_timer > 0:
            core = resources.glow(52, (255, 255, 255), 150) if resources is not None else None
            if core is not None:
                surface.blit(core, core.get_rect(center=rect.center))

        if self.charge > 0:
            ratio = max(0.0, min(1.0, 1.0 - self.charge / 1.15))
            radius = int(self.radius + 38 * ratio)
            pygame.draw.circle(surface, self.base_color,
                               (int(self.posX), int(self.posY)), radius, 3)
            pygame.draw.circle(surface, (255, 236, 214),
                               (int(self.posX), int(self.posY)), max(6, radius - 9), 1)
