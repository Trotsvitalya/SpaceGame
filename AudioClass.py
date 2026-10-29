"""Asset-backed sound effects plus a graceful fallback to procedural audio."""

from __future__ import annotations

import os
import random

import pygame

from AudioSynth import make_coffin_dance_loop, make_meme_loop, make_sfx
from utils import ROOT

MUSIC_MENU = os.path.join(ROOT, "assets", "music", "BackgroundMenu.mp3")
MUSIC_NORMAL_DIR = os.path.join(ROOT, "assets", "music", "GameProcess")
MUSIC_MEME_DIR = os.path.join(ROOT, "assets", "music", "Meme")
SOUND_DIR = os.path.join(ROOT, "assets", "sounds")
AUDIO_EXTENSIONS = (".mp3", ".ogg", ".wav", ".flac")
MUSIC_END_EVENT = pygame.USEREVENT + 1

ASSET_SOUNDS = {
    "shot": "Shot.mp3",
    "shot_alt": "Shot1.mp3",
    "crash": "Crash.mp3",
    "gameover": "GameOver.mp3",
    "meme_chinese_shout_1": "meme_chinese_shout_1.wav",
    "meme_chinese_shout_2": "meme_chinese_shout_2.wav",
    "meme_chinese_shout_3": "meme_chinese_shout_3.wav",
    "meme_envelopes": "envelopes.mp3",
    "meme_dragon": "dragon.mp3",
    "meme_boat": "boat.mp3",
}


def music_files(directory):
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    found = []
    for name in names:
        if name.lower().endswith(AUDIO_EXTENSIONS):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                found.append(path)
    found.sort()
    return found


class AudioManager:
    """Owns music playback and a pooled sound bank.

    Every public method is safe to call when audio initialisation failed.
    """

    def __init__(self, settings):
        self.settings = settings
        self.enabled = False
        self.sounds = {}
        self.current_key = None
        self.playlist = []
        self.track_index = 0
        self.single_loop = False
        self.meme_loop_channel = None
        self.meme_loop_sound = None
        self.coffin_channel = None
        self.coffin_sound = None
        self.boat_channel = None
        self.paused = False
        self.music_paused = False
        self.last_played = {}
        self.tiger_sound = None
        self.tiger_channel = None
        try:
            if pygame.mixer.get_init():
                self.enabled = True
                pygame.mixer.set_num_channels(24)
                # Keep dedicated channels for music, Coffin Dance, Tiger, and
                # the boat loop so pooled effects can never cut them off.
                pygame.mixer.set_reserved(4)
                self.meme_loop_channel = pygame.mixer.Channel(0)
                self.coffin_channel = pygame.mixer.Channel(1)
                self.tiger_channel = pygame.mixer.Channel(2)
                self.boat_channel = pygame.mixer.Channel(3)
                # pygame-ce 2.5.x has no pygame.MUSIC_END constant, so use a
                # project event and register it with the music player.
                pygame.mixer.music.set_endevent(MUSIC_END_EVENT)
        except pygame.error:
            self.enabled = False

        if self.enabled:
            self._load_assets()
            try:
                self.sounds.update({k: v for k, v in make_sfx().items() if v is not None})
            except (pygame.error, ValueError, MemoryError):
                pass
        self.apply_settings()

    def _load_assets(self):
        for key, filename in ASSET_SOUNDS.items():
            path = os.path.join(SOUND_DIR, filename)
            try:
                self.sounds[key] = pygame.mixer.Sound(path)
            except (pygame.error, OSError, FileNotFoundError):
                # Leave the key absent; callers treat audio as optional.
                continue

    # ------------------------------------------------------------------ sfx
    def play(self, name, volume=1.0, throttle_ms=0):
        if not self.enabled or self.settings.muted:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        now = pygame.time.get_ticks()
        if throttle_ms:
            last = self.last_played.get(name, -100000)
            if now - last < throttle_ms:
                return
            self.last_played[name] = now
        try:
            channel = pygame.mixer.find_channel(True)
            if channel is None:
                return
            channel.set_volume(max(0.0, min(1.0, self.settings.sfx_volume * volume)))
            channel.play(sound)
        except pygame.error:
            pass

    def play_meme_shout(self, volume=0.65):
        available = [name for name in (
            "meme_chinese_shout_1", "meme_chinese_shout_2",
            "meme_chinese_shout_3",
        ) if self.sounds.get(name) is not None]
        if available:
            self.play(random.choice(available), volume, throttle_ms=100)

    def play_tiger_ultimate(self):
        """Play the supplied Tiger audio exactly once per activation, if valid."""
        if not self.enabled or self.settings.muted:
            return False
        if self.tiger_sound is None:
            path = os.path.join(SOUND_DIR, "tiger_hu_hu_sheng_wei.mp3")
            if not os.path.isfile(path):
                path = os.path.join(SOUND_DIR, "audio.mp3")
            try:
                self.tiger_sound = pygame.mixer.Sound(path)
            except (pygame.error, OSError):
                return False
        try:
            if self.tiger_channel is None:
                return False
            # A previous tail may still be playing when a new video begins.
            # Restart it on its reserved channel instead of dropping this cue.
            self.tiger_channel.stop()
            self.tiger_channel.set_volume(self.settings.sfx_volume)
            self.tiger_channel.play(self.tiger_sound)
            return True
        except pygame.error:
            return False

    def play_boat_loop(self):
        """Loop the boat ambience only while the Straw Boat event is visible."""
        if (not self.enabled or self.settings.muted or self.boat_channel is None):
            return False
        sound = self.sounds.get("meme_boat")
        if sound is None:
            return False
        try:
            if self.boat_channel.get_busy():
                return True
            self.boat_channel.set_volume(self.settings.sfx_volume * 0.55)
            self.boat_channel.play(sound, loops=-1)
            return True
        except pygame.error:
            return False

    def stop_boat_loop(self):
        try:
            if self.boat_channel is not None:
                self.boat_channel.stop()
        except pygame.error:
            pass

    def pause_tiger_ultimate(self):
        try:
            if self.tiger_channel is not None:
                self.tiger_channel.pause()
        except pygame.error:
            pass

    def resume_tiger_ultimate(self):
        try:
            if self.tiger_channel is not None:
                self.tiger_channel.unpause()
        except pygame.error:
            pass

    def tiger_ultimate_busy(self):
        try:
            return bool(self.tiger_channel is not None and
                        self.tiger_channel.get_busy())
        except pygame.error:
            return False

    def stop_tiger_ultimate(self):
        try:
            if self.tiger_channel is not None:
                self.tiger_channel.stop()
        except pygame.error:
            pass

    # ---------------------------------------------------------------- music
    def _music_volume(self):
        return 0.0 if self.settings.muted else self.settings.music_volume

    def _stop_all_music(self):
        self.music_paused = False
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass
        if self.meme_loop_channel is not None:
            try:
                self.meme_loop_channel.stop()
            except pygame.error:
                pass

    def stop_music(self):
        self._stop_all_music()
        self.stop_coffin_dance()
        self.stop_boat_loop()
        self.current_key = None
        self.playlist = []
        self.paused = False

    def play_music(self, context="menu", mode="normal"):
        if not self.enabled:
            return
        key = (context, mode)
        already_playing = False
        if self.current_key == key and not self.paused:
            if self.meme_loop_channel is not None and self.meme_loop_channel.get_busy():
                already_playing = True
            elif self.playlist:
                try:
                    already_playing = pygame.mixer.music.get_busy()
                except pygame.error:
                    already_playing = False
        if already_playing:
            self.apply_settings()
            return

        self._stop_all_music()
        self.current_key = key
        self.playlist = []
        self.track_index = 0
        self.single_loop = False
        self.paused = False
        self.music_paused = False

        if context == "menu":
            if os.path.isfile(MUSIC_MENU):
                try:
                    pygame.mixer.music.load(MUSIC_MENU)
                    pygame.mixer.music.set_volume(self._music_volume())
                    pygame.mixer.music.play(-1)
                    return
                except pygame.error:
                    pass
            files = music_files(MUSIC_NORMAL_DIR)
            if files:
                self._start_playlist(files, loop=True)
            return

        if mode == "meme":
            meme_files = music_files(MUSIC_MEME_DIR)
            if meme_files:
                self._start_playlist(meme_files, loop=False)
                return
            if self._start_meme_loop():
                return
        files = music_files(MUSIC_NORMAL_DIR)
        if files:
            self._start_playlist(files, loop=False)

    def _start_meme_loop(self):
        if self.meme_loop_channel is None:
            return False
        if self.meme_loop_sound is None:
            try:
                self.meme_loop_sound = make_meme_loop()
            except (pygame.error, ValueError, MemoryError):
                self.meme_loop_sound = None
        if self.meme_loop_sound is None:
            return False
        try:
            self.meme_loop_channel.set_volume(self._music_volume() * 0.75)
            self.meme_loop_channel.play(self.meme_loop_sound, loops=-1)
            return True
        except pygame.error:
            return False

    def play_coffin_dance(self):
        """Loop the original synthesized dance beat while its event is active."""
        if not self.enabled or self.settings.muted or self.coffin_channel is None:
            return False
        try:
            if self.coffin_channel.get_busy():
                return True
            if self.coffin_sound is None:
                self.coffin_sound = make_coffin_dance_loop()
            if self.coffin_sound is None:
                return False
            self.coffin_channel.set_volume(self._music_volume() * 0.72)
            self.coffin_channel.play(self.coffin_sound, loops=-1)
            return True
        except (pygame.error, ValueError, MemoryError):
            return False

    def stop_coffin_dance(self):
        try:
            if self.coffin_channel is not None:
                self.coffin_channel.stop()
        except pygame.error:
            pass

    def _start_playlist(self, files, loop=False):
        self.playlist = list(files)
        random.shuffle(self.playlist)
        self.track_index = 0
        self.single_loop = bool(loop or len(self.playlist) == 1)
        self._play_current_track()

    def _play_current_track(self):
        if not self.playlist:
            return
        attempts = len(self.playlist)
        while attempts > 0:
            attempts -= 1
            if self.track_index >= len(self.playlist):
                self.track_index = 0
            path = self.playlist[self.track_index]
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(self._music_volume())
                pygame.mixer.music.play(-1 if self.single_loop else 0)
                return
            except pygame.error:
                self.track_index += 1
        # Every file failed: clear the playlist rather than retrying forever.
        self.playlist = []

    def on_music_end(self):
        if not self.playlist or self.single_loop or self.paused:
            return
        self.track_index += 1
        self._play_current_track()

    def pause_music(self):
        if not self.enabled:
            return
        self.paused = True
        self.music_paused = False
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.pause()
                self.music_paused = True
        except pygame.error:
            pass
        if self.meme_loop_channel is not None:
            try:
                if self.meme_loop_channel.get_busy():
                    self.meme_loop_channel.pause()
                    self.music_paused = True
            except pygame.error:
                pass
        if self.coffin_channel is not None:
            try:
                if self.coffin_channel.get_busy():
                    self.coffin_channel.pause()
            except pygame.error:
                pass
        if self.boat_channel is not None:
            try:
                if self.boat_channel.get_busy():
                    self.boat_channel.pause()
            except pygame.error:
                pass

    def resume_music(self):
        if not self.enabled:
            return
        self.paused = False
        if self.coffin_channel is not None:
            try:
                self.coffin_channel.unpause()
            except pygame.error:
                pass
        if self.boat_channel is not None:
            try:
                self.boat_channel.unpause()
            except pygame.error:
                pass
        if not self.music_paused:
            return
        self.music_paused = False
        try:
            pygame.mixer.music.unpause()
        except pygame.error:
            pass
        if self.meme_loop_channel is not None:
            try:
                self.meme_loop_channel.unpause()
            except pygame.error:
                pass

    def apply_settings(self):
        """Apply volume/mute changes immediately."""
        if not self.enabled:
            return
        try:
            pygame.mixer.music.set_volume(self._music_volume())
        except pygame.error:
            pass
        if self.meme_loop_channel is not None:
            try:
                self.meme_loop_channel.set_volume(self._music_volume() * 0.75)
            except pygame.error:
                pass
        if self.coffin_channel is not None:
            try:
                self.coffin_channel.set_volume(self._music_volume() * 0.72)
            except pygame.error:
                pass
        if self.settings.muted:
            for index in range(2, pygame.mixer.get_num_channels()):
                try:
                    pygame.mixer.Channel(index).set_volume(0.0)
                except pygame.error:
                    break
        else:
            for index in range(2, pygame.mixer.get_num_channels()):
                try:
                    pygame.mixer.Channel(index).set_volume(self.settings.sfx_volume)
                except pygame.error:
                    break
