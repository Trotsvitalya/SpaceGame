"""Assets, fonts, localization and audio fallbacks."""

import os
import shutil
import tempfile
import unittest

import pygame

from AudioClass import AudioManager, music_files
from Localization import MEME_TAUNTS, STRINGS, LANGUAGE_NAMES, meme_taunt, tr
from ResourcesClass import MEME_PALETTE, NORMAL_PALETTE, Resources, palette_for
from SettingsClass import Settings


class AssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((320, 240))
        cls.resources = Resources(Settings())

    def test_assets_loaded(self):
        self.assertGreaterEqual(len(self.resources.backgrounds), 1)
        self.assertGreaterEqual(len(self.resources.ship_frames), 1)
        self.assertGreaterEqual(len(self.resources.ship_large), 1)
        self.assertGreaterEqual(len(self.resources.bullet_frames), 1)
        self.assertGreaterEqual(len(self.resources.asteroid_sources), 1)
        self.assertIsNotNone(self.resources.ship_small)

    def test_cached_surfaces(self):
        first = self.resources.asteroid(0, 30)
        second = self.resources.asteroid(0, 30)
        self.assertIs(first, second)
        self.assertEqual(first.get_size(), (60, 60))

        font = self.resources.font(20)
        self.assertIs(font, self.resources.font(20))
        image = self.resources.text("Тест Test 123", 20, (255, 255, 255))
        self.assertGreater(image.get_width(), 0)
        self.assertIs(image, self.resources.text("Тест Test 123", 20, (255, 255, 255)))

    def test_custom_chinese_font_renders_meme_glyphs(self):
        font = self.resources.font(38, kind="chinese")
        image = font.render("草船借箭 咚 吸 龍 福", True, (255, 220, 120))
        self.assertGreater(image.get_width(), 0)
        self.assertGreater(image.get_height(), 0)
        self.assertIs(font, self.resources.font(38, kind="chinese"))

    def test_generated_decor(self):
        self.assertEqual(self.resources.vignette.get_size(), (1280, 720))
        self.assertEqual(self.resources.menu_grid.get_size(), (1280, 720))
        self.assertEqual(self.resources.nebula("normal").get_size(), (1280, 1440))
        self.assertEqual(self.resources.menu_planet("meme").get_size()[0], 250)
        normal = self.resources.background(0, "normal")
        flipped = self.resources.background_flipped(0, "normal")
        self.assertEqual(normal.get_size(), flipped.get_size())
        glow = self.resources.glow(40, (255, 0, 0), 80)
        self.assertEqual(glow.get_size(), (80, 80))

    def test_palettes(self):
        self.assertIs(palette_for("normal"), NORMAL_PALETTE)
        self.assertIs(palette_for("meme"), MEME_PALETTE)
        self.assertIs(palette_for("anything"), NORMAL_PALETTE)
        for palette in (NORMAL_PALETTE, MEME_PALETTE):
            for key in ("bg", "text", "accent", "danger", "warning", "success"):
                self.assertIn(key, palette)

    def test_wrap_text(self):
        lines = self.resources.wrap_text(
            "Це досить довгий рядок для перевірки переносу слів у меню.", 18, 220
        )
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(line for line in lines))


class LocalizationTests(unittest.TestCase):
    def test_language_tables_match(self):
        self.assertEqual(set(STRINGS["uk"]), set(STRINGS["en"]))
        self.assertEqual(set(LANGUAGE_NAMES), {"uk", "en"})
        for language in ("uk", "en"):
            for key, value in STRINGS[language].items():
                self.assertIsInstance(value, str, key)
                self.assertTrue(value, key)

    def test_lookup_and_fallback(self):
        self.assertEqual(tr("uk", "new_game"), "НОВА ГРА")
        self.assertEqual(tr("en", "new_game"), "NEW GAME")
        self.assertEqual(tr("en", "does_not_exist"), "does_not_exist")
        self.assertEqual(tr("xx", "wave_announce", wave=3), "WAVE 3")
        # A bad placeholder must not raise.
        self.assertIn("{wave}", tr("en", "wave_announce", wrong=1))

    def test_meme_taunts(self):
        for language in ("uk", "en"):
            self.assertTrue(MEME_TAUNTS[language])
            self.assertEqual(meme_taunt(language, 0), MEME_TAUNTS[language][0])
            self.assertEqual(
                meme_taunt(language, len(MEME_TAUNTS[language])),
                MEME_TAUNTS[language][0],
            )
        self.assertTrue(meme_taunt("xx", 0))


class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.mixer.init()
        cls.settings = Settings()
        cls.audio = AudioManager(cls.settings)

    def test_music_file_filter(self):
        tempdir = tempfile.mkdtemp(prefix="spacegame-music-")
        self.addCleanup(shutil.rmtree, tempdir, True)
        for name in ("a.mp3", "b.ogg", "c.txt", "d.wav"):
            with open(os.path.join(tempdir, name), "wb") as handle:
                handle.write(b"")
        os.makedirs(os.path.join(tempdir, "nested.ogg"))
        found = music_files(tempdir)
        self.assertEqual([os.path.basename(path) for path in found],
                         ["a.mp3", "b.ogg", "d.wav"])
        self.assertEqual(music_files(os.path.join(tempdir, "missing")), [])

    def test_safe_noops_without_device(self):
        # Public methods must be safe regardless of the enabled flag.
        enabled = self.audio.enabled
        self.audio.enabled = False
        try:
            self.audio.play("shot")
            self.audio.play_music("menu")
            self.audio.pause_music()
            self.audio.resume_music()
            self.audio.stop_music()
            self.audio.on_music_end()
            self.audio.apply_settings()
        finally:
            self.audio.enabled = enabled

    def test_broken_music_does_not_crash(self):
        tempdir = tempfile.mkdtemp(prefix="spacegame-broken-")
        self.addCleanup(shutil.rmtree, tempdir, True)
        bad = os.path.join(tempdir, "broken.mp3")
        with open(bad, "wb") as handle:
            handle.write(b"this is definitely not an mp3")
        self.audio.playlist = [bad]
        self.audio.single_loop = False
        self.audio._play_current_track()
        # Every track failed: the playlist is cleared instead of retried.
        self.assertEqual(self.audio.playlist, [])
        self.audio.on_music_end()
        self.audio.stop_music()

    def test_settings_application(self):
        self.audio.settings.muted = True
        self.audio.apply_settings()
        self.assertEqual(self.audio._music_volume(), 0.0)
        self.audio.settings.muted = False
        self.audio.settings.music_volume = 0.4
        self.audio.apply_settings()
        self.assertAlmostEqual(self.audio._music_volume(), 0.4)

    def test_every_weapon_has_a_sound(self):
        if not self.audio.enabled:
            self.skipTest("audio device unavailable")
        from GameData import WEAPONS
        required = {spec["sound"] for spec in WEAPONS.values()}
        required.update({"upgrade_open", "upgrade_apply", "boss_phase",
                         "hazard_warn", "beam_charge", "low_health"})
        missing = {key for key in required if self.audio.sounds.get(key) is None}
        self.assertEqual(missing, set())

    def test_pause_without_music_is_safe(self):
        self.audio.stop_music()
        self.audio.pause_music()
        self.assertFalse(self.audio.music_paused)
        self.audio.resume_music()
        self.assertFalse(self.audio.music_paused)


if __name__ == "__main__":
    unittest.main()
