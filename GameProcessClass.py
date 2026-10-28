"""Main gameplay scene: player, enemies, projectiles, hazards and HUD.

The run is built from the data in :mod:`GameData`: the selected ship picks a
weapon class, waves rotate through space zones, bosses have three phases and
cleared waves can offer permanent-for-the-run salvage upgrades.
"""

from __future__ import annotations

import math
import random

import pygame

from BulletClass import Bullet, EnemyBullet
from Balance import Balance, BalanceMetrics
from CampaignData import mission_by_id
from EffectsClass import Effects, ScreenShake
from EnemyAsteroidClass import BossEnemy, EnemyAsteroid, EnemyShip
from GameData import (SHIPS, UPGRADES, UPGRADE_ORDER, WEAPONS, ZONES,
                      boss_kind_for_wave, upgrade_available, upgrade_cost,
                      zone_for_wave, zone_index_for_wave)
from Hazards import BeamAttack, DangerZone
from Localization import meme_taunt, tr
from PowerUpClass import PowerUp
from ResourcesClass import palette_for
from SpaceBackdrop import SpaceBackdrop
from UIClass import Button, WidgetGroup, draw_bar, draw_panel, draw_text
from UserShipClass import UserShip
from utils import (VH, VW, circle_hit, clamp, format_score, format_time,
                   lerp, segment_circle_hit)


class GameProcess:
    WAVE_DURATION = 24.0
    MAX_ENEMIES = 18
    MAX_PLAYER_BULLETS = 90
    MAX_ENEMY_BULLETS = 240
    MAX_POWERUPS = 9

    SALVAGE_REWARD = {
        "asteroid": 1,
        "scout": 2,
        "fighter": 3,
        "bomber": 4,
        "raider": 3,
        "elite": 6,
    }

    def __init__(self, app, mode="normal", difficulty=None, mission=None,
                 progress=None):
        self.app = app
        self.mode = mode if mode in ("normal", "meme") else "normal"
        self.settings = app.settings
        self.resources = app.resources
        self.audio = app.audio
        self.language = self.settings.language
        self.palette = palette_for(self.mode)
        self.isRunMainLoop = True
        self.difficulty = difficulty or getattr(self.settings, "difficulty", "normal")
        self.balance = Balance(self.difficulty)
        self.metrics = BalanceMetrics()

        # A campaign mission is a plain data dict from CampaignData.  It only
        # changes the wave plan, enemy pool and win condition; every combat
        # system below is shared with endless mode.
        self.campaign_mission = mission if isinstance(mission, dict) else None
        self.campaign = self.campaign_mission is not None
        self.campaign_progress = progress if self.campaign else None
        self.campaign_result = None
        self.story_keys = (tuple(self.campaign_mission.get("story", ()))
                           if self.campaign else ())
        self.story_index = 0
        self.story_time = 0.0

        self.world = pygame.Surface((VW, VH)).convert()
        start_zone = (self.campaign_mission["zone"] if self.campaign
                      else zone_index_for_wave(1))
        self.backdrop = SpaceBackdrop(
            self.resources, self.mode, zone=start_zone,
            seed=random.randint(1, 99999),
            quality=getattr(self.settings, "effects_quality", 2),
        )
        self.zone_id = self.backdrop.zone["id"]
        self.effects = Effects(self.resources,
                               quality=getattr(self.settings, "effects_quality", 2),
                               reduced_flash=getattr(self.settings, "reduced_flash", False))
        self.shake = ScreenShake()

        self.ship_kind = getattr(self.settings, "ship", "fighter")
        if self.ship_kind not in SHIPS:
            self.ship_kind = "fighter"
        self.player = UserShip(
            VW * 0.5 - 39, VH - 178, VW, VH,
            imageList=self.resources.ship_frames_for(self.ship_kind),
            imageBoomList=self.resources.boom_sources,
            kind=self.ship_kind,
        )
        self.player_bullets = []
        self.enemy_bullets = []
        self.enemies = []
        self.powerups = []
        self.danger_zones = []
        self.beams = []
        self.boss = None
        self.boss_drop_flags = {}

        self.score = 0.0
        self.display_score = 0.0
        self.kills = 0
        self.salvage = (self.campaign_progress.salvage_bonus
                        if self.campaign else 0)
        self.wave = 1
        self.game_time = 0.0
        self.best_before = app.leaderboard.best(self.mode)
        if self.campaign and self.campaign_progress is not None:
            best = self.campaign_progress.best_for(self.campaign_mission["id"])
            self.best_before = int(best.get("score", 0)) if best else 0
        self.result = None

        self.spawn_timer = 1.15
        self.spawn_grace = 0.0
        self.wave_timer = 0.0
        self.combo_chain = 0
        self.combo_timer = 0.0
        self.multiplier = 1
        self.engine_accum = 0.0
        self.time = 0.0
        self.info_timer = 11.0
        self.state = "playing"
        self.death_timer = 0.0
        self.overlay_time = 0.0
        self.pause_group = None
        self.over_group = None
        self.victory_group = None
        self.announce_text = None
        self.announce_sub = None
        self.announce_color = self.palette["accent"]
        self.announce_timer = 0.0
        self.announce_duration = 1.0
        self.taunt_text = None
        self.taunt_timer = 0.0
        self.meme_index = 0
        self.pending_asteroids = []
        self.input_override = None  # (move_x, move_y, firing) for automated tests
        self.enemy_bullet_color = self.palette["enemy_bullet"]
        self.enemy_bullet_sprite = self.resources.enemy_bullet(self.mode)
        self.music_started = False
        self.hide_cursor = True

        self.upgrade_choices = []
        self.upgrade_focus = 0

        self._announce(tr(self.language, "wave_announce", wave=self.wave),
                       self.palette["accent"], 2.4)

        if self.campaign and self.story_keys:
            self.state = "story"

    @property
    def total_waves(self):
        if self.campaign:
            return max(1, int(self.campaign_mission.get("waves", 1)))
        return None

    # ------------------------------------------------------------ lifecycle
    def on_enter(self):
        self.audio.play_music("game", self.mode)
        self.music_started = True

    def on_exit(self):
        self.audio.stop_music()

    def _restart(self):
        self.audio.play("ui_click", 0.5)
        if self.campaign:
            self.app.start_campaign(self.campaign_mission["id"], self.mode,
                                    self.difficulty)
        else:
            self.app.start_game(self.mode)

    def _to_menu(self):
        self.audio.play("ui_click", 0.5)
        if self.campaign:
            self.app.go_campaign()
        else:
            self.app.go_menu()

    def _handle_action(self, action):
        if not action:
            return
        if action == "resume":
            self._resume()
        elif action == "restart":
            self._restart()
        elif action == "menu":
            if self.campaign:
                self.app.go_campaign()
            else:
                self._to_menu()
        elif action == "campaign_menu":
            self.audio.play("ui_click", 0.5)
            self.app.go_campaign()
        elif action == "campaign_main":
            self.audio.play("ui_click", 0.5)
            self.app.go_menu()
        elif action == "campaign_next":
            summary = self.campaign_result or {}
            next_id = summary.get("next_mission")
            if next_id:
                self.audio.play("ui_click", 0.5)
                self.app.start_campaign(next_id, self.mode, self.difficulty)
        elif action == "campaign_replay":
            self._restart()

    # ---------------------------------------------------------------- input
    def handle_event(self, event, mouse=None):
        mouse = mouse or self.app.mouse
        if event.type == pygame.QUIT:
            self.app.quit()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.app.toggle_fullscreen()
            return
        if (event.type == getattr(pygame, "WINDOWFOCUSLOST", -1)
                and getattr(self.settings, "auto_pause", True)):
            if self.state == "playing":
                self._pause()
            return

        if self.state == "story":
            self._handle_story_event(event, mouse)
            return

        if self.state == "upgrade":
            self._handle_upgrade_event(event, mouse)
            return

        if self.state == "paused":
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_p):
                    self._resume()
                    return
                if event.key == pygame.K_r:
                    self._restart()
                    return
                if event.key == pygame.K_m:
                    self._to_menu()
                    return
            action = self.pause_group.handle_event(event, mouse) if self.pause_group else None
            self._handle_action(action)
            return

        if self.state == "victory":
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_n):
                    self._handle_action("campaign_next")
                    return
                if event.key == pygame.K_r:
                    self._restart()
                    return
                if event.key in (pygame.K_ESCAPE, pygame.K_m):
                    self.app.go_campaign()
                    return
            action = self.victory_group.handle_event(event, mouse) if self.victory_group else None
            self._handle_action(action)
            return

        if self.state == "gameover":
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_r):
                    self._restart()
                    return
                if event.key in (pygame.K_ESCAPE, pygame.K_m):
                    self._to_menu()
                    return
            action = self.over_group.handle_event(event, mouse) if self.over_group else None
            self._handle_action(action)
            return

        if self.state in ("playing", "dying"):
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_p):
                    if self.state == "playing":
                        self._pause()
                    return
                if event.key == pygame.K_m and self.state == "dying":
                    self._to_menu()

    # ------------------------------------------------------------- updates
    def _read_input(self):
        if self.input_override is not None:
            return self.input_override
        keys = pygame.key.get_pressed()
        move_x = 0.0
        move_y = 0.0
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            move_x += 1.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            move_x -= 1.0
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            move_y += 1.0
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            move_y -= 1.0
        firing = bool(keys[pygame.K_SPACE])
        return move_x, move_y, firing

    def _update_player(self, dt):
        move_x, move_y, firing = self._read_input()
        events = self.player.update(dt, move_x, move_y)
        for event_name in events:
            if event_name == "weapon_expired":
                self.effects.text(
                    tr(self.language, "weapon_expired"),
                    self.player.centerx, self.player.posY - 18,
                    self.palette["warning"], 15, 1.4,
                )
            elif event_name == "shield_expired":
                self.effects.text(
                    tr(self.language, "shield_expired"),
                    self.player.centerx, self.player.posY - 18,
                    self.palette["muted"], 15, 1.3,
                )
            elif event_name == "rapid_expired":
                self.effects.text(
                    tr(self.language, "rapid_expired"),
                    self.player.centerx, self.player.posY - 18,
                    self.palette["muted"], 15, 1.3,
                )
            elif event_name == "respawned":
                self.effects.ring(self.player.centerx, self.player.centery,
                                  self.palette["accent"], 72, 0.7, 3)
                self.effects.pickup(self.player.centerx, self.player.centery,
                                    self.palette["accent"])
                self.audio.play("shield", 0.6)

        if firing and self.player.alive:
            self._try_fire()

        if self.player.alive:
            self.engine_accum += dt
            flame = self.palette["accent"] if self.mode == "normal" else self.palette["accent2"]
            while self.engine_accum >= 0.024:
                self.engine_accum -= 0.024
                self.effects.engine(
                    self.player.centerx + random.uniform(-5, 5),
                    self.player.posY + self.player.height - 6,
                    flame, 0.85 + max(0.0, -self.player.vy) / 500.0,
                )
            if self.player.shield_timer > 0 and random.random() < 0.16:
                angle = random.uniform(0, math.tau)
                self.effects.trail(
                    self.player.centerx + math.cos(angle) * 44,
                    self.player.centery + math.sin(angle) * 44,
                    self.palette["accent"],
                )
        else:
            self.engine_accum = 0.0

        # Safety net: a dead player with zero lives must always end the run.
        if not self.player.alive and self.player.life <= 0 and self.state == "playing":
            self.state = "dying"
            self.death_timer = 1.8

    def _try_fire(self):
        shots = self.player.fire_volley()
        if not shots:
            return
        weapon = WEAPONS.get(self.player.weapon_class, WEAPONS["pulse"])
        color = weapon["color"] if self.mode == "normal" else self.palette["bullet"]
        sprite = self.resources.bullet_sprite("player_" + self.player.weapon_class,
                                              self.mode)
        for shot in shots:
            if len(self.player_bullets) >= self.MAX_PLAYER_BULLETS:
                self.player_bullets.pop(0)
            self.player_bullets.append(Bullet(
                shot.x, shot.y, sprite=sprite, vx=shot.vx, vy=shot.vy,
                radius=shot.radius, damage=shot.damage, color=color,
                kind=shot.kind, pierce=shot.pierce, splash=shot.splash,
            ))
        self.effects.muzzle(
            self.player.centerx, self.player.posY + 2, color,
            angle=-math.pi / 2, intensity=0.7,
        )
        self.audio.play(weapon.get("sound", "shot"), 0.38, throttle_ms=45)
        if self.mode == "meme" and random.random() < 0.2:
            self.audio.play("meme_boing", 0.12, throttle_ms=180)

    def _update_bullets(self, dt):
        for bullet in self.player_bullets:
            bullet.update(dt)
        self.player_bullets = [
            bullet for bullet in self.player_bullets
            if bullet.alive and not bullet.is_outside(VW, VH)
        ]
        for bullet in self.enemy_bullets:
            bullet.update(dt)
        self.enemy_bullets = [
            bullet for bullet in self.enemy_bullets
            if bullet.alive and not bullet.is_outside(VW, VH)
        ]

    def _update_enemies(self, dt):
        for enemy in self.enemies:
            if enemy.alive:
                enemy.update(dt, self)
        if self.boss is not None:
            for event_name in self.boss.update(dt, self):
                self._handle_boss_event(event_name)
        self.enemies = [enemy for enemy in self.enemies if enemy.alive]
        if len(self.enemies) > self.MAX_ENEMIES:
            del self.enemies[self.MAX_ENEMIES:]

    def _handle_boss_event(self, event_name):
        if event_name in ("phase2", "phase3"):
            phase = int(event_name[-1])
            self._announce(
                tr(self.language, "boss_phase", phase=phase),
                self.palette["warning"] if phase == 2 else self.palette["danger"],
                2.4, sub=tr(self.language, "boss_phase_hint"),
            )
            self.audio.play("boss_phase", 0.75)
            self.shake.add(0.35)
        elif event_name == "beam":
            self.audio.play("boss_warn", 0.45, throttle_ms=260)
        elif event_name == "zones":
            self.audio.play("boss_warn", 0.4, throttle_ms=240)
        elif event_name == "minions":
            self._announce(tr(self.language, "boss_minions"), self.palette["warning"],
                           1.8)

    def _update_hazards(self, dt):
        for zone in self.danger_zones:
            zone.update(dt)
        for beam in self.beams:
            beam.update(dt)
        self.danger_zones = [zone for zone in self.danger_zones if zone.alive]
        self.beams = [beam for beam in self.beams if beam.alive]
        self.metrics.note_hazards(len(self.danger_zones), len(self.beams))

    def _update_powerups(self, dt):
        for powerup in self.powerups:
            powerup.update(dt, self.player)
        self.powerups = [powerup for powerup in self.powerups if powerup.alive]

    def _update_combo(self, dt):
        if self.combo_timer > 0:
            self.combo_timer = max(0.0, self.combo_timer - dt)
            if self.combo_timer <= 0:
                self.combo_chain = 0
                self.multiplier = 1

    def _update_announcements(self, dt):
        if self.announce_timer > 0:
            self.announce_timer = max(0.0, self.announce_timer - dt)
        if self.taunt_timer > 0:
            self.taunt_timer = max(0.0, self.taunt_timer - dt)
        if self.info_timer > 0:
            self.info_timer = max(0.0, self.info_timer - dt)

    # ---------------------------------------------------------------- story
    def _handle_story_event(self, event, mouse):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_s, pygame.K_ESCAPE):
                self._skip_story()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER,
                               pygame.K_SPACE, pygame.K_RIGHT, pygame.K_d):
                self._advance_story()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._advance_story()

    def _advance_story(self):
        self.story_index += 1
        self.story_time = 0.0
        if self.story_index >= len(self.story_keys):
            self._end_story()
        else:
            self.audio.play("ui_click", 0.4)

    def _skip_story(self):
        self.audio.play("ui_click", 0.5)
        self._end_story()

    def _end_story(self):
        if self.state != "story":
            return
        self.state = "playing"
        self.story_index = len(self.story_keys)
        mission = self.campaign_mission or {}
        if mission.get("boss"):
            objective = tr(self.language, "mission_objective_boss",
                           waves=self.total_waves)
        else:
            objective = tr(self.language, "mission_objective_survive",
                           waves=self.total_waves)
        self._announce(tr(self.language, mission.get("name_key", "campaign_title")),
                       self.palette["accent"], 3.0, sub=objective)
        self.audio.play("wave", 0.7)

    def _update_waves(self, dt):
        if self.boss is not None:
            return
        self.wave_timer += dt
        if self.wave_timer < self.WAVE_DURATION:
            return
        self.wave_timer = 0.0
        self.metrics.note_wave(self.wave, self.WAVE_DURATION)

        if self.campaign:
            mission = self.campaign_mission
            if self.wave >= self.total_waves:
                if mission.get("boss"):
                    self._spawn_boss()
                else:
                    self._complete_mission()
                return
            self.wave += 1
            self._announce(
                tr(self.language, "wave_announce", wave=self.wave),
                self.palette["accent"], 2.4,
                sub=tr(self.language, mission["name_key"]),
            )
            self.audio.play("wave", 0.6)
            start_kind = ("shield" if self.player.life <= 1 else
                          random.choice(("weapon", "shield", "rapid")))
            self._spawn_powerup(
                random.uniform(160, VW - 160), 120, start_kind,
            )
            # Campaign missions are short, so every cleared wave offers an
            # upgrade instead of every third endless wave.
            self._open_upgrade()
            return

        self.wave += 1
        self._sync_zone(announce=True)
        if self.wave % 5 == 0:
            self._spawn_boss()
            return
        self._announce(
            tr(self.language, "wave_announce", wave=self.wave),
            self.palette["accent"], 2.4,
        )
        self.audio.play("wave", 0.6)
        if self.player.alive and self.player.life <= 1:
            start_kind = random.choice(("shield", "life"))
        else:
            start_kind = random.choice(("weapon", "shield", "rapid"))
        self._spawn_powerup(
            random.uniform(160, VW - 160), 120, start_kind,
        )
        if self.wave % 3 == 0:
            self._open_upgrade()

    def _sync_zone(self, announce=False):
        if self.campaign:
            return
        index = zone_index_for_wave(self.wave)
        zone = ZONES[index]
        if zone["id"] == self.zone_id:
            return
        self.zone_id = zone["id"]
        self.backdrop.set_zone(index, fade=True)
        if announce:
            self._announce(tr(self.language, zone["name"]), zone["accent"], 2.8,
                           sub=tr(self.language, "zone_enter"))
            self.audio.play("wave", 0.5)

    def update(self, dt):
        if self.state == "paused":
            return
        dt = min(max(dt, 0.0), 0.05)
        self.time += dt
        if self.settings.screen_shake:
            self.shake.update(dt)
        else:
            self.shake.trauma = 0.0
            self.shake.offset_x = self.shake.offset_y = 0.0
        self.display_score = lerp(self.display_score, self.score, min(1.0, dt * 9.0))

        boost = max(0.0, -self.player.vy)
        time_scale = 0.35 if self.state == "gameover" else 1.0
        self.backdrop.update(dt * time_scale, boost * 0.7)
        self.effects.update(dt * (0.55 if self.state == "gameover" else 1.0))
        self._update_hazards(dt * time_scale)

        if self.state == "story":
            self.story_time += dt
            self._update_announcements(dt)
            return
        if self.state == "upgrade":
            self._update_announcements(dt)
            return
        if self.state == "gameover":
            self.overlay_time += dt
            return
        if self.state == "dying":
            self.death_timer -= dt
            self._update_announcements(dt)
            if self.death_timer <= 0:
                self._finalize_game_over()
            return

        # playing
        self.game_time += dt
        self._update_player(dt)
        self._update_bullets(dt)
        self._update_enemies(dt)
        self._update_powerups(dt)
        self._update_collisions()
        self._update_combo(dt)
        self._update_announcements(dt)
        if self.state == "playing":
            self._update_waves(dt)
        if self.state == "playing":
            self.spawn_timer -= dt
            if self.spawn_grace > 0:
                self.spawn_grace = max(0.0, self.spawn_grace - dt)
            elif self.spawn_timer <= 0 and self.boss is None:
                self._spawn_enemy()
                self.spawn_timer = self._spawn_interval()

    # ------------------------------------------------------------- spawning
    def _spawn_interval(self):
        base = self.balance.spawn_interval(self.wave)
        return base * random.uniform(0.82, 1.18)

    def _spawn_enemy(self):
        if self.boss is not None or len(self.enemies) >= self.MAX_ENEMIES:
            return
        roll = random.random()
        if self.campaign:
            mission = self.campaign_mission
            pool = [kind for kind in mission.get("enemies", ("scout",))
                    if kind != "asteroid"]
            if not pool:
                pool = ["scout"]
            elite_cap = max(0, int(mission.get("max_elites", 1)))
            elites = sum(1 for enemy in self.enemies
                         if getattr(enemy, "kind", "") == "elite")
            if elites >= elite_cap:
                pool = [kind for kind in pool if kind != "elite"] or ["scout"]
            ratio = clamp(float(mission.get("asteroid_ratio", 0.3)), 0.0, 1.0)
            kind = "asteroid" if roll < ratio else random.choice(pool)
            if kind == "asteroid":
                self._spawn_asteroid()
            else:
                self._spawn_ship(kind)
            return
        zone = zone_for_wave(self.wave)
        if self.wave <= 1:
            kind = "asteroid"
        elif self.wave == 2:
            kind = "asteroid" if roll < 0.72 else "scout"
        else:
            pool = [kind for kind in zone["enemies"] if kind != "asteroid"]
            if self.wave < 4:
                pool = [kind for kind in pool if kind in ("scout", "fighter")]
            if self.wave < 8:
                # Elites arrive after the first boss recovery window, never
                # during the wave that follows it.
                pool = [kind for kind in pool if kind != "elite"]
            else:
                elite_cap = 2 if self.wave >= 15 else 1
                elites = sum(1 for enemy in self.enemies
                             if getattr(enemy, "kind", "") == "elite")
                if elites >= elite_cap:
                    pool = [kind for kind in pool if kind != "elite"]
            if not pool:
                pool = ["scout"]
            kind = "asteroid" if roll < 0.30 else random.choice(pool)
        if kind == "asteroid":
            self._spawn_asteroid()
        else:
            self._spawn_ship(kind)

    def _spawn_asteroid(self, x=None, y=None, level=None, radius=None,
                        rot_index=None, defer=False):
        if len(self.enemies) >= self.MAX_ENEMIES + 4:
            return None
        if level is None:
            level = "large" if random.random() < 0.38 else "small"
        if radius is None:
            radius = random.randint(30, 48) if level == "large" else random.randint(17, 25)
        index = (rot_index if rot_index is not None
                 else random.randrange(len(self.resources.asteroid_sources)))
        image = self.resources.asteroid(index, radius)
        asteroid = EnemyAsteroid(
            VW, VH, image, None, x=x, y=y, radius=radius,
            speed_scale=self.balance.asteroid_speed(self.wave), level=level,
            resources=self.resources, rot_index=index,
        )
        if not defer:
            self.enemies.append(asteroid)
        self.metrics.note_spawn("asteroid", at=self.game_time)
        return asteroid

    def _spawn_ship(self, kind, x=None, y=-70, wave=None):
        if len(self.enemies) >= self.MAX_ENEMIES:
            return None
        ship = EnemyShip(kind, self.mode, self.resources, x=x, y=y,
                         wave=wave if wave is not None else self.wave,
                         balance=self.balance)
        self.enemies.append(ship)
        self.metrics.note_spawn(kind, at=self.game_time)
        return ship

    def _spawn_boss(self):
        if self.boss is not None:
            return
        for enemy in self.enemies:
            if enemy.alive:
                self.effects.explosion(enemy.posX, enemy.posY,
                                       self.palette["particle"], count=10, speed=140)
                enemy.alive = False
        self.enemies.clear()
        self.enemy_bullets.clear()
        self.danger_zones.clear()
        self.beams.clear()
        if self.campaign:
            mission = self.campaign_mission
            kind = mission.get("boss") or boss_kind_for_wave(self.wave)
            boss_wave = int(mission.get("boss_wave", self.wave))
            self.boss = BossEnemy(self.mode, self.resources, boss_wave,
                                  kind=kind, balance=self.balance)
            scale = max(0.25, float(mission.get("boss_scale", 1.0)))
            if abs(scale - 1.0) > 1e-6:
                self.boss.max_hp = max(1, int(round(self.boss.max_hp * scale)))
                self.boss.hp = self.boss.max_hp
        else:
            self.boss = BossEnemy(self.mode, self.resources, self.wave,
                                  kind=boss_kind_for_wave(self.wave),
                                  balance=self.balance)
        self.metrics.note_boss()
        self.boss_drop_flags = {0.66: False, 0.33: False}
        warning_key = ("boss_warning_sentinel" if self.boss.kind == "sentinel"
                       else "boss_warning")
        self._announce(tr(self.language, warning_key), self.palette["danger"], 3.6,
                       sub=tr(self.language, self.boss.name_key))
        self.audio.play("boss_warn", 0.8)
        self.audio.play("wave", 0.5)
        self.shake.add(0.55)

    def spawn_boss_minions(self, boss):
        offsets = (-130, 130)
        for offset in offsets:
            self._spawn_ship("scout", x=clamp(boss.posX + offset, 80, VW - 80),
                             y=boss.posY, wave=self.wave)
        if boss.phase >= 3:
            self._spawn_ship("elite", x=clamp(boss.posX, 100, VW - 100),
                             y=boss.posY, wave=self.wave)
        self.effects.ring(boss.posX, boss.posY, self.palette["danger"], 180, 0.7, 4)
        self.audio.play("boss_warn", 0.35, throttle_ms=300)

    def _spawn_powerup(self, x, y, kind):
        if len(self.powerups) >= self.MAX_POWERUPS:
            return
        self.powerups.append(PowerUp(
            clamp(x, 30, VW - 30), clamp(y, 90, VH - 80),
            kind, self.mode, self.resources,
        ))
        self.metrics.note_powerup(kind)

    def _maybe_drop(self, enemy):
        chance = {
            "asteroid": 0.10,
            "scout": 0.13,
            "fighter": 0.2,
            "bomber": 0.34,
            "raider": 0.22,
            "elite": 0.55,
        }.get(enemy.kind, 0.1)
        chance = self.balance.drop_chance(chance)
        # Low-health pity: a struggling player gets a real chance at a shield
        # or an extra hull instead of purely random weapon drops.
        if (self.player.alive and self.player.life <= 1
                and self.player.shield_timer <= 0):
            chance = min(0.9, chance + 0.12)
            if random.random() < 0.35:
                self._spawn_powerup(enemy.posX, enemy.posY,
                                    random.choice(("shield", "life")))
                return
        if random.random() < chance:
            self._spawn_powerup(enemy.posX, enemy.posY, PowerUp.random_kind())

    # ------------------------------------------------------------ collisions
    def _bullet_hit_target(self, bullet, target):
        if not target.alive or id(target) in bullet.hits:
            return False
        if not segment_circle_hit(
            bullet.prev_x, bullet.prev_y, bullet.posX, bullet.posY,
            target.posX, target.posY, target.hit_radius + bullet.radius,
        ):
            return False
        bullet.hits.add(id(target))
        killed = target.damage(bullet.damage)
        spark_color = (self.palette["warning"] if target.kind == "boss"
                       else self.palette["bullet"])
        self.effects.hit_sparks(bullet.posX, bullet.posY, spark_color, count=5)
        if bullet.pierce > 0:
            bullet.pierce -= 1
        else:
            bullet.alive = False
        return killed

    def _apply_splash(self, bullet, origin):
        if bullet.splash <= 0:
            return
        for enemy in self.enemies:
            if not enemy.alive or enemy is origin:
                continue
            if circle_hit(enemy.posX, enemy.posY, enemy.hit_radius,
                          origin.posX, origin.posY, bullet.splash):
                if enemy.damage(bullet.damage * 0.5):
                    self._kill_enemy(enemy)
        if self.boss is not None and self.boss.alive and self.boss is not origin:
            if circle_hit(self.boss.posX, self.boss.posY, self.boss.hit_radius,
                          origin.posX, origin.posY, bullet.splash):
                if self.boss.damage(bullet.damage * 0.5):
                    self._defeat_boss()

    def _update_collisions(self):
        # Player bullets vs regular enemies.
        for enemy in self.enemies:
            if not enemy.alive:
                continue
            for bullet in self.player_bullets:
                if not bullet.alive:
                    continue
                if self._bullet_hit_target(bullet, enemy):
                    self._apply_splash(bullet, enemy)
                    self._kill_enemy(enemy)
                if not bullet.alive:
                    break

        # Player bullets vs boss.
        if self.boss is not None:
            boss = self.boss
            for bullet in self.player_bullets:
                if not bullet.alive:
                    continue
                if self._bullet_hit_target(bullet, boss):
                    self._apply_splash(bullet, boss)
                    self._defeat_boss()
                    break
                ratio = boss.hp / max(1, boss.max_hp)
                for threshold in (0.66, 0.33):
                    if not self.boss_drop_flags.get(threshold, True) and ratio <= threshold:
                        self.boss_drop_flags[threshold] = True
                        self._spawn_powerup(
                            boss.posX + random.uniform(-70, 70),
                            boss.posY + 50,
                            "weapon" if threshold > 0.5 else "shield",
                        )
                        self.effects.text(
                            tr(self.language, "powerup_hint"),
                            boss.posX, boss.posY + 90,
                            self.palette["warning"], 16, 1.3,
                        )

        # Enemy bullets vs player.
        if self.player.alive:
            for bullet in self.enemy_bullets:
                if not bullet.alive:
                    continue
                if segment_circle_hit(
                    bullet.prev_x, bullet.prev_y, bullet.posX, bullet.posY,
                    self.player.centerx, self.player.centery,
                    self.player.hit_radius + bullet.radius,
                ):
                    bullet.alive = False
                    result = self._player_hit()
                    if result != "none":
                        break

        # Telegraphed hazards.
        if self.player.alive:
            for zone in self.danger_zones:
                if zone.active and not zone.hit_player and zone.contains(
                    self.player.centerx, self.player.centery,
                    self.player.hit_radius * 0.45,
                ):
                    zone.hit_player = True
                    if self._player_hit() != "none":
                        break
            if self.player.alive:
                for beam in self.beams:
                    if not beam.hit_player and beam.hits(
                        self.player.centerx, self.player.centery,
                        self.player.hit_radius * 0.7,
                    ):
                        beam.hit_player = True
                        if self._player_hit() != "none":
                            break

        # Contact damage.
        if self.player.alive:
            for enemy in self.enemies:
                if not enemy.alive:
                    continue
                if circle_hit(self.player.centerx, self.player.centery,
                              self.player.hit_radius, enemy.posX, enemy.posY,
                              enemy.hit_radius):
                    result = self._player_hit()
                    if result in ("shield", "dead"):
                        self._kill_enemy(enemy, award=(result == "shield"))
                        if self.state != "playing":
                            break
            if self.boss is not None and self.player.alive:
                if circle_hit(self.player.centerx, self.player.centery,
                              self.player.hit_radius, self.boss.posX, self.boss.posY,
                              self.boss.hit_radius):
                    self._player_hit()

        # Power-ups.
        if self.player.alive:
            for powerup in self.powerups:
                if powerup.alive and circle_hit(
                    self.player.centerx, self.player.centery,
                    self.player.hit_radius + 4, powerup.posX, powerup.posY,
                    powerup.radius + 7,
                ):
                    self._collect_powerup(powerup)

        self.player_bullets = [bullet for bullet in self.player_bullets if bullet.alive]
        self.enemy_bullets = [bullet for bullet in self.enemy_bullets if bullet.alive]
        self.powerups = [powerup for powerup in self.powerups if powerup.alive]
        self.enemies = [enemy for enemy in self.enemies if enemy.alive]
        if self.pending_asteroids:
            self.enemies.extend(self.pending_asteroids)
            self.pending_asteroids.clear()

    # --------------------------------------------------------------- damage
    def _player_hit(self):
        result = self.player.take_hit()
        if result == "none":
            return result
        if result == "shield":
            self.effects.shield_hit(
                self.player.centerx, self.player.centery, self.palette["accent"]
            )
            self.audio.play("shield", 0.85)
            self.shake.add(0.3)
            self._clear_enemy_bullets_near(self.player.centerx, self.player.centery, 210)
            self.effects.text(
                tr(self.language, "shield"), self.player.centerx,
                self.player.posY - 24, self.palette["accent"], 20, 1.2,
            )
            return result

        # Dead.
        self.metrics.note_damage()
        self.combo_chain = 0
        self.combo_timer = 0.0
        self.multiplier = 1
        self.effects.explosion(
            self.player.centerx, self.player.centery,
            (255, 180, 90) if self.mode == "normal" else (255, 120, 220),
            count=52, speed=330, size=4.8, life=1.05,
        )
        self.effects.boom(self.player.centerx, self.player.centery, 62)
        self.effects.flash((255, 210, 170), 95)
        self.shake.add(0.8)
        self.audio.play("crash", 0.95)
        if self.mode == "meme":
            self.audio.play("meme_explode", 0.7)
        self._clear_enemy_bullets_near(self.player.centerx, self.player.centery, 240)
        if self.player.life <= 0:
            self.state = "dying"
            self.death_timer = 1.8
        else:
            self.audio.play("low_health", 0.7)
        return result

    def _kill_enemy(self, enemy, award=True, drop=True):
        if getattr(enemy, "_handled", False):
            return
        enemy._handled = True
        enemy.alive = False
        self.kills += 1
        if award:
            gained = self._register_kill(int(enemy.score))
            self.effects.text(
                f"+{gained}", clamp(enemy.posX, 44, VW - 44),
                clamp(enemy.posY, 96, VH - 60), self.palette["accent"], 17, 0.9,
            )
            if self.multiplier > 1:
                self.effects.text(
                    f"x{self.multiplier}", clamp(enemy.posX, 44, VW - 44),
                    clamp(enemy.posY - 20, 86, VH - 70), self.palette["warning"], 15, 0.9,
                )
        salvage = self.balance.salvage(int(round(
            self.SALVAGE_REWARD.get(enemy.kind, 1) * self.player.salvage_mult
        )))
        if salvage > 0:
            self.salvage += salvage
        radius = float(getattr(enemy, "radius", 28))
        if enemy.kind == "asteroid":
            self.effects.boom(enemy.posX, enemy.posY, radius * 1.25)
            self.effects.explosion(
                enemy.posX, enemy.posY, self.palette["particle"],
                count=20, speed=200, size=3.0, life=0.6,
            )
            if enemy.level == "large" and award:
                for direction in (-1, 1):
                    child = self._spawn_asteroid(
                        x=clamp(enemy.posX + direction * 20, 30, VW - 30),
                        y=clamp(enemy.posY, 30, VH - 120),
                        level="small", radius=random.randint(17, 23),
                        rot_index=getattr(enemy, "rot_index", None),
                        defer=True,
                    )
                    if child is not None:
                        child.vx = direction * random.uniform(80, 140)
                        child.vy = random.uniform(90, 150)
                        self.pending_asteroids.append(child)
            self.shake.add(0.12)
        else:
            self.effects.explosion(
                enemy.posX, enemy.posY, self.palette["particle"],
                count=34, speed=250, size=3.8, life=0.8,
            )
            self.effects.ring(enemy.posX, enemy.posY, self.palette["accent"], 54, 0.35, 2)
            self.shake.add(0.18)
        self.audio.play("crash", 0.55 if enemy.kind == "asteroid" else 0.7,
                        throttle_ms=35)
        if self.mode == "meme":
            if self.kills % 4 == 0:
                self.taunt_text = meme_taunt(self.language, self.meme_index)
                self.meme_index += 1
                self.taunt_timer = 2.8
            if random.random() < 0.35:
                self.audio.play("meme_boing", 0.2, throttle_ms=180)
        if drop:
            self._maybe_drop(enemy)

    def _defeat_boss(self):
        boss = self.boss
        if boss is None or getattr(boss, "_handled", False):
            return
        boss._handled = True
        boss.alive = False
        self.kills += 1
        gained = self._register_kill(int(boss.score))
        self.salvage += self.balance.salvage(20 + self.wave)
        self.effects.text(
            f"+{gained}", boss.posX, boss.posY,
            self.palette["warning"], 30, 1.8,
        )
        self.effects.boss_explosion(boss.posX, boss.posY, self.palette["particle"])
        self.effects.boom(boss.posX, boss.posY, 110)
        self.audio.play("crash", 1.0)
        if self.mode == "meme":
            self.audio.play("meme_explode", 0.9)
        self.shake.add(1.0)
        self.enemy_bullets.clear()
        self.danger_zones.clear()
        self.beams.clear()
        for kind, offset in (("weapon", -90), ("shield", 0), ("life", 90)):
            self._spawn_powerup(boss.posX + offset, boss.posY + 30, kind)
        # Recovery window: heal, clear the arena and hold off new spawns for a
        # few seconds after the upgrade overlay closes.
        if self.player.alive:
            for _ in range(self.balance.post_boss_heal):
                self.player.heal()
        self.spawn_grace = self.balance.post_boss_grace
        self.spawn_timer = self.spawn_grace
        if self.campaign:
            self.boss = None
            self._complete_mission()
            return
        self.boss = None
        self.wave += 1
        self.wave_timer = 0.0
        self._sync_zone(announce=False)
        self._announce(tr(self.language, "boss_defeated"), self.palette["success"], 3.0,
                       sub=tr(self.language, "wave_announce", wave=self.wave))
        self.audio.play("wave", 0.9)
        self._open_upgrade()

    def _complete_mission(self):
        """Finish the current campaign mission and persist its rewards."""
        if not self.campaign or self.state in ("victory", "gameover"):
            return
        mission = self.campaign_mission
        mission_id = mission["id"]
        summary = {
            "first_completion": False,
            "next_mission": None,
            "salvage_bonus": 0,
            "best": None,
        }
        if self.campaign_progress is not None:
            summary = self.campaign_progress.complete_mission(
                mission_id,
                score=int(self.score),
                kills=self.kills,
                time=self.game_time,
                reward=int(mission.get("reward_salvage", 0)),
            )
        campaign_complete = bool(
            self.campaign_progress is not None
            and self.campaign_progress.completed_count()
            >= self.campaign_progress.total_count()
        )
        self.state = "victory"
        self.overlay_time = 0.0
        self.announce_timer = 0.0
        self.announce_text = None
        self.taunt_timer = 0.0
        self.info_timer = 0.0
        self.danger_zones.clear()
        self.beams.clear()
        self.enemy_bullets.clear()
        self.campaign_result = {
            "mission": mission,
            "score": int(self.score),
            "kills": self.kills,
            "time": self.game_time,
            "summary": summary,
            "campaign_complete": campaign_complete,
        }
        self.audio.stop_music()
        self.audio.play("wave", 0.9)
        self.audio.play("upgrade_apply", 0.7)
        self._build_victory_widgets(summary, campaign_complete)

    def _build_victory_widgets(self, summary, campaign_complete):
        cx = VW // 2
        panel_top = VH // 2 - 250
        widgets = []
        next_id = summary.get("next_mission")
        if next_id and not campaign_complete:
            widgets.append(Button((cx - 170, panel_top + 352, 340, 46),
                                  tr(self.language, "campaign_next"),
                                  "campaign_next", size=19))
            widgets.append(Button((cx - 170, panel_top + 406, 340, 42),
                                  tr(self.language, "campaign_replay"),
                                  "campaign_replay", size=17))
        else:
            offset = 430 if campaign_complete else 352
            widgets.append(Button((cx - 170, panel_top + offset, 340, 46),
                                  tr(self.language, "campaign_back"),
                                  "campaign_menu", size=19))
            widgets.append(Button((cx - 170, panel_top + offset + 54, 340, 42),
                                  tr(self.language, "campaign_menu"),
                                  "campaign_main", size=17))
        self.victory_group = WidgetGroup(
            widgets, on_hover=lambda: self.audio.play("ui_hover", 0.4)
        )


    def _clear_enemy_bullets_near(self, x, y, radius):
        for bullet in self.enemy_bullets:
            if bullet.alive and circle_hit(bullet.posX, bullet.posY, 4, x, y, radius):
                bullet.alive = False
                self.effects.hit_sparks(
                    bullet.posX, bullet.posY, self.palette["enemy_bullet"], count=3
                )
        self.enemy_bullets = [bullet for bullet in self.enemy_bullets if bullet.alive]

    def _register_kill(self, base_points):
        self.combo_chain += 1
        self.combo_timer = 2.6
        self.multiplier = min(5, 1 + self.combo_chain // 5)
        gained = int(base_points * self.multiplier)
        self.score += gained
        return gained

    def _collect_powerup(self, powerup):
        if not powerup.alive:
            return
        powerup.alive = False
        kind = powerup.kind
        color = powerup.color
        message = ""
        self.effects.pickup(powerup.posX, powerup.posY, color)
        if kind == "shield":
            self.player.add_shield(12.0)
            message = tr(self.language, "meme_pickup_shield" if self.mode == "meme"
                         else "pickup_shield", seconds=12)
        elif kind == "life":
            if self.player.heal():
                message = tr(self.language, "meme_pickup_life" if self.mode == "meme"
                             else "pickup_life")
            else:
                bonus = 1000 * self.multiplier
                self.score += bonus
                message = tr(self.language, "pickup_life_full", points=bonus)
        elif kind == "weapon":
            improved = self.player.add_weapon()
            if improved:
                message = tr(self.language, "meme_pickup_weapon" if self.mode == "meme"
                             else "pickup_weapon", level=self.player.weapon_level)
            else:
                bonus = 1000 * self.multiplier
                self.score += bonus
                message = tr(self.language, "pickup_weapon_max", points=bonus)
        elif kind == "rapid":
            self.player.add_rapid(11.0)
            message = tr(self.language, "meme_pickup_rapid" if self.mode == "meme"
                         else "pickup_rapid", seconds=11)
        else:  # points
            bonus = 500 * self.multiplier
            self.score += bonus
            message = tr(self.language, "meme_pickup_points" if self.mode == "meme"
                         else "pickup_points", points=bonus)

        self.effects.text(message, clamp(powerup.posX, 90, VW - 90),
                          powerup.posY - 16, color, 18, 1.5, vy=-40)
        if self.mode == "meme":
            self.audio.play("meme_pickup", 0.75)
        else:
            self.audio.play("powerup" if kind != "points" else "pickup", 0.75)

    # ---------------------------------------------------------- projectiles
    def spawn_enemy_bullet(self, x, y, angle, speed, radius=6.0, kind="enemy_orb"):
        if len(self.enemy_bullets) >= self.MAX_ENEMY_BULLETS:
            self.enemy_bullets.pop(0)
        sprite = self.resources.bullet_sprite(kind, self.mode)
        color = (self.palette["accent2"] if kind == "enemy_plasma"
                 else self.enemy_bullet_color)
        self.enemy_bullets.append(EnemyBullet(
            x, y, math.cos(angle) * speed, math.sin(angle) * speed,
            radius=radius, mode=self.mode, color=color,
            sprite=sprite, kind=kind,
        ))

    def spawn_danger_zone(self, x, y, radius=96.0, warn=1.15, duration=1.6):
        self.danger_zones.append(DangerZone(
            x, y, radius=radius, warn=warn, duration=duration,
            color=self.palette["danger"],
        ))
        self.audio.play("hazard_warn", 0.5, throttle_ms=180)
        if len(self.danger_zones) > self.balance.max_zones:
            del self.danger_zones[:len(self.danger_zones) - self.balance.max_zones]

    def spawn_beam(self, x, y, angle, warn=1.0, duration=0.4, width=18.0,
                   sweep=0.0, color=None):
        self.beams.append(BeamAttack(
            x, y, angle, warn=warn, duration=duration,
            width=width, sweep=sweep,
            color=color or self.palette["danger"],
        ))
        self.audio.play("beam_charge", 0.5, throttle_ms=220)
        if len(self.beams) > self.balance.max_beams:
            del self.beams[:len(self.beams) - self.balance.max_beams]

    # -------------------------------------------------------------- upgrades
    def _available_upgrades(self):
        return [key for key in UPGRADE_ORDER
                if upgrade_available(key, self.player.upgrades)]

    def _upgrade_card_rects(self):
        card_w = 300
        gap = 22
        total = card_w * 3 + gap * 2
        left = VW // 2 - total // 2
        return [pygame.Rect(left + index * (card_w + gap), 262, card_w, 290)
                for index in range(3)]

    def _upgrade_skip_rect(self):
        return pygame.Rect(VW // 2 - 90, 574, 180, 40)

    def _open_upgrade(self):
        if self.state != "playing":
            return
        pool = self._available_upgrades()
        if not pool:
            return
        random.shuffle(pool)
        self.upgrade_choices = [
            (key, upgrade_cost(key, self.player.upgrade_level(key)))
            for key in pool[:3]
        ]
        self.upgrade_focus = 0
        self.state = "upgrade"
        self.audio.play("upgrade_open", 0.7)
        self.effects.ring(self.player.centerx, self.player.centery,
                          self.palette["warning"], 120, 0.7, 3)

    def _close_upgrade(self):
        if self.state != "upgrade":
            return
        self.state = "playing"
        self.upgrade_choices = []
        if self.spawn_grace > 0:
            self.spawn_timer = max(self.spawn_timer, self.spawn_grace)
        else:
            self.spawn_timer = min(self.spawn_timer, 0.8)
        self.audio.play("ui_click", 0.5)

    def _apply_upgrade(self, index):
        if index < 0 or index >= len(self.upgrade_choices):
            return
        key, cost = self.upgrade_choices[index]
        spec = UPGRADES[key]
        if not upgrade_available(key, self.player.upgrades):
            return
        if self.salvage < cost:
            self.audio.play("hit", 0.4, throttle_ms=160)
            self.effects.text(tr(self.language, "upgrade_no_salvage"),
                              VW // 2, 548, self.palette["danger"], 15, 0.9)
            return
        self.salvage -= cost
        if self.player.apply_upgrade(key):
            self.effects.text(
                tr(self.language, "upgrade_applied",
                   name=tr(self.language, spec["name"])),
                VW // 2, 210, spec["color"], 20, 1.4,
            )
            self.audio.play("upgrade_apply", 0.8)
        self._close_upgrade()

    def _handle_upgrade_event(self, event, mouse):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._close_upgrade()
            elif event.key in (pygame.K_LEFT, pygame.K_a, pygame.K_UP, pygame.K_w):
                self.upgrade_focus = (self.upgrade_focus - 1) % max(1, len(self.upgrade_choices))
                self.audio.play("ui_hover", 0.35, throttle_ms=55)
            elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN, pygame.K_s):
                self.upgrade_focus = (self.upgrade_focus + 1) % max(1, len(self.upgrade_choices))
                self.audio.play("ui_hover", 0.35, throttle_ms=55)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._apply_upgrade(self.upgrade_focus)
            elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                self._apply_upgrade(event.key - pygame.K_1)
            return
        if event.type == pygame.MOUSEMOTION:
            for index, rect in enumerate(self._upgrade_card_rects()):
                if index < len(self.upgrade_choices) and rect.collidepoint(mouse):
                    if self.upgrade_focus != index:
                        self.upgrade_focus = index
                        self.audio.play("ui_hover", 0.35, throttle_ms=55)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for index, rect in enumerate(self._upgrade_card_rects()):
                if index < len(self.upgrade_choices) and rect.collidepoint(mouse):
                    self._apply_upgrade(index)
                    return
            if self._upgrade_skip_rect().collidepoint(mouse):
                self._close_upgrade()

    # -------------------------------------------------------------- endgame
    def _pause(self):
        if self.state != "playing":
            return
        self.state = "paused"
        self.audio.pause_music()
        self.audio.play("ui_click", 0.5)
        self._build_pause_widgets()

    def _resume(self):
        if self.state != "paused":
            return
        self.state = "playing"
        self.audio.resume_music()
        self.audio.play("ui_click", 0.4)
        self.pause_group = None

    def _build_pause_widgets(self):
        cx = VW // 2
        panel_top = VH // 2 - 190
        menu_label = ("campaign_back" if self.campaign else "main_menu")
        widgets = [
            Button((cx - 150, panel_top + 190, 300, 48), tr(self.language, "resume"), "resume"),
            Button((cx - 150, panel_top + 250, 300, 48), tr(self.language, "restart"), "restart"),
            Button((cx - 150, panel_top + 310, 300, 48), tr(self.language, menu_label), "menu"),
        ]
        self.pause_group = WidgetGroup(widgets, on_hover=lambda: self.audio.play("ui_hover", 0.4))

    def _finalize_game_over(self):
        if self.state == "gameover":
            return
        self.state = "gameover"
        self.overlay_time = 0.0
        self.announce_timer = 0.0
        self.announce_text = None
        self.taunt_timer = 0.0
        self.info_timer = 0.0
        self.audio.stop_music()
        self.audio.play("gameover" if self.mode == "normal" else "meme_gameover", 0.85)
        if self.campaign:
            # Campaign failures never touch the endless leaderboard.
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
                "campaign": True,
                "mission": self.campaign_mission,
            }
            self._build_gameover_widgets()
            return
        rank, is_new, best_before = self.app.leaderboard.add(
            self.mode, int(self.score), self.wave, self.kills
        )
        self.result = {
            "score": int(self.score),
            "wave": self.wave,
            "kills": self.kills,
            "time": self.game_time,
            "rank": rank,
            "is_new": is_new,
            "best_before": best_before,
            "best": self.app.leaderboard.best(self.mode),
            "salvage": self.salvage,
        }
        self._build_gameover_widgets()

    def _build_gameover_widgets(self):
        cx = VW // 2
        panel_top = VH // 2 - 235
        if self.campaign:
            widgets = [
                Button((cx - 150, panel_top + 330, 300, 46),
                       tr(self.language, "campaign_retry"), "campaign_replay"),
                Button((cx - 150, panel_top + 386, 300, 46),
                       tr(self.language, "campaign_back"), "campaign_menu"),
                Button((cx - 110, panel_top + 442, 220, 38),
                       tr(self.language, "campaign_menu"), "campaign_main", size=17),
            ]
            self.over_group = WidgetGroup(
                widgets, on_hover=lambda: self.audio.play("ui_hover", 0.4)
            )
            return
        widgets = [
            Button((cx - 150, panel_top + 330, 300, 46),
                   tr(self.language, "restart"), "restart"),
            Button((cx - 150, panel_top + 386, 300, 46),
                   tr(self.language, "main_menu"), "menu"),
        ]
        self.over_group = WidgetGroup(widgets, on_hover=lambda: self.audio.play("ui_hover", 0.4))

    # ---------------------------------------------------------------- draw
    def draw(self, canvas):
        self.hide_cursor = self.state in ("playing", "dying")
        self._draw_world()
        canvas.fill(self.palette["bg"])
        offset_x = int(self.shake.offset_x) if self.settings.screen_shake else 0
        offset_y = int(self.shake.offset_y) if self.settings.screen_shake else 0
        canvas.blit(self.world, (offset_x, offset_y))
        self.effects.draw_flash(canvas)
        canvas.blit(self.resources.vignette, (0, 0))
        if self.state not in ("upgrade", "story", "victory"):
            self._draw_hud(canvas)
        if self.state == "dying":
            overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
            overlay.fill((80, 10, 20, 45))
            canvas.blit(overlay, (0, 0))
        elif self.state == "story":
            self._draw_story(canvas)
        elif self.state == "paused":
            self._draw_pause(canvas)
        elif self.state == "upgrade":
            self._draw_upgrade(canvas)
        elif self.state == "victory":
            self._draw_victory(canvas)
        elif self.state == "gameover":
            self._draw_gameover(canvas)

    def _draw_world(self):
        world = self.world
        world.fill(self.palette["bg"])
        self.backdrop.draw(world)

        for zone in self.danger_zones:
            zone.draw(world, self.palette)

        for powerup in self.powerups:
            powerup.draw(world, self.resources)

        for enemy in self.enemies:
            enemy.draw(world, self.resources)
            if enemy.kind != "asteroid" and enemy.hp < enemy.max_hp:
                draw_bar(
                    world,
                    (int(enemy.posX - 22), int(enemy.posY - enemy.radius - 12), 44, 4),
                    enemy.hp / max(1, enemy.max_hp), self.palette["danger"],
                    (24, 16, 30), None, 2,
                )

        if self.boss is not None:
            self.boss.draw(world, self.resources)

        for beam in self.beams:
            beam.draw(world)

        for bullet in self.player_bullets:
            bullet.draw(world)
        for bullet in self.enemy_bullets:
            bullet.draw(world)

        self.player.draw(world, self.resources, self.time, self.mode)
        self.effects.draw(world)

    def _draw_hud(self, canvas):
        palette = self.palette
        if self.campaign:
            zone = ZONES[max(0, min(len(ZONES) - 1,
                                    self.campaign_mission.get("zone", 0)))]
        else:
            zone = zone_for_wave(self.wave)
        top = pygame.Rect(18, 12, VW - 36, 60)
        draw_panel(canvas, top, (*palette["panel"], 210), palette["border"], 12, 1)

        score_label = tr(self.language, "meme_score" if self.mode == "meme" else "score")
        draw_text(canvas, self.resources, score_label, 11, palette["muted"], (36, 21))
        draw_text(canvas, self.resources, format_score(self.display_score), 27,
                  palette["accent"], (36, 32), shadow=(2, 5, 12))
        best_value = max(self.best_before, int(self.score))
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'meme_best' if self.mode == 'meme' else 'best')}  {format_score(best_value)}",
                  11, palette["muted"], (240, 23))
        draw_text(canvas, self.resources, tr(self.language, zone["name"]), 10,
                  zone["accent"], (240, 48))

        # Wave + zone + progress.
        if self.campaign:
            mission = self.campaign_mission
            draw_text(canvas, self.resources,
                      tr(self.language, mission.get("name_key", "campaign_title")),
                      11, palette["muted"], (VW // 2, 18), anchor="midtop")
            draw_text(canvas, self.resources,
                      f"{self.wave:02d} / {self.total_waves:02d}", 21,
                      palette["text"], (VW // 2, 31), anchor="midtop")
            if self.boss is None:
                progress = clamp(self.wave_timer / self.WAVE_DURATION, 0.0, 1.0)
                draw_bar(canvas, (VW // 2 - 70, 59, 140, 3), progress,
                         palette["accent2"], (28, 34, 54), None, 1)
            if self.boss is None:
                if mission.get("boss"):
                    objective = tr(self.language, "mission_objective_boss",
                                   waves=self.total_waves)
                else:
                    objective = tr(self.language, "mission_objective_survive",
                                   waves=self.total_waves)
                draw_text(canvas, self.resources, objective, 9, palette["muted"],
                          (VW // 2, 76), anchor="midtop")
        else:
            wave_label = tr(self.language, "meme_wave" if self.mode == "meme" else "wave")
            draw_text(canvas, self.resources, wave_label, 11, palette["muted"],
                      (VW // 2, 20), anchor="midtop")
            draw_text(canvas, self.resources, f"{self.wave:02d}", 23, palette["text"],
                      (VW // 2, 30), anchor="midtop")
            if self.boss is None:
                progress = clamp(self.wave_timer / self.WAVE_DURATION, 0.0, 1.0)
                draw_bar(canvas, (VW // 2 - 70, 59, 140, 3), progress,
                         palette["accent2"], (28, 34, 54), None, 1)

        # Lives.
        lives_label = tr(self.language, "meme_lives" if self.mode == "meme" else "lives")
        draw_text(canvas, self.resources, lives_label, 11, palette["muted"],
                  (VW - 36, 20), anchor="topright")
        icon = self.resources.ship_small
        for index in range(min(7, self.player.life)):
            canvas.blit(icon, (VW - 54 - index * 30, 36))
        if self.player.life <= 0:
            draw_text(canvas, self.resources, "0", 18, palette["danger"],
                      (VW - 52, 36), anchor="topright")

        if self.player.shield_timer > 0:
            draw_bar(canvas, (VW - 196, 63, 158, 5),
                     self.player.shield_timer / 12.0, palette["accent2"],
                     (26, 34, 54), None, 2)
            draw_text(canvas, self.resources, f"{int(self.player.shield_timer) + 1}s",
                      11, palette["accent2"], (VW - 200, 56), anchor="topright")

        combo_y = 136 if (self.boss is not None and self.boss.entered) else 82
        if self.multiplier > 1:
            pulse = 0.8 + math.sin(self.time * 8.0) * 0.2
            color = (
                int(palette["warning"][0] * pulse),
                int(palette["warning"][1] * pulse),
                int(palette["warning"][2] * pulse),
            )
            combo_key = "meme_combo" if self.mode == "meme" else "combo"
            draw_text(canvas, self.resources,
                      tr(self.language, combo_key, multiplier=self.multiplier),
                      18, color, (VW // 2, combo_y), anchor="midtop")

        if self.boss is not None and self.boss.entered:
            self._draw_boss_bar(canvas)

        # Bottom-left weapon + salvage panel.
        panel = pygame.Rect(18, VH - 70, 440, 52)
        draw_panel(canvas, panel, (*palette["panel"], 190), palette["border"], 10, 1)
        weapon_spec = WEAPONS.get(self.player.weapon_class, WEAPONS["pulse"])
        draw_text(canvas, self.resources, tr(self.language, "weapon"), 10,
                  palette["muted"], (32, VH - 64))
        draw_text(canvas, self.resources, tr(self.language, weapon_spec["name"]), 14,
                  palette["accent"], (32, VH - 50))
        for index in range(3):
            color = palette["accent"] if index < self.player.weapon_level else (38, 48, 70)
            pygame.draw.rect(canvas, color, (32 + index * 22, VH - 30, 16, 6),
                             border_radius=2)
        draw_text(canvas, self.resources, tr(self.language, "salvage"), 10,
                  palette["muted"], (panel.right - 18, VH - 64), anchor="topright")
        draw_text(canvas, self.resources, str(self.salvage), 22,
                  palette["warning"], (panel.right - 18, VH - 52), anchor="topright")

        # Bottom-right timed bonuses.
        panel_r = pygame.Rect(VW - 356, VH - 92, 338, 74)
        draw_panel(canvas, panel_r, (*palette["panel"], 190), palette["border"], 10, 1)
        row_y = VH - 82
        if self.player.weapon_timer > 0:
            draw_text(canvas, self.resources, tr(self.language, "weapon"), 10,
                      palette["muted"], (VW - 342, row_y))
            draw_bar(canvas, (VW - 342, row_y + 13, 300, 4),
                     self.player.weapon_timer / 18.0, palette["warning"],
                     (28, 34, 54), None, 2)
            row_y += 20
        if self.player.shield_timer > 0:
            draw_text(canvas, self.resources, tr(self.language, "shield"), 10,
                      palette["muted"], (VW - 342, row_y))
            draw_bar(canvas, (VW - 342, row_y + 13, 300, 4),
                     self.player.shield_timer / 12.0, palette["accent"],
                     (28, 34, 54), None, 2)
            row_y += 20
        if self.player.rapid_timer > 0:
            draw_text(canvas, self.resources, tr(self.language, "rapid"), 10,
                      palette["muted"], (VW - 342, row_y))
            draw_bar(canvas, (VW - 342, row_y + 13, 300, 4),
                     self.player.rapid_timer / 11.0, palette["success"],
                     (28, 34, 54), None, 2)
        if not any((self.player.weapon_timer, self.player.shield_timer,
                    self.player.rapid_timer)):
            draw_text(canvas, self.resources, tr(self.language, "powerup_hint"), 12,
                      palette["muted"], (VW - 342, VH - 64))

        # Center announcement (gameplay only; never over overlays).
        if (self.state in ("playing", "dying")
                and self.announce_timer > 0 and self.announce_text):
            progress = 1.0 - self.announce_timer / max(0.001, self.announce_duration)
            alpha = int(255 * min(1.0, progress * 6.0, self.announce_timer / 0.45))
            draw_text(canvas, self.resources, self.announce_text, 46,
                      self.announce_color, (VW // 2, VH * 0.30),
                      anchor="center", shadow=(2, 6, 16), alpha=alpha)
            if self.announce_sub:
                draw_text(canvas, self.resources, self.announce_sub, 20,
                          palette["text"], (VW // 2, VH * 0.30 + 44),
                          anchor="center", alpha=alpha)

        # Meme taunt.
        if self.state in ("playing", "dying") and self.taunt_timer > 0 and self.taunt_text:
            alpha = int(255 * min(1.0, self.taunt_timer / 0.5))
            draw_text(canvas, self.resources, self.taunt_text, 16,
                      palette["accent2"], (VW // 2, VH - 110), anchor="center",
                      alpha=alpha)

        # First-run controls hint.
        if self.state in ("playing", "dying") and self.info_timer > 0:
            alpha = int(255 * min(1.0, self.info_timer / 1.5))
            draw_text(canvas, self.resources, tr(self.language, "hint_controls"), 13,
                      palette["muted"], (VW // 2, VH - 32), anchor="center", alpha=alpha)

        if self.settings.show_fps:
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'fps')} {int(self.app.clock.get_fps())}", 12,
                      palette["muted"], (VW - 24, 80), anchor="topright")

    def _draw_boss_bar(self, canvas):
        palette = self.palette
        boss = self.boss
        rect = pygame.Rect(VW // 2 - 280, 82, 560, 44)
        draw_panel(canvas, rect, (*palette["panel"], 220), palette["danger"], 10, 1)
        draw_text(canvas, self.resources, tr(self.language, boss.name_key), 13,
                  palette["danger"], (rect.x + 16, rect.y + 5))
        phase_text = tr(self.language, "boss_phase", phase=boss.phase)
        draw_text(canvas, self.resources, phase_text, 11,
                  palette["warning"], (rect.right - 16, rect.y + 6), anchor="topright")
        hp = max(0, boss.hp)
        draw_text(canvas, self.resources, f"{int(hp)} / {boss.max_hp}", 11,
                  palette["muted"], (rect.right - 16, rect.y + 23), anchor="topright")
        draw_bar(canvas, (rect.x + 14, rect.y + 27, rect.width - 120, 10),
                 hp / max(1, boss.max_hp), palette["danger"],
                 (34, 18, 28), palette["border"], 3)
        for threshold in (0.33, 0.66):
            x = rect.x + 14 + (rect.width - 120) * threshold
            pygame.draw.line(canvas, (255, 220, 180), (x, rect.y + 26),
                             (x, rect.y + 38), 1)

    def _draw_upgrade(self, canvas):
        palette = self.palette
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        overlay.fill((3, 6, 16, 205))
        canvas.blit(overlay, (0, 0))
        cx = VW // 2
        draw_text(canvas, self.resources, tr(self.language, "upgrade_title"), 38,
                  palette["warning"], (cx, 112), anchor="center", shadow=(2, 6, 16))
        draw_text(canvas, self.resources, tr(self.language, "upgrade_subtitle"), 15,
                  palette["text"], (cx, 158), anchor="center")
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'salvage')}: {self.salvage}", 18,
                  palette["warning"], (cx, 190), anchor="center")

        rects = self._upgrade_card_rects()
        for index, rect in enumerate(rects):
            if index >= len(self.upgrade_choices):
                continue
            key, cost = self.upgrade_choices[index]
            spec = UPGRADES[key]
            level = self.player.upgrade_level(key)
            focused = index == self.upgrade_focus
            affordable = self.salvage >= cost
            color = spec["color"] if affordable else palette["muted"]
            border = color if focused else palette["border"]
            draw_panel(canvas, rect.move(0, -5 if focused else 0),
                       (18, 30, 58, 238), border, 14, 3 if focused else 1)
            draw_text(canvas, self.resources, f"{index + 1}", 13, palette["muted"],
                      (rect.x + 14, rect.y + 10))
            icon = self.resources.powerup_sprite(
                {"damage": "weapon", "firerate": "rapid", "hull": "life",
                 "multishot": "weapon", "engine": "rapid", "salvage": "points",
                 "shield": "shield"}.get(key, "points"), self.mode)
            icon = pygame.transform.smoothscale(icon, (58, 58))
            canvas.blit(icon, icon.get_rect(center=(rect.centerx, rect.y + 58)))
            draw_text(canvas, self.resources, tr(self.language, spec["name"]), 20,
                      color, (rect.centerx, rect.y + 104), anchor="center")
            draw_text(canvas, self.resources,
                      tr(self.language, "upgrade_level",
                         level=level, max=spec["max"]), 11,
                      palette["muted"], (rect.centerx, rect.y + 126),
                      anchor="center")
            for pip in range(spec["max"]):
                pip_color = color if pip < level else (42, 52, 74)
                pygame.draw.rect(canvas, pip_color,
                                 (rect.centerx - spec["max"] * 10 + pip * 20,
                                  rect.y + 142, 14, 5), border_radius=2)
            lines = self.resources.wrap_text(
                tr(self.language, spec["desc"]), 13, rect.width - 36
            )
            for line_index, line in enumerate(lines[:3]):
                draw_text(canvas, self.resources, line, 13, palette["text"],
                          (rect.centerx, rect.y + 162 + line_index * 19),
                          anchor="center", alpha=220)
            cost_color = palette["warning"] if affordable else palette["danger"]
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'upgrade_cost')} {cost}", 16,
                      cost_color, (rect.centerx, rect.bottom - 24), anchor="center")

        skip = self._upgrade_skip_rect()
        hovered = skip.collidepoint(self.app.mouse)
        draw_panel(canvas, skip, (24, 38, 64, 220) if hovered else (14, 24, 46, 210),
                   palette["accent"] if hovered else palette["border"], 10, 2 if hovered else 1)
        draw_text(canvas, self.resources, tr(self.language, "upgrade_skip"), 16,
                  palette["text"], skip.center, anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "upgrade_hint"), 12,
                  palette["muted"], (cx, skip.bottom + 18), anchor="center")

    def _draw_story(self, canvas):
        palette = self.palette
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        overlay.fill((4, 6, 16, 224))
        canvas.blit(overlay, (0, 0))
        cx = VW // 2
        panel = pygame.Rect(cx - 390, VH // 2 - 196, 780, 392)
        draw_panel(canvas, panel, (*palette["panel"], 245),
                   palette["accent"], 18, 2)
        mission = self.campaign_mission or {}
        draw_text(canvas, self.resources,
                  tr(self.language, "campaign_story"), 13, palette["muted"],
                  (panel.x + 34, panel.y + 24))
        draw_text(canvas, self.resources,
                  tr(self.language, mission.get("name_key", "campaign_title")),
                  28, palette["accent"], (panel.x + 34, panel.y + 44),
                  shadow=(2, 5, 14))
        index = min(self.story_index, max(0, len(self.story_keys) - 1))
        key = self.story_keys[index] if self.story_keys else "campaign_title"
        lines = self.resources.wrap_text(
            tr(self.language, key), 19, panel.width - 72
        )
        for line_index, line in enumerate(lines[:8]):
            draw_text(canvas, self.resources, line, 19, palette["text"],
                      (panel.x + 36, panel.y + 108 + line_index * 27))
        draw_text(canvas, self.resources,
                  f"{index + 1} / {max(1, len(self.story_keys))}", 12,
                  palette["muted"], (panel.right - 34, panel.y + 28),
                  anchor="topright")
        draw_text(canvas, self.resources, tr(self.language, "story_next_hint"), 12,
                  palette["muted"], (cx, panel.bottom - 26), anchor="center")

    def _draw_pause(self, canvas):
        palette = self.palette
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        overlay.fill((4, 6, 16, 190))
        canvas.blit(overlay, (0, 0))
        cx = VW // 2
        panel_top = VH // 2 - 190
        panel = pygame.Rect(cx - 270, panel_top, 540, 430)
        draw_panel(canvas, panel, (*palette["panel"], 240), palette["accent"], 16, 2)
        draw_text(canvas, self.resources, tr(self.language, "paused"), 48,
                  palette["accent"], (cx, panel_top + 42), anchor="center",
                  shadow=(2, 5, 14))
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'score')}: {format_score(self.score)}   ·   "
                  f"{tr(self.language, 'wave')}: {self.wave}   ·   "
                  f"{tr(self.language, 'salvage')}: {self.salvage}",
                  17, palette["text"], (cx, panel_top + 92), anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "focus_hint"), 11,
                  palette["muted"], (cx, panel_top + 116), anchor="center")
        self.pause_group.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources, "ESC / P — " + tr(self.language, "resume"),
                  12, palette["muted"], (cx, panel.bottom - 24), anchor="center")

    def _draw_victory(self, canvas):
        palette = self.palette
        fade = min(1.0, self.overlay_time * 2.6)
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        overlay.fill((4, 5, 14, int(205 * fade)))
        canvas.blit(overlay, (0, 0))
        cx = VW // 2
        result = self.campaign_result or {}
        summary = result.get("summary", {})
        mission = result.get("mission") or self.campaign_mission or {}
        campaign_complete = bool(result.get("campaign_complete"))
        panel_top = VH // 2 - 250
        panel = pygame.Rect(cx - 360, panel_top, 720, 590)
        accent = palette["success"] if not campaign_complete else palette["warning"]
        draw_panel(canvas, panel, (*palette["panel"], int(245 * fade)),
                   accent, 18, 2)

        title = ("campaign_complete" if campaign_complete else "mission_complete")
        draw_text(canvas, self.resources, tr(self.language, title), 44, accent,
                  (cx, panel_top + 44), anchor="center", shadow=(2, 6, 16))
        draw_text(canvas, self.resources,
                  tr(self.language, mission.get("name_key", "campaign_title")),
                  22, palette["text"], (cx, panel_top + 90), anchor="center")

        draw_text(canvas, self.resources, tr(self.language, "final_score"), 13,
                  palette["muted"], (cx, panel_top + 122), anchor="center")
        draw_text(canvas, self.resources, format_score(result.get("score", 0)), 50,
                  palette["warning"], (cx, panel_top + 140), anchor="midtop",
                  shadow=(2, 6, 16))
        stats = (
            f"{tr(self.language, 'kills')}  {result.get('kills', 0)}     "
            f"{tr(self.language, 'time')}  {format_time(result.get('time', 0.0))}"
        )
        draw_text(canvas, self.resources, stats, 15, palette["text"],
                  (cx, panel_top + 202), anchor="center")

        if campaign_complete:
            hint_key = "campaign_complete_hint"
            draw_text(canvas, self.resources, tr(self.language, hint_key), 16,
                      palette["accent"], (cx, panel_top + 242), anchor="center")
            lines = self.resources.wrap_text(
                tr(self.language, "campaign_epilogue"), 15, panel.width - 110
            )
            for index, line in enumerate(lines[:4]):
                draw_text(canvas, self.resources, line, 15, palette["text"],
                          (cx, panel_top + 274 + index * 22), anchor="center",
                          alpha=225)
        else:
            if summary.get("first_completion"):
                reward = int(mission.get("reward_salvage", 0))
                draw_text(canvas, self.resources,
                          tr(self.language, "mission_reward_earned", salvage=reward),
                          18, palette["warning"], (cx, panel_top + 236),
                          anchor="center")
            elif summary.get("best"):
                best = summary["best"]
                draw_text(canvas, self.resources,
                          f"{tr(self.language, 'campaign_best')}  "
                          f"{format_score(best.get('score', 0))}", 15,
                          palette["muted"], (cx, panel_top + 236),
                          anchor="center")
            next_id = summary.get("next_mission")
            if next_id:
                next_mission = mission_by_id(next_id)
                if next_mission:
                    draw_text(canvas, self.resources,
                              tr(self.language, "mission_unlocked",
                                 name=tr(self.language, next_mission["name_key"])),
                              14, palette["accent"], (cx, panel_top + 262),
                              anchor="center")
            if summary.get("salvage_bonus"):
                draw_text(canvas, self.resources,
                          f"{tr(self.language, 'campaign_bonus')}  "
                          f"{summary['salvage_bonus']}", 13, palette["muted"],
                          (cx, panel_top + 286), anchor="center")

        if self.victory_group is not None:
            self.victory_group.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources, tr(self.language, "campaign_victory_hint"),
                  12, palette["muted"], (cx, panel.bottom - 22), anchor="center",
                  alpha=int(255 * fade))

    def _draw_gameover(self, canvas):
        palette = self.palette
        fade = min(1.0, self.overlay_time * 2.6)
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        overlay.fill((4, 5, 14, int(205 * fade)))
        canvas.blit(overlay, (0, 0))
        cx = VW // 2
        panel_top = VH // 2 - 235
        panel = pygame.Rect(cx - 320, panel_top, 640,
                            520 if self.campaign else 470)
        draw_panel(canvas, panel, (*palette["panel"], int(245 * fade)),
                   palette["danger"], 18, 2)

        title = ("mission_failed" if self.campaign else "game_over")
        draw_text(canvas, self.resources, tr(self.language, title), 44,
                  palette["danger"], (cx, panel_top + 46), anchor="center",
                  shadow=(2, 6, 16), alpha=int(255 * fade))
        if self.campaign:
            draw_text(canvas, self.resources,
                      tr(self.language,
                         (self.campaign_mission or {}).get("name_key",
                                                          "campaign_title")),
                      18, palette["text"], (cx, panel_top + 84), anchor="center",
                      alpha=int(255 * fade))
        elif self.mode == "meme":
            draw_text(canvas, self.resources, tr(self.language, "meme_game_over"), 15,
                      palette["accent2"], (cx, panel_top + 84), anchor="center",
                      alpha=int(255 * fade))

        result = self.result or {
            "score": int(self.score), "wave": self.wave, "kills": self.kills,
            "time": self.game_time, "is_new": False,
            "best": self.app.leaderboard.best(self.mode),
        }
        draw_text(canvas, self.resources, tr(self.language, "final_score"), 13,
                  palette["muted"], (cx, panel_top + 112), anchor="center")
        draw_text(canvas, self.resources, format_score(result["score"]), 52,
                  palette["warning"], (cx, panel_top + 132), anchor="midtop",
                  shadow=(2, 6, 16))

        if not self.campaign:
            if result.get("is_new"):
                text = tr(self.language, "new_record_meme" if self.mode == "meme" else "new_record")
                color = palette["success"]
            else:
                text = f"{tr(self.language, 'best')}: {format_score(result.get('best', 0))}"
                color = palette["muted"]
            draw_text(canvas, self.resources, text, 17, color, (cx, panel_top + 208),
                      anchor="center")

        stats = (
            f"{tr(self.language, 'wave')}  {result['wave']}     "
            f"{tr(self.language, 'kills')}  {result['kills']}     "
            f"{tr(self.language, 'time')}  {format_time(result['time'])}"
        )
        draw_text(canvas, self.resources, stats, 15, palette["text"],
                  (cx, panel_top + 244), anchor="center")
        if result.get("salvage") is not None:
            draw_text(canvas, self.resources,
                      f"{tr(self.language, 'salvage')}  {result['salvage']}", 13,
                      palette["muted"], (cx, panel_top + 266), anchor="center")
        if result.get("rank") and not self.campaign:
            draw_text(canvas, self.resources, f"{tr(self.language, 'rank')} {result['rank']}",
                      14, palette["accent"], (cx, panel_top + 282), anchor="center")

        self.over_group.draw(canvas, self.resources, palette)
        hint_key = ("campaign_fail_hint" if self.campaign else
                    ("meme_press_enter_restart" if self.mode == "meme"
                     else "press_enter_restart"))
        draw_text(canvas, self.resources, tr(self.language, hint_key),
                  12, palette["muted"], (cx, panel.bottom - 22), anchor="center",
                  alpha=int(255 * fade))

    # -------------------------------------------------------------- helpers
    def _announce(self, text, color, duration=2.2, sub=None):
        self.announce_text = text
        self.announce_color = color
        self.announce_duration = duration
        self.announce_timer = duration
        self.announce_sub = sub
