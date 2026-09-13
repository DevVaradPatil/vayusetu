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
> events the average hides (Bahadurgarh at 918 µg/m³ while the city average read 202), raises
> alerts from observations to an acknowledge-and-resolve inbox, and tells residents what
> to do in ten Indian languages, read aloud.

Short form (if the field is tight):

> VayuSetu explains why Delhi NCR's air is bad, finds localities breathing four times the
> city average, and alerts the offices that can act — Gemini reasoning over measured
> satellite, fire and monitor data, checked in code, with advice for residents in ten
> Indian languages.

---

## The five things the track asked for, and where we stand

Honest mapping, because judges will do this mapping themselves.

| Track asks | Delivered | Evidence |
|---|---|---|
| Combine citizen photos, satellite and meteorology | **Yes.** Monitors + FIRMS fires + ERA5 wind and boundary layer + Earth Engine layers; Gemini photo triage that corroborates but never sets a value | `api/evidence.py`, `api/gemini/vision.py` |
| Detect hidden pollution hotspots | **Yes — hidden by the average**, not hidden from the network. 251 station-hours across 48 localities on all 26 days | `python -m api.hotspots` |
| Forecast air-quality spikes | **Tested and falsified**, deliberately not shipped. "Warn after 6 Nov" beats every weather rule (Peirce +0.71 vs +0.61) | `python -m ml.evaluate_warning` |
| Alert authorities for rapid intervention | **Yes**, on observed conditions, to mock accounts, with acknowledge/resolve and an audit trail | `python -m api.alerts` |
| Interoperability — cities share models | **Partly.** Open schemas published and validated in code; the model registry is empty because no model passed its guard; Lucknow is provisioned but not ingested | `spec/`, `ml/registry.py` |

---

## Demo video script (target 4:00)

Record from the live URL, not localhost. **Say the replay out loud** (checklist R7).

| Time | Screen | Say |
|---|---|---|
| 0:00–0:25 | Officials view, 12 Nov 01:30 | "Every AQI app in India shows a number and a colour. This is a replay of a real November 2025 episode: Delhi NCR at Severe, 407 µg/m³. The question nobody answers is *why* — and who should do what." |
| 0:25–1:10 | Map with wind fan and fires; brief panel | "35 fires inside the upwind fan, a 65-metre air ceiling trapping it. Gemini reads only measured evidence, and every number it cites is checked against the data in code before you see it. It names the offices that should act." |
| 1:10–1:50 | Hyper-local panel on the regional hour, then click Bahadurgarh | "At the peak, no single locality stands out — the whole region is affected, and the page says so. Jump to 16 November: the region read 202. Arya Nagar in Bahadurgarh read 918 — 4.4 times its surroundings, about 2,000 people in that square kilometre. The reading was public. The average hid it." |
| 1:50–2:30 | Alerts panel: raise, acknowledge, resolve | "Alerts fire only on what is measured. Raising is a deliberate action, never a page load. Every recipient is a demo account — the system holds no real contact details. Acknowledge as the district officer, resolve as the municipal corporation; the trail records who." |
| 2:30–3:15 | Residents view, switch to Hindi, press listen, photo upload | "Residents get the same facts in their language — ten Indian languages, read aloud. A photo of the haze is checked by Gemini: it can corroborate, never set a pollution value." |
| 3:15–3:50 | TODO.md falsification table or a slide | "We tested our own ideas. A gridded model lost to interpolation. A 72-hour forecast lost to persistence. A day-ahead warning lost to the calendar. So we shipped none of them, and built what the data supports." |
| 3:50–4:00 | Live URL on screen | "VayuSetu. Live, open source, built on Google Cloud." |

---

## Deck outline (11 slides)

1. **Title** — VayuSetu: why the air is bad, where it is worst, who should act.
2. **The problem** — a number and a colour; 30M people, ~40 official monitors; GRAP decisions taken on a city average.
3. **What officials actually need** — three questions after the number: why, where, who.
4. **Live product** — screenshot of the officials view on 12 Nov 01:30.
5. **Why** — attribution: upwind fire cone + boundary layer, r = +0.58 / −0.48 on 26 IST days; Gemini with code-checked citations.
6. **Where** — the Bahadurgarh event: 918 vs 207; robust z; 251 events across 48 localities.
7. **Who, and did they act** — alerts from observations, mock inbox, audit trail.
8. **Residents** — ten languages, speech, photo triage that cannot set a value.
9. **We tested our own ideas** — the falsification table (five "No", one "Yes"). The proof of rigour, not an apology.
10. **Deployable and scalable** — one Cloud Run service, BigQuery per-tenant datasets, open schemas, `infra/deploy.sh`; what a new city needs.
11. **Limits and next** — hotspots only where monitors exist; forecast BLH and 3+ seasons needed for a warning; identity in front of alerts; Lucknow ingestion.
