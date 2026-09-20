# VayuSetu deck — slide specification

Feed `design.md` first, then this file. 15 slides, 16:9. Every number below was measured
in this repository; the "verify" line on each slide says where it comes from, so nothing
on a slide is unsourced.

**Assets you must supply** are marked `[ASSET n]` and collected in §Assets at the end.
Leave the placeholder box in the deck until the real file is dropped in.

Live URL for every screenshot: `https://vayusetu-999960875509.asia-south1.run.app`

---

## Slide 1 — Title · archetype A (dark)

**Headline:** VayuSetu
**Subhead (32 px, dim):** Why the air is bad, where it is worst, and who should act —
with every number measured.
**Footer line (15 px, blue):** Build with AI: Code for Communities · Track 02, Clean Air
& Climate Resilience
**Footer line 2 (15 px, muted):** vayusetu-999960875509.asia-south1.run.app · Delhi NCR,
replaying a real November 2025 episode

**Graphic:** behind the text, a very low-contrast (8% opacity) sparkline of the 26-day
city PM2.5 series rising into the November peak, bled off the right edge. Data shape:
starts ~150, dips ~95 on 4 Nov, climbs to ~280 by 12 Nov, holds ~215-250 to 19 Nov.
No axes, no labels — texture only.

---

## Slide 2 — The problem · archetype B

**Kicker:** THE PROBLEM
**Headline:** Every air quality app in India tells you a number and a colour

**Stat tiles (4):**
| 30M+ | people in Delhi NCR |
| ~40 | official monitors the city is judged by |
| 84,765 | pollution complaints to Green Delhi in 2024 |
| 10,656 | of them went overdue |

**Body (one line under the tiles):** A city average hides the locality breathing four
times it, says nothing about why, and names nobody to fix it. One department had 99 of
its 183 "resolved" complaints reopened.

**Speaker note:** India does not usually fail at detection. It fails at *explanation* and
at *closure*. That is the gap this product is built in.

**Verify:** Green Delhi figures — `README.md`, "Cases go to demo accounts" and
`api/cases.py` module docstring.

---

## Slide 3 — What it does · archetype E (table)

**Kicker:** THE PRODUCT
**Headline:** Six questions that come after the number

| Question | Answered from |
|---|---|
| What is happening? | 70 CPCB monitors via OpenAQ, hourly |
| **Can that monitor be trusted?** | **Four integrity checks on every single reading** |
| Where is it worst? | Each monitor against the robust median of its neighbours |
| Why? | NASA FIRMS fires sectored by ERA5 wind, and boundary layer height |
| Who should act, by when? | Gemini over measured evidence; cases with deadlines |
| Was it really fixed? | A checked site photo **and** the readings afterwards |

Emphasis row (blue tint fill): row 2 — it is the row nobody else has.

**Graphic:** to the right of the table, a thin vertical pipeline diagram:
`measure → gate → detect → explain → assign → verify`, each step a small box, the "gate"
box in blue. 6 steps, top to bottom, connected by 1 px hairlines.

---

## Slide 4 — Hero episode · archetype F (screenshot)

**Kicker:** 12 NOVEMBER 2025, 01:30 IST
**Headline:** A real Severe episode, explained end to end

`[ASSET 1]` — screenshot of the officials view at the hero hour.

**Callouts (blue numbered circles on the screenshot):**
1. City average **407.3 µg/m³** — Severe, 2.31× the 14-day baseline
2. Air ceiling **110 m** — a lid holding the smoke down
3. **33 of 68** nearby fires inside the upwind wind fan (from 325°)

**Right column (3 bullets):**
- Gemini names the cause — crop residue burning, confidence 0.85 — and the offices that
  should act.
- It only ever sees measured evidence, and every number it cites is checked against the
  data in code before the page renders.
- Two monitors reporting that hour failed the integrity checks and were dropped from the
  average and the analysis.

**Verify:** `GET /api/v1/ncr/episode?ts=2025-11-11T20:00:00Z`; `api/evidence.py`.

---

## Slide 5 — The hidden event · archetype B + inline chart

**Kicker:** HYPER-LOCAL DETECTION
**Headline:** The event the city average hid

**Stat tiles (4):**
| 629 → 507 | NSIT Dwarka, three hours running |
| 123 | the region's median that same hour |
| 4.1× | its surroundings |
| ~24,500 | people in that square kilometre |

**Graphic (below tiles):** a horizontal dot-strip of all ~60 monitors reporting at
30 Oct 2025 13:30 IST, plotted by PM2.5 on a 0–700 axis. The cluster sits at 90–160 in
Moderate yellow; one dot far right at 629 in Severe maroon, labelled "NSIT Dwarka". A
vertical hairline marks the median at 123 labelled "what the city average sees".
This single graphic *is* the argument — give it half the slide.

**Footer line:** Across the window: **111 confirmed event-hours in 26 localities on 21
days** — trusted readings, far above their surroundings, for at least two consecutive
hours with distinct values.

**Verify:** `python -m api.hotspots`; `GET /api/v1/ncr/hotspots?ts=2025-10-30T08:00:00Z`.

---

## Slide 6 — The broken sensor · archetype D (evidence block)

**Kicker:** WHAT WE GOT WRONG
**Headline:** Our own headline hotspot was a broken instrument

**Evidence block** (per `design.md` §5) — title line
`ARYA NAGAR, BAHADURGARH · 16 NOV 2025, HOURLY PM2.5`, values:

```
717   31   559   33   500   0   886   4   918   19   557   0   0   0
```

Colour the impossible ones (`31, 33, 0, 4, 19, 0, 0, 0`) in `#B3261E`; second line in
dim: `Every monitor within 25 km, same hours: 250–300`.

**Three bullets under it:**
- The first version of this deck's headline was "918 µg/m³ in Bahadurgarh". PM2.5 does
  not do that. The instrument was broken.
- **22 of the 40** events our detector first ranked highest had faults like this nearby.
- So nothing reaches a map, a case or the AI until it passes four checks — thresholds set
  from the distribution of **35,602 real station-hours**, not guessed.

**Verify:** `TODO.md` 2026-09-15; `python -m api.integrity`.

---

## Slide 7 — The gate · archetype C (diagram left, text right)

**Kicker:** THE INTEGRITY GATE
**Headline:** Four checks, and what each one catches

**Graphic (left):** four small sparkline cards stacked, each showing the fault shape in
`#B3261E` against a flat grey neighbour line:
1. **Stuck** — the same value 3+ hours (±0.05). *Flat line.*
2. **Dead zero** — below 5 µg/m³ while the region reads 60+. *Drops to the floor.*
3. **Spike** — up 200 and back down 200 within an hour. *Single tooth.*
4. **Low in episode** — robust z ≤ −3.5 while the region is Severe. *Suspicion only,
   never proof — a monitor can genuinely sit in a cleaner pocket.*

**Right column:**
- A reading is trusted only if no fault flag sits within ±3 hours at that monitor.
- Monitors are then labelled **faulty** (≥5% faulted hours), **offline** (<50% uptime),
  **check siting**, or **healthy**.
- In the Delhi window this refused **51 outliers** that would otherwise have been
  hotspots — and the attribution finding survived unchanged: **r = +0.57** with upwind
  fires, **−0.48** with the air ceiling.

**Verify:** `api/integrity.py`; `python -m api.integrity`.

---

## Slide 8 — National reach · archetype B + ranked table

**Kicker:** THE SAME CHECK, EVERY CPCB MONITOR
**Headline:** 62 of 361 monitors across India could not be trusted

**Stat tiles (4):**
| 361 | CPCB monitors, 26 states |
| 186,645 | hourly readings checked |
| 62 (17%) | not trustworthy: 40 faulty, 22 dark |
| 240 (66%) | had at least one faulted hour |

**Ranked table (5 rows), with an inline bar in the "not trustworthy" cell:**

| State | Monitors | Not trustworthy |
|---|---|---|
| Karnataka | 23 | 14 |
| Tamil Nadu | 27 | 10 |
| Andhra Pradesh | 21 | 7 |
| Maharashtra | 69 | 7 |
| Odisha | 18 | 5 |

**Do not draw a filled India map** (`design.md` §4, rule 5).

**Footnote (13 px muted):** Each monitor is judged against its own state's hourly median,
never a national one. In 13 of the 26 states too few monitors report together to form a
median, so only the stuck-value and spike checks can fire there — those states are
labelled, not counted as clean.

**Verify:** `python -m ingestion.monitor_ledger`; `GET /api/v1/ncr/national/monitors`.

---

## Slide 9 — The error code · archetype D (evidence block)

**Kicker:** WHAT THE NATIONAL RUN FOUND
**Headline:** An error code is being published as a pollution reading

**Evidence block** — title `B.KATIHALLI, HASSAN, KARNATAKA · HOURLY PM2.5`:

```
985.0   985.0   985.0   985.0   985.0   985.0   985.0
```

all in `#B3261E`; second line dim: `The rest of Karnataka, same hours: 30–36`.

**Two stat tiles beside it:**
| 8 monitors | publishing exactly 985.0, across Karnataka and Tamil Nadu |
| 345 hours | of it — 214 at this one monitor |

**One line below:** Exactly 0.0 appears **4,516 times across 155 monitors**. A number that
round, repeating across two states, is an instrument or pipeline code — not air. Nobody
is watching for it, and every dashboard built on this feed inherits it.

**Verify:** `TODO.md` 2026-09-20; `vayusetu_shared.monitor_ledger`.

---

## Slide 10 — Cases · archetype C (flow diagram)

**Kicker:** FROM MEASUREMENT TO CLOSURE
**Headline:** A case closes only when the evidence and the measurements agree

**Graphic (left, flow diagram, 5 boxes left to right with arrows):**
`Trusted measurement` → `Case opened, owner + deadline` → `Agency acts` →
`Closure submitted: photo + note + location` → decision fork:
- up branch, green `#0D5323`: **Closed, verified** — "the excess subsided 2 h later"
- down branch, red `#B3261E`: **Refused** — "the region is still Severe, median 304"

**Right column:**
- The owner is read from the monitor's own name: "NSIT Dwarka, Delhi - CPCB" routes to
  Delhi's municipal enforcement, copied to the state board.
- Deadlines: **24 h** local event, **72 h** broken monitor, **12 h** regional episode,
  **7 days** a farm-fire notice. Overdue and CAQM escalation are computed when the queue
  is read, so there is no scheduler to fail quietly.
- Gemini *describes* the photo — genuine site photo, is a source still visible, is the
  monitor in frame. **Code decides.** A clean photo cannot close a case the measurements
  say is still happening.
- Every agency and officer in the demo is a mock account; no real contact details exist
  anywhere in the codebase.

`[ASSET 2]` — optional inset: screenshot of a refused closure with its reason.

**Verify:** `python -m api.cases`; `GET /api/v1/ncr/cases`.

---

## Slide 11 — Farm fires · archetype C (paired bars — the signature graphic)

**Kicker:** CROSS-STATE
**Headline:** Punjab's fire alerts fell 95%. The burning fell 49%.

**Graphic (left, paired bar chart), Punjab, Oct–Nov:**

| Season | Daytime fire alerts | Land burned (km²) |
|---|---|---|
| 2020 | 74,975 | 17,565 |
| 2021 | 77,722 | 17,531 |
| 2022 | 46,260 | 16,419 |
| 2023 | 30,766 | 14,689 |
| 2024 | 8,781 | 6,244 |
| 2025 | 3,936 | 8,965 |

Alerts in grey `#737780`, land burned in fire orange `#EA580C`, normalised to their 2020
values so both start at 100 and the divergence is the story. Annotate 2025 with a blue
callout: **"0.23 → 2.28 km² burned per alert: a 10× change"**.

**Right column:**
- Fire counts come from satellites that pass over Punjab around midday. An independent
  analysis of geostationary data found **90% of large Punjab fires in 2024-25 were set
  after 3 PM**, against 3% in 2021. The counts stopped seeing them; the burn scars did not.
- Night passes do not catch them either — night detections are flat at 82–136 a season.
- Haryana shows the same shift: 0.33 → 1.39 km² per alert.

**Verify:** `python -m ingestion.fire_ledger`; `GET /api/v1/ncr/fires/ledger`.

---

## Slide 12 — Rank flip · archetype C (slope diagram)

**Kicker:** WHERE THE INSPECTORS SHOULD GO
**Headline:** Rank districts by alerts and you go to the wrong ones

**Graphic:** two vertical ranked lists with connecting lines between the same district.
Left list "By fire alerts (2025)", right list "By land burned (2025)". Lines that cross
steeply are the point; draw those two in blue, the rest in hairline grey.

| District | By alerts | By land burned | Land per alert vs its own 2020-21 |
|---|---|---|---|
| Amritsar | **1** | 10 | 2.6× |
| Firozpur | 2 | 2 | 12.6× |
| Sangrur | 3 | **1** | **20.5×** |
| Bathinda | 4 | 5 | 13.9× |
| Mansa | 10 | 4 | **22.2×** |

**Callout under the diagram:** Sangrur burned **3,198 km²** and raised **531 alerts**. At
its own 2020-21 rate, that burning would have raised about **10,900**.

**Right column, 2 bullets:**
- Nine districts cross the threshold (8× and 200 km²). Each gets a verification notice to
  its state board, copied to CAQM, with a 7-day deadline — eight in Punjab, one in Haryana.
- It is **not** blame for a given Delhi day. We tested that link: after removing the
  seasonal trend, wind-carried Punjab fires explain Delhi's daily PM2.5 at **r = +0.32**
  over 23 days. That cannot name a state as the cause of a day, so the deck does not.

---

## Slide 13 — Falsification · archetype E (table, the credibility slide)

**Kicker:** WE TESTED OUR OWN IDEAS
**Headline:** Seven things we tried to prove, and the one that survived

| Claim we tested | Verdict |
|---|---|
| A gridded ML model beats simple interpolation | **No** — MAE 53.81 vs 52.93 |
| Satellite AOD explains where interpolation is wrong | **No** — r = +0.04 |
| A 72-hour forecast beats diurnal persistence | **No** — loses at every horizon |
| A day-ahead Severe warning beats the calendar | **No** — +0.61 vs the calendar's +0.71 |
| Our top-ranked hotspot was real pollution | **No** — a faulty monitor; 22 of the top 40 |
| Burned area explains Delhi's daily PM2.5 | **No** — r = −0.66; smoke hides the scars |
| **Upwind fires + air ceiling explain the episodes** | **Yes** — r = +0.55 and −0.42 |

Style: the six "No" rows in dim with the verdict in `#B3261E`; the final row on blue tint
with the verdict in `#0D5323`, bold.

**Line below the table (blue, 20 px):** The model registry refuses to publish a model that
loses to its own baseline. It refused ours — so none of the failures ship, and there is no
forecast and no predicted-hotspot map in the product.

**Speaker note:** This is the slide that separates us from a demo that would break in
week two. Say out loud: "we shipped what survived."

---

## Slide 14 — Deployable · archetype C (architecture diagram)

**Kicker:** BUILT TO BE RUN BY SOMEONE ELSE
**Headline:** One service, one command, any Indian city

**Graphic (left, simple architecture, 3 columns of boxes left to right):**
- **Sources:** CPCB/OpenAQ · NASA FIRMS · ERA5 (Open-Meteo) · Earth Engine (MODIS burn
  scars, population) · Google Air Quality
- **BigQuery:** `vayusetu_<tenant>` (per city) + `vayusetu_shared` (fires, ledgers)
- **Cloud Run (asia-south1):** API + built site, one service — with Gemini 3.5 Flash Lite,
  Cloud Translation, Cloud Text-to-Speech hanging off it

**Right column:**
- `bash infra/deploy.sh` builds, deploys and smoke-tests the deployment itself.
- A new city is a bounds entry, a dataset and a backfill — the same path the national run
  used to cover 26 states.
- Two open Apache-2.0 schemas so another system can consume an episode without trusting
  our models; validated against real output on every run.
- **No API key in the repository or the image.** Gemini's lives in Secret Manager; Google
  Air Quality authenticates as the runtime service account.

`[ASSET 3]` — optional: screenshot of the resident view in Hindi with the Listen button.

---

## Slide 15 — Limits and ask · archetype A (dark) or B

**Kicker:** WHAT IT DOES NOT DO
**Headline:** The limits, stated plainly

Four short lines, each on its own row with a hairline between:
- **No forecast, no predicted hotspot map.** Both were falsified; neither is served.
- **Hotspots are hidden by the average, not from the network.** The detector needs a
  monitor to be there.
- **Attribution is correlational** over one season, and counts fire alerts that now
  undercount burning about tenfold.
- **The demo is a replay**, labelled on screen, because the CPCB live feed is stalled —
  the Monitors tab shows Google's modelled air beside our latest measurement and its age.

**Closing line (32 px, centred):** Every number in this deck can be recomputed from the
repository.
**Footer:** vayusetu-999960875509.asia-south1.run.app

---

## Assets you need to supply

| # | What | How to capture |
|---|---|---|
| **ASSET 1** | Officials view at the hero hour — **required**, slide 4 | Open `/#/`, set the time slider to **12 Nov 2025, 01:30 IST**. Wait for the brief to load. Window 1600 × 1000, light theme, browser chrome cropped out. Must show the map with the wind fan, the four stat cards and the brief panel. |
| **ASSET 2** | A refused closure — optional, slide 10 | Open `/#/cases`, find the region-wide case, "Submit closure", type a note, submit. Capture the red "Closure refused" verdict with its reason and the 24-hour outcome bars. |
| **ASSET 3** | Resident view in Hindi — optional, slide 14 | Open `/#/residents`, switch language to हिन्दी. Capture the coloured band, the advice and the Listen button. |
| **ASSET 4** | Farm fires desk — optional, slide 11 or 12 | Open `/#/fires`. Capture the Punjab/Haryana trend cards and the district table with the ranking toggle visible. |
| **ASSET 5** | India tab with a state expanded — optional, slide 8 or 9 | Open `/#/national`, expand **Karnataka** so the raw-reading strip for B.Katihalli is visible. |
| **ASSET 6** | Team photo or logo — optional, slide 1 or 15 | Anything you want credited. |

If an asset is missing at submission time, keep the placeholder box: an honest "screenshot
to come" reads better than a slide that silently lost its evidence.

---

## Timing for the live pitch

| Slides | Minutes | Beat |
|---|---|---|
| 1–3 | 0:45 | The gap: a number and a colour, no why, no owner |
| 4–5 | 1:15 | It works, and it finds what the average hides |
| 6–7 | 1:00 | We caught ourselves; the gate is the product |
| 8–9 | 0:45 | It scales — and it found an error code in the national feed |
| 10 | 0:45 | Closure is where India actually fails |
| 11–12 | 1:00 | The fire counts are wrong, and here is where to send people |
| 13 | 0:45 | We published what failed |
| 14–15 | 0:45 | Deployable, and honest about its limits |
