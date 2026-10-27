# VayuSetu — Finals run sheet (5 minutes)

Share **one browser window** with two tabs: the deck (`docs/VayuSetu_finals.pptx`) and the
live site. Keep this page on a second screen.

**Live:** https://vayusetu-999960875509.asia-south1.run.app

## 5 minutes before

- [ ] Open the site and click every tab once: This hour, Monitors, Cases, Residents → हिन्दी → सुनना.
      The service sleeps when idle and Gemini's first brief takes ~10 s; after this, every page is ~1 s.
- [ ] Dismiss the "How to read this page" card.
- [ ] Deck tab on slide 1. Close everything else; turn notifications off.

## Run order

| Time | Screen | Say |
|---|---|---|
| 0:00–0:30 | **Slide 1** | Every AQI app gives you a number and a colour. An official needs three things after that number: **why** the air is bad, **where** it is far worse than the average, and **who** should act. VayuSetu answers those for Delhi NCR. |
| 0:30–1:45 | **Site → This hour** | A real night: 12 November 2025, 1:30 am, 407 — Severe. *(Say it: this is a real event, replayed, because the government feed stopped in September.)* Point at the **wind fan**: 33 fires upwind, wind from the north-west. **Air ceiling 110 m** — the smoke has nowhere to go. Then the panel: **Gemini** writes this explanation from measured data only, and our code checks every number it quotes before it is shown — that is the green *Checked against data* badge. |
| 1:45–2:30 | **Monitors tab** | Our first headline hotspot, Arya Nagar at 918, was a **broken sensor** — its readings jumped 717, 31, 559, 33. So every reading passes four integrity checks first. Run over every government monitor in India: **62 of 361 aren't trustworthy**. |
| 2:30–3:30 | **Cases tab** | Measurements open a case for the agency responsible, with a deadline. On the region-wide case: **Submit closure**, type a note, **Check evidence and close** → **refused**, the region is still Severe. To close, you need a site photo **Gemini** checks *and* readings afterwards that show the problem gone. |
| 3:30–4:15 | **Residents → हिन्दी → सुनना** | The same facts for residents, in ten Indian languages through **Cloud Translation**, read aloud by **Cloud Text-to-Speech**. A resident's photo is triaged by **Gemini**, but it can never set a pollution value on its own. |
| 4:15–5:00 | **Slide 2** | We tested our own ideas and published what failed: the forecast and the predicted hotspot map lost to simple baselines, so they're not in the product. It runs as one **Cloud Run** service on **BigQuery**, one dataset per city — the same path that already checked monitors in 26 states. |

Short on time: drop the Monitors tab and say the Arya Nagar story in one line on This hour.
Spare time: Farm fires tab — Punjab burned **10× more land per satellite fire alert** in 2025 than 2020, so fire counts now undercount the burning.

## Google AI and Cloud, in one breath

Gemini (the explanation, closure photos, resident photos) · Cloud Translation · Cloud
Text-to-Speech · BigQuery · Earth Engine · Cloud Run · Google Air Quality API, shown only as a
live comparison — nothing in the product runs on it.

## If something breaks

The site does not load → deck slides 3–5 are the same screens as screenshots. Keep talking from them.

## Do not say

"Real-time satellite" (it is daily) · "federated learning" (it is model *sharing*) · "forecast"
(we tested one and it lost) · "exactly 1 km" (approximately).

## Likely questions

- **Is this live?** The pipeline is; the government feed via OpenAQ stalled in September, so we
  replay a real episode and label it on screen. The Monitors tab shows Google's current modelled value beside our last measurement.
- **Why not a forecast?** We built one; it lost to persistence at every horizon, so the registry refused it.
- **How does it scale?** A new city is a bounds entry, a BigQuery dataset and a backfill.
- **What stops a fake closure?** Gemini checks the photo is a genuine site photo within 1 km, and
  the readings afterwards must agree. Either failing refuses the closure, and the refusal is logged.
