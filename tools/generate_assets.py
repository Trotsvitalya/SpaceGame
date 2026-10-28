"""Generate SpaceGame 2.0 sprite art with pygame.

The game ships the generated PNG files, so players never need to run this
tool.  Everything is original procedural artwork created for this project and
covered by the repository's Unlicense.

Usage:
    python tools/generate_assets.py
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "assets" / "images"
SHIP_DIR = IMG / "ships"
ENEMY_DIR = IMG / "enemies"
BOSS_DIR = IMG / "bosses"
PLANET_DIR = IMG / "planets"
POWERUP_DIR = IMG / "powerups"
BULLET_DIR = IMG / "bullets"

FACTOR = 4


def _surface(size):
    return pygame.Surface(size, pygame.SRCALPHA)


def _save(surface, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, str(path))


def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _alpha(color, alpha):
    return (color[0], color[1], color[2], max(0, min(255, int(alpha))))


def _glow(size, color, strength=120):
    surface = _surface((size, size))
    center = size / 2
    steps = 34
    for step in range(steps, 0, -1):
        ratio = step / steps
        alpha = int(strength * (1.0 - ratio) ** 1.9)
        if alpha <= 0:
            continue
        pygame.draw.circle(
            surface,
            _alpha(color, alpha),
            (int(center), int(center)),
            max(1, int(center * ratio)),
        )
    return surface


def _outline_points(points, center, scale):
    return [(int(center[0] + x * scale), int(center[1] + y * scale)) for x, y in points]


def _draw_poly(surface, color, points, center, scale, width=0):
    pygame.draw.polygon(surface, color, _outline_points(points, center, scale), width)


def _draw_line(surface, color, a, b, center, scale, width):
    pygame.draw.line(
        surface, color,
        _outline_points([a], center, scale)[0],
        _outline_points([b], center, scale)[0],
        max(1, int(width)),
    )


def _draw_ship(surface, palette, points, center, scale, frame, enemy=False, details=None):
    base, dark, light, accent, engine = (
        palette["base"], palette["dark"], palette["light"],
        palette["accent"], palette["engine"],
    )
    pulse = (0.55, 1.0, 0.75)[frame % 3]
    outline = (10, 14, 24, 245)

    # Engine bloom behind the hull.
    engine_points = palette.get("engines", [(0, 47)])
    for ex, ey in engine_points:
        bloom = _glow(int(74 * scale), engine, int(80 + 35 * pulse))
        surface.blit(
            bloom,
            bloom.get_rect(center=(int(center[0] + ex * scale), int(center[1] + ey * scale))),
            special_flags=pygame.BLEND_RGBA_ADD,
        )

    # Dark silhouette / shadow pass gives ships a strong read at small sizes.
    shadow = [(x, y + 2.5) for x, y in points]
    _draw_poly(surface, outline, shadow, center, scale)

    # Wings and hull.  A lighter inner polygon keeps the silhouette readable.
    _draw_poly(surface, dark, points, center, scale)
    inner = []
    for x, y in points:
        inner.append((x * 0.78, y * 0.82))
    _draw_poly(surface, base, inner, center, scale)

    if details:
        details(surface, center, scale, frame, palette)

    # Central spine, cockpit and panel lines.
    _draw_poly(surface, tuple(int(c * 0.82) for c in base),
               [(-5, -34), (5, -34), (7, 22), (0, 34), (-7, 22)],
               center, scale)
    _draw_poly(surface, accent, [(-3.5, -34), (3.5, -34), (4, -15), (0, -9), (-4, -15)],
               center, scale)

    cockpit_rect = pygame.Rect(
        int(center[0] - 7 * scale), int(center[1] - 26 * scale),
        int(14 * scale), int(24 * scale),
    )
    pygame.draw.ellipse(surface, dark, cockpit_rect)
    pygame.draw.ellipse(surface, _mix(accent, light, 0.45), cockpit_rect.inflate(-2 * scale, -2 * scale))
    glint = pygame.Rect(
        cockpit_rect.x + int(3 * scale), cockpit_rect.y + int(3 * scale),
        max(1, int(3 * scale)), max(1, int(8 * scale)),
    )
    pygame.draw.ellipse(surface, (255, 255, 255, 210), glint)

    for x in (-20, 20):
        _draw_line(surface, _mix(base, light, 0.38), (x, -8), (x * 1.55, 24), center, scale, 1.4 * scale)
    _draw_line(surface, accent, (-41, 10), (-20, 17), center, scale, 1.7 * scale)
    _draw_line(surface, accent, (41, 10), (20, 17), center, scale, 1.7 * scale)

    # Engine nozzles and hot cores.
    for ex, ey in engine_points:
        nozzle = pygame.Rect(
            int(center[0] + (ex - 6) * scale), int(center[1] + (ey - 4) * scale),
            int(12 * scale), int(12 * scale),
        )
        pygame.draw.ellipse(surface, dark, nozzle)
        pygame.draw.ellipse(surface, _mix(engine, (255, 255, 255), 0.12), nozzle.inflate(-2 * scale, -2 * scale))
        core = _glow(int(12 * scale), _mix(engine, (255, 255, 255), 0.55), 180)
        surface.blit(core, core.get_rect(center=(nozzle.centerx, nozzle.centery + int(3 * scale))))

    # Navigation lights.
    lights = palette.get("lights", [(-35, 20), (35, 20)])
    for index, (lx, ly) in enumerate(lights):
        color = accent if index % 2 == 0 else (255, 255, 235)
        pygame.draw.circle(
            surface, color,
            _outline_points([(lx, ly)], center, scale)[0],
            max(1, int(1.8 * scale)),
        )


def ship_sprite(kind, frame):
    size = 192
    big = _surface((size * FACTOR, size * FACTOR))
    center = (size * FACTOR / 2, size * FACTOR / 2)
    scale = size * FACTOR / 120.0

    palettes = {
        "fighter": {
            "base": (74, 122, 166), "dark": (22, 38, 66), "light": (196, 236, 255),
            "accent": (66, 224, 255), "engine": (74, 190, 255),
            "engines": [(-14, 46), (14, 46)], "lights": [(-38, 12), (38, 12)],
        },
        "interceptor": {
            "base": (126, 83, 178), "dark": (36, 22, 62), "light": (228, 198, 255),
            "accent": (255, 104, 208), "engine": (255, 98, 190),
            "engines": [(0, 45)], "lights": [(-42, 22), (42, 22)],
        },
        "tank": {
            "base": (158, 112, 68), "dark": (52, 36, 30), "light": (255, 224, 174),
            "accent": (255, 168, 72), "engine": (255, 144, 60),
            "engines": [(-24, 43), (-9, 47), (9, 47), (24, 43)],
            "lights": [(-45, 8), (45, 8)],
        },
        "engineer": {
            "base": (62, 138, 118), "dark": (20, 50, 50), "light": (190, 255, 236),
            "accent": (92, 255, 190), "engine": (76, 255, 190),
            "engines": [(-18, 44), (18, 44)], "lights": [(-36, 26), (36, 26)],
        },
    }
    palette = palettes[kind]

    shapes = {
        "fighter": [(0, -57), (-14, -31), (-21, -12), (-44, 12), (-45, 24),
                    (-18, 20), (-15, 45), (0, 39), (15, 45), (18, 20),
                    (45, 24), (44, 12), (21, -12), (14, -31)],
        "interceptor": [(0, -61), (-9, -26), (-18, -6), (-48, 29), (-23, 24),
                        (-13, 43), (0, 37), (13, 43), (23, 24), (48, 29),
                        (18, -6), (9, -26)],
        "tank": [(0, -46), (-19, -37), (-28, -21), (-49, 4), (-47, 30),
                 (-25, 39), (-20, 49), (0, 44), (20, 49), (25, 39),
                 (47, 30), (49, 4), (28, -21), (19, -37)],
        "engineer": [(0, -48), (-18, -39), (-31, -22), (-39, 2), (-31, 28),
                     (-17, 37), (-12, 48), (0, 42), (12, 48), (17, 37),
                     (31, 28), (39, 2), (31, -22), (18, -39)],
    }

    def details(surface, center, scale, frame, palette):
        if kind == "tank":
            for x in (-31, 31):
                pod = pygame.Rect(int(center[0] + (x - 8) * scale),
                                  int(center[1] - 16 * scale),
                                  int(16 * scale), int(38 * scale))
                pygame.draw.rect(surface, palette["dark"], pod, border_radius=int(4 * scale))
                pygame.draw.rect(surface, _mix(palette["base"], palette["accent"], 0.65), pod, width=max(1, int(scale)), border_radius=int(4 * scale))
            _draw_poly(surface, _mix(palette["base"], palette["light"], 0.32),
                       [(-15, -28), (15, -28), (18, 22), (0, 31), (-18, 22)],
                       center, scale)
        elif kind == "engineer":
            for x in (-29, 29):
                pygame.draw.circle(surface, palette["dark"],
                                   _outline_points([(x, 6)], center, scale)[0], int(9 * scale))
                pygame.draw.circle(surface, palette["accent"],
                                   _outline_points([(x, 6)], center, scale)[0], int(6 * scale), max(1, int(1.4 * scale)))
            _draw_line(surface, _mix(palette["base"], palette["light"], 0.42), (-22, -16), (22, -16), center, scale, 1.4 * scale)
        elif kind == "interceptor":
            _draw_poly(surface, _mix(palette["base"], palette["light"], 0.40),
                       [(-9, -30), (0, -48), (9, -30), (0, -20)], center, scale)
            for x in (-29, 29):
                _draw_line(surface, palette["dark"], (x, 2), (x * 1.5, 25), center, scale, 3 * scale)
        else:
            for x in (-23, 0, 23):
                _draw_line(surface, _mix(palette["base"], palette["light"], 0.34), (x, -7), (x, 23), center, scale, 1.2 * scale)
            _draw_poly(surface, _mix(palette["base"], palette["dark"], 0.55),
                       [(-15, 23), (0, 30), (15, 23), (10, 36), (-10, 36)], center, scale)

    _draw_ship(big, palette, shapes[kind], center, scale, frame, details=details)
    return pygame.transform.smoothscale(big, (size, size))


def enemy_sprite(kind, frame):
    size = 168
    big = _surface((size * FACTOR, size * FACTOR))
    center = (size * FACTOR / 2, size * FACTOR / 2)
    scale = size * FACTOR / 120.0

    palettes = {
        "scout": {
            "base": (154, 70, 78), "dark": (48, 18, 30), "light": (255, 178, 170),
            "accent": (255, 98, 82), "engine": (255, 120, 56),
            "engines": [(-14, -42), (14, -42)], "lights": [(-33, -6), (33, -6)],
        },
        "fighter": {
            "base": (132, 68, 146), "dark": (44, 20, 56), "light": (255, 186, 255),
            "accent": (246, 96, 236), "engine": (212, 88, 255),
            "engines": [(-17, -43), (17, -43)], "lights": [(-42, 8), (42, 8)],
        },
        "bomber": {
            "base": (120, 64, 52), "dark": (42, 24, 22), "light": (255, 186, 130),
            "accent": (255, 134, 64), "engine": (255, 92, 48),
            "engines": [(-25, -39), (0, -44), (25, -39)], "lights": [(-46, 12), (46, 12)],
        },
        "raider": {
            "base": (62, 118, 148), "dark": (18, 40, 58), "light": (164, 236, 255),
            "accent": (80, 238, 255), "engine": (72, 186, 255),
            "engines": [(-22, -32), (22, -32)], "lights": [(-40, -4), (40, -4)],
        },
        "elite": {
            "base": (132, 114, 60), "dark": (38, 32, 20), "light": (255, 238, 164),
            "accent": (255, 206, 74), "engine": (255, 148, 48),
            "engines": [(-28, -36), (0, -43), (28, -36)], "lights": [(-46, 8), (46, 8)],
        },
    }
    # Enemies enter nose-down, so mirror the player silhouettes on Y.
    shapes = {
        "scout": [(0, 54), (-11, 28), (-18, 4), (-39, -18), (-36, -30),
                  (-16, -25), (-12, -44), (0, -37), (12, -44), (16, -25),
                  (36, -30), (39, -18), (18, 4), (11, 28)],
        "fighter": [(0, 60), (-13, 33), (-20, 8), (-48, -18), (-44, -32),
                    (-21, -24), (-14, -43), (0, -34), (14, -43), (21, -24),
                    (44, -32), (48, -18), (20, 8), (13, 33)],
        "bomber": [(0, 53), (-27, 39), (-34, 18), (-53, 2), (-52, -18),
                   (-32, -24), (-27, -43), (0, -35), (27, -43), (32, -24),
                   (52, -18), (53, 2), (34, 18), (27, 39)],
        "raider": [(0, 61), (-9, 28), (-27, 13), (-45, -22), (-23, -16),
                   (-13, -35), (0, -26), (13, -35), (23, -16), (45, -22),
                   (27, 13), (9, 28)],
        "elite": [(0, 51), (-18, 42), (-29, 23), (-50, 15), (-47, -9),
                  (-31, -14), (-25, -41), (-10, -33), (0, -44), (10, -33),
                  (25, -41), (31, -14), (47, -9), (50, 15), (29, 23), (18, 42)],
    }

    def details(surface, center, scale, frame, palette):
        if kind == "bomber":
            for x in (-33, 33):
                pod = pygame.Rect(int(center[0] + (x - 8) * scale),
                                  int(center[1] - 20 * scale),
                                  int(16 * scale), int(35 * scale))
                pygame.draw.rect(surface, palette["dark"], pod, border_radius=int(5 * scale))
                pygame.draw.rect(surface, _mix(palette["base"], palette["accent"], 0.7), pod, width=max(1, int(1.4 * scale)), border_radius=int(5 * scale))
            pygame.draw.circle(surface, palette["accent"],
                               _outline_points([(0, 8)], center, scale)[0], int(10 * scale))
        elif kind == "elite":
            for x in (-26, 26):
                pygame.draw.circle(surface, palette["dark"],
                                   _outline_points([(x, 8)], center, scale)[0], int(9 * scale))
                pygame.draw.circle(surface, palette["accent"],
                                   _outline_points([(x, 8)], center, scale)[0], int(5 * scale))
            _draw_line(surface, _mix(palette["base"], palette["light"], 0.5), (-22, -12), (22, -12), center, scale, 2 * scale)
        elif kind == "raider":
            _draw_poly(surface, _mix(palette["base"], palette["light"], 0.36),
                       [(-7, 28), (0, 20), (7, 28), (0, 40)], center, scale)
        else:
            for x in (-19, 19):
                _draw_line(surface, _mix(palette["base"], palette["light"], 0.32), (x, 2), (x, -25), center, scale, 1.2 * scale)

    palette = palettes[kind]
    _draw_ship(big, palette, shapes[kind], center, scale, frame, enemy=True, details=details)
    return pygame.transform.smoothscale(big, (size, size))


def boss_sprite(kind, frame):
    size = (480, 360)
    big = _surface((size[0] * 3, size[1] * 3))
    center = (size[0] * 1.5, size[1] * 1.5)
    scale = 2.9
    pulse = (0.7, 1.0)[frame % 2]

    if kind == "sentinel":
        base, dark, light, accent = (92, 82, 150), (26, 22, 50), (208, 198, 255), (190, 118, 255)
        engine = (110, 210, 255)
        shape = [(0, 140), (-48, 118), (-92, 72), (-122, 10), (-112, -54),
                 (-70, -92), (-22, -114), (22, -114), (70, -92), (112, -54),
                 (122, 10), (92, 72), (48, 118)]
    else:
        base, dark, light, accent = (122, 76, 70), (34, 22, 26), (255, 206, 174), (255, 112, 82)
        engine = (255, 138, 62)
        shape = [(0, 154), (-54, 132), (-108, 146), (-152, 102), (-140, 56),
                 (-174, 24), (-144, -42), (-98, -56), (-72, -112), (-28, -86),
                 (0, -132), (28, -86), (72, -112), (98, -56), (144, -42),
                 (174, 24), (140, 56), (152, 102), (108, 146), (54, 132)]

    for ex, ey in ((-70, 92), (70, 92), (-110, 32), (110, 32)):
        bloom = _glow(int(66 * scale), engine, 88)
        big.blit(bloom, bloom.get_rect(center=(int(center[0] + ex * scale), int(center[1] + ey * scale))),
                 special_flags=pygame.BLEND_RGBA_ADD)

    _draw_poly(big, (10, 10, 18, 250), [(x, y + 2) for x, y in shape], center, scale)
    _draw_poly(big, dark, shape, center, scale)
    _draw_poly(big, base, [(x * 0.83, y * 0.83) for x, y in shape], center, scale)
    _draw_poly(big, _mix(base, light, 0.18), [(x * 0.58, y * 0.6) for x, y in shape], center, scale)

    if kind == "sentinel":
        # Rotating eye core and armoured ring.
        for radius, color, width in ((78, accent, 10), (56, light, 4), (110, _mix(base, accent, 0.5), 3)):
            pygame.draw.circle(big, color, (int(center[0]), int(center[1])), int(radius * scale), int(width * scale))
        for index in range(8):
            angle = index * math.tau / 8 + frame * 0.18
            x = center[0] + math.cos(angle) * 94 * scale
            y = center[1] + math.sin(angle) * 94 * scale
            pygame.draw.circle(big, accent, (int(x), int(y)), int(9 * scale))
        core = _glow(int(56 * scale), (214, 166, 255), int(125 * pulse))
        big.blit(core, core.get_rect(center=(int(center[0]), int(center[1]))))
        pygame.draw.circle(big, (250, 245, 255), (int(center[0]), int(center[1])), int(15 * scale))
        pygame.draw.circle(big, dark, (int(center[0]), int(center[1])), int(8 * scale))
    else:
        # Dreadnought armour plates, turrets and a central furnace.
        for x in (-118, -58, 58, 118):
            pygame.draw.circle(big, dark, (int(center[0] + x * scale), int(center[1] + 42 * scale)), int(18 * scale))
            pygame.draw.circle(big, accent, (int(center[0] + x * scale), int(center[1] + 42 * scale)), int(8 * scale))
        for x in (-80, 0, 80):
            pygame.draw.rect(big, dark, (int(center[0] + (x - 7) * scale),
                                        int(center[1] + 78 * scale),
                                        int(14 * scale), int(46 * scale)),
                             border_radius=int(4 * scale))
        core = _glow(int(64 * scale), (255, 142, 88), int(120 * pulse))
        big.blit(core, core.get_rect(center=(int(center[0]), int(center[1] + 4 * scale))))
        pygame.draw.circle(big, dark, (int(center[0]), int(center[1] + 4 * scale)), int(34 * scale))
        pygame.draw.circle(big, accent, (int(center[0]), int(center[1] + 4 * scale)), int(22 * scale))
        pygame.draw.circle(big, (255, 240, 210), (int(center[0]), int(center[1] + 4 * scale)), int(10 * scale))
        _draw_line(big, _mix(base, light, 0.5), (-140, 20), (-52, -44), center, scale, 3 * scale)
        _draw_line(big, _mix(base, light, 0.5), (140, 20), (52, -44), center, scale, 3 * scale)

    return pygame.transform.smoothscale(big, size)


def planet_sprite(name, size=420):
    palette = {
        "azure": ((58, 120, 210), (8, 20, 52), (120, 200, 255),
                  (255, 238, 202), (80, 160, 255)),
        "ember": ((190, 86, 52), (38, 10, 16), (255, 176, 92),
                  (255, 226, 176), (255, 120, 70)),
        "verdant": ((62, 150, 116), (6, 32, 28), (150, 250, 190),
                    (220, 255, 210), (80, 255, 190)),
        "meme": ((228, 86, 180), (52, 8, 50), (255, 180, 236),
                 (255, 246, 160), (255, 120, 220)),
    }[name]
    base, shade, light, rim, atmo = palette
    rng = random.Random(name)

    # Render the sphere at low resolution, then upscale once.  This keeps the
    # terminator and the cloud bands smooth without per-pixel work at full size.
    low = max(96, size // 3)
    surface = pygame.Surface((low, low), pygame.SRCALPHA)
    cx = cy = low / 2
    radius = low * 0.455
    lx, ly, lz = -0.60, -0.56, 0.57

    craters = []
    for _ in range(16):
        angle = rng.uniform(0, math.tau)
        distance = rng.uniform(0, 0.78) * radius
        craters.append((
            cx + math.cos(angle) * distance,
            cy + math.sin(angle) * distance,
            rng.uniform(0.035, 0.105) * low,
            rng.uniform(0.18, 0.42),
        ))

    for py in range(low):
        for px in range(low):
            nx = (px - cx) / radius
            ny = (py - cy) / radius
            d2 = nx * nx + ny * ny
            if d2 > 1.16:
                continue
            if d2 > 1.0:
                # Thin atmospheric halo, brightest on the lit limb.
                edge = 1.0 - (math.sqrt(d2) - 1.0) / 0.16
                dot = max(0.0, nx * lx + ny * ly + 0.35)
                alpha = int(58 * max(0.0, edge) * (0.3 + 0.7 * dot))
                if alpha > 0:
                    surface.set_at((px, py), (*atmo, alpha))
                continue

            nz = math.sqrt(1.0 - d2)
            diffuse = max(0.0, nx * lx + ny * ly + nz * lz)
            lighting = 0.13 + 0.92 * diffuse ** 1.15

            band = 0.5 + 0.5 * math.sin(ny * 8.2 + math.sin(nx * 3.1) * 1.4 + 0.7)
            cloud = 0.5 + 0.5 * math.sin(ny * 15.0 + nx * 4.0 + 2.2)
            color = _mix(shade, base, 0.35 + 0.5 * band)
            color = _mix(color, light, 0.16 * cloud ** 2.4)

            for crater_x, crater_y, crater_r, strength in craters:
                dx = px - crater_x
                dy = py - crater_y
                distance = math.hypot(dx, dy)
                if distance < crater_r:
                    depth = 1.0 - distance / crater_r
                    color = _mix(color, shade, strength * depth)
                    if dy > 0 and distance > crater_r * 0.55:
                        color = _mix(color, light, strength * 0.30)

            if d2 > 0.90:
                limb = (d2 - 0.90) / 0.10
                color = _mix(color, rim, 0.45 * limb * max(0.0, diffuse) ** 0.8)
            lit = tuple(max(0, min(255, int(channel * lighting))) for channel in color)
            surface.set_at((px, py), (*lit, 255))

    big = pygame.transform.smoothscale(surface, (size, size))

    # A soft atmospheric bloom behind the limb.
    bloom = _glow(size, atmo, 44)
    halo = pygame.Surface((size, size), pygame.SRCALPHA)
    halo.blit(bloom, (0, 0))
    halo.blit(big, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
    big = halo

    if name == "meme":
        eye_white = (255, 255, 255)
        pupil = (34, 16, 34)
        for x in (-62, 62):
            pygame.draw.circle(big, eye_white, (int(cx + x), int(cy - 32)), 28)
            pygame.draw.circle(big, pupil, (int(cx + x + 8), int(cy - 26)), 13)
            pygame.draw.circle(big, (255, 240, 255), (int(cx + x + 2), int(cy - 38)), 5)
        pygame.draw.arc(big, pupil, (int(cx - 82), int(cy + 4), 164, 96), 0.2, math.pi - 0.2, 9)
        pygame.draw.circle(big, (255, 176, 224), (int(cx - 72), int(cy + 42)), 11)
        pygame.draw.circle(big, (255, 176, 224), (int(cx + 72), int(cy + 42)), 11)
    return big


def powerup_sprite(kind):
    size = 80
    f = 4
    big = _surface((size * f, size * f))
    c = size * f // 2
    colors = {
        "shield": (82, 196, 255),
        "life": (255, 92, 126),
        "weapon": (255, 202, 78),
        "rapid": (106, 255, 176),
        "points": (198, 132, 255),
    }
    color = colors[kind]
    big.blit(_glow(size * f, color, 110), (0, 0))
    pygame.draw.circle(big, (8, 14, 28, 235), (c, c), 27 * f)
    pygame.draw.circle(big, _alpha(color, 120), (c, c), 30 * f, 4 * f)
    pygame.draw.circle(big, color, (c, c), 27 * f, 2 * f)
    pygame.draw.circle(big, _alpha((255, 255, 255), 210), (int(c - 9 * f), int(c - 11 * f)), 5 * f)

    def points(items):
        return [(c + x * f, c + y * f) for x, y in items]

    if kind == "shield":
        shape = points([(0, -23), (17, -15), (14, 6), (0, 22), (-14, 6), (-17, -15)])
        pygame.draw.polygon(big, color, shape)
        pygame.draw.polygon(big, (255, 255, 255), shape, 2 * f)
    elif kind == "life":
        pygame.draw.circle(big, color, (c - 7 * f, c - 6 * f), 10 * f)
        pygame.draw.circle(big, color, (c + 7 * f, c - 6 * f), 10 * f)
        pygame.draw.polygon(big, color, points([(-17, -3), (17, -3), (0, 19)]))
        pygame.draw.circle(big, (255, 235, 235), (c - 5 * f, c - 9 * f), 3 * f)
    elif kind == "weapon":
        pygame.draw.rect(big, color, (c - 16 * f, c + 5 * f, 32 * f, 9 * f),
                         border_radius=3 * f)
        pygame.draw.rect(big, color, (c - 4 * f, c - 18 * f, 8 * f, 25 * f),
                         border_radius=3 * f)
        pygame.draw.rect(big, color, (c - 16 * f, c - 10 * f, 32 * f, 7 * f),
                         border_radius=3 * f)
        pygame.draw.circle(big, (255, 250, 210), (c, c - 21 * f), 5 * f)
    elif kind == "rapid":
        pygame.draw.polygon(big, color, points([
            (6, -24), (-13, 0), (-3, 0), (-9, 22), (16, -6), (4, -6),
        ]))
    else:
        points_list = []
        for index in range(10):
            angle = -math.pi / 2 + index * math.pi / 5
            distance = 20 if index % 2 == 0 else 9
            points_list.append((c + math.cos(angle) * distance * f,
                                c + math.sin(angle) * distance * f))
        pygame.draw.polygon(big, color, points_list)
        pygame.draw.polygon(big, (255, 255, 255), points_list, f)
    return pygame.transform.smoothscale(big, (size, size))


def bullet_sprite(kind):
    f = 3
    if kind == "player_lance":
        size = (40, 88)
    else:
        size = (40, 52)
    big = _surface((size[0] * f, size[1] * f))
    glow_color = {
        "player_pulse": (86, 220, 255),
        "player_burst": (255, 236, 126),
        "player_spread": (255, 156, 74),
        "player_lance": (214, 112, 255),
        "enemy_orb": (255, 88, 120),
        "enemy_plasma": (226, 92, 255),
    }[kind]
    if kind == "player_lance":
        w, h = size[0] * f, size[1] * f
        mid = w // 2
        pygame.draw.line(big, _alpha(glow_color, 70), (mid, 4 * f), (mid, h - 4 * f), 32 * f)
        pygame.draw.line(big, _alpha(glow_color, 150), (mid, 10 * f), (mid, h - 10 * f), 14 * f)
        pygame.draw.line(big, (255, 255, 255), (mid, 16 * f), (mid, h - 14 * f), 5 * f)
        pygame.draw.polygon(big, glow_color, [
            (mid, 0), (mid + 9 * f, 28 * f), (mid + 4 * f, 70 * f),
            (mid - 4 * f, 70 * f), (mid - 9 * f, 28 * f),
        ])
    else:
        w, h = size[0] * f, size[1] * f
        cx, cy = w // 2, h // 2
        glow_size = 40 * f
        big.blit(_glow(glow_size, glow_color, 150), (cx - glow_size // 2, cy - glow_size // 2))
        if kind == "player_spread":
            pygame.draw.polygon(big, glow_color, [
                (cx, 4 * f), (cx + 8 * f, 30 * f), (cx, 46 * f), (cx - 8 * f, 30 * f),
            ])
            pygame.draw.circle(big, (255, 246, 210), (cx, 26 * f), 5 * f)
        elif kind == "player_burst":
            pygame.draw.ellipse(big, glow_color, (cx - 5 * f, 4 * f, 10 * f, 40 * f))
            pygame.draw.ellipse(big, (255, 255, 230), (cx - 2 * f, 10 * f, 4 * f, 26 * f))
        elif kind.startswith("enemy"):
            pygame.draw.circle(big, _alpha(glow_color, 80), (cx, cy), 18 * f)
            pygame.draw.circle(big, glow_color, (cx, cy), 10 * f)
            pygame.draw.circle(big, (255, 240, 245), (cx, cy), 4 * f)
            pygame.draw.circle(big, _alpha(glow_color, 150), (cx, cy), 14 * f, 2 * f)
        else:
            pygame.draw.ellipse(big, glow_color, (cx - 6 * f, 3 * f, 12 * f, 42 * f))
            pygame.draw.ellipse(big, (255, 255, 255), (cx - 2 * f, 8 * f, 4 * f, 28 * f))
    return pygame.transform.smoothscale(big, size)


def main():
    pygame.init()
    for directory in (SHIP_DIR, ENEMY_DIR, BOSS_DIR, PLANET_DIR, POWERUP_DIR, BULLET_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    for kind in ("fighter", "interceptor", "tank", "engineer"):
        for frame in range(3):
            _save(ship_sprite(kind, frame), SHIP_DIR / f"{kind}_{frame}.png")

    for kind in ("scout", "fighter", "bomber", "raider", "elite"):
        for frame in range(3):
            _save(enemy_sprite(kind, frame), ENEMY_DIR / f"{kind}_{frame}.png")

    for kind in ("dreadnought", "sentinel"):
        for frame in range(2):
            _save(boss_sprite(kind, frame), BOSS_DIR / f"{kind}_{frame}.png")

    for name in ("azure", "ember", "verdant", "meme"):
        _save(planet_sprite(name), PLANET_DIR / f"planet_{name}.png")

    for kind in ("shield", "life", "weapon", "rapid", "points"):
        _save(powerup_sprite(kind), POWERUP_DIR / f"{kind}.png")

    for kind in ("player_pulse", "player_burst", "player_spread", "player_lance",
                 "enemy_orb", "enemy_plasma"):
        _save(bullet_sprite(kind), BULLET_DIR / f"{kind}.png")

    pygame.quit()
    print("Generated SpaceGame 2.0 sprite art.")


if __name__ == "__main__":
    main()
