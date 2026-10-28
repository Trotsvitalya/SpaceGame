"""Balance, difficulty and post-boss recovery tests.

These scenarios are reproducible: the random seed and the frame step are
fixed, so the printed report can be compared between runs.  They are not a
substitute for human playtesting; they verify bounded scaling, hazard
concurrency and the size of the step from wave 5 to wave 6.
"""

import math
import os
import random
import shutil
import tempfile
import unittest

os.environ.setdefault(
    "SPACEGAME_CONFIG_DIR",
    tempfile.mkdtemp(prefix="spacegame-balance-tests-"),
)

import pygame

from AppClass import App
from Balance import Balance, DIFFICULTY, DIFFICULTY_ORDER
from BulletClass import Bullet
from EnemyAsteroidClass import BossEnemy, EnemyShip
from GameData import SHIPS, SHIP_ORDER, WEAPONS
from GameProcessClass import GameProcess
from MenuClass import Menu
from utils import VH, VW


class BalanceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.app = App(force_windowed=True)

    def setUp(self):
        self._original_ship = self.app.settings.ship
        self._original_difficulty = self.app.settings.difficulty
        self.addCleanup(self._restore)
        self.tempdir = tempfile.mkdtemp(prefix="spacegame-balance-")
        self.addCleanup(shutil.rmtree, self.tempdir, True)

    def _restore(self):
        self.app.settings.ship = self._original_ship
        self.app.settings.difficulty = self._original_difficulty
        self.app.resources.select_ship(self._original_ship)

    def make_game(self, mode="normal", difficulty=None, ship="fighter"):
        self.app.settings.ship = ship
        self.app.settings.difficulty = difficulty or "normal"
        self.app.resources.select_ship(ship)
        game = GameProcess(self.app, mode, difficulty=difficulty)
        self.addCleanup(game.on_exit)
        return game


class SaturationTests(unittest.TestCase):
    def test_wave_curves_are_monotonic_and_bounded(self):
        for key, spec in DIFFICULTY.items():
            with self.subTest(difficulty=key):
                balance = Balance(key)
                hp = [balance.enemy_hp(wave) for wave in range(1, 301)]
                speed = [balance.enemy_speed(wave) for wave in range(1, 301)]
                bullets = [balance.bullet_speed(wave) for wave in range(1, 301)]
                fire = [balance.enemy_fire(wave) for wave in range(1, 301)]
                spawn = [balance.spawn_interval(wave) for wave in range(1, 301)]

                for series in (hp, speed, bullets):
                    self.assertEqual(series, sorted(series))
                self.assertEqual(fire, sorted(fire, reverse=True))
                self.assertEqual(spawn, sorted(spawn, reverse=True))

                self.assertAlmostEqual(hp[0], 1.0)
                self.assertAlmostEqual(hp[-1], spec.hp_cap, places=2)
                self.assertAlmostEqual(speed[-1], spec.speed_cap, places=2)
                self.assertAlmostEqual(bullets[-1], spec.bullet_cap, places=2)
                self.assertGreaterEqual(fire[-1], 1.0 - spec.fire_cap)
                self.assertAlmostEqual(spawn[-1], spec.spawn_floor, places=2)

                # No wave may exceed its finite ceiling.
                self.assertLessEqual(max(hp), spec.hp_cap + 1e-9)
                self.assertLessEqual(max(speed), spec.speed_cap + 1e-9)
                self.assertLessEqual(max(bullets), spec.bullet_cap + 1e-9)
                self.assertGreaterEqual(balance.telegraph(0.1), 0.95)

    def test_boss_health_is_bounded(self):
        for key, spec in DIFFICULTY.items():
            with self.subTest(difficulty=key):
                balance = Balance(key)
                values = [balance.boss_hp(wave) for wave in range(1, 101)]
                self.assertEqual(values, sorted(values))
                self.assertLess(values[4], values[9])
                self.assertEqual(balance.boss_hp(20), balance.boss_hp(100))
                self.assertLess(balance.boss_hp(100), 300 * spec.boss_hp_scale)

    def test_wave_six_is_not_a_difficulty_spike(self):
        for key in DIFFICULTY_ORDER:
            with self.subTest(difficulty=key):
                balance = Balance(key)
                hp_ratio = balance.enemy_hp(6) / balance.enemy_hp(5)
                spawn_ratio = balance.spawn_interval(6) / balance.spawn_interval(5)
                bullet_ratio = balance.bullet_speed(6) / balance.bullet_speed(5)
                speed_ratio = balance.enemy_speed(6) / balance.enemy_speed(5)
                self.assertLess(hp_ratio, 1.12)
                self.assertLess(bullet_ratio, 1.10)
                self.assertLess(speed_ratio, 1.10)
                # Spawns must not accelerate by more than 10% right after a boss.
                self.assertGreater(spawn_ratio, 0.90)

    def test_difficulty_presets_are_ordered(self):
        story, normal, hard = (Balance("story"), Balance("normal"),
                               Balance("hard"))
        self.assertLess(story.enemy_hp(6), normal.enemy_hp(6))
        self.assertLess(normal.enemy_hp(6), hard.enemy_hp(6))
        self.assertGreater(story.spawn_interval(6), normal.spawn_interval(6))
        self.assertGreater(normal.spawn_interval(6), hard.spawn_interval(6))
        self.assertLess(story.max_zones, normal.max_zones)
        self.assertLess(normal.max_zones, hard.max_zones)
        self.assertGreater(story.post_boss_grace, normal.post_boss_grace)
        self.assertEqual(normal.telegraph(1.2), 1.2)

    def test_unknown_difficulty_falls_back_to_normal(self):
        self.assertEqual(Balance("impossible").difficulty, "normal")


class EnemyScalingTests(BalanceTestCase):
    def test_menu_difficulty_choice_is_persisted(self):
        self.app.settings.difficulty = "normal"
        menu = Menu(self.app)
        menu._set_screen("settings")
        difficulty = menu.widgets.widgets[10]
        before = self.app.settings.difficulty
        menu.widgets.selected = 10
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                             key=pygame.K_RIGHT))
        self.assertNotEqual(self.app.settings.difficulty, before)
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                             key=pygame.K_RIGHT))
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                             key=pygame.K_RIGHT))
        self.assertEqual(self.app.settings.difficulty, before)
        menu.draw(self.app.canvas)
        self.assertIsNotNone(difficulty)

    def test_enemy_stats_stop_growing(self):
        late = Balance("normal")
        ship = EnemyShip("elite", "normal", self.app.resources, wave=500)
        self.assertEqual(ship.max_hp,
                         max(1, int(round(EnemyShip.STATS["elite"]["hp"]
                                         * late.enemy_hp(500)))))
        self.assertLessEqual(ship.max_hp,
                             math.ceil(EnemyShip.STATS["elite"]["hp"]
                                       * late.spec.hp_cap))
        self.assertLessEqual(ship.vy,
                             EnemyShip.STATS["elite"]["speed"]
                             * late.spec.speed_cap + 1e-6)

    def test_hazards_are_capped_per_difficulty(self):
        for key in DIFFICULTY_ORDER:
            with self.subTest(difficulty=key):
                game = self.make_game(difficulty=key)
                expected = game.balance.spec
                for index in range(12):
                    game.spawn_danger_zone(100 + index * 40, 200, radius=80)
                    game.spawn_beam(100 + index * 40, 200, math.pi / 2)
                self.assertLessEqual(len(game.danger_zones), expected.max_zones)
                self.assertLessEqual(len(game.beams), expected.max_beams)
                game._update_hazards(1.0 / 60.0)
                self.assertLessEqual(game.metrics.max_zones, expected.max_zones)
                self.assertLessEqual(game.metrics.max_beams, expected.max_beams)

    def test_boss_attacks_respect_hazard_caps(self):
        for key in DIFFICULTY_ORDER:
            with self.subTest(difficulty=key):
                game = self.make_game(difficulty=key)
                boss = BossEnemy("normal", self.app.resources, 10,
                                 kind="dreadnought",
                                 balance=game.balance)
                boss.entered = True
                boss._attack_zones(game, [])
                boss._attack_beam_sweep(game, [])
                self.assertLessEqual(len(game.danger_zones),
                                     game.balance.max_zones)
                self.assertLessEqual(len(game.beams),
                                     game.balance.max_beams)


class PostBossRecoveryTests(BalanceTestCase):
    def test_boss_defeat_heals_clears_and_grants_a_grace_window(self):
        game = self.make_game()
        game.player.life = 1
        game.wave = 10
        game._spawn_boss()
        boss = game.boss
        self.assertIsNotNone(boss)
        boss.hp = 1
        game.player_bullets = [Bullet(boss.posX, boss.posY, damage=5)]
        game._update_collisions()

        self.assertIsNone(game.boss)
        self.assertEqual(game.wave, 11)
        self.assertEqual(game.state, "upgrade")
        self.assertGreaterEqual(game.player.life, 2)
        self.assertEqual(len(game.powerups), 3)
        self.assertEqual(game.danger_zones, [])
        self.assertEqual(game.beams, [])
        self.assertGreaterEqual(game.spawn_grace, 2.0)
        self.assertGreaterEqual(game.spawn_timer, game.spawn_grace - 1e-6)

        game._close_upgrade()
        before = game.metrics.total_spawns
        for _ in range(120):  # 2 seconds, still inside the grace window
            game.update(1.0 / 60.0)
        self.assertEqual(game.metrics.total_spawns, before)
        for _ in range(180):  # cross the 3 second grace window
            game.update(1.0 / 60.0)
        self.assertGreater(game.metrics.total_spawns, before)

    def test_low_health_wave_start_offers_recovery(self):
        game = self.make_game()
        game.player.life = 1
        game.wave = 7
        game.wave_timer = game.WAVE_DURATION
        game._update_waves(1.0 / 60.0)
        self.assertTrue(any(powerup.kind in ("shield", "life")
                            for powerup in game.powerups))

    def test_low_health_changes_drop_table(self):
        game = self.make_game()
        game.player.life = 1
        game.player.shield_timer = 0.0
        drops = {"shield": 0, "life": 0}
        random.seed(17)
        enemy = EnemyShip("bomber", "normal", self.app.resources,
                          x=400, y=300, wave=6)
        for _ in range(200):
            game.powerups.clear()
            enemy.posX, enemy.posY = 400, 300
            game._maybe_drop(enemy)
            for powerup in game.powerups:
                if powerup.kind in drops:
                    drops[powerup.kind] += 1
        self.assertGreater(sum(drops.values()), 5)


class ShipViabilityTests(unittest.TestCase):
    def test_every_ship_has_recovery_and_usable_damage(self):
        for kind in SHIP_ORDER:
            with self.subTest(ship=kind):
                stats = SHIPS[kind]
                self.assertGreaterEqual(stats["life"], 3)
                self.assertGreater(stats["max_life"], stats["life"])
                self.assertGreaterEqual(stats["speed"], 300.0)

                weapon = WEAPONS[stats["weapon"]]
                shots = weapon["pattern"][1]
                burst = sum(shot[4] for shot in shots)
                dps = burst / stats["fire_interval"]
                self.assertGreater(dps, 4.0)


class ScenarioTests(BalanceTestCase):
    """Seeded wave-6 scenarios for every ship and difficulty.

    The autopilot only dodges incoming projectiles and hazard centres; it is
    deliberately simple so the report shows *exposure* rather than perfect
    play.  Human playtesting is still required for final tuning.
    """

    DURATION = 18.0
    STEP = 1.0 / 60.0

    @staticmethod
    def _autopilot(game, elapsed):
        player = game.player
        if not player.alive:
            return 0.0, 0.0, False
        cx, cy = player.centerx, player.centery
        target_x = VW * 0.5 + math.sin(elapsed * 0.8) * 300.0
        target_y = VH - 230.0
        vx = (target_x - cx) * 0.9
        vy = (target_y - cy) * 1.2

        for zone in game.danger_zones:
            dx, dy = cx - zone.x, cy - zone.y
            distance = math.hypot(dx, dy)
            if distance < zone.radius + 90.0:
                weight = (zone.radius + 90.0 - distance) / max(1.0, zone.radius)
                vx += dx / max(1.0, distance) * 420.0 * weight
                vy += dy / max(1.0, distance) * 420.0 * weight

        for bullet in game.enemy_bullets:
            dx, dy = cx - bullet.posX, cy - bullet.posY
            distance = math.hypot(dx, dy)
            if 1.0 < distance < 150.0:
                weight = (150.0 - distance) / 150.0
                vx += dx / distance * 360.0 * weight
                vy += dy / distance * 360.0 * weight

        length = math.hypot(vx, vy)
        if length <= 1e-6:
            return 0.0, 0.0, True
        return vx / length, vy / length, True

    def run_scenario(self, difficulty, ship, wave=6):
        random.seed(20260501)
        game = self.make_game(difficulty=difficulty, ship=ship)
        game.wave = wave
        game.wave_timer = 0.0
        game.spawn_timer = 0.0
        game.player.life = game.player.max_life
        game.player.invulnerable_timer = 0.0

        elapsed = 0.0
        frames = int(self.DURATION / self.STEP)
        for _ in range(frames):
            game.input_override = self._autopilot(game, elapsed)
            game.update(self.STEP)
            elapsed += self.STEP
            if game.state in ("gameover", "upgrade", "paused"):
                break
        return game

    def test_wave_six_scenarios(self):
        cases = [("normal", ship, 6) for ship in SHIP_ORDER]
        cases += [(difficulty, "fighter", 6) for difficulty in DIFFICULTY_ORDER
                  if difficulty != "normal"]
        cases += [(difficulty, "fighter", 8) for difficulty in DIFFICULTY_ORDER]
        report = []
        for difficulty, ship, wave in cases:
            game = self.run_scenario(difficulty, ship, wave)
            metrics = game.metrics
            summary = metrics.summary()
            report.append(
                "scenario difficulty={:<6} ship={:<11} wave={:<2} spawns={:<3} "
                "rate={:.2f}/s powerups={:<2} damage={} zones={} beams={} "
                "state={}".format(
                    difficulty, ship, wave, summary["total_spawns"],
                    summary["spawn_rate_per_s"], summary["total_powerups"],
                    summary["damage_taken"], summary["max_concurrent_zones"],
                    summary["max_concurrent_beams"], game.state,
                )
            )
            self.assertIn(game.state, ("playing", "dying", "gameover"))
            self.assertLessEqual(metrics.max_zones, game.balance.max_zones)
            self.assertLessEqual(metrics.max_beams, game.balance.max_beams)
            self.assertGreater(metrics.total_spawns, 2)
            self.assertLessEqual(metrics.total_spawns, 60)
            self.assertLessEqual(metrics.damage_taken, SHIPS[ship]["max_life"])
            rate = summary["spawn_rate_per_s"]
            self.assertLessEqual(rate, 1.35 / game.balance.spec.spawn_floor)
        print("\n" + "\n".join(report))


if __name__ == "__main__":
    unittest.main()
