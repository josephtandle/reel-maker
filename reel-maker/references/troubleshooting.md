# Troubleshooting

Always start with `PY "SKILL_DIR/scripts/reelmaker.py" doctor`. Fix only things inside the job folder or `~/.reel-maker`. Never delete the user's files.

| Symptom | Likely cause | Smallest fix |
|---|---|---|
| `python3` / `py` not found | Python not installed | User installs Python 3.11+ from python.org (Windows: tick "Add python.exe to PATH"), then re-run doctor |
| Exit code 3, "NEEDS_CONSENT" | Something needs downloading | Show the user the plan, ask, then re-run with `--yes` |
| Exit code 2, no transcription engine | Setup not run yet | Ask, then `setup --yes` |
| ffmpeg not found | No ffmpeg on the computer | `setup --yes` installs a private copy (imageio-ffmpeg). System install only as a last resort, with the user's OK |
| No H.264 encoder | Unusual ffmpeg build | `setup --yes` adds imageio-ffmpeg; or set `REEL_MAKER_FFMPEG` to another ffmpeg for this run |
| pip fails with "externally managed environment" | System Python protection | Nothing to fix system-wide: Reel Maker always installs into its own venv in `~/.reel-maker/venv`. Re-run `setup --yes` |
| pip fails building a wheel | Python too new for a package | Install Python 3.11 or 3.12 from python.org, delete nothing, re-run setup (it rebuilds the venv with the chosen Python if you run setup with that Python) |
| mlx-whisper error on a Mac | Not Apple Silicon, or broken install | `transcribe ... --backend faster` (run `setup --yes --backend faster` first if needed) |
| Transcription very slow | CPU-only machine, big model | Use `--model small`, or pass an existing SRT/VTT with `--transcript` |
| Captions misspell names | Speech recognition limits | Add `"display": "Right Name"` to those words in `working/transcript.json`, then `render --only N` |
| Clip starts mid-word or on "so/um" | Window boundary | Move `first_word` one or two words later in moments.json, re-render that reel |
| Clip ends mid-sentence | Window boundary | Move `last_word` to the word that ends the sentence |
| Face cut off / wrong person framed | Several people or screen share | `render --only N --layout fit` shows the whole picture over a blurred background |
| Face detection not used | opencv not installed (`--no-faces`) | Framing falls back to centre. Re-run `setup --yes` without `--no-faces` to enable it |
| Headline covers a face | Tall face placement in the shot | Shorten the headline to one line, or use `--layout fit` |
| Loudness check fails | Very quiet or clipped source | Re-render the reel; if the source is mostly silence, choose another moment |
| Captions check fails | Text not drawn, or no words in range | Check `working/reel-N/words.json` has words; check the moment range contains speech; re-render |
| Duration check fails | Moment shorter than 20 s or longer than 60 s | Adjust `first_word` / `last_word` |
| "No space left on device" | Disk full | Tell the user how much space is needed; old versions in `working/old/` can be removed only if the user agrees |
| Windows: path errors | Quotes or backslashes | Wrap every path in double quotes; forward slashes work too |
| Audio-only file makes a waveform video | By design | Podcasts become audiograms with your brand color, logo and captions |
| Output folder already exists | Same video processed before | Reel Maker resumes the same job for the same source; a different source gets " (2)" |

## Self-test

`PY "SKILL_DIR/scripts/smoke_test.py"` generates a sample video, renders reels through the standard path (no downloads, no transcription engine needed) and checks size, duration, audio, loudness, burned captions and clean decode. If it passes, the rendering side is healthy and any remaining issue is in transcription or the input file.
