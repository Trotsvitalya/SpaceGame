"""Host-authoritative co-op scene.

The host runs the normal :class:`GameProcess` simulation with two ships.  A
second ship is driven by the latest validated input received over TCP; clients
never simulate enemies, bosses or projectiles themselves.  Snapshots are small
JSON dictionaries so both players see the same world.
"""

from __future__ import annotations

import math

import pygame

from GameData import UPGRADES, upgrade_available, zone_index_for_wave
from GameProcessClass import GameProcess
from Localization import tr
from UIClass import Button, WidgetGroup, draw_bar, draw_panel, draw_text
from UserShipClass import UserShip
from utils import VH, VW, clamp

SNAPSHOT_INTERVAL = 1.0 / 20.0
REVIVE_TIME = 2.4
REVIVE_RADIUS = 105.0


def _color(value):
    return [int(component) for component in value[:3]]


def _ship_state(ship, slot, name, revive_time=REVIVE_TIME):
    return {
        "slot": slot,
        "name": name[:24],
        "ship": ship.kind,
        "x": round(ship.posX, 1),
        "y": round(ship.posY, 1),
        "vx": round(getattr(ship, "vx", 0.0), 1),
        "vy": round(getattr(ship, "vy", 0.0), 1),
        "life": int(ship.life),
        "max_life": int(getattr(ship, "max_life", ship.life)),
        "alive": bool(ship.alive),
        "downed": bool(getattr(ship, "downed", False)),
        "revive": round(getattr(ship, "revive_progress", 0.0), 2),
        "revive_need": revive_time,
        "shield": round(getattr(ship, "shield_timer", 0.0), 2),
        "weapon": int(getattr(ship, "weapon_level", 1)),
        "weapon_class": getattr(ship, "weapon_class", "pulse"),
        "rapid": round(getattr(ship, "rapid_timer", 0.0), 2),
        "invuln": round(getattr(ship, "invulnerable_timer", 0.0), 2),
        "flash": round(getattr(ship, "damage_flash", 0.0), 2),
    }


def build_snapshot(game, names):
    """Serialise the host world into a bounded, JSON-safe dictionary."""
    campaign = getattr(game, "campaign", False)
    mission = getattr(game, "campaign_mission", None) if campaign else None
    zone_index = (int(mission.get("zone", 0)) if mission
                  else zone_index_for_wave(game.wave))
    state = game.state
    story = None
    if state == "story" and getattr(game, "story_keys", ()):
        index = min(game.story_index, len(game.story_keys) - 1)
        story = {
            "key": game.story_keys[index],
            "index": index + 1,
            "total": len(game.story_keys),
        }
    snapshot = {
        "time": round(game.time, 2),
        "state": state,
        "mode": game.mode,
        "difficulty": game.difficulty,
        "campaign": bool(campaign),
        "mission": mission["id"] if mission else None,
        "mission_name": mission["name_key"] if mission else None,
        "zone": int(zone_index),
        "wave": int(game.wave),
        "total_waves": game.total_waves,
        "wave_timer": round(game.wave_timer, 2),
        "score": int(game.score),
        "display_score": int(game.display_score),
        "kills": int(game.kills),
        "salvage": int(game.salvage),
        "meme_points": int(getattr(game, "meme_points", 0)),
        "superpower_charges": dict(getattr(
            game, "superpower_charges", {"tiger": 0, "chainsaw": 0}
        )),
        "boss": None,
        "players": [
            _ship_state(game.player, 0, names[0]),
            _ship_state(game.player2, 1, names[1]),
        ],
        "enemies": [],
        "player_bullets": [],
        "enemy_bullets": [],
        "powerups": [],
        "zones": [],
        "beams": [],
        "announce": None,
        "tiger": ({
            "phase": game.tiger_ultimate.phase,
            "elapsed": round(game.tiger_ultimate.elapsed, 3),
            "phase_time": round(game.tiger_ultimate.phase_time, 3),
            "struck": bool(game.tiger_ultimate.struck),
        } if game.tiger_ultimate.active else None),
        "chainsaw": ({
            "phase": game.chainsaw.phase,
            "phase_time": round(game.chainsaw.phase_time, 3),
            "elapsed": round(game.chainsaw.elapsed, 3),
            "saws": [[round(saw[0], 1), round(saw[1], 1)]
                     for saw in game.chainsaw.saws],
        } if game.chainsaw.active else None),
        "meme_event": ({
            "kind": game.meme_event.kind,
            "time": round(game.meme_event.time, 3),
            "duration": round(game.meme_event.duration, 3),
            "arrow_count": int(game.meme_event.arrow_count),
            "envelopes": [{
                "x": round(envelope["x"], 1),
                "y": round(envelope["y"], 1),
                "speed": round(envelope["speed"], 1),
                "phase": round(envelope["phase"], 3),
            } for envelope in game.meme_event.envelopes],
        } if game.meme_event.active else None),
        "story": story,
        "upgrade": None,
        "result": (game.campaign_result if state == "victory"
                   else game.result if state == "gameover" else None),
    }
    if state == "upgrade" and game.upgrade_choices:
        snapshot["upgrade"] = {
            "salvage": int(game.salvage),
            "focus": int(getattr(game, "upgrade_focus", 0)),
            "choices": [
                {
                    "key": key,
                    "cost": int(cost),
                    "level": int(game.player.upgrade_level(key)),
                    "affordable": bool(game.salvage >= cost),
                }
                for key, cost in game.upgrade_choices[:3]
            ],
        }
    boss = game.boss
    if boss is not None:
        snapshot["boss"] = {
            "kind": boss.kind,
            "x": round(boss.posX, 1),
            "y": round(boss.posY, 1),
            "hp": round(max(0.0, boss.hp), 1),
            "max_hp": int(boss.max_hp),
            "phase": int(getattr(boss, "phase", 1)),
            "entered": bool(getattr(boss, "entered", False)),
        }
    for enemy in game.enemies[:24]:
        if not enemy.alive:
            continue
        snapshot["enemies"].append({
            "kind": enemy.kind,
            "x": round(enemy.posX, 1),
            "y": round(enemy.posY, 1),
            "hp": round(max(0.0, enemy.hp), 1),
            "max_hp": int(enemy.max_hp),
            "radius": round(float(getattr(enemy, "radius", 20.0)), 1),
            "level": getattr(enemy, "level", ""),
            "angle": round(float(getattr(enemy, "angle", 0.0)), 1),
            "index": int(getattr(enemy, "rot_index", 0) or 0),
        })
    for bullet in game.player_bullets[:110]:
        snapshot["player_bullets"].append({
            "x": round(bullet.posX, 1), "y": round(bullet.posY, 1),
            "kind": bullet.kind, "radius": round(bullet.radius, 1),
            "color": _color(bullet.color),
        })
    for bullet in game.enemy_bullets[:220]:
        snapshot["enemy_bullets"].append({
            "x": round(bullet.posX, 1), "y": round(bullet.posY, 1),
            "kind": bullet.kind, "radius": round(bullet.radius, 1),
            "color": _color(bullet.color),
        })
    for powerup in game.powerups[:10]:
        snapshot["powerups"].append({
            "kind": powerup.kind,
            "x": round(powerup.posX, 1), "y": round(powerup.posY, 1),
        })
    for zone in game.danger_zones[:8]:
        snapshot["zones"].append({
            "x": round(zone.x, 1), "y": round(zone.y, 1),
            "radius": round(zone.radius, 1),
            "warn": round(zone.warn, 2), "duration": round(zone.duration, 2),
            "age": round(zone.age, 2), "color": _color(zone.color),
        })
    for beam in game.beams[:6]:
        snapshot["beams"].append({
            "x": round(beam.x, 1), "y": round(beam.y, 1),
            "angle": round(beam.angle, 3),
            "warn": round(beam.warn, 2), "duration": round(beam.duration, 2),
            "length": round(beam.length, 1), "width": round(beam.width, 1),
            "age": round(beam.age, 2), "sweep": round(beam.sweep, 3),
            "color": _color(beam.color),
        })
    if game.announce_timer > 0 and game.announce_text:
        snapshot["announce"] = {
            "text": game.announce_text,
            "sub": game.announce_sub,
            "color": _color(game.announce_color),
            "timer": round(game.announce_timer, 2),
            "duration": round(game.announce_duration, 2),
        }
    return snapshot


class CoopHostGame(GameProcess):
    """Two-ship run whose second ship is fed by a :class:`HostSession`."""

    def __init__(self, app, session, mode="normal", difficulty=None,
                 mission=None, progress=None, client_name=None,
                 client_ship=None):
        super().__init__(app, mode, difficulty=difficulty, mission=mission,
                         progress=progress)
        self.net = session
        self.coop = True
        client_name = client_name or getattr(session, "client_name", "") or "Pilot"
        self.client_name = client_name[:24]
        self.host_name = (getattr(session, "host_name", "") or "Host")[:24]
        client_ship = client_ship or getattr(session, "client_ship", "fighter")
        self.client_ship = client_ship if client_ship in ("fighter", "interceptor",
                                                          "tank", "engineer") else "fighter"
        self.player2 = UserShip(
            VW * 0.66, VH - 178, VW, VH,
            imageList=self.resources.ship_frames_for(self.client_ship),
            imageBoomList=self.resources.boom_sources,
            kind=self.client_ship,
        )
        self.player2.posX = VW * 0.66
        self.player2.posY = VH - 178
        self.player2.downed = False
        self.player2.revive_progress = 0.0
        self.players = [self.player, self.player2]
        self._sync_timer = 0.0
        self._result_sent = False
        self._last_wave = self.wave
        self.peer_left = False
        self.disconnect_reason = ""
        self._state_before_disconnect = "playing"
        self._closing = False

    # ------------------------------------------------------------ lifecycle
    def on_enter(self):
        super().on_enter()
        if self.net is not None:
            self.net.reset_input()
            self.net.send_start(
                mode=self.mode,
                difficulty=self.difficulty,
                mission=(self.campaign_mission["id"] if self.campaign else None),
                host_name=self.host_name,
                client_name=self.client_name,
                host_ship=self.ship_kind,
                client_ship=self.client_ship,
            )
            self._send_snapshot()

    def on_exit(self):
        self._close_net()
        super().on_exit()

    def _close_net(self):
        if self._closing:
            return
        self._closing = True
        if self.net is not None:
            try:
                self.net.close()
            except OSError:
                pass
            self.net = None

    def _end_session(self, main_menu=False):
        self._close_net()
        if main_menu:
            self.app.go_menu()
        else:
            self.app.go_multiplayer()

    # ---------------------------------------------------------------- input
    def _input_for(self, ship):
        if ship is self.player2:
            if self.net is None or self.peer_left:
                return (0.0, 0.0, False)
            return self.net.input()
        return super()._input_for(ship)

    def _on_player_downed(self, player):
        name = (self.client_name if player is self.player2
                else self.host_name)
        self._announce(tr(self.language, "coop_player_down", name=name),
                       self.palette["danger"], 2.4,
                       sub=tr(self.language, "coop_revive_hint"))
        self.audio.play("low_health", 0.8)

    # --------------------------------------------------------------- updates
    def update(self, dt):
        if self.state == "disconnected":
            self.overlay_time += dt
            self._poll_network()
            return
        self._poll_network()
        if self.state == "disconnected":
            self.overlay_time += dt
            return
        super().update(dt)
        if self.state in ("playing", "dying") and not self.tiger_ultimate.active:
            self._update_revives(dt)
            if self.wave != self._last_wave:
                self._last_wave = self.wave
                self._revive_at_wave()
        self._sync_timer += dt
        if self._sync_timer >= SNAPSHOT_INTERVAL:
            self._sync_timer = 0.0
            self._send_snapshot()
        if self.state in ("victory", "gameover") and not self._result_sent:
            self._send_result()

    def _poll_network(self):
        if self.net is None or self.peer_left:
            return
        for message in self.net.poll():
            kind = message.get("t")
            if kind in ("peer_left", "error"):
                reason = message.get("reason") or message.get("message") or ""
                self._peer_disconnected(reason)
                return
            if kind == "pause_request":
                # Pause is authoritative on the host, then shared with both
                # players through the next state snapshot.
                desired = message.get("paused")
                if desired is True and self.state == "playing":
                    self._pause()
                elif desired is False and self.state == "paused":
                    self._resume()
                elif desired is None:
                    if self.state == "playing":
                        self._pause()
                    elif self.state == "paused":
                        self._resume()
                continue
            if kind == "peer_story_skip":
                if self.state == "story":
                    self._advance_story()
                    self._send_snapshot()
                continue
            if kind == "superpower":
                if self.mode == "meme" and self.state == "playing":
                    self._buy_or_activate_superpower(message.get("kind"))
                continue
            if kind == "peer_joined":
                continue

    def _peer_disconnected(self, reason):
        if self.peer_left:
            return
        self.peer_left = True
        if self.tiger_ultimate.active:
            self.tiger_ultimate.cancel()
            self.audio.stop_tiger_ultimate()
            self.audio.resume_music()
        self.disconnect_reason = (reason or "partner disconnected")[:80]
        if self.state in ("playing", "story", "paused", "upgrade", "dying"):
            self._state_before_disconnect = self.state
            self.state = "disconnected"
            self.overlay_time = 0.0
            self.audio.play("low_health", 0.8)
            self._send_snapshot()

    def _update_revives(self, dt):
        for player in self.players:
            if not getattr(player, "downed", False):
                continue
            partner = self.player2 if player is self.player else self.player
            if not partner.alive:
                continue
            distance = math.hypot(player.centerx - partner.centerx,
                                  player.centery - partner.centery)
            if distance <= REVIVE_RADIUS:
                player.revive_progress = min(
                    REVIVE_TIME, getattr(player, "revive_progress", 0.0) + dt
                )
                if player.revive_progress >= REVIVE_TIME:
                    self._revive_player(player)
            else:
                player.revive_progress = max(
                    0.0, getattr(player, "revive_progress", 0.0) - dt * 0.6
                )

    def _revive_player(self, player):
        player.downed = False
        player.revive_progress = 0.0
        player.life = max(1, player.life)
        player.alive = True
        player.isBoom = False
        player.respawn_timer = 0.0
        player.invulnerable_timer = 2.2
        player.posX = clamp(player.posX, 60, VW - 60)
        player.posY = clamp(player.posY, 80, VH - 90)
        name = (self.client_name if player is self.player2
                else self.host_name)
        self._announce(tr(self.language, "coop_revived", name=name),
                       self.palette["success"], 2.0)
        self.audio.play("upgrade_apply", 0.7)
        self.effects.ring(player.centerx, player.centery,
                          self.palette["success"], 90, 0.6, 3)

    def _revive_at_wave(self):
        for player in self.players:
            if getattr(player, "downed", False):
                self._revive_player(player)

    # -------------------------------------------------------------- upgrades
    def _apply_upgrade(self, index):
        if index < 0 or index >= len(self.upgrade_choices):
            return
        key, cost = self.upgrade_choices[index]
        if not upgrade_available(key, self.player.upgrades):
            return
        if self.salvage < cost:
            self.audio.play("hit", 0.4, throttle_ms=160)
            self.effects.text(tr(self.language, "upgrade_no_salvage"),
                              VW // 2, 548, self.palette["danger"], 15, 0.9)
            return
        self.salvage -= cost
        applied = False
        for player in self.players:
            if player.apply_upgrade(key):
                applied = True
        if applied:
            spec = UPGRADES[key]
            self.effects.text(
                tr(self.language, "upgrade_applied",
                   name=tr(self.language, spec["name"])),
                VW // 2, 210, spec["color"], 20, 1.4,
            )
            self.audio.play("upgrade_apply", 0.8)
        self._close_upgrade()

    # ---------------------------------------------------------------- pauses
    def _pause(self):
        super()._pause()
        self._send_snapshot()

    def _resume(self):
        super()._resume()
        self._send_snapshot()

    def _build_pause_widgets(self):
        cx = VW // 2
        panel_top = VH // 2 - 190
        widgets = [
            Button((cx - 150, panel_top + 190, 300, 48),
                   tr(self.language, "resume"), "resume"),
            Button((cx - 150, panel_top + 250, 300, 48),
                   tr(self.language, "coop_end_session"), "end_session"),
            Button((cx - 150, panel_top + 310, 300, 48),
                   tr(self.language, "main_menu"), "main_menu_quit"),
        ]
        self.pause_group = WidgetGroup(
            widgets, on_hover=lambda: self.audio.play("ui_hover", 0.4)
        )

    def _restart(self):
        self._end_session()

    def _to_menu(self):
        self._end_session()

    def _handle_action(self, action):
        if action in ("end_session", "campaign_menu", "menu", "campaign_next",
                      "campaign_replay", "campaign_retry"):
            self._end_session()
            return
        if action in ("main_menu_quit", "campaign_main"):
            self._end_session(main_menu=True)
            return
        super()._handle_action(action)

    # -------------------------------------------------------------- endgame
    def _finalize_game_over(self):
        if self.state == "gameover":
            return
        if self.campaign:
            super()._finalize_game_over()
            return
        self.state = "gameover"
        self.overlay_time = 0.0
        self.audio.stop_music()
        self.audio.play("gameover" if self.mode == "normal" else "meme_gameover",
                        0.85)
        self.result = {
            "score": int(self.score),
            "wave": self.wave,
            "kills": self.kills,
            "time": self.game_time,
            "rank": 0,
            "is_new": False,
            "best_before": 0,
            "best": 0,
            "salvage": self.salvage,
            "coop": True,
        }
        self._build_gameover_widgets()

    def _build_gameover_widgets(self):
        cx = VW // 2
        panel_top = VH // 2 - 235
        widgets = [
            Button((cx - 160, panel_top + 366, 320, 46),
                   tr(self.language, "coop_end_session"), "end_session"),
            Button((cx - 160, panel_top + 420, 320, 42),
                   tr(self.language, "main_menu"), "main_menu_quit", size=17),
        ]
        self.over_group = WidgetGroup(
            widgets, on_hover=lambda: self.audio.play("ui_hover", 0.4)
        )

    def _build_victory_widgets(self, summary, campaign_complete):
        cx = VW // 2
        panel_top = VH // 2 - 250
        widgets = [
            Button((cx - 170, panel_top + 430, 340, 46),
                   tr(self.language, "coop_end_session"), "end_session", size=19),
            Button((cx - 170, panel_top + 484, 340, 42),
                   tr(self.language, "main_menu"), "main_menu_quit", size=17),
        ]
        self.victory_group = WidgetGroup(
            widgets, on_hover=lambda: self.audio.play("ui_hover", 0.4)
        )

    # ------------------------------------------------------------- networking
    def _send_snapshot(self):
        if self.net is None or not self.net.connected:
            return
        try:
            self.net.send_state(build_snapshot(
                self, (self.host_name, self.client_name)
            ))
        except (ValueError, TypeError):
            self._peer_disconnected("could not serialise world state")

    def _send_result(self):
        self._result_sent = True
        if self.net is None or not self.net.connected:
            return
        result = (self.campaign_result if self.state == "victory"
                  else self.result) or {}
        payload = {
            "state": self.state,
            "score": int(result.get("score", self.score)),
            "kills": int(result.get("kills", self.kills)),
            "time": float(result.get("time", self.game_time)),
            "wave": int(result.get("wave", self.wave)),
            "campaign": bool(self.campaign),
            "campaign_complete": bool(result.get("campaign_complete", False)),
            "summary": result.get("summary") if isinstance(
                result.get("summary"), dict) else None,
            "mission": (self.campaign_mission["name_key"]
                        if self.campaign else None),
        }
        try:
            self.net.send_result(payload)
        except (ValueError, TypeError):
            pass

    # ------------------------------------------------------------------- draw
    def _draw_coop_status(self, canvas):
        palette = self.palette
        panel = pygame.Rect(VW - 358, 78, 340, 92)
        draw_panel(canvas, panel, (*palette["panel"], 205),
                   palette["border"], 10, 1)
        names = (self.host_name, self.client_name)
        for index, player in enumerate(self.players):
            y = panel.y + 10 + index * 40
            label = "%s  %s" % (tr(self.language, "coop_p1" if index == 0
                                   else "coop_p2"), names[index])
            draw_text(canvas, self.resources, label, 11,
                      palette["accent"] if player.alive else palette["muted"],
                      (panel.x + 12, y))
            for pip in range(min(7, max(0, player.life))):
                canvas.blit(self.resources.ship_small,
                            (panel.x + 150 + pip * 24, y - 2))
            if getattr(player, "downed", False):
                draw_text(canvas, self.resources,
                          tr(self.language, "coop_downed"), 11,
                          palette["danger"], (panel.x + 216, y))
                progress = getattr(player, "revive_progress", 0.0) / REVIVE_TIME
                draw_bar(canvas, (panel.x + 216, y + 14, 108, 4), progress,
                         palette["warning"], (28, 34, 54), None, 2)
            elif not player.alive:
                draw_text(canvas, self.resources,
                          tr(self.language, "coop_respawning"), 10,
                          palette["muted"], (panel.x + 216, y))

    def _draw_hud(self, canvas):
        super()._draw_hud(canvas)
        self._draw_coop_status(canvas)

    def _draw_disconnected(self, canvas):
        palette = self.palette
        fade = min(1.0, self.overlay_time * 2.6)
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        overlay.fill((4, 5, 14, int(210 * fade)))
        canvas.blit(overlay, (0, 0))
        cx = VW // 2
        panel = pygame.Rect(cx - 330, VH // 2 - 170, 660, 340)
        draw_panel(canvas, panel, (*palette["panel"], int(245 * fade)),
                   palette["danger"], 18, 2)
        draw_text(canvas, self.resources, tr(self.language, "coop_disconnected"),
                  34, palette["danger"], (cx, panel.y + 44), anchor="center")
        draw_text(canvas, self.resources,
                  self.disconnect_reason or tr(self.language, "coop_link_lost"),
                  14, palette["text"], (cx, panel.y + 92), anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "coop_continue_solo"),
                  17, palette["accent"], (cx, panel.y + 172), anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "coop_end_hint"),
                  14, palette["muted"], (cx, panel.y + 202), anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "coop_solo_hint"),
                  11, palette["muted"], (cx, panel.y + 250), anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "coop_end_session"),
                  13, palette["muted"], (cx, panel.y + 292), anchor="center")

    def handle_event(self, event, mouse=None):
        if self.state == "disconnected":
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._continue_solo()
                elif event.key in (pygame.K_ESCAPE, pygame.K_m):
                    self._end_session()
            return
        super().handle_event(event, mouse)

    def _continue_solo(self):
        self._close_net()
        self.peer_left = False
        self.players = [self.player]
        if getattr(self.player, "downed", False):
            self._revive_player(self.player)
        self.coop = False
        self.state = "playing"
        self.overlay_time = 0.0
        self._announce(tr(self.language, "coop_solo"), self.palette["warning"],
                       2.2)

    def draw(self, canvas):
        super().draw(canvas)
        if self.state == "disconnected":
            self._draw_disconnected(canvas)
