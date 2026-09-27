# Layout and rendering contract

Canvas 1080×1920, 25 fps, H.264/AAC with faststart. Instagram text-safe band: y=220 through 1540. Foreground width/height W,H are measured after any approved trim and display-aspect correction.

- s = min(1080/W, 880/H); FW,FH = floor(W*s/2)*2, floor(H*s/2)*2.
- Y0 = floor(220 + (890-FH)/2).
- Headline: transparent 1080×200 PNG at Y0, initially slides horizontally into place in 0.4 s. Under 8 words, approximately 76 px, balanced two-line wrapping, no one-word final line.
- Whole foreground: centered at x=(1080-FW)/2, y=Y0+230. After black-border removal and approved stamp trim, only scale and sample-aspect normalization in foreground branch. Portrait and square frames fit inside 1080×880 without cropping or zooming. Before layout, cropdetect samples every 0.5 s and groups consecutive boxes within four pixels. Each segment uses its own crop, foreground geometry and blurred background; segments are concatenated before timed overlays. Segments shorter than 1 s merge into a neighbour with a union crop to preserve picture. Inspect transitions and dark edges as well as standard stills. This is not subject zoom.
- Captions: transparent 1080×170 at y=Y0+260+FH. Text approximately 62 px, fixed canvas for one or two lines. All 2–5 words are white with thick black outline; current word uses accent #FFD166 (configurable). Transparent intervals preserve speech gaps. Every PNG event uses the same word times as the cut.
- Optional CTA: 1080×28 PNG, 22 px, at Y0+201 in the gap above the video during the last three seconds. Keep it short; a longer CTA belongs in post copy.
- Optional logo: thumbnail <=80×80 at x=970,y=Y0; headline reserves its space.
- Progress: 1080×6 accent PNG at y=1534, moving from x=-1080 to x=0 over the clip; no drawbox dependency.
- Background only: scale to fill, crop to 1080×1920, blur and darken slightly. This fill crop is allowed only in the background branch.

Optional bottom trim: only a burned-in Zoom date/name stamp, wholly contained in an <=8% strip. Set bottom_trim_fraction and a bottom_trim_evidence description after inspecting a still. Strip rounded down to an even pixel count; no top/side cuts, no automated subject cropping.

Fonts: configured font first; macOS Arial Bold then Helvetica TTC bold index 1; Windows arialbd.ttf then segoeuib.ttf in system Fonts; Linux DejaVuSans-Bold.ttf then another Bold TTF. Last fallback is Pillow load_default(size=...), requiring >=10.1. Never unsized default. Check actual glyphs for the language; configure an appropriate font if missing.

Cut with `-ss START` BEFORE `-i INPUT`, `-t LENGTH`, always re-encode. Never stream-copy a cut. Map real source audio explicitly. Probe cut and final duration with ffprobe; tolerance 0.5 seconds. Shell-free subprocess argument lists protect paths with spaces, quotes and non-ASCII text. Captions use an ffconcat sequence with controlled relative filenames and per-word durations; this avoids hundreds of concurrent ffmpeg PNG inputs. Keep ffmpeg commands and render.json as evidence.
