"""Visual effects: parallax stars, particles, explosion sprites, floating text."""

from __future__ import annotations

import math
import random

import pygame

from utils import VH, VW


class StarField:
    """Three parallax star layers with a subtle twinkle."""

    LAYERS = (
        (80, 22.0, 1, 0.55),
        (50, 48.0, 1, 0.8),
        (30, 90.0, 2, 1.0),
    )

    def __init__(self, seed=7, count_scale=1.0):
        rng = random.Random(seed)
        self.stars = []
        self.time = 0.0
        for count, speed, size, brightness in self.LAYERS:
            for _ in range(max(1, int(count * count_scale))):
                self.stars.append(
                    [rng.uniform(0, VW), rng.uniform(0, VH), speed, size,
                     brightness, rng.uniform(0, math.tau)]
                )

    def update(self, dt, boost=0.0):
        self.time += dt
        for star in self.stars:
            factor = 1.0 + max(0.0, boost) / 380.0 * (star[2] / 90.0)
            star[1] += star[2] * factor * dt
            if star[1] > VH + 2:
                star[1] -= VH + 4
                star[0] = random.uniform(0, VW)

    def draw(self, surface, star_color=(210, 235, 255), boost=0.0):
        for x, y, speed, size, brightness, phase in self.stars:
            twinkle = 0.72 + 0.28 * math.sin(self.time * 2.2 + phase)
            value = brightness * twinkle
            color = (
                int(star_color[0] * value),
                int(star_color[1] * value),
                int(star_color[2] * value),
            )
            if boost > 170 and speed > 40:
                tail = min(10.0, boost / 45.0)
                pygame.draw.line(
                    surface, color, (x, y), (x, y - tail * (speed / 90.0)), size
                )
            elif size <= 1:
                surface.set_at((int(x) % VW, int(y) % VH), color)
            else:
                pygame.draw.circle(surface, color, (int(x), int(y)), int(size))


class ScreenShake:
    def __init__(self):
        self.trauma = 0.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.time = 0.0

    def add(self, amount):
        self.trauma = min(1.0, self.trauma + amount)

    def update(self, dt):
        self.time += dt
        self.trauma = max(0.0, self.trauma - dt * 1.9)
        magnitude = self.trauma * self.trauma * 13.0
        if magnitude <= 0.2:
            self.offset_x = self.offset_y = 0.0
            return
        self.offset_x = math.sin(self.time * 83.0) * magnitude
        self.offset_y = math.cos(self.time * 67.0) * magnitude * 0.75


class Particle:
    __slots__ = (
        "x", "y", "vx", "vy", "life", "max_life", "size", "color",
        "gravity", "drag", "shape", "spawn_size", "spin",
    )

    def __init__(self, x, y, vx, vy, life, size, color, gravity=0.0, drag=0.9, shape="circle"):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.size = size
        self.spawn_size = size
        self.color = color
        self.gravity = gravity
        self.drag = drag
        self.shape = shape
        self.spin = 0.0


class FloatingText:
    __slots__ = ("text", "x", "y", "vy", "life", "max_life", "size", "color")

    def __init__(self, text, x, y, color, size=18, life=1.1, vy=-48):
        self.text = text
        self.x = x
        self.y = y
        self.vy = vy
        self.life = life
        self.max_life = life
        self.size = size
        self.color = color


class ShockRing:
    __slots__ = ("x", "y", "radius", "max_radius", "life", "max_life", "color", "width")

    def __init__(self, x, y, color, max_radius=90, life=0.45, width=3):
        self.x = x
        self.y = y
        self.radius = 8.0
        self.max_radius = max_radius
        self.life = life
        self.max_life = life
        self.color = color
        self.width = width


class ExplosionSprite:
    __slots__ = ("frames", "x", "y", "index", "timer", "frame_time", "alive")

    def __init__(self, frames, x, y, frame_time=0.045):
        self.frames = frames
        self.x = x
        self.y = y
        self.index = 0
        self.timer = 0.0
        self.frame_time = frame_time
        self.alive = bool(frames)

    def update(self, dt):
        if not self.alive:
            return
        self.timer += dt
        while self.timer >= self.frame_time:
            self.timer -= self.frame_time
            self.index += 1
            if self.index >= len(self.frames):
                self.alive = False
                return

    def draw(self, surface):
        if not self.alive or not self.frames:
            return
        image = self.frames[min(self.index, len(self.frames) - 1)]
        rect = image.get_rect(center=(int(self.x), int(self.y)))
        surface.blit(image, rect)


class Effects:
    """Particle/text/ring container with a hard object cap."""

    MAX_PARTICLES = 700

    def __init__(self, resources, quality=None, reduced_flash=None):
        self.resources = resources
        self.particles = []
        self.texts = []
        self.rings = []
        self.booms = []
        self.flash_alpha = 0.0
        self.flash_color = (255, 255, 255)
        self._flash_surface = pygame.Surface((VW, VH), pygame.SRCALPHA)
        if quality is None:
            quality = getattr(getattr(resources, "settings", None), "effects_quality", 2)
        if reduced_flash is None:
            reduced_flash = getattr(
                getattr(resources, "settings", None), "reduced_flash", False
            )
        self.set_quality(quality)
        self.set_reduced_flash(reduced_flash)

    def set_quality(self, quality):
        self.quality = max(0, min(2, int(quality)))
        self.max_particles = (220, 420, self.MAX_PARTICLES)[self.quality]
        self.limit = (0.55, 0.78, 1.0)[self.quality]

    def set_reduced_flash(self, reduced_flash):
        """Tone full-screen flashes down for photosensitivity/comfort."""
        self.reduced_flash = bool(reduced_flash)

    def clear(self):
        self.particles.clear()
        self.texts.clear()
        self.rings.clear()
        self.booms.clear()
        self.flash_alpha = 0.0

    def _add(self, particle):
        if len(self.particles) >= self.max_particles:
            del self.particles[:max(20, self.max_particles // 8)]
        self.particles.append(particle)

    def explosion(self, x, y, color=(255, 170, 90), count=26, speed=260, size=3.5,
                  life=0.7, smoke=True):
        rng = random
        count = max(6, int(count * self.limit))
        for _ in range(count):
            angle = rng.uniform(0, math.tau)
            velocity = rng.uniform(speed * 0.25, speed)
            self._add(Particle(
                x, y,
                math.cos(angle) * velocity,
                math.sin(angle) * velocity,
                rng.uniform(life * 0.5, life),
                rng.uniform(size * 0.5, size * 1.5),
                color,
                drag=0.93,
                shape="circle" if rng.random() < 0.62 else "spark",
            ))
        if smoke:
            for _ in range(max(2, int(count // 6))):
                angle = rng.uniform(0, math.tau)
                self._add(Particle(
                    x, y,
                    math.cos(angle) * rng.uniform(10, 70),
                    math.sin(angle) * rng.uniform(10, 70) - 20,
                    rng.uniform(0.5, 1.1),
                    rng.uniform(5, 10),
                    (90, 90, 110),
                    drag=0.86,
                ))
        self.ring(x, y, color, max_radius=70, life=0.35, width=3)

    def hit_sparks(self, x, y, color=(255, 225, 140), count=7, spread=1.0):
        for _ in range(max(2, int(count * self.limit))):
            angle = random.uniform(0, math.tau)
            velocity = random.uniform(60, 240) * spread
            self._add(Particle(
                x, y,
                math.cos(angle) * velocity,
                math.sin(angle) * velocity,
                random.uniform(0.14, 0.35),
                random.uniform(1.2, 2.6),
                color,
                drag=0.9,
                shape="spark",
            ))

    def muzzle(self, x, y, color=(160, 230, 255), angle=0.0, intensity=1.0):
        """Small directional flash; never covers a large part of the screen."""
        for _ in range(max(2, int(5 * self.limit))):
            spread = random.uniform(-0.35, 0.35)
            velocity = random.uniform(110, 270) * intensity
            self._add(Particle(
                x, y,
                math.cos(angle + spread) * velocity,
                math.sin(angle + spread) * velocity,
                random.uniform(0.08, 0.20),
                random.uniform(1.2, 2.8),
                color,
                drag=0.88,
                shape="spark",
            ))
        self.ring(x, y, color, max_radius=24, life=0.14, width=2)

    def debris(self, x, y, color=(255, 170, 90), count=12, speed=180):
        for _ in range(max(3, int(count * self.limit))):
            angle = random.uniform(0, math.tau)
            velocity = random.uniform(speed * 0.2, speed)
            self._add(Particle(
                x, y,
                math.cos(angle) * velocity,
                math.sin(angle) * velocity,
                random.uniform(0.4, 0.9),
                random.uniform(2.0, 4.5),
                color,
                gravity=110,
                drag=0.985,
                shape="debris",
            ))

    def engine(self, x, y, color=(90, 190, 255), intensity=1.0):
        for _ in range(2 if self.quality >= 2 else 1):
            self._add(Particle(
                x + random.uniform(-4, 4),
                y + random.uniform(-2, 2),
                random.uniform(-22, 22),
                random.uniform(100, 210) * intensity,
                random.uniform(0.18, 0.42),
                random.uniform(1.6, 4.2),
                color,
                drag=1.02,
                shape="spark",
            ))

    def trail(self, x, y, color=(255, 160, 60)):
        self._add(Particle(
            x + random.uniform(-5, 5),
            y,
            random.uniform(-12, 12),
            random.uniform(40, 90),
            random.uniform(0.3, 0.7),
            random.uniform(1.5, 3.6),
            color,
            drag=0.98,
        ))

    def pickup(self, x, y, color=(120, 255, 200)):
        for _ in range(max(8, int(18 * self.limit))):
            angle = random.uniform(0, math.tau)
            velocity = random.uniform(40, 190)
            self._add(Particle(
                x, y,
                math.cos(angle) * velocity,
                math.sin(angle) * velocity - 30,
                random.uniform(0.3, 0.75),
                random.uniform(1.5, 3.8),
                color,
                drag=0.92,
            ))
        self.ring(x, y, color, max_radius=64, life=0.5, width=2)

    def shield_hit(self, x, y, color=(90, 200, 255)):
        for _ in range(max(8, int(26 * self.limit))):
            angle = random.uniform(0, math.tau)
            velocity = random.uniform(80, 220)
            self._add(Particle(
                x, y,
                math.cos(angle) * velocity,
                math.sin(angle) * velocity,
                random.uniform(0.25, 0.6),
                random.uniform(1.5, 4),
                color,
                drag=0.91,
            ))
        self.ring(x, y, color, max_radius=96, life=0.45, width=4)
        self.flash((120, 210, 255), 52)

    def boss_explosion(self, x, y, color=(255, 160, 80)):
        bursts = 5 if self.quality >= 1 else 3
        for _ in range(bursts):
            self.explosion(
                x + random.uniform(-55, 55),
                y + random.uniform(-40, 40),
                color,
                count=38,
                speed=360,
                size=5,
                life=1.1,
            )
        self.ring(x, y, (255, 230, 160), max_radius=210, life=0.8, width=6)
        self.flash((255, 220, 180), 88)


    def text(self, text, x, y, color, size=18, life=1.1, vy=-48):
        self.texts.append(FloatingText(str(text), x, y, color, size, life, vy))
        if len(self.texts) > 40:
            del self.texts[:10]

    def ring(self, x, y, color, max_radius=90, life=0.45, width=3):
        self.rings.append(ShockRing(x, y, color, max_radius, life, width))

    def boom(self, x, y, radius):
        if self.resources.boom_sources:
            self.booms.append(ExplosionSprite(self.resources.boom_frames(radius), x, y))
        else:
            self.explosion(x, y, count=18, speed=180, size=3)

    def flash(self, color, alpha):
        self.flash_color = color
        if self.reduced_flash:
            alpha *= 0.25
        self.flash_alpha = max(self.flash_alpha, min(160.0, alpha))

    def update(self, dt):
        if dt <= 0:
            return
        alive_particles = []
        for particle in self.particles:
            particle.life -= dt
            if particle.life <= 0:
                continue
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.vy += particle.gravity * dt
            particle.vx *= particle.drag
            particle.vy *= particle.drag
            particle.size = max(0.5, particle.spawn_size * (particle.life / particle.max_life))
            alive_particles.append(particle)
        self.particles = alive_particles

        for text in self.texts[:]:
            text.life -= dt
            text.y += text.vy * dt
            text.vy *= 0.96
            if text.life <= 0:
                self.texts.remove(text)

        for ring in self.rings[:]:
            ring.life -= dt
            progress = 1.0 - max(0.0, ring.life) / ring.max_life
            ring.radius = 8 + (ring.max_radius - 8) * progress
            if ring.life <= 0:
                self.rings.remove(ring)

        for boom in self.booms[:]:
            boom.update(dt)
            if not boom.alive:
                self.booms.remove(boom)

        if self.flash_alpha > 0:
            self.flash_alpha = max(0.0, self.flash_alpha - dt * 420)

    def draw(self, surface):
        for boom in self.booms:
            boom.draw(surface)

        for particle in self.particles:
            ratio = max(0.0, min(1.0, particle.life / particle.max_life))
            color = (
                int(particle.color[0] * (0.45 + ratio * 0.55)),
                int(particle.color[1] * (0.45 + ratio * 0.55)),
                int(particle.color[2] * (0.45 + ratio * 0.55)),
            )
            x, y = int(particle.x), int(particle.y)
            if particle.shape == "spark":
                dx = particle.vx * 0.025
                dy = particle.vy * 0.025
                pygame.draw.line(surface, color, (x, y), (int(x - dx), int(y - dy)),
                                 max(1, int(particle.size)))
            elif particle.shape == "debris":
                size = max(1, int(particle.size))
                pygame.draw.polygon(surface, color, [
                    (x, y - size), (x + size, y), (x, y + size), (x - size, y),
                ])
            else:
                pygame.draw.circle(surface, color, (x, y), max(1, int(particle.size)))

        for ring in self.rings:
            ratio = max(0.0, ring.life / ring.max_life)
            color = (
                int(ring.color[0] * ratio),
                int(ring.color[1] * ratio),
                int(ring.color[2] * ratio),
            )
            pygame.draw.circle(
                surface, color, (int(ring.x), int(ring.y)),
                max(2, int(ring.radius)), max(1, int(ring.width * ratio) or 1),
            )

        for text in self.texts:
            ratio = max(0.0, min(1.0, text.life / text.max_life))
            image = self.resources.text(text.text, text.size, text.color)
            image.set_alpha(int(255 * min(1.0, ratio * 1.8)))
            surface.blit(image, image.get_rect(center=(int(text.x), int(text.y))))
            image.set_alpha(255)

    def draw_flash(self, surface):
        if self.flash_alpha <= 1:
            return
        self._flash_surface.fill((*self.flash_color, int(self.flash_alpha)))
        surface.blit(self._flash_surface, (0, 0))
