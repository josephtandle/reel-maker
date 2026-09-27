# Failure evidence and recovery

Keep exact command/error, fix only this job, rerun failed check then all checks for that reel. No more than two identical failed attempts without new evidence. All processing stays in the foreground. Do not delete sources or other people's files.

| Symptom | Diagnosis and smallest fix |
|---|---|
| Full-length clip or wrong duration | Use -ss before -i and -t as duration, re-encode; ffprobe cut and final; rebuild only failed reel |
| Cropped/zoomed foreground | Inspect foreground branch: remove detected persistent black borders only, then scale except evidenced bottom strip <=8%; restore whole active picture and fit 1080×880 |
| Portrait/square text overlaps picture | Recalculate FW,FH,Y0 from measured display dimensions, not assumed 16:9 |
| Captions hidden behind Instagram UI | Fixed 170-pixel PNG and geometry must end by y=1540 |
| Caption jumps between one/two lines | Same 1080×170 transparent canvas, centered text for every event |
| Captions late inside long cues | Even-spread/character-weighted times drifted by up to 2.3 s in the reference run. Re-align selected windows with local Whisper, inspect match share/max drift, then machine-check finished reels at 25/50/75% and across all caption words |
| Previous sentence leaks into first seconds | Estimated first-word times can include the previous-sentence tail. Match Whisper words, then snap to the nearest preceding PCM silence gap; T6 checks first-0.3-second energy and the first recognized word. A real quiet gap may be only 60 ms (RMS below 0.006). With continuous speech, use up to 0.08 s before the aligned onset, never crossing the previous word’s end, and a 0.12 s audio fade-in; tests.json records the fallback |
| Ending includes next sentence | Tail is .4 s maximum and cannot cross next word; confirm the complete sentence in recognized text |
| Missing drawtext/subtitles/drawbox | Never use these filters; all text and progress are PNG overlays |
| Unknown H.264 encoder | Inspect encoders, use supported encoder or imageio-ffmpeg build; no stream-copy workaround |
| Missing boxblur/eq | gblur fallback; darken with lutrgb if eq unavailable. If fallback also missing, change ffmpeg build |
| imageio-ffmpeg installed but probe missing | It does not supply ffprobe. Obtain official ffprobe with system-install approval if needed; do not pretend regex duration is verified |
| Font tiny or unreadable glyphs | Use OS bold fallback or supplied language font; Pillow>=10.1 sized default only; inspect actual text |
| Headline leaves one word alone | Balanced two-line split or reduce font size; shorten headline rather than tiny text |
| Word timing restarts in transcription chunks | Add each chunk's absolute source offset before merging words |
| speaker repeats a phrase that Whisper drops (T5 fails by seconds) | Pick another moment, or hide the repeat through display-skip: set `display` to an empty string while preserving original text, timing, entries and word indices. Rerender that candidate and rerun T5; never delete or renumber words |
| Repeated phrase hallucinations | Skip repetition-loop regions; inspect gaps and never invent replacement speech |
| Garbled captions, lowercase names | Agent reviews full context, writes display corrections without changing meaning; uncertainty needs review |
| Several subtitle speakers overlap | NEEDS_REVIEW; isolate intended speaker/timings rather than stacking captions |
| Video has no audio | NEEDS_INPUT; do not map audio optionally or synthesize fake sound |
| Audio lost during render | Probe source and cut; explicit -map 0:a:0 and AAC encoding; decode whole output |
| Wrong Desktop on Windows/WSL | Use Windows known folder, or PowerShell GetFolderPath plus wslpath; never assume Linux home or OneDrive path |
| Existing output folder/files | New folder with suffix, or resume its matching working files/job.json; superseded finals move into working files |
| Missing attachment/Python/tools/model, offline | Request a local file path/VTT/SRT; venv-local official packages first; explain system install and obtain OK only if needed |
| Slow transcription/render or tool timeout | Warn, process sequentially, use foreground tool continuation or bounded chunks, report progress. Do not launch detached work |
| Old review passes after rerender | Reviews bind to SHA-256; new output requires new still and machine-listening evidence |
| Small phone tile inside wide recording | Sample cropdetect every 0.5 s, group stable layouts, and fit each segment separately with its own cropped blurred background. Merge sub-second segments conservatively. This is not zoom: no active-picture content is intentionally removed. Inspect dark edges in all three stills |
| Transcript longer than video | Accept the transcript and warn about extra words; only candidates inside the actual video duration are selectable |
| Floating short caption words | Pillow must use baseline/ascender anchor `la` for every token, including short words; never position by each glyph bounding box |
| Empty display word | `display: ""` intentionally omits the caption token; skip it before grouping or drawing, never render a blank active word |
| Mis-heard proper nouns | Read surrounding context and fix `display` only when the intended name is clear. Preserve original text, capitalize names and “I”, and never change meaning; uncertainty remains NEEDS_REVIEW |
| Date/name stamp looks rough | Optional whole-label bottom strip <=8%, only after still inspection; otherwise retain it. Burned-in stamps taller than the 8% trim stay visible; choose a moment without them or accept |
| Name labels inside removed side bars | These labels are cropped; mention it in the summary |

To select a different verified build without editing PATH, set process-local `REEL_MAKER_FFMPEG` and/or `REEL_MAKER_FFPROBE` to its executable path. For imageio-ffmpeg use the value returned by `imageio_ffmpeg.get_ffmpeg_exe()`. No shell-profile change is needed.

## T1–T10 and honest review

T1 measured length 20–59 seconds, shorter than source and within .5 s of requested length. T2 1080×1920. T3 whole active picture (black borders removed, permitted stamp trim only). T4 readable headline in safe band. T5 machine caption sync. T6 machine clean-start evidence. T7 face not covered. T8 audio present. T9 source SHA-256 and size unchanged. T10 entire output decodes.

T5 re-transcribes the finished reel with local Whisper and compares both word starts and ends against every active caption event. Only matched non-filler caption words enter sync statistics: at least 90% must be within .5 s, and none may exceed 1 s. Fillers (“um”, “uh”, “er”, “ah”) and unmatched words are excluded and listed separately. The 25/50/75% samples with scored words must agree within .5 s; samples without scored words are excluded, or pass if blank in both speech and captions. No scored words means NEEDS_REVIEW. Alignment share is separate: below 0.90 writes a WARNING in tests.md asking the agent to look at the listed unmatched words; low share alone does not fail T5. T6 reads PCM energy in the first 1.0 s and checks that the first recognized word is the intended first spoken word, including display-skipped tokens. A quiet onset passes, or continuous speech uses a verified aligned onset with 0.08 s preroll and 0.12 s audio fade-in. The fallback and applied fade are recorded in tests.json. Opening foreground frames at 0, 0.5 and 0.96 s are compared to flag silent still openings. Missing backend/model or insufficient alignment evidence remains NEEDS_REVIEW. Missing cached models are not downloaded silently by alignment/verification. Use the same `--backend` on make_reels.py; verify.py reads it from job state.

Only T3/T4/T7 require visual review: **look at every 25/50/75% still**. The midpoint contact sheet alone is insufficient. Write `working files/reviews.json`, keyed by candidate number:

```json
{
  "1": {
    "sha256": "COPY EXACT DIGEST FROM working files/tests.json",
    "T3": {"pass": true, "note": "All active-picture edges visible at all three stills"},
    "T4": {"pass": true, "note": "Hook readable, no missing glyphs, within safe band"},
    "T7": {"pass": true, "note": "All visible faces clear in three stills"}
  }
}
```

Use `pass:false` with evidence for visual failures. T5/T6 cannot be overridden with a manual review. Run verify.py again; a stale digest invalidates visual review. Read `working files/tests.json` for per-reel alignment match share/max drift, all-word offsets, three sample comparisons and first-.3-second energy. Confirm complete sentence endings against the recognized text and original transcript. Synthetic tone tests validate rendering mechanics only; fake-aligner tests validate timing logic, not real speech recognition.

For a name, headline or caption edit, use `--rerender N`. It re-aligns, cuts and renders only that reel; it is not an overlay-only operation. Final names stay readable, superseded files are retained under `working files`, and the other reels keep their reviews.

## Zoom opening-frame lag

Zoom active-speaker switching can lag speech by about 1 s. Audio checks cannot establish that the visible person is speaking. Inspect the three opening frames and listen to the first second. If the opening word is a filler such as “well”, “so” or “um”, consider starting 0.5–1.0 s later at the next meaningful word's aligned onset, preserving a complete sentence. Change the selected first-word index and re-align; never trim into a word or merely hide its caption to fix the picture.

Layout detection has 0.5 s sampling resolution. Inspect layout transitions as well as the three standard stills, particularly dark scenes and rapid speaker switches. Sub-second layouts are merged with a union crop to preserve real picture, which can retain borders briefly.

Vertical cropdetect cuts are widened unless full-width rows are pure black in at least 90% of samples within the layout segment. Dark picture content and uncertain borders are retained.
