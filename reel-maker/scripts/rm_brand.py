"""Portable personal branding, stored only in the reel-maker home."""
from __future__ import annotations
import re
import shutil
from pathlib import Path
from rm_env import NeedsInput, home, read_json, write_json, log


def tint(color):
    return "#" + "".join(f"{round(int(color[i:i+2], 16) * .6 + 255 * .4):02X}" for i in (1, 3, 5))


def defaults():
    return {"name": "", "handle": "", "color": "#7C69C7", "accent": tint("#7C69C7"),
            "cta_word": "INFO", "cta_text": "Comment {CTA_WORD} for the details", "font": None, "logo": None}


def load():
    path = home() / "brand.json"
    return {**defaults(), **(read_json(path) if path.exists() else {})}


def cta(brand):
    return brand["cta_text"].replace("{CTA_WORD}", brand["cta_word"])


def configure(args):
    brand = defaults() if args.reset else load()
    for key in brand:
        value = getattr(args, key, None)
        if value is not None:
            brand[key] = value
    for key in ("color", "accent"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", brand[key]):
            raise NeedsInput(key + " must be a hex color such as #7C69C7.")
    if args.color and not args.accent:
        brand["accent"] = tint(args.color)
    if args.font and not Path(args.font).is_file():
        raise NeedsInput("Font does not exist. Supply a local TTF or TTC font file.")
    if args.font:
        brand["font"] = str(Path(args.font).resolve())
    if args.logo:
        logo = Path(args.logo).resolve()
        if logo.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise NeedsInput("Logo must be PNG, JPG or WebP. Export SVG artwork as PNG first.")
        if not logo.is_file():
            raise NeedsInput("Logo file does not exist.")
        dest = home() / "brand" / ("logo" + logo.suffix.lower())
        dest.parent.mkdir(parents=True, exist_ok=True)
        if logo != dest.resolve():
            shutil.copy2(logo, dest)
        brand["logo"] = str(dest)
    if args.reset or any(getattr(args, key, None) is not None for key in defaults()):
        write_json(home() / "brand.json", brand)
        log("Brand saved to " + str(home() / "brand.json"))
    import json
    print(json.dumps(brand, indent=2, ensure_ascii=False))
