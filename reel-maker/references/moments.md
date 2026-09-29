# Picking moments that stop the scroll

The script scores every window with a hook-first formula (hook 35%, stand-alone 20%, payoff 20%, pace 15%, length 10%) and saves the sub-scores in `moments.json`. Use them as a shortlist. Your judgment beats the formula: you can read meaning, the script can only count words.

## The stranger test

Picture someone who has never heard of the speaker, scrolling at 11pm, half distracted and a bit skeptical. In the first 3 seconds, would they stop? At the end, would they want to know more about what the speaker offers? Pick the moments where both answers are yes.

## What a great clip has

1. **A hook in the first sentence.** Tension, a surprising claim, a specific number, a question the viewer wants answered, or a result. "Most people price this completely wrong" beats "So, the next thing I want to talk about is pricing."
2. **It stands alone.** No "like I said earlier", no "that" or "it" pointing at something the viewer never saw. If it needs setup, start earlier or skip it.
3. **A payoff.** The clip delivers what the hook promised: the answer, the example, the before and after, the number. End right after the payoff lands, on a complete sentence.
4. **Proof over claims.** A real story, a client result, a specific example. Never invent or exaggerate a result that is not in the transcript.
5. **Offer fit.** It gives the viewer a reason to want what the speaker sells (their service, course, product, community). Work out the offer from the whole transcript first.
6. **Variety.** Across the set, mix types: one insight, one story or result, one objection answered, one contrarian take. Don't pick three clips from the same five minutes.

## Moment types that work

| Type | Opening line looks like |
|---|---|
| Contrarian take | "Everyone says X. That's wrong." |
| Mistake | "The biggest mistake I see is..." |
| Result / before-after | "We went from 2 calls a month to 11." |
| How-to in one breath | "Here's the three-step version." |
| Objection answered | "People ask me if this works for small teams." |
| Story with a turn | "Last week a client called me, panicking." |
| Guest testimonial | "Before this I was working 70-hour weeks." (guest, not the host) |

## Boundaries

- Start on the hook sentence itself. Cut filler openers ("so", "um", "and", "yeah") by starting one word later.
- 20 to 60 seconds. 30 to 45 is the sweet spot. Shorter is better than padded.
- End on a full stop, not mid-thought. The script adds a small tail and stops before the next word.
- Use `working/transcript.txt` to find word indexes: each line shows the index of its first word, count forward for the exact word.

## Writing the text

- **Headline** (burned into the top of the video): 7 words or fewer, concrete, the reason to keep watching. Mark ONE word with `*asterisks*` for the accent color. Good: `Why your *pricing* page scares buyers`. Bad: `Great insights on pricing strategy`.
- **Post caption** (captions.txt): first line = the hook, 1 to 3 short lines of value, then the CTA from the brand settings. Under 120 words. No hashtag walls; 0 to 3 relevant ones if the user wants them.
- **Cover text**: 5 words or fewer, readable as a thumbnail.
- **Captions**: fix misheard names and words with `display` in `working/transcript.json`. Keep the speaker's words and meaning. Proper nouns and "I" capitalized.

## When there isn't enough

If a short video only has one or two strong moments, make fewer reels and say why. Never pad the count with weak clips, and never invent content.
