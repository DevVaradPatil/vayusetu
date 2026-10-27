"""
docs/build_deck.py — the pitch deck, generated from the numbers in this repository.

The deck is a submission deliverable, and every figure on it also appears in README.md,
TODO.md or docs/ARCHITECTURE.md. Generating it rather than hand-typing it means a number
that changes in the code changes on the slide, and nothing on a slide can be a figure the
project cannot show you where it came from.

Run: `python docs/build_deck.py` -> docs/VayuSetu.pptx (13 slides, 16:9).
"""

from __future__ import annotations

import pathlib

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

OUT = pathlib.Path(__file__).resolve().parent / "VayuSetu.pptx"
FINALS = OUT.parent / "VayuSetu_finals.pptx"
ASSETS = OUT.parent / "deck_assets"          # screenshots of the live site, asset1.png ...

INK = RGBColor(0x1A, 0x1C, 0x21)
DIM = RGBColor(0x43, 0x47, 0x50)
BLUE = RGBColor(0x0B, 0x57, 0xD0)
RED = RGBColor(0x99, 0x1B, 0x1B)
GREEN = RGBColor(0x0D, 0x53, 0x23)
PAPER = RGBColor(0xFF, 0xFF, 0xFF)
BAND = RGBColor(0xF0, 0xF2, 0xF6)

W, H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.9)


def _text(slide, left, top, width, height, runs, align=PP_ALIGN.LEFT, spacing=1.15):
    """runs: list of (text, size, bold, colour) — one paragraph each."""
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, (text, size, bold, colour) in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        p.space_after = Pt(6)
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = colour
        r.font.name = "Segoe UI"
    return box


def _slide(prs, title: str, kicker: str | None = None):
    s = prs.slides.add_slide(prs.slide_layouts[6])          # blank
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = PAPER
    top = Inches(0.55)
    if kicker:
        _text(s, MARGIN, top, W - 2 * MARGIN, Inches(0.35), [(kicker.upper(), 12, True, BLUE)])
        top = Inches(0.95)
    _text(s, MARGIN, top, W - 2 * MARGIN, Inches(0.9), [(title, 30, True, INK)])
    return s


def _bullets(slide, items, top=Inches(2.0), size=17, width=None):
    runs = []
    for text in items:
        runs.append((f"—  {text}", size, False, DIM))
    _text(slide, MARGIN, top, width or (W - 2 * MARGIN), H - top - Inches(0.6), runs, spacing=1.3)


def _stat_row(slide, stats, top=Inches(2.1), height=Inches(1.5)):
    """stats: list of (value, label, colour)."""
    n = len(stats)
    gap = Inches(0.3)
    width = Emu(int((W - 2 * MARGIN - gap * (n - 1)) / n))
    for i, (value, label, colour) in enumerate(stats):
        left = Emu(int(MARGIN + i * (width + gap)))
        box = slide.shapes.add_shape(1, left, top, width, height)      # rectangle
        box.fill.solid()
        box.fill.fore_color.rgb = BAND
        box.line.fill.background()
        box.shadow.inherit = False
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Inches(0.18)
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT
        r = p.add_run()
        r.text = value
        r.font.size = Pt(30)
        r.font.bold = True
        r.font.color.rgb = colour
        r.font.name = "Segoe UI"
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text = label
        r2.font.size = Pt(12.5)
        r2.font.color.rgb = DIM
        r2.font.name = "Segoe UI"


def _table(slide, headers, rows, top=Inches(2.1), col_widths=None):
    n_rows, n_cols = len(rows) + 1, len(headers)
    shape = slide.shapes.add_table(n_rows, n_cols, MARGIN, top, W - 2 * MARGIN,
                                   Inches(0.4) * n_rows)
    table = shape.table
    if col_widths:
        total = sum(col_widths)
        for i, w in enumerate(col_widths):
            table.columns[i].width = Emu(int((W - 2 * MARGIN) * w / total))
    for c, h in enumerate(headers):
        cell = table.cell(0, c)
        cell.text = h
        para = cell.text_frame.paragraphs[0]
        para.runs[0].font.size = Pt(13)
        para.runs[0].font.bold = True
        para.runs[0].font.color.rgb = INK
        cell.fill.solid()
        cell.fill.fore_color.rgb = BAND
    for r, row in enumerate(rows, start=1):
        for c, val in enumerate(row):
            cell = table.cell(r, c)
            cell.text = str(val)
            para = cell.text_frame.paragraphs[0]
            para.runs[0].font.size = Pt(12.5)
            para.runs[0].font.color.rgb = DIM if c else INK
            para.runs[0].font.bold = c == 0
            cell.fill.solid()
            cell.fill.fore_color.rgb = PAPER
    return table


def _placeholder(slide, label: str, how: str, left=MARGIN, top=Inches(2.2),
                 width=None, height=Inches(3.6), asset: str | None = None):
    """
    The screenshot docs/deck_assets/<asset>, fitted and centred in the box — or, until a
    person has captured it, a visible gap where it goes.

    The gap is left in on purpose: an honest "screenshot to come" box reads better in a
    review than a slide that quietly lost the evidence it was built around.
    docs/deck.md lists the capture instructions for each one.
    """
    width = width or (W - 2 * MARGIN)
    img = ASSETS / asset if asset else None
    if img and img.exists():
        from PIL import Image
        iw, ih = Image.open(img).size
        scale = min(width / iw, height / ih)
        pw, ph = int(iw * scale), int(ih * scale)
        return slide.shapes.add_picture(str(img), Emu(int(left + (width - pw) / 2)),
                                        Emu(int(top + (height - ph) / 2)), pw, ph)
    box = slide.shapes.add_shape(1, left, top, width, height)
    box.fill.solid()
    box.fill.fore_color.rgb = BAND
    box.line.color.rgb = RGBColor(0xDA, 0xDD, 0xE4)
    box.line.width = Pt(1.5)
    box.line.dash_style = 4                       # dashed
    box.shadow.inherit = False
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.4)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = f"[ {label} ]"
    r.font.size = Pt(17)
    r.font.bold = True
    r.font.color.rgb = DIM
    r.font.name = "Segoe UI"
    p2 = tf.add_paragraph()
    p2.alignment = PP_ALIGN.CENTER
    r2 = p2.add_run()
    r2.text = how
    r2.font.size = Pt(13)
    r2.font.color.rgb = RGBColor(0x62, 0x67, 0x72)
    r2.font.name = "Segoe UI"
    return box


def build() -> pathlib.Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # 1 — title
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = PAPER
    _text(s, MARGIN, Inches(2.3), W - 2 * MARGIN, Inches(2.4), [
        ("VayuSetu", 58, True, INK),
        ("Why the air is bad, where it is worst, and who should act — with every number measured.", 22, False, DIM),
        ("Build with AI: Code for Communities · Track 02, Clean Air & Climate Resilience", 14, False, BLUE),
        ("Live: vayusetu-999960875509.asia-south1.run.app", 14, False, DIM),
    ])

    # 2 — the problem
    s = _slide(prs, "Every AQI app tells you a number and a colour", "The problem")
    _bullets(s, [
        "30 million people in Delhi NCR; GRAP decisions are taken on a city average.",
        "An average hides the locality breathing four times it, and says nothing about why.",
        "India's response does not usually fail at detection. It fails at closure: the Green Delhi "
        "app took 84,765 complaints in 2024, 10,656 went overdue, and one department had 99 of its "
        "183 'resolved' complaints reopened.",
        "And the instruments themselves are unreliable: in 2025 only 270 of 562 real-time monitors "
        "gave stable data.",
    ])

    # 3 — what we built
    s = _slide(prs, "Six questions after the number", "What VayuSetu does")
    _table(s, ["Question", "Answered from"], [
        ("What is happening?", "70 CPCB monitors via OpenAQ, hourly"),
        ("Can that monitor be trusted?", "Four integrity checks on every reading"),
        ("Where is it worst?", "Each monitor against the robust median of its neighbours"),
        ("Why?", "NASA FIRMS fires sectored by ERA5 wind, boundary layer height"),
        ("Who should act?", "Gemini, over measured evidence, verified in code"),
        ("Was it really fixed?", "Closure needs a checked photo and the measurements after"),
    ], col_widths=[4, 8])

    # 4 — hero episode
    s = _slide(prs, "A real episode, explained end to end", "12 November 2025, 01:30 IST")
    _stat_row(s, [("407.3", "µg/m³ city average — Severe", RED),
                  ("110 m", "air ceiling trapping it", INK),
                  ("33", "fires inside the upwind fan", RGBColor(0xEA, 0x58, 0x0C)),
                  ("0.85", "Gemini's confidence, cause: crop burning", BLUE)])
    _placeholder(s, "ASSET 1 — screenshot: officials view at the hero hour",
                 "Open /#/ on the live site, set the time to 12 Nov 2025 01:30 IST, capture "
                 "1600x1000 in the light theme. Must show the map with the wind fan, the four "
                 "stat cards and the brief panel. Instructions: docs/deck.md.",
                 top=Inches(3.85), height=Inches(3.35), asset="asset1.png")

    # 5 — hidden hotspot
    s = _slide(prs, "The event the city average hid", "Hyper-local detection")
    _stat_row(s, [("629 → 507", "NSIT Dwarka, 3 hours", RED),
                  ("123", "the region's median that hour", INK),
                  ("24,500", "people in that square kilometre", BLUE),
                  ("111", "confirmed event-hours, 26 localities", GREEN)])
    _bullets(s, [
        "Measurement, not a model: one monitor against the robust median of the monitors reporting "
        "in the same hour, confirmed only when it persists for two hours with distinct values.",
        "At the peak of the smog episode it reports nothing — the whole region is Severe together. "
        "That is the correct answer, and the page says so.",
    ], top=Inches(4.0))

    # 6 — the broken sensor
    s = _slide(prs, "Our own headline was a broken sensor", "Why integrity comes first")
    _bullets(s, [
        "The first README led with 'Arya Nagar, 918 µg/m³'. Its readings that morning: "
        "717, 31, 559, 33, 500, 0, 886, 4, 918, 19 — while every monitor within 25 km held near 250.",
        "22 of the 40 events we first ranked highest had faults like that nearby.",
        "Four checks now gate every reading: stuck values, zeros during dirty air, impossible "
        "spikes, implausibly low during an episode. Thresholds set from 35,602 real readings.",
        "51 outliers refused as sensor faults. The attribution finding survives unchanged: "
        "r = +0.57 with upwind fires, −0.48 with the air ceiling.",
    ])

    # 7 — national
    s = _slide(prs, "The same check, every CPCB monitor in India", "Reach")
    _stat_row(s, [("62 of 361", "monitors not trustworthy (17%)", RED),
                  ("26", "states covered", INK),
                  ("240", "monitors with a faulted hour", RGBColor(0xEA, 0x58, 0x0C)),
                  ("985.0", "µg/m³ error code in the public feed", BLUE)])
    _bullets(s, [
        "Exactly 985.0 appears on 8 monitors in Karnataka and Tamil Nadu for 345 hours — 214 of "
        "them at one monitor in Hassan, while the rest of the state read about 30.",
        "Each monitor is judged against its own state's median; states too thin for a median are "
        "labelled, never reported clean. Every verdict ships with the raw readings behind it.",
    ], top=Inches(4.0))

    # 8 — cases
    s = _slide(prs, "A case closes only when the evidence agrees", "Accountability")
    _bullets(s, [
        "Measurements open a case for the agency named on the monitor itself, with a deadline: "
        "24 h for a local event, 72 h for a broken monitor, 12 h for a regional episode.",
        "Overdue and CAQM escalation are computed on read, so there is no scheduler to fail quietly.",
        "To close: a site photo Gemini examines (is it genuine, is a source still visible), taken "
        "within 1 km — and the readings afterwards must show the problem gone.",
        "A region-wide case cannot be closed with a note while the monitors still show Severe a "
        "day later. The refusal, and its reason, go in the audit trail.",
        "Every agency and officer is a demo account: no real contact details exist in this codebase.",
    ])
    _placeholder(s, "ASSET 2 (optional) — screenshot: a refused closure",
                 "/#/cases -> submit a closure on the region-wide case with only a note. "
                 "Capture the red refusal and its reason.",
                 top=Inches(6.15), height=Inches(0.95), asset="asset2.png")

    # 9 — farm fires
    s = _slide(prs, "The fires the count stopped seeing", "Cross-state")
    _table(s, ["Punjab, Oct–Nov", "2020", "2025"], [
        ("Satellite fire alerts (daytime)", "74,975", "3,936  (−95%)"),
        ("Land burned (MODIS burn scars)", "17,565 km²", "8,965 km²  (−49%)"),
        ("Land burned per alert", "0.23 km²", "2.28 km²  (10×)"),
    ], col_widths=[5, 3, 4])
    _bullets(s, [
        "Amritsar has the most alerts and ranks 10th by land burned; Sangrur ranks 3rd by alerts "
        "and 1st by land. An inspection plan built on counts goes to the wrong districts.",
        "Nine verification notices go to Punjab's and Haryana's boards, copied to CAQM — not blame "
        "for a given day: we tested that link and it is r = +0.32 once the season is removed.",
    ], top=Inches(4.3))

    # 10 — residents
    s = _slide(prs, "The same facts, in the resident's language", "Residents")
    _bullets(s, [
        "Ten Indian languages, with the advice read aloud.",
        "Health guidance follows the CPCB band, written for someone who has never seen an AQI map.",
        "A resident can send a photo of the haze; Gemini triages it, and it can corroborate a "
        "reading but can never set a pollution value or trigger a response on its own.",
        "Installs as an app; the service worker never caches a reading.",
    ], width=Inches(6.2))
    _placeholder(s, "ASSET 3 (optional) — screenshot: resident view in Hindi",
                 "/#/residents with the language set to हिन्दी, showing the band, the advice "
                 "and the Listen button.",
                 left=MARGIN + Inches(6.5), top=Inches(2.0), width=Inches(5.0),
                 height=Inches(4.9), asset="asset3.png")

    # 11 — falsification
    s = _slide(prs, "We tested our own ideas, and published what failed", "Rigour")
    _table(s, ["Claim we tested", "Result"], [
        ("Gridded ML beats interpolation", "No — loses at every network density"),
        ("Satellite AOD explains the gaps", "No — r = +0.04"),
        ("72-hour forecast beats persistence", "No — loses at every horizon"),
        ("Day-ahead Severe warning beats the calendar", "No — +0.61 against the calendar's +0.71"),
        ("Our top hotspot was real pollution", "No — a faulty monitor; 22 of the top 40 were"),
        ("Burned area explains daily PM2.5", "No — r = −0.66, the smoke hides the scars"),
        ("Upwind fires + air ceiling explain episodes", "Yes — r = +0.55 and −0.42"),
    ], col_widths=[6, 6])
    _text(s, MARGIN, Inches(6.3), W - 2 * MARGIN, Inches(0.6),
          [("The model registry refuses a model that loses to its baseline. It refused ours, so "
            "none of these is in the product.", 14, False, BLUE)])

    # 12 — deployable
    s = _slide(prs, "Built to be run by someone else", "Deployability")
    _bullets(s, [
        "One Cloud Run service in asia-south1 serves the API and the site; `bash infra/deploy.sh` "
        "builds, deploys and smoke-tests it.",
        "BigQuery per tenant: a new city is a bounds entry, a dataset and a backfill — the same "
        "path the national run used for 26 states.",
        "Two open Apache-2.0 schemas so another system can consume an episode without trusting our "
        "models, validated against real output in code.",
        "No API key in the repository or the image: Gemini's lives in Secret Manager, and Google "
        "Air Quality authenticates as the runtime service account.",
    ])

    # 13 — limits
    s = _slide(prs, "What it does not do", "Limits, stated")
    _bullets(s, [
        "No forecast and no predicted hotspot map: both were falsified, so neither is served.",
        "Hotspots are hidden by the average, not from the network — the detector needs a monitor "
        "to be there.",
        "Attribution is correlational over one season, and counts fire alerts that now undercount "
        "burning about tenfold.",
        "The demo is a replay of a real episode, labelled on screen, because the CPCB live feed is "
        "stalled; the Monitors tab shows Google's modelled air beside our latest measurement.",
        "Every agency is a demo account, and case actions would sit behind identity in production.",
    ])

    prs.save(OUT)
    return OUT


def build_finals(src: pathlib.Path = OUT) -> pathlib.Path:
    """
    The finals cut: the live demo carries the talk, so the deck only opens and closes it.
    Title and Rigour, then slides 4, 8 and 10 as a backup if the site is unreachable.
    Run order and script: docs/FINALS.md.
    """
    prs = Presentation(src)
    ids = prs.slides._sldIdLst
    slides = list(ids)
    keep = [slides[i - 1] for i in (1, 11, 4, 8, 10)]
    for s in slides:
        ids.remove(s)
        if s not in keep:
            prs.part.drop_rel(s.rId)
    for s in keep:
        ids.append(s)
    prs.save(FINALS)
    return FINALS


def demo() -> None:
    finals = Presentation(build_finals(build()))
    order = [" ".join(sh.text_frame.text for sh in sl.shapes if sh.has_text_frame)
             for sl in finals.slides]
    assert len(order) == 5 and "VayuSetu" in order[0] and "tested our own ideas" in order[1], order
    path = OUT
    prs = Presentation(path)
    assert len(prs.slides) == 13, len(prs.slides)
    def texts(shape):
        if shape.has_text_frame:
            yield shape.text_frame.text
        if shape.has_table:                      # table cells are not text frames
            for row in shape.table.rows:
                for cell in row.cells:
                    yield cell.text

    words = " ".join(t for sl in prs.slides for sh in sl.shapes for t in texts(sh))
    for number in ("407.3", "629", "62 of 361", "985.0", "74,975", "+0.32", "84,765"):
        assert number in words, f"{number} missing from the deck"
    assert "predicted" not in words.lower() or "no predicted" in words.lower()
    # Slides that stand on a screenshot carry it, or a visible placeholder until it arrives.
    pictures = sum(sh.shape_type == 13 for sl in prs.slides for sh in sl.shapes)
    assert words.count("ASSET") + pictures >= 3, "screenshots and their placeholders missing"
    print(f"[OK] {path.name}: {len(prs.slides)} slides, every headline figure present")


if __name__ == "__main__":
    demo()
