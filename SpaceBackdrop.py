"""Layered, cached space backdrop used by the menu and gameplay.

The expensive parts (tinted background, planets, nebula) are prepared once per
zone.  Every frame only blits those surfaces and moves a handful of star and
dust particles, which keeps the parallax affordable even on integrated GPUs.
"""

from __future__ import annotations

import math
import random

import pygame

from GameData import ZONES, zone_index_for_wave
from utils import VH, VW


class _Star:
    __slots__ = ("x", "y", "speed", "size", "brightness", "phase")

    def __init__(self, x, y, speed, size, brightness, phase):
        self.x = x
        self.y = y
        self.speed = speed
        self.size = size
        self.brightness = brightness
        self.phase = phase


class _Comet:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "length", "color")

    def __init__(self, x, y, vx, vy, life, length, color):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.length = length
        self.color = color


class SpaceBackdrop:
    STAR_LAYERS = (
        (58, 20.0, 1, 0.55),
        (44, 42.0, 1, 0.78),
        (28, 78.0, 2, 1.0),
        (14, 132.0, 2, 1.0),
    )

    def __init__(self, resources, mode="normal", zone=None, seed=None,
                 quality=None, planet_scale=1.0):
        self.resources = resources
        self.mode = mode if mode in ("normal", "meme") else "normal"
        self.quality = quality
        if self.quality is None:
            self.quality = getattr(resources.settings, "effects_quality", 2)
        self.quality = max(0, min(2, int(self.quality)))
        self.rng = random.Random(seed)
        self.planet_scale = planet_scale
        self.time = 0.0
        self.bg_offset = 0.0
        self.nebula_offset = 0.0
        self.zone_index = 0 if zone is None else int(zone)
        self._zone_fade = 0.0
        self._fade_surface = None
        self._planet_cache = {}
        self._dust_sprites = self._build_dust()
        self.stars = []
        self.dust = []
        self.comets = []
        self.comet_timer = self.rng.uniform(5.0, 10.0)
        self._build_stars()
        self._build_zone(fade=False)

    # ------------------------------------------------------------- construction
    def _build_stars(self):
        count_scale = (0.42, 0.72, 1.0)[self.quality]
        self.stars = []
        for count, speed, size, brightness in self.STAR_LAYERS:
            for _ in range(max(3, int(count * count_scale))):
                self.stars.append(_Star(
                    self.rng.uniform(0, VW), self.rng.uniform(0, VH),
                    speed, size, brightness, self.rng.uniform(0, math.tau),
                ))
        self.dust = []
        for _ in range(max(6, int(34 * count_scale))):
            self.dust.append([
                self.rng.uniform(0, VW), self.rng.uniform(0, VH),
                self.rng.uniform(55, 110), self.rng.choice((2, 3, 4)),
                self.rng.uniform(0.25, 0.55),
            ])

    def _build_dust(self):
        sprites = []
        for base in (4, 7, 10):
            surface = pygame.Surface((base * 2, base * 2), pygame.SRCALPHA)
            for step in range(base, 0, -1):
                alpha = int(70 * (1.0 - step / (base + 1)) ** 1.4)
                if alpha <= 0:
                    continue
                pygame.draw.circle(surface, (190, 220, 255, alpha), (base, base), step)
            sprites.append(surface)
        return sprites

    def _build_zone(self, fade=True):
        zone = ZONES[self.zone_index % len(ZONES)]
        self.zone = zone
        self.background = self.resources.zone_background(
            self.zone_index, self.mode
        )
        # Planet placement is seeded by the zone so every run looks consistent.
        rng = random.Random(1000 + self.zone_index * 17 + (0 if self.mode == "normal" else 3))
        self.planets = []
        primary_size = int((360 + rng.randint(0, 90)) * self.planet_scale)
        primary = self.resources.planet(zone["planet"], primary_size)
        if primary is not None:
            self._planet_cache[primary_size] = primary
            self.planets.append({
                "image": primary,
                "x": VW - primary_size * 0.52 + rng.randint(-40, 30),
                "y": -primary_size * 0.20 + rng.randint(-30, 40),
                "bob": rng.uniform(0.0, math.tau),
                "amplitude": rng.uniform(4.0, 9.0),
                "alpha": 155 if self.mode == "normal" else 135,
                "glow": self.resources.glow(
                    primary_size // 2, zone["accent"], 34
                ),
            })
        moon_size = int(92 * self.planet_scale)
        moon = self.resources.planet("azure" if zone["planet"] != "meme" else "meme", moon_size)
        if moon is not None:
            self.planets.append({
                "image": moon,
                "x": 170 + rng.randint(-40, 60),
                "y": 120 + rng.randint(-30, 40),
                "bob": rng.uniform(0.0, math.tau),
                "amplitude": 5.0,
                "alpha": 95,
                "glow": None,
            })
        self.zone_accent = zone["accent"]
        self.star_color = zone["meme_stars"] if self.mode == "meme" else zone["stars"]
        if not fade:
            self._zone_fade = 0.0
        else:
            self._zone_fade = 1.0
            tint = zone["accent"]
            self._fade_surface = pygame.Surface((VW, VH), pygame.SRCALPHA)
            self._fade_surface.fill((*tint, 255))

    # ------------------------------------------------------------------ public
    def set_zone(self, index, fade=True):
        index %= len(ZONES)
        if index == self.zone_index:
            return
        self.zone_index = index
        self._build_zone(fade=fade)

    def set_wave_zone(self, wave):
        self.set_zone(zone_index_for_wave(wave))

    def set_quality(self, quality):
        quality = max(0, min(2, int(quality)))
        if quality == self.quality:
            return
        self.quality = quality
        self._build_stars()

    @property
    def star_tint(self):
        return self.star_color

    # ------------------------------------------------------------------ update
    def update(self, dt, boost=0.0, speed_scale=1.0):
        if dt <= 0:
            return
        self.time += dt
        self._zone_fade = max(0.0, self._zone_fade - dt * 1.15)
        factor = 1.0 + max(0.0, boost) / 420.0
        for star in self.stars:
            star.y += star.speed * factor * speed_scale * dt
            if star.y > VH + 2:
                star.y -= VH + 4
                star.x = self.rng.uniform(0, VW)
        for particle in self.dust:
            particle[1] += particle[2] * factor * speed_scale * dt
            if particle[1] > VH + 8:
                particle[1] = -8
                particle[0] = self.rng.uniform(0, VW)
        self.bg_offset = (self.bg_offset + 9.0 * speed_scale * dt) % VH
        self.nebula_offset = (self.nebula_offset + 5.0 * speed_scale * dt) % VH

        self.comet_timer -= dt
        if self.comet_timer <= 0 and len(self.comets) < 2:
            self._spawn_comet()
            self.comet_timer = self.rng.uniform(7.0, 16.0)
        for comet in self.comets:
            comet.x += comet.vx * dt
            comet.y += comet.vy * dt
            comet.life -= dt
        self.comets = [comet for comet in self.comets if comet.life > 0]

    def _spawn_comet(self):
        from_left = self.rng.random() < 0.55
        speed = self.rng.uniform(220, 360)
        angle = self.rng.uniform(0.25, 0.55)
        vx = math.cos(angle) * speed * (1 if from_left else -1)
        vy = math.sin(angle) * speed
        if from_left:
            x = self.rng.uniform(-160, VW * 0.35)
        else:
            x = self.rng.uniform(VW * 0.65, VW + 160)
        self.comets.append(_Comet(
            x, self.rng.uniform(-70, VH * 0.35),
            vx, vy, self.rng.uniform(1.2, 2.0),
            self.rng.uniform(46, 92),
            (255, 238, 206) if self.mode == "normal" else (255, 190, 240),
        ))

    # -------------------------------------------------------------------- draw
    def draw(self, surface):
        surface.blit(self.background, (0, 0))

        if self.quality >= 1:
            nebula = self.resources.nebula(self.mode)
            nebula.set_alpha(44 if self.quality >= 2 else 28)
            y = int(self.nebula_offset)
            surface.blit(nebula, (0, y - VH))
            surface.blit(nebula, (0, y))
            nebula.set_alpha(255)

        for planet in self.planets:
            bob = math.sin(self.time * 0.22 + planet["bob"]) * planet["amplitude"]
            position = (int(planet["x"]), int(planet["y"] + bob))
            if planet["glow"] is not None:
                glow = planet["glow"]
                glow_position = (position[0] + planet["image"].get_width() // 2,
                                 position[1] + planet["image"].get_height() // 2)
                surface.blit(glow, glow.get_rect(center=glow_position),
                             special_flags=pygame.BLEND_RGBA_ADD)
            image = planet["image"]
            image.set_alpha(planet["alpha"])
            surface.blit(image, position)
            image.set_alpha(255)

        self._draw_stars(surface)
        self._draw_dust(surface)
        self._draw_comets(surface)

        if self._zone_fade > 0 and self._fade_surface is not None:
            self._fade_surface.set_alpha(int(70 * self._zone_fade))
            surface.blit(self._fade_surface, (0, 0))

    def _draw_stars(self, surface):
        boost = 0.0
        for star in self.stars:
            twinkle = 0.72 + 0.28 * math.sin(self.time * 2.1 + star.phase)
            value = star.brightness * twinkle
            color = (
                int(self.star_color[0] * value),
                int(self.star_color[1] * value),
                int(self.star_color[2] * value),
            )
            x = int(star.x)
            y = int(star.y)
            if star.size <= 1:
                if 0 <= x < VW and 0 <= y < VH:
                    surface.set_at((x, y), color)
            else:
                pygame.draw.circle(surface, color, (x, y), star.size)

    def _draw_dust(self, surface):
        for x, y, speed, size, brightness in self.dust:
            sprite = self._dust_sprites[min(len(self._dust_sprites) - 1, max(0, size - 2))]
            sprite.set_alpha(int(60 * brightness))
            surface.blit(sprite, (int(x) - sprite.get_width() // 2,
                                  int(y) - sprite.get_height() // 2))
        for sprite in self._dust_sprites:
            sprite.set_alpha(255)

    def _draw_comets(self, surface):
        for comet in self.comets:
            ratio = max(0.0, min(1.0, comet.life / comet.max_life))
            magnitude = max(1.0, math.hypot(comet.vx, comet.vy))
            dx = comet.vx / magnitude * comet.length
            dy = comet.vy / magnitude * comet.length
            tail = (int(comet.x - dx), int(comet.y - dy))
            head = (int(comet.x), int(comet.y))
            fade = max(0.0, min(1.0, ratio * 2.4))
            core = tuple(int(channel * fade) for channel in comet.color)
            pygame.draw.line(surface, core, tail, head, max(1, int(2 * ratio)))
            pygame.draw.circle(surface, (255, 255, 255), head, max(1, int(2 * ratio)))


def backdrop_for_game(resources, mode, wave=1, seed=None):
    return SpaceBackdrop(
        resources, mode, zone=zone_index_for_wave(wave), seed=seed,
        quality=getattr(resources.settings, "effects_quality", 2),
    )
