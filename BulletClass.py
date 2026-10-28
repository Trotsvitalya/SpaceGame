"""Player and enemy projectiles.

Bullets store their previous position so collision checks can use a swept
segment instead of a single point; that prevents tunneling on slower frames.
Player shots also carry weapon metadata (pierce, splash and sprite kind).
"""

from __future__ import annotations

import math

import pygame


class Bullet:
    def __init__(self, posX, posY, imageList=None, speed=920,
                 vx=0.0, vy=None, radius=8.0, damage=1, color=(255, 220, 120),
                 kind="pulse", sprite=None, pierce=0, splash=0.0, life=4.0):
        self.posX = float(posX)
        self.posY = float(posY)
        self.prev_x = self.posX
        self.prev_y = self.posY
        self.vx = float(vx)
        self.vy = float(-speed if vy is None else vy)
        self.speed = speed
        self.radius = radius
        self.damage = damage
        self.color = color
        self.kind = kind
        self.sprite = sprite
        self.pierce = max(0, int(pierce))
        self.splash = max(0.0, float(splash))
        self.hits = set()
        self.life = float(life)
        self.imageList = imageList or []
        self.imageNum = 0
        self.image = self.imageList[0] if self.imageList else None
        self.timeTick = 0
        self.timeTickMax = 8
        self.alive = True
        self._rotation_cache = {}

    def update(self, dt):
        self.prev_x = self.posX
        self.prev_y = self.posY
        self.posX += self.vx * dt
        self.posY += self.vy * dt
        self.life -= dt
        if self.life <= 0:
            self.alive = False
        if self.imageList:
            self.timeTick += 1
            if self.timeTick >= self.timeTickMax:
                self.timeTick = 0
                self.imageNum = (self.imageNum + 1) % len(self.imageList)
                self.image = self.imageList[self.imageNum]

    # Backwards-compatible name used by the original project.
    def update_position(self):
        self.update(1.0 / 60.0)

    def is_outside(self, width, height):
        return (self.posY < -40 or self.posX < -40 or
                self.posX > width + 40 or self.posY > height + 40)

    def _oriented(self):
        base = self.sprite if self.sprite is not None else self.image
        if base is None:
            return None
        if self.sprite is None:
            return base
        angle = -math.degrees(math.atan2(self.vx, -self.vy))
        step = int(round(angle / 6.0)) * 6
        if step == 0:
            return base
        cached = self._rotation_cache.get(step)
        if cached is None:
            cached = pygame.transform.rotozoom(base, step, 1.0)
            if len(self._rotation_cache) > 8:
                self._rotation_cache.clear()
            self._rotation_cache[step] = cached
        return cached

    def draw(self, surface):
        image = self._oriented()
        if image is not None:
            rect = image.get_rect(center=(int(self.posX), int(self.posY)))
            surface.blit(image, rect)
        else:
            pygame.draw.circle(surface, self.color, (int(self.posX), int(self.posY)),
                               int(self.radius))
        # Short motion streak so fast shots read clearly over busy backdrops.
        magnitude = math.hypot(self.vx, self.vy)
        if magnitude > 60:
            length = min(20.0, magnitude * 0.022)
            dx = self.vx / magnitude * length
            dy = self.vy / magnitude * length
            tail = (int(self.posX - dx), int(self.posY - dy))
            head = (int(self.posX), int(self.posY))
            pygame.draw.line(surface, self.color, tail, head,
                             max(1, int(self.radius * 0.35)))


class EnemyBullet:
    def __init__(self, posX, posY, vx, vy, radius=6.0, damage=1,
                 mode="normal", color=None, sprite=None, life=9.0,
                 kind="enemy_orb"):
        self.posX = float(posX)
        self.posY = float(posY)
        self.prev_x = self.posX
        self.prev_y = self.posY
        self.vx = float(vx)
        self.vy = float(vy)
        self.radius = radius
        self.damage = damage
        self.mode = mode
        self.kind = kind
        self.color = color or ((255, 120, 220) if mode == "meme" else (255, 92, 122))
        self.sprite = sprite
        self.life = life
        self.alive = True
        self._rotation_cache = {}

    def update(self, dt):
        self.prev_x = self.posX
        self.prev_y = self.posY
        self.posX += self.vx * dt
        self.posY += self.vy * dt
        self.life -= dt
        if self.life <= 0:
            self.alive = False

    def is_outside(self, width, height):
        return (self.posY < -60 or self.posX < -60 or
                self.posX > width + 60 or self.posY > height + 60)

    def _oriented(self):
        if self.sprite is None:
            return None
        angle = -math.degrees(math.atan2(self.vx, -self.vy))
        step = int(round(angle / 8.0)) * 8
        if step == 0:
            return self.sprite
        cached = self._rotation_cache.get(step)
        if cached is None:
            cached = pygame.transform.rotozoom(self.sprite, step, 1.0)
            if len(self._rotation_cache) > 8:
                self._rotation_cache.clear()
            self._rotation_cache[step] = cached
        return cached

    def draw(self, surface):
        image = self._oriented()
        if image is not None:
            rect = image.get_rect(center=(int(self.posX), int(self.posY)))
            surface.blit(image, rect)
        else:
            pygame.draw.circle(surface, self.color, (int(self.posX), int(self.posY)),
                               int(self.radius))
        # A short tail makes small projectiles readable on busy backgrounds.
        length = min(16.0, math.hypot(self.vx, self.vy) * 0.028)
        if length > 2:
            magnitude = max(1.0, math.hypot(self.vx, self.vy))
            dx = self.vx / magnitude * length
            dy = self.vy / magnitude * length
            pygame.draw.line(
                surface, self.color,
                (int(self.posX), int(self.posY)),
                (int(self.posX - dx), int(self.posY - dy)),
                2,
            )
