# Submission checklist

Walk this end to end before submitting. Every line is either a hard requirement from the hackathon rules or a way teams lose marks they had already earned.

## Required deliverables

- [ ] **Source code** — public GitHub repo, or access granted to judges. Verify in a logged-out browser.
- [ ] **Demo video** — 3–5 minutes, working end-to-end walkthrough. Not a slideshow.
- [ ] **Pitch deck** — 10–12 slides covering: problem, solution, AI approach, who it serves, why it is deployable, how it scales across India.
- [ ] **Brief description** — 2–3 lines.
- [ ] **Deployed link** — live and working. **Test it from outside our network, on mobile data, in an incognito window.**

## Mandatory build requirements

- [ ] Functioning end-to-end flow for the track's core use case
- [ ] **Google AI doing meaningful work**, not bolted on — Gemini vision, Gemini reasoning, Vertex AI serving, Earth Engine
- [ ] Real or realistic data — ours is real throughout
- [ ] Built for India, designed to scale across states — the tenant architecture plus the Lucknow transfer
- [ ] Multilingual or voice support — 10 languages plus TTS

## Deployed link — the one most likely to be broken

- [ ] Loads in under 5 seconds cold
- [ ] `min-instances=1` set on both Cloud Run services for demo week
- [ ] Works in Chrome, Safari, and on a real Android phone
- [ ] Citizen PWA camera flow works on an actual phone, on mobile data
- [ ] No console errors on load
- [ ] Maps key referrer restriction includes the deployed origin
- [ ] Anonymous auth works — a judge must not hit a signup wall
- [ ] Demo data is present and current; `verify_data.py --strict` passes on both tenants

## Honesty audit — do this deliberately

Read `AGENTS.md` §4 R7, then check every claim in the video, deck, README and UI copy:

- [ ] No claim of **federated learning**. It is federated model *sharing*
- [ ] No claim of **back-trajectory modelling**. It is a wind-sector cone
- [ ] No claim of **real-time satellite**. Gridded product is daily, forecast is hourly
- [ ] No claim of **exactly 1 km**. The grid is 0.01°, approximately 1 km
- [ ] Every metric comes from a LOSO run, not in-sample, not from memory
- [ ] Baselines shown alongside every model metric
- [ ] Replay is **verbally disclosed** in the video
- [ ] Nothing shown in the video is a hardcoded fixture pretending to be a live path
- [ ] The transfer demo shows the honest accuracy drop

If a claim cannot be supported, cut it. Do not soften it.

## Safety and privacy

- [ ] **No real official's email, phone, or webhook anywhere** — code, tests, fixtures, demo data, deck. Mock accounts only
- [ ] No API key, service-account JSON, or credential committed. Check the full history, not just HEAD
- [ ] Citizen photos: EXIF stripped except timestamp and GPS
- [ ] Seed photos are ones the team took. No scraped images of identifiable people
- [ ] Rate limiting active on the public upload endpoint before it is publicly linked
- [ ] `.env` gitignored; `.env.example` committed with dummy values

## Scoring artifacts that are easy to forget

- [ ] `docs/DEPLOYMENT.md` complete, with a **real** monthly cost estimate — 20% of the score is deployability
- [ ] `spec/` schemas published, versioned, Apache-2.0, documented for outside adopters
- [ ] `README.md` has an honest limitations section
- [ ] `LICENSE` present (Apache-2.0)
- [ ] Repo has no dead scaffolding or commented-out blocks — judges do open the code

## Video quality

- [ ] 3–5 minutes. Under 3 looks thin, over 5 may not be watched to the end
- [ ] Audio is clear and consistent
- [ ] Map is legible at 720p after compression — check an actual compressed export
- [ ] The residual layer moment is unmistakable — the one beat a judge should remember
- [ ] Backtest chart is on screen with the real MAE spoken aloud
- [ ] Ends with the honesty beat: what is real, what is replayed, what is roadmap

## Deck

- [ ] Slide 5 (AI approach) is the strongest slide — it is 25% of the score
- [ ] Slide 6 (proof) has real numbers with baselines
- [ ] Slide 11 (limitations) is present and specific
- [ ] Every number traceable to a run, not a guess

## Final

- [ ] Code frozen 48 hours before deadline
- [ ] Someone outside the team followed `README.md` setup successfully
- [ ] All links in the submission form tested in an incognito window
- [ ] Submitted with time to spare, not in the final hour
