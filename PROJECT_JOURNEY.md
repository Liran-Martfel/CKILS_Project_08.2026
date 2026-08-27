# CKILS Project Journey

A running log of this project, from the first ask to the day it's declared done. Updated as
milestones happen — new entries get appended at the bottom, oldest first.

**Note on how progress is tracked:** the training platform's "mark reviewed & merged" checkboxes
are saved locally in your browser only — Claude cannot see them remotely. Instead, this log gets a
timestamped entry each time finished lesson code comes back to a Claude Code chat for review,
which is the natural checkpoint in the workflow anyway.

---

## 2026-08-26 — Kickoff & planning

**21:03** — Project started. Asked for a plan to execute the POC described in
`POC - Proof Of Concept - theory.docx`, using an (at the time empty) `Welcome_page_explaining`
file to explain the project. Read the full theory doc: it specifies **CKILS** (Contextual Keyboard
Input Locale Switcher) — a Windows background service that auto-switches keyboard input language
(Hebrew/English) based on which app/window has focus, with a 3-tier detection architecture, 9
measurable success criteria, a 5-case test matrix, and a 6-week roadmap.

Mid-planning, a separately pasted draft plan turned out to describe a *different* project (a
UI-language/translation website) based on a mismatched guess rather than the actual theory doc.
Confirmed with you that the real docx content — CKILS — is the target; the pasted draft was set
aside.

Clarified through discussion:
- Initial tech-stack pick was Rust (`windows-rs`) for direct Win32 access.
- Revealed this is a **course project for learning to code and build AI**, not a delivery task —
  reframed everything around learning, not just output.
- Switched the stack decision to **Python** (`pywin32`), since it reaches the same Win32 APIs with
  far less ceremony than Rust, fitting a first coding project.
- A "website" idea was clarified to mean a **learning-guide site**, not the POC itself (a browser
  can't control other native apps' keyboard state, so it can't be the actual product).
- Timeline: up to 4 weeks, less if possible. Scope: "do as much as we can," prioritized so a
  partial build still yields a valid answer per the charter's own Go/Go-with-Conditions/No-Go
  framework.
- Landed on a two-track plan: **Track A** — a learning-guide site, built entirely by Claude — and
  **Track B** — the actual CKILS Python code, written by you, reviewed and merged in by Claude
  after each lesson.

Plan approved. Saved at `C:\Users\liran\.claude\plans\hi-i-want-to-scalable-book.md`.

**21:05–21:10** — Execution began:
- Initialized a git repository in the project folder.
- Wrote `Welcome_page_explaining.md` (replacing the empty placeholder) — the project's plain-language
  explainer: the problem, the core hypothesis, the 3-tier architecture, scope, success criteria,
  and current status.
- Created the `ckils-poc/` folder for Track B's code, plus a `.gitignore` for the Python venv.

**21:15** — Built and published the Track A learning-guide site as a Claude Artifact — you named it
**the training platform**. Live at:
`https://claude.ai/code/artifact/f6d5d3c8-41c7-467e-b4d6-16313baaa78c`

First version shipped Week 1's three lessons (environment setup, focus-change detection, process
identification) plus an outline preview of Weeks 2–4.

**21:35** — Feedback: the first version of the lessons used fill-in-the-blank code stubs with
hints, assuming knowledge you don't have yet ("most of the thing i dont know"). Clarified your
baseline: comfortable with Python up through concepts like PCA (i.e. general Python fluency from a
data-science-flavored course), but new to OS-level/Win32 programming specifically.

Rewrote all three Week 1 lessons: full working code shown upfront (no blanks), a "new words"
glossary per lesson for jargon (library, handle, callback, hook, process, PID, etc.), and a
line-by-line walkthrough of what each piece of code does and why, before asking you to type and run
it. Republished to the same link.

**21:43** — Requested this journal, to document the project from here through to completion.

---

## 2026-08-27 — Lesson 1.1 complete

**09:18** — Brought back working code for Lesson 1.1 (say hello to Win32): correctly used
`win32gui.GetForegroundWindow()` to get the focused window's handle and `win32gui.GetWindowText()`
to read its title, with accurate comments showing real understanding of what each call does.
Asked a sharp clarifying question — correctly noticed that neither `GetWindowText` nor the
suggested `GetClassName` stretch can identify *language*, only *which window/app is focused*.
Confirmed: window identity is just the lookup key for a language-rule table that gets built in
Week 2 — it was never meant to reveal language itself. Reviewed, correct, merged into
`ckils-poc/week1/hello_win32.py`.

---

## 2026-08-27 — First real bug: `SetWinEventHook` isn't in pywin32

**09:36** — Lesson 1.2 hit `AttributeError: module 'win32api' has no attribute 'SetWinEventHook'`.
Verified against pywin32's actual C source (`win32apimodule.cpp`) — confirmed `SetWinEventHook` is
genuinely not wrapped by pywin32 at all; it's one of the Win32 API's gaps in that library. The fix,
confirmed against a working real-world example, is calling it via `ctypes.windll.user32` directly
instead, with the callback explicitly typed via `ctypes.WINFUNCTYPE` and kept alive in a variable
(a Python-garbage-collection pitfall specific to handing callbacks to raw C functions). A second,
unrelated bug was also caught in the same code: `win32gui.pumpMessages()` needed a capital P
(`PumpMessages`) — Python is case-sensitive.

This was a mistake in the lesson content itself (an unverified assumption baked into the original
Week 1 teaching material), not a learner error. Corrected `ckils-poc/week1/focus_watcher.py`, and
updated both Lesson 1.2 and 1.3 on the training platform to the verified `ctypes`-based approach so
the same wall isn't hit twice.

---

## 2026-08-27 — Consolidated onto the real project folder

**09:49** — Discovered a folder mismatch: all setup so far (git repo, docs, Week 1 code) had been
built in `Language Change Project`, a folder with no GitHub connection — while the user was
actually coding in PyCharm inside `C:\Users\liran\Personal_Project`, which turned out to already be
a real, working project: its own venv, a git repo, and a remote already pointed at
**github.com/Liran-Martfel/CKILS_Project_08.2026**, with one commit ("version 1.0") already pushed.
The user had also already applied the `ctypes` fix from the previous entry directly into
`Personal_Project/ckils-poc.py` independently.

Consolidated everything onto `Personal_Project` as the single real project home: copied the theory
doc, `Welcome_page_explaining.md`, and this journal over; restructured code under `week1/`
(`hello_win32.py` for lesson 1.1, `focus_watcher.py` for lesson 1.2 — moved from the root-level
`ckils-poc.py`); added a `.gitignore` (none existed yet, and `.venv` wasn't being tracked but also
wasn't formally excluded). The `Language Change Project` folder is retired — no further work will
happen there. Nothing has been pushed to GitHub as part of this cleanup; the user is handling
commits/pushes themselves going forward.

---

## 2026-08-27 — Finding: Alt-Tab fires multiple foreground events

**09:55** — Running `focus_watcher.py`, noticed `Focus changed!` prints multiple times per single
Alt-Tab switch. Confirmed this is real Windows behavior, not a bug: Alt-Tab shows a temporary
switcher overlay before landing on the target window, and that overlay itself briefly takes
foreground, firing its own `EVENT_SYSTEM_FOREGROUND` — so one Alt-Tab can fire 2-3 events.

Noted as a real design constraint for Week 2's rule engine: it can't react blindly to every event
fired and will need to check whether the window/process actually changed from the last one it
acted on before applying a language switch, to avoid redundant/flickery switching from event
bursts like this.

---

## 2026-08-27 — Week 1 complete; Week 2 lessons built

**10:23** — Week 1 finished: `hello_win32.py` (1.1), `focus_watcher.py` (1.2, fixed and confirmed
working), and lesson 1.3 (process identification, fixed a tuple-unpacking bug independently along
the way) all working. Along the way, confirmed a real OS finding: Alt-Tab fires multiple
`EVENT_SYSTEM_FOREGROUND` events per switch (its overlay briefly takes foreground itself) — noted
as a constraint for Week 2's rule engine. Also clarified that tab-level detection (switching Gmail
↔ Google Search in one browser window) is out of scope for Week 1 by design — no focus event fires
for tab switches at all, since the window itself never loses focus; that's Week 3 territory
(matches the charter's own TC-02 test case).

User asked whether leaving Week 2 as an outline meant self-directed research was expected — clarified
that was never the intent; per the plan, later weeks were deliberately left light only until Week 1
was actually finished. Verified the Week 2 Win32 mechanics properly this time before writing
anything (learned from the Week 1 `SetWinEventHook` mistake): confirmed `win32api.GetKeyboardLayoutList()`,
`win32api.GetKeyboardLayout(thread_id)`, and `win32con.WM_INPUTLANGCHANGEREQUEST` are all real,
pywin32-wrapped functions. Built and published all four Week 2 lessons in full teaching style
(2.1 force-switch by hand, 2.2 rule engine, 2.3 override guard, 2.4 latency measurement).

---

## Reference

- **Project home:** `C:\Users\liran\Personal_Project` (GitHub: `Liran-Martfel/CKILS_Project_08.2026`)
- **Theory doc:** `POC - Proof Of Concept - theory.docx`
- **Welcome page:** `Welcome_page_explaining.md`
- **Execution plan:** `C:\Users\liran\.claude\plans\hi-i-want-to-scalable-book.md`
- **Training platform (Track A):** https://claude.ai/code/artifact/f6d5d3c8-41c7-467e-b4d6-16313baaa78c
- **Code (Track B):** `week1/`, `week2/`, etc.
