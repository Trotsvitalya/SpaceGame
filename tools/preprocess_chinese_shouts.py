"""Prepare short CC0 Mandarin battle-shout cues from the source recordings."""

from __future__ import annotations

import array
import os
import wave

import pygame


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOUND_DIR = os.path.join(ROOT, "assets", "sounds")
SAMPLE_RATE = 48_000
BITS_PER_SAMPLE = 2

# The source recordings are CC0 Freesound uploads. These short windows retain
# the original Mandarin group calls while excluding most of the long ambience.
CLIPS = (
    ("chinese_battle_shouts_source.mp3", 0.35, 1.20,
     "meme_chinese_shout_1.wav"),
    ("chinese_battle_shouts_source.mp3", 2.75, 3.60,
     "meme_chinese_shout_2.wav"),
    ("chinese_battle_shouts_open_source.mp3", 14.0, 14.9,
     "meme_chinese_shout_3.wav"),
)


def _prepare_clip(samples: array.array) -> array.array:
    if not samples:
        return samples
    mean = sum(samples) / len(samples)
    peak = max(abs(sample - mean) for sample in samples) or 1
    gain = min(3.0, 24_000 / peak)
    fade_in = min(int(SAMPLE_RATE * 0.015), len(samples) // 4)
    fade_out = min(int(SAMPLE_RATE * 0.10), len(samples) // 3)
    output = array.array("h")
    for index, sample in enumerate(samples):
        envelope = 1.0
        if fade_in and index < fade_in:
            envelope = min(envelope, index / fade_in)
        remaining = len(samples) - index - 1
        if fade_out and remaining < fade_out:
            envelope = min(envelope, remaining / fade_out)
        value = int((sample - mean) * gain * envelope)
        output.append(max(-32768, min(32767, value)))
    return output


def main() -> None:
    pygame.mixer.init(SAMPLE_RATE, -16, 1, allowedchanges=0)
    try:
        for source_name, start, end, output_name in CLIPS:
            source = pygame.mixer.Sound(os.path.join(SOUND_DIR, source_name))
            source_samples = array.array("h", source.get_raw())
            first = int(start * SAMPLE_RATE)
            last = int(end * SAMPLE_RATE)
            samples = _prepare_clip(source_samples[first:last])
            with wave.open(os.path.join(SOUND_DIR, output_name), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(BITS_PER_SAMPLE)
                output.setframerate(SAMPLE_RATE)
                output.writeframes(samples.tobytes())
    finally:
        pygame.mixer.quit()


if __name__ == "__main__":
    main()
