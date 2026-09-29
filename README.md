# Reel Maker

Turn a long video, Zoom call, webinar or podcast into 2 to 5 ready-to-post vertical Reels, using Claude Code or Codex on your own computer. Free and open source (MIT). Version 2.0.0.

**Before:** a 45-minute recording with your best 40 seconds buried somewhere in the middle, a wide landscape frame, quiet audio and no captions.

**After:** a folder on your Desktop with:

- `Reel 1 - <name>.mp4`, `Reel 2 ...`: vertical 1080x1920 clips, each opening on its strongest line, framed around the speaker's face (full head, proper headroom), with a hook headline, word-by-word highlighted captions, your logo and brand color, a "Comment WORD" call-to-action at the end, a progress bar, and audio leveled to -14 LUFS (the loudness Instagram, TikTok and YouTube expect)
- `captions.txt`: a ready-to-paste post caption for each reel, hook first
- `contact-sheet.jpg`: stills from every reel so you can check them at a glance
- `.srt` caption files, a `report.md` of automatic checks, and the transcript

Nothing is uploaded or posted. You review, you post.

## What it does

1. **Transcribes** with word-level timestamps on your machine (mlx-whisper on Apple Silicon Macs, faster-whisper on Windows, Intel Macs and Linux). Or use a transcript you already have (SRT/VTT).
2. **Finds the best moments** hook-first: every 20 to 60 second window is scored on the opening line, whether it stands alone, the payoff, pace and length. Then your AI assistant reads the whole transcript and makes the final picks, headlines and captions like an editor would.
3. **Cuts and frames** each moment in 9:16 with face detection, following the speaker across shots. Screen shares and gallery views get a "fit" layout (whole picture over a blurred background). Podcasts get a branded audiogram.
4. **Renders** captions and graphics that work with any ffmpeg (no special builds), normalizes loudness and checks every file: length, size, audio, loudness, captions burned in, clean decode.
5. **Premium mode (optional):** a more designed look rendered with Remotion: serif headline with an italic accent word, glowing video card, animated caption pills, speaker name tag and CTA pill in your brand colors.

## Install (no GitHub knowledge needed)

1. On this page, click the green **Code** button, then **Download ZIP**. (Or download `reel-maker.zip` from the latest release on the right.)
2. Unzip it. You get a folder; inside is a folder called **reel-maker**.
3. Open **Claude Code** or **Codex**, drag the inner **reel-maker** folder into the chat, and type:

   > Install this skill.

4. It checks your computer and asks before downloading anything (about 600 MB once: the speech-to-text engine and model). It also asks for your name, handle, brand color, logo and call-to-action word once, and remembers them.

Then any time:

> Turn this video into reels: /path/to/my-video.mp4

You can drag the video into the chat instead of typing the path.

### Requirements

- Python 3.9 or newer (3.11+ recommended). Mac: usually already there; if not, python.org. Windows: python.org, and tick "Add python.exe to PATH".
- ffmpeg. If you don't have it, Reel Maker installs a private copy.
- About 2 GB free disk space.
- Optional for premium mode: Node.js 18+ (nodejs.org).

Everything Reel Maker installs goes in one folder, `~/.reel-maker`. Delete that folder to remove it completely.

## Speed

On an Apple Silicon Mac, a one-hour recording transcribes in roughly 3 to 6 minutes and each reel renders in under a minute. Older laptops and CPU-only Windows machines are slower; use a transcript file if you have one.

## Self-test

```
python3 reel-maker/scripts/smoke_test.py
```

Generates a sample clip and runs the whole standard render path with checks. Needs only Python, Pillow and ffmpeg (no downloads).

## Permission

If other people appear in your recording, get their OK before posting clips of them.

## License

MIT. See [LICENSE](LICENSE). Premium mode uses [Remotion](https://www.remotion.dev), which is free for individuals and small teams (up to 3 people) and needs a company license for larger companies.

Made by Joe Che. Share it with anyone.
