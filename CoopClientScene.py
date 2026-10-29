"""Client-side co-op scene.

The client never simulates the world.  It sends small input frames to the host
and renders the snapshots the host broadcasts.  All gameplay state (waves,
enemies, projectiles, bosses, salvage and results) therefore stays
authoritative on the host machine, which also owns campaign progress.
"""

from __future__ import annotations

import math
import random
import time

import pygame

from GameData import SHIPS, UPGRADES, WEAPONS
from ChainsawUltimate import ChainsawUltimate
from Hazards import BeamAttack, DangerZone
from Localization import tr
from MemeEventSystem import MemeEventSystem
from PowerUpClass import PowerUp
from ResourcesClass import palette_for
from SpaceBackdrop import SpaceBackdrop
from TigerUltimate import TigerUltimate
from UIClass import draw_bar, draw_panel, draw_text
from utils import VH, VW, clamp, format_score, format_time

SNAPSHOT_STALE = 8.0
SNAPSHOT_INTERPOLATION = 0.05


def _color(value, fallback=(120, 220, 255)):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return fallback
    try:
        return tuple(max(0, min(255, int(channel))) for channel in value[:3])
    except (TypeError, ValueError):
        return fallback


class CoopClientScene:
    """Renders host snapshots and forwards local input."""

    hide_cursor = False
    isRunMainLoop = True

    def __init__(self, app, session, start_info=None):
        self.app = app
        self.settings = app.settings
        self.resources = app.resources
        self.audio = app.audio
        self.net = session
        self.language = self.settings.language
        info = start_info if isinstance(start_info, dict) else {}
        self.start_info = dict(info)
        self.mode = info.get("mode") if info.get("mode") in ("normal", "meme") else "normal"
        self.difficulty = info.get("difficulty", "normal")
        self.palette = palette_for(self.mode)
        self.local_slot = 1
        self.local_name = (info.get("client_name") or self.settings.player_name)[:24]
        self.host_name = (info.get("host_name") or "Host")[:24]
        self.host_ship = info.get("host_ship") if info.get("host_ship") in SHIPS else "fighter"
        self.client_ship = info.get("client_ship") if info.get("client_ship") in SHIPS else "fighter"
        self.mission_id = info.get("mission")

        quality = getattr(self.settings, "effects_quality", 2)
        self.backdrop = SpaceBackdrop(
            self.resources, self.mode, zone=0, seed=random.randint(1, 99999),
            quality=quality, planet_scale=0.9,
        )
        self._zone_index = 0

        self.snapshot = None
        self.previous_snapshot = None
        self.snapshot_time = time.monotonic()
        self.previous_snapshot_time = self.snapshot_time
        self.state = "waiting"
        self.result = None
        self.disconnect_reason = ""
        self.time = 0.0
        self.overlay_time = 0.0
        self.local_menu = False
        self.pause_hint = 0.0
        self.story_key = None
        self._last_state = "waiting"
        self._overlay_buttons = []
        self._music_stopped = False
        self.tiger_ultimate = TigerUltimate()
        self.chainsaw = ChainsawUltimate()
        self.meme_event = MemeEventSystem()
        self._remote_chainsaw_sound_timer = 0.0
        self._tiger_paused = False
        self._tiger_resume_pending = False

    # ------------------------------------------------------------ lifecycle
    def on_enter(self):
        self.audio.play_music("game", self.mode)

    def on_exit(self):
        self.tiger_ultimate.cancel()
        self.tiger_ultimate.close()
        self.audio.stop_tiger_ultimate()
        self.audio.stop_music()
        self._close_session()

    def _close_session(self):
        if self.net is not None:
            try:
                self.net.close()
            except OSError:
                pass
            self.net = None

    # ---------------------------------------------------------------- input
    def _read_local_input(self):
        if (self.local_menu or self.net is None
                or self.state not in ("playing", "dying")):
            return 0.0, 0.0, False
        keys = pygame.key.get_pressed()
        move_x = 0.0
        move_y = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            move_x -= 1.0
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            move_x += 1.0
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            move_y += 1.0
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            move_y -= 1.0
        firing = bool(keys[pygame.K_SPACE])
        return move_x, move_y, firing

    def _local_player(self):
        if not self.snapshot:
            return None
        players = self.snapshot.get("players") or []
        if 0 <= self.local_slot < len(players):
            return players[self.local_slot]
        return players[0] if players else None

    # --------------------------------------------------------------- update
    def update(self, dt):
        dt = clamp(dt, 0.0, 0.1)
        self._poll_network()
        if self.net is not None:
            move_x, move_y, firing = self._read_local_input()
            self.net.send_input(move_x, move_y, firing)
            self.net.heartbeat()
        if self.tiger_ultimate.active:
            if self.state != "paused":
                self.tiger_ultimate._update_particles(dt)
            return
        if self.chainsaw.chasing:
            self._remote_chainsaw_sound_timer -= dt
            if self._remote_chainsaw_sound_timer <= 0:
                self.audio.play("chainsaw", 0.55)
                self._remote_chainsaw_sound_timer = 1.1
        if self.meme_event.active and self.state != "paused":
            self.meme_event.time += dt
            if self.meme_event.kind == "red_envelopes":
                for envelope in self.meme_event.envelopes:
                    envelope["y"] += envelope["speed"] * dt
                    envelope["x"] += math.sin(
                        self.meme_event.time * 2.8 + envelope["phase"]
                    ) * 34 * dt
        if (self._tiger_resume_pending
                and not self.audio.tiger_ultimate_busy()):
            self.audio.resume_music()
            self._tiger_resume_pending = False
        self.time += dt
        self.overlay_time += dt
        self.pause_hint = max(0.0, self.pause_hint - dt)
        self.backdrop.update(dt, 0.4)
        if self.state not in ("victory", "gameover", "disconnected"):
            if time.monotonic() - self.snapshot_time > SNAPSHOT_STALE:
                self._disconnect(tr(self.language, "coop_link_lost"))

    def _poll_network(self):
        if self.net is None:
            return
        for message in self.net.poll():
            kind = message.get("t")
            if kind == "state":
                snapshot = message.get("state")
                if isinstance(snapshot, dict):
                    self._apply_snapshot(snapshot)
            elif kind == "result":
                result = message.get("result")
                if isinstance(result, dict):
                    self._apply_result(result)
            elif kind == "start":
                self.start_info.update(message)
                self.mode = message.get("mode", self.mode)
                self.difficulty = message.get("difficulty", self.difficulty)
                self.host_name = message.get("host_name", self.host_name)[:24]
                self.local_name = message.get("client_name", self.local_name)[:24]
                self.host_ship = message.get("host_ship", self.host_ship)
                self.client_ship = message.get("client_ship", self.client_ship)
                self.mission_id = message.get("mission", self.mission_id)
            elif kind in ("error", "peer_left"):
                reason = (message.get("reason") or message.get("message")
                          or tr(self.language, "coop_link_lost"))
                self._disconnect(reason)

    def _apply_snapshot(self, snapshot):
        self.previous_snapshot = self.snapshot
        self.previous_snapshot_time = self.snapshot_time
        self.snapshot = snapshot
        self.snapshot_time = time.monotonic()
        zone = snapshot.get("zone")
        if isinstance(zone, int) and zone != self._zone_index:
            self._zone_index = zone
            self.backdrop.set_zone(zone)
        state = snapshot.get("state")
        if state in ("playing", "dying", "story", "paused", "upgrade",
                     "victory", "gameover", "waiting"):
            self._set_state(state)
        self._sync_tiger(snapshot.get("tiger"), snapshot.get("mode"))
        self._sync_chainsaw(snapshot.get("chainsaw"))
        self._sync_meme_event(snapshot.get("meme_event"))
        if snapshot.get("result") and not self.result:
            self.result = snapshot["result"]
        story = snapshot.get("story")
        if isinstance(story, dict):
            key = story.get("key")
            if key != self.story_key:
                self.story_key = key
                self.audio.play("ui_click", 0.35, throttle_ms=180)

    def _sync_meme_event(self, state):
        valid_events = set(MemeEventSystem.EVENTS) | {"coffin_dance"}
        previous_kind = self.meme_event.kind
        kind = state.get("kind") if isinstance(state, dict) else None
        if kind not in valid_events:
            self._stop_synced_meme_audio(previous_kind)
            self.meme_event.kind = None
            self.meme_event.time = self.meme_event.duration = 0.0
            self.meme_event.envelopes.clear()
            return
        if kind != previous_kind:
            self._stop_synced_meme_audio(previous_kind)
            if kind == "coffin_dance":
                self.audio.play_coffin_dance()
            elif kind == "straw_boat":
                self.audio.play_meme_shout()
                self.audio.play_boat_loop()
                self.audio.play("meme_drum", 0.65)
                self.audio.play("meme_water", 0.55)
            elif kind == "vacuum_hurricane":
                self.audio.play("meme_air_raid", 0.65)
            elif kind == "golden_dragon":
                self.audio.play("meme_dragon", 0.85)
            elif kind == "red_envelopes":
                self.audio.play("meme_envelopes", 0.85)
        self.meme_event.kind = kind
        try:
            self.meme_event.time = clamp(float(state.get("time", 0)), 0.0,
                                         180.0)
            duration = float(state.get("duration", 0))
            self.meme_event.duration = (duration if math.isfinite(duration)
                                        and duration > 0 else
                                        MemeEventSystem.DURATIONS[self.meme_event.kind])
            self.meme_event.arrow_count = max(0, min(
                MemeEventSystem.BOAT_MAX_ARROWS,
                int(state.get("arrow_count", 22))))
        except (TypeError, ValueError, OverflowError):
            self.meme_event.time = 0.0
            self.meme_event.duration = MemeEventSystem.DURATIONS[self.meme_event.kind]
            self.meme_event.arrow_count = 22
        envelopes = []
        for envelope in state.get("envelopes") or []:
            if not isinstance(envelope, dict):
                continue
            try:
                envelopes.append({
                    "x": clamp(float(envelope.get("x", 0)), -100.0, VW + 100.0),
                    "y": clamp(float(envelope.get("y", 0)), -VH, VH + 100.0),
                    "speed": clamp(float(envelope.get("speed", 0)), 0.0, 300.0),
                    "phase": float(envelope.get("phase", 0)),
                })
            except (TypeError, ValueError):
                continue
        self.meme_event.envelopes = envelopes

    def _stop_synced_meme_audio(self, kind):
        if kind == "straw_boat":
            self.audio.stop_boat_loop()
        elif kind == "coffin_dance":
            self.audio.stop_coffin_dance()

    def _sync_chainsaw(self, state):
        valid_phases = {"split", "chase", "finish"}
        active = isinstance(state, dict) and state.get("phase") in valid_phases
        if not active:
            if self.chainsaw.active:
                self.chainsaw.cancel()
                self.audio.resume_music()
            return

        previous_phase = self.chainsaw.phase
        if not self.chainsaw.active:
            self.audio.pause_music()
            self.audio.play("chainsaw", 0.85)
            self._remote_chainsaw_sound_timer = 1.1
        self.chainsaw.phase = state["phase"]
        if (previous_phase == "split" and self.chainsaw.phase == "chase"
                and self.state != "paused"):
            self.audio.resume_music()
            self.audio.play("chainsaw", 0.85)
            self._remote_chainsaw_sound_timer = 1.1
        try:
            self.chainsaw.phase_time = clamp(float(state.get("phase_time", 0)),
                                              0.0, 2.0)
            self.chainsaw.elapsed = clamp(float(state.get("elapsed", 0)),
                                          0.0, 20.0)
        except (TypeError, ValueError):
            self.chainsaw.phase_time = self.chainsaw.elapsed = 0.0
        saws = state.get("saws") or []
        self.chainsaw.saws = []
        for saw in saws[:ChainsawUltimate.SAW_COUNT]:
            if not isinstance(saw, (list, tuple)) or len(saw) < 2:
                continue
            try:
                x = clamp(float(saw[0]), -100.0, VW + 100.0)
                y = clamp(float(saw[1]), -100.0, VH + 100.0)
            except (TypeError, ValueError):
                continue
            self.chainsaw.saws.append([x, y, None])

    def _sync_tiger(self, tiger, mode):
        active = (mode == "meme" and isinstance(tiger, dict)
                  and tiger.get("phase") in {
                      name for name, _duration in TigerUltimate.PHASES
                  })
        if active and not self.tiger_ultimate.active:
            self.tiger_ultimate.start()
            self.audio.pause_music()
            self.audio.play_tiger_ultimate()
            self._tiger_resume_pending = False
            self._tiger_paused = False
        elif not active and self.tiger_ultimate.active:
            self.tiger_ultimate.cancel()
            self._tiger_resume_pending = True
            self._tiger_paused = False

        if active:
            old_phase = self.tiger_ultimate.phase
            new_phase = tiger["phase"]
            if new_phase == "claw_strike" and old_phase != "claw_strike":
                self.tiger_ultimate._burst()
            self.tiger_ultimate.phase = new_phase
            try:
                self.tiger_ultimate.elapsed = max(0.0, min(
                    30.0, float(tiger.get("elapsed", 0.0))))
                self.tiger_ultimate.phase_time = max(0.0, min(
                    10.0, float(tiger.get("phase_time", 0.0))))
            except (TypeError, ValueError):
                self.tiger_ultimate.elapsed = self.tiger_ultimate.phase_time = 0.0
            self.tiger_ultimate.struck = bool(tiger.get("struck", False))
            previous_cut_event = self.tiger_ultimate.remote_cut_event
            self.tiger_ultimate.sync_remote_cut_events()
            for _when, kind, _index in TigerUltimate.CUT_EVENTS[
                    previous_cut_event:self.tiger_ultimate.remote_cut_event]:
                self.audio.play("chainsaw" if kind == "chainsaw" else "claw_slash",
                                0.8, throttle_ms=80)
            paused = self.state == "paused"
            if paused != self._tiger_paused:
                (self.audio.pause_tiger_ultimate() if paused else
                 self.audio.resume_tiger_ultimate())
                self._tiger_paused = paused

    def _apply_result(self, result):
        self.result = result
        state = result.get("state")
        self._set_state(state if state in ("victory", "gameover") else "gameover")

    def _set_state(self, state):
        if state == self.state:
            return
        previous = self.state
        self.state = state
        if state != previous:
            self.overlay_time = 0.0
        if state in ("victory", "gameover") and not self._music_stopped:
            self._music_stopped = True
            self.audio.stop_music()
            key = ("victory" if state == "victory" else
                   ("meme_gameover" if self.mode == "meme" else "gameover"))
            self.audio.play(key, 0.85)
        elif previous in ("victory", "gameover") and state in ("playing", "story"):
            self._music_stopped = False
            self.audio.play_music("game", self.mode)
        if state == "paused" and previous != "paused":
            self.audio.pause_music()
            if self.tiger_ultimate.active:
                self.audio.pause_tiger_ultimate()
        elif previous == "paused" and state != "paused":
            self.audio.resume_music()
            if self.tiger_ultimate.active:
                self.audio.resume_tiger_ultimate()

    def _disconnect(self, reason):
        if self.state == "disconnected":
            return
        if self.state in ("victory", "gameover") and self.result is not None:
            # The run already finished; a closed socket is expected and should
            # not replace the result screen.
            return
        self.disconnect_reason = str(reason or tr(self.language, "coop_link_lost"))[:120]
        if self.tiger_ultimate.active:
            self.tiger_ultimate.cancel()
            self.audio.stop_tiger_ultimate()
            self.audio.resume_music()
            self._tiger_resume_pending = False
        self._set_state("disconnected")
        self.audio.stop_music()
        self.audio.play("low_health", 0.8)

    # --------------------------------------------------------------- events
    def handle_event(self, event, mouse=None):
        mouse = mouse or self.app.mouse
        if event.type == pygame.QUIT:
            self.app.quit()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.app.toggle_fullscreen()
            return

        if self.state in ("victory", "gameover", "disconnected"):
            self._handle_overlay_event(event, self._overlay_buttons)
            return
        if self.local_menu:
            self._handle_overlay_event(event, self._overlay_buttons,
                                       escape_action="close_local_menu")
            return
        if self.state == "story":
            if event.type == pygame.KEYDOWN and event.key in (
                pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE,
                pygame.K_RIGHT, pygame.K_d, pygame.K_s, pygame.K_ESCAPE,
            ):
                self.net.send_story_skip() if self.net else None
            return

        if event.type == pygame.KEYDOWN:
            if (event.key in (pygame.K_1, pygame.K_2)
                    and self.mode == "meme" and self.state == "playing"
                    and self.net is not None):
                self.net.send_superpower(
                    "tiger" if event.key == pygame.K_1 else "chainsaw"
                )
                self.audio.play("ui_click", 0.45, throttle_ms=80)
                return
            if event.key == pygame.K_ESCAPE:
                self.local_menu = True
                self.overlay_time = 0.0
                self.audio.play("ui_click", 0.5)
                return
            if event.key == pygame.K_p:
                self.pause_hint = 2.6
                if self.net is not None:
                    self.net.send_pause_request(paused=self.state != "paused")
                self.audio.play("ui_click", 0.5)
                return

    def _handle_overlay_event(self, event, buttons, escape_action="leave_session"):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if escape_action == "close_local_menu":
                    self.local_menu = False
                    self.audio.play("ui_click", 0.5)
                else:
                    self._leave_session()
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER,
                             pygame.K_m):
                if buttons:
                    self._run_overlay_action(buttons[0][2])
                return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for rect, _label, action in buttons:
                if rect.collidepoint(self.app.mouse):
                    self._run_overlay_action(action)
                    return

    def _run_overlay_action(self, action):
        if action == "leave_session":
            self._leave_session()
        elif action == "main_menu":
            self._leave_session(main_menu=True)
        elif action == "close_local_menu":
            self.local_menu = False
            self.audio.play("ui_click", 0.5)

    def _leave_session(self, main_menu=False):
        if self.net is not None:
            try:
                self.net.send_leave("client left")
            except OSError:
                pass
            self.net = None
        if main_menu:
            self.app.go_menu()
        else:
            self.app.go_multiplayer()

    def _interpolated_snapshot(self):
        current = self.snapshot
        previous = self.previous_snapshot
        if not isinstance(current, dict) or not isinstance(previous, dict):
            return current
        elapsed = max(0.0, time.monotonic() - self.snapshot_time)
        sample_span = max(0.016, min(
            0.15, self.snapshot_time - self.previous_snapshot_time
        ))
        alpha = clamp(elapsed / max(sample_span, SNAPSHOT_INTERPOLATION), 0.0, 1.0)
        if alpha >= 1.0:
            return current
        display = dict(current)
        for list_key, match_key in (("players", "slot"), ("enemies", None)):
            now_items = current.get(list_key) or []
            old_items = previous.get(list_key) or []
            if len(now_items) != len(old_items):
                continue
            blended = []
            for index, item in enumerate(now_items):
                old = old_items[index]
                if (not isinstance(item, dict) or not isinstance(old, dict)
                        or (match_key and item.get(match_key) != old.get(match_key))
                        or (not match_key and item.get("kind") != old.get("kind"))):
                    blended.append(item)
                    continue
                blended_item = dict(item)
                for coord in ("x", "y"):
                    try:
                        blended_item[coord] = float(old.get(coord, item[coord])) + (
                            float(item[coord]) - float(old.get(coord, item[coord]))
                        ) * alpha
                    except (KeyError, TypeError, ValueError):
                        pass
                blended.append(blended_item)
            display[list_key] = blended
        old_boss = previous.get("boss")
        new_boss = current.get("boss")
        if (isinstance(old_boss, dict) and isinstance(new_boss, dict)
                and old_boss.get("kind") == new_boss.get("kind")):
            boss = dict(new_boss)
            for coord in ("x", "y"):
                try:
                    boss[coord] = float(old_boss.get(coord, new_boss[coord])) + (
                        float(new_boss[coord]) - float(old_boss.get(coord, new_boss[coord]))
                    ) * alpha
                except (KeyError, TypeError, ValueError):
                    pass
            display["boss"] = boss
        return display

    # ----------------------------------------------------------------- draw
    def draw(self, canvas):
        self._overlay_buttons = []
        self.backdrop.draw(canvas)
        snapshot = self._interpolated_snapshot()
        if snapshot is not None:
            self._draw_world(canvas, snapshot)
        canvas.blit(self.resources.vignette, (0, 0))
        if self.chainsaw.active:
            self.chainsaw.draw(canvas)
        if snapshot is not None:
            self._draw_hud(canvas, snapshot)
        if self.tiger_ultimate.active:
            self.tiger_ultimate.draw(
                canvas, getattr(self.settings, "reduced_flash", False),
                getattr(self.settings, "effects_quality", 2), self.language)
            if self.tiger_ultimate.phase == "return" and snapshot is not None:
                self._draw_hud(canvas, snapshot)

        if self.state == "waiting":
            self._draw_waiting(canvas)
        elif self.state == "story":
            self._draw_story(canvas)
        elif self.state == "paused":
            self._draw_paused(canvas)
        elif self.state == "upgrade":
            self._draw_upgrade(canvas, snapshot)
        elif self.state == "victory":
            self._draw_result(canvas, victory=True)
        elif self.state == "gameover":
            self._draw_result(canvas, victory=False)
        elif self.state == "disconnected":
            self._draw_disconnected(canvas)
        if self.local_menu:
            self._draw_local_menu(canvas)

    # --------------------------------------------------------------- world
    def _draw_world(self, canvas, snapshot):
        for zone in snapshot.get("zones") or []:
            try:
                hazard = DangerZone(
                    zone.get("x", 0), zone.get("y", 0),
                    radius=zone.get("radius", 96),
                    warn=zone.get("warn", 1.15),
                    duration=zone.get("duration", 1.6),
                    color=_color(zone.get("color"), self.palette["danger"]),
                )
                hazard.age = float(zone.get("age", 0.0))
                hazard.draw(canvas, self.palette)
            except (TypeError, ValueError):
                continue

        for powerup in snapshot.get("powerups") or []:
            self._draw_powerup(canvas, powerup)

        for enemy in snapshot.get("enemies") or []:
            self._draw_enemy(canvas, enemy)

        boss = snapshot.get("boss")
        if isinstance(boss, dict):
            self._draw_boss(canvas, boss)

        for beam in snapshot.get("beams") or []:
            try:
                hazard = BeamAttack(
                    beam.get("x", 0), beam.get("y", 0), beam.get("angle", 0),
                    warn=beam.get("warn", 1.0),
                    duration=beam.get("duration", 0.4),
                    length=beam.get("length", 1400),
                    width=beam.get("width", 18),
                    sweep=beam.get("sweep", 0.0),
                    color=_color(beam.get("color"), self.palette["danger"]),
                )
                hazard.age = float(beam.get("age", 0.0))
                hazard.draw(canvas)
            except (TypeError, ValueError):
                continue

        for bullet in snapshot.get("player_bullets") or []:
            self._draw_bullet(canvas, bullet, player=True)
        for bullet in snapshot.get("enemy_bullets") or []:
            self._draw_bullet(canvas, bullet, player=False)

        for player in snapshot.get("players") or []:
            self._draw_player(canvas, player)
        self.meme_event.draw(canvas, self.resources)

    def _draw_player(self, canvas, player):
        x = int(player.get("x", 0))
        y = int(player.get("y", 0))
        kind = player.get("ship", "fighter")
        if player.get("downed"):
            pulse = 0.55 + math.sin(self.time * 5.0) * 0.25
            radius = int(46 + pulse * 12)
            pygame.draw.circle(canvas, self.palette["danger"], (x, y), radius, 2)
            pygame.draw.circle(canvas, self.palette["warning"], (x, y), 18, 2)
            draw_text(canvas, self.resources, tr(self.language, "coop_downed"),
                      11, self.palette["danger"], (x, y - 44), anchor="center")
            return
        if not player.get("alive"):
            return
        frames = self.resources.ship_frames_for(kind)
        if not frames:
            return
        image = frames[int(self.time * 12) % len(frames)]
        if player.get("flash", 0) > 0:
            glow = self.resources.glow(70, (255, 255, 255), 140)
            canvas.blit(glow, glow.get_rect(center=(x, y)))
        alpha = 255
        if player.get("invuln", 0) > 0 and int(self.time * 14) % 2:
            alpha = 110
        if alpha < 255:
            image = image.copy()
            image.set_alpha(alpha)
        rect = image.get_rect(center=(x, y))
        canvas.blit(image, rect)
        if player.get("shield", 0) > 0:
            pygame.draw.circle(canvas, self.palette["accent"], (x, y), 45, 2)
            pygame.draw.circle(canvas, (240, 250, 255), (x, y), 41, 1)
        slot = player.get("slot", 0)
        label = self.local_name if slot == self.local_slot else self.host_name
        color = (self.palette["success"] if slot == self.local_slot
                 else self.palette["accent2"])
        draw_text(canvas, self.resources, label, 10, color, (x, y + 42),
                  anchor="center", alpha=190)

    def _draw_enemy(self, canvas, enemy):
        kind = enemy.get("kind", "asteroid")
        x = int(enemy.get("x", 0))
        y = int(enemy.get("y", 0))
        radius = max(6, int(enemy.get("radius", 20)))
        if kind == "asteroid":
            sources = self.resources.asteroid_sources
            index = int(enemy.get("index", 0)) % max(1, len(sources))
            image = self.resources.asteroid_rot(
                index, radius, float(enemy.get("angle", 0.0)),
            )
        else:
            frames = self.resources.enemy_frames(kind)
            if frames:
                image = frames[int(self.time * 12) % len(frames)]
            else:
                image = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(image, self.palette["danger"],
                                   (radius, radius), radius)
        canvas.blit(image, image.get_rect(center=(x, y)))
        hp = enemy.get("hp", 0)
        max_hp = max(1, int(enemy.get("max_hp", 1)))
        if kind != "asteroid" and hp < max_hp:
            draw_bar(canvas, (x - 22, y - radius - 12, 44, 4),
                     hp / max_hp, self.palette["danger"], (24, 16, 30), None, 2)

    def _draw_boss(self, canvas, boss):
        kind = boss.get("kind", "dreadnought")
        x = int(boss.get("x", 0))
        y = int(boss.get("y", 0))
        frames = self.resources.boss_frames(kind)
        if frames:
            image = frames[int(self.time * 8) % len(frames)]
            glow = self.resources.glow(120, self.palette["danger"], 55)
            canvas.blit(glow, glow.get_rect(center=(x, y)))
            canvas.blit(image, image.get_rect(center=(x, y)))
        else:
            pygame.draw.circle(canvas, self.palette["danger"], (x, y), 92, 3)

    def _draw_bullet(self, canvas, bullet, player):
        x = int(bullet.get("x", 0))
        y = int(bullet.get("y", 0))
        kind = bullet.get("kind", "pulse" if player else "enemy_orb")
        sprite_kind = ("player_" + str(kind)) if player else str(kind)
        image = self.resources.bullet_sprite(sprite_kind, self.mode)
        if image is not None:
            canvas.blit(image, image.get_rect(center=(x, y)))
        else:
            pygame.draw.circle(canvas, _color(bullet.get("color")), (x, y),
                               max(2, int(bullet.get("radius", 5))))

    def _draw_powerup(self, canvas, powerup):
        kind = powerup.get("kind", "points")
        x = int(powerup.get("x", 0))
        y = int(powerup.get("y", 0))
        bob = math.sin(self.time * 3.0 + x * 0.01) * 4
        center = (x, int(y + bob))
        sprite = self.resources.powerup_sprite(kind, self.mode)
        glow_color = PowerUp.COLORS.get(kind, self.palette["warning"])
        glow = self.resources.glow(30, glow_color, 80)
        canvas.blit(glow, glow.get_rect(center=center))
        if sprite:
            image = pygame.transform.rotozoom(
                sprite, math.sin(self.time * 2.0) * 8, 1.0
            )
            canvas.blit(image, image.get_rect(center=center))

    # ----------------------------------------------------------------- HUD
    def _draw_hud(self, canvas, snapshot):
        palette = self.palette
        top = pygame.Rect(18, 12, VW - 36, 60)
        draw_panel(canvas, top, (*palette["panel"], 210), palette["border"], 12, 1)
        draw_text(canvas, self.resources, tr(self.language, "score"), 11,
                  palette["muted"], (36, 21))
        draw_text(canvas, self.resources, format_score(snapshot.get("score", 0)),
                  27, palette["accent"], (36, 32), shadow=(2, 5, 12))

        mission_name = (snapshot.get("mission_name") if snapshot.get("campaign")
                        else None)
        if mission_name:
            draw_text(canvas, self.resources, tr(self.language, mission_name),
                      11, palette["muted"], (VW // 2, 18), anchor="midtop")
            draw_text(canvas, self.resources,
                      f"{snapshot.get('wave', 1):02d} / "
                      f"{snapshot.get('total_waves', 1):02d}", 21,
                      palette["text"], (VW // 2, 31), anchor="midtop")
        else:
            draw_text(canvas, self.resources, tr(self.language, "wave"), 11,
                      palette["muted"], (VW // 2, 20), anchor="midtop")
            draw_text(canvas, self.resources,
                      f"{snapshot.get('wave', 1):02d}", 23,
                      palette["text"], (VW // 2, 30), anchor="midtop")
        boss = snapshot.get("boss")
        if not boss:
            progress = clamp(snapshot.get("wave_timer", 0.0) / 24.0, 0.0, 1.0)
            draw_bar(canvas, (VW // 2 - 70, 59, 140, 3), progress,
                     palette["accent2"], (28, 34, 54), None, 1)
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'coop_host')}: {self.host_name}", 11,
                  palette["muted"], (VW - 36, 20), anchor="topright")
        draw_text(canvas, self.resources,
                  f"{self.difficulty.upper()}", 10, palette["accent2"],
                  (VW - 36, 38), anchor="topright")
        draw_text(canvas, self.resources,
                  tr(self.language, "coop_partner"), 10, palette["muted"],
                  (VW - 36, 52), anchor="topright")

        if boss:
            self._draw_boss_bar(canvas, boss)

        self._draw_coop_panel(canvas, snapshot)
        if snapshot.get("mode") == "meme":
            self._draw_superpower_shop(canvas, snapshot)

        local = self._local_player()
        if local:
            panel = pygame.Rect(18, VH - 70, 440, 52)
            draw_panel(canvas, panel, (*palette["panel"], 190),
                       palette["border"], 10, 1)
            weapon_key = local.get("weapon_class", "pulse")
            weapon_spec = WEAPONS.get(weapon_key, WEAPONS["pulse"])
            draw_text(canvas, self.resources, tr(self.language, "weapon"), 10,
                      palette["muted"], (32, VH - 64))
            draw_text(canvas, self.resources,
                      tr(self.language, weapon_spec["name"]), 14,
                      palette["accent"], (32, VH - 50))
            for index in range(3):
                color = (palette["accent"] if index < local.get("weapon", 1)
                         else (38, 48, 70))
                pygame.draw.rect(canvas, color, (32 + index * 22, VH - 30, 16, 6),
                                 border_radius=2)
            draw_text(canvas, self.resources, tr(self.language, "salvage"), 10,
                      palette["muted"], (panel.right - 18, VH - 64),
                      anchor="topright")
            draw_text(canvas, self.resources, str(snapshot.get("salvage", 0)), 22,
                      palette["warning"], (panel.right - 18, VH - 52),
                      anchor="topright")

        if self.pause_hint > 0:
            draw_text(canvas, self.resources, tr(self.language, "coop_pause_host"),
                      16, palette["warning"], (VW // 2, VH - 104),
                      anchor="center", alpha=220)

        announce = snapshot.get("announce")
        if (self.state in ("playing", "dying") and isinstance(announce, dict)
                and announce.get("text")):
            timer = float(announce.get("timer", 0.0))
            duration = max(0.001, float(announce.get("duration", 1.0)))
            progress = 1.0 - timer / duration
            alpha = int(255 * min(1.0, progress * 6.0, timer / 0.45))
            draw_text(canvas, self.resources, announce["text"], 46,
                      _color(announce.get("color"), palette["accent"]),
                      (VW // 2, VH * 0.30), anchor="center",
                      shadow=(2, 6, 16), alpha=alpha)
            if announce.get("sub"):
                draw_text(canvas, self.resources, announce["sub"], 20,
                          palette["text"], (VW // 2, VH * 0.30 + 44),
                          anchor="center", alpha=alpha)

    def _draw_superpower_shop(self, canvas, snapshot):
        points = max(0, int(snapshot.get("meme_points", 0)))
        charges = snapshot.get("superpower_charges") or {}
        items = (("tiger", "1", (255, 188, 66), 4000),
                 ("chainsaw", "2", (255, 112, 48), 1800))
        for index, (kind, key, color, cost) in enumerate(items):
            x = VW - 480 + index * 100
            rect = pygame.Rect(x, 14, 92, 54)
            charged = max(0, int(charges.get(kind, 0))) > 0
            ratio = (1.0 if charged else clamp(points / cost, 0.0, 1.0))
            border = color if charged or ratio >= 1.0 else self.palette["border"]
            draw_panel(canvas, rect, (*self.palette["panel"], 225), border,
                       8, 2 if charged else 1)
            draw_text(canvas, self.resources, key, 12, color,
                      (rect.x + 6, rect.y + 3))
            if kind == "tiger":
                pygame.draw.circle(canvas, color, (rect.centerx, rect.y + 22), 13)
                pygame.draw.polygon(canvas, color,
                                    ((rect.centerx - 10, rect.y + 15),
                                     (rect.centerx - 8, rect.y + 7),
                                     (rect.centerx - 2, rect.y + 14)))
                pygame.draw.polygon(canvas, color,
                                    ((rect.centerx + 10, rect.y + 15),
                                     (rect.centerx + 8, rect.y + 7),
                                     (rect.centerx + 2, rect.y + 14)))
            else:
                cy = rect.y + 22
                pygame.draw.rect(canvas, color,
                                 (rect.centerx - 17, cy - 6, 25, 12),
                                 border_radius=4)
                pygame.draw.circle(canvas, (218, 226, 230),
                                   (rect.centerx + 8, cy), 10, 3)
                for tooth in range(8):
                    angle = self.time * 8 + tooth * math.tau / 8
                    start = (rect.centerx + 8 + math.cos(angle) * 7,
                             cy + math.sin(angle) * 7)
                    end = (rect.centerx + 8 + math.cos(angle + .1) * 13,
                           cy + math.sin(angle + .1) * 13)
                    pygame.draw.line(canvas, color, start, end, 2)
            label_key = ("superpower_tiger" if kind == "tiger"
                         else "superpower_chainsaw")
            draw_text(canvas, self.resources, tr(self.language, label_key), 10,
                      self.palette["text"], (rect.centerx, rect.y + 31),
                      anchor="midtop")
            value = (f"x{max(0, int(charges.get(kind, 0)))}" if charged
                     else format_score(cost))
            draw_text(canvas, self.resources, value, 10,
                      color if charged or ratio >= 1.0 else self.palette["muted"],
                      (rect.right - 5, rect.y + 3), anchor="topright")
            draw_bar(canvas, (rect.x + 7, rect.bottom - 8, rect.width - 14, 5),
                     ratio, color, (28, 34, 54), None, 1)
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'meme_wallet')}: {format_score(points)}",
                  10, self.palette["muted"], (VW - 480, 69))

    def _draw_boss_bar(self, canvas, boss):
        palette = self.palette
        rect = pygame.Rect(VW // 2 - 280, 82, 560, 44)
        draw_panel(canvas, rect, (*palette["panel"], 220), palette["danger"],
                   10, 1)
        name_key = ("boss_sentinel" if boss.get("kind") == "sentinel"
                    else "boss_dreadnought")
        draw_text(canvas, self.resources, tr(self.language, name_key), 13,
                  palette["danger"], (rect.x + 16, rect.y + 5))
        draw_text(canvas, self.resources,
                  tr(self.language, "boss_phase", phase=boss.get("phase", 1)), 11,
                  palette["warning"], (rect.right - 16, rect.y + 6),
                  anchor="topright")
        hp = max(0.0, float(boss.get("hp", 0)))
        max_hp = max(1, int(boss.get("max_hp", 1)))
        draw_text(canvas, self.resources, f"{int(hp)} / {max_hp}", 11,
                  palette["muted"], (rect.right - 16, rect.y + 23),
                  anchor="topright")
        draw_bar(canvas, (rect.x + 14, rect.y + 27, rect.width - 120, 10),
                 hp / max_hp, palette["danger"], (34, 18, 28),
                 palette["border"], 3)

    def _draw_coop_panel(self, canvas, snapshot):
        palette = self.palette
        panel = pygame.Rect(VW - 358, 78, 340, 92)
        draw_panel(canvas, panel, (*palette["panel"], 205),
                   palette["border"], 10, 1)
        players = snapshot.get("players") or []
        for index, player in enumerate(players[:2]):
            y = panel.y + 10 + index * 40
            name = player.get("name") or (self.host_name if index == 0
                                          else self.local_name)
            role_key = "coop_p1" if index == 0 else "coop_p2"
            label = "%s  %s" % (tr(self.language, role_key), str(name)[:24])
            color = (palette["success"] if player.get("alive")
                     else palette["muted"])
            draw_text(canvas, self.resources, label, 11, color,
                      (panel.x + 12, y))
            for pip in range(min(7, max(0, int(player.get("life", 0))))):
                canvas.blit(self.resources.ship_small,
                            (panel.x + 150 + pip * 24, y - 2))
            if player.get("downed"):
                draw_text(canvas, self.resources,
                          tr(self.language, "coop_downed"), 11,
                          palette["danger"], (panel.x + 216, y))
                need = max(0.01, float(player.get("revive_need", 2.4)))
                progress = float(player.get("revive", 0.0)) / need
                draw_bar(canvas, (panel.x + 216, y + 14, 108, 4), progress,
                         palette["warning"], (28, 34, 54), None, 2)
            elif not player.get("alive"):
                draw_text(canvas, self.resources,
                          tr(self.language, "coop_respawning"), 10,
                          palette["muted"], (panel.x + 216, y))

    # ------------------------------------------------------------- overlays
    def _overlay(self, canvas, alpha=205):
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        overlay.fill((4, 5, 14, int(alpha)))
        canvas.blit(overlay, (0, 0))

    def _draw_waiting(self, canvas):
        self._overlay(canvas, 150)
        draw_text(canvas, self.resources, tr(self.language, "coop_waiting_first"),
                  26, self.palette["accent"], (VW // 2, VH // 2),
                  anchor="center")

    def _draw_story(self, canvas):
        palette = self.palette
        self._overlay(canvas, 224)
        panel = pygame.Rect(VW // 2 - 390, VH // 2 - 196, 780, 392)
        draw_panel(canvas, panel, (*palette["panel"], 246),
                   palette["accent"], 18, 2)
        story = (self.snapshot or {}).get("story") or {}
        key = story.get("key")
        text = tr(self.language, key) if key else ""
        draw_text(canvas, self.resources, tr(self.language, "story"), 13,
                  palette["muted"], (panel.x + 42, panel.y + 30))
        lines = self.resources.wrap_text(text, 24, panel.width - 84)
        y = panel.y + 92
        for line in lines[:6]:
            draw_text(canvas, self.resources, line, 24, palette["text"],
                      (panel.centerx, y), anchor="midtop", alpha=235)
            y += 34
        draw_text(canvas, self.resources,
                  f"{story.get('index', 1)} / {story.get('total', 1)}", 12,
                  palette["muted"], (panel.right - 42, panel.y + 30),
                  anchor="topright")
        draw_text(canvas, self.resources, tr(self.language, "coop_story_hint"),
                  13, palette["accent"], (panel.centerx, panel.bottom - 42),
                  anchor="center")

    def _draw_paused(self, canvas):
        palette = self.palette
        self._overlay(canvas, 185)
        draw_text(canvas, self.resources, tr(self.language, "coop_paused"), 38,
                  palette["warning"], (VW // 2, VH // 2 - 20), anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "coop_pause_host"),
                  16, palette["muted"], (VW // 2, VH // 2 + 34), anchor="center")

    def _draw_upgrade(self, canvas, snapshot):
        palette = self.palette
        self._overlay(canvas, 205)
        upgrade = (snapshot or {}).get("upgrade") or {}
        cx = VW // 2
        draw_text(canvas, self.resources, tr(self.language, "upgrade_title"), 38,
                  palette["warning"], (cx, 112), anchor="center",
                  shadow=(2, 6, 16))
        draw_text(canvas, self.resources, tr(self.language, "coop_upgrade_wait"),
                  15, palette["text"], (cx, 166), anchor="center")
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'salvage')}: {upgrade.get('salvage', 0)}",
                  18, palette["warning"], (cx, 196), anchor="center")
        card_w = 300
        gap = 22
        left = cx - (card_w * 3 + gap * 2) // 2
        for index, choice in enumerate((upgrade.get("choices") or [])[:3]):
            rect = pygame.Rect(left + index * (card_w + gap), 262, card_w, 290)
            key = choice.get("key", "damage")
            spec = UPGRADES.get(key, UPGRADES["damage"])
            color = spec["color"] if choice.get("affordable") else palette["muted"]
            draw_panel(canvas, rect, (18, 30, 58, 238), palette["border"], 14, 1)
            draw_text(canvas, self.resources, tr(self.language, spec["name"]), 20,
                      color, (rect.centerx, rect.y + 104), anchor="center")
            draw_text(canvas, self.resources,
                      tr(self.language, "upgrade_level",
                         level=choice.get("level", 1), max=spec["max"]), 11,
                      palette["muted"], (rect.centerx, rect.y + 126),
                      anchor="center")
            draw_text(canvas, self.resources, str(choice.get("cost", 0)), 20,
                      palette["warning"], (rect.centerx, rect.y + 168),
                      anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "coop_upgrade_wait"),
                  13, palette["muted"], (cx, 590), anchor="center")

    def _draw_result(self, canvas, victory):
        palette = self.palette
        self._overlay(canvas, 205)
        cx = VW // 2
        panel = pygame.Rect(cx - 360, VH // 2 - 250, 720, 520)
        draw_panel(canvas, panel, (*palette["panel"], 242),
                   palette["success"] if victory else palette["danger"], 18, 2)
        result = self.result or {}
        if victory:
            title = (tr(self.language, "mission_complete") if result.get("campaign")
                     else tr(self.language, "victory"))
            color = palette["success"]
        else:
            title = (tr(self.language, "mission_failed") if result.get("campaign")
                     else tr(self.language, "game_over"))
            color = palette["danger"]
        draw_text(canvas, self.resources, title, 36, color, (cx, panel.y + 34),
                  anchor="midtop", shadow=(2, 6, 16))
        if result.get("campaign_complete"):
            draw_text(canvas, self.resources, tr(self.language, "campaign_complete"),
                      18, palette["warning"], (cx, panel.y + 86), anchor="midtop")
        if result.get("campaign"):
            mission = result.get("mission")
            if mission:
                draw_text(canvas, self.resources, tr(self.language, mission), 14,
                          palette["muted"], (cx, panel.y + 112), anchor="midtop")
        rows = [
            ("coop_result_score", format_score(result.get("score", 0))),
            ("coop_result_kills", str(result.get("kills", 0))),
            ("coop_result_time", format_time(result.get("time", 0.0))),
            ("coop_result_wave", str(result.get("wave", 0))),
        ]
        y = panel.y + 144
        for key, value in rows:
            draw_text(canvas, self.resources, tr(self.language, key), 13,
                      palette["muted"], (panel.x + 70, y))
            draw_text(canvas, self.resources, value, 22, palette["text"],
                      (panel.right - 70, y - 3), anchor="topright")
            y += 42
        summary = result.get("summary")
        if isinstance(summary, dict) and summary.get("first_completion"):
            draw_text(canvas, self.resources,
                      tr(self.language, "campaign_reward_first",
                         salvage=summary.get("salvage_bonus", 0)),
                      13, palette["warning"], (cx, panel.y + 336),
                      anchor="midtop")
        elif victory and result.get("campaign") and summary is not None:
            draw_text(canvas, self.resources,
                      tr(self.language, "campaign_reward_replay"), 13,
                      palette["muted"], (cx, panel.y + 336), anchor="midtop")
        if victory:
            hint = tr(self.language, "coop_end_hint")
        else:
            hint = tr(self.language, "coop_client_ended")
        draw_text(canvas, self.resources, hint, 12, palette["muted"],
                  (cx, panel.y + 366), anchor="midtop")

        first = (cx - 170, panel.y + 404, 340, 46)
        second = (cx - 170, panel.y + 456, 340, 40)
        self._overlay_buttons = [
            (pygame.Rect(first), tr(self.language, "coop_end_session"),
             "leave_session"),
            (pygame.Rect(second), tr(self.language, "main_menu"),
             "main_menu"),
        ]
        for rect, label, _action in self._overlay_buttons:
            hovered = rect.collidepoint(self.app.mouse)
            draw_panel(canvas, rect,
                       (24, 44, 74, 235) if hovered else (18, 30, 58, 210),
                       palette["accent"] if hovered else palette["border"], 10,
                       2 if hovered else 1)
            draw_text(canvas, self.resources, label, 17,
                      palette["accent"] if hovered else palette["text"],
                      rect.center, anchor="center")

    def _draw_disconnected(self, canvas):
        palette = self.palette
        self._overlay(canvas, 214)
        cx = VW // 2
        panel = pygame.Rect(cx - 340, VH // 2 - 190, 680, 380)
        draw_panel(canvas, panel, (*palette["panel"], 246),
                   palette["danger"], 18, 2)
        draw_text(canvas, self.resources, tr(self.language, "coop_disconnected"),
                  34, palette["danger"], (cx, panel.y + 40), anchor="midtop")
        draw_text(canvas, self.resources,
                  self.disconnect_reason or tr(self.language, "coop_link_lost"),
                  15, palette["text"], (cx, panel.y + 94), anchor="midtop")
        draw_text(canvas, self.resources, tr(self.language, "coop_reconnect_hint"),
                  12, palette["muted"], (cx, panel.y + 136), anchor="midtop")
        draw_text(canvas, self.resources, tr(self.language, "coop_end_hint"),
                  12, palette["muted"], (cx, panel.y + 166), anchor="midtop")

        first = (cx - 170, panel.y + 224, 340, 46)
        second = (cx - 170, panel.y + 280, 340, 40)
        self._overlay_buttons = [
            (pygame.Rect(first), tr(self.language, "coop_end_session"),
             "leave_session"),
            (pygame.Rect(second), tr(self.language, "main_menu"),
             "main_menu"),
        ]
        for rect, label, _action in self._overlay_buttons:
            hovered = rect.collidepoint(self.app.mouse)
            draw_panel(canvas, rect,
                       (24, 44, 74, 235) if hovered else (18, 30, 58, 210),
                       palette["accent"] if hovered else palette["border"], 10,
                       2 if hovered else 1)
            draw_text(canvas, self.resources, label, 17,
                      palette["accent"] if hovered else palette["text"],
                      rect.center, anchor="center")

    def _draw_local_menu(self, canvas):
        palette = self.palette
        self._overlay(canvas, 170)
        cx = VW // 2
        panel = pygame.Rect(cx - 260, VH // 2 - 140, 520, 280)
        draw_panel(canvas, panel, (*palette["panel"], 244),
                   palette["accent"], 16, 2)
        draw_text(canvas, self.resources, tr(self.language, "coop_leaving"), 28,
                  palette["warning"], (cx, panel.y + 32), anchor="midtop")
        draw_text(canvas, self.resources, tr(self.language, "coop_pause_host"),
                  12, palette["muted"], (cx, panel.y + 78), anchor="midtop")
        first = (cx - 170, panel.y + 116, 340, 46)
        second = (cx - 170, panel.y + 174, 340, 40)
        self._overlay_buttons = [
            (pygame.Rect(first), tr(self.language, "coop_resume_view"),
             "close_local_menu"),
            (pygame.Rect(second), tr(self.language, "coop_leave"),
             "leave_session"),
        ]
        for rect, label, _action in self._overlay_buttons:
            hovered = rect.collidepoint(self.app.mouse)
            draw_panel(canvas, rect,
                       (24, 44, 74, 235) if hovered else (18, 30, 58, 210),
                       palette["accent"] if hovered else palette["border"], 10,
                       2 if hovered else 1)
            draw_text(canvas, self.resources, label, 17,
                      palette["accent"] if hovered else palette["text"],
                      rect.center, anchor="center")
