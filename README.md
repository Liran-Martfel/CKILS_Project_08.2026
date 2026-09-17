# CKILS — Contextual Keyboard Input Locale Switcher

A Windows background tool that automatically switches your keyboard's typing language (Hebrew ⇄
English) based on what you're actually looking at and typing — so you stop manually pressing
Alt+Shift, and stop typing whole sentences into the wrong layout before noticing.

This is a hands-on learning project: a proof of concept built from scratch in Python, one weekly
milestone at a time, as a way to learn both coding and how a real Windows system-level tool comes
together in practice — bugs, packaging, and all.

## The problem

If you type in more than one language, you know the drill: you switch to a different app, forget
your keyboard is still set to the other language, and type a full sentence of gibberish before
noticing. Then you delete it, switch layouts by hand, and retype. It happens constantly — in
chats, documents, search bars, calendars — and it adds up to real lost time and real mistakes.

## The master goal

The rule-based layers below are the learning foundation, not the finish line. This project is
only truly done once CKILS is **AI-driven**: reading the screen and deciding the right language
from that understanding directly, with no hand-written per-app rule table required at all.

## How it works

CKILS layers three decision tiers, from simplest to most advanced, each one only stepping in
where the one before it isn't enough:

1. **Fast path — learned defaults.** An instant first guess for a window, built entirely from
   CKILS's own past confident decisions (per app, and per exact app+title) — never a hand-written
   rule. A key only gets *trusted* once it has enough history and that history actually agrees
   with itself (≥3 samples, ≥80% agreement) — a browser's whole-app guess or a chat app's one
   shared generic title naturally never earns trust, automatically, with no app named anywhere in
   the code.
2. **Content-aware correction (Tier 3).** Runs in the background after every switch: UI Automation
   locates the real focused control, reads its text (via accessible text where available, OCR via
   Tesseract otherwise), and a classifier trained from scratch on real usage decides the language
   — correcting the fast path's guess if it disagrees and is confident.
3. **Manual override, always respected.** If you switch the language yourself, CKILS leaves that
   window alone immediately — no timer, no button — and quietly resumes automatic control the
   moment you move to a different window. A manual override also teaches the trust system
   directly, the same way a confident automatic decision does.

Every real language change (automatic or manual) is written to a local decision log —
timestamped, with the exact text read, the reasoning, and a screenshot cropped to just the region
read — specifically so a wrong guess can be diagnosed from evidence instead of guesswork.

## Current status

The core switching pipeline (all three tiers) is built, wired end to end, and has been running
against real daily use. That real use has surfaced — and fixed — a steady stream of genuine bugs
in how various apps expose their on-screen content: Zoom's chat panel reading its own header (and,
more recently, its main call window landing on a toolbar button) instead of the conversation,
WhatsApp, Claude.ai, and YouTube's own UI chrome (placeholders, logos, taglines) being misread as
real typed content, Google Calendar's event tiles diluting a real Hebrew title with English
scaffolding text, and Google Docs periodically re-asserting a stale title-based guess over live
typing. Real usage data also shows the reliability trend directly: override rate — how often a
decision needed manual correction — dropped from 5.67% before the trust-history mechanism landed
to under 0.3% since. A real live run also surfaced a genuine performance bug: the background safety
poll was re-running full OCR on an already-settled window every ~1.5 seconds forever, burning
sustained CPU — fixed with per-window backoff once a read has repeated unchanged a few times in a
row (confirmed after the fact: sustained CPU dropped from ~9% to under 1%). A separate real bug
meant a manual language correction could be silently undone by the next background check unless you
forced a fresh focus event by alt-tabbing away and back — fixed by making the background poll detect
a manual override on its own, within one poll interval, no "ping-pong" required. That fix itself then
surfaced a same-day regression — a single mismatched keyboard reading (Windows hadn't yet applied
CKILS's own pending switch) was being trusted as proof of a manual override on the spot, silently
freezing correction — fixed by requiring the same mismatch twice, on two independent checks, before
it's trusted. The whole-window search added for Zoom also turned out to occasionally pick the entire
browser window itself (tab strip and bookmarks bar included) as "content" on other apps — confirmed
live with a purpose-built diagnostic tool — fixed by rejecting any candidate that spans essentially
the whole window, since real content is never that. Each fix is backed by a regression test built
from the real failure it addresses — 52 tests currently, covering every bug found so far
(`ckils/week2/test_regressions.py`).

**Known open limitations:**
- No proactive language guess yet for a brand-new page with zero learned history (e.g. the first
  visit to a new YouTube video) — the keyboard simply stays at its last physical state until Tier
  3 catches up from real content.
- Nothing in CKILS learns *where* to look on screen — only *what language things tend to be* once
  it's already looking in a good spot. Every "wrong element focused" fix (Zoom's header, Zoom's
  toolbar button, ...) has been a targeted, hand-diagnosed structural fix, not something that
  generalizes on its own to an app not yet encountered. A second, separate learning system for
  "which control reliably has real content" is a real idea for later, not yet designed.

The full, honest development history — every real bug found, how it was diagnosed, what was tried
and rejected, and why — lives in [`PROJECT_JOURNEY.md`](PROJECT_JOURNEY.md).

## The language model

The classifier is a small model trained from scratch (TF-IDF character n-grams + logistic
regression) on 228 real labeled examples captured from actual usage — not a public dataset, not
hand-written examples. It measures at **98% held-out accuracy**. The raw labeled dataset is kept
local-only (real captured text from real usage isn't something that belongs in a public repo);
the trained model file (`ckils/week2/language_model.joblib`) is what ships and is what CKILS
actually runs on.

## Repo layout

- `ckils/week1/`, `ckils/week2/` — the working code, one file per lesson; `rule_engine.py` is the
  live entry point, `decision_logger.py` the diagnostic log, `test_regressions.py` the test suite.
- [`PROJECT_JOURNEY.md`](PROJECT_JOURNEY.md) — the full development log: every real bug, fix, and
  design decision, in order, with reasoning.
- `POC - Proof Of Concept - theory.docx` — the original project charter/spec.

## Running it

Either way, one thing is required first on the machine that runs CKILS —
[Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki), a separate free program that
CKILS uses to read on-screen text. It's not bundled; install it once:

```
winget install --id UB-Mannheim.TesseractOCR -e
```

**Just want to run it? Download the exe — no Python required.**

**→ [Download CKILS.exe](https://github.com/Liran-Martfel/CKILS_Project_08.2026/releases/latest)**

A standalone build (via PyInstaller, with the trained model and OCR data bundled inside it) —
double-click it, no setup, no configuration. It decides from real on-screen content and learns
its own per-app defaults as it goes. It isn't checked into the repo itself (a built binary doesn't
belong in source control); the link above is a GitHub Release, built fresh from this same source.

**Want to read or change the code? Run the source directly.**
`rule_engine.py` is the actual source — the same code the exe is built from, just runnable
straight from Python for development:

Requirements: Windows 10/11, Python 3.10+, with the packages in `ckils/week2/` installed
(`pywin32`, `psutil`, `uiautomation`, `pytesseract`, `Pillow`, `scikit-learn`, `joblib`) inside a
virtual environment.

```
python ckils/week2/rule_engine.py
```

## Testing

```
python ckils/week2/test_regressions.py
```

One test class per real bug fixed, each one reproducing the exact failure that was found — not a
synthetic approximation of it.
