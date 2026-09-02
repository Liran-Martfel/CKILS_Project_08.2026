# CKILS — Contextual Keyboard Input Locale Switcher

A Windows background tool that automatically switches your keyboard's typing language (Hebrew ⇄
English) based on which app or window has focus — so you stop manually pressing Alt+Shift and
stop typing gibberish into the wrong layout.

This is a hands-on learning project: a proof of concept being built from scratch in Python, one
weekly milestone at a time, as a way to learn both coding and how a real Windows system-level tool
comes together.

## The master goal

The rule-based version below is the learning foundation, not the finish line. This project is only
truly done once CKILS is **AI-driven**: recognizing the screen (image/vision) and how the user is
typing, and deciding the right language switch from that understanding directly — no per-app rule
map required at that point.

## How it works today

- Watches Windows focus changes (`SetWinEventHook` / `EVENT_SYSTEM_FOREGROUND`) to know the moment
  you switch apps or windows.
- Looks up the focused app against a small process → language rule table.
- Switches that window's keyboard layout automatically (`WM_INPUTLANGCHANGEREQUEST`).
- Respects a manual override instantly and invisibly: if you switch the language yourself, CKILS
  leaves that window alone — no timer, no button — and quietly resumes automatic control the
  moment you move to a different window.

## Project status

- **Week 1 — done.** Focus-change detection, resolving the focused window to its process.
- **Week 2 — done.** Rule-based auto-switching, the manual-override guard, and switch-latency
  measurement (well under 1ms per switch, charter target is under 150ms) — all verified working
  end to end.
- **Week 3 — done.** Title-based rules for multi-window apps (Tier 2), catching browser tab
  switches with no focus change at all (via `EVENT_OBJECT_NAMECHANGE`), and a real-app check —
  confirmed on Chrome, Edge, and Firefox (independent of browser engine).
- **Week 4 — done.** All five of the charter's test cases (TC-01–TC-05) pass. **SC-01 (environment
  coverage) passes at 7/10 (70%)** — Chrome, Edge, Firefox, Word, Windows Terminal, Google
  Docs/Gmail, and Teams all confirmed working; Calculator and Windows Settings are confirmed
  *incompatible* (both wrapped by `ApplicationFrameHost.exe` — an architectural limit, not a CKILS
  bug), and Notepad remains quirky. SC-04, SC-06, and **SC-09 (8-hour stability)** all pass — the
  process survived an extended real run with zero crashes. SC-08 is correctly scoped out. Two real
  findings surfaced from actually living with it: local-app/terminal workflows expose a real limit
  of pure rule-based switching (a lived case *for* the master goal), and switch reliability
  degrades over very long continuous uptime, though a fresh restart fully restores it. **Decision,
  applying the charter's own framework: Go with Conditions** — window/app-level switching is the
  proven foundation; those two findings plus Tier 3 itself are the conditions carried into
  Weeks 5-6.
- **Week 5 — wired in, real-world testing next.** The master goal above, built end to end: **5.1**
  (UI Automation pinpoints the exact focused control) confirmed working. **5.2** (OCR reads the
  text inside that control) — real finding: Windows' own built-in OCR has no Hebrew support at
  all, on any machine (confirmed via `Get-WindowsCapability`), so this runs on **Tesseract**
  instead (free, open-source, Apache 2.0), reading English and Hebrew in one call, confirmed
  working on real captures of both. **5.3** — a real labeled dataset (228 rows) built from the
  user's own OCR captures plus a smaller supplemental batch, balanced ~50/50 Hebrew/English.
  **5.4** — a classifier trained from scratch (TF-IDF character n-grams + logistic regression,
  100% held-out accuracy, correct and appropriately-calibrated on genuinely novel test cases
  including out-of-vocabulary words and out-of-scope scripts). **5.5** — wired directly into
  `rule_engine.py`: the model now refines the rule table's answer, and can make a decision even
  for apps with **no rule configured at all** (a capability improvement over the original design).
  Verified to compile; not yet run live against real usage — that's the next step, along with
  measuring whether it adds noticeable latency (a real risk flagged during wiring: this now runs on
  every browser-tab title-change event, not just full focus changes).

**Overall progress, honestly:** against the original charter (the rule-based POC, Weeks 1-4),
this is roughly **90%** done — 7 of 8 Must criteria confirmed passing, with only the 8-hour
stability run left. Against the project's actual **master goal** (AI-driven, no rule table at
all), it's closer to **65-70%** — the full AI decision pipeline is built and wired into the live
switching path; what's left is real-world testing (accuracy in daily use, and specifically
latency against the charter's 150ms target for this new path).

## Repo layout

- `ckils/week1/`, `ckils/week2/`, … — the actual working code, one file per lesson.
- `Welcome_page_explaining.md` — the full project explainer: problem, hypothesis, architecture,
  scope, success criteria.
- `PROJECT_JOURNEY.md` — a running log of the project from kickoff to completion.
- `POC - Proof Of Concept - theory.docx` — the original project charter/spec.

## Build & run

Requirements: Windows 10/11, Python 3.10+, with `pywin32` and `psutil` installed
(`pip install pywin32 psutil`) inside a virtual environment.

To try the current rule-based auto-switcher, edit the `RULES` dictionary near the top of
`ckils/week2/rule_engine.py` to match two apps you actually have open, then run:

```
python ckils/week2/rule_engine.py
```

and Alt-Tab between them.

## Learning platform

A companion lesson-by-lesson guide (built alongside this code) walks through every concept used
here, from "hello Win32" through the override guard:
https://claude.ai/code/artifact/f6d5d3c8-41c7-467e-b4d6-16313baaa78c
