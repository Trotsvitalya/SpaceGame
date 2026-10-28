"""Application shell: display scaling, scene switching, fade transitions."""

from __future__ import annotations

import pygame

from AudioClass import AudioManager, MUSIC_END_EVENT
from CampaignData import mission_by_id
from CampaignProgress import CampaignProgress
from GameProcessClass import GameProcess
from MenuClass import Menu
from ResourcesClass import Resources
from SettingsClass import Leaderboard, Settings
from utils import VH, VW


class ScreenFade:
    def __init__(self):
        self.alpha = 255.0
        self.direction = -1  # -1 fading in, 1 fading out, 0 idle
        self.callback = None
        self.black = pygame.Surface((VW, VH))
        self.black.fill((0, 0, 0))

    @property
    def blocking(self):
        return self.direction == 1

    def to_black(self, callback):
        if self.direction == 1:
            return
        self.callback = callback
        self.direction = 1

    def update(self, dt):
        if self.direction == 1:
            self.alpha = min(255.0, self.alpha + 900.0 * dt)
            if self.alpha >= 255.0:
                callback = self.callback
                self.callback = None
                self.direction = -1
                if callback:
                    callback()
        elif self.direction == -1:
            self.alpha = max(0.0, self.alpha - 780.0 * dt)
            if self.alpha <= 0.0:
                self.direction = 0

    def draw(self, surface):
        if self.alpha <= 0:
            return
        self.black.set_alpha(int(self.alpha))
        surface.blit(self.black, (0, 0))


class App:
    def __init__(self, force_windowed=False):
        if not pygame.get_init():
            pygame.init()
        self.settings = Settings.load()
        if force_windowed:
            self.settings.fullscreen = False
        self.leaderboard = Leaderboard.load()
        self.campaign_progress = CampaignProgress.load()
        self._windowed_size = (VW, VH)
        self.window = None
        self.viewport = (0, 0, VW, VH)
        self.mouse = (-9999.0, -9999.0)
        self.running = True
        self._cursor_visible = True
        self._apply_display_mode()
        self.canvas = pygame.Surface((VW, VH)).convert()
        self.resources = Resources(self.settings)
        self.audio = AudioManager(self.settings)
        self._set_icon()
        self.clock = pygame.time.Clock()
        self.fade = ScreenFade()
        self.scene = Menu(self)
        self.scene.on_enter()

    # ------------------------------------------------------------- display
    def _set_icon(self):
        try:
            icon = pygame.transform.smoothscale(self.resources.ship_small, (32, 32))
            pygame.display.set_icon(icon)
        except (pygame.error, ValueError):
            pass

    def _apply_display_mode(self):
        try:
            if self.settings.fullscreen:
                self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                self.window = pygame.display.set_mode(self._windowed_size, pygame.RESIZABLE)
        except pygame.error:
            self.settings.fullscreen = False
            try:
                self.window = pygame.display.set_mode(self._windowed_size, pygame.RESIZABLE)
            except pygame.error:
                self.window = pygame.display.get_surface()
        pygame.display.set_caption("SpaceGame — Cosmic Shooter")
        self._compute_viewport()

    def apply_display_mode(self):
        if not self.settings.fullscreen:
            try:
                current = pygame.display.get_surface()
                if current and not (pygame.display.get_surface().get_flags() & pygame.FULLSCREEN):
                    size = current.get_size()
                    if size[0] >= 640 and size[1] >= 360:
                        self._windowed_size = size
            except pygame.error:
                pass
        self._apply_display_mode()

    def toggle_fullscreen(self):
        self.settings.fullscreen = not self.settings.fullscreen
        self.settings.save()
        self.apply_display_mode()

    def _compute_viewport(self):
        try:
            width, height = pygame.display.get_surface().get_size()
        except (pygame.error, AttributeError):
            width, height = VW, VH
        if width <= 0 or height <= 0:
            width, height = VW, VH
        scale = min(width / VW, height / VH)
        view_w = max(1, int(VW * scale))
        view_h = max(1, int(VH * scale))
        self.viewport = ((width - view_w) // 2, (height - view_h) // 2, view_w, view_h)

    def _update_mouse(self):
        self._compute_viewport()
        offset_x, offset_y, view_w, view_h = self.viewport
        try:
            mx, my = pygame.mouse.get_pos()
        except pygame.error:
            self.mouse = (-9999.0, -9999.0)
            return
        if offset_x <= mx < offset_x + view_w and offset_y <= my < offset_y + view_h:
            self.mouse = (
                (mx - offset_x) * VW / max(1, view_w),
                (my - offset_y) * VH / max(1, view_h),
            )
        else:
            self.mouse = (-9999.0, -9999.0)

    # -------------------------------------------------------------- scenes
    def set_scene(self, scene):
        try:
            self.scene.on_exit()
        except (pygame.error, AttributeError):
            pass
        self.scene = scene
        self.scene.on_enter()

    def transition_to(self, factory):
        self.fade.to_black(lambda: self.set_scene(factory()))

    def start_game(self, mode):
        self.settings.mode = mode
        self.settings.save()
        self.transition_to(lambda: GameProcess(self, mode))

    def start_campaign(self, mission_id, mode=None, difficulty=None):
        """Launch one campaign mission, remembering the player's choices."""
        mission = mission_by_id(mission_id)
        if mission is None:
            return None
        if not self.campaign_progress.is_unlocked(mission_id):
            return None
        mode = mode or self.settings.mode
        difficulty = (difficulty or self.campaign_progress.difficulty
                      or getattr(self.settings, "difficulty", "normal"))
        self.settings.mode = mode
        self.settings.difficulty = difficulty
        self.settings.save()
        self.campaign_progress.begin_mission(
            mission_id, ship=self.settings.ship, difficulty=difficulty
        )
        self.transition_to(lambda: GameProcess(
            self, mode, difficulty=difficulty, mission=mission,
            progress=self.campaign_progress,
        ))
        return mission

    def go_menu(self, screen="main"):
        self.transition_to(lambda: Menu(self, initial_screen=screen))

    def go_campaign(self, screen="campaign"):
        self.transition_to(lambda: Menu(self, initial_screen=screen))

    def quit(self):
        self.running = False

    # ----------------------------------------------------------------- run
    def run(self):
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._update_mouse()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit()
                    continue
                if event.type == pygame.VIDEORESIZE:
                    if not self.settings.fullscreen:
                        self._windowed_size = (max(800, event.w), max(450, event.h))
                        try:
                            self.window = pygame.display.set_mode(
                                self._windowed_size, pygame.RESIZABLE
                            )
                        except pygame.error:
                            pass
                        self._compute_viewport()
                    continue
                if event.type == MUSIC_END_EVENT:
                    self.audio.on_music_end()
                    continue
                if self.fade.blocking:
                    continue
                self.scene.handle_event(event, self.mouse)

            self.fade.update(dt)
            if not self.fade.blocking:
                self.scene.update(dt)

            self.scene.draw(self.canvas)
            self.fade.draw(self.canvas)
            self._present()

            want_cursor = not getattr(self.scene, "hide_cursor", False)
            if want_cursor != self._cursor_visible:
                self._cursor_visible = want_cursor
                pygame.mouse.set_visible(want_cursor)

        self.settings.save()
        try:
            self.audio.stop_music()
        except (pygame.error, AttributeError):
            pass

    def _present(self):
        window = pygame.display.get_surface()
        if window is None:
            return
        window.fill((0, 0, 0))
        offset_x, offset_y, view_w, view_h = self.viewport
        if view_w == VW and view_h == VH:
            window.blit(self.canvas, (offset_x, offset_y))
        else:
            scaled = pygame.transform.smoothscale(self.canvas, (view_w, view_h))
            window.blit(scaled, (offset_x, offset_y))
        pygame.display.flip()
