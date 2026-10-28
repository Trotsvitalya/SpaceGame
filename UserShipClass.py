"""The player's ship.

Movement is velocity based (pixels per second) so the handling is identical at
any frame rate.  The class also owns weapon/shield timers and the short
respawn sequence.
"""

from __future__ import annotations

import math

import pygame

from utils import clamp


class UserShip:
    MAX_SPEED = 390.0
    ACCELERATION = 3200.0
    FRICTION = 3800.0
    BASE_FIRE_INTERVAL = 0.17
    MAX_WEAPON_LEVEL = 3

    def __init__(self, posX, posY, maxW, maxH, imageList=None,
                 imageBoomList=None, height=78, width=78):
        self.posX = float(posX)
        self.posY = float(posY)
        self.maxW = maxW
        self.maxH = maxH
        self.width = width
        self.height = height
        self.speed = self.MAX_SPEED
        self.vx = 0.0
        self.vy = 0.0
        self.currentDirection = 0

        self.life = 3
        self.max_life = 5
        self.isBoom = False
        self.alive = True
        self.respawn_timer = 0.0
        self.invulnerable_timer = 2.0
        self.shield_timer = 0.0
        self.weapon_level = 1
        self.weapon_timer = 0.0
        self.rapid_timer = 0.0
        self.fire_cooldown = 0.0
        self.hit_radius = 19.0
        self.animation_time = 0.0
        self.bank = 0.0

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
        return self.BASE_FIRE_INTERVAL * (0.45 if self.rapid_timer > 0 else 1.0)

    # --------------------------------------------------------------- update
    def update(self, dt, move_x=0.0, move_y=0.0):
        events = []
        length = math.hypot(move_x, move_y)
        if length > 0:
            move_x /= length
            move_y /= length

        target_vx = move_x * self.MAX_SPEED
        target_vy = move_y * self.MAX_SPEED
        acceleration = self.ACCELERATION if length > 0 else self.FRICTION
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
            # Keep the ship clear of the top and bottom HUD panels.
            top_bound = 82
            bottom_bound = self.maxH - self.height - 82
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
            # Defensive fix for hand-edited state or a missed timer.
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

        self.bank = clamp(-self.vx / self.MAX_SPEED, -1.0, 1.0) * 11.0
        self._update_image(dt)
        return events

    def _update_image(self, dt):
        if not self.imageList:
            return
        self.animation_time += dt
        frame_time = 0.085 if (abs(self.vx) + abs(self.vy) > 20) else 0.13
        if self.animation_time >= frame_time:
            self.animation_time = 0.0
            self.imageNum = (self.imageNum + 1) % len(self.imageList)
            self.image = self.imageList[self.imageNum]

    # -------------------------------------------------------- combat state
    def revive(self):
        self.alive = True
        self.isBoom = False
        self.posX = self.maxW * 0.5 - self.width * 0.5
        self.posY = self.maxH - self.height - 82
        self.vx = self.vy = 0.0
        self.invulnerable_timer = 2.4
        self.respawn_timer = 0.0

    def take_hit(self):
        """Returns 'shield', 'dead', or 'none' (ignored while invulnerable)."""
        if not self.alive or self.invulnerable_timer > 0:
            return "none"
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
        """Consume the cooldown and return (offset_x, offset_y, vx, vy) shots."""
        if not self.can_fire():
            return []
        self.fire_cooldown = self.fire_interval
        y = self.posY + 4
        cx = self.centerx
        level = max(1, min(self.MAX_WEAPON_LEVEL, self.weapon_level))
        if level == 1:
            return [(cx, y, 0.0, -920.0)]
        if level == 2:
            return [(cx - 12, y + 8, -25.0, -930.0), (cx + 12, y + 8, 25.0, -930.0)]
        return [
            (cx, y - 4, 0.0, -960.0),
            (cx - 19, y + 10, -105.0, -920.0),
            (cx + 19, y + 10, 105.0, -920.0),
        ]

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

    # ---------------------------------------------------------------- draw
    def draw(self, surface, resources, time, mode="normal"):
        if not self.alive or self.image is None:
            return
        if self.invulnerable_timer > 0 and self.shield_timer <= 0:
            if int(self.invulnerable_timer * 14) % 2 == 0:
                return
        center = (int(self.centerx), int(self.centery))

        # Engine flame (procedural, flickering).
        flame_length = 19 + math.sin(time * 31.0) * 5 + abs(self.vy) * 0.025
        flame_color = (255, 156, 62) if mode == "normal" else (255, 110, 210)
        flame_inner = (255, 246, 190) if mode == "normal" else (255, 245, 120)
        base_y = self.posY + self.height - 8
        flicker = math.sin(time * 47.0) * 3
        pygame.draw.polygon(surface, flame_color, [
            (center[0] - 11, base_y),
            (center[0] + 11, base_y),
            (center[0] + flicker, base_y + flame_length),
        ])
        pygame.draw.polygon(surface, flame_inner, [
            (center[0] - 5, base_y),
            (center[0] + 5, base_y),
            (center[0] + flicker * 0.5, base_y + flame_length * 0.55),
        ])

        image = self.image
        if abs(self.bank) > 0.4:
            image = pygame.transform.rotozoom(image, self.bank, 1.0)
        rect = image.get_rect(center=center)
        if self.invulnerable_timer > 0:
            image.set_alpha(150)
        surface.blit(image, rect)
        image.set_alpha(255)

        if self.shield_timer > 0:
            pulse = 0.78 + math.sin(time * 7.0) * 0.12
            radius = int(44 * pulse)
            glow_color = (80, 200, 255) if mode == "normal" else (255, 130, 220)
            glow = resources.glow(radius, glow_color, 100)
            surface.blit(glow, glow.get_rect(center=center))
            pygame.draw.circle(surface, glow_color, center, radius, 2)
            pygame.draw.circle(surface, (230, 250, 255), center, radius - 4, 1)
