"""Central, cached access to every image, font and procedural surface."""

from __future__ import annotations

import math
import os
import random

import pygame

from GameData import SHIP_ORDER, ZONES
from utils import ROOT, VH, VW

IMG_ASTEROIDS = os.path.join(ROOT, "assets", "images", "asteroids")
IMG_ASTEROID_BOOM = os.path.join(ROOT, "assets", "images", "asteroidsBoom")
IMG_BACKGROUNDS = os.path.join(ROOT, "assets", "images", "backgrounds")
IMG_SHIPS = os.path.join(ROOT, "assets", "images", "userStarShips")
IMG_BULLETS = os.path.join(ROOT, "assets", "images", "userBullets")
IMG_SHIPS_HD = os.path.join(ROOT, "assets", "images", "ships")
IMG_ENEMIES_HD = os.path.join(ROOT, "assets", "images", "enemies")
IMG_BOSSES_HD = os.path.join(ROOT, "assets", "images", "bosses")
IMG_PLANETS_HD = os.path.join(ROOT, "assets", "images", "planets")
IMG_POWERUPS_HD = os.path.join(ROOT, "assets", "images", "powerups")
IMG_BULLETS_HD = os.path.join(ROOT, "assets", "images", "bullets")
FONT_BODY = os.path.join(ROOT, "assets", "fonts", "solid.ttf")
FONT_TITLE = os.path.join(ROOT, "assets", "fonts", "Space Age.ttf")
FONT_CHINESE = os.path.join(ROOT, "assets", "fonts", "wt034.ttf")

ENEMY_DISPLAY_SIZE = {
    "scout": (58, 58),
    "fighter": (72, 72),
    "bomber": (84, 84),
    "raider": (66, 66),
    "elite": (96, 96),
}


NORMAL_PALETTE = {
    "bg": (6, 10, 24),
    "panel": (10, 18, 38),
    "panel_light": (18, 30, 58),
    "border": (52, 96, 150),
    "text": (226, 241, 255),
    "muted": (128, 156, 190),
    "accent": (64, 214, 255),
    "accent2": (142, 116, 255),
    "danger": (255, 84, 100),
    "warning": (255, 198, 82),
    "success": (86, 240, 162),
    "bullet": (255, 215, 120),
    "enemy_bullet": (255, 92, 122),
    "particle": (255, 170, 90),
    "star": (210, 235, 255),
    "tint": (226, 238, 255),
    "overlay": (4, 8, 20, 200),
    "hull": (72, 84, 112),
    "hull_dark": (34, 42, 64),
    "enemy_accent": (255, 96, 96),
}

MEME_PALETTE = {
    "bg": (26, 8, 30),
    "panel": (42, 14, 46),
    "panel_light": (64, 22, 68),
    "border": (180, 74, 160),
    "text": (255, 240, 252),
    "muted": (208, 154, 204),
    "accent": (255, 100, 196),
    "accent2": (255, 226, 92),
    "danger": (255, 74, 120),
    "warning": (255, 226, 92),
    "success": (120, 255, 180),
    "bullet": (255, 240, 112),
    "enemy_bullet": (255, 120, 220),
    "particle": (255, 132, 210),
    "star": (255, 220, 245),
    "tint": (255, 172, 214),
    "overlay": (26, 6, 28, 205),
    "hull": (112, 70, 132),
    "hull_dark": (52, 30, 68),
    "enemy_accent": (255, 110, 210),
}


def palette_for(mode):
    return MEME_PALETTE if mode == "meme" else NORMAL_PALETTE


def _safe_load_alpha(path, size=None):
    try:
        surface = pygame.image.load(path)
        surface = surface.convert_alpha()
        if size:
            surface = pygame.transform.smoothscale(surface, size)
        return surface
    except (pygame.error, OSError):
        return None


def _placeholder_surface(size, color=(90, 100, 120), transparent=True):
    flags = pygame.SRCALPHA if transparent else 0
    surface = pygame.Surface(size, flags)
    if transparent:
        surface.fill((0, 0, 0, 0))
    else:
        surface.fill(color)
    pygame.draw.circle(
        surface,
        color,
        (size[0] // 2, size[1] // 2),
        max(2, min(size) // 2 - 2),
        2,
    )
    return surface


def _radial_glow(radius, color, intensity=110):
    radius = max(2, int(radius))
    surface = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    steps = max(6, min(radius, 30))
    for step in range(steps, 0, -1):
        fraction = step / steps
        alpha = int(intensity * (1.0 - fraction) ** 1.6)
        if alpha <= 0:
            alpha = 1
        pygame.draw.circle(
            surface,
            (color[0], color[1], color[2], alpha),
            (radius, radius),
            max(1, int(radius * fraction)),
        )
    return surface


class Resources:
    def __init__(self, settings):
        self.settings = settings
        self._font_cache = {}
        self._text_cache = {}
        self._glow_cache = {}
        self._asteroid_cache = {}
        self._boom_cache = {}
        self._enemy_cache = {}
        self._powerup_cache = {}
        self._bullet_cache = {}
        self._background_cache = {}
        self._nebula_cache = {}
        self._planet_cache = {}
        self._rotation_cache = {}
        self._hud_icon_cache = {}
        self.backgrounds = []
        self.ship_frames = []
        self.ship_large = []
        self.ship_small = None
        self.bullet_frames = []
        self.asteroid_sources = []
        self.boom_sources = []
        self.ship_sets = {}
        self.ship_large_sets = {}
        self.enemy_sets = {}
        self.boss_sets = {}
        self.planet_sources = {}
        self.powerup_sources = {}
        self.bullet_sprites = {}
        self._load_images()
        self._load_generated()
        self._build_fonts()
        self.vignette = self._build_vignette()
        self.scanlines = self._build_scanlines()
        self.menu_grid = self._build_grid()

    # --------------------------------------------------------------- loading
    def _load_images(self):
        for name in sorted(os.listdir(IMG_ASTEROIDS)) if os.path.isdir(IMG_ASTEROIDS) else []:
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                image = _safe_load_alpha(os.path.join(IMG_ASTEROIDS, name))
                if image:
                    self.asteroid_sources.append(image)
        if not self.asteroid_sources:
            self.asteroid_sources = [_placeholder_surface((96, 96), (100, 100, 110))]

        for name in sorted(os.listdir(IMG_ASTEROID_BOOM)) if os.path.isdir(IMG_ASTEROID_BOOM) else []:
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                image = _safe_load_alpha(os.path.join(IMG_ASTEROID_BOOM, name))
                if image:
                    self.boom_sources.append(image)

        for name in sorted(os.listdir(IMG_SHIPS)) if os.path.isdir(IMG_SHIPS) else []:
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                image = _safe_load_alpha(os.path.join(IMG_SHIPS, name))
                if image:
                    self.ship_frames.append(pygame.transform.smoothscale(image, (78, 78)))
                    self.ship_large.append(pygame.transform.smoothscale(image, (250, 250)))
        if not self.ship_frames:
            fallback = _placeholder_surface((78, 78), (90, 160, 220))
            self.ship_frames = [fallback]
            self.ship_large = [pygame.transform.smoothscale(fallback, (250, 250))]
        self.ship_small = pygame.transform.smoothscale(self.ship_frames[0], (28, 28))

        for name in sorted(os.listdir(IMG_BULLETS)) if os.path.isdir(IMG_BULLETS) else []:
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                image = _safe_load_alpha(os.path.join(IMG_BULLETS, name), (22, 22))
                if image:
                    self.bullet_frames.append(image)
        if not self.bullet_frames:
            fallback = pygame.Surface((22, 22), pygame.SRCALPHA)
            pygame.draw.circle(fallback, (255, 220, 120), (11, 11), 7)
            pygame.draw.circle(fallback, (255, 255, 255), (11, 11), 4)
            self.bullet_frames = [fallback]

        for name in sorted(os.listdir(IMG_BACKGROUNDS)) if os.path.isdir(IMG_BACKGROUNDS) else []:
            if name.lower().endswith((".jpg", ".jpeg", ".png")):
                try:
                    image = pygame.image.load(os.path.join(IMG_BACKGROUNDS, name)).convert()
                    self.backgrounds.append(pygame.transform.smoothscale(image, (VW, VH)))
                except (pygame.error, OSError):
                    continue
        if not self.backgrounds:
            fallback = pygame.Surface((VW, VH)).convert()
            fallback.fill((8, 10, 24))
            self.backgrounds = [fallback]

    @staticmethod
    def _frame_files(directory, prefix=None):
        try:
            names = os.listdir(directory)
        except OSError:
            return []
        files = [
            name for name in names
            if name.lower().endswith(".png")
            and (prefix is None or name.startswith(prefix + "_"))
        ]

        def sort_key(name):
            stem = name.rsplit(".", 1)[0]
            tail = stem.rsplit("_", 1)[-1]
            return (int(tail) if tail.isdigit() else 999, stem)

        return [os.path.join(directory, name) for name in sorted(files, key=sort_key)]

    def _load_generated(self):
        """Load the optional high-resolution art created by tools/generate_assets.py.

        Every set is optional: if a file is missing the procedural fallbacks
        from the original game keep working.
        """
        for kind in SHIP_ORDER:
            frames = []
            for path in self._frame_files(IMG_SHIPS_HD, kind):
                image = _safe_load_alpha(path)
                if image is not None:
                    frames.append(image)
            if frames:
                self.ship_sets[kind] = [
                    pygame.transform.smoothscale(image, (78, 78)) for image in frames
                ]
                self.ship_large_sets[kind] = [
                    pygame.transform.smoothscale(image, (250, 250)) for image in frames
                ]
            else:
                self.ship_sets[kind] = list(self.ship_frames)
                self.ship_large_sets[kind] = list(self.ship_large)

        preferred = getattr(self.settings, "ship", "fighter")
        if preferred not in self.ship_sets:
            preferred = "fighter"
        self.ship_frames = list(self.ship_sets[preferred])
        self.ship_large = list(self.ship_large_sets[preferred])
        self.ship_small = pygame.transform.smoothscale(self.ship_frames[0], (28, 28))

        for kind, size in ENEMY_DISPLAY_SIZE.items():
            frames = []
            for path in self._frame_files(IMG_ENEMIES_HD, kind):
                image = _safe_load_alpha(path)
                if image is not None:
                    frames.append(pygame.transform.smoothscale(image, size))
            if frames:
                self.enemy_sets[kind] = frames

        for kind in ("dreadnought", "sentinel"):
            frames = []
            for path in self._frame_files(IMG_BOSSES_HD, kind):
                image = _safe_load_alpha(path)
                if image is not None:
                    frames.append(pygame.transform.smoothscale(image, (330, 248)))
            if frames:
                self.boss_sets[kind] = frames

        for path in self._frame_files(IMG_PLANETS_HD):
            image = _safe_load_alpha(path)
            if image is None:
                continue
            name = os.path.basename(path)
            if name.startswith("planet_"):
                name = name[len("planet_"):]
            name = name.rsplit(".", 1)[0]
            self.planet_sources[name] = image

        for path in self._frame_files(IMG_POWERUPS_HD):
            image = _safe_load_alpha(path, (44, 44))
            if image is not None:
                self.powerup_sources[os.path.basename(path).rsplit(".", 1)[0]] = image

        bullet_sizes = {
            "player_pulse": (18, 24),
            "player_burst": (16, 22),
            "player_spread": (20, 28),
            "player_lance": (24, 54),
            "enemy_orb": (20, 20),
            "enemy_plasma": (20, 20),
        }
        for kind, size in bullet_sizes.items():
            path = os.path.join(IMG_BULLETS_HD, kind + ".png")
            image = _safe_load_alpha(path, size)
            if image is not None:
                self.bullet_sprites[kind] = image

    # ------------------------------------------------------------ sprite API
    def ship_frames_for(self, kind):
        return self.ship_sets.get(kind) or self.ship_frames

    def select_ship(self, kind):
        """Make ``kind`` the active hull used by HUD icons and the menu hero."""
        if kind not in self.ship_sets:
            kind = "fighter"
        if kind not in self.ship_sets:
            return None
        self.ship_frames = list(self.ship_sets[kind])
        self.ship_large = list(self.ship_large_sets[kind])
        self.ship_small = pygame.transform.smoothscale(self.ship_frames[0], (28, 28))
        self.settings.ship = kind
        return kind

    def ship_large_for(self, kind):
        return self.ship_large_sets.get(kind) or self.ship_large

    def enemy_frames(self, kind):
        frames = self.enemy_sets.get(kind)
        if frames:
            return frames
        return None

    def boss_frames(self, kind):
        return self.boss_sets.get(kind)

    def planet(self, name, size):
        name = name if name in self.planet_sources else next(iter(self.planet_sources), None)
        if name is None:
            return None
        size = max(48, int(size))
        key = ("planet", name, size)
        cached = self._planet_cache.get(key)
        if cached is not None:
            return cached
        image = pygame.transform.smoothscale(self.planet_sources[name], (size, size))
        if len(self._planet_cache) > 40:
            self._planet_cache.clear()
        self._planet_cache[key] = image
        return image

    def bullet_sprite(self, kind, mode="normal"):
        key = (kind, mode)
        cached = self._bullet_cache.get(key)
        if cached is not None:
            return cached
        image = self.bullet_sprites.get(kind)
        if image is None:
            # Reuse the legacy bullet sheet if the new art is unavailable.
            image = self.bullet_frames[0] if self.bullet_frames else None
            if image is None:
                image = pygame.Surface((16, 16), pygame.SRCALPHA)
                pygame.draw.circle(image, (255, 220, 120), (8, 8), 6)
        if mode == "meme" and kind.startswith("player_"):
            image = image.copy()
            image.fill((255, 186, 232), special_flags=pygame.BLEND_RGB_MULT)
        self._bullet_cache[key] = image
        return image

    def asteroid_rot(self, index, radius, angle):
        index %= len(self.asteroid_sources)
        radius = max(10, int(radius))
        step = int(round(angle / 8.0)) % 45
        key = (index, radius, step)
        cached = self._rotation_cache.get(key)
        if cached is not None:
            return cached
        base = self.asteroid(index, radius)
        image = pygame.transform.rotozoom(base, step * 8.0, 1.0)
        if len(self._rotation_cache) > 420:
            self._rotation_cache.clear()
        self._rotation_cache[key] = image
        return image

    def zone_background(self, zone_index, mode):
        zone_index %= len(ZONES)
        key = ("zone", zone_index, mode)
        cached = self._background_cache.get(key)
        if cached is not None:
            return cached
        zone = ZONES[zone_index]
        base_index = (zone_index + 2) % len(self.backgrounds)
        surface = self.backgrounds[base_index].copy()
        tint = zone["tint"] if mode == "normal" else (255, 180, 220)
        surface.fill(tint, special_flags=pygame.BLEND_RGB_MULT)
        overlay = self._gradient_overlay()
        surface.blit(overlay, (0, 0))
        self._background_cache[key] = surface
        return surface

    def _gradient_overlay(self):
        cached = self._nebula_cache.get("__gradient")
        if cached is not None:
            return cached
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        for y in range(0, VH, 8):
            alpha = int(16 + 82 * (y / VH))
            pygame.draw.rect(overlay, (2, 4, 12, alpha), (0, y, VW, 8))
        self._nebula_cache["__gradient"] = overlay
        return overlay

    def _build_fonts(self):
        # The bundled fonts have no real Cyrillic glyphs (they render boxes),
        # so translated UI text uses a system font that definitely does.  The
        # decorative Space Age font is still used for the Latin title and
        # arcade-style digits.
        self._font_files = {
            "body": self._find_system_font(("segoeui", "tahoma", "arial", "dejavusans",
                                            "liberationsans", "notosans")),
            "bold": self._find_system_font(("segoeuisemibold", "segoeuibold", "tahomabd",
                                            "arialbd", "dejavusansbold", "liberationsansbold")),
            "title": FONT_TITLE,
            "chinese": FONT_CHINESE,
        }
        if not self._font_files["body"]:
            self._font_files["body"] = self._font_files["bold"]
        if not self._font_files["bold"]:
            self._font_files["bold"] = self._font_files["body"]

    @staticmethod
    def _find_system_font(candidates):
        for name in candidates:
            try:
                path = pygame.font.match_font(name)
            except (pygame.error, AttributeError):
                path = None
            if path:
                return path
        return None

    def _build_vignette(self):
        surface = pygame.Surface((VW, VH), pygame.SRCALPHA)
        depth = 110
        for index in range(depth):
            alpha = int(90 * (1.0 - index / depth) ** 2)
            pygame.draw.rect(
                surface,
                (0, 0, 0, alpha),
                (index, index, VW - index * 2, VH - index * 2),
                1,
            )
        return surface

    def _build_scanlines(self):
        surface = pygame.Surface((VW, VH), pygame.SRCALPHA)
        for y in range(0, VH, 4):
            pygame.draw.line(surface, (0, 0, 0, 14), (0, y), (VW, y))
        return surface

    def _build_grid(self):
        surface = pygame.Surface((VW, VH), pygame.SRCALPHA)
        for x in range(0, VW, 64):
            pygame.draw.line(surface, (70, 180, 255, 12), (x, 0), (x, VH))
        for y in range(0, VH, 64):
            pygame.draw.line(surface, (70, 180, 255, 12), (0, y), (VW, y))
        return surface

    # ---------------------------------------------------------------- fonts
    def font(self, size, kind="body"):
        key = (kind, int(size))
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        path = self._font_files.get(kind, FONT_BODY)
        try:
            if path:
                font = pygame.font.Font(path, max(8, int(size)))
            else:
                font = pygame.font.Font(None, max(8, int(size)))
        except (pygame.error, OSError, TypeError):
            try:
                font = pygame.font.Font(None, max(8, int(size)))
            except pygame.error:
                font = pygame.font.SysFont(None, max(8, int(size)))
        self._font_cache[key] = font
        return font

    def text(self, text, size, color, kind="body"):
        key = (str(text), int(size), tuple(color), kind)
        cached = self._text_cache.get(key)
        if cached is not None:
            return cached
        surface = self.font(size, kind).render(str(text), True, color)
        if len(self._text_cache) > 700:
            self._text_cache.clear()
        self._text_cache[key] = surface
        return surface

    def text_size(self, text, size, kind="body"):
        return self.font(size, kind).size(str(text))

    def wrap_text(self, text, size, max_width, kind="body"):
        font = self.font(size, kind)
        words = str(text).split()
        lines = []
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    # ----------------------------------------------------------- backgrounds
    @property
    def background_count(self):
        return len(self.backgrounds)

    def background(self, index, mode):
        index %= len(self.backgrounds)
        key = (index, mode)
        cached = self._background_cache.get(key)
        if cached is not None:
            return cached
        surface = self.backgrounds[index].copy()
        tint = palette_for(mode)["tint"]
        try:
            surface.fill(tint, special_flags=pygame.BLEND_RGB_MULT)
        except (pygame.error, ValueError):
            pass
        # A subtle dark gradient keeps HUD text and bullets readable.
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        for y in range(0, VH, 8):
            alpha = int(20 + 75 * (y / VH))
            pygame.draw.rect(overlay, (2, 4, 12, alpha), (0, y, VW, 8))
        surface.blit(overlay, (0, 0))
        self._background_cache[key] = surface
        return surface

    def background_flipped(self, index, mode):
        index %= len(self.backgrounds)
        key = ("flip", index, mode)
        cached = self._background_cache.get(key)
        if cached is not None:
            return cached
        surface = pygame.transform.flip(self.background(index, mode), False, True)
        self._background_cache[key] = surface
        return surface

    def nebula(self, mode):
        cached = self._nebula_cache.get(mode)
        if cached is not None:
            return cached
        palette = palette_for(mode)
        surface = pygame.Surface((VW, VH * 2), pygame.SRCALPHA)
        rng = random.Random(991 if mode == "normal" else 1777)
        if mode == "meme":
            colors = [(255, 80, 180), (255, 210, 80), (140, 80, 255), (80, 255, 200)]
        else:
            colors = [(70, 110, 255), (120, 60, 220), (30, 180, 220), (170, 80, 255)]
        for _ in range(9):
            cx = rng.randint(-100, VW + 100)
            cy = rng.randint(-100, VH * 2 + 100)
            radius = rng.randint(110, 320)
            color = rng.choice(colors)
            steps = 16
            for step in range(steps, 0, -1):
                alpha = int(7 * (1.0 - step / steps) ** 1.2)
                if alpha <= 0:
                    continue
                pygame.draw.circle(
                    surface,
                    (color[0], color[1], color[2], alpha),
                    (cx, cy),
                    max(2, int(radius * step / steps)),
                )
        self._nebula_cache[mode] = surface
        return surface

    # ------------------------------------------------------------- sprites
    def asteroid(self, index, radius):
        index %= len(self.asteroid_sources)
        radius = max(10, int(radius))
        key = (index, radius)
        cached = self._asteroid_cache.get(key)
        if cached is not None:
            return cached
        size = max(8, radius * 2)
        surface = pygame.transform.smoothscale(self.asteroid_sources[index], (size, size))
        if len(self._asteroid_cache) > 220:
            self._asteroid_cache.clear()
        self._asteroid_cache[key] = surface
        return surface

    def boom_frames(self, radius):
        radius = max(12, int(radius))
        key = radius
        cached = self._boom_cache.get(key)
        if cached is not None:
            return cached
        frames = []
        size = max(20, radius * 2)
        for source in self.boom_sources:
            try:
                frames.append(pygame.transform.smoothscale(source, (size, size)))
            except (pygame.error, ValueError):
                continue
        if not frames:
            frames = [self.glow(radius, (255, 160, 70))]
        if len(self._boom_cache) > 40:
            self._boom_cache.clear()
        self._boom_cache[key] = frames
        return frames

    def glow(self, radius, color, intensity=110):
        radius = max(2, int(radius))
        key = (radius, tuple(color), intensity)
        cached = self._glow_cache.get(key)
        if cached is not None:
            return cached
        surface = _radial_glow(radius, color, intensity)
        if len(self._glow_cache) > 120:
            self._glow_cache.clear()
        self._glow_cache[key] = surface
        return surface

    def enemy_sprite(self, kind, mode):
        key = (kind, mode)
        cached = self._enemy_cache.get(key)
        if cached is not None:
            return cached
        palette = palette_for(mode)
        if kind == "scout":
            surface = self._make_scout(palette)
        elif kind == "fighter":
            surface = self._make_fighter(palette)
        elif kind == "bomber":
            surface = self._make_bomber(palette)
        elif kind == "boss":
            surface = self._make_boss(palette)
        else:
            surface = _placeholder_surface((60, 60), palette["hull"])
        self._enemy_cache[key] = surface
        return surface

    def _downscale_draw(self, size, painter, factor=3):
        big = pygame.Surface((size[0] * factor, size[1] * factor), pygame.SRCALPHA)
        painter(big, factor)
        return pygame.transform.smoothscale(big, size)

    def _make_scout(self, palette):
        size = (74, 74)

        def paint(surface, f):
            hull = palette["hull"]
            dark = palette["hull_dark"]
            accent = palette["enemy_accent"]
            pygame.draw.circle(surface, (*accent, 40), (37 * f, 40 * f), 34 * f)
            body = [(37, 68), (27, 48), (14, 40), (23, 27), (33, 35), (37, 8),
                    (41, 35), (51, 27), (60, 40), (47, 48)]
            pygame.draw.polygon(surface, dark, [(x * f, y * f) for x, y in body])
            inner = [(37, 60), (30, 44), (24, 39), (31, 34), (37, 44), (43, 34),
                     (50, 39), (44, 44)]
            pygame.draw.polygon(surface, hull, [(x * f, y * f) for x, y in inner])
            pygame.draw.circle(surface, accent, (37 * f, 42 * f), 5 * f)
            pygame.draw.circle(surface, (255, 255, 255), (37 * f, 42 * f), 2 * f)
            pygame.draw.line(surface, accent, (30 * f, 22 * f), (37 * f, 12 * f), max(1, f))
            pygame.draw.line(surface, accent, (44 * f, 22 * f), (37 * f, 12 * f), max(1, f))

        return self._downscale_draw(size, paint)

    def _make_fighter(self, palette):
        size = (86, 86)

        def paint(surface, f):
            hull = palette["hull"]
            dark = palette["hull_dark"]
            accent = palette["enemy_accent"]
            pygame.draw.circle(surface, (*accent, 35), (43 * f, 43 * f), 40 * f)
            outer = [(43, 80), (34, 58), (12, 48), (20, 30), (33, 36), (38, 16),
                     (48, 16), (53, 36), (66, 30), (74, 48), (52, 58)]
            pygame.draw.polygon(surface, dark, [(x * f, y * f) for x, y in outer])
            inner = [(43, 70), (37, 52), (26, 44), (31, 38), (39, 44), (43, 28),
                     (47, 44), (55, 38), (60, 44), (49, 52)]
            pygame.draw.polygon(surface, hull, [(x * f, y * f) for x, y in inner])
            pygame.draw.ellipse(surface, accent, (37 * f, 34 * f, 12 * f, 18 * f))
            pygame.draw.circle(surface, (255, 255, 255), (43 * f, 40 * f), 3 * f)
            pygame.draw.rect(surface, accent, (22 * f, 46 * f, 6 * f, 12 * f))
            pygame.draw.rect(surface, accent, (58 * f, 46 * f, 6 * f, 12 * f))

        return self._downscale_draw(size, paint)

    def _make_bomber(self, palette):
        size = (108, 94)

        def paint(surface, f):
            hull = palette["hull"]
            dark = palette["hull_dark"]
            accent = palette["enemy_accent"]
            pygame.draw.circle(surface, (*accent, 30), (54 * f, 46 * f), 48 * f)
            outer = [(54, 88), (38, 70), (10, 62), (16, 34), (36, 40), (44, 12),
                     (64, 12), (72, 40), (92, 34), (98, 62), (70, 70)]
            pygame.draw.polygon(surface, dark, [(x * f, y * f) for x, y in outer])
            inner = [(54, 78), (44, 64), (24, 58), (28, 44), (44, 48), (48, 26),
                     (60, 26), (64, 48), (80, 44), (84, 58), (64, 64)]
            pygame.draw.polygon(surface, hull, [(x * f, y * f) for x, y in inner])
            pygame.draw.rect(surface, accent, (24 * f, 52 * f, 14 * f, 9 * f))
            pygame.draw.rect(surface, accent, (70 * f, 52 * f, 14 * f, 9 * f))
            pygame.draw.ellipse(surface, accent, (46 * f, 38 * f, 16 * f, 22 * f))
            pygame.draw.circle(surface, (255, 255, 255), (54 * f, 47 * f), 4 * f)

        return self._downscale_draw(size, paint)

    def _make_boss(self, palette):
        size = (260, 190)

        def paint(surface, f):
            hull = palette["hull"]
            dark = palette["hull_dark"]
            accent = palette["enemy_accent"]
            warning = palette["warning"]
            pygame.draw.circle(surface, (*accent, 42), (130 * f, 95 * f), 92 * f)
            outer = [(130, 178), (96, 150), (44, 160), (18, 120), (44, 88),
                     (28, 54), (70, 48), (96, 72), (112, 22), (148, 22),
                     (164, 72), (190, 48), (232, 54), (216, 88), (242, 120),
                     (216, 160), (164, 150)]
            pygame.draw.polygon(surface, dark, [(x * f, y * f) for x, y in outer])
            inner = [(130, 160), (104, 138), (62, 142), (42, 118), (66, 96),
                     (54, 70), (86, 66), (106, 88), (118, 42), (142, 42),
                     (154, 88), (174, 66), (206, 70), (194, 96), (218, 118),
                     (198, 142), (156, 138)]
            pygame.draw.polygon(surface, hull, [(x * f, y * f) for x, y in inner])
            # Armour stripes and turrets.
            for x in (66, 194):
                pygame.draw.circle(surface, dark, (x * f, 112 * f), 20 * f)
                pygame.draw.circle(surface, accent, (x * f, 112 * f), 9 * f)
                pygame.draw.circle(surface, warning, (x * f, 112 * f), 4 * f)
            pygame.draw.circle(surface, accent, (130 * f, 100 * f), 32 * f)
            pygame.draw.circle(surface, dark, (130 * f, 100 * f), 24 * f)
            pygame.draw.circle(surface, warning, (130 * f, 100 * f), 14 * f)
            pygame.draw.circle(surface, (255, 255, 255), (130 * f, 100 * f), 7 * f)
            for x in (94, 130, 166):
                pygame.draw.rect(surface, accent, ((x - 3) * f, 148 * f, 6 * f, 20 * f))

        return self._downscale_draw(size, paint)

    def powerup_sprite(self, kind, mode):
        key = (kind, mode)
        cached = self._powerup_cache.get(key)
        if cached is not None:
            return cached
        if kind in self.powerup_sources:
            surface = self.powerup_sources[kind]
            if mode == "meme":
                surface = surface.copy()
                surface.fill((255, 188, 235), special_flags=pygame.BLEND_RGB_MULT)
            self._powerup_cache[key] = surface
            return surface
        palette = palette_for(mode)
        colors = {
            "shield": (80, 190, 255),
            "life": (255, 92, 124),
            "weapon": (255, 200, 76),
            "rapid": (120, 255, 180),
            "points": (196, 130, 255),
            "chainsaw": (255, 112, 48),
            "tiger": (255, 186, 45),
        }
        color = colors.get(kind, palette["accent"])
        surface = pygame.Surface((48, 48), pygame.SRCALPHA)
        pygame.draw.circle(surface, (*color, 34), (24, 24), 23)
        pygame.draw.circle(surface, (*color, 70), (24, 24), 19)
        pygame.draw.circle(surface, (8, 12, 24, 220), (24, 24), 16)
        pygame.draw.circle(surface, color, (24, 24), 16, 2)
        if kind == "shield":
            points = [(24, 12), (34, 17), (32, 29), (24, 37), (16, 29), (14, 17)]
            pygame.draw.polygon(surface, color, points)
            pygame.draw.polygon(surface, (255, 255, 255), points, 1)
        elif kind == "life":
            pygame.draw.circle(surface, color, (20, 20), 6)
            pygame.draw.circle(surface, color, (28, 20), 6)
            pygame.draw.polygon(surface, color, [(14, 22), (34, 22), (24, 36)])
        elif kind == "weapon":
            pygame.draw.rect(surface, color, (16, 28, 16, 6))
            pygame.draw.rect(surface, color, (22, 16, 4, 14))
            pygame.draw.rect(surface, color, (16, 20, 16, 4))
            pygame.draw.circle(surface, color, (24, 14), 4)
        elif kind == "rapid":
            pygame.draw.polygon(
                surface, color, [(27, 11), (17, 25), (23, 25), (20, 37), (32, 21), (26, 21)]
            )
        elif kind == "tiger":
            pygame.draw.circle(surface, color, (24, 24), 11, 2)
            pygame.draw.polygon(surface, color, [(14, 18), (16, 11), (21, 17)])
            pygame.draw.polygon(surface, color, [(34, 18), (32, 11), (27, 17)])
            pygame.draw.line(surface, color, (18, 22), (21, 25), 2)
            pygame.draw.line(surface, color, (30, 22), (27, 25), 2)
            pygame.draw.polygon(surface, color, [(21, 28), (27, 28), (24, 32)])
            pygame.draw.line(surface, (255, 255, 255), (22, 34), (21, 39), 2)
            pygame.draw.line(surface, (255, 255, 255), (26, 34), (27, 39), 2)
        elif kind == "chainsaw":
            pygame.draw.rect(surface, color, (10, 18, 20, 12), border_radius=4)
            pygame.draw.circle(surface, (225, 232, 238), (33, 24), 10, 3)
            for tooth in range(8):
                angle = tooth * math.tau / 8
                pygame.draw.line(
                    surface, (255, 239, 193),
                    (33 + math.cos(angle) * 8, 24 + math.sin(angle) * 8),
                    (33 + math.cos(angle + .1) * 14,
                     24 + math.sin(angle + .1) * 14), 2)
        else:  # points
            points = []
            for index in range(10):
                angle = -math.pi / 2 + index * math.pi / 5
                radius = 11 if index % 2 == 0 else 5
                points.append((24 + math.cos(angle) * radius, 24 + math.sin(angle) * radius))
            pygame.draw.polygon(surface, color, points)
        self._powerup_cache[key] = surface
        return surface

    def enemy_bullet(self, mode, kind="normal"):
        key = (mode, kind)
        cached = self._powerup_cache.get(key)
        if cached is not None:
            return cached
        palette = palette_for(mode)
        color = palette["enemy_bullet"]
        surface = pygame.Surface((24, 24), pygame.SRCALPHA)
        pygame.draw.circle(surface, (*color, 40), (12, 12), 11)
        pygame.draw.circle(surface, color, (12, 12), 6)
        pygame.draw.circle(surface, (255, 255, 255), (12, 12), 3)
        self._powerup_cache[key] = surface
        return surface

    # --------------------------------------------------------------- decor
    def menu_planet(self, mode):
        cached = self._planet_cache.get(mode)
        if cached is not None:
            return cached
        palette = palette_for(mode)
        size = 250
        surface = pygame.Surface((size, size), pygame.SRCALPHA)
        base = (70, 120, 210) if mode == "normal" else (255, 120, 200)
        shade = (24, 40, 86) if mode == "normal" else (110, 30, 100)
        for radius in range(118, 0, -1):
            t = radius / 118
            color = (
                int(shade[0] + (base[0] - shade[0]) * (1 - t) ** 1.5),
                int(shade[1] + (base[1] - shade[1]) * (1 - t) ** 1.5),
                int(shade[2] + (base[2] - shade[2]) * (1 - t) ** 1.5),
            )
            pygame.draw.circle(surface, color, (125, 125), radius)
        details = pygame.Surface((size, size), pygame.SRCALPHA)
        for index in range(5):
            y = 55 + index * 32
            pygame.draw.ellipse(
                details,
                (*palette["accent"], 34),
                (12, y, 226, 14 + index * 2),
                3,
            )
        pygame.draw.circle(details, (255, 255, 255, 24), (82, 76), 34)
        surface.blit(details, (0, 0))
        if mode == "meme":
            pygame.draw.circle(surface, (255, 255, 255), (96, 104), 17)
            pygame.draw.circle(surface, (255, 255, 255), (154, 104), 17)
            pygame.draw.circle(surface, (30, 20, 40), (100, 108), 7)
            pygame.draw.circle(surface, (30, 20, 40), (150, 108), 7)
            pygame.draw.arc(surface, (30, 20, 40), (84, 112, 82, 58), math.pi * 0.1, math.pi * 0.9, 5)
        else:
            pygame.draw.circle(surface, (255, 255, 255, 25), (82, 76), 34)
        self._planet_cache[mode] = surface
        return surface
