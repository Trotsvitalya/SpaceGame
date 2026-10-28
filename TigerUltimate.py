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

    PHASES = (("freeze", .35), ("reveal", 3.05), ("claw_windup", .42),
              ("claw_strike", 2.05), ("clear", .25), ("return", 1.25))
    CLAW_PATHS = (
        ((-.08, .20), (1.08, .78)),
        ((-.08, .79), (1.08, .17)),
        ((-.08, .43), (1.08, .57)),
    )
    CHAINSAW_LANES = (.18, .38, .58, .78)
    CUT_EVENTS = (
        (.36, "claw", 0), (.72, "claw", 1), (1.08, "claw", 2),
        (1.26, "chainsaw", 0), (1.45, "chainsaw", 1),
        (1.64, "chainsaw", 2), (1.83, "chainsaw", 3),
    )
    MIN_ENEMIES = 3
    DROP_CHANCE = .20

    def __init__(self, frames_dir=None):
        self.frames_dir = frames_dir or os.path.join(
            os.path.dirname(__file__), "assets", "video", "tiger_frames")
        self.frames = []
        self.frame_paths = []
        self.loader_stop = threading.Event()
        self.loader_thread = None
        self.fps = 24.0
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
        self.next_cut_event = 0
        self.remote_cut_event = 0

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
        self.next_cut_event = self.remote_cut_event = 0

    def cancel(self):
        self.phase = "idle"
        self.phase_time = self.elapsed = 0.0
        self.struck = False
        self.particles.clear()
        self.next_cut_event = self.remote_cut_event = 0

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
            if (name == "reveal" and not self.frame_error
                    and self.loader_thread is not None
                    and self.loader_thread.is_alive()
                    and len(self.frames) < len(self.frame_paths)):
                self.phase_time = duration
                self._update_particles(dt)
                return None
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
                self.next_cut_event = 0
                self._burst()
                return "strike"
            if self.phase == "clear":
                return "clear"
        if (self.phase == "claw_strike"
                and self.next_cut_event < len(self.CUT_EVENTS)
                and self.phase_time >= self.CUT_EVENTS[self.next_cut_event][0]):
            _when, kind, index = self.CUT_EVENTS[self.next_cut_event]
            self.next_cut_event += 1
            self._burst_at(*self.impact_point(kind, index), count=26)
            return kind, index
        self._update_particles(dt)
        return None

    def _burst(self):
        self.wave_time = 0.0
        self._burst_at(VW * .5, VH * .52, count=44)

    def _burst_at(self, x, y, count=26):
        for i in range(count):
            angle = (math.tau * i / 44) + (i % 3) * .07
            speed = 100 + (i * 37 % 250)
            self.particles.append([x, y, math.cos(angle) * speed,
                                  math.sin(angle) * speed, .38 + (i % 6) * .07])

    @classmethod
    def cut_segment(cls, kind, index):
        if kind == "claw":
            start, end = cls.CLAW_PATHS[index]
            return (start[0] * VW, start[1] * VH,
                    end[0] * VW, end[1] * VH)
        y = cls.CHAINSAW_LANES[index] * VH
        return (-24.0, y, VW + 24.0, y)

    @classmethod
    def impact_point(cls, kind, index):
        x1, y1, x2, y2 = cls.cut_segment(kind, index)
        return ((x1 + x2) * .5, (y1 + y2) * .5)

    def sync_remote_cut_events(self):
        """Create matching local impact particles from host-synced timing."""
        if self.phase != "claw_strike":
            return
        while (self.remote_cut_event < len(self.CUT_EVENTS)
               and self.phase_time >= self.CUT_EVENTS[self.remote_cut_event][0]):
            _when, kind, index = self.CUT_EVENTS[self.remote_cut_event]
            self.remote_cut_event += 1
            self._burst_at(*self.impact_point(kind, index), count=26)

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
        if self.phase == "reveal":
            self._draw_tiger(surface)
        if self.phase in ("claw_windup", "claw_strike", "clear"):
            self._draw_claws(surface, reduced_flash, quality)
        if self.phase == "reveal":
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
        idx = min(len(self.frames) - 1,
                  int(max(0, self.phase_time) * self.fps))
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
        lines = pygame.Surface((VW, VH), pygame.SRCALPHA)
        for i, (start, end) in enumerate(self.CLAW_PATHS):
            cut_time = self.CUT_EVENTS[i][0]
            swipe_start = cut_time - .32
            local = (t - swipe_start) if not wind else t - i * .10
            if local < 0:
                continue
            if wind:
                line_progress = .14 + .26 * min(1.0, local / .5)
                fade = .45
            else:
                line_progress = min(1.0, local / .32)
                fade = max(0.0, min(1.0, 1.0 - max(0.0, local - .32) / .24))
            sx, sy = start[0] * VW, start[1] * VH
            ex, ey = end[0] * VW, end[1] * VH
            x1, y1 = sx + (ex - sx) * line_progress, sy + (ey - sy) * line_progress
            x2, y2 = sx, sy
            width = max(3, int((25 if not wind else 15) *
                               (1 if quality >= 2 else .72)))
            a = int(alpha * fade)
            pygame.draw.line(lines, (255, 104, 24, a), (x1, y1), (x2, y2), width*2)
            pygame.draw.line(lines, (255, 232, 150, a), (x1, y1), (x2, y2), width)
            pygame.draw.line(lines, (255, 255, 232, a), (x1, y1), (x2, y2), max(2,width//3))
        if self.phase == "claw_strike":
            for index, lane in enumerate(self.CHAINSAW_LANES):
                event_time = self.CUT_EVENTS[3 + index][0]
                saw_start = event_time - .19
                local = t - saw_start
                if not 0.0 <= local <= .24:
                    continue
                progress = min(1.0, local / .21)
                x = -20 + (VW + 40) * progress
                y = VH * lane
                pygame.draw.line(lines, (255, 111, 24, 135), (0, y), (x, y), 18)
                pygame.draw.line(lines, (255, 221, 131, 190), (0, y), (x, y), 7)
                self._draw_chainsaw(lines, x, y, t * 32 + index * .8, alpha)
        surface.blit(lines, (0, 0))
        if self.phase == "claw_strike" and not reduced_flash and t < .12:
            flash = pygame.Surface((VW, VH), pygame.SRCALPHA)
            flash.fill((255, 240, 190, int(100 * (1-t/.12))))
            surface.blit(flash, (0, 0))
        if self.phase in ("claw_strike", "clear"):
            radius = int(min(VW, VH) * min(1, self.wave_time * 1.8))
            ring = pygame.Surface((VW, VH), pygame.SRCALPHA)
            pygame.draw.circle(ring, (255, 180, 75, 150),
                               (VW // 2, VH // 2), radius, 5)
            surface.blit(ring, (0, 0))

    @staticmethod
    def _draw_chainsaw(surface, x, y, angle, alpha):
        blade = (int(x), int(y))
        radius = 25
        pygame.draw.circle(surface, (255, 180, 55, alpha), blade, radius + 7, 5)
        pygame.draw.circle(surface, (214, 223, 231, alpha), blade, radius, 4)
        for tooth in range(12):
            a = angle + tooth * math.tau / 12
            inner = (x + math.cos(a) * (radius - 3),
                     y + math.sin(a) * (radius - 3))
            outer = (x + math.cos(a + .09) * (radius + 5),
                     y + math.sin(a + .09) * (radius + 5))
            pygame.draw.line(surface, (255, 240, 190, alpha), inner, outer, 4)
        pygame.draw.rect(surface, (255, 131, 38, alpha),
                         (int(x - 42), int(y - 12), 36, 24), border_radius=7)
        pygame.draw.rect(surface, (255, 227, 151, alpha),
                         (int(x - 54), int(y - 7), 18, 14), border_radius=4)
