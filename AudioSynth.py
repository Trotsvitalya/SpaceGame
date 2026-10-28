"""Tiny procedural audio synth used for UI sounds and the meme soundtrack.

No external libraries or downloaded assets are required: sounds are generated
as signed 16-bit PCM and handed to pygame.mixer.  If the mixer is unavailable
(or uses an unexpected sample format) every function simply returns None.
"""

from __future__ import annotations

import array
import math
import random

import pygame

_SR = 44100


def _mixer_format():
    try:
        info = pygame.mixer.get_init()
    except pygame.error:
        return None
    if not info:
        return None
    frequency, sample_format, channels = info
    if sample_format != -16:
        return None
    return frequency, channels


def _clamp_sample(value):
    if value > 1.0:
        return 1.0
    if value < -1.0:
        return -1.0
    return value


def _sound_from_channels(left, right, volume=0.5):
    fmt = _mixer_format()
    if fmt is None:
        return None
    _, channels = fmt
    data = array.array("h")
    scale = 32767.0 * max(0.0, min(1.0, volume))
    if channels >= 2:
        for lval, rval in zip(left, right):
            data.append(int(_clamp_sample(lval) * scale))
            data.append(int(_clamp_sample(rval) * scale))
    else:
        for lval, rval in zip(left, right):
            data.append(int(_clamp_sample((lval + rval) * 0.5) * scale))
    try:
        return pygame.mixer.Sound(buffer=data.tobytes())
    except pygame.error:
        return None


def _sound_from_mono(samples, volume=0.5):
    return _sound_from_channels(samples, samples, volume)


def _envelope(position, total, attack=0.01, release=0.12):
    if total <= 0:
        return 0.0
    t = position / total
    if t < attack:
        return t / max(attack, 0.0001)
    if t > 1.0 - release:
        return max(0.0, (1.0 - t) / max(release, 0.0001))
    return 1.0


def sweep(start_hz, end_hz, duration, waveform="sine", volume=0.5, wobble=0.0):
    fmt = _mixer_format()
    if fmt is None:
        return None
    sample_rate = fmt[0]
    count = max(1, int(sample_rate * duration))
    phase = 0.0
    samples = []
    for index in range(count):
        t = index / count
        frequency = start_hz + (end_hz - start_hz) * t
        if wobble:
            frequency *= 1.0 + math.sin(t * math.pi * 18.0) * wobble
        phase += frequency / sample_rate
        phase %= 1.0
        if waveform == "square":
            value = 1.0 if phase < 0.5 else -1.0
        elif waveform == "triangle":
            value = 4.0 * abs(phase - 0.5) - 1.0
        elif waveform == "saw":
            value = phase * 2.0 - 1.0
        else:
            value = math.sin(phase * math.tau)
        samples.append(value * _envelope(index, count) * 0.8)
    return _sound_from_mono(samples, volume)


def noise_burst(duration, volume=0.5, lowpass=0.55):
    fmt = _mixer_format()
    if fmt is None:
        return None
    sample_rate = fmt[0]
    count = max(1, int(sample_rate * duration))
    rng = random.Random(1337)
    samples = []
    previous = 0.0
    for index in range(count):
        raw = rng.uniform(-1.0, 1.0)
        previous = previous * lowpass + raw * (1.0 - lowpass)
        samples.append(previous * _envelope(index, count, 0.005, 0.5))
    return _sound_from_mono(samples, volume)


def sequence(notes, volume=0.5, waveform="sine", gap=0.0):
    """notes: iterable of (frequency, duration) pairs."""
    fmt = _mixer_format()
    if fmt is None:
        return None
    sample_rate = fmt[0]
    samples = []
    for frequency, duration in notes:
        count = max(1, int(sample_rate * duration))
        gap_count = int(sample_rate * gap)
        for index in range(count):
            phase = (index * frequency / sample_rate) % 1.0
            if waveform == "square":
                value = 1.0 if phase < 0.5 else -1.0
            elif waveform == "triangle":
                value = 4.0 * abs(phase - 0.5) - 1.0
            else:
                value = math.sin(phase * math.tau)
            samples.append(value * _envelope(index, count, 0.02, 0.2) * 0.8)
        samples.extend([0.0] * gap_count)
    return _sound_from_mono(samples, volume)


def make_sfx():
    """Build the small built-in sound bank.  Failures are ignored."""
    bank = {}
    builders = {
        "ui_hover": lambda: sweep(900, 1000, 0.035, "sine", 0.12),
        "ui_click": lambda: sweep(520, 780, 0.075, "square", 0.22),
        "pickup": lambda: sequence([(660, 0.05), (880, 0.05), (1320, 0.09)], 0.35),
        "powerup": lambda: sequence([(440, 0.06), (660, 0.06), (880, 0.06), (1320, 0.14)], 0.4),
        "weapon": lambda: sweep(300, 1200, 0.28, "saw", 0.32),
        "shot_burst": lambda: sequence([(880, 0.03), (1180, 0.05)], 0.24, "square"),
        "shot_lance": lambda: sweep(170, 980, 0.22, "saw", 0.3),
        "shot_spread": lambda: sequence([(360, 0.035), (300, 0.045)], 0.22, "triangle"),
        "claw_slash": lambda: sweep(980, 120, 0.18, "saw", 0.34, wobble=0.12),
        "chainsaw": lambda: sweep(75, 245, 0.42, "saw", 0.38, wobble=0.22),
        "upgrade_open": lambda: sequence([(392, 0.07), (523, 0.07), (659, 0.12)], 0.32,
                                         "triangle"),
        "upgrade_apply": lambda: sequence([(523, 0.05), (659, 0.05), (784, 0.05),
                                           (1046, 0.14)], 0.4, "triangle"),
        "boss_phase": lambda: sweep(110, 430, 0.5, "saw", 0.4, wobble=0.12),
        "hazard_warn": lambda: sweep(320, 170, 0.34, "triangle", 0.28, wobble=0.05),
        "beam_charge": lambda: sweep(80, 520, 0.55, "sine", 0.3, wobble=0.03),
        "low_health": lambda: sequence([(330, 0.1), (262, 0.16)], 0.3, "square"),
        "shield": lambda: sweep(220, 520, 0.32, "sine", 0.35, wobble=0.08),
        "hit": lambda: noise_burst(0.12, 0.3),
        "enemy_shot": lambda: sweep(420, 160, 0.09, "square", 0.16),
        "wave": lambda: sequence([(330, 0.09), (440, 0.09), (660, 0.18)], 0.3, "triangle"),
        "boss_warn": lambda: sequence([(120, 0.25), (90, 0.35)], 0.45, "saw"),
        "meme_boing": lambda: sweep(180, 760, 0.26, "sine", 0.4, wobble=0.25),
        "meme_wow": lambda: sweep(800, 120, 0.55, "saw", 0.32, wobble=0.15),
        "meme_gameover": lambda: sequence(
            [(392, 0.18), (370, 0.18), (349, 0.18), (330, 0.42)], 0.4, "saw"
        ),
        "meme_pickup": lambda: sequence(
            [(523, 0.06), (659, 0.06), (784, 0.06), (1046, 0.16)], 0.4, "square"
        ),
        "meme_explode": lambda: noise_burst(0.22, 0.4, 0.25),
        "gameover": lambda: sequence([(220, 0.2), (196, 0.2), (175, 0.45)], 0.35, "triangle"),
    }
    for name, builder in builders.items():
        try:
            bank[name] = builder()
        except (pygame.error, ValueError, MemoryError):
            bank[name] = None
    return bank


def make_meme_loop():
    """Generate a short, deliberately goofy chiptune loop (~5.5 seconds)."""
    fmt = _mixer_format()
    if fmt is None:
        return None
    sample_rate, _ = fmt
    bpm = 128.0
    beats = 12.0
    duration = beats * 60.0 / bpm
    count = int(sample_rate * duration)
    if count <= 0:
        return None

    # A minor pentatonic-ish lead. None means a rest.
    lead_pattern = [440, 523, 659, 784, 659, 523, 587, 494,
                    440, 523, 659, 880, 784, 659, 587, 494,
                    392, 494, 587, 784, 659, 587, 523, 440]
    bass_pattern = [110, 110, 98, 98, 87, 87, 98, 98,
                    110, 110, 131, 131, 98, 98, 87, 87,
                    110, 110, 98, 98, 87, 87, 82, 82]

    left = [0.0] * count
    right = [0.0] * count
    rng = random.Random(2024)
    noise = [rng.uniform(-1.0, 1.0) for _ in range(count)]
    smoothed_noise = []
    prev = 0.0
    for value in noise:
        prev = prev * 0.7 + value * 0.3
        smoothed_noise.append(prev)

    eighth = 60.0 / bpm / 2.0
    for index in range(count):
        t = index / sample_rate
        eighth_index = int(t / eighth) % len(lead_pattern)
        local = (t % eighth) / eighth
        # Lead with a per-note envelope.
        note = lead_pattern[eighth_index]
        lead_env = math.sin(math.pi * min(1.0, local * 1.15)) * 0.22
        lead_phase = (t * note) % 1.0
        lead = (1.0 if lead_phase < 0.5 else -1.0) * lead_env
        # Bass on quarter notes.
        bass_index = int(t / (eighth * 2)) % len(bass_pattern)
        bass_note = bass_pattern[bass_index]
        bass_phase = (t * bass_note) % 1.0
        bass = (4.0 * abs(bass_phase - 0.5) - 1.0) * 0.16
        # Noise hats every half eighth.
        hat_phase = (t % eighth) / eighth
        hat = 0.0
        if hat_phase < 0.16:
            hat = smoothed_noise[index] * (1.0 - hat_phase / 0.16) * 0.11
        # A silly wobble every two bars.
        wobble = 1.0 + math.sin(t * math.tau * 0.31) * 0.04
        mono = (lead + bass + hat) * wobble
        pan = math.sin(t * 0.7) * 0.22
        left[index] = mono * (1.0 - pan)
        right[index] = mono * (1.0 + pan)
    return _sound_from_channels(left, right, 0.55)
