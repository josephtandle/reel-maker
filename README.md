# reel-maker

Turn a long Zoom call, webinar or talk into 3–5 Instagram Reels that give viewers a reason to want what you sell. An Agent Skill for business owners using Claude Code or Codex.

**Before:** a long recording with valuable moments buried inside it. **After:** short vertical videos with the whole original picture over a blurred background, an animated hook, word-highlighted captions, a progress bar and optional branding. You also get post copy, ten scored candidate moments, a contact sheet and a per-reel test report. Nothing is uploaded or posted.

Download this repository, then paste a setup request into your chat:

**Claude Code**
> Install the reel-maker skill from this downloaded repository into ~/.claude/skills/reel-maker. Copy only its reel-maker folder. Read SKILL.md, check the tools, and help me turn my recording into reels. Ask me before any whole-computer installation.

**Codex**
> Install the reel-maker skill from this downloaded repository into ~/.agents/skills/reel-maker. Copy only its reel-maker folder. Read SKILL.md, check the tools, and help me turn my recording into reels. Ask me before any whole-computer installation.

Then say: “Turn this video into reels,” and provide the recording's local file path and, if available, its VTT/SRT transcript. The agent reads the whole transcript, scores ten moments and chooses the strongest non-overlapping excerpts. You can choose another saved candidate and ask it to re-render that number.

Requirements: Python 3.9+ (3.10+ recommended), Pillow 10.1+, ffmpeg with an H.264 encoder and ffprobe. An attached transcript avoids full-recording transcription. Selected-window alignment and final machine listening still use local faster-whisper (or mlx-whisper on Apple Silicon); initial model setup needs internet; alignment/verification use cached models only and report NEEDS_REVIEW when unavailable. Tools are installed in a local venv where possible. imageio-ffmpeg is an ffmpeg fallback, but does not bundle ffprobe. No accounts or paid APIs are required.

Files go in a new `Reels - (video name) - (date)` folder on your actual Desktop, including redirected Windows/OneDrive Desktops. Edit `reel-maker.config.json` there for an accent color, bold font, PNG logo or short final CTA. The original video remains unchanged. `moments.json` retains the choices. Finals are named `Reel N - <short-slug>.mp4`. Only finals, `contact-sheet.jpg`, `tests.md`, `moments.json`, `clips-and-captions.txt` and config stay at top level. Old renders, transcripts, `words.json`, `tests.json`, reviews and job state are retained under `working files`.

The agent must inspect 25/50/75% stills. Machine listening re-transcribes finished reels and checks caption timing: 90% of words within 0.5 s, none over 1 s, plus the three sample points. A first-0.3-second energy and speech check verifies clean starts. Missing Whisper evidence cannot be manually marked passed. Subtitle estimates are refined on selected windows with 2-second padding; alignment quality is recorded. The user remains responsible for obtaining participants' permission before posting.

Transcripts beside the video are discovered by matching the video stem or “transcript”; the closest last cue wins when several match. Indexed `working files/transcript.txt` makes word-range selection explicit. Transcripts may extend past the video, but selected clips may not. Black borders around a small phone picture are detected and removed before fitting the whole active picture; this is not a zoom.

For name/headline/caption edits, update `display` in `working files/words.json` or edit `moments.json`, then run the original command with `--out "<job>" --rerender N`. It re-aligns and re-renders only candidate N, including the cut; no overlay-only shortcut is currently implemented. Preserve proper nouns and “I”; correct misheard names only from clear context without changing meaning.

For maintainers: create `.venv`, install `requirements.txt`, then run `.venv/bin/python -m unittest discover -s tests`. The suite works offline when Pillow and ffmpeg/ffprobe already work. The 90-second synthetic tone fixture renders two reels and checks mechanics; natural speech and platform-specific installs still need live review.

MIT licensed. See [LICENSE](LICENSE).
