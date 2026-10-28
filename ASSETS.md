# Asset provenance and licensing

SpaceGame 2.0 uses a mix of original generated art, synthesized audio and media
that shipped with the original project. This file records what is original,
what is pre-existing and what that means if you redistribute the game.

The repository's [LICENSE](LICENSE) is the **Unlicense** (public domain). It
applies to the source code and to the original assets listed below. It does
**not** automatically relicense third-party media that predates 2.0.

## Original 2.0 assets

### Generated sprite art

All files under these folders were created specifically for SpaceGame 2.0 by
`tools/generate_assets.py` using procedural pygame drawing (no external images,
textures or AI-generated art):

| Folder | Files | Contents |
| --- | --- | --- |
| `assets/images/ships/` | 12 | 4 player ships × 3 animation frames |
| `assets/images/enemies/` | 15 | 5 enemy types × 3 animation frames |
| `assets/images/bosses/` | 4 | 2 bosses × 2 animation frames |
| `assets/images/planets/` | 4 | Azure, verdant, ember and meme planets |
| `assets/images/powerups/` | 5 | Shield, life, weapon, rapid, points icons |
| `assets/images/bullets/` | 6 | Player pulse/burst/lance/spread and enemy orb/plasma |

Total: **46 PNG files**. The generator is deterministic enough to reproduce the
shipped look and writes only into the folders above.

**License:** dedicated to the public domain under the same Unlicense as the
project. You may copy, modify, redistribute or sell them.

To regenerate them:

```bash
python tools/generate_assets.py
```

### Synthesized audio

`AudioSynth.py` synthesizes the combat and UI sound effects at runtime (signed
16-bit PCM handed to `pygame.mixer`). No audio files are written or shipped for
these effects. This includes weapon fire, boss phase stingers, hazard warnings,
beam charge, upgrade chimes, low-health alerts, UI clicks/hovers and the Meme
mode procedural loop fallback.

**License:** original work, dedicated to the public domain under the Unlicense.

### Screenshots

`screenshots/2.0/*.jpg` are captures of this game produced by the headless QA
harness. They show only original game content and may be reused with the
project.

## Pre-existing assets (not relicensed)

These files shipped with SpaceGame before the 2.0 work and are kept for
compatibility. Their original source and license are **not recorded in this
repository**, so they remain under whatever terms they were originally
distributed with and are excluded from the Unlicense dedication above.

| Path | Contents | Notes |
| --- | --- | --- |
| `assets/images/asteroids/` | Asteroid sprites | Pre-2.0 media |
| `assets/images/asteroidsBoom/` | Explosion animation frames | Pre-2.0 media |
| `assets/images/backgrounds/` | Parallax backgrounds | Pre-2.0 media |
| `assets/images/userBullets/` | Legacy player bullet frames | Pre-2.0 media |
| `assets/images/userStarShips/` | Legacy player ship frames | Pre-2.0 media |
| `assets/music/BackgroundMenu.mp3` | Menu music | Pre-2.0 media |
| `assets/music/GameProcess/*.mp3` | Normal-mode soundtrack | Pre-2.0 media |
| `assets/sounds/*.mp3` | Shot/crash/game-over effects | Pre-2.0 media |
| `assets/fonts/*.ttf` | Bundled decorative fonts | Pre-2.0 media |
| `screenshots/*.png` | Earlier screenshots | Captures of pre-2.0 builds |

If you plan to redistribute SpaceGame commercially, verify the rights for these
files or replace them. The game is designed to keep running when images, fonts
or audio are missing: procedural fallbacks are used for missing sprites and the
audio layer degrades to silence.

## Fonts

- `assets/fonts/Space Age.ttf` is used only for large Latin display text.
- UI/body text uses an installed system font with Cyrillic coverage (Segoe UI,
  Tahoma, Arial, DejaVu Sans, Liberation Sans or Noto Sans). System fonts are
  **not** redistributed with the game.
- The other TTFs in `assets/fonts/` are pre-existing and unused by the 2.0 UI.

## Music added by players

`assets/music/Meme/` and the normal playlist folders are scanned at runtime.
Any music you add there remains your responsibility; it is not part of the
project and must not be committed unless you own or license it.

## Third-party code

Only Python, Pygame/pygame-ce and the standard library are required. See
`requirements.txt`; those packages keep their own licenses.
