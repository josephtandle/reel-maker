# Read, score, then choose

Read all transcript words before identifying the speaker's offer. Keep the host's insights and guest results; never assume a guest is the seller. Avoid transcript hallucination/repetition loops. A sellable moment is a truthful result, before/after, useful insight or answered objection, not a fabricated promise.

List exactly 10 candidates (they may overlap each other), each 20–59 seconds and complete sentences with no preceding fragments. Score each dimension 1–5:

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| hook | Slow setup | Interesting question | Immediate tension/result in first 3 s |
| clarity | Depends on missing context | Mostly understandable | Fully stand-alone |
| proof | Unsupported assertion | Specific example | Concrete, credible result |
| offer_fit | Unrelated | Broadly relevant | Direct reason to want the actual offer |

Sum the four scores. Select the top 3–5 that do not overlap and provide useful variety. Save any tie-break/overlap substitution in selection_note. If the user chooses another candidate, honor that choice and note the override. For an unusually short source with fewer than 10 distinct good candidates, candidates may be alternate boundaries around the same moments; disclose that. Do not invent new content to fill a quota. If enough complete moments cannot be found, NEEDS_INPUT for a longer recording.

The first run creates moments.json with this schema:

```json
{
  "offer": "A factual description inferred from the full transcript",
  "transcript_read_in_full": true,
  "selection_note": "Top non-overlapping moments, with varied proof",
  "candidates": [{
    "id": 1, "first_word": 0, "last_word": 60,
    "headline": "A concrete benefit in seven words",
    "reason": "Why this actual excerpt supports the offer",
    "scores": {"hook": 5, "clarity": 4, "proof": 5, "offer_fit": 5},
    "complete_sentences": true, "selected": true,
    "instagram_caption": "Under 120 words, ending with the supplied CTA.",
    "cover_text": "Under five words",
    "participants": ["Host", "Guest (not host)"]
  }]
}
```

Expand to ten entries. first_word and last_word are inclusive zero-based indexes into `working files/words.json`; `working files/transcript.txt` shows the first word index of every cue. The script calculates start, end and total. End is final word end +0.4 s, bounded by the next word and recording end so a new sentence does not leak in. Selected moments are then re-timed with local Whisper on a window padded by 2 seconds. Matched words use Whisper times; unmatched words interpolate between anchors. The start snaps to the nearest preceding PCM silence gap; the tail becomes at most .15 s. T5/T6 machine checks on the final reel must confirm sync and a clean first word. Missing models preserve estimates and require review; do not blindly trim off the intended first word.

Set optional display on a word to correct caption text; keep text as originally transcribed and preserve timing. Use sentence case, light punctuation, fix only unmistakable mishearings and remove um/uh or accidental adjacent duplicates. Names/acronyms keep their proper casing. Clean captions do not authorize rewriting the speaker's meaning.

To swap a reel, toggle selected on the old/new candidates, keep the count consistent, then run with --rerender NEW_ID. Other current renders remain; removed selections remain on disk as old revisions but leave the current manifest/contact sheet. Share only the current manifest's reels.
