"""Campaign data, persistence, mission flow and menu tests (headless SDL)."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

os.environ.setdefault(
    "SPACEGAME_CONFIG_DIR",
    tempfile.mkdtemp(prefix="spacegame-campaign-tests-"),
)

import pygame

from AppClass import App
from Balance import DIFFICULTY_ORDER
from BulletClass import Bullet
from CampaignData import (MISSION_BY_ID, MISSION_IDS, MISSIONS,
                          first_mission_id, mission_by_id, mission_index,
                          mission_objective, next_mission_id)
from CampaignProgress import MAX_SALVAGE_BONUS, CampaignProgress
from GameData import SHIP_ORDER
from GameProcessClass import GameProcess
from Localization import STRINGS
from MenuClass import Menu


class CampaignDataTests(unittest.TestCase):
    def test_mission_ids_are_unique_and_linear(self):
        self.assertEqual(len(MISSION_IDS), 10)
        self.assertEqual(len(set(MISSION_IDS)), 10)
        self.assertEqual(MISSION_IDS[0], "m01")
        self.assertEqual(MISSION_IDS[-1], "m10")
        for index, mission_id in enumerate(MISSION_IDS):
            self.assertEqual(mission_index(mission_id), index)
            following = next_mission_id(mission_id)
            if index + 1 < len(MISSION_IDS):
                self.assertEqual(following, MISSION_IDS[index + 1])
            else:
                self.assertIsNone(following)

    def test_every_mission_has_playable_data(self):
        for mission in MISSIONS:
            with self.subTest(mission=mission["id"]):
                self.assertEqual(mission_by_id(mission["id"]), mission)
                self.assertTrue(0 <= mission["zone"] <= 3)
                self.assertTrue(2 <= mission["waves"] <= 4)
                self.assertIn(mission["boss"], (None, "dreadnought", "sentinel"))
                self.assertGreater(mission["reward_salvage"], 0)
                self.assertTrue(mission["enemies"])
                self.assertIn("asteroid", mission["enemies"])
                self.assertTrue(0.0 < mission["asteroid_ratio"] < 1.0)
                self.assertGreaterEqual(mission["max_elites"], 0)
                self.assertTrue(mission["story"])
                self.assertGreaterEqual(mission["boss_scale"], 1.0)

    def test_mission_bosses_stay_inside_their_zone(self):
        bosses = [mission for mission in MISSIONS if mission["boss"]]
        self.assertEqual([mission["id"] for mission in bosses],
                         ["m03", "m06", "m08", "m10"])
        for mission in bosses:
            self.assertIn(mission["zone"], (0, 1, 2, 3))

    def test_every_mission_string_exists_in_both_languages(self):
        for language in ("uk", "en"):
            strings = STRINGS[language]
            for mission in MISSIONS:
                keys = [mission["name_key"], mission["brief_key"]]
                keys.extend(mission["story"])
                for key in keys:
                    with self.subTest(language=language, key=key):
                        self.assertIn(key, strings)
                        self.assertTrue(strings[key].strip())
                for kind in mission["enemies"]:
                    self.assertIn("enemy_" + kind, strings)
            for key in ("campaign", "campaign_title", "campaign_start",
                        "campaign_replay", "campaign_next", "campaign_locked",
                        "campaign_completed", "campaign_available",
                        "campaign_complete", "mission_complete",
                        "mission_failed", "story_next_hint",
                        "campaign_victory_hint", "campaign_fail_hint"):
                self.assertIn(key, strings)

    def test_objective_text_matches_boss_presence(self):
        for language in ("uk", "en"):
            for mission in MISSIONS:
                text = mission_objective(language, mission).lower()
                mentions_boss = "boss" in text or "бос" in text
                if mission["boss"]:
                    self.assertTrue(mentions_boss)
                else:
                    self.assertFalse(mentions_boss)


class CampaignProgressTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="spacegame-campaign-progress-")
        self.addCleanup(shutil.rmtree, self.tempdir, True)
        self.path = os.path.join(self.tempdir, "campaign.json")

    def test_missing_file_creates_default_progress(self):
        progress = CampaignProgress.load(self.path)
        self.assertTrue(os.path.isfile(self.path))
        self.assertEqual(progress.unlocked, ["m01"])
        self.assertEqual(progress.completed, [])
        self.assertEqual(progress.completed_count(), 0)
        self.assertEqual(progress.difficulty, "normal")
        self.assertEqual(progress.salvage_bonus, 0)
        self.assertEqual(first_mission_id(progress), "m01")

    def test_first_clear_unlocks_and_rewards_once(self):
        progress = CampaignProgress({}, path=self.path)
        summary = progress.complete_mission(
            "m01", score=1200, kills=9, time=44.0, reward=6
        )
        self.assertTrue(summary["first_completion"])
        self.assertEqual(summary["next_mission"], "m02")
        self.assertEqual(progress.salvage_bonus, 6)
        self.assertEqual(progress.unlocked, ["m01", "m02"])
        self.assertTrue(progress.is_completed("m01"))
        self.assertEqual(progress.best_for("m01")["score"], 1200)

        # Replaying must not grant the permanent reward twice.
        summary = progress.complete_mission(
            "m01", score=800, kills=2, time=10.0, reward=6
        )
        self.assertFalse(summary["first_completion"])
        self.assertEqual(progress.salvage_bonus, 6)
        self.assertEqual(progress.best_for("m01")["score"], 1200)
        self.assertEqual(progress.completed.count("m01"), 1)

        # A better replay updates the stored best result.
        progress.complete_mission("m01", score=2000, kills=12, time=30.0,
                                  reward=6)
        self.assertEqual(progress.best_for("m01")["score"], 2000)
        self.assertEqual(progress.best_for("m01")["kills"], 12)

    def test_progress_round_trip_and_resume_mission(self):
        progress = CampaignProgress({}, path=self.path)
        progress.begin_mission("m02", ship="tank", difficulty="hard")
        progress.complete_mission("m01", score=500, kills=4, time=20.0,
                                  reward=6)
        progress.complete_mission("m02", score=900, kills=8, time=30.0,
                                  reward=8)
        reloaded = CampaignProgress.load(self.path)
        self.assertEqual(reloaded.completed, ["m01", "m02"])
        self.assertEqual(reloaded.unlocked, ["m01", "m02", "m03"])
        self.assertEqual(reloaded.ship, "tank")
        self.assertEqual(reloaded.difficulty, "hard")
        self.assertEqual(reloaded.salvage_bonus, 14)
        self.assertEqual(reloaded.last_mission, "m03")
        self.assertEqual(reloaded.next_open_mission(), "m03")
        self.assertEqual(reloaded.progress_ratio(), 0.2)

    def test_corrupt_file_is_repaired(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        progress = CampaignProgress.load(self.path)
        self.assertEqual(progress.unlocked, ["m01"])
        with open(self.path, encoding="utf-8") as handle:
            repaired = json.load(handle)
        self.assertEqual(repaired["unlocked"], ["m01"])
        self.assertEqual(repaired["completed"], [])
        self.assertEqual(repaired["version"], CampaignProgress.VERSION)

    def test_hand_edited_values_are_sanitized(self):
        data = {
            "completed": ["m04", "nope", 4, "m04"],
            "unlocked": [],
            "best": {
                "m04": {"score": -5, "kills": "lots", "time": -2},
                "m99": {"score": 10},
                "m01": "broken",
            },
            "ship": "ufo",
            "difficulty": "impossible",
            "salvage_bonus": 999999,
            "last_mission": "m99",
        }
        progress = CampaignProgress(data, path=self.path)
        self.assertEqual(progress.completed, ["m04"])
        # Completing m04 unlocks m05 but never the skipped m01-m03.
        self.assertIn("m04", progress.unlocked)
        self.assertIn("m05", progress.unlocked)
        self.assertEqual(progress.best["m04"]["score"], 0)
        self.assertEqual(progress.best["m04"]["kills"], 0)
        self.assertNotIn("m99", progress.best)
        self.assertNotIn("m01", progress.best)
        self.assertEqual(progress.ship, "fighter")
        self.assertEqual(progress.difficulty, "normal")
        self.assertEqual(progress.salvage_bonus, MAX_SALVAGE_BONUS)
        self.assertIsNone(progress.last_mission)

    def test_bonus_is_capped_and_copy_is_independent(self):
        progress = CampaignProgress({"salvage_bonus": 490}, path=self.path)
        progress.complete_mission("m01", reward=50)
        self.assertEqual(progress.salvage_bonus, MAX_SALVAGE_BONUS)
        clone = progress.copy()
        clone.completed.append("m02")
        self.assertNotIn("m02", progress.completed)


class CampaignFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.app = App(force_windowed=True)
        cls.app.settings.ship = "fighter"
        cls.app.settings.mode = "normal"
        cls.app.settings.difficulty = "normal"
        cls.app.resources.select_ship("fighter")

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="spacegame-campaign-flow-")
        self.addCleanup(shutil.rmtree, self.tempdir, True)
        self.path = os.path.join(self.tempdir, "campaign.json")
        self.app.campaign_progress = CampaignProgress({}, path=self.path)
        self.app.settings.ship = "fighter"
        self.app.settings.difficulty = "normal"
        self.app.resources.select_ship("fighter")

    def make_game(self, mission_id, difficulty="normal", completed=None):
        if completed:
            self.app.campaign_progress = CampaignProgress(
                {"completed": list(completed)}, path=self.path
            )
        mission = mission_by_id(mission_id)
        game = GameProcess(self.app, "normal", difficulty=difficulty,
                           mission=mission,
                           progress=self.app.campaign_progress)
        self.addCleanup(game.on_exit)
        return game

    def test_mission_launch_sets_zone_waves_story_and_bonus(self):
        self.app.campaign_progress.salvage_bonus = 12
        game = self.make_game("m01")
        self.assertTrue(game.campaign)
        self.assertEqual(game.state, "story")
        self.assertEqual(game.story_index, 0)
        self.assertEqual(game.total_waves, 2)
        self.assertEqual(game.zone_id, "core")
        self.assertEqual(game.salvage, 12)
        self.assertEqual(game.backdrop.zone["id"], "core")

        game._skip_story()
        self.assertEqual(game.state, "playing")
        game.update(1.0 / 60.0)
        game.draw(self.app.canvas)
        self.assertLessEqual(len(game.enemies), game.MAX_ENEMIES)

    def test_story_cards_advance_and_skip(self):
        game = self.make_game("m01")
        self.assertEqual(len(game.story_keys), 2)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                             key=pygame.K_RETURN))
        self.assertEqual(game.story_index, 1)
        self.assertEqual(game.state, "story")
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s))
        self.assertEqual(game.state, "playing")
        self.assertEqual(game.story_index, len(game.story_keys))
        game.draw(self.app.canvas)

    def test_non_boss_mission_completes_after_final_wave(self):
        game = self.make_game("m01")
        game._skip_story()
        game.player.life = 3
        game.wave = game.total_waves
        game.wave_timer = game.WAVE_DURATION
        game.update(1.0 / 60.0)
        self.assertEqual(game.state, "victory")
        self.assertTrue(game.campaign_result["summary"]["first_completion"])
        self.assertEqual(game.campaign_result["summary"]["next_mission"],
                         "m02")
        self.assertFalse(game.campaign_result["campaign_complete"])
        self.assertTrue(self.app.campaign_progress.is_completed("m01"))
        self.assertTrue(self.app.campaign_progress.is_unlocked("m02"))
        self.assertEqual(self.app.campaign_progress.salvage_bonus, 6)
        game.draw(self.app.canvas)

        # Reload from disk: progress survives a restart.
        reloaded = CampaignProgress.load(self.path)
        self.assertIn("m01", reloaded.completed)
        self.assertIn("m02", reloaded.unlocked)

    def test_boss_mission_spawns_scaled_boss_and_completes(self):
        game = self.make_game("m08")
        game._skip_story()
        game.wave = game.total_waves
        game.wave_timer = game.WAVE_DURATION
        game.update(1.0 / 60.0)
        self.assertIsNotNone(game.boss)
        self.assertEqual(game.boss.kind, "dreadnought")
        self.assertEqual(game.boss.max_hp,
                         int(round(game.balance.boss_hp(15) * 1.1)))
        self.assertEqual(game.wave, game.total_waves)
        game.boss.hp = 1
        game.player_bullets = [Bullet(game.boss.posX, game.boss.posY,
                                      damage=50)]
        game._update_collisions()
        self.assertEqual(game.state, "victory")
        self.assertTrue(self.app.campaign_progress.is_completed("m08"))
        game.draw(self.app.canvas)

    def test_campaign_failure_does_not_touch_leaderboard(self):
        board_before = list(self.app.leaderboard.board("normal"))
        game = self.make_game("m01")
        game._skip_story()
        game.player.life = 1
        game.player.invulnerable_timer = 0.0
        game._player_hit()
        for _ in range(130):
            game.update(1.0 / 60.0)
        self.assertEqual(game.state, "gameover")
        self.assertTrue(game.result["campaign"])
        self.assertEqual(game.result["rank"], 0)
        self.assertEqual(list(self.app.leaderboard.board("normal")),
                         board_before)
        self.assertFalse(self.app.campaign_progress.is_completed("m01"))
        self.assertTrue(any(button.action == "campaign_replay"
                            for button in game.over_group.widgets))
        game.draw(self.app.canvas)

    def test_final_mission_marks_campaign_complete(self):
        completed = list(MISSION_IDS[:9])
        game = self.make_game("m10", completed=completed)
        self.assertTrue(self.app.campaign_progress.is_unlocked("m10"))
        game._skip_story()
        game.wave = game.total_waves
        game.wave_timer = game.WAVE_DURATION
        game.update(1.0 / 60.0)
        self.assertIsNotNone(game.boss)
        self.assertEqual(game.boss.kind, "sentinel")
        game.boss.hp = 1
        game.player_bullets = [Bullet(game.boss.posX, game.boss.posY,
                                      damage=50)]
        game._update_collisions()
        self.assertEqual(game.state, "victory")
        self.assertTrue(game.campaign_result["campaign_complete"])
        self.assertEqual(self.app.campaign_progress.completed_count(), 10)
        game.draw(self.app.canvas)

    def test_campaign_difficulty_drives_balance(self):
        for difficulty in DIFFICULTY_ORDER:
            with self.subTest(difficulty=difficulty):
                game = self.make_game("m01", difficulty=difficulty)
                self.assertEqual(game.difficulty, difficulty)
                self.assertEqual(game.balance.difficulty, difficulty)
                game._skip_story()
                game.wave = game.total_waves
                game.wave_timer = game.WAVE_DURATION
                game.update(1.0 / 60.0)
                self.assertEqual(game.state, "victory")

    def test_every_ship_can_launch_a_campaign_mission(self):
        original = self.app.settings.ship
        self.addCleanup(self.app.resources.select_ship, original)
        self.addCleanup(setattr, self.app.settings, "ship", original)
        for ship in SHIP_ORDER:
            with self.subTest(ship=ship):
                self.app.settings.ship = ship
                self.app.resources.select_ship(ship)
                game = self.make_game("m01")
                self.assertEqual(game.ship_kind, ship)
                game._skip_story()
                game.update(1.0 / 60.0)
                game.draw(self.app.canvas)


class CampaignMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.app = App(force_windowed=True)
        cls.app.settings.ship = "fighter"
        cls.app.resources.select_ship("fighter")

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="spacegame-campaign-menu-")
        self.addCleanup(shutil.rmtree, self.tempdir, True)
        self.path = os.path.join(self.tempdir, "campaign.json")
        self.app.campaign_progress = CampaignProgress({}, path=self.path)
        self.app.settings.mode = "normal"
        self.app.settings.difficulty = "normal"
        self.app.settings.language = "uk"
        self.addCleanup(lambda: self.app.resources.select_ship("fighter"))
        self.addCleanup(self._restore_settings)

    def _restore_settings(self):
        self.app.settings.mode = "normal"
        self.app.settings.difficulty = "normal"
        self.app.settings.language = "uk"

    def make_menu(self):
        return Menu(self.app)

    def test_main_menu_has_campaign_entry(self):
        menu = self.make_menu()
        actions = [button.action for button in menu.widgets.widgets]
        self.assertIn("campaign", actions)
        self.assertIn("new_game", actions)
        self.assertEqual(len(actions), 7)

    def test_campaign_list_navigation_and_draw(self):
        menu = self.make_menu()
        menu._set_screen("campaign")
        self.assertEqual(menu.screen, "campaign")
        menu.draw(self.app.canvas)
        self.assertEqual(len(menu.campaign_rows), 10)
        self.assertEqual(menu.campaign_focus, 0)
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                             key=pygame.K_DOWN))
        self.assertEqual(menu.campaign_focus, 1)
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
        self.assertEqual(menu.campaign_focus, 0)
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                             key=pygame.K_RETURN))
        self.assertEqual(menu.screen, "campaign_brief")
        self.assertEqual(menu.campaign_mission_id, "m01")

    def test_campaign_brief_shows_mission_and_difficulty(self):
        menu = self.make_menu()
        menu._open_campaign_brief("m01")
        menu.draw(self.app.canvas)
        self.assertEqual(menu.screen, "campaign_brief")
        self.assertEqual(len(menu.widgets.widgets), 3)
        menu.widgets.selected = 0
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                             key=pygame.K_RIGHT))
        self.assertNotEqual(self.app.campaign_progress.difficulty, "normal")
        self.assertEqual(self.app.settings.difficulty,
                         self.app.campaign_progress.difficulty)
        reloaded = CampaignProgress.load(self.path)
        self.assertEqual(reloaded.difficulty,
                         self.app.campaign_progress.difficulty)

    def test_locked_mission_cannot_start(self):
        menu = self.make_menu()
        menu._open_campaign_brief("m02")
        self.assertFalse(self.app.campaign_progress.is_unlocked("m02"))
        menu.draw(self.app.canvas)
        with mock.patch.object(self.app, "start_campaign") as start:
            menu._start_campaign()
        start.assert_not_called()

    def test_unlocked_mission_starts_with_saved_choices(self):
        menu = self.make_menu()
        self.app.campaign_progress.difficulty = "story"
        self.app.campaign_progress.save()
        menu._open_campaign_brief("m01")
        menu.draw(self.app.canvas)
        with mock.patch.object(self.app, "start_campaign") as start:
            menu._start_campaign()
        start.assert_called_once_with("m01", self.app.settings.mode, "story")

    def test_completed_mission_shows_replay(self):
        self.app.campaign_progress.complete_mission(
            "m01", score=999, kills=3, time=20.0, reward=6
        )
        menu = self.make_menu()
        menu._set_screen("campaign")
        menu.draw(self.app.canvas)
        menu._open_campaign_brief("m01")
        menu.draw(self.app.canvas)
        labels = [button.label() for button in menu.widgets.widgets]
        self.assertIn("ПОВТОРИТИ МІСІЮ", labels)

    def test_app_start_campaign_records_progress(self):
        with mock.patch.object(self.app, "transition_to") as transition:
            mission = self.app.start_campaign("m01", "meme", "hard")
        self.assertIsNotNone(mission)
        self.assertEqual(mission["id"], "m01")
        self.assertEqual(self.app.settings.mode, "meme")
        self.assertEqual(self.app.settings.difficulty, "hard")
        self.assertEqual(self.app.campaign_progress.last_mission, "m01")
        self.assertEqual(self.app.campaign_progress.ship, "fighter")
        self.assertEqual(self.app.campaign_progress.difficulty, "hard")
        transition.assert_called_once()

    def test_all_campaign_screens_draw_without_errors(self):
        menu = self.make_menu()
        for screen in ("campaign", "campaign_brief"):
            with self.subTest(screen=screen):
                menu._set_screen(screen)
                for _ in range(40):
                    menu.update(1.0 / 60.0)
                    menu.draw(self.app.canvas)
                self.assertEqual(menu.screen, screen)


if __name__ == "__main__":
    unittest.main()
