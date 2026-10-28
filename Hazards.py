"""Telegraphed hazards: danger zones and charged beam attacks.

Both hazards have a generous warning phase, then a short damaging window, so
strong attacks stay readable and avoidable.
"""

from __future__ import annotations

import math

import pygame

from utils import VH, VW


class DangerZone:
    __slots__ = ("x", "y", "radius", "warn", "duration", "age", "color",
                 "alive", "hit_player")

    def __init__(self, x, y, radius=96.0, warn=1.15, duration=1.8,
                 color=(255, 92, 100)):
        self.x = float(x)
        self.y = float(y)
        self.radius = float(radius)
        self.warn = float(warn)
        self.duration = float(duration)
        self.age = 0.0
        self.color = color
        self.alive = True
        self.hit_player = False

    @property
    def active(self):
        return self.age >= self.warn

    @property
    def remaining(self):
        return max(0.0, self.warn + self.duration - self.age)

    def update(self, dt):
        self.age += dt
        if self.age >= self.warn + self.duration:
            self.alive = False

    def contains(self, x, y, extra=0.0):
        return math.hypot(x - self.x, y - self.y) <= self.radius + extra

    def draw(self, surface, palette=None):
        color = self.color
        if not self.active:
            progress = min(1.0, self.age / max(0.05, self.warn))
            # Fill inward while the warning counts down.
            fill_radius = int(self.radius * progress)
            pygame.draw.circle(surface, (54, 18, 28),
                               (int(self.x), int(self.y)), int(self.radius))
            pygame.draw.circle(surface, (120, 36, 44),
                               (int(self.x), int(self.y)), fill_radius)
            pygame.draw.circle(surface, color,
                               (int(self.x), int(self.y)), int(self.radius), 3)
            pygame.draw.circle(surface, (255, 210, 160),
                               (int(self.x), int(self.y)), int(self.radius) - 6, 1)
            for index in range(4):
                angle = index * math.pi / 2 + self.age * 1.5
                x1 = self.x + math.cos(angle) * (self.radius - 12)
                y1 = self.y + math.sin(angle) * (self.radius - 12)
                x2 = self.x + math.cos(angle) * (self.radius + 2)
                y2 = self.y + math.sin(angle) * (self.radius + 2)
                pygame.draw.line(surface, color, (int(x1), int(y1)),
                                 (int(x2), int(y2)), 3)
        else:
            remaining = max(0.0, 1.0 - (self.age - self.warn) / max(0.05, self.duration))
            outer = int(self.radius)
            pygame.draw.circle(surface, (72, 14, 22),
                               (int(self.x), int(self.y)), outer)
            pygame.draw.circle(surface, (150, 40, 50),
                               (int(self.x), int(self.y)), max(2, int(outer * remaining)))
            pygame.draw.circle(surface, (255, 168, 120),
                               (int(self.x), int(self.y)), outer, 2)


class BeamAttack:
    __slots__ = ("x", "y", "angle", "warn", "duration", "length", "width",
                 "age", "sweep", "color", "alive", "hit_player")

    def __init__(self, x, y, angle, warn=1.0, duration=0.38, length=1400.0,
                 width=18.0, sweep=0.0, color=(255, 120, 100)):
        self.x = float(x)
        self.y = float(y)
        self.angle = float(angle)
        self.warn = float(warn)
        self.duration = float(duration)
        self.length = float(length)
        self.width = float(width)
        self.age = 0.0
        self.sweep = float(sweep)
        self.color = color
        self.alive = True
        self.hit_player = False

    @property
    def active(self):
        return self.warn <= self.age < self.warn + self.duration

    def update(self, dt):
        self.age += dt
        if self.age >= self.warn + self.duration:
            self.alive = False
        elif self.active and self.sweep:
            self.angle += self.sweep * dt

    def endpoints(self, extension=1.0):
        dx = math.cos(self.angle) * self.length * extension
        dy = math.sin(self.angle) * self.length * extension
        return (self.x, self.y), (self.x + dx, self.y + dy)

    def hits(self, px, py, radius=0.0):
        if not self.active:
            return False
        (x1, y1), (x2, y2) = self.endpoints()
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 0:
            return False
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
        cx = x1 + t * dx
        cy = y1 + t * dy
        return math.hypot(px - cx, py - cy) <= self.width * 0.5 + radius

    def draw(self, surface):
        start, end = self.endpoints()
        if not self.active:
            progress = min(1.0, self.age / max(0.05, self.warn))
            pygame.draw.line(surface, (110, 40, 52),
                             (int(start[0]), int(start[1])),
                             (int(end[0]), int(end[1])), 2)
            # Dotted warning line.
            steps = 16
            for index in range(steps):
                if index % 2:
                    continue
                t0 = (index / steps) * progress
                t1 = ((index + 1) / steps) * progress
                pygame.draw.line(
                    surface, self.color,
                    (int(start[0] + (end[0] - start[0]) * t0),
                     int(start[1] + (end[1] - start[1]) * t0)),
                    (int(start[0] + (end[0] - start[0]) * t1),
                     int(start[1] + (end[1] - start[1]) * t1)),
                    3,
                )
            pygame.draw.circle(surface, self.color,
                               (int(start[0]), int(start[1])),
                               max(4, int(12 * progress)), 2)
        else:
            remaining = max(0.0, min(1.0, (self.age - self.warn) / max(0.05, self.duration)))
            width = max(2, int(self.width * (0.6 + 0.4 * remaining)))
            pygame.draw.line(surface, (110, 30, 40),
                             (int(start[0]), int(start[1])),
                             (int(end[0]), int(end[1])), width + 8)
            pygame.draw.line(surface, self.color,
                             (int(start[0]), int(start[1])),
                             (int(end[0]), int(end[1])), width)
            pygame.draw.line(surface, (255, 246, 236),
                             (int(start[0]), int(start[1])),
                             (int(end[0]), int(end[1])), max(2, width // 3))


def clamp_to_screen(x, y, radius=0):
    return (max(radius, min(VW - radius, x)),
            max(radius, min(VH - radius, y)))
