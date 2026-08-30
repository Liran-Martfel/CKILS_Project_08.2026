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
- **Week 2 — nearly done.** Rule-based auto-switching plus the manual-override guard, both
  verified working end to end.
- **Weeks 3+ — ahead.** Broader app/browser-tab compatibility, then the master goal above:
  replacing the rule table with real AI-driven understanding.

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
