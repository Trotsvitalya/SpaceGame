"""Asset-backed sound effects plus a graceful fallback to procedural audio."""

from __future__ import annotations

import os
import random

import pygame

from AudioSynth import make_meme_loop, make_sfx
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
        self.paused = False
        self.last_played = {}
        try:
            if pygame.mixer.get_init():
                self.enabled = True
                pygame.mixer.set_num_channels(24)
                pygame.mixer.set_reserved(1)
                self.meme_loop_channel = pygame.mixer.Channel(0)
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

    # ---------------------------------------------------------------- music
    def _music_volume(self):
        return 0.0 if self.settings.muted else self.settings.music_volume

    def _stop_all_music(self):
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
        try:
            pygame.mixer.music.pause()
        except pygame.error:
            pass
        if self.meme_loop_channel is not None:
            try:
                self.meme_loop_channel.pause()
            except pygame.error:
                pass

    def resume_music(self):
        if not self.enabled:
            return
        self.paused = False
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
        if self.settings.muted:
            for index in range(1, pygame.mixer.get_num_channels()):
                try:
                    pygame.mixer.Channel(index).set_volume(0.0)
                except pygame.error:
                    break
        else:
            for index in range(1, pygame.mixer.get_num_channels()):
                try:
                    pygame.mixer.Channel(index).set_volume(self.settings.sfx_volume)
                except pygame.error:
                    break
