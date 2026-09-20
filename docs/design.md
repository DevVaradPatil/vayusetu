# VayuSetu deck — design system

Art direction for the pitch deck. Paste this file **first** into Claude Design, then
`deck.md` for the slide-by-slide content. Everything here is derived from the product's
own design tokens (`web/src/theme.css`), so the deck and the live site look like one thing.

---

## 0. The one-line brief

> A measurement instrument's report, not a startup pitch. Calm, dense, factual, with big
> honest numbers and visible evidence. The audience should finish it believing *every
> figure on screen could be checked* — because in the product, it can.

Reference points: The Economist / FT graphics desk, ProPublica data stories, a Google
Cloud technical keynote. **Not** a SaaS landing page, not a 3D-illustration startup deck,
not gradients-and-glow.

---

## 1. Canvas and grid

| | |
|---|---|
| Aspect | 16:9, 1920 × 1080 px (13.333 × 7.5 in) |
| Outer margin | 88 px left/right, 64 px top, 72 px bottom |
| Column grid | 12 columns, 24 px gutters |
| Baseline rhythm | 8 px; every gap is a multiple of 8 |
| Safe zone | Nothing critical within 40 px of any edge (projector overscan) |

**Layout rule:** one idea per slide, and the headline states the finding, not the topic.
"Our own headline was a broken sensor" beats "Data quality". Every slide is one of the
six archetypes in §6.

---

## 2. Colour

Copied from the product. Two locks that must not be broken:

**Lock 1 — blue is interface, never data.** Titles, rules, kickers, links, the logo mark.
**Lock 2 — the green-to-maroon ramp is the CPCB National AQI scale and is used for
pollution values only.** Never decorate with it, never re-order it, never invent a band.

```
Ink        #1A1C21   headlines, table row labels
Dim        #434750   body text, secondary labels
Muted      #626772   captions, footnotes, source lines
Hairline   #DADDE4   rules, table borders, chart axes
Paper      #FFFFFF   slide background (default)
Band       #F0F2F6   stat tiles, table headers, quiet panels
Blue       #0B57D0   kickers, emphasis, the single accent
Blue tint  #D6E4FD   highlight fills behind key numbers
```

CPCB AQI ramp (data only):

```
Good          #22C55E    ≤ 30 µg/m³
Satisfactory  #84CC16    ≤ 60
Moderate      #EAB308    ≤ 90
Poor          #F97316    ≤ 120
Very Poor     #DC2626    ≤ 250
Severe        #991B1B    > 250
```

Supporting data colours: **Fire / burning** `#EA580C`, **Verified good** `#0D5323`,
**Refused / fault** `#B3261E`, **Modelled (not measured)** `#737780` — always the grey
one, because modelled values must never look like measurements.

Dark slides: exactly two in the deck (title, closing). Background `#121317`, ink
`#E4E2E6`, dim `#C5C6D0`, blue `#A8C7FA`, hairline `#34363E`. Ramp colours unchanged.

---

## 3. Type

Roboto (product font) or Inter. One family, four sizes, no exceptions.

| Role | Size / weight | Notes |
|---|---|---|
| Slide headline | 40 px / 700, ink | Max two lines, sentence case, no full stop |
| Kicker | 15 px / 700, blue, letter-spacing 0.06em, UPPERCASE | One or two words above the headline |
| Body & bullets | 20 px / 400, dim | Max 3 lines per bullet, max 4 bullets |
| Stat number | 64–96 px / 700 | Tabular figures **on** |
| Stat label | 15 px / 400, muted | Sentence case, ≤ 6 words |
| Table cell | 17 px / 400 | Row label 17 px / 600 ink |
| Caption / source | 13 px / 400, muted | Every chart ends with one |

Rules: numbers always tabular (`font-variant-numeric: tabular-nums`) so columns align;
units at 40% of the number's size in muted; no italics; no ALL CAPS except the kicker;
never more than ~55 words of body copy on a slide.

---

## 4. Charts and diagrams

Style: flat, no 3D, no drop shadows, no gradients except a single 8%-opacity tint used as
a band. Axes and gridlines in Hairline; label the data directly instead of using a legend
wherever two series or fewer. Y axes start at zero for anything counted. Annotate the
point the slide is about with a short blue callout line and 15 px label.

Chart types this deck uses, and nothing else:

1. **Paired bar** — two series against a shared category axis (fire alerts vs land burned).
2. **Sparkline strip** — a row of small bars for an hourly series (the broken sensor).
3. **Slope / rank-flip diagram** — two ranked lists with connecting lines (districts by
   alerts vs by land burned). This is the deck's signature graphic; give it room.
4. **Flow diagram** — left-to-right boxes with arrows (how a case closes).
5. **Choropleth-free state table** — a ranked table with a small inline bar in the cell.
   Do **not** draw an India map with state fills: our coverage is uneven and a filled map
   would imply we measured states we barely sampled. A ranked table is the honest form.

Every chart carries a source line: `Source: <dataset>, <window>. Computed in <file>.`

---

## 5. Evidence blocks (the deck's distinctive element)

Wherever a claim rests on raw readings, show the readings. The pattern:

```
┌──────────────────────────────────────────────────────────────┐
│ ARYA NAGAR, BAHADURGARH · 16 NOV 2025, HOURLY PM2.5          │  ← 13 px muted
│                                                              │
│  717   31  559   33  500    0  886    4  918   19  557    0  │  ← 28 px tabular
│                                                              │
│  Neighbouring monitors, same hours: 250–300                  │  ← 15 px dim
└──────────────────────────────────────────────────────────────┘
```

Fill `#F0F2F6`, 8 px radius, 24 px padding, no border. Impossible values in `#B3261E`,
plausible ones in ink. Use this block on slides 6, 7 and 10. It is the thing that makes
the deck feel like an audit rather than a pitch.

---

## 6. Slide archetypes

Use these six; do not invent a seventh.

| # | Archetype | Structure |
|---|---|---|
| A | **Statement** | Dark background, one sentence at 56 px, small attribution. Title and closing only |
| B | **Stat row** | Kicker + headline + 3–4 stat tiles across 12 columns + one line of context below |
| C | **Chart left, text right** | Chart on columns 1–7, headline + 3 bullets on 8–12 |
| D | **Full-bleed evidence** | Kicker + headline + one evidence block (§5) + one line of interpretation |
| E | **Table** | Kicker + headline + one table, max 7 rows, with a blue emphasis row |
| F | **Screenshot** | Product screenshot at 60% width with a 1 px Hairline border and 12 px radius, three numbered callouts in blue circles, notes on the right |

---

## 7. Placeholders for assets I cannot generate

Anywhere the deck needs a real screenshot or photo, leave a visible placeholder box:
Band fill, 2 px dashed Hairline border, centred 17 px muted text reading exactly what is
needed and where to get it, e.g.

```
[ SCREENSHOT — Officials view, hero hour
  https://vayusetu-999960875509.asia-south1.run.app/#/
  Set the time to 12 Nov 2025 01:30 IST · capture at 1600 × 1000, light theme ]
```

`deck.md` lists every one of these with its exact capture instructions. Keep the
placeholders in the generated file so nothing is silently missing.

---

## 8. Accessibility and projection

- Contrast ≥ 4.5:1 for all text. On Severe `#991B1B`, Very Poor `#DC2626` and Fire
  `#EA580C`, use white text; on Moderate `#EAB308` and Satisfactory `#84CC16`, use ink.
- Never encode meaning by colour alone: the fault colour always sits next to the word
  "faulty" or "refused".
- Minimum type on any slide: 13 px (captions). Nothing smaller, ever.
- Assume a washed-out projector: no light grey text on white below `#626772`.

---

## 9. Voice

- Past tense for what was measured, present for what the product does.
- Name the source in the sentence: "MODIS burn scars", "CPCB via OpenAQ", not "our data".
- Give the counter-evidence its own line rather than a hedge: "We tested that. It does not
  hold: r = +0.32 once the season is removed."
- Never write "AI-powered", "revolutionary", "cutting-edge", "seamless", "leverage".
- Indian numbering is fine in speech; on slides use plain grouped digits (3,198 km²).

---

## 10. What "done" looks like

A reviewer flipping through in 90 seconds should land on: *the air is bad for a reason we
can show, the worst place is not the average, the instrument itself may be lying, the work
has an owner and a deadline, the fire counts are wrong, and these people published what
failed.* If a slide does not serve one of those six, cut it.
