"""Menu scene: title screen, mode select, settings, leaderboard and help."""

from __future__ import annotations

import math
import random

import pygame

from EffectsClass import Effects, StarField
from Localization import LANGUAGE_NAMES, tr
from ResourcesClass import MEME_PALETTE, NORMAL_PALETTE, palette_for
from UIClass import (Button, Choice, Slider, Toggle, WidgetGroup, draw_bar,
                     draw_panel, draw_text, measure)
from utils import VH, VW, clamp, format_score


class MenuDeco:
    def __init__(self, resources):
        self.radius = random.randint(18, 40)
        index = random.randrange(len(resources.asteroid_sources))
        self.image = resources.asteroid(index, self.radius)
        self.x = random.uniform(0, VW)
        self.y = random.uniform(-VH, VH)
        self.vx = random.uniform(-12, 12)
        self.vy = random.uniform(14, 34)
        self.angle = random.uniform(0, 360)
        self.spin = random.uniform(-18, 18)
        self.alpha = random.randint(70, 140)

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle = (self.angle + self.spin * dt) % 360
        if self.x < -60:
            self.x = VW + 40
        elif self.x > VW + 60:
            self.x = -40
        if self.y > VH + 60:
            self.y = -60
            self.x = random.uniform(0, VW)

    def draw(self, surface):
        image = pygame.transform.rotozoom(self.image, self.angle, 1.0)
        image.set_alpha(self.alpha)
        surface.blit(image, image.get_rect(center=(int(self.x), int(self.y))))
        image.set_alpha(255)


class Menu:
    def __init__(self, app, initial_screen="main"):
        self.app = app
        self.settings = app.settings
        self.resources = app.resources
        self.audio = app.audio
        self.language = self.settings.language
        self.palette = NORMAL_PALETTE
        self.screen = initial_screen if initial_screen in (
            "main", "mode", "settings", "leaderboard", "controls"
        ) else "main"
        self.isRunMainLoop = True
        self.isStartGame = False
        self.isCloseGame = False

        self.starfield = StarField(seed=random.randint(1, 99999), count_scale=0.9)
        self.effects = Effects(self.resources)
        self.decor = [MenuDeco(self.resources) for _ in range(6)]
        self.background_index = random.randrange(self.resources.background_count)
        self.bg_offset = 0.0
        self.nebula_offset = 0.0
        self.time = 0.0
        self.screen_fade = 255.0
        self.mode_focus = 0 if self.settings.mode == "normal" else 1
        self.mode_rects = []
        self.back_rect = pygame.Rect(0, 0, 0, 0)
        self.widgets = None
        self.menu_buttons = []
        self.hero_frame = 0
        self.hero_timer = 0.0
        self.engine_timer = 0.0
        self.dim = pygame.Surface((VW, VH), pygame.SRCALPHA)
        self.dim.fill((3, 7, 18, 105))
        self._build_screen(self.screen)

    # ------------------------------------------------------------ lifecycle
    def on_enter(self):
        self.audio.play_music("menu", "normal")

    def on_exit(self):
        self.audio.stop_music()

    def _hover_sound(self):
        self.audio.play("ui_hover", 0.35, throttle_ms=55)

    def _click_sound(self):
        self.audio.play("ui_click", 0.55)

    def _set_screen(self, name):
        self.screen = name
        self.screen_fade = 255.0
        self._build_screen(name)
        self._click_sound()

    def _build_screen(self, name):
        self.widgets = None
        self.menu_buttons = []
        self.mode_rects = []
        if name == "main":
            x = 105
            y = 300
            width = 342
            height = 52
            gap = 61
            specs = [
                (tr(self.language, "new_game"), "new_game"),
                (tr(self.language, "leaderboard"), "leaderboard"),
                (tr(self.language, "settings"), "settings"),
                (tr(self.language, "how_to_play"), "controls"),
                (tr(self.language, "quit"), "quit"),
            ]
            widgets = []
            for index, (label, action) in enumerate(specs):
                widgets.append(Button((x, y + index * gap, width, height),
                                      label, action,
                                      size=22,
                                      accent=NORMAL_PALETTE["danger"] if action == "quit"
                                      else NORMAL_PALETTE["accent"]))
            self.widgets = WidgetGroup(widgets, on_hover=self._hover_sound)
        elif name == "mode":
            self.mode_focus = 0 if self.settings.mode == "normal" else 1
        elif name == "settings":
            self._build_settings()
        elif name == "leaderboard":
            self._build_single_back()
        elif name == "controls":
            self._build_single_back()

    def _build_single_back(self):
        self.widgets = WidgetGroup([
            Button((VW // 2 - 130, VH - 96, 260, 46),
                   lambda: tr(self.language, "back"), "back", size=20)
        ], on_hover=self._hover_sound)

    def _build_settings(self):
        cx = VW // 2
        left = cx - 330
        width = 660
        top = 104

        def save_and_apply():
            self.settings.save()
            self.audio.apply_settings()

        def save_only():
            self.settings.save()

        def apply_language():
            self.language = self.settings.language
            self.audio.play("ui_click", 0.4)
            self.settings.save()

        def apply_fullscreen():
            self.settings.save()
            self.app.apply_display_mode()
            self.audio.apply_settings()

        widgets = [
            Slider((left, top + 82, width, 40),
                   lambda: tr(self.language, "music"),
                   lambda: self.settings.music_volume,
                   lambda value: setattr(self.settings, "music_volume", value),
                   save_and_apply),
            Slider((left, top + 132, width, 40),
                   lambda: tr(self.language, "sfx"),
                   lambda: self.settings.sfx_volume,
                   lambda value: setattr(self.settings, "sfx_volume", value),
                   save_and_apply),
            Toggle((left, top + 186, width, 40),
                   lambda: tr(self.language, "mute"),
                   lambda: self.settings.muted,
                   lambda value: setattr(self.settings, "muted", value),
                   save_and_apply),
            Toggle((left, top + 232, width, 40),
                   lambda: tr(self.language, "fullscreen"),
                   lambda: self.settings.fullscreen,
                   lambda value: setattr(self.settings, "fullscreen", value),
                   apply_fullscreen),
            Toggle((left, top + 278, width, 40),
                   lambda: tr(self.language, "screen_shake"),
                   lambda: self.settings.screen_shake,
                   lambda value: setattr(self.settings, "screen_shake", value),
                   save_only),
            Toggle((left, top + 324, width, 40),
                   lambda: tr(self.language, "show_fps"),
                   lambda: self.settings.show_fps,
                   lambda value: setattr(self.settings, "show_fps", value),
                   save_only),
            Choice((left, top + 370, width, 40),
                   lambda: tr(self.language, "language"),
                   [("uk", LANGUAGE_NAMES["uk"]), ("en", LANGUAGE_NAMES["en"])],
                   lambda: 0 if self.settings.language == "uk" else 1,
                   self._set_language_index,
                   apply_language),
            Button((cx - 130, top + 430, 260, 44),
                   lambda: tr(self.language, "back"), "back", size=20),
        ]
        self.widgets = WidgetGroup(widgets, on_hover=self._hover_sound)

    def _set_language_index(self, index):
        self.settings.language = "uk" if index == 0 else "en"
        self.language = self.settings.language

    # ---------------------------------------------------------------- input
    def handle_event(self, event, mouse=None):
        mouse = mouse or self.app.mouse
        if event.type == pygame.QUIT:
            self.app.quit()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.app.toggle_fullscreen()
            return

        if self.screen == "mode":
            self._handle_mode_event(event, mouse)
            return

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.screen == "main":
                self._click_sound()
                self.app.quit()
            else:
                self._set_screen("main")
            return

        if self.widgets is not None:
            action = self.widgets.handle_event(event, mouse)
            if action:
                self._handle_action(action)

    def _handle_mode_event(self, event, mouse):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._set_screen("main")
            elif event.key in (pygame.K_LEFT, pygame.K_a, pygame.K_UP, pygame.K_w):
                self.mode_focus = 0
                self._hover_sound()
            elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN, pygame.K_s):
                self.mode_focus = 1
                self._hover_sound()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._start(("normal", "meme")[self.mode_focus])
        elif event.type == pygame.MOUSEMOTION:
            for index, rect in enumerate(self.mode_rects):
                if rect.collidepoint(mouse):
                    if self.mode_focus != index:
                        self.mode_focus = index
                        self._hover_sound()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for index, rect in enumerate(self.mode_rects):
                if rect.collidepoint(mouse):
                    self._start(("normal", "meme")[index])
                    return
            if self.back_rect.collidepoint(mouse):
                self._set_screen("main")

    def _handle_action(self, action):
        if action == "quit":
            self._click_sound()
            self.app.quit()
        elif action == "new_game":
            self._set_screen("mode")
        elif action in ("leaderboard", "settings", "controls"):
            self._set_screen(action)
        elif action == "back":
            self._set_screen("main")
        elif action.startswith("start_"):
            self._start(action.split("_", 1)[1])

    def _start(self, mode):
        self._click_sound()
        self.settings.mode = mode
        self.settings.save()
        self.app.start_game(mode)

    # --------------------------------------------------------------- update
    def update(self, dt):
        dt = min(max(dt, 0.0), 0.05)
        self.time += dt
        self.screen_fade = max(0.0, self.screen_fade - dt * 620.0)
        self.starfield.update(dt, 8.0)
        self.bg_offset = (self.bg_offset + 8.0 * dt) % (VH * 2)
        self.nebula_offset = (self.nebula_offset + 4.0 * dt) % VH
        self.effects.update(dt)
        for decor in self.decor:
            decor.update(dt)
        self.hero_timer += dt
        if self.hero_timer >= 0.1:
            self.hero_timer = 0.0
            self.hero_frame = (self.hero_frame + 1) % len(self.resources.ship_large)
        self.engine_timer += dt
        if self.screen == "main":
            while self.engine_timer >= 0.045:
                self.engine_timer -= 0.045
                self.effects.engine(
                    VW - 300 + random.uniform(-7, 7),
                    458 + random.uniform(-3, 3),
                    NORMAL_PALETTE["accent"], 0.6,
                )

    # ----------------------------------------------------------------- draw
    def draw(self, canvas):
        palette = self.palette
        background = self.resources.background(self.background_index, "normal")
        background_flip = self.resources.background_flipped(self.background_index, "normal")
        bg_y = -(int(self.bg_offset) % (VH * 2))
        for index in range(3):
            tile = background if index % 2 == 0 else background_flip
            canvas.blit(tile, (0, bg_y + index * VH))

        nebula = self.resources.nebula("normal")
        neb_y = int(self.nebula_offset)
        canvas.blit(nebula, (0, neb_y - VH))
        canvas.blit(nebula, (0, neb_y))

        planet = self.resources.menu_planet("normal")
        planet.set_alpha(120)
        canvas.blit(planet, (VW - 360, 78 + int(math.sin(self.time * 0.35) * 12)))
        planet.set_alpha(255)

        self.starfield.draw(canvas, palette["star"], 8.0)
        for decor in self.decor:
            decor.draw(canvas)
        canvas.blit(self.resources.menu_grid, (0, 0))
        if self.screen == "main":
            self._draw_hero(canvas)
        self.effects.draw(canvas)
        canvas.blit(self.resources.vignette, (0, 0))
        if self.screen != "main":
            canvas.blit(self.dim, (0, 0))

        if self.screen == "main":
            self._draw_main(canvas)
        elif self.screen == "mode":
            self._draw_mode(canvas)
        elif self.screen == "settings":
            self._draw_settings(canvas)
        elif self.screen == "leaderboard":
            self._draw_leaderboard(canvas)
        elif self.screen == "controls":
            self._draw_controls(canvas)

        if self.screen_fade > 0:
            overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
            overlay.fill((2, 4, 10, int(min(255, self.screen_fade))))
            canvas.blit(overlay, (0, 0))

    def _draw_hero(self, canvas):
        center = (VW - 300, 360 + int(math.sin(self.time * 1.2) * 8))
        ring_color = NORMAL_PALETTE["accent"]
        pygame.draw.circle(canvas, (30, 60, 92), center, 146, 1)
        pygame.draw.circle(canvas, (52, 110, 154), center, 128, 1)
        for index in range(3):
            angle = self.time * 0.5 + index * math.tau / 3
            x = center[0] + math.cos(angle) * 146
            y = center[1] + math.sin(angle) * 146
            pygame.draw.circle(canvas, ring_color, (int(x), int(y)), 3)

        glow = self.resources.glow(150, (40, 120, 200), 55)
        canvas.blit(glow, glow.get_rect(center=center))
        frame = self.resources.ship_large[self.hero_frame % len(self.resources.ship_large)]
        rect = frame.get_rect(center=center)
        canvas.blit(frame, rect)

        flame_y = center[1] + 105
        flicker = math.sin(self.time * 27) * 6
        pygame.draw.polygon(canvas, (255, 140, 50), [
            (center[0] - 18, flame_y),
            (center[0] + 18, flame_y),
            (center[0] + flicker, flame_y + 38 + math.sin(self.time * 13) * 8),
        ])
        pygame.draw.polygon(canvas, (255, 240, 160), [
            (center[0] - 7, flame_y),
            (center[0] + 7, flame_y),
            (center[0] + flicker * 0.4, flame_y + 20),
        ])

        # Hero stats card.
        best = self.app.leaderboard.best(self.settings.mode)
        card = pygame.Rect(VW - 470, VH - 154, 410, 80)
        draw_panel(canvas, card, (*NORMAL_PALETTE["panel"], 185),
                   NORMAL_PALETTE["border"], 12, 1)
        mode_key = "meme_badge" if self.settings.mode == "meme" else "normal_badge"
        draw_text(canvas, self.resources, tr(self.language, mode_key), 10,
                  NORMAL_PALETTE["accent2"] if self.settings.mode == "meme"
                  else NORMAL_PALETTE["muted"], (card.x + 18, card.y + 12))
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'best')}: {format_score(best)}", 22,
                  NORMAL_PALETTE["accent"], (card.x + 18, card.y + 28))
        draw_text(canvas, self.resources, tr(self.language, "footer"), 10,
                  NORMAL_PALETTE["muted"], (card.right - 18, card.y + 18),
                  anchor="topright")
        draw_text(canvas, self.resources, tr(self.language, "add_music_hint"), 10,
                  NORMAL_PALETTE["muted"], (card.right - 18, card.y + 38),
                  anchor="topright")

    def _draw_main(self, canvas):
        palette = self.palette
        draw_text(canvas, self.resources, "SPACE", 64, palette["text"],
                  (100, 58), kind="title", shadow=(3, 7, 18))
        draw_text(canvas, self.resources, "GAME", 92, palette["accent"],
                  (100, 116), kind="title", shadow=(3, 8, 20))
        draw_text(canvas, self.resources, tr(self.language, "subtitle"), 18,
                  palette["accent"], (108, 220))
        draw_text(canvas, self.resources, tr(self.language, "tagline"), 15,
                  palette["text"], (108, 254), alpha=185)
        pygame.draw.line(canvas, palette["accent"], (108, 278), (448, 278), 1)
        self.widgets.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources, tr(self.language, "focus_hint"), 11,
                  palette["muted"], (VW // 2, VH - 28), anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "version"), 11,
                  palette["muted"], (VW - 30, VH - 28), anchor="bottomright")

    def _draw_mode(self, canvas):
        palette = self.palette
        draw_text(canvas, self.resources, tr(self.language, "select_mode"), 44,
                  palette["text"], (VW // 2, 78), anchor="center",
                  shadow=(2, 6, 16))
        draw_text(canvas, self.resources, tr(self.language, "choose_mode_hint"), 15,
                  palette["muted"], (VW // 2, 124), anchor="center")

        card_w = 400
        card_h = 300
        top = 190
        lefts = (VW // 2 - card_w - 30, VW // 2 + 30)
        self.mode_rects = [
            pygame.Rect(lefts[0], top, card_w, card_h),
            pygame.Rect(lefts[1], top, card_w, card_h),
        ]
        modes = ("normal", "meme")
        for index, rect in enumerate(self.mode_rects):
            mode = modes[index]
            mode_palette = palette_for(mode)
            focused = index == self.mode_focus
            fill = (18, 30, 58, 235) if mode == "normal" else (58, 18, 62, 235)
            border = mode_palette["accent"] if focused else palette["border"]
            draw_panel(canvas, rect.move(0, -6 if focused else 0), fill, border,
                       radius=16, width=3 if focused else 1)
            if focused:
                glow = self.resources.glow(120, mode_palette["accent"], 42)
                canvas.blit(glow, glow.get_rect(center=(rect.centerx, rect.y + 8)))
            icon_y = rect.y + 86
            if mode == "normal":
                frame = self.resources.ship_large[0]
                image = pygame.transform.smoothscale(frame, (116, 116))
                canvas.blit(image, image.get_rect(center=(rect.centerx, icon_y)))
            else:
                planet = self.resources.menu_planet("meme")
                image = pygame.transform.smoothscale(planet, (132, 132))
                canvas.blit(image, image.get_rect(center=(rect.centerx, icon_y)))
            title_key = "mode_normal" if mode == "normal" else "mode_meme"
            draw_text(canvas, self.resources, tr(self.language, title_key), 26,
                      mode_palette["accent"], (rect.centerx, rect.y + 158),
                      anchor="center")
            draw_text(canvas, self.resources,
                      tr(self.language, "normal_badge" if mode == "normal" else "meme_badge"),
                      11, palette["text"], (rect.centerx, rect.y + 184), anchor="center",
                      alpha=190)
            desc_key = "mode_normal_desc" if mode == "normal" else "mode_meme_desc"
            lines = self.resources.wrap_text(
                tr(self.language, desc_key), 14, rect.width - 60
            )
            for line_index, line in enumerate(lines[:4]):
                draw_text(canvas, self.resources, line, 14, palette["text"],
                          (rect.centerx, rect.y + 210 + line_index * 20),
                          anchor="center")

        self.back_rect = pygame.Rect(VW // 2 - 130, VH - 90, 260, 44)
        hovered = self.back_rect.collidepoint(self.app.mouse)
        draw_panel(canvas, self.back_rect,
                   (18, 30, 58, 210) if not hovered else (30, 50, 80, 230),
                   palette["accent"] if hovered else palette["border"], 10, 2 if hovered else 1)
        draw_text(canvas, self.resources, tr(self.language, "back"), 20,
                  palette["accent"] if hovered else palette["text"],
                  self.back_rect.center, anchor="center")
        draw_text(canvas, self.resources, "← →  ·  ENTER  ·  ESC", 12,
                  palette["muted"], (VW // 2, VH - 34), anchor="center")

    def _draw_settings(self, canvas):
        palette = self.palette
        draw_text(canvas, self.resources, tr(self.language, "settings_title"), 40,
                  palette["text"], (VW // 2, 56), anchor="center", shadow=(2, 5, 14))
        panel = pygame.Rect(VW // 2 - 390, 96, 780, 520)
        draw_panel(canvas, panel, (*palette["panel"], 224), palette["border"], 16, 2)
        self.widgets.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources, tr(self.language, "settings_saved"), 11,
                  palette["muted"], (VW // 2, panel.bottom + 22), anchor="center")
        if not self.audio.enabled:
            draw_text(canvas, self.resources, tr(self.language, "audio_unavailable"), 12,
                      palette["warning"], (VW // 2, panel.bottom + 42), anchor="center")

    def _draw_leaderboard(self, canvas):
        palette = self.palette
        draw_text(canvas, self.resources, tr(self.language, "leaderboard_title"), 40,
                  palette["text"], (VW // 2, 56), anchor="center", shadow=(2, 5, 14))
        draw_text(canvas, self.resources, tr(self.language, "focus_hint"), 11,
                  palette["muted"], (VW // 2, 106), anchor="center")

        panel_w = 540
        panel_h = 450
        top = 140
        for index, mode in enumerate(("normal", "meme")):
            x = VW // 2 - panel_w - 20 if index == 0 else VW // 2 + 20
            rect = pygame.Rect(x, top, panel_w, panel_h)
            mode_palette = palette_for(mode)
            draw_panel(canvas, rect, (*palette["panel"], 220), mode_palette["accent"], 14, 1)
            title = tr(self.language, "mode_normal" if mode == "normal" else "mode_meme")
            draw_text(canvas, self.resources, title, 21, mode_palette["accent"],
                      (rect.centerx, rect.y + 20), anchor="midtop")
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'rank')}    {tr(self.language, 'score')}",
                      11, palette["muted"], (rect.x + 30, rect.y + 56))
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'wave')}   {tr(self.language, 'time')}",
                      11, palette["muted"], (rect.right - 30, rect.y + 56),
                      anchor="topright")
            board = self.app.leaderboard.board(mode)
            if not board:
                draw_text(canvas, self.resources, tr(self.language, "leaderboard_empty"),
                          14, palette["muted"], (rect.centerx, rect.y + 190),
                          anchor="center")
            else:
                for rank, entry in enumerate(board[:8], start=1):
                    row_y = rect.y + 84 + (rank - 1) * 40
                    if rank % 2 == 0:
                        pygame.draw.rect(canvas, (24, 38, 66),
                                         (rect.x + 18, row_y - 5, rect.width - 36, 34),
                                         border_radius=6)
                    color = mode_palette["accent"] if rank == 1 else palette["text"]
                    draw_text(canvas, self.resources, f"{rank:02d}", 14,
                              palette["muted"], (rect.x + 34, row_y))
                    draw_text(canvas, self.resources, format_score(entry["score"]), 20,
                              color, (rect.x + 80, row_y - 2), kind="title")
                    draw_text(canvas, self.resources,
                              f"{entry['wave']:02d}       {entry.get('date', '')}",
                              11, palette["muted"], (rect.right - 30, row_y + 3),
                              anchor="topright")
        self.widgets.draw(canvas, self.resources, palette)

    def _draw_controls(self, canvas):
        palette = self.palette
        draw_text(canvas, self.resources, tr(self.language, "controls_title"), 40,
                  palette["text"], (VW // 2, 56), anchor="center", shadow=(2, 5, 14))
        panel = pygame.Rect(VW // 2 - 390, 120, 780, 430)
        draw_panel(canvas, panel, (*palette["panel"], 226), palette["border"], 16, 2)
        rows = [
            ("ctrl_move", "ctrl_move_keys"),
            ("ctrl_fire", "ctrl_fire_keys"),
            ("ctrl_pause", "ctrl_pause_keys"),
            ("ctrl_fullscreen", "ctrl_fullscreen_keys"),
            ("ctrl_menu", "ctrl_menu_keys"),
        ]
        y = panel.y + 44
        for label_key, keys_key in rows:
            draw_text(canvas, self.resources, tr(self.language, label_key), 13,
                      palette["muted"], (panel.x + 42, y + 8))
            key_text = tr(self.language, keys_key)
            key_rect = pygame.Rect(panel.x + 220, y, panel.width - 270, 38)
            draw_panel(canvas, key_rect, (18, 28, 50, 210), palette["border"], 8, 1)
            draw_text(canvas, self.resources, key_text, 17, palette["accent"],
                      (key_rect.x + 16, key_rect.centery), anchor="midleft")
            y += 56
        draw_text(canvas, self.resources, tr(self.language, "ctrl_tip"), 13,
                  palette["text"], (panel.centerx, panel.bottom - 76), anchor="center")
        self.widgets.draw(canvas, self.resources, palette)
