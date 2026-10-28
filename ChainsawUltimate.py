"""The paid chainsaw superpower: a brief screen split, then hunting saws."""

from __future__ import annotations

import math

import pygame

from utils import VH, VW, clamp


class ChainsawUltimate:
    SPLIT_DURATION = .72
    CHASE_DURATION = 9.0
    FINISH_DURATION = .32
    SAW_COUNT = 4
    SAW_SPEED = 700.0
    SAW_RADIUS = 21.0

    def __init__(self):
        self.phase = "idle"
        self.phase_time = 0.0
        self.elapsed = 0.0
        self.saws = []
        self.hit_targets = set()

    @property
    def active(self):
        return self.phase != "idle"

    @property
    def chasing(self):
        return self.phase == "chase"

    def start(self):
        if self.active:
            return False
        self.phase = "split"
        self.phase_time = self.elapsed = 0.0
        self.hit_targets.clear()
        self.saws = [[VW * .5, VH * .5, None] for _ in range(self.SAW_COUNT)]
        return True

    def cancel(self):
        self.phase = "idle"
        self.phase_time = self.elapsed = 0.0
        self.saws.clear()
        self.hit_targets.clear()

    def update(self, dt, targets):
        """Advance the effect; return (phase_event, targets_hit)."""
        if not self.active:
            return None, ()
        dt = min(max(float(dt), 0.0), .05)
        self.phase_time += dt
        self.elapsed += dt
        if self.phase == "split":
            if self.phase_time >= self.SPLIT_DURATION:
                self.phase = "chase"
                self.phase_time = 0.0
                return "chase", ()
            return None, ()
        if self.phase == "finish":
            if self.phase_time >= self.FINISH_DURATION:
                self.cancel()
                return "done", ()
            return None, ()

        targets = [target for target in targets if target.alive]
        if self.elapsed >= self.SPLIT_DURATION + self.CHASE_DURATION or not targets:
            self.phase = "finish"
            self.phase_time = 0.0
            return "finish", ()

        hits = []
        reserved = set()
        for saw in self.saws:
            x, y, target = saw
            if (target is None or not target.alive
                    or id(target) in self.hit_targets):
                saw[2] = target = None
            elif id(target) in reserved:
                saw[2] = target = None
            if target is None:
                choices = [item for item in targets
                           if id(item) not in self.hit_targets
                           and id(item) not in reserved]
                if not choices:
                    continue
                target = min(choices, key=lambda item:
                             math.hypot(item.posX - x, item.posY - y))
                saw[2] = target
            reserved.add(id(target))
            dx, dy = target.posX - x, target.posY - y
            distance = max(1.0, math.hypot(dx, dy))
            step = self.SAW_SPEED * dt
            if distance <= step + target.hit_radius + self.SAW_RADIUS:
                self.hit_targets.add(id(target))
                hits.append(target)
                saw[2] = None
            else:
                saw[0] += dx / distance * step
                saw[1] += dy / distance * step
        return None, tuple(hits)

    def flee(self, target, dt):
        """Push enemies away from nearby saws while the chase is active."""
        if not self.chasing:
            return
        for x, y, _assigned in self.saws:
            dx, dy = target.posX - x, target.posY - y
            distance = math.hypot(dx, dy)
            radius = 270.0
            if 1.0 < distance < radius:
                strength = 240.0 + 180.0 * (1.0 - distance / radius)
                target.posX += dx / distance * strength * dt
                target.posY += dy / distance * strength * dt
        target.posX = clamp(target.posX, target.radius + 8, VW - target.radius - 8)
        target.posY = clamp(target.posY, target.radius + 74, VH - target.radius - 60)

    def draw(self, surface):
        if not self.active:
            return
        if self.phase == "split":
            self._draw_split(surface)
        elif self.phase == "chase":
            self._draw_saws(surface)
        elif self.phase == "finish":
            alpha = int(110 * max(0.0, 1.0 - self.phase_time / self.FINISH_DURATION))
            layer = pygame.Surface((VW, VH), pygame.SRCALPHA)
            pygame.draw.line(layer, (255, 155, 65, alpha), (0, VH // 2),
                             (VW, VH // 2), max(2, int(18 * alpha / 110)))
            surface.blit(layer, (0, 0))

    def _draw_split(self, surface):
        progress = min(1.0, self.phase_time / self.SPLIT_DURATION)
        displacement = int(32 * math.sin(progress * math.pi))
        original = surface.copy()
        half = VH // 2
        surface.blit(original, (0, -displacement), (0, 0, VW, half))
        surface.blit(original, (0, half + displacement),
                     (0, half, VW, VH - half))
        layer = pygame.Surface((VW, VH), pygame.SRCALPHA)
        alpha = int(205 * (1.0 - progress * .35))
        pygame.draw.line(layer, (255, 92, 36, alpha), (0, half), (VW, half), 28)
        pygame.draw.line(layer, (255, 244, 190, min(255, alpha + 45)),
                         (0, half), (VW, half), 5)
        blade_x = int(progress * (VW + 100) - 50)
        self._draw_saw(layer, blade_x, half, progress * 28, alpha)
        surface.blit(layer, (0, 0))

    def _draw_saws(self, surface):
        layer = pygame.Surface((VW, VH), pygame.SRCALPHA)
        for index, (x, y, target) in enumerate(self.saws):
            if target is not None and target.alive:
                pygame.draw.line(layer, (255, 100, 35, 100),
                                 (x, y), (target.posX, target.posY), 3)
            self._draw_saw(layer, x, y, self.elapsed * 24 + index, 255)
        surface.blit(layer, (0, 0))

    @classmethod
    def _draw_saw(cls, surface, x, y, angle, alpha):
        center = (int(x), int(y))
        radius = cls.SAW_RADIUS
        pygame.draw.circle(surface, (255, 168, 48, alpha), center, radius + 6, 5)
        pygame.draw.circle(surface, (220, 230, 236, alpha), center, radius, 4)
        for tooth in range(12):
            a = angle + tooth * math.tau / 12
            start = (x + math.cos(a) * (radius - 2),
                     y + math.sin(a) * (radius - 2))
            end = (x + math.cos(a + .08) * (radius + 5),
                   y + math.sin(a + .08) * (radius + 5))
            pygame.draw.line(surface, (255, 245, 205, alpha), start, end, 4)
        pygame.draw.rect(surface, (255, 126, 36, alpha),
                         (int(x - 36), int(y - 10), 25, 20), border_radius=6)

