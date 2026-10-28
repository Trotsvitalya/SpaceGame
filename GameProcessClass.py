"""Main gameplay scene: player, enemies, projectiles, power-ups and HUD."""

from __future__ import annotations

import math
import random

import pygame

from BulletClass import Bullet, EnemyBullet
from EffectsClass import Effects, ScreenShake, StarField
from EnemyAsteroidClass import BossEnemy, EnemyAsteroid, EnemyShip
from Localization import meme_taunt, tr
from PowerUpClass import PowerUp
from ResourcesClass import palette_for
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

    def __init__(self, app, mode="normal"):
        self.app = app
        self.mode = mode if mode in ("normal", "meme") else "normal"
        self.settings = app.settings
        self.resources = app.resources
        self.audio = app.audio
        self.language = self.settings.language
        self.palette = palette_for(self.mode)
        self.isRunMainLoop = True

        self.world = pygame.Surface((VW, VH)).convert()
        self.background_index = random.randrange(self.resources.background_count)
        self.starfield = StarField(seed=random.randint(1, 99999))
        self.effects = Effects(self.resources)
        self.shake = ScreenShake()

        self.player = UserShip(
            VW * 0.5 - 39, VH - 150, VW, VH,
            imageList=self.resources.ship_frames,
            imageBoomList=self.resources.boom_sources,
        )
        self.player_bullets = []
        self.enemy_bullets = []
        self.enemies = []
        self.powerups = []
        self.boss = None
        self.boss_drop_flags = {}

        self.score = 0.0
        self.display_score = 0.0
        self.kills = 0
        self.wave = 1
        self.game_time = 0.0
        self.best_before = app.leaderboard.best(self.mode)
        self.result = None

        self.spawn_timer = 1.15
        self.wave_timer = 0.0
        self.combo_chain = 0
        self.combo_timer = 0.0
        self.multiplier = 1
        self.engine_accum = 0.0
        self.bg_offset = 0.0
        self.nebula_offset = 0.0
        self.time = 0.0
        self.info_timer = 11.0
        self.state = "playing"
        self.death_timer = 0.0
        self.overlay_time = 0.0
        self.pause_group = None
        self.over_group = None
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

        self._announce(tr(self.language, "wave_announce", wave=self.wave),
                       self.palette["accent"], 2.4)

    # ------------------------------------------------------------ lifecycle
    def on_enter(self):
        self.audio.play_music("game", self.mode)
        self.music_started = True

    def on_exit(self):
        self.audio.stop_music()

    def _restart(self):
        self.audio.play("ui_click", 0.5)
        self.app.start_game(self.mode)

    def _to_menu(self):
        self.audio.play("ui_click", 0.5)
        self.app.go_menu()

    def _handle_action(self, action):
        if not action:
            return
        if action == "resume":
            self._resume()
        elif action == "restart":
            self._restart()
        elif action == "menu":
            self._to_menu()

    # ---------------------------------------------------------------- input
    def handle_event(self, event, mouse=None):
        mouse = mouse or self.app.mouse
        if event.type == pygame.QUIT:
            self.app.quit()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.app.toggle_fullscreen()
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
        for x, y, vx, vy in shots:
            if len(self.player_bullets) >= self.MAX_PLAYER_BULLETS:
                self.player_bullets.pop(0)
            self.player_bullets.append(Bullet(
                x, y, self.resources.bullet_frames, vx=vx, vy=vy,
                radius=8.0, damage=1,
                color=self.palette["bullet"],
            ))
        self.effects.hit_sparks(
            self.player.centerx, self.player.posY + 4,
            self.palette["bullet"], count=3,
        )
        self.audio.play("shot", 0.38, throttle_ms=45)
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
            self.boss.update(dt, self)
        self.enemies = [enemy for enemy in self.enemies if enemy.alive]
        if self.enemies and len(self.enemies) > self.MAX_ENEMIES:
            del self.enemies[self.MAX_ENEMIES:]

    def _update_powerups(self, dt):
        for powerup in self.powerups:
            powerup.update(dt)
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

    def _update_waves(self, dt):
        if self.boss is not None:
            return
        self.wave_timer += dt
        if self.wave_timer >= self.WAVE_DURATION:
            self.wave_timer = 0.0
            self.wave += 1
            if self.wave % 5 == 0:
                self._spawn_boss()
            else:
                self._announce(
                    tr(self.language, "wave_announce", wave=self.wave),
                    self.palette["accent"], 2.4,
                )
                self.audio.play("wave", 0.6)
                self._spawn_powerup(
                    random.uniform(160, VW - 160), 120,
                    random.choice(("weapon", "shield", "rapid")),
                )

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
        self.starfield.update(dt * time_scale, boost * 0.7)
        background_speed = 26.0 + boost * 0.24
        self.bg_offset = (self.bg_offset + background_speed * dt) % (VH * 2)
        self.nebula_offset = (self.nebula_offset + 9.0 * dt) % VH
        self.effects.update(dt * (0.55 if self.state == "gameover" else 1.0))

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
            self.spawn_timer -= dt
            if self.spawn_timer <= 0 and self.boss is None:
                self._spawn_enemy()
                self.spawn_timer = self._spawn_interval()

    # ------------------------------------------------------------- spawning
    def _spawn_interval(self):
        base = max(0.55, 1.42 - 0.074 * (self.wave - 1))
        return base * random.uniform(0.72, 1.22)

    def _spawn_enemy(self):
        if self.boss is not None or len(self.enemies) >= self.MAX_ENEMIES:
            return
        roll = random.random()
        if self.wave <= 1:
            kind = "asteroid"
        elif self.wave == 2:
            kind = "asteroid" if roll < 0.75 else "scout"
        elif self.wave == 3:
            kind = "asteroid" if roll < 0.55 else "scout" if roll < 0.82 else "fighter"
        else:
            if roll < 0.42:
                kind = "asteroid"
            elif roll < 0.66:
                kind = "scout"
            elif roll < 0.85:
                kind = "fighter"
            else:
                kind = "bomber"
        if kind == "asteroid":
            self._spawn_asteroid()
        else:
            self._spawn_ship(kind)

    def _spawn_asteroid(self, x=None, y=None, level=None, radius=None):
        if len(self.enemies) >= self.MAX_ENEMIES + 4:
            return None
        if level is None:
            level = "large" if random.random() < 0.38 else "small"
        if radius is None:
            radius = random.randint(30, 48) if level == "large" else random.randint(17, 25)
        index = random.randrange(len(self.resources.asteroid_sources))
        image = self.resources.asteroid(index, radius)
        asteroid = EnemyAsteroid(
            VW, VH, image, None, x=x, y=y, radius=radius,
            speed_scale=1.0 + 0.022 * (self.wave - 1), level=level,
        )
        self.enemies.append(asteroid)
        return asteroid

    def _spawn_ship(self, kind, x=None, y=-70, wave=None):
        if len(self.enemies) >= self.MAX_ENEMIES:
            return None
        ship = EnemyShip(kind, self.mode, self.resources, x=x, y=y,
                         wave=wave if wave is not None else self.wave)
        self.enemies.append(ship)
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
        self.boss = BossEnemy(self.mode, self.resources, self.wave)
        self.boss_drop_flags = {0.66: False, 0.33: False}
        self._announce(tr(self.language, "boss_warning"), self.palette["danger"], 3.6,
                       sub=tr(self.language, "boss_name"))
        self.audio.play("boss_warn", 0.8)
        self.audio.play("wave", 0.5)
        self.shake.add(0.55)

    def _spawn_boss_minions(self, boss):
        for offset in (-120, 120):
            self._spawn_ship("scout", x=clamp(boss.posX + offset, 80, VW - 80),
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

    def _maybe_drop(self, enemy):
        chance = {
            "asteroid": 0.10,
            "scout": 0.13,
            "fighter": 0.2,
            "bomber": 0.34,
        }.get(enemy.kind, 0.1)
        if enemy.kind == "boss":
            chance = 1.0
        if random.random() < chance:
            self._spawn_powerup(enemy.posX, enemy.posY, PowerUp.random_kind())

    # ------------------------------------------------------------ collisions
    def _update_collisions(self):
        # Player bullets vs regular enemies.
        for enemy in self.enemies:
            if not enemy.alive:
                continue
            for bullet in self.player_bullets:
                if not bullet.alive:
                    continue
                if segment_circle_hit(
                    bullet.prev_x, bullet.prev_y, bullet.posX, bullet.posY,
                    enemy.posX, enemy.posY, enemy.hit_radius + bullet.radius,
                ):
                    bullet.alive = False
                    killed = enemy.damage(bullet.damage)
                    self.effects.hit_sparks(
                        bullet.posX, bullet.posY, self.palette["bullet"], count=5
                    )
                    if killed:
                        self._kill_enemy(enemy)
                    break

        # Player bullets vs boss.
        if self.boss is not None:
            boss = self.boss
            for bullet in self.player_bullets:
                if not bullet.alive:
                    continue
                if segment_circle_hit(
                    bullet.prev_x, bullet.prev_y, bullet.posX, bullet.posY,
                    boss.posX, boss.posY, boss.hit_radius + bullet.radius,
                ):
                    bullet.alive = False
                    killed = boss.damage(bullet.damage)
                    self.effects.hit_sparks(
                        bullet.posX, bullet.posY, self.palette["warning"], count=6
                    )
                    if killed:
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
                    )
                    if child is not None:
                        child.vx = direction * random.uniform(80, 140)
                        child.vy = random.uniform(90, 150)
                        self.pending_asteroids.append(self.enemies.pop())
            self.shake.add(0.12)
        else:
            self.effects.explosion(
                enemy.posX, enemy.posY, self.palette["particle"],
                count=34, speed=250, size=3.8, life=0.8,
            )
            self.effects.ring(enemy.posX, enemy.posY, self.palette["accent"], 54, 0.35, 2)
            self.shake.add(0.18)
        self.audio.play("crash", 0.55 if enemy.kind == "asteroid" else 0.7, throttle_ms=35)
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
        for kind, offset in (("weapon", -90), ("shield", 0), ("life", 90)):
            self._spawn_powerup(boss.posX + offset, boss.posY + 30, kind)
        self.boss = None
        self.wave += 1
        self.wave_timer = 0.0
        self._announce(tr(self.language, "boss_defeated"), self.palette["success"], 3.0,
                       sub=tr(self.language, "wave_announce", wave=self.wave))
        self.audio.play("wave", 0.9)

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
    def spawn_enemy_bullet(self, x, y, angle, speed, radius=6.0):
        if len(self.enemy_bullets) >= self.MAX_ENEMY_BULLETS:
            self.enemy_bullets.pop(0)
        self.enemy_bullets.append(EnemyBullet(
            x, y, math.cos(angle) * speed, math.sin(angle) * speed,
            radius=radius, mode=self.mode, color=self.enemy_bullet_color,
            sprite=self.enemy_bullet_sprite,
        ))

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
        widgets = [
            Button((cx - 150, panel_top + 190, 300, 48), tr(self.language, "resume"), "resume"),
            Button((cx - 150, panel_top + 250, 300, 48), tr(self.language, "restart"), "restart"),
            Button((cx - 150, panel_top + 310, 300, 48), tr(self.language, "main_menu"), "menu"),
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
        }
        self._build_gameover_widgets()

    def _build_gameover_widgets(self):
        cx = VW // 2
        panel_top = VH // 2 - 235
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
        self._draw_hud(canvas)
        if self.state == "dying":
            overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
            overlay.fill((80, 10, 20, 45))
            canvas.blit(overlay, (0, 0))
        elif self.state == "paused":
            self._draw_pause(canvas)
        elif self.state == "gameover":
            self._draw_gameover(canvas)

    def _draw_world(self):
        world = self.world
        world.fill(self.palette["bg"])
        background = self.resources.background(self.background_index, self.mode)
        background_flip = self.resources.background_flipped(self.background_index, self.mode)
        bg_y = -(int(self.bg_offset) % (VH * 2))
        for index in range(3):
            tile = background if index % 2 == 0 else background_flip
            world.blit(tile, (0, bg_y + index * VH))

        nebula = self.resources.nebula(self.mode)
        neb_y = int(self.nebula_offset)
        world.blit(nebula, (0, neb_y - VH))
        world.blit(nebula, (0, neb_y))

        if self.mode == "meme":
            planet = self.resources.menu_planet("meme")
            planet.set_alpha(120)
            world.blit(planet, (VW - 245, 76 + int(math.sin(self.time * 0.4) * 10)))
            planet.set_alpha(255)

        boost = max(0.0, -self.player.vy)
        self.starfield.draw(world, self.palette["star"], boost)

        for powerup in self.powerups:
            powerup.draw(world, self.resources)

        for enemy in self.enemies:
            enemy.draw(world, self.resources)
            if enemy.kind != "asteroid" and enemy.hp < enemy.max_hp:
                draw_bar(
                    world,
                    (int(enemy.posX - 20), int(enemy.posY - enemy.radius - 12), 40, 4),
                    enemy.hp / max(1, enemy.max_hp), self.palette["danger"],
                    (24, 16, 30), None, 2,
                )

        if self.boss is not None:
            self.boss.draw(world, self.resources)

        for bullet in self.player_bullets:
            bullet.draw(world)
        for bullet in self.enemy_bullets:
            bullet.draw(world)

        self.player.draw(world, self.resources, self.time, self.mode)
        self.effects.draw(world)

    def _draw_hud(self, canvas):
        palette = self.palette
        top = pygame.Rect(18, 12, VW - 36, 60)
        draw_panel(canvas, top, (*palette["panel"], 210), palette["border"], 12, 1)

        score_label = tr(self.language, "meme_score" if self.mode == "meme" else "score")
        draw_text(canvas, self.resources, score_label, 11, palette["muted"], (36, 21))
        draw_text(canvas, self.resources, format_score(self.display_score), 26,
                  palette["accent"], (36, 32), kind="title", shadow=(2, 5, 12))
        best_value = max(self.best_before, int(self.score))
        draw_text(canvas, self.resources,
                  f"{tr(self.language, 'meme_best' if self.mode == 'meme' else 'best')}  {format_score(best_value)}",
                  11, palette["muted"], (240, 23))

        # Wave + progress.
        wave_label = tr(self.language, "meme_wave" if self.mode == "meme" else "wave")
        draw_text(canvas, self.resources, wave_label, 11, palette["muted"],
                  (VW // 2, 20), anchor="midtop")
        draw_text(canvas, self.resources, f"{self.wave:02d}", 24, palette["text"],
                  (VW // 2, 30), anchor="midtop", kind="title")
        if self.boss is None:
            progress = clamp(self.wave_timer / self.WAVE_DURATION, 0.0, 1.0)
            draw_bar(canvas, (VW // 2 - 70, 59, 140, 3), progress,
                     palette["accent2"], (28, 34, 54), None, 1)

        # Lives.
        lives_label = tr(self.language, "meme_lives" if self.mode == "meme" else "lives")
        draw_text(canvas, self.resources, lives_label, 11, palette["muted"],
                  (VW - 36, 20), anchor="topright")
        icon = self.resources.ship_small
        for index in range(min(5, self.player.life)):
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
                      18, color, (VW // 2, 82), anchor="midtop")

        if self.boss is not None and self.boss.entered:
            self._draw_boss_bar(canvas)

        # Bottom-left weapon panel.
        panel = pygame.Rect(18, VH - 66, 340, 48)
        draw_panel(canvas, panel, (*palette["panel"], 190), palette["border"], 10, 1)
        draw_text(canvas, self.resources, tr(self.language, "weapon"), 10,
                  palette["muted"], (32, VH - 60))
        draw_text(canvas, self.resources, f"LVL {self.player.weapon_level}", 16,
                  palette["accent"], (100, VH - 61))
        for index in range(3):
            color = palette["accent"] if index < self.player.weapon_level else (38, 48, 70)
            pygame.draw.rect(canvas, color, (32 + index * 24, VH - 41, 18, 6),
                             border_radius=2)
        if self.player.weapon_timer > 0:
            draw_bar(canvas, (168, VH - 42, 170, 5),
                     self.player.weapon_timer / 18.0, palette["warning"],
                     (28, 34, 54), None, 2)
            draw_text(canvas, self.resources, f"{int(self.player.weapon_timer) + 1}s", 11,
                      palette["warning"], (168, VH - 56))
        elif self.player.rapid_timer <= 0:
            draw_text(canvas, self.resources, "SPACE", 11, palette["muted"],
                      (168, VH - 56))

        # Bottom-right power-up timers.
        panel_r = pygame.Rect(VW - 348, VH - 66, 330, 48)
        draw_panel(canvas, panel_r, (*palette["panel"], 190), palette["border"], 10, 1)
        row_y = VH - 57
        if self.player.shield_timer > 0:
            draw_text(canvas, self.resources, tr(self.language, "shield"), 10,
                      palette["muted"], (VW - 334, row_y))
            draw_bar(canvas, (VW - 334, row_y + 16, 130, 5),
                     self.player.shield_timer / 12.0, palette["accent"],
                     (28, 34, 54), None, 2)
            row_y += 22
        if self.player.rapid_timer > 0:
            draw_text(canvas, self.resources, tr(self.language, "rapid"), 10,
                      palette["muted"], (VW - 188, VH - 57))
            draw_bar(canvas, (VW - 188, VH - 41, 150, 5),
                     self.player.rapid_timer / 11.0, palette["success"],
                     (28, 34, 54), None, 2)
        if self.player.shield_timer <= 0 and self.player.rapid_timer <= 0:
            draw_text(canvas, self.resources, tr(self.language, "powerup_hint"), 12,
                      palette["muted"], (VW - 334, VH - 46))

        # Center announcement (gameplay only; never over the pause/game-over UI).
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
                      palette["accent2"], (VW // 2, VH - 56), anchor="center",
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
        rect = pygame.Rect(VW // 2 - 260, 82, 520, 40)
        draw_panel(canvas, rect, (*palette["panel"], 220), palette["danger"], 10, 1)
        draw_text(canvas, self.resources, tr(self.language, "boss_name"), 13,
                  palette["danger"], (rect.x + 16, rect.y + 5))
        hp = max(0, boss.hp)
        draw_text(canvas, self.resources, f"{int(hp)} / {boss.max_hp}", 11,
                  palette["muted"], (rect.right - 16, rect.y + 6), anchor="topright")
        draw_bar(canvas, (rect.x + 14, rect.y + 22, rect.width - 28, 10),
                 hp / max(1, boss.max_hp), palette["danger"],
                 (34, 18, 28), palette["border"], 3)
        segments = 10
        for index in range(1, segments):
            x = rect.x + 14 + (rect.width - 28) * index / segments
            pygame.draw.line(canvas, (18, 10, 20), (x, rect.y + 22),
                             (x, rect.y + 32), 1)

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
                  f"{tr(self.language, 'wave')}: {self.wave}",
                  17, palette["text"], (cx, panel_top + 92), anchor="center")
        draw_text(canvas, self.resources, tr(self.language, "focus_hint"), 11,
                  palette["muted"], (cx, panel_top + 116), anchor="center")
        self.pause_group.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources, "ESC / P — " + tr(self.language, "resume"),
                  12, palette["muted"], (cx, panel.bottom - 24), anchor="center")

    def _draw_gameover(self, canvas):
        palette = self.palette
        fade = min(1.0, self.overlay_time * 2.6)
        overlay = pygame.Surface((VW, VH), pygame.SRCALPHA)
        overlay.fill((4, 5, 14, int(205 * fade)))
        canvas.blit(overlay, (0, 0))
        cx = VW // 2
        panel_top = VH // 2 - 235
        panel = pygame.Rect(cx - 320, panel_top, 640, 470)
        draw_panel(canvas, panel, (*palette["panel"], int(245 * fade)),
                   palette["danger"], 18, 2)

        title = tr(self.language, "game_over")
        draw_text(canvas, self.resources, title, 46, palette["danger"],
                  (cx, panel_top + 46), anchor="center", shadow=(2, 6, 16), alpha=int(255 * fade))
        if self.mode == "meme":
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
                  kind="title", shadow=(2, 6, 16))

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
        if result.get("rank"):
            draw_text(canvas, self.resources, f"{tr(self.language, 'rank')} {result['rank']}",
                      14, palette["accent"], (cx, panel_top + 270), anchor="center")

        self.over_group.draw(canvas, self.resources, palette)
        draw_text(canvas, self.resources,
                  tr(self.language, "meme_press_enter_restart" if self.mode == "meme"
                     else "press_enter_restart"),
                  12, palette["muted"], (cx, panel.bottom - 22), anchor="center",
                  alpha=int(255 * fade))

    # -------------------------------------------------------------- helpers
    def _announce(self, text, color, duration=2.2, sub=None):
        self.announce_text = text
        self.announce_color = color
        self.announce_duration = duration
        self.announce_timer = duration
        self.announce_sub = sub
