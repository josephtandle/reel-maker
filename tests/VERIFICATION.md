# Implementation verification

This is the implementer’s report, not an independent review.

- `.venv/bin/python -m unittest discover -s tests`: **15 tests passed**, 29.954 seconds.
- Real ffmpeg integration generated a 90-second color/sine recording, prepared indexed subtitles, rendered two 1080×1920 reels with logo/CTA, verified source preservation and foreground/caption pixels, then re-rendered one reel while preserving the other. Superseded renders were archived and the cleaned job remained resumable.
- New regression coverage: missing Whisper backend and graceful timing fallback; fake-aligner matched timestamps and interpolation; silence-gap snapping; final machine-sync thresholds and first-.3-second energy (including an unrecognized prior fragment); transcript discovery and closest-duration selection; indexed cues; transcripts longer than the video; output cleanup including nested branding assets; empty display words; proper-name/acronym and “I” casing.
- The crop test generated a real synthetic letterboxed video, detected its 80×140 active picture inside a 320×180 frame, applied the crop, and verified the resulting pixels/dimensions.
- Manual review cannot override T5/T6. Tone-only fixtures retain pending speech evidence; stale visual reviews remain invalid. T3/T4/T7 still require inspection of all three stills for real deliveries.
- `.venv/bin/python -m compileall -q reel-maker/scripts tests`: passed.
- Parsing all script/test modules with `ast.parse(..., feature_version=(3, 9))`: passed (syntax compatibility, not a Python 3.9 runtime test).
- `git diff --check`: passed. Repository content scan for the three prohibited identifiers: zero matches, excluding ignored venv/Git/generated cache files.
- Both temporary reference scripts were read, their alignment and sync-check ideas incorporated, and the scripts deleted as requested.

Limits: real Whisper inference/model downloads and the original Zoom recording were not exercised in this network-disabled worktree. Fake recognition tests establish algorithm behavior, not recognition accuracy. Dark-scene crop boundaries and real faces still require visual review. The local venv used existing system packages; no network installs, servers, publication, commits or source-checkout edits occurred. `--rerender N` intentionally re-aligns and re-renders one reel including its cut; an overlay-only shortcut is not implemented.

## Third-test follow-up

- Added a real FFmpeg portrait fixture with a dark-grey top 30% and black side bars. The regression first failed with all 54 dark rows removed, then passed after conservative vertical widening. Full-width pure-black evidence must support vertical borders in at least 90% of samples per layout; 90% and 80% boundary cases are covered. Lossy border noise is retained.
- Caption sync now scores matched non-filler words only. Tests cover excluded filler offsets, unmatched tokens, no-match review, and advisory alignment-share warnings in tests.md. Alignment share retains its separate all-caption-word denominator.
- Added stamp/side-bar-label limitations and deleted the temporary renderer.
- Verification uses an isolated temporary `.venv` with existing system packages; no network setup or real Whisper inference.
