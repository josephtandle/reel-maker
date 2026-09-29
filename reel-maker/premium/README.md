# Premium renderer

Optional MIT-licensed Remotion composition for reel-maker. Requires Node.js 18+,
npm/npx, ffmpeg, and prepared `moments.json` plus `working/reel-N` assets.

```sh
python reel-maker/scripts/premium.py --out JOB --yes --concurrency 4
python reel-maker/scripts/premium.py --out JOB --only 1,2 --eyebrow "FIELD NOTES"
```

`--yes` authorizes the one-time npm install. Remotion also needs a headless browser;
if its download fails, run `npx remotion browser ensure` in this directory.
Initial installation and Google Fonts loading require internet access. Exit codes:
0 success, 1 render/input error, 2 missing Node tooling, 3 installation consent needed.

Brand settings come from `~/.reel-maker/brand.json` (`REEL_MAKER_HOME` overrides the
directory): `name`, `handle`, `color`, `accent`, `logo`, `cta_word`, `cta_text`.
Relative logo paths resolve against that directory. Optional `logo_aspect` is width
divided by height. `{CTA_WORD}` in `cta_text` is substituted literally.

Selected moments are numbered in file order. `--only` uses those reel numbers,
not moment IDs. Crop segments use clip-relative seconds and source-pixel rectangles.
Missing face detections or `layout: "fit"` contain the full active image.
The exported `ReelProps` type supports timed speakers and crop changes; the adapter
maps the moment speaker to the full clip. Only the foreground video supplies audio.

Each render saves its props under `working/reel-N`, stages media in
`working/premium-public`, and writes `Reel N - slug (premium).mp4` at the job root.
Previous final outputs move to `working/old`. Intermediate renders remain available
for diagnosis. Loudness is measured and corrected to -14 LUFS when outside a 1 LU
tolerance; silence is reported because it cannot be normalized to that target.

```sh
npm install --no-fund --no-audit
npx tsc --noEmit
npx remotion render src/index.tsx reel out/reel.mp4 --props=props.json --public-dir=PUBLIC
```

The composition is 1080×1920; duration and fps come from props (30 fps by default).
Headlines are measured after fonts load and shrink to at most three lines. A single
asterisk-wrapped word receives emphasis. Caption pages contain at most three words
and 20 characters, except an individual word longer than 20 characters, which is
kept intact and reduced in size. Word timestamps must be relative to the clip.
