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
- **Week 4 — nearly done.** All five of the charter's test cases (TC-01–TC-05) pass. Of the
  remaining success criteria: **SC-01 (environment coverage) passes at 7/10 (70%)** — Chrome, Edge,
  Firefox, Word, Windows Terminal, Google Docs/Gmail, and Teams all confirmed working; Calculator
  and Windows Settings are confirmed *incompatible* (both wrapped by `ApplicationFrameHost.exe` —
  an architectural limit, not a CKILS bug), and Notepad remains quirky. SC-04 (first-character
  accuracy) and SC-06 (password-field protection) both pass. SC-08 is correctly scoped out
  (Nice-to-have, needs a 5-user study). Only **SC-09 (8-hour stability)** and the final
  Go/No-Go write-up (4.3) are still open.
- **Week 5+ — ahead.** The master goal above: replacing the rule table with real AI-driven
  understanding.

**Overall progress, honestly:** against the original charter (the rule-based POC, Weeks 1-4),
this is roughly **90%** done — 7 of 8 Must criteria confirmed passing, with only the 8-hour
stability run left. Against the project's actual **master goal** (AI-driven, no rule table at
all), it's closer to **40-45%** — Weeks 1-4 are the solid foundation, but Weeks 5-6 (the mandatory
AI phase) haven't started, and that's the hardest, least-proven part of the whole project.

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
