# VayuSetu — Submission

Build with AI: Code for Communities, Second Edition · Track 02, Clean Air & Climate
Resilience.

Every number below was measured in this repository and can be reproduced from the
command next to it. `SUBMISSION_CHECKLIST.md` tracks what is done; this file holds the
text that goes into the form, the deck and the video.

---

## Links

| Deliverable | Where | Status |
|---|---|---|
| Live demo | https://vayusetu-999960875509.asia-south1.run.app | Deployed, verified 2026-09-13 |
| Residents view | https://vayusetu-999960875509.asia-south1.run.app/#/residents | Deployed |
| Source code | *not yet published — no git remote exists* | **To do** |
| Demo video (3–5 min) | — | **To do** — script below |
| Pitch deck (10–12 slides) | — | **To do** — outline below |

---

## Brief description (2–3 lines)

> VayuSetu tells Delhi NCR's officials **why** the air is bad, **where** it is far worse
> than the city average shows, and **who** should act — fusing 65 CPCB monitors, NASA
> fire detections and ERA5 weather in BigQuery, with Gemini reasoning over measured
> evidence and every claim checked in code before it is shown. It finds hyper-local
> events the average hides (NSIT Dwarka at 507-629 µg/m³ for three hours while its surroundings read 123), refuses readings from broken monitors, and turns
> them into cases for the responsible agency that close only when a Gemini-checked site photo and the
> measurements afterwards both show the problem gone. It also shows where farm-fire counts have
> stopped telling the truth: Punjab burned 10× more land per satellite fire alert in 2025 than in 2020 — with advice for residents in ten Indian languages, read aloud.

Short form (if the field is tight):

> VayuSetu explains why Delhi NCR's air is bad, finds localities breathing four times the
> city average, flags broken government monitors, and gives the responsible agency a case it can only close with verified evidence — Gemini reasoning over measured
> satellite, fire and monitor data, checked in code, with advice for residents in ten
> Indian languages.

---

## The five things the track asked for, and where we stand

Honest mapping, because judges will do this mapping themselves.

| Track asks | Delivered | Evidence |
|---|---|---|
| Combine citizen photos, satellite and meteorology | **Yes.** Monitors + FIRMS fires + ERA5 wind and boundary layer + Earth Engine layers; Gemini photo triage that corroborates but never sets a value | `api/evidence.py`, `api/gemini/vision.py` |
| Detect hidden pollution hotspots | **Yes — hidden by the average**, not hidden from the network. 111 confirmed event-hours in 26 localities on 21 days, after refusing 51 outliers as sensor faults. **And burning hidden from the fire count:** MODIS burn scars against VIIRS alerts per district; Sangrur is #1 by land burned and #3 by alerts, with 20.5× its 2020-21 land per alert | `python -m api.hotspots`, `python -m api.integrity`, `python -m ingestion.fire_ledger` |
| Reach beyond one city | **Yes.** The integrity gate runs over 361 CPCB monitors in 26 states: 62 (17%) not trustworthy, and an error code (985.0 µg/m³) found reaching the public feed on 8 monitors | `python -m ingestion.monitor_ledger` |
| Forecast air-quality spikes | **Tested and falsified**, deliberately not shipped. "Warn after 6 Nov" beats every weather rule (Peirce +0.71 vs +0.61) | `python -m ml.evaluate_warning` |
| Alert authorities for rapid intervention | **Yes, and follows it to closure.** Cases routed to the responsible agency with deadlines and CAQM escalation; closure needs a Gemini-checked photo and measurements showing the problem gone; demo accounts only | `python -m api.alerts` |
| Cross-boundary action (smoke from Punjab and Haryana) | **Yes, on what the data supports.** Verification notices to Punjab's and Haryana's boards, copied to CAQM, for the nine districts whose burn scars most outrun their fire alerts; a daily "this state caused this day" link was tested (r = +0.32 detrended) and not claimed | `python -m api.cases` |
| Interoperability — cities share models | **Partly.** Open schemas published and validated in code; the model registry is empty because no model passed its guard; Lucknow is provisioned but not ingested | `spec/`, `ml/registry.py` |

---

## Demo video script (target 4:00)

Record from the live URL, not localhost. **Say the replay out loud** (checklist R7).

| Time | Screen | Say |
|---|---|---|
| 0:00–0:25 | Officials view, 12 Nov 01:30 | "Every AQI app in India shows a number and a colour. This is a replay of a real November 2025 episode: Delhi NCR at Severe, 407 µg/m³. The question nobody answers is *why* — and who should do what." |
| 0:25–1:10 | Map with wind fan and fires; brief panel | "33 fires inside the upwind fan, a 110-metre air ceiling trapping it. Gemini reads only measured evidence, and every number it cites is checked against the data in code before you see it. It names the offices that should act." |
| 1:10–1:50 | Hyper-local panel on the regional hour, then the NSIT Dwarka event, then the Arya Nagar exclusion | "At the peak, no single locality stands out — the whole region is affected, and the page says so. Jump to 30 October: the region read 123. NSIT Dwarka read over 500 for three hours — four times its surroundings, 24,500 people in that square kilometre. And on 16 November a monitor read 918 — and we refuse it: its readings jump from 886 to 4 to 918 to 19. It is broken. A hotspot map without this check sends inspectors to faulty boxes." |
| 1:50–2:40 | Cases: open from the hour, take ownership, try to close | "Detection isn't where India fails — closure is: Green Delhi had ten thousand overdue complaints, and some departments saw half their 'resolved' cases reopened. Here, measurements open a case for the agency named on the monitor itself, with a deadline. Watch me try to close the region-wide case with a note: refused — the monitors still show Severe a day later. Close Dwarka with a site photo: Gemini checks the photo, the readings show the excess gone two hours later — closed, verified. Every agency is a demo account." |
| 2:40–3:05 | Farm fires: Punjab trend, then toggle the district ranking | "Stubble burning is policed by fire counts, from satellites that pass at midday — and farmers now burn after they pass. Burn scars see every field. Punjab's fire alerts fell 95% since 2020; land burned fell 49%. Rank by land and Sangrur is first; rank by alerts and Amritsar is. One button sends nine verification notices to the Punjab and Haryana boards, copied to CAQM. We don't claim Punjab caused a given Delhi day — we tested that, and the data can't show it." |
| 3:05–3:25 | Residents view, switch to Hindi, press listen | "Residents get the same facts in their language — ten Indian languages, read aloud. A photo of the haze is checked by Gemini: it can corroborate, never set a pollution value." |
| 3:25–3:35 | India tab, expand Karnataka | "The same check, every CPCB monitor in the country: 62 of 361 not trustworthy — including eight monitors publishing the number 985 as if it were air." |
| 3:35–3:50 | TODO.md falsification table or a slide | "We tested our own ideas. A gridded model lost to interpolation. A 72-hour forecast lost to persistence. A day-ahead warning lost to the calendar. So we shipped none of them, and built what the data supports." |
| 3:50–4:00 | Live URL on screen | "VayuSetu. Live, open source, built on Google Cloud." |

---

## Deck outline (13 slides)

1. **Title** — VayuSetu: why the air is bad, where it is worst, who should act.
2. **The problem** — a number and a colour; 30M people, ~40 official monitors; GRAP decisions taken on a city average.
3. **What officials actually need** — three questions after the number: why, where, who.
4. **Live product** — screenshot of the officials view on 12 Nov 01:30.
5. **Why** — attribution: upwind fire cone + boundary layer, r = +0.58 / −0.48 on 26 IST days; Gemini with code-checked citations.
6. **Where, and can we trust it** — NSIT Dwarka 507-629 vs 123 for 3 h; 111 confirmed event-hours in 26 localities; the Arya Nagar 918 that was a broken sensor, and the national monitor-reliability numbers.
7. **Who owns it, and was it really fixed** — cases routed from the monitor's own name, deadlines and CAQM escalation, closure refused unless the photo and the measurements agree; the Green Delhi overdue and reopen numbers as the motivation.
8. **The fires the count stopped seeing** — Punjab 2020 → 2025: alerts −95%, land burned −49%, 0.23 → 2.28 km² per alert; the two district rankings side by side (Amritsar #1 by alerts / #10 by land; Sangrur #3 / #1); nine cross-state verification notices, and why they are not daily blame (r = +0.32 detrended).
9. **One city or every city** — the gate over 361 CPCB monitors in 26 states: 62 untrusted, 985.0 as a published reading; what a state board gets on day one.
10. **Residents** — ten languages, speech, photo triage that cannot set a value.
11. **We tested our own ideas** — the falsification table (seven "No", one "Yes"). The proof of rigour, not an apology.
12. **Deployable and scalable** — one Cloud Run service, BigQuery per-tenant datasets, open schemas, `infra/deploy.sh`; what a new city needs.
13. **Limits and next** — hotspots only where monitors exist; attribution still counts undercounted fire alerts; forecast BLH and 3+ seasons needed for a warning; identity in front of case actions; Lucknow ingestion.
