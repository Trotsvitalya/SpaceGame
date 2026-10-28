"""Collectible power-ups."""

from __future__ import annotations

import math
import random

import pygame

from utils import VH


class PowerUp:
    KINDS = ("shield", "life", "weapon", "rapid", "points")
    WEIGHTS = (26, 9, 27, 21, 17)
    COLORS = {
        "shield": (80, 190, 255),
        "life": (255, 92, 124),
        "weapon": (255, 200, 76),
        "rapid": (120, 255, 180),
        "points": (196, 130, 255),
    }

    def __init__(self, x, y, kind, mode="normal", resources=None):
        self.posX = float(x)
        self.posY = float(y)
        self.kind = kind if kind in self.KINDS else "points"
        self.mode = mode
        self.resources = resources
        self.radius = 17.0
        self.speed = 92.0
        self.time = random.uniform(0, math.tau)
        self.alive = True
        self.sprite = resources.powerup_sprite(self.kind, mode) if resources else None
        self.color = self.COLORS[self.kind]
        self.label = {
            "shield": "S",
            "life": "+",
            "weapon": "W",
            "rapid": "R",
            "points": "*",
        }[self.kind]

    @classmethod
    def random_kind(cls):
        return random.choices(cls.KINDS, weights=cls.WEIGHTS, k=1)[0]

    def update(self, dt):
        self.time += dt
        self.posY += self.speed * dt
        self.posX += math.sin(self.time * 2.1) * 28 * dt
        if self.posY > VH + 50:
            self.alive = False

    def draw(self, surface, resources=None):
        resources = resources or self.resources
        bob = math.sin(self.time * 3.0) * 4
        center = (int(self.posX), int(self.posY + bob))
        if resources:
            glow = resources.glow(30, self.color, 80)
            surface.blit(glow, glow.get_rect(center=center))
        if self.sprite:
            image = pygame.transform.rotozoom(self.sprite, math.sin(self.time * 2.0) * 8, 1.0)
            surface.blit(image, image.get_rect(center=center))
        else:
            pygame.draw.circle(surface, self.color, center, 16, 2)
            pygame.draw.circle(surface, self.color, center, 5)
        if resources:
            label = resources.text(self.label, 13, (12, 18, 32))
            surface.blit(label, label.get_rect(center=center))
