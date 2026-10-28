"""Non-blocking Tiger Ultimate cinematic and its vector claw animation."""

from __future__ import annotations

import math
import json
import os
import threading

import pygame

from utils import VH, VW
from Localization import tr


class TigerUltimate:
    """A timed cinematic. Frames are optional so a missing decoder fails safe."""

    PHASES = (("freeze", .35), ("reveal", 2.7), ("claw_windup", .65),
              ("claw_strike", .72), ("clear", .25), ("return", 1.25))
    MIN_ENEMIES = 8
    DROP_CHANCE = .08

    def __init__(self, frames_dir=None):
        self.frames_dir = frames_dir or os.path.join(
            os.path.dirname(__file__), "assets", "video", "tiger_frames")
        self.frames = []
        self.frame_paths = []
        self.loader_stop = threading.Event()
        self.loader_thread = None
        self.fps = 24.0
        self.video_has_title = False
        self.frame_size = (1280, 720)
        self.frame_boxes = []
        self.frame_error = False
        self.elapsed = 0.0
        self.phase = "idle"
        self.phase_time = 0.0
        self.struck = False
        self.audio_started = False
        self.particles = []
        self.wave_time = 0.0

    @property
    def active(self):
        return self.phase != "idle"

    def _load_frames(self):
        try:
            metadata_path = os.path.join(self.frames_dir, "metadata.json")
            if os.path.isfile(metadata_path):
                with open(metadata_path, "r", encoding="utf-8") as metadata_file:
                    metadata = json.load(metadata_file)
                    self.fps = max(1.0, min(120.0,
                        float(metadata.get("fps", 24.0))))
                    frame_count = int(metadata.get("frames", 0))
                    self.video_has_title = bool(metadata.get("contains_title", False))
                    self.frame_size = (int(metadata.get("frame_width", 640)),
                                       int(metadata.get("frame_height", 360)))
                    self.frame_boxes = metadata.get("frame_boxes", [])
            else:
                frame_count = 0
            names = sorted(n for n in os.listdir(self.frames_dir)
                           if n.lower().endswith(".png"))
            if frame_count:
                names = names[:frame_count]
            self.frame_paths = [os.path.join(self.frames_dir, n) for n in names]
            self.frame_error = not bool(self.frame_paths)
            self.loader_stop.clear()
            self.loader_thread = threading.Thread(
                target=self._decode_frames, daemon=True,
                name="spacegame-tiger-video")
            self.loader_thread.start()
        except (OSError, pygame.error, MemoryError):
            self.frame_paths = []
            self.frame_error = True

    def _decode_frames(self):
        for path in self.frame_paths:
            if self.loader_stop.is_set():
                break
            try:
                self.frames.append(pygame.image.load(path))
            except (OSError, pygame.error, MemoryError):
                self.frame_error = True
                break

    def start(self):
        if not self.frame_paths and not self.frames and not self.frame_error:
            self._load_frames()
        self.phase, self.phase_time, self.elapsed = "freeze", 0.0, 0.0
        self.struck = self.audio_started = False
        self.particles.clear()
        self.wave_time = 0.0

    def cancel(self):
        self.phase = "idle"
        self.phase_time = self.elapsed = 0.0
        self.struck = False
        self.particles.clear()

    def close(self):
        self.loader_stop.set()
        if self.loader_thread is not None:
            self.loader_thread.join(timeout=.1)
        self.frames.clear()
        self.frame_paths.clear()

    def update(self, dt, audio_busy=False):
        if not self.active:
            return None
        dt = min(max(float(dt), 0.0), .05)
        self.elapsed += dt
        self.phase_time += dt
        idx = next((i for i, (name, duration) in enumerate(self.PHASES)
                    if name == self.phase), len(self.PHASES))
        name, duration = self.PHASES[idx]
        if self.phase_time >= duration:
            if name == "return" and audio_busy:
                self.phase_time = duration
                self._update_particles(dt)
                return None
            if idx + 1 >= len(self.PHASES):
                self.cancel()
                return "done"
            self.phase = self.PHASES[idx + 1][0]
            self.phase_time = 0.0
            if self.phase == "claw_strike":
                self.struck = True
                self._burst()
                return "strike"
        self._update_particles(dt)
        return None

    def _burst(self):
        self.wave_time = 0.0
        for i in range(44):
            angle = (math.tau * i / 44) + (i % 3) * .07
            speed = 100 + (i * 37 % 250)
            self.particles.append([VW * .5, VH * .52, math.cos(angle) * speed,
                                  math.sin(angle) * speed, .45 + (i % 6) * .09])

    def _update_particles(self, dt):
        self.wave_time += dt
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[4] -= dt
        self.particles[:] = [p for p in self.particles if p[4] > 0]

    def draw(self, surface, reduced_flash=False, quality=2, language="en"):
        if not self.active:
            return
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        alpha = 215
        if self.phase == "return":
            alpha = int(170 * max(0.0, 1.0 - self.phase_time / 1.25))
        overlay.fill((5, 4, 15, alpha))
        surface.blit(overlay, (0, 0))
        if self.phase in ("reveal", "claw_windup", "claw_strike"):
            self._draw_tiger(surface)
        if self.phase in ("claw_windup", "claw_strike", "clear"):
            self._draw_claws(surface, reduced_flash, quality)
        if (not self.video_has_title
                and self.phase in ("reveal", "claw_windup", "claw_strike")):
            font = pygame.font.SysFont("microsoftyahei,simhei,arialunicode", 54, bold=True)
            text = font.render("虎虎生威", True, (255, 213, 105))
            surface.blit(text, text.get_rect(center=(VW // 2, 95)))
        if self.phase in ("reveal", "claw_windup", "claw_strike"):
            if self.frame_error:
                notice = tr(language, "tiger_video_error")
            elif not self.frames:
                notice = tr(language, "tiger_video_loading")
            else:
                notice = None
            if notice:
                font = pygame.font.SysFont("arial", 20)
                surface.blit(font.render(notice, True, (255, 210, 170)),
                             (VW // 2 - 180, VH - 58))
        if self.particles:
            particle_layer = pygame.Surface((VW, VH), pygame.SRCALPHA)
            for x, y, _vx, _vy, life in self.particles:
                c = max(0, min(255, int(255 * min(1, life / .3))))
                pygame.draw.circle(particle_layer, (255, min(255, c), 175, c),
                                   (int(x), int(y)),
                                   max(1, int(4 * min(1, life))))
            surface.blit(particle_layer, (0, 0))

    def _draw_tiger(self, surface):
        if not self.frames:
            return
        reveal = self.elapsed - self.PHASES[0][1]
        idx = min(len(self.frames) - 1,
                  int(max(0, reveal) * self.fps))
        frame = self.frames[idx]
        max_w, max_h = VW * .83, VH * .71
        scale = min(max_w / self.frame_size[0], max_h / self.frame_size[1])
        image = pygame.transform.smoothscale(frame, (max(1, int(frame.get_width()*scale)),
                                                      max(1, int(frame.get_height()*scale))))
        box = (self.frame_boxes[idx] if idx < len(self.frame_boxes)
               else (0, 0, self.frame_size[0], self.frame_size[1]))
        left = VW * .5 - self.frame_size[0] * scale * .5 + box[0] * scale
        top = VH * .5 + 20 - self.frame_size[1] * scale * .5 + box[1] * scale
        surface.blit(image, (int(left), int(top)))

    def _draw_claws(self, surface, reduced_flash, quality):
        t = self.phase_time
        wind = self.phase == "claw_windup"
        alpha = 210 if reduced_flash else 255
        cx, cy = VW * .5, VH * .51
        lines = pygame.Surface((VW, VH), pygame.SRCALPHA)
        for i in range(4):
            local = t - i * .065
            if local < 0:
                continue
            offset = (i - 1.5) * 49
            if wind:
                line_progress = .2 + .3 * min(1.0, local / .65)
                fade = .45
            else:
                line_progress = min(1.0, local / .31)
                fade = max(0.0, min(1.0, (0.72 - local) / .30))
            line_length = min(VW, VH) * .8 * line_progress
            x1, y1 = cx - line_length*.32 + offset, cy - line_length*.36
            x2, y2 = x1 + line_length*.48, y1 + line_length*.72
            width = max(3, int(18 * (1 if quality >= 2 else .7)))
            a = int(alpha * fade)
            pygame.draw.line(lines, (255, 104, 24, a), (x1, y1), (x2, y2), width*2)
            pygame.draw.line(lines, (255, 232, 150, a), (x1, y1), (x2, y2), width)
            pygame.draw.line(lines, (255, 255, 232, a), (x1, y1), (x2, y2), max(2,width//3))
        surface.blit(lines, (0, 0))
        if self.phase == "claw_strike" and not reduced_flash and t < .12:
            flash = pygame.Surface((VW, VH), pygame.SRCALPHA)
            flash.fill((255, 240, 190, int(100 * (1-t/.12))))
            surface.blit(flash, (0, 0))
        if self.phase in ("claw_strike", "clear"):
            radius = int(min(VW, VH) * min(1, self.wave_time * 3.1))
            ring = pygame.Surface((VW, VH), pygame.SRCALPHA)
            pygame.draw.circle(ring, (255, 180, 75, 150), (int(cx), int(cy)), radius, 5)
            surface.blit(ring, (0, 0))
