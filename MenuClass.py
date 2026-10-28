"""Menu scenes: title, mode select, hangar, settings, leaderboard and help.

The visual layer comes from :class:`SpaceBackdrop`, the same cached parallax
system the gameplay uses, so the menu and the run share one look.  All ship
data is read from :mod:`GameData`; nothing here hard-codes archetype numbers.
"""

from __future__ import annotations

import math
import random

import pygame

from EffectsClass import Effects
from GameData import SHIPS, SHIP_ORDER, WEAPONS, ZONES
from Localization import LANGUAGE_NAMES, tr
from ResourcesClass import MEME_PALETTE, NORMAL_PALETTE, palette_for
from SpaceBackdrop import SpaceBackdrop
from UIClass import (Button, Choice, Slider, Toggle, WidgetGroup, draw_bar,
                     draw_panel, draw_text)
from utils import VH, VW, clamp, format_score

SCREENS = ("main", "mode", "hangar", "settings", "leaderboard", "controls")


class MenuDeco:
    """A slowly tumbling asteroid in the menu foreground."""

    def __init__(self, resources):
        self.resources = resources
        self.radius = random.randint(18, 40)
        self.index = random.randrange(len(resources.asteroid_sources))
        self.x = random.uniform(0, VW)
        self.y = random.uniform(-VH, VH)
        self.vx = random.uniform(-12, 12)
        self.vy = random.uniform(14, 34)
        self.angle = random.uniform(0, 360)
        self.spin = random.uniform(-18, 18)
        self.alpha = random.randint(60, 120)

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
        image = self.resources.asteroid_rot(self.index, self.radius, self.angle)
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
        self.screen = initial_screen if initial_screen in SCREENS else "main"
        self.isRunMainLoop = True
        self.isStartGame = False
        self.isCloseGame = False
        self.hide_cursor = False

        quality = getattr(self.settings, "effects_quality", 2)
        self.backdrop = SpaceBackdrop(
            self.resources, "normal", zone=3, seed=random.randint(1, 99999),
            quality=quality, planet_scale=0.9,
        )
        self.effects = Effects(self.resources, quality=quality,
                               reduced_flash=getattr(self.settings, "reduced_flash", False))
        self.decor = [MenuDeco(self.resources) for _ in range(5)]
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
        self.dim.fill((3, 7, 18, 120))
        self.hangar_focus = SHIP_ORDER.index(self.settings.ship) \
            if self.settings.ship in SHIP_ORDER else 0
        self.hangar_cards = []
        self.hangar_select_rect = pygame.Rect(0, 0, 0, 0)
        self.hangar_back_rect = pygame.Rect(0, 0, 0, 0)
        self.hangar_frames = {
            kind: [pygame.transform.smoothscale(frame, (158, 158))
                   for frame in self.resources.ship_large_for(kind)]
            for kind in SHIP_ORDER
        }
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
            x = 100
            y = 300
            width = 342
            height = 52
            gap = 60
            specs = [
                (tr(self.language, "new_game"), "new_game"),
                (tr(self.language, "hangar"), "hangar"),
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
        elif name == "hangar":
            self.hangar_focus = (SHIP_ORDER.index(self.settings.ship)
                                 if self.settings.ship in SHIP_ORDER else 0)
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

        def apply_effects():
            self.effects.set_reduced_flash(self.settings.reduced_flash)
            self.settings.save()

        def apply_language():
            self.language = self.settings.language
            self.audio.play("ui_click", 0.4)
            self.settings.save()

        def apply_fullscreen():
            self.settings.save()
            self.app.apply_display_mode()
            self.audio.apply_settings()

        quality_labels = (
            lambda: tr(self.language, "quality_low"),
            lambda: tr(self.language, "quality_medium"),
            lambda: tr(self.language, "quality_high"),
        )
        widgets = [
            Slider((left, top - 4, width, 40),
                   lambda: tr(self.language, "music"),
                   lambda: self.settings.music_volume,
                   lambda value: setattr(self.settings, "music_volume", value),
                   save_and_apply),
            Slider((left, top + 42, width, 40),
                   lambda: tr(self.language, "sfx"),
                   lambda: self.settings.sfx_volume,
                   lambda value: setattr(self.settings, "sfx_volume", value),
                   save_and_apply),
            Toggle((left, top + 88, width, 40),
                   lambda: tr(self.language, "mute"),
                   lambda: self.settings.muted,
                   lambda value: setattr(self.settings, "muted", value),
                   save_and_apply),
            Toggle((left, top + 134, width, 40),
                   lambda: tr(self.language, "fullscreen"),
                   lambda: self.settings.fullscreen,
                   lambda value: setattr(self.settings, "fullscreen", value),
                   apply_fullscreen),
            Toggle((left, top + 180, width, 40),
                   lambda: tr(self.language, "screen_shake"),
                   lambda: self.settings.screen_shake,
                   lambda value: setattr(self.settings, "screen_shake", value),
                   save_only),
            Toggle((left, top + 226, width, 40),
                   lambda: tr(self.language, "show_fps"),
                   lambda: self.settings.show_fps,
                   lambda value: setattr(self.settings, "show_fps", value),
                   save_only),
            Choice((left, top + 272, width, 40),
                   lambda: tr(self.language, "effects_quality"),
                   [(0, quality_labels[0]), (1, quality_labels[1]),
                    (2, quality_labels[2])],
                   lambda: int(getattr(self.settings, "effects_quality", 2)),
                   self._set_quality_index,
                   save_only),
            Toggle((left, top + 318, width, 40),
                   lambda: tr(self.language, "reduced_flash"),
                   lambda: self.settings.reduced_flash,
                   lambda value: setattr(self.settings, "reduced_flash", value),
                   apply_effects),
            Toggle((left, top + 364, width, 40),
                   lambda: tr(self.language, "auto_pause"),
                   lambda: self.settings.auto_pause,
                   lambda value: setattr(self.settings, "auto_pause", value),
                   save_only),
            Choice((left, top + 410, width, 40),
                   lambda: tr(self.language, "language"),
                   [("uk", LANGUAGE_NAMES["uk"]), ("en", LANGUAGE_NAMES["en"])],
                   lambda: 0 if self.settings.language == "uk" else 1,
                   self._set_language_index,
                   apply_language),
            Button((cx - 130, top + 462, 260, 44),
                   lambda: tr(self.language, "back"), "back", size=20),
        ]
        self.widgets = WidgetGroup(widgets, on_hover=self._hover_sound)

    def _set_language_index(self, index):
        self.settings.language = "uk" if index == 0 else "en"
        self.language = self.settings.language

    def _set_quality_index(self, index):
        self.settings.effects_quality = max(0, min(2, int(index)))
        self.backdrop.set_quality(self.settings.effects_quality)
        self.effects.set_quality(self.settings.effects_quality)

    def _select_ship(self, kind):
        if kind not in SHIPS:
            return
        if self.settings.ship != kind:
            self.settings.ship = kind
            self.resources.select_ship(kind)
            self.hero_frame = 0
            self.audio.play("powerup", 0.7)
            try:
                self.app._set_icon()
            except (AttributeError, pygame.error):
                pass
        else:
            self._click_sound()
        self.settings.save()
        viewport = (VW // 2, VH - 96)
        self.effects.ring(*viewport, NORMAL_PALETTE["accent"], 96, 0.55, 3)
        self.effects.pickup(*viewport, normalise_color(SHIPS[kind]["accent"]))

    # ---------------------------------------------------------------- input
    def handle_event(self, event, mouse=None):
        mouse = mouse or self.app.mouse
        if event.type == pygame.QUIT:
            self.app.quit()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.app.toggle_fullscreen()
            return
        if (event.type == pygame.KEYDOWN and event.key == pygame.K_h
                and self.screen != "hangar"):
            self._click_sound()
            self._set_screen("hangar")
            return

        if self.screen == "mode":
            self._handle_mode_event(event, mouse)
            return
        if self.screen == "hangar":
            self._handle_hangar_event(event, mouse)
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

    def _handle_hangar_event(self, event, mouse):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._set_screen("main")
            elif event.key in (pygame.K_LEFT, pygame.K_a):
                self.hangar_focus = (self.hangar_focus - 1) % len(SHIP_ORDER)
                self._hover_sound()
            elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_TAB):
                self.hangar_focus = (self.hangar_focus + 1) % len(SHIP_ORDER)
                self._hover_sound()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._select_ship(SHIP_ORDER[self.hangar_focus])
            return
        if event.type == pygame.MOUSEMOTION:
            for index, rect in enumerate(self.hangar_cards):
                if rect.collidepoint(mouse) and self.hangar_focus != index:
                    self.hangar_focus = index
                    self._hover_sound()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for index, rect in enumerate(self.hangar_cards):
                if rect.collidepoint(mouse):
                    if index == self.hangar_focus:
                        self._select_ship(SHIP_ORDER[index])
                    else:
                        self.hangar_focus = index
                        self._hover_sound()
                    return
            if self.hangar_select_rect.collidepoint(mouse):
                self._select_ship(SHIP_ORDER[self.hangar_focus])
            elif self.hangar_back_rect.collidepoint(mouse):
                self._set_screen("main")

    def _handle_action(self, action):
        if action == "quit":
            self._click_sound()
            self.app.quit()
        elif action == "new_game":
            self._set_screen("mode")
        elif action == "hangar":
            self._set_screen("hangar")
        elif action in ("leaderboard", "settings", "controls"):
            self._set_screen(action)
        elif action == "back":
            self._set_screen("main")
        elif action == "hangar_select":
            self._select_ship(SHIP_ORDER[self.hangar_focus])
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
        self.backdrop.update(dt, 8.0)
        self.effects.update(dt)
        for decor in self.decor:
            decor.update(dt)
        self.hero_timer += dt
        if self.hero_timer >= 0.1:
            self.hero_timer = 0.0
            self.hero_frame += 1
        self.engine_timer += dt
        if self.screen == "main":
            center = self._hero_center()
            while self.engine_timer >= 0.045:
                self.engine_timer -= 0.045
                self.effects.engine(
                    center[0] + random.uniform(-7, 7),
                    center[1] + 104 + random.uniform(-3, 3),
                    SHIPS[self.settings.ship]["accent"], 0.55,
                )

    def _hero_center(self):
        return (VW - 330, 352 + int(math.sin(self.time * 1.2) * 8))

    def _hero_frames(self):
        return self.resources.ship_large_for(self.settings.ship)

    # ----------------------------------------------------------------- draw
    def draw(self, canvas):
        palette = self.palette
        self.backdrop.draw(canvas)
        canvas.blit(self.resources.menu_grid, (0, 0))
        for decor in self.decor:
            decor.draw(canvas)
        if self.screen == "main":
            self._draw_hero(canvas)
        self.effects.draw(canvas)
        canvas.blit(self.resources.vignette, (0, 0))
        if self.screen not in ("main", "hangar"):
            canvas.blit(self.dim, (0, 0))

        if self.screen == "main":
            self._draw_main(canvas)
        elif self.screen == "mode":
            self._draw_mode(canvas)
        elif self.screen == "hangar":
            self._draw_hangar(canvas)
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
        center = self._hero_center()
        ships = self._hero_frames()
        if not ships:
            return
        accent = SHIPS[self.settings.ship]["accent"]
        pygame.draw.circle(canvas, (30, 60, 92), center, 150, 1)
        pygame.draw.circle(canvas, (52, 110, 154), center, 130, 1)
        for index in range(3):
            angle = self.time * 0.5 + index * math.tau / 3
            x = center[0] + math.cos(angle) * 150
            y = center[1] + math.sin(angle) * 150
            pygame.draw.circle(canvas, accent, (int(x), int(y)), 3)

        glow = self.resources.glow(152, accent, 58)
        canvas.blit(glow, glow.get_rect(center=center))
        frame = ships[self.hero_frame % len(ships)]
        rect = frame.get_rect(center=center)
        canvas.blit(frame, rect)

        flame_y = center[1] + 106
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

        # Selected ship + mode summary card.
        best = self.app.leaderboard.best(self.settings.mode)
        card = pygame.Rect(VW - 500, VH - 154, 450, 88)
        draw_panel(canvas, card, (*NORMAL_PALETTE["panel"], 195),
                   NORMAL_PALETTE["border"], 12, 1)
        ship = SHIPS[self.settings.ship]
        weapon = WEAPONS[ship["weapon"]]
        mode_key = "meme_badge" if self.settings.mode == "meme" else "normal_badge"
        draw_text(canvas, self.resources, tr(self.language, mode_key), 10,
                  NORMAL_PALETTE["accent2"] if self.settings.mode == "meme"
                  else NORMAL_PALETTE["muted"], (card.x + 18, card.y + 10))
        draw_text(canvas, self.resources, tr(self.language, ship["name"]), 20,
                  accent, (card.x + 18, card.y + 24))
        draw_text(canvas, self.resources,
                  f"{tr(self.language, ship['role'])} · "
                  f"{tr(self.language, weapon['name'])}",
                  11, NORMAL_PALETTE["muted"], (card.x + 18, card.y + 52))
        draw_text(canvas, self.resources, tr(self.language, "best"), 10,
                  NORMAL_PALETTE["muted"], (card.right - 18, card.y + 10),
                  anchor="topright")
        draw_text(canvas, self.resources, format_score(best), 22,
                  NORMAL_PALETTE["accent"], (card.right - 18, card.y + 24),
                  anchor="topright")
        draw_text(canvas, self.resources, tr(self.language, "add_music_hint"), 10,
                  NORMAL_PALETTE["muted"], (card.right - 18, card.y + 56),
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
                  palette["text"], (VW // 2, 74), anchor="center",
                  shadow=(2, 6, 16))
        draw_text(canvas, self.resources, tr(self.language, "choose_mode_hint"), 15,
                  palette["muted"], (VW // 2, 120), anchor="center")

        card_w = 400
        card_h = 316
        top = 178
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
            icon_y = rect.y + 84
            if mode == "normal":
                ships = self.resources.ship_large_for(self.settings.ship)
                frame = ships[0] if ships else None
                if frame is not None:
                    image = pygame.transform.smoothscale(frame, (116, 116))
                    canvas.blit(image, image.get_rect(center=(rect.centerx, icon_y)))
            else:
                planet = self.resources.menu_planet("meme")
                image = pygame.transform.smoothscale(planet, (132, 132))
                canvas.blit(image, image.get_rect(center=(rect.centerx, icon_y)))
            title_key = "mode_normal" if mode == "normal" else "mode_meme"
            draw_text(canvas, self.resources, tr(self.language, title_key), 26,
                      mode_palette["accent"], (rect.centerx, rect.y + 156),
                      anchor="center")
            draw_text(canvas, self.resources,
                      tr(self.language, "normal_badge" if mode == "normal" else "meme_badge"),
                      11, palette["text"], (rect.centerx, rect.y + 182), anchor="center",
                      alpha=190)
            desc_key = "mode_normal_desc" if mode == "normal" else "mode_meme_desc"
            lines = self.resources.wrap_text(
                tr(self.language, desc_key), 14, rect.width - 60
            )
            for line_index, line in enumerate(lines[:4]):
                draw_text(canvas, self.resources, line, 14, palette["text"],
                          (rect.centerx, rect.y + 206 + line_index * 20),
                          anchor="center")
            ship_name = tr(self.language, SHIPS[self.settings.ship]["name"])
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'hangar')}: {ship_name}", 12,
                      palette["muted"], (rect.centerx, rect.bottom - 20),
                      anchor="center")

        self.back_rect = pygame.Rect(VW // 2 - 130, VH - 90, 260, 44)
        hovered = self.back_rect.collidepoint(self.app.mouse)
        draw_panel(canvas, self.back_rect,
                   (18, 30, 58, 210) if not hovered else (30, 50, 80, 230),
                   palette["accent"] if hovered else palette["border"], 10,
                   2 if hovered else 1)
        draw_text(canvas, self.resources, tr(self.language, "back"), 20,
                  palette["accent"] if hovered else palette["text"],
                  self.back_rect.center, anchor="center")
        draw_text(canvas, self.resources, "← →  ·  ENTER  ·  ESC", 12,
                  palette["muted"], (VW // 2, VH - 34), anchor="center")

    def _draw_hangar(self, canvas):
        palette = self.palette
        draw_text(canvas, self.resources, tr(self.language, "hangar_title"), 40,
                  palette["text"], (VW // 2, 52), anchor="center", shadow=(2, 5, 14))
        draw_text(canvas, self.resources, tr(self.language, "hangar_hint"), 14,
                  palette["muted"], (VW // 2, 92), anchor="center")

        card_w = 270
        card_h = 330
        gap = 20
        total = card_w * len(SHIP_ORDER) + gap * (len(SHIP_ORDER) - 1)
        left = VW // 2 - total // 2
        top = 118
        self.hangar_cards = [
            pygame.Rect(left + index * (card_w + gap), top, card_w, card_h)
            for index in range(len(SHIP_ORDER))
        ]

        stats_keys = ("ship_stat_speed", "ship_stat_armor", "ship_stat_fire",
                      "ship_stat_utility")
        for index, rect in enumerate(self.hangar_cards):
            kind = SHIP_ORDER[index]
            ship = SHIPS[kind]
            focused = index == self.hangar_focus
            selected = kind == self.settings.ship
            accent = normalise_color(ship["accent"])
            border = accent if focused else palette["border"]
            fill = (18, 30, 58, 236) if focused else (10, 18, 38, 214)
            draw_panel(canvas, rect.move(0, -6 if focused else 0), fill, border,
                       radius=14, width=3 if focused else 1)
            if focused:
                glow = self.resources.glow(
                    110, accent, 40
                )
                canvas.blit(glow, glow.get_rect(center=(rect.centerx, rect.y + 12)))

            frames = self.hangar_frames[kind]
            if frames:
                image = frames[self.hero_frame % len(frames)]
                canvas.blit(image, image.get_rect(center=(rect.centerx, rect.y + 92)))

            draw_text(canvas, self.resources, tr(self.language, ship["name"]), 20,
                      accent, (rect.centerx, rect.y + 174), anchor="center")
            draw_text(canvas, self.resources, tr(self.language, ship["role"]), 11,
                      palette["muted"], (rect.centerx, rect.y + 196), anchor="center")
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'weapon')}: "
                      f"{tr(self.language, WEAPONS[ship['weapon']]['name'])}",
                      11, palette["text"], (rect.centerx, rect.y + 214),
                      anchor="center", alpha=200)
            row_y = rect.y + 228
            for stat_index, value in enumerate(ship["stats"]):
                draw_text(canvas, self.resources,
                          tr(self.language, stats_keys[stat_index]), 10,
                          palette["muted"], (rect.x + 18, row_y))
                draw_bar(canvas, (rect.x + 96, row_y + 1, rect.width - 114, 8),
                         value / 5.0, accent, (26, 36, 58), None, 2)
                row_y += 20
            if selected:
                badge = pygame.Rect(rect.centerx - 52, rect.bottom - 26, 104, 20)
                draw_panel(canvas, badge, (*accent, 200), None, 8, 1)
                draw_text(canvas, self.resources, tr(self.language, "hangar_selected"),
                          11, (10, 16, 28), badge.center, anchor="center")

        detail = pygame.Rect(VW // 2 - 570, 470, 1140, 116)
        ship = SHIPS[SHIP_ORDER[self.hangar_focus]]
        accent = normalise_color(ship["accent"])
        draw_panel(canvas, detail, (*palette["panel"], 218), accent, 12, 1)
        draw_text(canvas, self.resources, tr(self.language, ship["name"]), 22,
                  accent, (detail.x + 22, detail.y + 14))
        passive_key = "passive_" + str(ship["passive"])
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'hangar')} · {tr(self.language, passive_key)}",
                  11, palette["muted"], (detail.right - 22, detail.y + 18),
                  anchor="topright")
        lines = self.resources.wrap_text(
            tr(self.language, ship["desc"]), 14, detail.width - 44
        )
        for index, line in enumerate(lines[:2]):
            draw_text(canvas, self.resources, line, 14, palette["text"],
                      (detail.x + 22, detail.y + 48 + index * 22), alpha=220)
        weapon = WEAPONS[ship["weapon"]]
        draw_text(canvas, self.resources,
                  f"{tr(self.language, weapon['name'])} — "
                  f"{tr(self.language, weapon['desc'])}", 13,
                  accent, (detail.x + 22, detail.y + 88), alpha=225)

        self.hangar_select_rect = pygame.Rect(VW // 2 - 190, VH - 88, 180, 46)
        self.hangar_back_rect = pygame.Rect(VW // 2 + 10, VH - 88, 180, 46)
        mouse = self.app.mouse
        for rect, label, action in (
            (self.hangar_select_rect,
             tr(self.language, "hangar_select"), "hangar_select"),
            (self.hangar_back_rect, tr(self.language, "back"), "back"),
        ):
            hovered = rect.collidepoint(mouse)
            draw_panel(canvas, rect,
                       (24, 44, 74, 235) if hovered else (18, 30, 58, 210),
                       palette["accent"] if hovered else palette["border"], 10,
                       2 if hovered else 1)
            draw_text(canvas, self.resources, label, 18,
                      palette["accent"] if hovered else palette["text"],
                      rect.center, anchor="center")
        draw_text(canvas, self.resources, "← →  ·  ENTER  ·  ESC", 12,
                  palette["muted"], (VW // 2, VH - 24), anchor="center")

    def _draw_settings(self, canvas):
        palette = self.palette
        draw_text(canvas, self.resources, tr(self.language, "settings_title"), 38,
                  palette["text"], (VW // 2, 30), anchor="center", shadow=(2, 5, 14))
        panel = pygame.Rect(VW // 2 - 390, 78, 780, 572)
        draw_panel(canvas, panel, (*palette["panel"], 226), palette["border"], 16, 2)
        self.widgets.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources, tr(self.language, "settings_saved"), 11,
                  palette["muted"], (VW // 2, panel.bottom + 12), anchor="center")
        if not self.audio.enabled:
            draw_text(canvas, self.resources, tr(self.language, "audio_unavailable"), 12,
                      palette["warning"], (VW // 2, panel.bottom + 30), anchor="center")

    def _draw_leaderboard(self, canvas):
        palette = self.palette
        draw_text(canvas, self.resources, tr(self.language, "leaderboard_title"), 40,
                  palette["text"], (VW // 2, 52), anchor="center", shadow=(2, 5, 14))
        draw_text(canvas, self.resources, tr(self.language, "focus_hint"), 11,
                  palette["muted"], (VW // 2, 100), anchor="center")

        panel_w = 540
        panel_h = 450
        top = 130
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
                  palette["text"], (VW // 2, 52), anchor="center", shadow=(2, 5, 14))
        panel = pygame.Rect(VW // 2 - 390, 110, 780, 450)
        draw_panel(canvas, panel, (*palette["panel"], 226), palette["border"], 16, 2)
        rows = [
            ("ctrl_move", "ctrl_move_keys"),
            ("ctrl_fire", "ctrl_fire_keys"),
            ("ctrl_pause", "ctrl_pause_keys"),
            ("ctrl_fullscreen", "ctrl_fullscreen_keys"),
            ("ctrl_menu", "ctrl_menu_keys"),
            ("ctrl_hangar", "ctrl_hangar_keys"),
        ]
        y = panel.y + 38
        for label_key, keys_key in rows:
            draw_text(canvas, self.resources, tr(self.language, label_key), 13,
                      palette["muted"], (panel.x + 42, y + 8))
            key_text = tr(self.language, keys_key)
            key_rect = pygame.Rect(panel.x + 220, y, panel.width - 270, 38)
            draw_panel(canvas, key_rect, (18, 28, 50, 210), palette["border"], 8, 1)
            draw_text(canvas, self.resources, key_text, 17, palette["accent"],
                      (key_rect.x + 16, key_rect.centery), anchor="midleft")
            y += 52
        draw_text(canvas, self.resources, tr(self.language, "ctrl_tip"), 13,
                  palette["text"], (panel.centerx, panel.bottom - 58), anchor="center")
        self.widgets.draw(canvas, self.resources, palette)


def normalise_color(color):
    """Clamp an RGB tuple so generated palettes always render."""
    return tuple(max(0, min(255, int(channel))) for channel in color[:3])
