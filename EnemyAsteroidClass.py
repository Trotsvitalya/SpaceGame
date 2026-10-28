"""Enemies: asteroids, three ship archetypes and a wave boss."""

from __future__ import annotations

import math
import random

import pygame

from utils import VH, VW, clamp


class EnemyAsteroid:
    """A drifting, rotating asteroid.

    The original constructor signature is preserved, so existing callers can
    still create asteroids from raw image surfaces.
    """

    def __init__(self, maxW, maxH, image, imageBoomList=None, x=None, y=None,
                 radius=None, speed_scale=1.0, level="large"):
        self.maxW = maxW
        self.maxH = maxH
        self.level = level
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
        self.kind = "asteroid"
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
        image = pygame.transform.rotozoom(self.base_image, self.angle, 1.0)
        rect = image.get_rect(center=(int(self.posX), int(self.posY)))
        if self.flash_timer > 0:
            image.set_alpha(135)
        surface.blit(image, rect)
        image.set_alpha(255)


class EnemyShip:
    """Fast scout, hovering fighter and slow spread-firing bomber."""

    STATS = {
        "scout": {"radius": 21, "hp": 2, "score": 150, "sprite": (74, 74)},
        "fighter": {"radius": 27, "hp": 4, "score": 250, "sprite": (86, 86)},
        "bomber": {"radius": 34, "hp": 8, "score": 420, "sprite": (108, 94)},
    }

    def __init__(self, kind, mode, resources, x=None, y=-70, wave=1):
        stats = self.STATS.get(kind, self.STATS["scout"])
        self.kind = kind
        self.mode = mode
        self.radius = stats["radius"]
        self.hit_radius = self.radius * 0.72
        self.max_hp = max(1, int(round(stats["hp"] * (1.0 + 0.055 * (wave - 1)))))
        self.hp = self.max_hp
        self.score = stats["score"]
        self.posX = float(x if x is not None else random.randint(80, VW - 80))
        self.posY = float(y)
        self.base_x = self.posX
        self.target_y = 120 if kind == "fighter" else 96 if kind == "bomber" else -80
        self.vy = {"scout": 155.0, "fighter": 120.0, "bomber": 82.0}.get(kind, 140.0)
        self.vy *= 1.0 + 0.025 * (wave - 1)
        self.phase = random.uniform(0, math.tau)
        self.time = 0.0
        self.drift = random.uniform(-40, 40)
        self.fire_timer = random.uniform(0.9, 2.0)
        self.alive = True
        self.flash_timer = 0.0
        self.entered = False
        self.sprite = resources.enemy_sprite(kind, mode)
        self.image = self.sprite

    def update(self, dt, game):
        self.time += dt
        self.flash_timer = max(0.0, self.flash_timer - dt)
        self.fire_timer -= dt

        if self.kind == "scout":
            self.posY += self.vy * dt
            self.base_x += self.drift * dt
            if self.base_x < 70:
                self.base_x = 70
                self.drift = abs(self.drift)
            elif self.base_x > VW - 70:
                self.base_x = VW - 70
                self.drift = -abs(self.drift)
            self.posX = self.base_x + math.sin(self.time * 2.6 + self.phase) * 62
        elif self.kind == "fighter":
            if self.posY < self.target_y:
                self.posY += self.vy * dt
            else:
                self.entered = True
                self.posY = self.target_y + math.sin(self.time * 1.7 + self.phase) * 16
                self.posX += math.sin(self.time * 1.15 + self.phase) * 74 * dt
                self.posX = clamp(self.posX, 70, VW - 70)
        else:  # bomber
            if self.posY < self.target_y:
                self.posY += self.vy * dt
            else:
                self.entered = True
                self.posY = self.target_y + math.sin(self.time * 0.9 + self.phase) * 11
                self.posX += self.drift * 0.45 * dt
                if self.posX < 85:
                    self.posX = 85
                    self.drift = abs(self.drift)
                elif self.posX > VW - 85:
                    self.posX = VW - 85
                    self.drift = -abs(self.drift)

        if self.posY > VH + 120 or self.posX < -160 or self.posX > VW + 160:
            self.alive = False

        if self.fire_timer <= 0 and self.posY > 30:
            self._fire(game)
            if self.kind == "scout":
                self.fire_timer = max(0.9, 1.85 - game.wave * 0.035)
            elif self.kind == "fighter":
                self.fire_timer = max(1.25, 2.25 - game.wave * 0.04)
            else:
                self.fire_timer = max(1.65, 2.8 - game.wave * 0.04)

    def _fire(self, game):
        player = game.player
        tx = player.centerx if player.alive else VW * 0.5
        ty = player.centery if player.alive else VH
        base_angle = math.atan2(ty - self.posY, tx - self.posX)
        nose_y = self.posY + self.radius * 0.7
        speed = (340.0 if self.mode == "meme" else 320.0) + game.wave * 7.0
        if self.kind == "scout":
            game.spawn_enemy_bullet(self.posX, nose_y, base_angle, speed)
            game.effects.hit_sparks(self.posX, nose_y, game.enemy_bullet_color, count=3)
        elif self.kind == "fighter":
            for offset in (-0.22, 0.0, 0.22):
                game.spawn_enemy_bullet(self.posX, nose_y, base_angle + offset, speed * 0.95)
            game.effects.hit_sparks(self.posX, nose_y, game.enemy_bullet_color, count=5)
            game.audio.play("enemy_shot", 0.35, throttle_ms=60)
        else:
            for offset in (-0.5, -0.25, 0.0, 0.25, 0.5):
                game.spawn_enemy_bullet(
                    self.posX, nose_y, math.pi / 2 + offset, speed * 0.8,
                    radius=7.0,
                )
            game.effects.hit_sparks(self.posX, nose_y, game.enemy_bullet_color, count=6)
            game.audio.play("enemy_shot", 0.45, throttle_ms=60)

    def damage(self, amount):
        self.hp -= amount
        self.flash_timer = 0.08
        if self.hp <= 0:
            self.alive = False
            return True
        return False

    def draw(self, surface, resources=None):
        tilt = -math.sin(self.time * 1.6 + self.phase) * 3.0
        image = self.sprite
        if abs(tilt) > 0.3:
            image = pygame.transform.rotozoom(self.sprite, tilt, 1.0)
        rect = image.get_rect(center=(int(self.posX), int(self.posY)))
        if self.flash_timer > 0:
            glow = resources.glow(int(self.radius * 1.25), (255, 255, 255), 150) if resources else None
            if glow:
                surface.blit(glow, glow.get_rect(center=rect.center))
            image.set_alpha(150)
        surface.blit(image, rect)
        image.set_alpha(255)


class BossEnemy:
    """A multi-pattern dreadnought that appears every fifth wave."""

    def __init__(self, mode, resources, wave):
        self.kind = "boss"
        self.mode = mode
        self.resources = resources
        self.radius = 82
        self.hit_radius = 72
        self.max_hp = 100 + wave * 9
        self.hp = self.max_hp
        self.score = 2500 + wave * 100
        self.posX = VW * 0.5
        self.posY = -150.0
        self.target_y = 228.0
        self.time = 0.0
        self.entered = False
        self.alive = True
        self.flash_timer = 0.0
        self.pattern = "fan"
        self.pattern_timer = 4.6
        self.fire_timer = 1.1
        self.ring_timer = 2.2
        self.minions_spawned = False
        self.sprite = resources.enemy_sprite("boss", mode)
        self.wave = wave

    @property
    def enraged(self):
        return self.hp <= self.max_hp * 0.42

    def update(self, dt, game):
        self.time += dt
        self.flash_timer = max(0.0, self.flash_timer - dt)
        if not self.entered:
            self.posY += 105 * dt
            if self.posY >= self.target_y:
                self.posY = self.target_y
                self.entered = True
            return

        self.posX = VW * 0.5 + math.sin(self.time * 0.68) * (VW * 0.5 - 190)
        self.posY = self.target_y + math.sin(self.time * 1.1) * 18

        if not self.minions_spawned and self.hp <= self.max_hp * 0.62:
            self.minions_spawned = True
            game.spawn_boss_minions(self)

        speed_mult = 0.68 if self.enraged else 1.0
        self.pattern_timer -= dt
        if self.pattern_timer <= 0:
            self.pattern = "ring" if self.pattern == "fan" else "fan"
            self.pattern_timer = 4.4 * speed_mult
            self.fire_timer = min(self.fire_timer, 0.4)
            self.ring_timer = min(self.ring_timer, 0.5)

        self.fire_timer -= dt
        self.ring_timer -= dt
        if self.pattern == "fan" and self.fire_timer <= 0:
            self._fire_fan(game)
            self.fire_timer = (0.95 if not self.enraged else 0.65)
        if self.pattern == "ring" and self.ring_timer <= 0:
            self._fire_ring(game)
            self.ring_timer = (2.1 if not self.enraged else 1.45)

        # A steady aimed tracer keeps pressure on even in ring phase.
        if self.fire_timer <= 0 and self.pattern == "ring":
            self._fire_aimed(game)
            self.fire_timer = 1.15

    def _fire_fan(self, game):
        player = game.player
        base = math.atan2(player.centery - self.posY, player.centerx - self.posX)
        speed = (335.0 if self.mode == "meme" else 310.0) + self.wave * 6.0
        for offset in (-0.5, -0.25, 0.0, 0.25, 0.5):
            game.spawn_enemy_bullet(self.posX, self.posY + 74, base + offset, speed, radius=8)
        game.effects.hit_sparks(self.posX, self.posY + 74, game.enemy_bullet_color, count=8)
        game.audio.play("enemy_shot", 0.55, throttle_ms=80)
        game.effects.ring(self.posX, self.posY + 60, game.enemy_bullet_color, 60, 0.35, 2)

    def _fire_ring(self, game):
        total = 16 if not self.enraged else 20
        speed = (235.0 if self.mode == "meme" else 215.0) + self.wave * 4.0
        for index in range(total):
            angle = index / total * math.tau + self.time * 0.45
            game.spawn_enemy_bullet(self.posX, self.posY + 10, angle, speed, radius=7)
        game.effects.ring(self.posX, self.posY, game.enemy_bullet_color, 130, 0.55, 3)
        game.audio.play("enemy_shot", 0.65, throttle_ms=80)

    def _fire_aimed(self, game):
        player = game.player
        if not player.alive:
            return
        angle = math.atan2(player.centery - self.posY, player.centerx - self.posX)
        game.spawn_enemy_bullet(self.posX, self.posY + 74, angle, 390, radius=7)

    def damage(self, amount):
        self.hp -= amount
        self.flash_timer = 0.06
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
            return True
        return False

    def draw(self, surface, resources=None):
        pulse = 0.75 + math.sin(self.time * 4.2) * 0.25
        color = (255, 100, 90) if self.mode == "normal" else (255, 100, 220)
        if resources:
            glow = resources.glow(112, color, int(55 + pulse * 70))
            surface.blit(glow, glow.get_rect(center=(int(self.posX), int(self.posY))))
        rect = self.sprite.get_rect(center=(int(self.posX), int(self.posY)))
        if self.flash_timer > 0:
            surface.blit(self.sprite, rect)
            pygame.draw.circle(surface, (255, 255, 255), (int(self.posX), int(self.posY)), 22)
        else:
            surface.blit(self.sprite, rect)
