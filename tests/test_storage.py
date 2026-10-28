"""Settings, JSON helpers and leaderboard persistence."""

import json
import os
import shutil
import tempfile
import unittest

from SettingsClass import DEFAULT_SETTINGS, Leaderboard, Settings
from utils import (circle_hit, format_score, format_time, normalize,
                   read_json, segment_circle_hit, write_json)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="spacegame-test-")
        self.addCleanup(shutil.rmtree, self.tempdir, True)
        self.settings_path = os.path.join(self.tempdir, "settings.json")
        self.scores_path = os.path.join(self.tempdir, "scores.json")


class SettingsTests(TempDirTestCase):
    def test_missing_file_creates_defaults(self):
        settings = Settings.load(self.settings_path)
        self.assertTrue(os.path.isfile(self.settings_path))
        self.assertEqual(settings.music_volume, DEFAULT_SETTINGS["music_volume"])
        self.assertEqual(settings.sfx_volume, DEFAULT_SETTINGS["sfx_volume"])
        self.assertEqual(settings.language, "uk")
        self.assertEqual(settings.mode, "normal")

    def test_roundtrip(self):
        settings = Settings.load(self.settings_path)
        settings.music_volume = 0.25
        settings.sfx_volume = 0.9
        settings.muted = True
        settings.fullscreen = True
        settings.language = "en"
        settings.mode = "meme"
        settings.screen_shake = False
        settings.show_fps = True
        self.assertTrue(settings.save(self.settings_path))

        loaded = Settings.load(self.settings_path)
        self.assertAlmostEqual(loaded.music_volume, 0.25)
        self.assertAlmostEqual(loaded.sfx_volume, 0.9)
        self.assertTrue(loaded.muted)
        self.assertTrue(loaded.fullscreen)
        self.assertEqual(loaded.language, "en")
        self.assertEqual(loaded.mode, "meme")
        self.assertFalse(loaded.screen_shake)
        self.assertTrue(loaded.show_fps)

    def test_ship_and_quality_roundtrip(self):
        settings = Settings.load(self.settings_path)
        settings.ship = "engineer"
        settings.effects_quality = 0
        settings.reduced_flash = True
        settings.auto_pause = False
        self.assertTrue(settings.save(self.settings_path))

        loaded = Settings.load(self.settings_path)
        self.assertEqual(loaded.ship, "engineer")
        self.assertEqual(loaded.effects_quality, 0)
        self.assertTrue(loaded.reduced_flash)
        self.assertFalse(loaded.auto_pause)

    def test_old_settings_gain_new_defaults(self):
        # Version 2 files predate the hangar and graphics options.
        with open(self.settings_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "music_volume": 0.4, "language": "en"}, handle)
        settings = Settings.load(self.settings_path)
        self.assertEqual(settings.ship, "fighter")
        self.assertEqual(settings.effects_quality, 2)
        self.assertFalse(settings.reduced_flash)
        self.assertTrue(settings.auto_pause)
        self.assertAlmostEqual(settings.music_volume, 0.4)
        self.assertEqual(settings.language, "en")

    def test_version_three_gains_accessibility_defaults(self):
        with open(self.settings_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 3, "ship": "tank", "effects_quality": 1},
                      handle)
        settings = Settings.load(self.settings_path)
        self.assertEqual(settings.ship, "tank")
        self.assertEqual(settings.effects_quality, 1)
        self.assertFalse(settings.reduced_flash)
        self.assertTrue(settings.auto_pause)

    def test_version_four_gains_difficulty_default(self):
        with open(self.settings_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 4, "ship": "engineer", "mode": "meme"},
                      handle)
        settings = Settings.load(self.settings_path)
        self.assertEqual(settings.difficulty, "normal")
        self.assertEqual(settings.ship, "engineer")
        self.assertEqual(settings.mode, "meme")

    def test_difficulty_roundtrip_and_sanitizing(self):
        settings = Settings({"difficulty": "hard"})
        self.assertEqual(settings.difficulty, "hard")
        self.assertEqual(Settings({"difficulty": "impossible"}).difficulty,
                         "normal")
        settings.save(self.settings_path)
        self.assertEqual(Settings.load(self.settings_path).difficulty, "hard")

    def test_invalid_ship_and_quality_are_sanitized(self):
        settings = Settings({
            "ship": "battlecruiser",
            "effects_quality": "ultra",
        })
        self.assertEqual(settings.ship, "fighter")
        self.assertEqual(settings.effects_quality, 2)

        settings = Settings({"ship": "tank", "effects_quality": 9})
        self.assertEqual(settings.ship, "tank")
        self.assertEqual(settings.effects_quality, 2)

    def test_corrupt_file_falls_back_and_is_repaired(self):
        with open(self.settings_path, "w", encoding="utf-8") as handle:
            handle.write('{"music_volume": 0.2, "broken":')
        settings = Settings.load(self.settings_path)
        self.assertEqual(settings.music_volume, DEFAULT_SETTINGS["music_volume"])
        repaired = read_json(self.settings_path, None)
        self.assertIsInstance(repaired, dict)
        self.assertEqual(repaired["version"], DEFAULT_SETTINGS["version"])

    def test_invalid_values_are_sanitized(self):
        data = {
            "music_volume": 12.0,
            "sfx_volume": -3,
            "muted": "yes",
            "fullscreen": 1,
            "language": "fr",
            "mode": "chaos",
            "screen_shake": None,
            "show_fps": [],
        }
        settings = Settings(data)
        self.assertEqual(settings.music_volume, 1.0)
        self.assertEqual(settings.sfx_volume, 0.0)
        self.assertFalse(settings.muted)
        self.assertFalse(settings.fullscreen)
        self.assertEqual(settings.language, "uk")
        self.assertEqual(settings.mode, "normal")
        self.assertTrue(settings.screen_shake)
        self.assertFalse(settings.show_fps)

    def test_non_dict_json_is_ignored(self):
        with open(self.settings_path, "w", encoding="utf-8") as handle:
            json.dump([1, 2, 3], handle)
        settings = Settings.load(self.settings_path)
        self.assertEqual(settings.language, "uk")

    def test_copy_is_independent(self):
        settings = Settings()
        clone = settings.copy()
        clone.language = "en"
        clone.music_volume = 0.1
        self.assertEqual(settings.language, "uk")
        self.assertAlmostEqual(settings.music_volume, DEFAULT_SETTINGS["music_volume"])

    def test_language_cycle(self):
        settings = Settings()
        self.assertEqual(settings.toggle_language(), "en")
        self.assertEqual(settings.toggle_language(), "uk")
        self.assertEqual(settings.cycle_language(), "en")

    def test_unwritable_path_does_not_raise(self):
        settings = Settings()
        directory = os.path.join(self.tempdir, "as-directory")
        os.makedirs(directory)
        self.assertFalse(settings.save(directory))


class LeaderboardTests(TempDirTestCase):
    def test_add_sorts_and_truncates(self):
        board = Leaderboard(path=self.scores_path)
        for score in range(100, 1300, 100):
            rank, is_new, best_before = board.add("normal", score, 1, 0)
        self.assertEqual(len(board.board("normal")), 10)
        scores = [entry["score"] for entry in board.board("normal")]
        self.assertEqual(scores[0], 1200)
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(rank, 1)
        self.assertTrue(is_new)
        self.assertEqual(best_before, 1100)
        self.assertEqual(board.best("normal"), 1200)
        self.assertEqual(board.best("meme"), 0)

    def test_zero_score_is_ignored(self):
        board = Leaderboard(path=self.scores_path)
        rank, is_new, best_before = board.add("normal", 0, 1, 0)
        self.assertIsNone(rank)
        self.assertFalse(is_new)
        self.assertEqual(best_before, 0)
        self.assertEqual(board.board("normal"), [])

    def test_persists_across_instances(self):
        board = Leaderboard(path=self.scores_path)
        board.add("meme", 777, 3, 9)
        loaded = Leaderboard.load(self.scores_path)
        self.assertEqual(loaded.best("meme"), 777)
        entry = loaded.board("meme")[0]
        self.assertEqual(entry["wave"], 3)
        self.assertEqual(entry["kills"], 9)
        self.assertTrue(entry["date"])

    def test_corrupt_file_is_tolerated(self):
        with open(self.scores_path, "w", encoding="utf-8") as handle:
            handle.write("not json")
        board = Leaderboard.load(self.scores_path)
        self.assertEqual(board.board("normal"), [])
        board.add("normal", 50, 1, 1)
        self.assertEqual(Leaderboard.load(self.scores_path).best("normal"), 50)

    def test_legacy_flat_format_is_migrated(self):
        legacy = {"scores": [{"score": 42, "wave": 2, "kills": 1, "date": "2024"}]}
        board = Leaderboard(legacy)
        self.assertEqual(board.best("normal"), 42)
        self.assertEqual(board.best("meme"), 0)

    def test_malformed_entries_are_skipped(self):
        data = {
            "normal": [
                "nope",
                {"score": "bad"},
                {"score": 10, "wave": "x", "kills": -5, "date": 1234},
                {"score": 30, "wave": 2, "kills": 2, "date": "2024-01-01"},
            ]
        }
        board = Leaderboard(data)
        board_entries = board.board("normal")
        self.assertEqual(len(board_entries), 2)
        self.assertEqual(board_entries[0]["score"], 30)
        self.assertEqual(board_entries[1]["wave"], 1)
        self.assertEqual(board_entries[1]["kills"], 0)
        self.assertEqual(board_entries[1]["date"], "")

    def test_unknown_mode_falls_back_to_normal(self):
        board = Leaderboard({"normal": [{"score": 5, "wave": 1, "kills": 1}],
                             "meme": []})
        self.assertEqual(board.board("unknown")[0]["score"], 5)
        board.add("unknown", 9, 1, 0)
        self.assertEqual(board.best("normal"), 9)


class UtilsTests(unittest.TestCase):
    def test_circle_and_segment_collision(self):
        self.assertTrue(circle_hit(0, 0, 5, 8, 0, 4))
        self.assertFalse(circle_hit(0, 0, 5, 30, 0, 4))
        # A fast segment crossing the circle must hit even when both endpoints
        # are outside of it.
        self.assertTrue(segment_circle_hit(-50, 0, 50, 0, 0, 0, 5))
        self.assertFalse(segment_circle_hit(-50, 20, 50, 20, 0, 0, 5))
        self.assertTrue(segment_circle_hit(0, 0, 0, 0, 0, 0, 5))

    def test_formatting(self):
        self.assertEqual(format_score(1234567), "1 234 567")
        self.assertEqual(format_score(None), "0")
        self.assertEqual(format_time(65), "01:05")
        self.assertEqual(format_time(-4), "00:00")

    def test_normalize(self):
        x, y = normalize(3, 4)
        self.assertAlmostEqual(x, 0.6)
        self.assertAlmostEqual(y, 0.8)
        self.assertEqual(normalize(0, 0), (0.0, 0.0))

    def test_json_roundtrip_and_failure(self):
        path = os.path.join(tempfile.mkdtemp(prefix="spacegame-json-"), "x.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        self.assertTrue(write_json(path, {"a": "тест"}))
        self.assertEqual(read_json(path, None), {"a": "тест"})
        self.assertEqual(read_json(path + ".missing", {"d": 1}), {"d": 1})
        self.assertFalse(write_json(os.path.dirname(path), {"a": 1}))


if __name__ == "__main__":
    unittest.main()
