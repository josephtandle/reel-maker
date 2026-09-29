# Premium mode (Remotion)

Premium re-renders the same selected moments with a designed "Moments" template built in [Remotion](https://www.remotion.dev) (React for video). It reuses the job folder the standard render made: the cut and loudness-normalized clip, word timings and the face crop plan.

## Look

- Eyebrow line with a glowing dot (your handle or name)
- Serif headline that rises in word by word, with one italic accent word (`*word*` in the headline)
- Rounded video card with a soft glow in your brand color, face-aware framing and a slow push-in
- Speaker name tag inside the card (from `speaker` / `speaker_role` in moments.json)
- Word-by-word caption pills in your brand gradient
- Footer with your name, replaced by a CTA pill for the last 4.5 seconds
- Progress bar and an optional logo in the card's corner
- Background: a blurred copy of the video with brand-colored glows

## Requirements

- Node.js 18 or newer (LTS from nodejs.org)
- A one-time `npm install` inside `SKILL_DIR/premium` (about 250 MB including a headless Chrome that Remotion downloads). `premium.py --yes` runs it; without `--yes` it only explains what it would install and exits with code 3.
- Internet on the first render (fonts load from Google Fonts).

## Commands

```
PY "SKILL_DIR/scripts/premium.py" --out "<job folder>" --yes
PY "SKILL_DIR/scripts/premium.py" --out "<job folder>" --only 2
PY "SKILL_DIR/scripts/premium.py" --out "<job folder>" --eyebrow "Live workshop"
```

Output: `Reel N - <name> (premium).mp4` next to the standard reels. Loudness is re-checked after rendering and corrected to -14 LUFS if needed.

## Customizing

The template is `SKILL_DIR/premium/src/Reel.tsx`. Colors come from your brand color (`colors.ts` derives tints). To preview and tweak interactively: `cd "SKILL_DIR/premium"` then `npx remotion studio src/index.tsx` and load a props file from `<job>/working/reel-N/premium-props.json`.

## Remotion license

Remotion is free for individuals and companies with up to 3 people; larger companies need a company license from remotion.dev. Mention this to the user if they are part of a bigger team.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Node.js not found" | Install Node LTS from nodejs.org, open a new terminal/chat, retry |
| Chrome download fails | Run `npx remotion browser ensure` inside the premium folder, retry |
| Fonts look like Georgia/Arial | First render needs internet for Google Fonts |
| Render very slow | Lower `--concurrency` if the computer is struggling, or raise it on a fast machine |
| Face cut off in the card | Re-run the standard `render` first so crop.json is fresh; the card falls back to showing the whole picture when no face is found |
