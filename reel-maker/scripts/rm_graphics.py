"""Pillow-only typography and a single timed PNG caption stream."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import re
import shutil
from rm_env import run, ffmpeg, NeedsInput
from rm_brand import cta


@lru_cache(64)
def font(size, custom=None, heavy=False):
    from PIL import ImageFont
    if custom and not Path(custom).is_file():
        raise NeedsInput("Configured font is missing. Run brand --font PATH or brand --reset.")
    candidates = [custom] if custom else []
    if heavy:
        candidates += ["/System/Library/Fonts/Supplemental/Arial Black.ttf", "C:/Windows/Fonts/seguibl.ttf"]
    candidates += ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
                   "/System/Library/Fonts/Helvetica.ttc", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"]
    if shutil.which("fc-match"):
        candidates.append(run(["fc-match", "-f", "%{file}", "sans:style=Bold"]).stdout)
    for path in candidates:
        if path and Path(path).is_file():
            try:
                return ImageFont.truetype(str(path), size, index=1 if str(path).endswith("Helvetica.ttc") else 0)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def text_image(text, path, brand, size=92, height=310, active=None, style="headline", pill=False, left=False):
    from PIL import Image, ImageDraw
    tokens = text.split()
    marked = [i for i, t in enumerate(tokens) if "*" in t]
    tokens = [t.replace("*", "") for t in tokens]
    if style in ("bold", "eyebrow"):
        tokens = [t.upper() for t in tokens]
    image = Image.new("RGBA", (1080, height))
    draw = ImageDraw.Draw(image)
    caption = active is not None
    limit = 900 if caption else 920
    stroke = 4 if caption else 0
    spacing = 3 if style == "eyebrow" else 0
    minimum = 48 if caption else 18
    for px in range(size, minimum-1, -2):
        f = font(px, brand.get("font"), True)
        ascent, descent = f.getmetrics()
        line_height = ascent + descent
        widths = [draw.textlength(t, font=f) + max(0, len(t)-1)*spacing for t in tokens]
        space = draw.textlength(" ", font=f) + spacing
        def width(row):
            return sum(widths[i] for i in row) + max(0, len(row)-1)*space
        rows = [list(range(len(tokens)))]
        if len(tokens) > 1 and (width(rows[0])+2*stroke > limit or style == "headline" and not pill and width(rows[0]) > 700):
            split = min(range(1,len(tokens)), key=lambda n: abs(width(list(range(n)))-width(list(range(n,len(tokens))))))
            rows = [list(range(split)), list(range(split,len(tokens)))]
        padding_y = 20 if pill else 18 if style == "headline" else stroke
        if max((width(row) for row in rows), default=0)+2*stroke <= limit and len(rows)*line_height+2*padding_y <= height:
            break
    else:
        raise NeedsInput("Text cannot fit legibly. Shorten the headline, CTA, speaker label or caption display text.")
    y = (height-len(rows)*line_height)/2
    if pill or style == "headline":
        box_w = max((width(row) for row in rows), default=0) + (72 if pill else 56)
        box_h = len(rows)*line_height + 2*padding_y
        draw.rounded_rectangle(((1080-box_w)/2,(height-box_h)/2,(1080+box_w)/2,(height+box_h)/2),
                               radius=28, fill=brand["accent"] if pill else (0,0,0,140))
    for row in rows:
        x = (1080-width(row))/2
        for i in row:
            fill = "#171522" if pill else brand["accent"] if i in marked[:1] or i == active and style != "clean" else "#e4e4ef" if style == "eyebrow" else "white"
            if i == active and style == "clean":
                draw.rounded_rectangle((x-4,y,x+widths[i]+4,y+line_height), radius=16, fill=brand["accent"])
            if spacing:
                for char in tokens[i]:
                    draw.text((x,y+ascent), char, font=f, fill=fill, anchor="ls")
                    x += draw.textlength(char,font=f)+spacing
                x -= spacing
            else:
                draw.text((x,y+ascent), tokens[i], font=f, fill=fill, stroke_width=stroke, stroke_fill="#101018", anchor="ls")
                x += widths[i]
            x += space
        y += line_height
    if left:
        box = image.getbbox()
        if box:
            aligned = Image.new("RGBA", image.size)
            aligned.alpha_composite(image.crop(box), (60, box[1]))
            image = aligned
    image.save(path)


def caption_track(words, duration, work, brand, style):
    from PIL import Image
    Image.new("RGBA", (1080,220)).save(work/"blank.png")
    pages, current = [], []
    for word in words:
        if current and (len(current) >= 3 or len(" ".join(w["text"] for w in current))+len(word["text"])+1 > 16 or word["start"]-current[-1]["end"] > .5 or re.search(r"[,.!?;:][\"’\x27]*$",current[-1]["text"])):
            pages.append(current)
            current = []
        current.append(word)
    if current:
        pages.append(current)
    events = []
    visible = [w for p in pages for w in p]
    global_index = 0
    for page in pages:
        for active, word in enumerate(page):
            next_start = visible[global_index+1]["start"] if global_index+1 < len(visible) else duration
            end = min(duration, word["end"] if next_start-word["end"] > .6 else next_start)
            start = max(0, word["start"])
            if end > start:
                filename = "word-" + str(len(events)).zfill(4) + ".png"
                text_image(" ".join(w["text"] for w in page),work/filename,brand, size=84,height=220,active=active,style=style)
                events.append({"start":start,"end":end,"file":filename})
            global_index += 1
    lines, cursor = ["ffconcat version 1.0"], 0.0
    def entry(filename, span):
        lines.extend(["file " + filename, "option framerate 30", f"duration {span:.8f}"])
    for event in events:
        if event["start"] > cursor:
            entry("blank.png", event["start"]-cursor)
        entry(event["file"], event["end"]-event["start"])
        cursor = event["end"]
    if cursor < duration:
        entry("blank.png", duration-cursor)
    lines.extend(["file blank.png", "option framerate 30"])
    target = work/"captions.ffconcat"
    target.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return target, events


def assets(work, moment, brand, layout, no_logo=False):
    from PIL import Image, ImageDraw, ImageColor
    text_image(moment["headline"],work/"headline.png",brand)
    text_image(cta(brand),work/"cta.png",brand,size=46,height=120,pill=True,style="cta")
    Image.new("RGBA", (1080,8),brand["accent"]).save(work/"progress.png")
    eyebrow = brand.get("handle") or brand.get("name")
    if eyebrow:
        text_image(eyebrow,work/"eyebrow.png",brand,size=34,height=55,style="eyebrow")
    if moment.get("speaker"):
        name_font = font(40,brand.get("font"),True)
        role_font = font(30,brand.get("font"),True)
        name = moment["speaker"]
        role = moment.get("speaker_role", "")
        image = Image.new("RGBA", (1080,140))
        draw = ImageDraw.Draw(image)
        width = max(draw.textlength(name,font=name_font),draw.textlength(role,font=role_font))
        if width > 888:
            raise NeedsInput("Speaker label is too long; shorten the name or role.")
        draw.rounded_rectangle((60,0,60+width+72,140 if role else 90),radius=28,fill=brand["accent"])
        y = 18
        for text, f in ((name,name_font),(role,role_font)):
            ascent, descent = f.getmetrics()
            draw.text((96,y+ascent),text,font=f,fill="#171522",anchor="ls")
            y += ascent+descent
        image.save(work/"name.png")
    if layout == "fill":
        scrim = Image.new("RGBA", (1080,1920))
        draw = ImageDraw.Draw(scrim)
        for y in range(1920):
            alpha = int(160*max(0,1-y/620)) if y < 620 else int(145*max(0,(y-1060)/860))
            if alpha:
                draw.line((0,y,1080,y),fill=(0,0,0,alpha))
        scrim.save(work/"scrim.png")
    if layout == "audiogram":
        background = Image.new("RGB", (1080,1920))
        draw = ImageDraw.Draw(background)
        color = ImageColor.getrgb(brand["color"])
        for y in range(1920):
            factor = .3 + .18*(1-y/1920)
            draw.line((0,y,1080,y),fill=tuple(round(c*factor) for c in color))
        draw.ellipse((380,550,700,870), fill=brand["accent"])
        initials = "".join(t[0] for t in (brand.get("name") or "Audio").split()[:2]).upper()
        draw.text((540,710),initials,font=font(110,brand.get("font")),fill="#171522",anchor="mm")
        if brand.get("logo") and not no_logo:
            with Image.open(brand["logo"]) as logo:
                logo = logo.convert("RGBA")
                logo.thumbnail((240,240))
                background.paste(logo,((1080-logo.width)//2,710-logo.height//2),logo)
        background.save(work/"background.png")
    if brand.get("logo") and not no_logo:
        with Image.open(brand["logo"]) as logo:
            logo = logo.convert("RGBA")
            logo.thumbnail((96,96))
            logo.save(work/"logo.png")


def contact_sheet(job, reels, brand):
    from PIL import Image, ImageDraw
    sheet = Image.new("RGB",(810,len(reels)*555),"#171522")
    draw = ImageDraw.Draw(sheet)
    for row, reel in enumerate(reels):
        for col, fraction in enumerate((.1,.5,.9)):
            target = Path(job)/"working"/f"sheet-{row}-{col}.png"
            run([ffmpeg(),"-nostdin","-y","-v","error","-ss",str(max(0,reel["duration"]-1.5) if col == 2 else reel["duration"]*fraction),"-i",Path(job)/reel["file"],"-frames:v","1","-vf","scale=270:480",target])
            with Image.open(target) as still:
                sheet.paste(still,(col*270,row*555+75))
        label = f"Reel {reel['number']} · {reel['headline'].replace('*','')}"
        f = font(26,brand.get("font"))
        while draw.textlength(label,font=f) > 785 and len(label)>10:
            label = label[:-2]
        draw.text((16,row*555+12+f.getmetrics()[0]),label,font=f,fill="white",anchor="ls")
    sheet.save(Path(job)/"contact-sheet.jpg",quality=90)
