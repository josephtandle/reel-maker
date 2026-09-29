---
name: reel-maker
description: Turn a long video, Zoom call, webinar or podcast into 2 to 5 ready-to-post vertical Reels (Instagram, TikTok, Shorts) with a hook headline, word-by-word captions, face-aware 9:16 framing, loudness at -14 LUFS, post captions and a contact sheet. Use for requests like "turn this video into reels", "make clips from my podcast", "cut shorts from this recording", or "install this skill". Everything runs on the user's computer. Nothing is uploaded or posted.
---

# Reel Maker

You are helping a business owner turn one long recording into short vertical clips people actually stop scrolling for. The user is probably not technical. Talk in plain English, one short line per step, and warn before anything slow (transcribing, rendering, downloading).

`SKILL_DIR` below means the folder this SKILL.md is in. `PY` means `python3` on macOS/Linux, and `py -3` (or `python`) on Windows. Run every command from any folder using full paths in quotes.

## 0. First time only: install, check, brand

**If the user just said "install this skill"** (they dragged this folder into the chat or gave you a path to it): copy the whole `reel-maker` folder that contains this SKILL.md to
- Claude Code: `~/.claude/skills/reel-maker` (Windows: `%USERPROFILE%\.claude\skills\reel-maker`)
- Codex: `~/.codex/skills/reel-maker` (Windows: `%USERPROFILE%\.codex\skills\reel-maker`), or `~/.agents/skills/reel-maker` if that is the folder your Codex version reads

Create the parent folder if needed. If an older reel-maker is already there, move it to `reel-maker.old-<date>` first (never delete it). Then continue with the check below and tell the user they can now say "turn this video into reels" any time.

**Check the computer:**

```
PY "SKILL_DIR/scripts/reelmaker.py" doctor
```

It reports ffmpeg, Python, the transcription engine, face detection and Node (premium only), and ends with a SETUP PLAN.

- **ffmpeg missing:** `setup` can install a private copy (imageio-ffmpeg, about 70 MB) inside Reel Maker's own folder. That is the default fix. Only if that fails, offer the system install (`brew install ffmpeg` on Mac if Homebrew exists, `winget install Gyan.FFmpeg` on Windows, `sudo apt install ffmpeg` on Linux) and wait for a yes.
- **Python missing or older than 3.9:** tell the user to install Python 3.11+ from python.org (Windows: tick "Add python.exe to PATH"). Wait for them, then re-run doctor.

**Install the tools (ask first).** Show the user the SETUP PLAN in one or two lines, for example: "I need to download about 600 MB once: the transcription engine and its speech model, plus a small face-detection library. It all goes in `~/.reel-maker`, nothing system-wide. OK?" Only after a clear yes:

```
PY "SKILL_DIR/scripts/reelmaker.py" setup --yes
```

On Apple Silicon Macs this installs mlx-whisper (fast, uses the GPU). Everywhere else it installs faster-whisper. Add `--model large-v3-turbo` for better accuracy (bigger download, about 1.6 GB) or `--no-faces` to skip face detection. Setup prints a progress line every 30 seconds; do not start it in the background.

**Brand (ask once, saved forever).** If doctor says no brand is saved, ask these in ONE message, all optional:
1. Your name as it should appear (e.g. "Sam Rivera")
2. Your handle (e.g. "@samrivera")
3. Brand color (a hex code like #2E86DE, or describe it and you pick the hex)
4. Logo file (PNG with a transparent background works best), or none
5. Your comment keyword for the call to action, e.g. INFO or GUIDE ("Comment GUIDE for the details")

Then save it:

```
PY "SKILL_DIR/scripts/reelmaker.py" brand --name "Sam Rivera" --handle "@samrivera" --color "#2E86DE" --logo "/path/logo.png" --cta-word GUIDE
```

Change it any time with the same command (`--show` prints it, `--reset` clears it).

## 1. Find the video

Use the file the user named or attached. A local file path is best (no upload limits). If they didn't give one, look only in their Desktop and Downloads for the newest video or audio file, name it and confirm. A folder is fine too: every video/audio file in it becomes its own job. Podcasts and audio-only files work: they get an audiogram (brand background, waveform, captions). Never modify, move or delete the original.

## 2. Transcribe and shortlist

```
PY "SKILL_DIR/scripts/reelmaker.py" make "<video>" --stop-after find
```

This creates the job folder on the Desktop, `Reels - <video name> - <date>` (use `--out "<folder>"` to put it elsewhere, and reuse that same `--out` for every later command). It transcribes with word timestamps (a 1-hour video takes about 3 to 6 minutes on Apple Silicon, longer on older laptops: say so), then scores every possible 20 to 60 second window and writes the top picks to `moments.json`. If the user already has an SRT/VTT transcript, add `--transcript "<file>"` to skip transcription.

## 3. Pick the moments (this is your job, not the user's)

The script's picks are a starting point. You are the editor. If the user told you what they sell, every pick should give a viewer a reason to want that; otherwise work out the offer from the transcript. Read [references/moments.md](references/moments.md), then read the WHOLE transcript in `working/transcript.txt` (format `[start-end] #firstWordIndex text`).

For each reel, edit `moments.json`:
- `selected`: true for the 2 to 5 you want (2 for a video under 5 minutes). Reels are numbered in file order, so put the strongest first.
- `first_word` / `last_word`: word indexes (from transcript.txt) so the clip opens on the hook line and ends on a complete thought. 20 to 60 seconds, 30 to 45 is the sweet spot.
- `headline`: 7 words or fewer, the reason to keep watching. Wrap ONE word in `*asterisks*` to color it, e.g. `The *one* email that books calls`.
- `post_caption`: under 120 words, first line is the hook, end with the CTA.
- `cover_text`: 5 words or fewer.
- `speaker` / `speaker_role`: optional name tag, e.g. "Sam Rivera", "Founder". Only for people you can clearly identify from the transcript; otherwise leave blank.

To fix a misheard word in the captions, add `"display": "Correct"` to that word in `working/transcript.json` (use `"display": ""` to hide a filler word). Never change the meaning of what someone said, and never invent claims.

## 4. Render

```
PY "SKILL_DIR/scripts/reelmaker.py" render --out "<job folder>"
```

Each reel: cut, loudness normalized to -14 LUFS, framed 9:16 around the speaker's face (full head and headroom), hook headline, word-highlight captions, optional name tag, logo, CTA pill in the last 3 seconds and a progress bar. Options: `--layout fit` keeps the whole picture over a blurred background (best for screen shares and gallery view; `auto` chooses for you), `--style clean` for sentence-case captions on a color pill instead of bold uppercase, `--only 2` to redo one reel.

Everything the user needs is at the top of the job folder:
- `Reel 1 - <name>.mp4` ... ready to upload
- `Reel 1 - <name>.srt` captions file, if they prefer the app's own captions
- `captions.txt` post captions with hooks, ready to paste
- `contact-sheet.jpg` stills from every reel
- `report.md` automatic checks
- `moments.json` and `working/` (transcript, cuts, old versions)

## 5. Check your own work

Open `contact-sheet.jpg` and LOOK at it (use your image viewing ability). Check: faces are not cut off, the headline is readable and not covering a face, captions are inside the frame. Read `report.md`: every reel should PASS length, 1080x1920, audio, loudness, captions burned in, and clean decode. If something fails, follow Self-healing below, re-render only that reel with `--only N`, and check again. Do not report a reel as done while any check fails.

## 6. Premium mode (optional)

A more designed "Moments" look rendered with Remotion: serif headline with an italic accent word, glowing video card, animated word-by-word caption pills, speaker name tag, CTA pill, progress bar and a logo slot, all in the user's brand color. It needs Node.js 18+ and a one-time download of about 250 MB. Offer it after the standard reels are done; only run with `--yes` after the user agrees:

```
PY "SKILL_DIR/scripts/premium.py" --out "<job folder>" --yes
```

It uses the same job folder and writes `Reel N - <name> (premium).mp4`. If Node is missing, tell the user to install the LTS version from nodejs.org, then try again. Details: [references/premium.md](references/premium.md).

## 7. Tell the user

In plain English: where the folder is (give the path), how many reels and why those moments, each headline, anything you could not fix, and who appears in each clip that is not the owner (they should get permission before posting). Then: "Upload the MP4 as a Reel, paste the matching caption from captions.txt, and pick a cover." Never upload or post anything yourself.

## Self-healing

When a command fails, fix it yourself before involving the user, within these limits:

1. **Diagnose.** Read the exact error. Run `doctor`. Check `report.md` and the last lines of output.
2. **Repair the smallest thing.** Use [references/troubleshooting.md](references/troubleshooting.md). Typical fixes: re-run `setup --yes` if a package is missing (already approved), switch `--layout fit` if faces are cut, use `--backend faster` if mlx fails, free disk space inside the job's `working/` folder only.
3. **Re-verify.** Re-run the failed step, then `PY "SKILL_DIR/scripts/reelmaker.py" verify --out "<job>"`.
4. **Bounded.** At most 3 attempts per problem, and never the same fix twice without new evidence. Then stop and tell the user in one line what failed, what you tried, and the one thing they can do.

Safety rules that always hold:
- Never delete or overwrite the user's files. Old renders move to `working/old/`.
- Ask before installing anything system-wide or anything big (the setup download, premium's Node packages, a larger model). Installing inside `~/.reel-maker` after the user agreed to setup is fine.
- Never edit PATH, shell profiles or system settings. Never use passwords, accounts or paid services. Never upload or post.
- If you cannot see images, say the visual check still needs a human look instead of claiming it passed.

## Command reference

| Command | What it does |
|---|---|
| `doctor [--json]` | Checks the computer and prints a setup plan |
| `setup --yes [--model small\|large-v3-turbo] [--backend mlx\|faster] [--no-faces]` | Installs tools into `~/.reel-maker` |
| `brand --name --handle --color --accent --logo --cta-word --cta-text --font --show --reset` | Saves branding once |
| `make INPUT [--out DIR] [--count N] [--stop-after transcribe\|find] [--transcript FILE] [--layout auto\|fill\|fit] [--style bold\|clean]` | Whole pipeline, or stop early for review |
| `transcribe INPUT --out DIR` | Transcript with word timestamps |
| `find --out DIR [--count N] [--force]` | Scores and shortlists moments |
| `render --out DIR [--only N] [--layout ...] [--style ...] [--no-logo]` | Renders selected reels |
| `verify --out DIR` | Re-runs the automatic checks |
| `scripts/premium.py --out DIR [--yes] [--only N]` | Premium Remotion render |
| `scripts/smoke_test.py` | Self-test on a generated sample (no downloads) |

Exit codes: 0 done, 2 needs input from the user, 3 needs the user's OK to install, 4 a check failed, 1 unexpected error. The last line of `make`/`render` output starts with `RESULT` and a JSON summary.
