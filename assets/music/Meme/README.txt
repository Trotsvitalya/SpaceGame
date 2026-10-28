# Meme mode music

Drop any `.mp3`, `.ogg`, `.wav` or `.flac` files into this folder
(`assets/music/Meme/`) and Meme mode will play them.

Notes:

- Files are picked up at runtime; no code changes are needed.
- If this folder is empty, the game uses a built-in procedural meme loop.
- Broken or unsupported files are skipped automatically.  The game falls back
  to the normal soundtrack and keeps running.
- Keep the files reasonably small; the whole playlist is scanned when a Meme
  run starts.
