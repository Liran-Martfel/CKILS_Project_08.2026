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

## 2026-08-27 — Lesson 2.2 debugging: three real bugs, one real finding

**11:29** — Working through lesson 2.2 (rule engine) surfaced a genuinely productive debugging
session:

1. **Blocking import bug:** `from week1.focus_watcher import WinEventProcType` executed that
   entire module on import — including its own blocking `PumpMessages()` call at the bottom — so
   the script never reached its own hook registration. Fixed by removing the unused import.
2. **Case-sensitivity bug:** `RULES` used lowercase keys (`'notepad.exe'`), but `psutil` reported
   `'Notepad.exe'` (capital N) on this machine — an exact-match dict lookup silently failed every
   time. Fixed with `RULES.get(exe_name.lower())`.
3. **Real architecture finding, not a bug:** Windows 11's built-in Calculator doesn't run as
   `calculator.exe` — its window belongs to `ApplicationFrameHost.exe`, a wrapper Windows puts
   around modern Store-style apps. Worse, even after matching that process name, the actual
   switch silently did nothing: `ApplicationFrameHost.exe` is only the title-bar/frame window: the
   real app content (and the thread actually receiving keystrokes) lives in a separate child
   window, usually owned by a different process. `PostMessage` succeeded but landed on the wrong
   thread. Confirmed this isn't a one-off guess — the charter's own test matrix already separates
   "Modern Windows (UWP)" as its own testbed category for exactly this reason. Decision: treat
   proper UWP-app targeting as Week 3/4 "edge case" work, not something Week 2's simple rule engine
   needs to solve — swapping the Hebrew test app to a classic (non-UWP) app instead to keep Week 2
   moving.

Also reconfirmed along the way: `-0xfc2fbf3` (Hebrew HKL from lesson 2.1) is correct — proven by
the identical code path already working for English/Notepad.

---

## 2026-08-27 — Lesson 2.2 working end to end

**11:38** — Confirmed working: Alt-Tabbing between two apps now visibly switches the keyboard
language automatically. Two more fixes along the way, found independently:

1. **Bad test app, not a bug:** confirmed Calculator (`ApplicationFrameHost.exe`) genuinely
   doesn't work with this approach, as diagnosed earlier. Swapped the test pair to **Chrome and
   Notepad** — both ordinary desktop apps — which resolved it immediately.
2. **Duplicate Hebrew layout entries:** the machine has more than one installed layout matching
   LCID `0x040D` (Hebrew) — an easy trap, since filtering by LCID alone doesn't guarantee a unique
   match if more than one is registered. Confirmed by testing: **`-0xfc2fbf3` is the correct one**;
   an earlier attempt used a different Hebrew-matching entry that didn't actually work.

Lesson 2.2 (rule engine) is now genuinely complete and verified working, not just "no errors
thrown." Next: 2.3 (override guard) and 2.4 (latency measurement).

---

## 2026-08-30 — "My code disappeared" — a stale-path bug in the lessons

**14:23** — User reported all Week 2 code missing from PyCharm. Investigated: nothing was
actually lost — `week2/list_layouts.py` and `week2/rule_engine.py` were sitting safely committed
in git, just nested under `ckils-poc/week2/` instead of the expected flat `week2/` (matching
`week1/`). Root cause: the training platform's Week 2 lesson instructions still said
`"Create ckils-poc/week1/..."` / `"ckils-poc/week2/..."` — leftover paths from before the project
was consolidated onto `Personal_Project` directly, never updated after that move. The user
followed the (wrong) instructions correctly; this was a lesson-content bug, not user error, same
category as the earlier `SetWinEventHook` mistake.

Fixed properly: moved both files from `ckils-poc/week2/` to `week2/` via `git mv` (preserving
history, staged but left uncommitted per the user's own commit workflow), removed the now-empty
`ckils-poc/` folder, and stripped every stale `ckils-poc/` prefix from all six affected lesson
instructions (1.1, 1.2, 1.3, 2.1, 2.2, 2.3) on the training platform so future lessons don't repeat
this.

---

## 2026-08-30 — One code folder: `week1/` and `week2/` moved under `ckils/`

**14:26** — At the user's request, tidied the project structure: both `week1/` and `week2/` now
live under a single parent folder, `ckils/` (`ckils/week1/`, `ckils/week2/`), instead of sitting
loose at the project root. Moved via `git mv` (staged, uncommitted — left to the user). Updated
every affected lesson path on the training platform to match (`ckils/week1/...`,
`ckils/week2/...`), so future weeks (3, 4, ...) land in the right place from the start instead of
repeating the stale-path issue from earlier today.

---

## 2026-08-30 — The "stuck on Hebrew" mystery: a deep multi-stage investigation

**17:25** — Long debugging session on lesson 2.3 (override guard), worth recording in full since it
took several rounds of hypothesis-and-test to actually nail down.

**Symptom:** switching Chrome → Notepad almost always failed to visibly switch to English;
waiting didn't help; Notepad → Chrome and a fresh cold-start on Notepad both worked fine. Ruled
out several plausible causes in order, each with concrete evidence:

1. *Windows' "different input method for each app window" setting* — a real Windows 11 feature
   that independently remembers/restores per-app language, which would explain this exact pattern.
   Ruled out: the user confirmed the setting was already off.
2. Added a debug print of `actual_hkl` vs `target_hkl` on every event — showed everything matching
   correctly at the moment of focus, no anomaly visible yet.
3. Added delayed re-checks (via background threads, since a `SetWinEventHook` callback can't safely
   `sleep()` without stalling the whole hook) peeking at the layout again +0.5s and +1.5s after each
   focus event. **This caught it directly:** Notepad's layout was correct (English) at the moment
   of focus, then flipped to Hebrew on its own about half a second later — with nothing in
   `rule_engine.py` ever telling it to do that (`RULES` only ever maps Notepad to English). This is
   also what was triggering false "manual override detected" messages on the next visit — the
   guard correctly detected a divergence, but had no way to know it wasn't the user causing it.

**Ruled out (4):** a stray duplicate `python.exe` process — checked `tasklist` while
`rule_engine.py` was actively running: exactly one process, no duplicates.

**Root cause, confirmed (5):** swapped the English test target from Notepad to **Visual Studio
Code** (`Code.exe`), keeping Chrome unchanged. VS Code stayed perfectly stable across every check
(focus time, +0.5s, +1.5s), zero reversions, over many repeated switches. This isolates the bug
entirely to **Notepad itself** — most likely modern Windows 11 Notepad's own internal text-service
behavior (it's been substantially rebuilt in recent years, unlike the old immutable version)
reasserting its own remembered state shortly after gaining focus. Not a flaw in CKILS's mechanism
(`ctypes` + `SetWinEventHook` + `PostMessage`/`WM_INPUTLANGCHANGEREQUEST` + the override guard all
verified working correctly against VS Code) — an app-specific quirk, in the same spirit as the
Calculator/UWP finding from lesson 2.2. Test apps going forward: prefer VS Code (or another
confirmed-stable app) over Notepad for the English side.

---

## 2026-08-30 — A second scare that turned out to be correct behavior

**17:39** — After the Notepad finding above, swapped the Hebrew test app to Zoom (`Zoom.exe`,
Code.exe still English) and saw what looked like a second mystery: both Zoom and VS Code triggered
"manual override detected." This time it wasn't a bug — confirmed the user had pressed their usual
manual-switch hotkey out of habit during the test, without intending to. The override guard
correctly detected it, backed off for both windows, and resumed normally afterward. A useful
reminder: not every unexpected override-detection is a bug — sometimes it's genuinely the feature
working, especially given the user's own lifelong habit of manually switching layouts is exactly
what this project exists to reduce. Lesson 2.3 is now fully confirmed working end to end.

---

## 2026-08-30 — Override guard redesigned: no timer, fully automatic

**18:11** — At the user's request, redesigned the override guard from lesson 2.3 to drop the
15-second cooldown timer entirely (`OVERRIDE_COOLDOWN`/`suppressed_until` removed) — it was making
manual testing fragile and timing-dependent, and the user specifically wanted no visible mechanism
at all (no button, no wait, invisible to the end user).

**New design:** once a manual override is detected on a window, CKILS leaves it alone indefinitely
— tracked via a new `overridden` set. The reset trigger is now purely event-based, not
time-based: the instant focus moves to a *different* window, whichever window was just left gets
its override memory wiped (`overridden.discard(...)`, `last_set.pop(...)`) via a new
`previous_hwnd` tracker at the top of `on_focus_change`. Its next visit is then treated as
completely fresh, rule re-applied automatically. Confirmed this requires no special handling for
"closing the app" — the reset only needs a switch to another window, which the user confirmed is
the actual desired trigger. The grace-period fix (`SWITCH_GRACE`/`last_switch_time`, from earlier)
is unrelated and was left untouched. Applied directly to `ckils/week2/rule_engine.py`, and updated
Lesson 2.3 on the training platform to teach this exact design instead of the old timer-based one.

**Decided for the final phase (not yet started):** debug `print()` output stays as-is until the
project is otherwise complete. At that point, logging moves from console prints to an external
database — **Neon Console** (Postgres) — instead. Captured here so it isn't lost before then.

Also updated `Welcome_page_explaining.md` with the current real status (Week 1 done, Week 2 nearly
done) and filled in the "how to build/run" section, which had been a placeholder since the start.

---

## 2026-08-30 — Master goal set: the project must finish AI-driven

**18:30** — Clarified the project's actual finish line: it must end up related to AI, not stop at
the rule-based tiers. The mandatory end state — CKILS recognizes the screen (image/vision) and how
the user is typing, and *decides* the right language autonomously from that understanding, instead
of relying on a fixed per-app rule map. This promotes the theory doc's "Tier 3, content-aware"
layer from an optional stretch goal to the required final phase.

Weeks 1-2 (focus detection, Tier 1 rule engine, override guard) are unchanged — they're still the
learning foundation this builds on top of, not replaced by it. Updated `Welcome_page_explaining.md`
with a new "The master goal" section near the top and a "Where this is headed" note before the
status section, and updated the training platform with the same framing so the two stay in sync.

---

## Reference

- **Project home:** `C:\Users\liran\Personal_Project` (GitHub: `Liran-Martfel/CKILS_Project_08.2026`)
- **Theory doc:** `POC - Proof Of Concept - theory.docx`
- **Welcome page:** `Welcome_page_explaining.md`
- **Execution plan:** `C:\Users\liran\.claude\plans\hi-i-want-to-scalable-book.md`
- **Training platform (Track A):** https://claude.ai/code/artifact/f6d5d3c8-41c7-467e-b4d6-16313baaa78c
- **Code (Track B):** `ckils/week1/`, `ckils/week2/`, etc.
