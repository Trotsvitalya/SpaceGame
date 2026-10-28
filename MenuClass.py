"""Menu scenes: title, mode select, hangar, settings, leaderboard and help.

The visual layer comes from :class:`SpaceBackdrop`, the same cached parallax
system the gameplay uses, so the menu and the run share one look.  All ship
data is read from :mod:`GameData`; nothing here hard-codes archetype numbers.
"""

from __future__ import annotations

import math
import random

import pygame

from Balance import DIFFICULTY_ORDER
from CampaignData import (MISSION_IDS, first_mission_id, mission_by_id,
                          mission_name, mission_objective, mission_zone_name,
                          next_mission_id)
from CampaignProgress import CampaignProgress
from EffectsClass import Effects
from GameData import SHIPS, SHIP_ORDER, WEAPONS, ZONES
from Localization import LANGUAGE_NAMES, tr
from NetCode import ClientSession, HostSession, local_ip
from ResourcesClass import MEME_PALETTE, NORMAL_PALETTE, palette_for
from SpaceBackdrop import SpaceBackdrop
from SettingsClass import SCREEN_RESOLUTIONS
from UIClass import (Button, Choice, Slider, TextInput, Toggle, WidgetGroup,
                     draw_bar, draw_panel, draw_text)
from utils import VH, VW, clamp, format_score

SCREENS = ("main", "mode", "hangar", "settings", "leaderboard", "controls",
           "campaign", "campaign_brief", "multiplayer", "mp_host", "mp_join",
           "mp_lobby")


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
        self.campaign_progress = getattr(app, "campaign_progress", None)
        if self.campaign_progress is None:
            self.campaign_progress = CampaignProgress.load()
        self.campaign_focus = 0
        self.campaign_rows = []
        self.campaign_back_rect = pygame.Rect(0, 0, 0, 0)
        self.campaign_mission_id = None
        # Multiplayer lobby state.  The menu owns the session until it is
        # handed to a game scene; on_exit closes it only if that never happened.
        self.mp_role = None
        self.mp_session = None
        self.mp_error = ""
        self.mp_notice = ""
        self.mp_connected = False
        self.mp_peer_name = ""
        self.mp_peer_ship = "fighter"
        self.mp_host_name = ""
        self.mp_handed_off = False
        self.mp_start_info = {}
        self.mp_form_name = self.settings.player_name
        self.mp_form_address = self.settings.last_host
        self.mp_form_port = str(self.settings.last_port)
        self.mp_local_ip = "127.0.0.1"
        self.mp_host_address = ""
        self.mp_port_display = self.settings.last_port
        self.mp_run_type = "endless"
        self.mp_mission_ids = []
        self.mp_mission_id = None
        self._build_screen(self.screen)

    # ------------------------------------------------------------ lifecycle
    def on_enter(self):
        self.audio.play_music("menu", "normal")

    def on_exit(self):
        self.audio.stop_music()
        if not self.mp_handed_off:
            self._close_mp_session()

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
            y = 286
            width = 342
            height = 46
            gap = 49
            specs = [
                (tr(self.language, "new_game"), "new_game"),
                (tr(self.language, "campaign"), "campaign"),
                (tr(self.language, "multiplayer"), "multiplayer"),
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
        elif name == "campaign":
            self._build_campaign()
        elif name == "campaign_brief":
            self._build_campaign_brief()
        elif name == "multiplayer":
            self._build_multiplayer()
        elif name in ("mp_host", "mp_join"):
            self._build_mp_connect(name)
        elif name == "mp_lobby":
            self._build_mp_lobby()

    def _build_single_back(self):
        self.widgets = WidgetGroup([
            Button((VW // 2 - 130, VH - 96, 260, 46),
                   lambda: tr(self.language, "back"), "back", size=20)
        ], on_hover=self._hover_sound)

    def _build_settings(self):
        cx = VW // 2
        left = cx - 330
        width = 660
        top = 84

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
            Slider((left, top + 38, width, 40),
                   lambda: tr(self.language, "sfx"),
                   lambda: self.settings.sfx_volume,
                   lambda value: setattr(self.settings, "sfx_volume", value),
                   save_and_apply),
            Toggle((left, top + 80, width, 40),
                   lambda: tr(self.language, "mute"),
                   lambda: self.settings.muted,
                   lambda value: setattr(self.settings, "muted", value),
                   save_and_apply),
            Toggle((left, top + 122, width, 40),
                   lambda: tr(self.language, "fullscreen"),
                   lambda: self.settings.fullscreen,
                   lambda value: setattr(self.settings, "fullscreen", value),
                   apply_fullscreen),
            Choice((left, top + 164, width, 40),
                   lambda: tr(self.language, "screen_resolution"),
                   [(size, size.replace("x", " × "))
                    for size in SCREEN_RESOLUTIONS],
                   lambda: SCREEN_RESOLUTIONS.index(self.settings.screen_resolution),
                   self._set_resolution_index,
                   apply_fullscreen),
            Toggle((left, top + 206, width, 40),
                   lambda: tr(self.language, "screen_shake"),
                   lambda: self.settings.screen_shake,
                   lambda value: setattr(self.settings, "screen_shake", value),
                   save_only),
            Toggle((left, top + 248, width, 40),
                   lambda: tr(self.language, "show_fps"),
                   lambda: self.settings.show_fps,
                   lambda value: setattr(self.settings, "show_fps", value),
                   save_only),
            Choice((left, top + 290, width, 40),
                   lambda: tr(self.language, "effects_quality"),
                   [(0, quality_labels[0]), (1, quality_labels[1]),
                    (2, quality_labels[2])],
                   lambda: int(getattr(self.settings, "effects_quality", 2)),
                   self._set_quality_index,
                   save_only),
            Toggle((left, top + 332, width, 40),
                   lambda: tr(self.language, "reduced_flash"),
                   lambda: self.settings.reduced_flash,
                   lambda value: setattr(self.settings, "reduced_flash", value),
                   apply_effects),
            Toggle((left, top + 374, width, 40),
                   lambda: tr(self.language, "auto_pause"),
                   lambda: self.settings.auto_pause,
                   lambda value: setattr(self.settings, "auto_pause", value),
                   save_only),
            Choice((left, top + 416, width, 40),
                   lambda: tr(self.language, "language"),
                   [("uk", LANGUAGE_NAMES["uk"]), ("en", LANGUAGE_NAMES["en"])],
                   lambda: 0 if self.settings.language == "uk" else 1,
                   self._set_language_index,
                   apply_language),
            Choice((left, top + 458, width, 40),
                   lambda: tr(self.language, "difficulty"),
                   [(key, tr(self.language, "difficulty_" + key))
                    for key in DIFFICULTY_ORDER],
                   lambda: self._difficulty_index(),
                   self._set_difficulty_index,
                   save_only),
            Button((cx - 130, top + 504, 260, 44),
                   lambda: tr(self.language, "back"), "back", size=20),
        ]
        self.widgets = WidgetGroup(widgets, on_hover=self._hover_sound)

    def _set_difficulty_index(self, index):
        self.settings.difficulty = DIFFICULTY_ORDER[
            max(0, min(len(DIFFICULTY_ORDER) - 1, int(index)))
        ]
        self.settings.save()

    def _difficulty_index(self):
        current = getattr(self.settings, "difficulty", "normal")
        return DIFFICULTY_ORDER.index(current) if current in DIFFICULTY_ORDER else 1

    # ------------------------------------------------------------ campaign
    @staticmethod
    def _campaign_panel():
        return pygame.Rect(VW // 2 - 560, 86, 1120, 560)

    @staticmethod
    def _campaign_brief_panel():
        return pygame.Rect(VW // 2 - 450, 66, 900, 600)

    def _build_campaign(self):
        self.widgets = None
        self.campaign_rows = []
        target = self.campaign_progress.next_open_mission()
        self.campaign_focus = (MISSION_IDS.index(target)
                               if target in MISSION_IDS else 0)

    def _open_campaign_brief(self, mission_id):
        if mission_id not in MISSION_IDS:
            return
        self.campaign_mission_id = mission_id
        self._set_screen("campaign_brief")

    def _build_campaign_brief(self):
        mission = mission_by_id(self.campaign_mission_id)
        if mission is None:
            unlocked = [mid for mid in MISSION_IDS
                        if self.campaign_progress.is_unlocked(mid)]
            mission = mission_by_id(
                unlocked[0] if unlocked
                else first_mission_id(self.campaign_progress)
            )
        self.campaign_mission_id = mission["id"]
        panel = self._campaign_brief_panel()
        left = panel.x + 60
        width = panel.width - 120
        current = self.campaign_progress.difficulty
        if current not in DIFFICULTY_ORDER:
            current = "normal"
        widgets = [
            Choice((left, panel.y + 424, width, 40),
                   lambda: tr(self.language, "campaign_difficulty_label"),
                   [(key, tr(self.language, "difficulty_" + key))
                    for key in DIFFICULTY_ORDER],
                   lambda: DIFFICULTY_ORDER.index(
                       self.campaign_progress.difficulty
                       if self.campaign_progress.difficulty in DIFFICULTY_ORDER
                       else "normal"),
                   self._set_campaign_difficulty_index),
            Button((left, panel.y + 478, 300, 48),
                   lambda: tr(self.language,
                              "campaign_replay"
                              if self.campaign_progress.is_completed(mission["id"])
                              else "campaign_start"),
                   "campaign_start", size=19),
            Button((left + width - 260, panel.y + 478, 260, 44),
                   lambda: tr(self.language, "campaign_back"),
                   "campaign_back", size=18),
        ]
        self.widgets = WidgetGroup(widgets, on_hover=self._hover_sound)

    def _set_campaign_difficulty_index(self, index):
        key = DIFFICULTY_ORDER[max(0, min(len(DIFFICULTY_ORDER) - 1,
                                          int(index)))]
        self.campaign_progress.difficulty = key
        self.campaign_progress.save()
        self.settings.difficulty = key
        self.settings.save()
        self.audio.play("ui_click", 0.4)

    def _start_campaign(self):
        mission = mission_by_id(self.campaign_mission_id)
        if mission is None:
            return
        if not self.campaign_progress.is_unlocked(mission["id"]):
            self.audio.play("low_health", 0.5)
            return
        self._click_sound()
        difficulty = self.campaign_progress.difficulty
        if difficulty not in DIFFICULTY_ORDER:
            difficulty = getattr(self.settings, "difficulty", "normal")
        self.app.start_campaign(mission["id"], self.settings.mode, difficulty)

    # ---------------------------------------------------------- multiplayer
    @staticmethod
    def _mp_panel():
        return pygame.Rect(VW // 2 - 430, 122, 860, 536)

    def _build_multiplayer(self):
        cx = VW // 2
        self.widgets = WidgetGroup([
            Button((cx - 270, 246, 540, 58), tr(self.language, "mp_host"),
                   "mp_host", size=22),
            Button((cx - 270, 366, 540, 58), tr(self.language, "mp_join"),
                   "mp_join", size=22),
            Button((cx - 130, VH - 92, 260, 44), tr(self.language, "back"),
                   "back", size=20),
        ], on_hover=self._hover_sound)

    def _build_mp_connect(self, name):
        panel = self._mp_panel()
        left = panel.x + 56
        width = panel.width - 112
        top = panel.y + 128
        widgets = [
            TextInput((left, top, width, 42), tr(self.language, "mp_name"),
                      lambda: self.mp_form_name,
                      lambda value: setattr(self, "mp_form_name", value),
                      max_length=24, placeholder="Pilot"),
        ]
        if name == "mp_host":
            self.mp_local_ip = local_ip()
            unlocked = [mission_id for mission_id in MISSION_IDS
                        if self.campaign_progress.is_unlocked(mission_id)]
            if not unlocked:
                unlocked = [MISSION_IDS[0]]
            self.mp_mission_ids = unlocked
            if self.mp_mission_id not in unlocked:
                self.mp_mission_id = unlocked[0]
            half = (width - 20) // 2
            widgets += [
                TextInput((left, top + 50, width, 42),
                          tr(self.language, "mp_port"),
                          lambda: self.mp_form_port,
                          lambda value: setattr(self, "mp_form_port", value),
                          max_length=5, numeric=True, placeholder="47521"),
                Choice((left, top + 100, half, 42),
                       lambda: tr(self.language, "mp_mode"),
                       [("normal", tr(self.language, "mode_normal")),
                        ("meme", tr(self.language, "mode_meme"))],
                       lambda: 0 if self.settings.mode == "normal" else 1,
                       self._set_mp_mode),
                Choice((left + half + 20, top + 100, half, 42),
                       lambda: tr(self.language, "mp_difficulty"),
                       [(key, tr(self.language, "difficulty_" + key))
                        for key in DIFFICULTY_ORDER],
                       lambda: self._difficulty_index(),
                       self._set_difficulty_index),
                Choice((left, top + 150, width, 42),
                       lambda: tr(self.language, "mp_run_type"),
                       [("endless", tr(self.language, "mp_endless")),
                        ("campaign", tr(self.language, "mp_campaign"))],
                       lambda: 0 if self.mp_run_type == "endless" else 1,
                       self._set_mp_run_type),
            ]
            if self.mp_run_type == "campaign":
                widgets.append(Choice(
                    (left, top + 200, width, 42),
                    lambda: tr(self.language, "mp_mission"),
                    [(index, mission_name(self.language,
                                          mission_by_id(mission_id)))
                     for index, mission_id in enumerate(self.mp_mission_ids)],
                    lambda: (self.mp_mission_ids.index(self.mp_mission_id)
                             if self.mp_mission_id in self.mp_mission_ids else 0),
                    self._set_mp_mission_index,
                ))
            start_action = "mp_start_host"
            start_label = tr(self.language, "mp_host_button")
        else:
            widgets += [
                TextInput((left, top + 50, width, 42),
                          tr(self.language, "mp_address"),
                          lambda: self.mp_form_address,
                          lambda value: setattr(self, "mp_form_address", value),
                          max_length=64, address=True,
                          placeholder="192.168.1.20"),
                TextInput((left, top + 100, width, 42),
                          tr(self.language, "mp_port"),
                          lambda: self.mp_form_port,
                          lambda value: setattr(self, "mp_form_port", value),
                          max_length=5, numeric=True, placeholder="47521"),
            ]
            start_action = "mp_connect"
            start_label = tr(self.language, "mp_connect")
        widgets += [
            Button((left, panel.y + 386, 360, 50), start_label,
                   start_action, size=19),
            Button((panel.right - 56 - 240, panel.y + 390, 240, 42),
                   tr(self.language, "mp_cancel"), "mp_cancel", size=17),
        ]
        self.widgets = WidgetGroup(widgets, on_hover=self._hover_sound)

    def _set_mp_mode(self, index):
        self.settings.mode = "normal" if index == 0 else "meme"
        self.settings.save()

    def _set_mp_run_type(self, index):
        self.mp_run_type = "campaign" if int(index) else "endless"
        self.audio.play("ui_click", 0.4)
        if self.screen == "mp_host":
            self._build_screen("mp_host")

    def _set_mp_mission_index(self, index):
        if not self.mp_mission_ids:
            return
        index = max(0, min(len(self.mp_mission_ids) - 1, int(index)))
        self.mp_mission_id = self.mp_mission_ids[index]
        self.audio.play("ui_click", 0.4)

    def _build_mp_lobby(self):
        panel = self._mp_panel()
        cx = VW // 2
        widgets = []
        if self.mp_error:
            widgets.append(Button((cx - 190, panel.bottom - 126, 380, 50),
                                  tr(self.language, "mp_retry"), "mp_retry",
                                  size=19))
        elif self.mp_role == "host":
            widgets.append(Button((cx - 200, panel.bottom - 132, 400, 54),
                                  tr(self.language, "mp_start_run"),
                                  "mp_start_run", size=21))
        widgets.append(Button((cx - 130, panel.bottom - 64, 260, 40),
                              tr(self.language, "mp_leave"), "mp_leave",
                              size=17))
        self.widgets = WidgetGroup(widgets, on_hover=self._hover_sound)

    def _form_port(self):
        try:
            port = int(str(self.mp_form_port).strip())
        except (TypeError, ValueError):
            return 0
        return port if 1 <= port <= 65535 else 0

    def _begin_host(self):
        self._close_mp_session()
        port = self._form_port()
        name = (self.mp_form_name or "").strip()[:24] or "Pilot"
        if not port:
            self._set_mp_error(tr(self.language, "mp_error",
                                  message="1-65535"))
            return
        self.settings.player_name = name
        self.settings.last_port = port
        self.settings.save()
        session = HostSession(port, name)
        actual = session.start()
        if not actual:
            message = session.error or "cannot listen"
            session.close()
            self._set_mp_error(tr(self.language, "mp_error", message=message))
            return
        self.mp_session = session
        self.mp_role = "host"
        self.mp_connected = False
        self.mp_peer_name = ""
        self.mp_peer_ship = "fighter"
        self.mp_error = ""
        self.mp_notice = ""
        self.mp_local_ip = local_ip()
        self.mp_port_display = actual
        self.audio.play("ui_click", 0.5)
        self._set_screen("mp_lobby")
        self._refresh_mp_lobby()

    def _begin_join(self):
        self._close_mp_session()
        address = (self.mp_form_address or "").strip()
        port = self._form_port()
        name = (self.mp_form_name or "").strip()[:24] or "Pilot"
        if not address:
            self._set_mp_error(tr(self.language, "mp_error",
                                  message="host address is empty"))
            return
        if not port:
            self._set_mp_error(tr(self.language, "mp_error",
                                  message="1-65535"))
            return
        self.settings.player_name = name
        self.settings.last_host = address
        self.settings.last_port = port
        self.settings.save()
        session = ClientSession(address, port, name, ship=self.settings.ship)
        self.mp_session = session
        self.mp_role = "client"
        self.mp_connected = False
        self.mp_host_name = ""
        self.mp_error = ""
        self.mp_notice = ""
        self.mp_host_address = address
        self.mp_port_display = port
        self.audio.play("ui_click", 0.5)
        session.connect()
        self._set_screen("mp_lobby")
        self._refresh_mp_lobby()

    def _set_mp_error(self, message):
        self.mp_error = str(message or tr(self.language, "coop_link_lost"))[:160]
        self.mp_connected = False
        self.audio.play("low_health", 0.6)
        self._refresh_mp_lobby()

    def _refresh_mp_lobby(self):
        if self.screen == "mp_lobby":
            self._build_mp_lobby()

    def _start_coop_run(self):
        if (self.mp_role != "host" or self.mp_session is None
                or not self.mp_session.connected):
            self._set_mp_error(tr(self.language, "mp_waiting"))
            return
        mission_id = None
        if self.mp_run_type == "campaign":
            mission_id = self.mp_mission_id
            if (not mission_id
                    or not self.campaign_progress.is_unlocked(mission_id)):
                self._set_mp_error(tr(
                    self.language, "mp_error",
                    message=tr(self.language, "campaign_mission_locked"),
                ))
                return
        self._click_sound()
        client_name = self.mp_session.client_name or self.mp_peer_name or "Pilot"
        client_ship = self.mp_session.client_ship or self.mp_peer_ship or "fighter"
        self.mp_handed_off = True
        mission = self.app.start_coop_host(
            self.mp_session, self.settings.mode, self.settings.difficulty,
            mission_id=mission_id, client_name=client_name,
            client_ship=client_ship,
        )
        if mission is None and mission_id:
            self.mp_handed_off = False
            self._set_mp_error(tr(
                self.language, "mp_error",
                message=tr(self.language, "campaign_mission_locked"),
            ))

    def _retry_mp(self):
        role = self.mp_role
        self._close_mp_session()
        self.mp_error = ""
        self.mp_notice = ""
        self._set_screen("mp_join" if role == "client" else "mp_host")

    def _leave_mp(self):
        self._close_mp_session()
        self.mp_error = ""
        self.mp_notice = ""
        self._set_screen("multiplayer")

    def _close_mp_session(self):
        session = self.mp_session
        role = self.mp_role
        self.mp_session = None
        self.mp_connected = False
        if session is None:
            return
        try:
            if session.connected and hasattr(session, "send_leave"):
                session.send_leave("host left" if role == "host"
                                   else "client returned to menu")
            else:
                session.close()
        except OSError:
            pass

    def _update_mp_lobby(self):
        session = self.mp_session
        if session is None or self.mp_handed_off:
            return
        if session.connected:
            session.heartbeat()
        for message in session.poll():
            kind = message.get("t")
            if kind == "peer_joined":
                self.mp_connected = True
                self.mp_peer_name = str(message.get("name") or "Pilot")[:24]
                self.mp_peer_ship = message.get("ship", "fighter")
                self.mp_notice = tr(self.language, "mp_connected")
                self.audio.play("powerup", 0.6)
                self._refresh_mp_lobby()
            elif kind == "welcome":
                self.mp_connected = True
                self.mp_host_name = str(message.get("host_name") or "Host")[:24]
                self.mp_notice = tr(self.language, "mp_connected")
                self.audio.play("powerup", 0.6)
                self._refresh_mp_lobby()
            elif kind == "start":
                if self.mp_role == "client":
                    self.mp_start_info = dict(message)
                    self.mp_handed_off = True
                    self.app.start_coop_client(self.mp_session, message)
                    return
            elif kind == "error":
                self._set_mp_error(tr(
                    self.language, "mp_error",
                    message=message.get("message") or message.get("code")
                    or session.error or "connection error",
                ))
            elif kind in ("peer_left", "leave"):
                reason = (message.get("reason") or session.error
                          or tr(self.language, "coop_link_lost"))
                self._set_mp_error(tr(self.language, "mp_error",
                                      message=reason))
        if session.state == "error" and not self.mp_error:
            self._set_mp_error(tr(self.language, "mp_error",
                                  message=session.error or "connection error"))

    def _set_language_index(self, index):
        self.settings.language = "uk" if index == 0 else "en"
        self.language = self.settings.language

    def _set_quality_index(self, index):
        self.settings.effects_quality = max(0, min(2, int(index)))
        self.backdrop.set_quality(self.settings.effects_quality)
        self.effects.set_quality(self.settings.effects_quality)

    def _set_resolution_index(self, index):
        index = max(0, min(len(SCREEN_RESOLUTIONS) - 1, int(index)))
        self.settings.screen_resolution = SCREEN_RESOLUTIONS[index]
        self.app._windowed_size = tuple(
            int(part) for part in self.settings.screen_resolution.split("x")
        )

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

        if self.screen == "campaign":
            self._handle_campaign_event(event, mouse)
            return
        if self.screen == "campaign_brief":
            self._handle_campaign_brief_event(event, mouse)
            return
        if self.screen == "multiplayer" or self.screen.startswith("mp_"):
            self._handle_mp_event(event, mouse)
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

    def _handle_campaign_event(self, event, mouse):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._set_screen("main")
            elif event.key in (pygame.K_UP, pygame.K_w):
                self.campaign_focus = (self.campaign_focus - 1) % len(MISSION_IDS)
                self._hover_sound()
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.campaign_focus = (self.campaign_focus + 1) % len(MISSION_IDS)
                self._hover_sound()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._open_campaign_brief(MISSION_IDS[self.campaign_focus])
            return
        if event.type == pygame.MOUSEMOTION:
            for index, rect in enumerate(self.campaign_rows):
                if rect.collidepoint(mouse) and self.campaign_focus != index:
                    self.campaign_focus = index
                    self._hover_sound()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for index, rect in enumerate(self.campaign_rows):
                if rect.collidepoint(mouse):
                    if index == self.campaign_focus:
                        self._open_campaign_brief(MISSION_IDS[index])
                    else:
                        self.campaign_focus = index
                        self._hover_sound()
                    return
            if self.campaign_back_rect.collidepoint(mouse):
                self._set_screen("main")

    def _handle_campaign_brief_event(self, event, mouse):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._set_screen("campaign")
            return
        if self.widgets is not None:
            action = self.widgets.handle_event(event, mouse)
            if action:
                self._handle_action(action)

    def _handle_mp_event(self, event, mouse):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.screen == "multiplayer":
                self._set_screen("main")
            elif self.screen in ("mp_host", "mp_join"):
                self._set_screen("multiplayer")
            else:
                self._leave_mp()
            return
        if (self.screen == "mp_lobby" and event.type == pygame.KEYDOWN
                and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)):
            if self.mp_error:
                self._retry_mp()
            elif self.mp_role == "host" and self.mp_connected:
                self._start_coop_run()
            return
        if self.widgets is not None:
            action = self.widgets.handle_event(event, mouse)
            if action:
                self._handle_action(action)

    def _handle_action(self, action):
        if action == "quit":
            self._click_sound()
            self.app.quit()
        elif action == "new_game":
            self._set_screen("mode")
        elif action == "campaign":
            self._set_screen("campaign")
        elif action == "multiplayer":
            self._set_screen("multiplayer")
        elif action == "mp_host":
            self.mp_error = ""
            self._set_screen("mp_host")
        elif action == "mp_join":
            self.mp_error = ""
            self._set_screen("mp_join")
        elif action == "mp_start_host":
            self._begin_host()
        elif action == "mp_connect":
            self._begin_join()
        elif action == "mp_start_run":
            self._start_coop_run()
        elif action == "mp_retry":
            self._retry_mp()
        elif action == "mp_leave":
            self._leave_mp()
        elif action == "mp_cancel":
            self._set_screen("multiplayer")
        elif action == "campaign_back":
            self._set_screen("campaign")
        elif action == "campaign_start":
            self._start_campaign()
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
        if self.screen == "mp_lobby" and not self.mp_handed_off:
            self._update_mp_lobby()

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
        elif self.screen == "campaign":
            self._draw_campaign(canvas)
        elif self.screen == "campaign_brief":
            self._draw_campaign_brief(canvas)
        elif self.screen == "multiplayer":
            self._draw_multiplayer(canvas)
        elif self.screen in ("mp_host", "mp_join"):
            self._draw_mp_connect(canvas)
        elif self.screen == "mp_lobby":
            self._draw_mp_lobby(canvas)

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
        panel = pygame.Rect(VW // 2 - 390, 78, 780, 620)
        draw_panel(canvas, panel, (*palette["panel"], 226), palette["border"], 16, 2)
        self.widgets.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources, tr(self.language, "settings_saved"), 11,
                  palette["muted"], (VW // 2, panel.bottom + 8), anchor="center")
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

    def _draw_campaign(self, canvas):
        palette = self.palette
        panel = self._campaign_panel()
        draw_text(canvas, self.resources, tr(self.language, "campaign_title"), 38,
                  palette["text"], (VW // 2, 36), anchor="center", shadow=(2, 5, 14))
        draw_text(canvas, self.resources,
                  tr(self.language, "campaign_progress",
                     done=self.campaign_progress.completed_count(),
                     total=self.campaign_progress.total_count()),
                  14, palette["accent"], (VW // 2, 72), anchor="center")
        draw_panel(canvas, panel, (*palette["panel"], 226), palette["border"], 16, 2)
        draw_text(canvas, self.resources, tr(self.language, "campaign_hint"), 11,
                  palette["muted"], (panel.centerx, panel.y + 16), anchor="center")

        self.campaign_rows = []
        row_x = panel.x + 20
        row_w = panel.width - 40
        start_y = panel.y + 40
        for index, mission_id in enumerate(MISSION_IDS):
            mission = mission_by_id(mission_id)
            rect = pygame.Rect(row_x, start_y + index * 44, row_w, 40)
            self.campaign_rows.append(rect)
            focused = index == self.campaign_focus
            completed = self.campaign_progress.is_completed(mission_id)
            unlocked = self.campaign_progress.is_unlocked(mission_id)
            if completed:
                color = palette["success"]
                status = tr(self.language, "campaign_completed")
            elif unlocked:
                color = palette["accent"]
                status = tr(self.language, "campaign_available")
            else:
                color = palette["muted"]
                status = tr(self.language, "campaign_locked")
            fill = (24, 42, 70, 235) if focused else (14, 24, 44, 200)
            if completed:
                fill = (16, 44, 46, 220) if focused else (12, 32, 36, 190)
            draw_panel(canvas, rect, fill,
                       palette["accent"] if focused else palette["border"], 8,
                       2 if focused else 1)
            draw_text(canvas, self.resources, f"{index + 1:02d}", 12,
                      palette["muted"], (rect.x + 14, rect.centery),
                      anchor="midleft")
            draw_text(canvas, self.resources, mission_name(self.language, mission),
                      17, color if unlocked else palette["muted"],
                      (rect.x + 52, rect.centery), anchor="midleft")
            draw_text(canvas, self.resources,
                      mission_zone_name(self.language, mission), 11,
                      palette["muted"], (rect.x + 336, rect.centery),
                      anchor="midleft")
            draw_text(canvas, self.resources,
                      mission_objective(self.language, mission), 11,
                      palette["text"] if unlocked else palette["muted"],
                      (rect.x + 520, rect.centery), anchor="midleft")
            draw_text(canvas, self.resources, status, 11, color,
                      (rect.right - 16, rect.centery), anchor="midright")

        self.campaign_back_rect = pygame.Rect(panel.centerx - 130,
                                              panel.bottom - 54, 260, 42)
        hovered = self.campaign_back_rect.collidepoint(self.app.mouse)
        draw_panel(canvas, self.campaign_back_rect,
                   (18, 30, 58, 210) if not hovered else (30, 50, 80, 230),
                   palette["accent"] if hovered else palette["border"], 10,
                   2 if hovered else 1)
        draw_text(canvas, self.resources, tr(self.language, "back"), 19,
                  palette["accent"] if hovered else palette["text"],
                  self.campaign_back_rect.center, anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "campaign_select_hint"),
                  11, palette["muted"], (VW // 2, VH - 20), anchor="center")

    def _draw_campaign_brief(self, canvas):
        palette = self.palette
        mission = mission_by_id(self.campaign_mission_id)
        if mission is None:
            return
        mission_id = mission["id"]
        completed = self.campaign_progress.is_completed(mission_id)
        unlocked = self.campaign_progress.is_unlocked(mission_id)
        panel = self._campaign_brief_panel()
        draw_panel(canvas, panel, (*palette["panel"], 234),
                   palette["accent"] if unlocked else palette["border"], 16, 2)
        left = panel.x + 60
        width = panel.width - 120

        draw_text(canvas, self.resources, mission_name(self.language, mission), 30,
                  palette["text"], (left, panel.y + 22), shadow=(2, 5, 14))
        status = ("campaign_completed" if completed else
                  ("campaign_available" if unlocked else "campaign_locked"))
        status_color = (palette["success"] if completed else
                        (palette["accent"] if unlocked else palette["muted"]))
        draw_text(canvas, self.resources, tr(self.language, status), 12,
                  status_color, (panel.right - 60, panel.y + 36), anchor="topright")

        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'campaign_zone')}:  "
                  f"{mission_zone_name(self.language, mission)}", 13,
                  palette["muted"], (left, panel.y + 70))
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'campaign_objective')}:  "
                  f"{mission_objective(self.language, mission)}", 13,
                  palette["accent"], (left, panel.y + 92))
        pygame.draw.line(canvas, palette["border"], (left, panel.y + 118),
                         (panel.right - 60, panel.y + 118), 1)

        brief_lines = self.resources.wrap_text(
            tr(self.language, mission["brief_key"]), 15, width
        )
        for index, line in enumerate(brief_lines[:3]):
            draw_text(canvas, self.resources, line, 15, palette["text"],
                      (left, panel.y + 130 + index * 20), alpha=225)

        draw_text(canvas, self.resources, tr(self.language, "campaign_story"), 11,
                  palette["muted"], (left, panel.y + 194))
        story_y = panel.y + 216
        for line in mission["story"][:2]:
            text = tr(self.language, line)
            for wrapped in self.resources.wrap_text(text, 14, width)[:2]:
                draw_text(canvas, self.resources, wrapped, 14, palette["text"],
                          (left + 14, story_y), alpha=210)
                story_y += 19

        enemies = " · ".join(tr(self.language, "enemy_" + kind)
                             for kind in mission["enemies"])
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'campaign_enemies')}:  {enemies}", 11,
                  palette["muted"], (left, panel.y + 320))
        if not unlocked:
            draw_text(canvas, self.resources, tr(self.language, "campaign_unlock_hint"),
                      13, palette["warning"], (left, panel.y + 342))
            reward_text = None
            reward_color = palette["muted"]
        elif completed:
            reward_text = tr(self.language, "campaign_reward_none")
            reward_color = palette["muted"]
        else:
            reward_text = tr(self.language, "campaign_reward",
                             salvage=int(mission["reward_salvage"]))
            reward_color = palette["warning"]
        if reward_text:
            draw_text(canvas, self.resources, reward_text, 13, reward_color,
                      (left, panel.y + 342))
        best = self.campaign_progress.best_for(mission_id)
        if best:
            best_text = (f"{tr(self.language, 'campaign_best')}:  "
                         f"{format_score(best['score'])}  ·  "
                         f"{best['kills']} {tr(self.language, 'kills')}")
        else:
            best_text = (f"{tr(self.language, 'campaign_best')}:  "
                         f"{tr(self.language, 'campaign_best_none')}")
        draw_text(canvas, self.resources, best_text, 12, palette["muted"],
                  (left, panel.y + 366))
        ship_name = tr(self.language, SHIPS[self.settings.ship]["name"])
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'campaign_ship')}:  {ship_name}     "
                  f"{tr(self.language, 'campaign_bonus')}:  "
                  f"{self.campaign_progress.salvage_bonus}", 12,
                  palette["muted"], (left, panel.y + 390))

        self.widgets.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources, tr(self.language, "campaign_brief_hint"),
                  11, palette["muted"], (VW // 2, panel.bottom - 22),
                  anchor="center")

    def _draw_multiplayer(self, canvas):
        palette = self.palette
        cx = VW // 2
        draw_text(canvas, self.resources, tr(self.language, "mp_title"), 42,
                  palette["text"], (cx, 40), anchor="center", shadow=(2, 6, 16))
        draw_text(canvas, self.resources, tr(self.language, "mp_subtitle"), 15,
                  palette["accent"], (cx, 84), anchor="center")
        panel = pygame.Rect(cx - 520, 122, 1040, 470)
        draw_panel(canvas, panel, (*palette["panel"], 226), palette["border"],
                   16, 2)
        for index, key in enumerate(("mp_host_desc", "mp_join_desc")):
            lines = self.resources.wrap_text(tr(self.language, key), 14, 820)
            y = panel.y + 190 + index * 120
            for line in lines[:2]:
                draw_text(canvas, self.resources, line, 14, palette["text"],
                          (cx, y), anchor="center", alpha=220)
                y += 20
        draw_text(canvas, self.resources, tr(self.language, "mp_lan_hint"), 13,
                  palette["warning"], (cx, panel.bottom - 76), anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "mp_network_note"),
                  11, palette["muted"], (cx, panel.bottom - 48), anchor="center")
        self.widgets.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources, tr(self.language, "focus_hint"), 11,
                  palette["muted"], (cx, VH - 22), anchor="center")

    def _draw_mp_connect(self, canvas):
        palette = self.palette
        cx = VW // 2
        hosting = self.screen == "mp_host"
        title_key = "mp_host" if hosting else "mp_join"
        desc_key = "mp_host_desc" if hosting else "mp_join_desc"
        draw_text(canvas, self.resources, tr(self.language, title_key), 38,
                  palette["text"], (cx, 38), anchor="center", shadow=(2, 6, 16))
        draw_text(canvas, self.resources, tr(self.language, desc_key), 13,
                  palette["muted"], (cx, 80), anchor="center")
        panel = self._mp_panel()
        draw_panel(canvas, panel, (*palette["panel"], 230), palette["border"],
                   16, 2)
        self.widgets.draw(canvas, self.resources, palette)
        info_y = panel.y + 440
        if hosting:
            draw_text(canvas, self.resources,
                      tr(self.language, "mp_ip_hint", ip=self.mp_local_ip), 13,
                      palette["accent"], (panel.x + 56, info_y))
            draw_text(canvas, self.resources, tr(self.language, "mp_lan_hint"),
                      11, palette["muted"], (panel.x + 56, info_y + 22))
        else:
            draw_text(canvas, self.resources, tr(self.language, "mp_lan_hint"),
                      11, palette["muted"], (panel.x + 56, info_y + 10))
        if self.mp_error:
            lines = self.resources.wrap_text(self.mp_error, 13, panel.width - 120)
            for index, line in enumerate(lines[:2]):
                draw_text(canvas, self.resources, line, 13, palette["danger"],
                          (panel.x + 56, info_y + 46 + index * 18))
        else:
            draw_text(canvas, self.resources, tr(self.language, "mp_network_note"),
                      11, palette["muted"], (panel.x + 56, info_y + 46))
        draw_text(canvas, self.resources, tr(self.language, "mp_start_hint"), 11,
                  palette["muted"], (cx, VH - 22), anchor="center")

    def _draw_mp_lobby(self, canvas):
        palette = self.palette
        cx = VW // 2
        hosting = self.mp_role == "host"
        title_key = "mp_lobby_host" if hosting else "mp_lobby_client"
        draw_text(canvas, self.resources, tr(self.language, title_key), 34,
                  palette["text"], (cx, 38), anchor="center", shadow=(2, 6, 16))
        panel = self._mp_panel()
        draw_panel(canvas, panel, (*palette["panel"], 232),
                   palette["danger"] if self.mp_error else palette["border"],
                   16, 2)
        left = panel.x + 56
        right = panel.right - 56

        status_color = (palette["success"] if self.mp_connected
                        else palette["warning"])
        if self.mp_error:
            status = tr(self.language, "mp_error", message="")
            status_color = palette["danger"]
        elif self.mp_connected:
            status = tr(self.language, "mp_connected")
        elif hosting:
            status = tr(self.language, "mp_waiting")
        else:
            status = tr(self.language, "mp_connecting")
        draw_text(canvas, self.resources, status, 24, status_color,
                  (cx, panel.y + 54), anchor="center")

        if hosting:
            draw_text(canvas, self.resources, tr(self.language, "mp_host_label"),
                      11, palette["muted"], (left, panel.y + 106))
            draw_text(canvas, self.resources,
                      f"{self.settings.player_name} · "
                      f"{tr(self.language, SHIPS[self.settings.ship]['name'])}",
                      17, palette["text"], (left, panel.y + 122))
            draw_text(canvas, self.resources,
                      tr(self.language, "mp_ip_hint", ip=self.mp_local_ip), 14,
                      palette["accent"], (left, panel.y + 164))
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'mp_port')}: "
                      f"{self.mp_port_display}", 14, palette["accent"],
                      (left, panel.y + 188))
            draw_text(canvas, self.resources,
                      tr(self.language, "mp_join_hint"), 11, palette["muted"],
                      (left, panel.y + 218))
            run_key = ("mp_campaign" if self.mp_run_type == "campaign"
                       else "mp_endless")
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'mp_run_type')}: "
                      f"{tr(self.language, run_key)}", 13,
                      palette["accent2"], (left, panel.y + 250))
            if self.mp_run_type == "campaign":
                mission = mission_by_id(self.mp_mission_id)
                if mission is not None:
                    draw_text(canvas, self.resources,
                              f"{tr(self.language, 'mp_mission')}: "
                              f"{mission_name(self.language, mission)}", 13,
                              palette["text"], (left, panel.y + 274))
            draw_text(canvas, self.resources,
                      tr(self.language, "mp_client_label"), 11,
                      palette["muted"], (right, panel.y + 106))
            if self.mp_connected:
                partner = self.mp_peer_name or "Pilot"
                ship_name = tr(self.language, SHIPS.get(
                    self.mp_peer_ship, SHIPS["fighter"])["name"])
                draw_text(canvas, self.resources, f"{partner} · {ship_name}", 17,
                          palette["text"], (right, panel.y + 122),
                          anchor="topright")
                draw_text(canvas, self.resources, tr(self.language, "mp_press_start"),
                          12, palette["success"], (right, panel.y + 164),
                          anchor="topright")
            else:
                draw_text(canvas, self.resources,
                          tr(self.language, "mp_waiting_short"), 17,
                          palette["muted"], (right, panel.y + 122),
                          anchor="topright")
        else:
            draw_text(canvas, self.resources, tr(self.language, "mp_client_label"),
                      11, palette["muted"], (left, panel.y + 106))
            draw_text(canvas, self.resources,
                      f"{self.settings.player_name} · "
                      f"{tr(self.language, SHIPS[self.settings.ship]['name'])}",
                      17, palette["text"], (left, panel.y + 122))
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'mp_address')}: "
                      f"{self.mp_host_address}", 14, palette["accent"],
                      (left, panel.y + 164))
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'mp_port')}: "
                      f"{self.mp_port_display}", 14, palette["accent"],
                      (left, panel.y + 188))
            draw_text(canvas, self.resources, tr(self.language, "mp_client_wait"),
                      12, palette["muted"], (left, panel.y + 222))
            draw_text(canvas, self.resources, tr(self.language, "mp_host_label"),
                      11, palette["muted"], (right, panel.y + 106))
            if self.mp_connected:
                draw_text(canvas, self.resources, self.mp_host_name or "Host", 17,
                          palette["text"], (right, panel.y + 122),
                          anchor="topright")
            else:
                draw_text(canvas, self.resources,
                          tr(self.language, "mp_waiting_short"), 17,
                          palette["muted"], (right, panel.y + 122),
                          anchor="topright")

        if self.mp_error:
            lines = self.resources.wrap_text(self.mp_error, 13, panel.width - 120)
            y = panel.bottom - 182
            for line in lines[:2]:
                draw_text(canvas, self.resources, line, 13, palette["danger"],
                          (cx, y), anchor="center")
                y += 18
            draw_text(canvas, self.resources, tr(self.language, "coop_reconnect_hint"),
                      11, palette["muted"], (cx, panel.bottom - 210),
                      anchor="center")
        self.widgets.draw(canvas, self.resources, palette)
        if not self.mp_error:
            hint = ("mp_start_hint" if hosting else "mp_join_hint_keys")
            draw_text(canvas, self.resources, tr(self.language, hint), 11,
                      palette["muted"], (cx, VH - 22), anchor="center")

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
