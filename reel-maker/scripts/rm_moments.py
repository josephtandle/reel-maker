"""Deterministic hook-first candidate scoring; existing editorial work is sacred."""
from __future__ import annotations
import re
from pathlib import Path
from rm_env import NeedsInput, read_json, write_json, log
from rm_transcribe import sentences
from rm_brand import load, cta

FILLERS = {"so", "um", "uh", "and", "but", "yeah", "like", "okay", "right", "because", "also"}
DANGLING = {"it", "that", "this", "they", "he", "she", "those"}
TENSION = r"\b(never|stop|mistake|secret|truth|wrong|why|how|nobody|most people|the problem|here.s|biggest|actually|instead)\b"
SPECIFICS = r"\d|\b(saved|made|grew|doubled|hours|clients|revenue|booked|finally|realized|learned|the answer|the key)\b"


STOPWORDS = set("is and it the a an of to that we i you or but so this with for in on at be are was".split())
CONNECTORS = set("and but so because which that when once".split())


def headline_phrase(text, maximum=7):
    clauses = re.split(r"[,;:.!?]+|\b(?:and|but|so|because|which|that|when|once)\b", text, flags=re.I)
    candidates = []
    for clause in clauses:
        tokens = re.findall(r"[\w’'%-]+", clause)
        while tokens and tokens[0].lower() in FILLERS | {"well"}:
            tokens.pop(0)
        while tokens and tokens[-1].lower() in STOPWORDS:
            tokens.pop()
        if not tokens:
            continue
        # Prefer a clause ending; shorten long clauses from the left to keep it.
        phrase = tokens[-maximum:]
        while phrase and phrase[0].lower() in FILLERS | {"well"}:
            phrase.pop(0)
        if not phrase:
            continue
        value = 3 * bool(re.search(r"\d", " ".join(phrase)))
        value += 2 * bool(re.search(r"\byou(r)?\b", " ".join(phrase), re.I))
        value += 2 * bool(re.search(TENSION, " ".join(phrase), re.I))
        value += 4 * (len(phrase) >= 3) + min(len(phrase), 5)*.1
        candidates.append((value, phrase))
    if not any(len(phrase) >= 3 for _, phrase in candidates):
        tokens = re.findall(r"[\w’'%-]+", text)
        while tokens and tokens[0].lower() in FILLERS | {"well"}:
            tokens.pop(0)
        while tokens and tokens[-1].lower() in STOPWORDS:
            tokens.pop()
        for end in range(len(tokens), 2, -1):
            phrase = tokens[max(0,end-maximum):end]
            if phrase[-1].lower() not in STOPWORDS and phrase[0].lower() not in CONNECTORS:
                candidates.append((5, phrase))
                break
    if not candidates:
        return "A fresh perspective"
    phrase = max(candidates, key=lambda item: (len(item[1]) >= 3, item[0]))[1]
    result = " ".join(phrase)
    return result[:1].upper()+result[1:]


def auto_headline(text):
    plain = headline_phrase(text)
    tokens = plain.split()
    numbers = [i for i,t in enumerate(tokens) if re.search(r"\d",t)]
    eligible = [i for i,t in enumerate(tokens) if len(t)>=4 and t.lower() not in STOPWORDS]
    accent = numbers[0] if numbers else max(eligible,key=lambda i:len(tokens[i])) if eligible else max(range(len(tokens)),key=lambda i:len(tokens[i]))
    tokens[accent] = "*"+tokens[accent]+"*"
    return " ".join(tokens), headline_phrase(plain, 5)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.replace("*", "").replace("'", "").replace("’", "").lower()).strip("-")[:70] or "highlight"


def score(group, words):
    first = group[0]["text"].lower()
    tokens = re.findall(r"\b[\w’\x27]+\b", first)
    hook = .3 if 4 <= len(tokens) <= 16 else .12
    hook += .18 * ("?" in first) + .17 * bool(re.search(r"[\d$%]", first))
    hook += .15 * bool(re.search(r"\byou(r)?\b", first)) + .2 * bool(re.search(TENSION, first))
    if tokens and tokens[0] in FILLERS | DANGLING:
        hook *= .35
    intro = " ".join(s["text"] for s in group[:2]).lower()
    standalone = 1.0 - .6 * bool(re.search(r"as i said|like i mentioned|going back to|that one", intro))
    end = group[-1]["text"].strip()
    if not re.search(r"[.!?][\"’\x27]*$", end):
        standalone -= .3
    if end.split()[-1].lower().strip(".,!?") in FILLERS:
        standalone -= .4
    later = " ".join(s["text"] for s in group[1:]).lower()
    payoff = min(1, .2 + .16 * len(re.findall(SPECIFICS, later)))
    chosen = words[group[0]["first_word"]:group[-1]["last_word"]+1]
    duration = group[-1]["end"] - group[0]["start"]
    wps = len(chosen) / max(duration, .1)
    pace = max(0, 1 - max(2-wps, wps-3.6, 0) / 2)
    pace *= max(0, 1 - sum(max(0, b["start"]-a["end"]-1.2) for a, b in zip(chosen, chosen[1:])) / max(duration*.3, 1))
    length = max(0, 1 - max(30-duration, duration-40, 0)/25)
    values = {"hook": hook, "standalone": max(0, standalone), "payoff": payoff, "pace": pace, "length": length}
    weights = {"hook": .35, "standalone": .2, "payoff": .2, "pace": .15, "length": .1}
    return round(100*sum(values[k]*weights[k] for k in values)), {k: round(v, 3) for k, v in values.items()}


def find(job, count=None, minimum=20, maximum=60, force=False):
    job = Path(job)
    output = job/"moments.json"
    if output.exists() and not force:
        log("moments.json exists; preserving all edits (use --force to regenerate)")
        return read_json(output)
    if minimum <= 0 or maximum < minimum:
        raise NeedsInput("Choose a positive --min and a --max at least as large.")
    transcript = read_json(job/"working"/"transcript.json")
    words, source = transcript["words"], read_json(job/"working"/"source.json")
    count = count if count is not None else (2 if source["duration"] < 300 else 3 if source["duration"] < 1200 else 4)
    if not 1 <= count <= 5:
        raise NeedsInput("--count must be between 1 and 5.")
    candidates, groups = [], sentences(words)
    for i in range(len(groups)):
        for j in range(i, len(groups)):
            duration = groups[j]["end"] - groups[i]["start"]
            if duration > maximum - .3:
                break
            if duration < minimum:
                continue
            value, scores = score(groups[i:j+1], words)
            candidates.append({"first_word": groups[i]["first_word"], "last_word": groups[j]["last_word"],
                               "start": groups[i]["start"], "end": groups[j]["end"], "score": value, "scores": scores,
                               "hook_line": groups[i]["text"], "text": " ".join(s["text"] for s in groups[i:j+1]),
                               "summary": " ".join(s["text"] for s in groups[i+1:min(j+1, i+3)])})
    candidates.sort(key=lambda m: (-m["score"], abs(m["end"]-m["start"]-35), m["start"]))
    selected = []
    for _ in range(count):
        eligible = [m for m in candidates if all(m["end"]+5.4 <= s["start"] or m["start"] >= s["end"]+5.4 for s in selected)]
        if not eligible:
            break
        best = eligible[0]
        varied = [m for m in eligible if m["score"] >= best["score"]*.9 and all(int(m["start"]//60) != int(s["start"]//60) for s in selected)]
        selected.append(varied[0] if varied else best)
    if not selected:
        raise NeedsInput("No complete moment meets the duration limits. Supply more speech or lower --min with find.")
    if len(selected) < count:
        log(f"Only {len(selected)} non-overlapping moments meet the limits (requested {count})")
    selected.sort(key=lambda m: (-m["score"], m["start"]))
    alternates = []
    for candidate in candidates:
        if candidate in selected or any(candidate["first_word"] == m["first_word"] for m in selected + alternates):
            continue
        alternates.append(candidate)
        if len(selected) + len(alternates) >= 10:
            break
    brand = load()
    moments = []
    for i, item in enumerate(selected + alternates, 1):
        headline, cover = auto_headline(item["hook_line"])
        summary = item.pop("summary")
        moments.append({**item, "id": i, "selected": i <= len(selected), "headline": headline,
                        "cover_text": cover,
                        "post_caption": item["hook_line"] + (" " + summary if summary else "") + "\n\n" + cta(brand),
                        "speaker": "", "speaker_role": "", "layout": "auto", "slug": "",
                        "reason": "Complete sentence boundaries; strongest factors: " + ", ".join(sorted(item["scores"], key=item["scores"].get, reverse=True)[:2])})
    result = {"version": 2, "source": source, "count": len(selected), "min": minimum, "max": maximum, "moments": moments}
    write_json(output, result)
    log(f"Selected {len(selected)} moments; {len(alternates)} alternates")
    return result


def bounds(moment, words, duration):
    if "first_word" in moment and "last_word" in moment:
        first, last = int(moment["first_word"]), int(moment["last_word"])
        if not 0 <= first <= last < len(words):
            raise NeedsInput("Moment word indices are outside the transcript. Review moments.json.")
        start = max(0, words[first]["start"]-.1, words[first-1]["end"] if first else 0)
        end = min(duration, words[last]["end"]+.3, words[last+1]["start"] if last+1 < len(words) else duration)
    else:
        start, end = float(moment["start"]), float(moment["end"])
    if not 0 <= start < end <= duration + .01:
        raise NeedsInput("Moment timestamps must be within the source duration.")
    return start, end
