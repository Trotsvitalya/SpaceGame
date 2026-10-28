"""Gameplay, collision, menu and scene-flow tests (headless SDL)."""

import math
import os
import shutil
import tempfile
import unittest
from unittest import mock

import pygame

from AppClass import App
from BulletClass import Bullet
from EnemyAsteroidClass import BossEnemy, EnemyAsteroid, EnemyShip
from GameProcessClass import GameProcess
from MenuClass import Menu
from PowerUpClass import PowerUp
from SettingsClass import Leaderboard, Settings
from UserShipClass import UserShip
from utils import VH, VW


class GameTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.app = App(force_windowed=True)

    def setUp(self):
        self._original_leaderboard = self.app.leaderboard
        self.tempdir = tempfile.mkdtemp(prefix="spacegame-game-")
        self.addCleanup(shutil.rmtree, self.tempdir, True)

    def tearDown(self):
        self.app.leaderboard = self._original_leaderboard

    def make_game(self, mode="normal"):
        game = GameProcess(self.app, mode)
        self.addCleanup(game.on_exit)
        return game

    def make_ship(self, x=100.0, y=300.0):
        return UserShip(x, y, VW, VH, self.app.resources.ship_frames)


class PlayerTests(GameTestCase):
    def test_movement_is_frame_rate_independent(self):
        slow = self.make_ship()
        fast = self.make_ship()
        for _ in range(90):
            slow.update(1.0 / 60.0, 1.0, 0.0)
        for _ in range(216):
            fast.update(1.0 / 144.0, 1.0, 0.0)
        self.assertAlmostEqual(slow.posX, fast.posX, delta=2.0)
        self.assertGreater(slow.posX, 600.0)

    def test_ship_stays_inside_playfield(self):
        ship = self.make_ship()
        for _ in range(600):
            ship.update(1.0 / 60.0, 1.0, -1.0)
        self.assertEqual(ship.posX, VW - ship.width - 14)
        self.assertEqual(ship.posY, 82)

        for _ in range(600):
            ship.update(1.0 / 60.0, -1.0, 1.0)
        self.assertEqual(ship.posX, 14)
        self.assertEqual(ship.posY, VH - ship.height - 82)

    def test_weapon_levels_and_cooldown(self):
        ship = self.make_ship()
        ship.invulnerable_timer = 0
        self.assertEqual(len(ship.fire_volley()), 1)
        self.assertEqual(ship.fire_volley(), [])
        ship.fire_cooldown = 0
        ship.weapon_level = 2
        self.assertEqual(len(ship.fire_volley()), 2)
        ship.fire_cooldown = 0
        ship.weapon_level = 3
        shots = ship.fire_volley()
        self.assertEqual(len(shots), 3)
        self.assertLess(shots[1][2], 0)
        self.assertGreater(shots[2][2], 0)

    def test_rapid_fire_shortens_cooldown(self):
        ship = self.make_ship()
        base = ship.fire_interval
        ship.add_rapid()
        self.assertLess(ship.fire_interval, base)
        self.assertAlmostEqual(ship.fire_interval, base * 0.45)

    def test_shield_then_death_then_respawn(self):
        ship = self.make_ship()
        ship.add_shield()
        ship.invulnerable_timer = 0
        self.assertEqual(ship.take_hit(), "shield")
        self.assertEqual(ship.life, 3)
        self.assertEqual(ship.shield_timer, 0.0)
        self.assertGreater(ship.invulnerable_timer, 0)

        ship.invulnerable_timer = 0
        self.assertEqual(ship.take_hit(), "dead")
        self.assertFalse(ship.alive)
        self.assertEqual(ship.life, 2)
        self.assertEqual(ship.take_hit(), "none")

        ship.update(1.6, 0.0, 0.0)
        self.assertTrue(ship.alive)
        self.assertGreater(ship.invulnerable_timer, 0)
        self.assertEqual(ship.posX, VW * 0.5 - ship.width * 0.5)

    def test_weapon_upgrade_caps(self):
        ship = self.make_ship()
        self.assertTrue(ship.add_weapon())
        self.assertTrue(ship.add_weapon())
        self.assertFalse(ship.add_weapon())
        self.assertEqual(ship.weapon_level, 3)
        self.assertGreater(ship.weapon_timer, 0)

    def test_life_cap(self):
        ship = self.make_ship()
        ship.life = ship.max_life
        self.assertFalse(ship.heal())
        ship.life = 1
        self.assertTrue(ship.heal())
        self.assertEqual(ship.life, 2)


class ProjectileAndPowerUpTests(GameTestCase):
    def test_bullet_moves_and_leaves_screen(self):
        bullet = Bullet(100, 700, vy=-900)
        for _ in range(60):
            bullet.update(1.0 / 60.0)
        self.assertTrue(bullet.is_outside(VW, VH))

    def test_enemy_bullet_lifetime(self):
        from BulletClass import EnemyBullet
        bullet = EnemyBullet(100, 100, 0, 100, life=0.5)
        bullet.update(0.6)
        self.assertFalse(bullet.alive)

    def test_bullet_lists_are_bounded(self):
        game = self.make_game()
        for _ in range(260):
            game.spawn_enemy_bullet(100, 100, math.pi / 2, 100)
        self.assertEqual(len(game.enemy_bullets), game.MAX_ENEMY_BULLETS)

        for _ in range(120):
            game.player.fire_cooldown = 0
            game._try_fire()
        self.assertLessEqual(len(game.player_bullets), game.MAX_PLAYER_BULLETS)
        self.assertGreater(len(game.player_bullets), 0)

    def test_powerup_falls_off_screen(self):
        powerup = PowerUp(100, VH + 40, "points", "normal", self.app.resources)
        powerup.update(0.2)
        self.assertFalse(powerup.alive)

    def test_powerup_pickup(self):
        game = self.make_game()
        self.app.leaderboard = Leaderboard(path=os.path.join(self.tempdir, "scores.json"))
        game.powerups = [PowerUp(game.player.centerx, game.player.centery,
                                 "shield", game.mode, game.resources)]
        game._update_collisions()
        self.assertGreater(game.player.shield_timer, 0)
        self.assertEqual(game.powerups, [])

    def test_points_powerup_adds_score(self):
        game = self.make_game()
        before = game.score
        powerup = PowerUp(game.player.centerx, game.player.centery,
                          "points", game.mode, game.resources)
        game.powerups = [powerup]
        game._update_collisions()
        self.assertGreater(game.score, before)


class CollisionTests(GameTestCase):
    def test_player_bullet_kills_enemy(self):
        game = self.make_game()
        enemy = EnemyShip("scout", "normal", self.app.resources,
                          x=game.player.centerx, y=game.player.centery - 100)
        enemy.hp = 1
        game.enemies = [enemy]
        game.player_bullets = [Bullet(enemy.posX, enemy.posY)]
        game._update_collisions()
        self.assertEqual(game.kills, 1)
        self.assertGreater(game.score, 0)
        self.assertNotIn(enemy, game.enemies)

    def test_large_asteroid_splits_into_two_small_ones(self):
        game = self.make_game()
        asteroid = EnemyAsteroid(
            VW, VH, self.app.resources.asteroid(0, 36),
            x=game.player.centerx, y=game.player.centery - 100,
            radius=36, level="large",
        )
        asteroid.hp = 1
        game.enemies = [asteroid]
        game.player_bullets = [Bullet(asteroid.posX, asteroid.posY)]
        game._update_collisions()
        # The split children are queued and then merged at the end of the same
        # collision pass, so they are never iterated twice.
        self.assertEqual(game.pending_asteroids, [])
        self.assertEqual(len(game.enemies), 2)
        for child in game.enemies:
            self.assertEqual(child.level, "small")
            self.assertTrue(child.alive)

    def test_contact_damage_with_shield(self):
        game = self.make_game()
        game.player.add_shield()
        game.player.invulnerable_timer = 0
        enemy = EnemyShip("scout", "normal", self.app.resources,
                          x=game.player.centerx, y=game.player.centery)
        enemy.hp = 1
        game.enemies = [enemy]
        game._update_collisions()
        self.assertEqual(game.player.shield_timer, 0.0)
        self.assertTrue(game.player.alive)
        self.assertNotIn(enemy, game.enemies)

    def test_enemy_bullet_hits_player(self):
        game = self.make_game()
        game.player.invulnerable_timer = 0
        game.spawn_enemy_bullet(game.player.centerx, game.player.centery,
                                math.pi / 2, 0)
        game._update_collisions()
        self.assertFalse(game.player.alive)
        self.assertEqual(game.player.life, 2)


class GameFlowTests(GameTestCase):
    def test_both_modes_run_headless(self):
        for mode in ("normal", "meme"):
            game = self.make_game(mode)
            game.input_override = (0.4, 0.0, True)
            for _ in range(240):
                game.update(1.0 / 60.0)
                game.draw(self.app.canvas)
            self.assertIn(game.state, ("playing", "dying"))
            self.assertLessEqual(len(game.enemies), game.MAX_ENEMIES)
            self.assertLessEqual(len(game.enemy_bullets), game.MAX_ENEMY_BULLETS)
            self.assertLessEqual(len(game.player_bullets), game.MAX_PLAYER_BULLETS)
            self.assertLessEqual(len(game.powerups), game.MAX_POWERUPS)

    def test_invalid_mode_falls_back_to_normal(self):
        game = self.make_game("nonsense")
        self.assertEqual(game.mode, "normal")
        self.assertEqual(game.palette["bg"], (6, 10, 24))

    def test_pause_suspends_and_resumes(self):
        game = self.make_game()
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertEqual(game.state, "paused")
        time_before = game.game_time
        game.update(1.0 / 60.0)
        self.assertEqual(game.game_time, time_before)
        game.draw(self.app.canvas)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertEqual(game.state, "playing")

    def test_wave_five_spawns_boss(self):
        game = self.make_game()
        game.wave_timer = game.WAVE_DURATION
        game.wave = 4
        game.update(1.0 / 60.0)
        self.assertIsNotNone(game.boss)
        self.assertEqual(game.wave, 5)

        game.player.invulnerable_timer = 999.0
        for _ in range(300):
            game.update(1.0 / 60.0)
        self.assertTrue(game.boss.entered)
        self.assertGreater(game.boss.posY, 150.0)
        game.draw(self.app.canvas)

        boss = game.boss
        boss.hp = 1
        self.assertTrue(boss.damage(1))
        game._defeat_boss()
        self.assertIsNone(game.boss)
        self.assertEqual(game.wave, 6)
        self.assertGreaterEqual(len(game.powerups), 3)
        self.assertGreater(game.score, 0)

    def test_game_over_records_leaderboard(self):
        self.app.leaderboard = Leaderboard(path=os.path.join(self.tempdir, "scores.json"))
        game = self.make_game()
        game.score = 1234
        game.wave = 3
        game.kills = 7
        game.player.life = 0
        game.player.alive = False
        game.state = "dying"
        game.death_timer = 0.0
        game.update(1.0 / 60.0)

        self.assertEqual(game.state, "gameover")
        self.assertEqual(game.result["score"], 1234)
        self.assertEqual(game.result["rank"], 1)
        self.assertTrue(game.result["is_new"])
        self.assertEqual(self.app.leaderboard.best("normal"), 1234)
        self.assertTrue(os.path.isfile(os.path.join(self.tempdir, "scores.json")))
        self.assertEqual(game.announce_timer, 0.0)
        game.draw(self.app.canvas)

    def test_restart_and_menu_actions_call_app(self):
        game = self.make_game()
        with mock.patch.object(self.app, "start_game") as start:
            game._handle_action("restart")
        start.assert_called_once_with("normal")
        with mock.patch.object(self.app, "go_menu") as go_menu:
            game._handle_action("menu")
        go_menu.assert_called_once_with()

    def test_enemies_despawn_and_lists_trim(self):
        game = self.make_game()
        game.enemies = [
            EnemyAsteroid(VW, VH, self.app.resources.asteroid(0, 20),
                          x=100, y=VH + 500, radius=20, level="small")
        ]
        game.update(1.0 / 60.0)
        self.assertEqual(game.enemies, [])


class MenuTests(GameTestCase):
    def test_main_menu_keyboard_navigation(self):
        menu = Menu(self.app)
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
        self.assertEqual(menu.widgets.selected, 1)
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
        self.assertEqual(menu.widgets.selected, 0)
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        self.assertEqual(menu.screen, "mode")

    def test_mode_select_keyboard_and_mouse(self):
        menu = Menu(self.app)
        menu._set_screen("mode")
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
        self.assertEqual(menu.mode_focus, 1)
        with mock.patch.object(self.app, "start_game") as start:
            menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        start.assert_called_once_with("meme")

        menu = Menu(self.app)
        menu._set_screen("mode")
        menu.draw(self.app.canvas)
        with mock.patch.object(self.app, "start_game") as start:
            menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1),
                              menu.mode_rects[0].center)
        start.assert_called_once_with("normal")
        menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1),
                          menu.back_rect.center)
        self.assertEqual(menu.screen, "main")

    def test_main_menu_mouse_clicks_button(self):
        menu = Menu(self.app)
        button = menu.widgets.widgets[1]  # Leaderboard
        point = button.rect.center
        menu.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=point), point)
        menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1), point)
        self.assertEqual(menu.screen, "leaderboard")
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertEqual(menu.screen, "main")

    def test_settings_keyboard_toggle_and_slider(self):
        settings = self.app.settings
        original_muted = settings.muted
        menu = Menu(self.app)
        menu._set_screen("settings")
        # Widget order: music slider, sfx slider, mute toggle, ...
        for _ in range(2):
            menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
        self.assertEqual(menu.widgets.selected, 2)
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        self.assertNotEqual(settings.muted, original_muted)

        # Slider keyboard adjustment.
        music = menu.widgets.widgets[0]
        previous = music.value()
        menu.widgets.selected = 0
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT))
        self.assertLess(music.value(), previous)

    def test_every_menu_screen_draws(self):
        menu = Menu(self.app)
        for screen in ("main", "mode", "settings", "leaderboard", "controls"):
            menu._set_screen(screen)
            for _ in range(5):
                menu.update(1.0 / 60.0)
                menu.draw(self.app.canvas)
            self.assertEqual(menu.screen, screen)

    def test_escape_from_main_quits(self):
        menu = Menu(self.app)
        with mock.patch.object(self.app, "quit") as quit_app:
            menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        quit_app.assert_called_once_with()


class DisplayTests(GameTestCase):
    def test_letterboxing_viewport(self):
        try:
            pygame.display.set_mode((900, 900))
            self.app._compute_viewport()
            left, top, width, height = self.app.viewport
            self.assertEqual(left, 0)
            self.assertEqual(width, 900)
            self.assertEqual(height, 506)
            self.assertEqual(top, (900 - 506) // 2)
            self.app._present()
        finally:
            pygame.display.set_mode((VW, VH), pygame.RESIZABLE)
            self.app._compute_viewport()

    def test_real_run_loop_processes_events_and_quits(self):
        # A non-quit event forces the loop past the music-end branch that
        # previously referenced the nonexistent pygame.MUSIC_END constant.
        self.app.running = True
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEMOTION, pos=(0, 0), rel=(0, 0), buttons=(0, 0, 0)
        ))
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        self.app.run()
        self.assertFalse(self.app.running)
        self.app.running = True

    def test_screen_fade_transition(self):
        from AppClass import ScreenFade
        fade = ScreenFade()
        called = []
        fade.to_black(lambda: called.append("scene"))
        for _ in range(40):
            fade.update(1.0 / 60.0)
        self.assertEqual(called, ["scene"])
        self.assertFalse(fade.blocking)


if __name__ == "__main__":
    unittest.main()
