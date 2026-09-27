"""A labeled midpoint still for every currently selected reel."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw
from common import job_path, read_json
from render import font


def contact_sheet(out):
    job = read_json(job_path(out, "job.json"))
    reels = sorted(job.get("reels", {}).items(), key=lambda item: int(item[0]))
    if not reels:
        return
    sheet = Image.new("RGB", (324*len(reels), 636), "#222222")
    draw = ImageDraw.Draw(sheet)
    for index, (number, reel) in enumerate(reels):
        with Image.open(out/reel["evidence"]/"still-50.jpg") as frame:
            sheet.paste(frame.resize((324,576)), (index*324,0))
        draw.text((index*324+12,585), f"Reel {number}", font=font(24), fill="white")
    sheet.save(out/"contact-sheet.jpg", quality=90)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    contact_sheet(p.parse_args().out)
