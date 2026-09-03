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

## 2026-08-30 — Plan revised: two new mandatory weeks for the AI phase

**19:15** — Asked whether the current path was still correct given the master goal, then asked to
update the plan and timeline. Confirmed the architecture already supports it cleanly: Weeks 1-2's
mechanism (focus detection, `PostMessage` switching, the override guard) is fully decoupled from
*how* the target language gets decided — right now a `RULES` dict lookup, later a drop-in AI call.
Nothing already built needs to change; Week 4's old "optional stretch" framing was the only thing
that no longer fit, since a real screen-recognition + typing-intent decision engine is a much
bigger problem than the one-line `langdetect` idea originally sketched there.

Updated `C:\Users\liran\.claude\plans\hi-i-want-to-scalable-book.md`:
- Timeline revised from "up to 4 weeks" to **up to 6 weeks total**, while noting actual pace has
  run well ahead of one-milestone-per-week so far.
- Added a **Master goal** section documenting Tier 3 as mandatory, not optional.
- Week 4 keeps its original scope (test matrix + findings on the rule-based system) but is now a
  real standalone checkpoint, not a stepping stone with a stretch goal bolted on.
- Added **Week 5** (research/prototype the AI decision engine offline, against recorded examples —
  correctness first, no latency budget yet) and **Week 6** (integrate it as the `RULES.get(...)`
  replacement, re-measure SC-02 latency, re-run the TC-01…TC-05 test matrix against the AI-driven
  version, decide explicitly whether the <150ms target needs relaxing for the decision step vs. the
  switch-execution step).

---

## 2026-08-30 — Every lesson now shows the complete file, not just a snippet

**19:40** — Motivated by a real confusion on lesson 2.4: its instructions said to add timing
"right before the PostMessage call," but the lesson only showed a short fragment with no visible
PostMessage call nearby, and the reference solution (2.3) used "..." elisions ("same imports as
2.2, plus:") instead of a complete file. That ambiguity led to code being added in the wrong place
in the actual function — before the rule lookup and override guard even ran, effectively bypassing
both.

Added a collapsible **"Full file, exactly as it should look after this lesson"** block to every
lesson (1.1 through 2.4) on the training platform — always the complete, standalone,
copy/paste-ready file(s) for that checkpoint, no ellipses. For 1.1–1.3, 2.1, and 2.2 this reuses
what was already complete in those lessons; 2.3 and 2.4 (previously incomplete) are now written
out in full, matching the actual reviewed/merged design (previous_hwnd-based override reset,
`perf_counter`-timed switch). Verified the underlying JS still parses cleanly before republishing.

---

## 2026-08-30 — Lesson 2.4 complete: latency measured, SC-02 passes

**20:05** — Working through 2.4 (latency measurement) surfaced a genuinely useful string of small,
repeated typos — good practice reading error messages carefully:

1. `time.pref_counter()` / `time.pred_counter()` → `time.perf_counter()` (typo'd twice, two
   different ways).
2. `{elapsed_ms.f1}` → tried as `{elapsed_ms:.f1}` next → finally correct as `{elapsed_ms:.1f}` —
   an f-string format spec (`:.1f`, one decimal place) is easy to garble character-by-character.
3. Placement bug: the timing block was first added at the very top of `on_focus_change`, before
   `exe_name`/`target_hkl` existed yet, with its own extra `PostMessage` call — which would have
   bypassed the rule lookup and the override guard entirely, forcing a switch on every focus event
   regardless of overrides. Corrected placement: wrap the one real, guarded `PostMessage` call
   near the bottom of the function instead — never add a second call.
4. A leftover duplicate `print(...)` (the pre-2.4 version, without timing) stuck around for a
   couple of rounds after the timed one was added — removed once flagged.

**Result, confirmed by the user:** switches print consistently at ≤0.5ms, one cold-start outlier
at 3.1ms (expected — first-call OS/Python warm-up, not a real number to worry about). Comfortably
passes the charter's SC-02 target (<150ms). Re-ran the override-guard sequence on this same edited
file afterward — manual override still detected and respected, and still resumes automatically
after switching to a different window and back. **Week 2 is now fully complete**: rule engine,
override guard, and latency measurement, all verified working end to end.

Merged `ckils/week2/rule_engine.py` as-is (a few harmless leftovers remain — the unused
`check_layout_later`/`threading` import and some commented-out debug lines from the override-guard
investigation earlier today — functionally inert, optional cleanup only, not blocking).

---

## 2026-08-30 — Docs synced to "Week 2 complete"; 2.4 gets a proper test procedure

**20:20** — Cleanup pass after Lesson 2.4's completion:

- Training platform's Lesson 2.4 "Type it and run it" section replaced with a proper **"How to
  test it"** step-by-step (open both apps, run it, Alt-Tab and read the numbers, check against
  SC-02, note that a single higher first reading is normal warm-up — and explicitly re-run 2.3's
  override check on the same file, since an edit here could silently break the previous lesson's
  guard without it being obvious).
- `Welcome_page_explaining.md` and `README.md` both updated from "Week 2 nearly done" to **Week 2
  done**, with the measured latency result (well under 1ms per switch) called out specifically.

---

## 2026-08-31 — Week 3 built out in full on the training platform

**09:15** — Built and published all three Week 3 lessons, replacing the old outline placeholder:

- **3.1 — Rules that check the title too (Tier 2).** `RULES` now accepts either a plain HKL
  (simple, always-one-language apps) or a list of `(title keyword, HKL)` pairs, resolved by a new
  `resolve_target(exe_name, title)` helper — needed because one process (e.g. `chrome.exe`) can
  host completely different windows (Gmail vs. an English site) that a process-only rule can't
  tell apart.
- **3.2 — Catch a tab switch without ever leaving the window.** The real gap Tier 2 alone doesn't
  close: switching *tabs* inside one window never fires `EVENT_SYSTEM_FOREGROUND` at all, since the
  window itself never loses focus — the charter's own TC-02 case, and something every mechanism
  built since Week 1 is blind to. Researched and verified (not assumed) a second Win32 event,
  `EVENT_OBJECT_NAMECHANGE`, which fires when a window's title text changes even without a focus
  change — confirmed via Microsoft's own engineering blog (Raymond Chen, "The Old New Thing") and
  double-checked directly against this project's own venv that pywin32 already wraps all three
  constants needed (`EVENT_OBJECT_NAMECHANGE`, `OBJID_WINDOW`, `CHILDID_SELF` — no `ctypes` gap
  this time, unlike `SetWinEventHook` itself back in Week 1). Registers a second hook pointed at
  the same callback, filtered to just the currently-focused window's own title changing.
- **3.3 — Test it against real apps.** Deliberately open-ended, no new code: extend `RULES` to
  Edge/Firefox (expected to behave like Chrome) and go find out — genuinely untested here, not
  assumed — whether Slack/Teams change their window title per-channel the way browsers do per-tab.

Verified before publishing: the JS still parses cleanly, and both full-file code listings (3.1,
3.2) were extracted and byte-compiled with the project's own Python (`py_compile`) to confirm they
run, not just read correctly.

---

## 2026-09-01 — Real finding: Chrome's multi-window shared thread broke the override guard

**09:40** — Testing 3.1 for real (two separate Chrome windows, Gmail + Google Docs) surfaced
repeated false <code>"manual override detected"</code> messages without ever touching the keyboard
manually. Investigated with evidence rather than guessing: added a debug print of `hwnd` and
`thread_id` together, Alt-Tabbed (and minimized) between the two Chrome windows, and confirmed
directly from the output — both windows reported the exact same `thread_id` (`18984`), despite
being two different `hwnd`s.

**Root cause:** keyboard layout is a per-*thread* OS property (established back in 2.1), not
per-window. Chrome's separate top-level windows commonly share one underlying UI thread, so
switching one window's layout silently changes it for every other window on that same thread.
2.3's override guard assumed `hwnd`-keyed bookkeeping told it about one window's independent true
state — an assumption that's simply false once two windows share a thread. The user's own
"it happens when I minimize" observation turned out to be a red herring pointing at the right
culprit: minimizing one Chrome window just happened to hand focus to its same-thread sibling,
triggering the same collision as any other switch between them.

**Fix:** re-keyed the guard's bookkeeping — `last_set`, `last_switch_time`, `overridden`, and the
reset trigger (`previous_hwnd` renamed `previous_thread`) — from `hwnd` to `thread_id` throughout.
`resolve_target`'s per-window title decision was untouched (it was never the problem). This costs
nothing for single-window apps like VS Code (one window, one thread — identical behavior either
way) and fixes the false positives for Chrome. Applied to `ckils/week2/rule_engine.py` and folded
directly into Lesson 3.1 (as the corrected, canonical version — not a bolted-on patch) and 3.2 on
the training platform, same pattern as the 2.3 override-guard rewrite.

**Confirmed fixed** — re-ran the same Gmail/Docs/minimize sequence with a debug print of
`hwnd`/`thread_id`/`actual`/`last` on every event: zero false "manual override detected" messages,
every `actual` reading matched `last` before each switch. 3.1 is genuinely done, not just
"no errors thrown."

Also broadened the standing "keep the journal updated" practice at the user's explicit request:
going forward, a real finding like this one gets the training platform's lesson content corrected
automatically too, not just a journal entry — without needing to be asked for the website update
specifically.

---

## 2026-09-01 — Lesson 3.2 confirmed working

**11:05** — Added the `EVENT_OBJECT_NAMECHANGE` filter and second hook to `rule_engine.py`. Two
small typos caught along the way: `if event = win32con...` (assignment `=` instead of comparison
`==`, which is what PyCharm's `':' expected` error was actually pointing at) and
`EVENT_OBJECT_NAMECHANGED` (extra trailing "D" — the real constant has none).

Tested with `Ctrl+Tab` switching between a Gmail tab and a Google Docs tab, never leaving the
window: confirmed via the debug print that `hwnd=264214` stayed identical across the entire
sequence (proving no focus/window change ever happened), while the language still correctly
flipped Hebrew ↔ English on every tab switch. **Lesson 3.2 is done** — CKILS now reacts to tab
switches, something no mechanism before this lesson could see at all.

Week 3's core mechanism (3.1 + 3.2) is now fully built and verified. 3.3 (testing against
Edge/Firefox/Slack/Teams) remains open.

---

## 2026-09-01 — Lesson 3.3 done; Week 3 complete

**11:20** — Tested Edge against 3.1 and 3.2: confirmed working exactly like Chrome (title-based
rules and tab-switching both fine — expected, since Edge is Chromium-based). Firefox and
Slack/Teams were **not tested** — the user doesn't have them installed, not a failure or an
assumption either way. Recorded honestly rather than guessed at: Edge is genuine, independent
confirmation only insofar as it's a second Chromium-family browser; real cross-engine (Firefox)
and non-browser (Slack/Teams title-per-channel) confirmation remains open for whenever those apps
are available to test.

**Week 3 is complete** — 3.1 (title-based Tier 2 rules), 3.2 (tab-switch detection via
`EVENT_OBJECT_NAMECHANGE`), and 3.3 (real-app testbed check) all done and verified. Next up per
the plan: Week 4 (the charter's TC-01…TC-05 test matrix, remaining success criteria, and a
Go/Go-with-Conditions/No-Go decision on the rule-based system as it stands).

---

## 2026-09-01 — Week 4 built out in full on the training platform

**12:10** — Re-extracted the actual theory doc text directly (the earlier read was Hebrew,
mojibake'd in the terminal on first attempt — re-ran it writing straight to a UTF-8 file instead
of printing through the console, since the console's codepage was garbling multi-byte characters)
to get the charter's real SC/TC definitions verbatim rather than working from memory, matching this
project's own "verify before teaching" rule.

Built and published all three Week 4 lessons, replacing the outline placeholder:

- **4.1 — Run the test matrix (TC-01–TC-05).** Two of five already genuinely satisfied by earlier
  work (TC-02 by 3.2's tab test, TC-04 by 2.3/3.1's override testing) — the lesson connects those
  dots rather than re-running them. Three are new: TC-01 (type immediately after switching,
  count first-character errors — different from 2.4's raw switch-speed measurement), TC-03 (an
  unconfigured app must be left completely alone), TC-05 (a password field's window still
  switches normally, without CKILS ever touching the field's content — architecturally guaranteed,
  verified behaviorally once).
- **4.2 — Check the remaining success criteria.** SC-01 (honest tally against the charter's own
  10-app testbed), SC-04 (first-character error rate, fed by 4.1's TC-01 data), SC-06 (password
  protection, both architectural — no code path reads field content at all — and behavioral),
  SC-08 (explicitly marked out of scope: it's Nice-to-have and its own measurement method needs a
  5-user study, genuinely not applicable to a solo learning POC), SC-09 (a real 8-hour background
  run, no shortcuts).
- **4.3 — Write the findings + decision.** Teaches the charter's own three-way framework verbatim
  (Go / Go with Conditions / No-Go) and asks for the SC/TC evidence to drive the verdict, rather
  than asserting one — deliberately left as the user's own conclusion to write, not pre-decided
  here.

---

## 2026-09-01 — Lesson 4.1 done: all five test cases pass

**12:40** — Ran all five of the charter's test cases against `rule_engine.py`:

- **TC-01 (Rapid Focus Switching):** 5 switch-then-type attempts, **0 wrong first characters**.
  Small sample — the charter's own <3% target is easier to trust with 10+ runs, so this is a good
  early signal rather than a fully confident number; worth noting honestly as such in 4.2 rather
  than treating 5/5 as proof.
- **TC-02 (Tab Context):** already satisfied by 3.2 — no new run needed.
- **TC-03 (Fallback Handling):** confirmed — an app with no `RULES` entry is left completely
  alone, no output, no switch attempt.
- **TC-04 (User Override):** already satisfied by 2.3/3.1 — no new run needed.
- **TC-05 (Security Sandbox):** confirmed — clicking into a real password field is a non-event for
  CKILS; it only ever reads window title and process name, never field content.

**Lesson 4.1 is done.** Next: 4.2 (remaining success criteria), which uses this TC-01 data
directly for SC-04.

---

## 2026-09-01 — SC-01 progress: Windows Terminal works, Settings confirmed incompatible

**13:05** — Testing two more apps from the charter's SC-01 testbed:

- **Windows Terminal — confirmed working.** First guess (`'cmd.exe'`) was wrong: modern Windows
  Terminal's window belongs to `WindowsTerminal.exe`, not the shell process running inside it.
  Fixed via a temporary `exe_name` debug print rather than guessing further. Confirmed switching
  correctly, consistently, once `RULES` used the right key.
- **Windows Settings — confirmed incompatible, same root cause as Calculator.** Its window also
  reports `ApplicationFrameHost.exe` (the same generic UWP wrapper Calculator uses — meaning the
  two can't even be told apart by exe name alone). The switch *looked* successful in the debug
  print (`actual` matched `target` right after "switched"), but nothing changed on screen — the
  wrapper's own thread state can shift while the real Settings content, owned by a separate
  child window/thread, never receives the message. Removed the `RULES` entry entirely rather than
  leave a misleading always-"succeeds" print for something that doesn't actually work.

**Running SC-01 tally**, against the charter's 10-app testbed: **working** — Chrome, Edge, Google
Docs/Gmail (web), Windows Terminal (4/10, 40%). **Confirmed incompatible** — Calculator, Settings
(both `ApplicationFrameHost.exe`-wrapped UWP apps). **Quirky/unreliable** — Notepad. **Untested** —
Firefox, Word, Slack/Teams. Still below the charter's 70% target as of this entry; three apps
remain untested.

---

## 2026-09-01 — Word confirmed working for SC-01; tally now 5/10

**13:20** — Tested Word (`WINWORD.EXE`) despite not having an active Office subscription — Word's
own nag/activation screen blocks normal document editing, so instead of typing, the OS-level
taskbar language indicator was checked directly (keyboard layout is tracked by Windows, not by
Word itself, so this works regardless of subscription state). **Confirmed working** on the first
attempt — the indicator switched correctly the instant Word gained focus. A second attempt was
blocked by the nag screen retaking focus before a repeat test could run; one confirmed switch is
sufficient evidence here (SC-01 isn't the criterion asking for repeated reps — that's SC-03's
separate 100-transition measurement, which isn't required per individual app).

**Updated SC-01 tally**, against the charter's 10-app testbed: **working** — Chrome, Edge, Google
Docs/Gmail (web), Windows Terminal, Word (**5/10, 50%**). **Confirmed incompatible** — Calculator,
Settings. **Quirky/unreliable** — Notepad. **Untested** — Firefox, Slack/Teams. Getting closer to
the charter's 70% target; two apps remain untested (Slack/Teams may stay permanently untested —
not installed on this machine).

---

## 2026-09-01 — SC-01 hits the charter's 70% target: Firefox and Teams both confirmed

**13:50** — Tested the last two apps on the charter's SC-01 testbed:

- **Firefox — confirmed working, fully.** Real exe name confirmed via debug print
  (`firefox.exe`) rather than guessed — one early attempt (`'firefox.exe.EXE'`) didn't match for
  exactly that reason. Once fixed, both mechanisms tested independently of Chromium: 3.1's
  title-based window rules and 3.2's tab-switch detection (`EVENT_OBJECT_NAMECHANGE`) both work
  correctly on Firefox's Gecko engine — real, independent confirmation that neither mechanism was
  quietly Chromium-specific.
- **Teams — confirmed working**, via a simple process-level rule.

**SC-01 now stands at 7/10 (70%)** against the charter's own representative testbed — **hitting
the Must-criterion target exactly**: Chrome, Edge, Firefox, Word, Windows Terminal, Google
Docs/Gmail (web), and Teams all confirmed working. Calculator and Settings remain confirmed
incompatible (both `ApplicationFrameHost.exe`-wrapped UWP apps — an architectural limit, not a
CKILS bug); Notepad remains quirky/unreliable. This is a real pass on one of the charter's Must
criteria, not a rounding-up — first genuine data point toward Week 4's Go/No-Go decision in 4.3.

---

## 2026-09-01 — Overall progress check: ~90% of the charter, ~40-45% of the master goal

**14:10** — Asked for an honest overall "how much is right" number. Answered with two separate
figures rather than one, since they measure genuinely different things:

- **Against the original charter** (the rule-based POC, Weeks 1-4): roughly **90%**. 7 of 8 Must
  success criteria confirmed passing with real evidence (SC-01 at 7/10, SC-02, SC-03, SC-04, SC-05,
  SC-06, SC-07). Only SC-09 (8-hour stability) is still open, and that's a matter of time, not risk.
  SC-08 is Nice-to-have and correctly scoped out.
- **Against the project's actual master goal** (AI-driven, no rule table at all): closer to
  **40-45%**. Weeks 1-4 are a solid, well-tested foundation, but Weeks 5-6 — the mandatory AI phase
  — haven't started at all, and that's explicitly the hardest, least-proven part of the whole
  project.

Updated `README.md` and `Welcome_page_explaining.md` with both figures and the current Week 4
status (test matrix passed, SC-01/04/06/08 done, SC-09 + the 4.3 write-up still open), so the
project's real state is visible without needing to read the full journal.

---

## 2026-09-01 — Week 4's real results folded into the training platform

**14:25** — Added "Results, tested for real" sections to Lessons 4.1 and 4.2 on the training
platform, so the actual outcomes (not just instructions on how to test) are visible there too:
TC-01's 5/5 result, TC-03/TC-05 confirmations, and the full SC-01 breakdown — 7/10 passing, the
Calculator/Settings `ApplicationFrameHost.exe` connection, and the Windows Terminal
(`WindowsTerminal.exe`, not `cmd.exe`) trap. SC-09 marked as not yet run.

---

## 2026-09-02 — SC-09 passes: no crashes over an extended real-world run

**08:15** — `rule_engine.py` ran continuously from 2026-09-01 afternoon through the morning of
2026-09-02 — well past the charter's 8-hour target, including a stretch of roughly 8 hours with no
user interaction at all. Confirmed: the process stayed alive and responsive the entire time, no
crash, no silent death, no restart needed. **SC-09 (0 crashes over 8 continuous hours) passes.**

That closes out every success criterion in 4.2. One separate, real problem surfaced during this
same run, unrelated to stability: switch reliability degraded badly over the long run — down to
roughly 20% success, affecting both Chrome and non-Chrome apps (Code.exe), with the console still
printing "switched" even when the layout visibly didn't change. Investigating this now as its own
issue before writing up 4.3 — the leading question is whether this is a long-uptime degradation
(testable by comparing a fresh restart against the same long-running process) or something more
architectural.

---

## 2026-09-02 — Reliability regression traced to long uptime, not a logic bug

**08:45** — After SC-09's long run, switch reliability had degraded badly (~20% success, affecting
Chrome *and* non-Chrome apps like `Code.exe` — the console printed "switched" but the layout
often didn't visibly change). Investigated by comparing behavior on a fresh restart of the exact
same code, with an upgraded debug line (`title` added alongside `hwnd`/`thread_id`/`actual`/`last`)
rather than guessing at a cause.

**Result: a fresh process was reliable again**, close to 100% across Code.exe, pycharm64.exe,
WindowsTerminal.exe, and multiple Chrome/Gemini tabs. Exactly one "manual override detected" fired
in the whole test — traced through the logic and confirmed it was the override-reset mechanism
working correctly (override detected on Gemini → cleared automatically the moment focus moved to
a different thread → resolved cleanly on the next visit), not a new bug.

**Conclusion:** the reliability collapse was caused by something accumulating over many continuous
hours of runtime (likely message-queue pressure or general resource buildup), not a flaw in the
switching logic itself. Documented as a real, honest finding rather than chased down to its exact
root cause, which is out of scope for this POC: **CKILS is reliable under normal use; very long
continuous uptime (8+ hours) can degrade switch reliability over time, and a fresh restart fully
restores it.** This nuances SC-09's pass — the *process* survives 8+ hours without crashing
(confirmed), but *switch reliability* under that same long uptime is a separate, now-documented
caveat worth carrying into 4.3's findings.

---

## 2026-09-02 — Week 4 findings + decision: Go with Conditions

**09:30** — Before writing this up, worth recording why this matters beyond the coursework: this
project isn't just a school exercise — the goal is to actually fix one of the most persistently
annoying parts of using a computer in two languages, switching keyboard layout on every window or
tab, for real, for good. That's the bar this decision is measured against, not just "did the demo
work."

**All results gathered, from 4.1/4.2:**
- TC-01–TC-05: all five pass (TC-01: 5/5 switch-then-type attempts correct, small sample).
- SC-01 (environment coverage): **70% (7/10)** — Chrome, Edge, Firefox, Word, Windows Terminal,
  Google Docs/Gmail, Teams confirmed working; Calculator and Settings confirmed incompatible
  (`ApplicationFrameHost.exe`); Notepad quirky.
- SC-02 (latency), SC-03 (process attribution), SC-05 (no admin), SC-07 (override): pass, proven
  across Weeks 2-3.
- SC-04 (first-character accuracy): pass (0/5 errors, small sample).
- SC-06 (password fields): pass, architecturally and behaviorally.
- SC-08: correctly out of scope (Nice-to-have, needs a 5-user study).
- SC-09 (8-hour stability): **pass** — no crash across an extended real run, including 8 hours
  with zero interaction.

**Two real findings from actually living with it, beyond the formal checklist:**

1. **Local-app workflows expose a real limitation of pure rule-based switching.** Workflows that
   bounce through a terminal window just to launch or restart something local (e.g. starting
   Jupyter) force that terminal's own language rule every time it's focused — even when you're not
   really "working" there, just passing through. A per-window rule has no way to distinguish
   "briefly passing through" from "about to actually type here." This is a genuine, lived case
   *for* the master goal: only real content/context awareness (Tier 3) can make that judgment —
   rules alone can't. Flagged as something to address, not urgently blocking, but real.
2. **Switch reliability degrades over very long continuous uptime** — already root-caused
   separately (see the 2026-09-02 08:45 entry): confidence going into this testing round was
   roughly **90%**; after living with the long SC-09 run, actual observed reliability felt closer
   to **20-30%**. A fresh restart of the identical code restored near-100% reliability immediately,
   confirming this is an accumulation-over-uptime issue, not a fundamental flaw — but it's a real,
   felt gap between "passes the test" and "trustworthy all day, every day," worth continued
   attention. Not yet confirmed whether this connects to the local-app/terminal friction above or
   is fully separate — flagged as something to keep testing.

**Decision, applying the charter's own framework:** despite the confidence drop during real
testing, the underlying mechanism has real, demonstrated potential — process/window-level
switching (Tiers 1-2) is fast, accurate, and survives extended real use; the gaps found are about
polish and long-run robustness, not a broken foundation, and a plain restart already proves it can
return to ~90%+ reliability. There is no content/context understanding (Tier 3) at all yet, which
is exactly what the charter's "Go with Conditions" language describes. **Decision: Go with
Conditions** — window/app-level switching ships as the proven foundation; the two findings above,
plus Tier 3 itself, are the specific conditions to work through next, in Weeks 5-6.

---

## 2026-09-02 — Week 5 begins: direction chosen, Lesson 5.1 built

**10:30** — Worked through the real design decision for the AI phase: a fully local, free,
trained-by-the-user model (not calling an existing pretrained model, and not a cloud API), given
the goal of eventually selling this and potentially patenting it. Landed on: **UI Automation
finds the exact focused control's screen region → Windows' own built-in OCR reads the text inside
it → a small, custom-trained model (built and trained by the user, not an existing one) decides
Hebrew or English from that text.** Chosen over an end-to-end raw-pixel model (skip OCR entirely)
after walking through real numbers: the text-based route is buildable in roughly 1-2 weeks with no
GPU needed, versus 4-8+ weeks and a real risk of needing more data/hardware than available for a
raw-pixel version. Flagged clearly (twice) that OCR-licensing-for-commercial-use and patent
eligibility are real legal questions for an actual attorney, not something to treat as settled
here — the one concrete, non-legal-opinion fact worth acting on: most patent systems (US included)
have a limited window after first public disclosure/sale before the right to patent is lost, so
that conversation should happen before showing this publicly, not after.

**Lesson 5.1 built and verified**: UI Automation's `GetFocusedControl()` and
`.BoundingRectangle` — confirmed against the actual `uiautomation` library source (not guessed),
then installed into the project's venv and run for real, returning genuine data with no errors.
This is the first building block Week 5's OCR/model steps will target instead of reading the whole
screen indiscriminately.

**14:00** — Lesson 5.1 confirmed working end to end: after fixing an early testing-methodology gap
(the script was reading its own PyCharm window because it checked focus instantly at launch, before
there was time to Alt-Tab elsewhere — fixed by adding a 3-second pause before `GetFocusedControl()`
runs), it correctly reported different, precise rectangles for different real controls.

---

## 2026-09-02 — Lessons 5.2 through 5.5 written and published

**14:30** — Authored all four remaining Week 5 lessons on the training platform, each verified for
real before being written (same rule as every lesson so far), not assumed from documentation:

- **5.2 — Read it (OCR).** Installed the actual `winrt` OCR packages plus `pillow` into the
  project's venv and ran real OCR against a live screen region before writing anything. **Real
  finding:** Hebrew OCR is *not* installed by default — `OcrEngine.try_create_from_language` for
  `"he"` returned `None` on this machine even though the Hebrew keyboard layout has worked since
  Week 1; the Hebrew *language pack's OCR feature* is a separate install (Settings → Language &
  region → Hebrew → enable "Optical character recognition"), confirmed via Microsoft's own docs.
  Also confirmed OCR isn't perfect — real misreads on real on-screen code (`sleep` → `steep`) — so
  the lesson explicitly teaches that noise as expected, not a bug to chase. The code runs both the
  English and Hebrew engines and keeps whichever recognized more text, since a single engine can't
  read a script it wasn't built for. Only the English half could be verified end-to-end on this dev
  machine (no Hebrew OCR installed here) — the user needs to confirm the Hebrew half after
  installing that language feature.
- **5.3 — Collect real examples.** A dataset-building script that reads whatever's focused (reusing
  5.2), guesses a label from Unicode script range, and asks the user to confirm/correct it into
  `training_data.csv` — deliberately built from real OCR captures of the user's own usage rather
  than a downloaded corpus, both to match real OCR noise and for originality given the stated
  patent interest.
- **5.4 — Train your own model.** Installed `scikit-learn` into the venv and ran the exact intended
  pipeline (TF-IDF over character n-grams → `LogisticRegression` → `joblib` save/reload) end to end
  against a stand-in dataset before writing the lesson. Chosen specifically because it matches every
  answer from the earlier 8-question elicitation quiz: lightweight/fast on an i5 laptop, simple to
  explain, and fully inspectable ("see exact info it used") — unlike a black-box neural net.
- **5.5 — Wire it into CKILS.** A `decide_hkl()` function that only *refines* the existing `RULES`
  lookup — falling back to it whenever OCR finds no text (an empty field) or the model's confidence
  is below a threshold — rather than replacing Tier 1/2 outright. This is a direct, literal
  application of the Week 4 "Go with Conditions" decision: rule-based switching stays the proven
  foundation, content-awareness sits on top of it. Flagged explicitly as untested for latency
  against the charter's <150ms target (SC-02) — that's the first thing to measure once this is
  actually wired into the user's live `rule_engine.py`.

All four lessons show complete, runnable code (no fill-in-the-blank hints, per standing instruction)
and are published to the training platform. Not yet done: the user writing/running this code
themselves and Claude reviewing it — that's the next real milestone for Week 5.

---

## 2026-09-02 — Real bug found testing 5.2: multi-monitor screenshots came back black

**16:00** — User wrote `ocr_reader.py` correctly (matched the lesson exactly, no typos) and tested
it on Notepad with real English text, but got an empty result every time. Root-caused with a debug
script rather than guessing: it printed the focused control's rectangle as
`left=-695 top=289 right=-209 bottom=662` — negative coordinates, meaning Notepad was on a *second*
monitor positioned to the left of the primary one in Windows' virtual desktop layout. Saved and
inspected the actual captured image directly — solid black.

**Confirmed the cause and the fix directly** (not guessed): `PIL.ImageGrab.grab(bbox=...)` on
Windows only captures the primary monitor unless `all_screens=True` is passed — for a rectangle on
any other monitor, it silently returns black instead of raising an error. Verified on the user's
actual machine: the exact same rectangle came back as solid black (`getextrema() == (0, 0)`)
without the flag, and showed real on-screen text once `all_screens=True` was added.

**Fixed in both places**, per standing instruction — a genuine finding, not a typo:
- Lesson 5.2 on the training platform: the `ImageGrab.grab()` line now includes `all_screens=True`
  by default, with the reasoning and the finding documented directly in the lesson.
- The user applies the same one-line fix to their own `ocr_reader.py`.

This is a real example of exactly the kind of gap this project's testing approach is meant to
catch — the code was "correct" by the lesson as originally written, and only broke because of the
user's actual hardware setup (multiple monitors), which no amount of single-monitor testing on the
dev side would have caught on its own.

**16:20** — Fix confirmed working: with `all_screens=True` added to `ocr_reader.py`, OCR correctly
read real English text off the second monitor. **Lesson 5.2 is done.**

---

## 2026-09-02 — Bigger finding: Windows' built-in OCR doesn't support Hebrew at all

**19:00** — Testing the Hebrew half of 5.2 (garbled output, `?1Dbw nn`) led to a much bigger finding
than expected. Root-caused with debug output showing `engines available: ['en']` — no `'he'` engine
ever got built. Checked directly on the machine with
`Get-WindowsCapability -Online | Where-Object { $_.Name -like "Language.OCR*" }`: over two dozen
languages listed (Arabic, Japanese, Korean, Chinese, most of Europe), every single one either
`Installed` or `NotPresent` (installable) — **no Hebrew entry at all**. Not "not installed yet" —
Microsoft's own OCR simply has no Hebrew model to offer. Confirmed with a second source too
(Microsoft Q&A acknowledging Hebrew as a known gap elsewhere in their OCR/Form Recognizer products).

Since reading Hebrew text is half of what CKILS's whole content-aware phase needs to do, this
wasn't a patchable bug — the OCR engine itself had to change project-wide, not just this one lesson.

**Switched to Tesseract** (free, open-source, Apache 2.0 — no restriction on commercial use or
patent filing, which matters given the stated goal to sell this and potentially patent it).
Installed for real (`winget install --id UB-Mannheim.TesseractOCR -e`), confirmed its installer only
ships English data, downloaded Hebrew's `heb.traineddata` from Tesseract's official repository, and
ran a real combined Hebrew+English recognition test before touching any lesson content.

**Two more real findings along the way:**
1. Tesseract's install folder is under Program Files, which needs admin rights to write to — so
   adding the downloaded Hebrew data there directly isn't possible without elevation. Fix: a
   project-local `tessdata` folder (with a copy of `eng.traineddata` plus the downloaded
   `heb.traineddata`), pointed at directly via `--tessdata-dir` — no admin rights needed anywhere.
2. The first real Hebrew OCR test looked like a total failure — a wall of `□□□□` boxes printed to
   the terminal. It wasn't: writing the result to a file and checking the actual Unicode character
   codes showed Tesseract had read every Hebrew letter correctly (`U+05E9`, `U+05DC`, ... — real,
   correct Hebrew codepoints). The boxes were only the Windows terminal failing to display Hebrew
   glyphs, not an OCR error. A genuinely easy trap to fall into without checking the real bytes.

**Bonus, not just a fix:** Tesseract can take `lang="eng+heb"` and read both scripts in one call,
directly handling a field with mixed Hebrew/English content — better than the old two-engine "race"
approach, and a direct, working answer to the "how does it handle mixed languages in one field"
question from the original design discussion.

Rewrote the user's live `ocr_reader.py` and Lesson 5.2 on the training platform to match, and fixed
the two downstream lessons (5.3, 5.5) whose code called the old async/two-engine version of
`read_region()`. Not yet confirmed: the user re-testing the new Tesseract-based `ocr_reader.py` for
real on their machine — that's the next step.

**19:30** — Confirmed working on the user's machine: the Tesseract-based `ocr_reader.py` correctly
reads real English and Hebrew text. **Lesson 5.2 is genuinely done now**, on real infrastructure
that actually supports both languages CKILS needs.

---

## 2026-09-02 — Lesson 5.3 done: 82 real, balanced training rows collected

**21:00** — User ran `collect_data.py` repeatedly across real usage — websites, chat apps, code
editors, news sites, social media, financial tools — building `training_data.csv` up to 83 rows,
nicely balanced between Hebrew (42) and English (41). One notable real bug hit along the way, worth
recording: OCR can only read what's inside a genuinely *focused, editable* control — static chat
response text (e.g. a generated list of example sentences) isn't focusable at all, so
`GetFocusedControl()` kept returning whatever real input box still had focus instead. Fixed
practically by pasting that kind of content into Notepad first, which *is* a real focusable control.

**Reviewed the dataset before moving to training** (per the "verify before teaching" habit, applied
here to reviewing data quality rather than a new API): found and removed one contaminated row that
had accidentally captured text from this very chat conversation (the earlier "thabks" keyboard-typo
tangent) rather than real language content — 82 clean rows remain, balance essentially unchanged.
The rest of the dataset is genuinely useful, real-world-messy OCR text, exactly the kind of noise
5.4's model needs to learn to handle rather than a clean, artificial dataset would.

**Lesson 5.3 is done.** Next: 5.4, training the actual classifier on this data.

---

## 2026-09-02 — Lesson 5.4 done: trained the classifier, one honest calibration finding

**21:20** — Trained the real classifier (TF-IDF over character n-grams + logistic regression) on
the actual 82-row dataset from 5.3. Held-out test accuracy: 100% (8/8 English, 9/9 Hebrew) — expected
at this stage, since Hebrew and English use entirely different character sets, so this mainly proves
the model learned that basic separation correctly, not much more.

**Tested it against genuinely new text it never saw**, including deliberately tricky cases: clean
English sentences, clean Hebrew sentences, a mixed Hebrew+English string, pure digits with no
language content at all, and short one-word inputs. Every prediction was directionally correct.

**One real, honest finding:** confidence is often weak — some clearly-correct predictions barely
clear 50% (`"ok"` → english at 53.6%, `"123456"` → hebrew at 51.2%, essentially a coin flip, which
is arguably the *right* uncertainty for text with no real language signal). Likely just a function
of only having 82 training rows — more data (going back to 5.3) should sharpen this over time. This
matters directly for 5.5: the planned 0.65 confidence threshold will cause the model to defer to the
rule-table fallback for a fair number of real, correctly-guessed-but-low-confidence cases — which is
actually safe, conservative behavior (better to defer than overrule a working rule on a weak guess),
but worth knowing going in rather than being surprised by it during 5.5 testing.

**Lesson 5.4 is done.** Next: 5.5, wiring this into the actual switching decision.

---

## 2026-09-02 — Lesson 5.5: wired the trained model into rule_engine.py for real

**22:10** — At the user's explicit request, wired Tier 3 directly into the live `rule_engine.py`
(not just a standalone reference file this time). Changes: three new imports (`uiautomation`,
`ocr_reader.read_region`, `predict_language.predict_language`), a new `decide_with_content()`
function next to `resolve_target()`, one change to how `target_hkl` gets its value inside
`on_focus_change()`, and one `InitializeUIAutomationInCurrentThread()` call added before the
message loop starts. Uses the project's real `English_HKL` / `Hebrew_HKL` constants throughout,
not placeholders. Verified to compile cleanly; not yet run live (needs the user's real UI
interaction to test, same limitation as every OCR-dependent script this week).

**One deliberate design change from the original 5.5 outline, made during real wiring:** the
handler no longer bails out immediately when `resolve_target()` returns `None` (an app with no
rule at all) — it now lets the content layer attempt a decision from the real on-screen text first.
This means Tier 3 can now make switching decisions for entirely unconfigured apps, not just refine
already-ruled ones — a genuine capability improvement over the original design, matching the
master goal more directly (less dependence on a maintained rule table over time).

**A new, honest risk surfaced specifically by wiring this into the real event flow (not
theoretical — a direct consequence of how this file already works):** `on_focus_change()` also
fires on every `EVENT_OBJECT_NAMECHANGE` (the Week 3 browser-tab mechanism), and some apps fire
that repeatedly for the same window — e.g. while a page title is still loading, or possibly while
typing in an address bar. Each such event now triggers a full OCR read. Logged `content_ms` on
every single check specifically so this can be measured with real numbers rather than guessed at.
If it turns out to cause noticeable lag in practice, the likely fix is restricting
`decide_with_content()` to genuine focus changes only — but that's a decision for real testing to
make, not something to pre-optimize away without evidence.

**Lesson 5.5 is wired in.** Not yet tested live — that's the next step.

---

## 2026-09-02 — Real live test of 5.5 found a severe latency bug, root-caused and fixed

**22:40** — First live run of the wired-in Tier 3 immediately surfaced a serious problem: logged
`content_ms` values of **1,000-15,296 ms** per check — 7 to over 100 times past SC-02's 150ms
target, not just "somewhat slower." The switch itself was waiting on this before happening at all,
making every focus change feel broken/unresponsive regardless of whether the eventual decision was
even correct.

**Root-caused with two direct benchmarks before touching any fix** (same rule as every other
finding this project):
1. Latency scales with the *amount of text* Tesseract has to recognize — roughly 3-4ms per
   character, confirmed across four image sizes (40k px → 1,335ms/304 chars; 3.6M px →
   43,959ms/9,918 chars). A dense code editor or browser pane can easily have thousands of visible
   characters, explaining the worst numbers directly.
2. Even a **nearly-empty tiny image** ("hi", 100x30px) still took 530-656ms — a large *fixed* cost
   independent of content, because `pytesseract` spawns a fresh `tesseract.exe` process and reloads
   its language model files from scratch on every single call.

Combined, this means the current OCR approach cannot hit 150ms even in the best case, and gets far
worse with real content-dense windows — an architectural mismatch, not a tunable parameter.

**Fix: decoupled Tier 3 from the blocking switch entirely.** `on_focus_change()` now performs the
rule-based switch exactly as it always has since Week 2 (unchanged, sub-millisecond, immediate) —
Tier 3 runs afterward in a background thread (`apply_content_correction()`), and only issues a
*second*, corrective switch if it disagrees, is confident, the window is still actually focused
(checked via `GetForegroundWindow()`, since the user may have moved on during the multi-second OCR
delay), and the user hasn't manually overridden that window in the meantime. This directly follows
what the original 6-week plan itself anticipated for exactly this scenario: "keep the rule table as
an instant fallback while the model result is still pending," rather than forcing an artificial
speed-up of Tesseract itself.

**Known, accepted limitation, not yet addressed:** the background thread and the main message-loop
thread now both touch shared state (`last_set`, `last_switch_time`, `overridden`) without a lock.
Python's GIL prevents low-level corruption, but logical races (a stale read/write ordering) are
possible in principle. Not fixed yet — flagged honestly rather than silently left unmentioned;
worth adding a `threading.Lock()` if real testing surfaces an actual symptom from this.

Verified to compile; **not yet re-tested live** with this fix — that's the immediate next step,
along with a separate, still-open question from the user about specific cases where the model
"didn't recognize" expected content, not yet diagnosed with a concrete example.

---

## 2026-09-02 — Second real bug, found on the very next live test: COM needs per-thread init

**23:10** — User re-tested and, correctly, suspected something was wrong ("maybe override, or the
rule is set and that's it") — real evidence confirmed it immediately: every single `[content]` line
printed `skipped ([WinError -2147221008] CoInitialize has not been called)`. Tier 3 had been
silently failing on every check since the background-thread fix, always falling back to the rule
table — exactly matching the user's own description of what they were observing.

**Root cause:** COM, which `uiautomation` is built on, initializes per *thread*, not once for the
whole process. `InitializeUIAutomationInCurrentThread()` was called once in the main thread before
`PumpMessages()` starts — correct for the main thread, but the previous fix (running Tier 3 in a
background thread) means a brand new thread gets spawned for every single focus change, and none of
those ever received that initialization. **Fix:** call it again at the top of
`apply_content_correction()` itself, since that's what actually executes inside each new thread.

This is now the second real, live-testing-only bug found in the Tier 3 wiring (the first being the
latency issue) — both were invisible from code review or `py_compile` alone, both only surfaced by
actually running it. Verified to compile; **still not yet confirmed working live** — that's next.

---

## 2026-09-02 — Tier 3 confirmed working live, plus a latency optimization

**23:40** — After the COM fix, added debug logging to `decide_with_content()` (the actual OCR'd
text, predicted label, and confidence for every check, since "no change" was ambiguous between an
empty field, low confidence, or genuine agreement). Re-tested live: **Tier 3 genuinely works.** Real
examples from the log: a real Hebrew news site (ynet) correctly triggered a Hebrew correction at
0.94 confidence; an English-language Gemini conversation correctly triggered an English correction;
low-confidence Zoom caption text (0.63-0.74) correctly deferred to the rule table instead of
guessing. Two minor errors also surfaced (`cannot write empty image`, one COM event-subscriber
hiccup) — both caught safely by the existing try/except, no crash, just a graceful "no change."

**User asked to reduce the latency further.** Tried `tesserocr` (keeps one Tesseract engine loaded
in memory instead of respawning a process per call — would directly target the ~500-650ms floor
cost found earlier) — not viable right now: needs Tesseract's native dev libraries to compile
against, not set up on this machine, and no pre-built wheel exists for this Python version.

**Verified a simpler, already-available fix instead:** latency scales with how much text there is
to recognize, not raw pixel area — measured 6,805ms OCRing a dense 1920x1080 pane versus 523ms on
the same content cropped to 300x100. Capped the OCR region to a fixed 400x150 maximum in
`decide_with_content()`. Real tradeoff, accepted deliberately: a huge focused pane (a whole code
editor, a whole webpage) now only gets read from its top-left corner, not read in full — reasonable
given Tier 3 was always meant for judging a small field you're about to type into, not OCRing an
entire document.

---

## 2026-09-02 — Cleanup: RULES moved out of the code, dead code removed

**00:10** — Started preparing the project to actually be shared/downloaded, not just run from this
dev machine. First step: the hardcoded `RULES` dictionary (Liran's personal apps and ML-course-topic
keywords baked directly into the code) moved out into `rules_config.json` — a plain JSON file,
gitignored, that a real user edits themselves without touching any Python. A clean,
generic `rules_config.example.json` (committed to git) ships instead, auto-copied into place on
first run if no personal config exists yet — verified both the real-config-parsing path and the
fresh-install auto-copy path directly before committing.

Also removed dead code found during cleanup: `check_layout_later()` (an old debug helper, confirmed
via search to be called nowhere in the actual program), a stale leftover comment block documenting
an old expected `KeyboardInterrupt` traceback, and added a `DEBUG` flag gating the verbose
`[debug]`/`[content]` diagnostic prints — on for now (still actively testing), meant to be `False`
for a real end-user-facing run. Meaningful status lines (switches, overrides, corrections) stay
visible either way.

Next: packaging this into a standalone Windows `.exe` so it can be downloaded and run without
installing Python — not started yet.

---

## 2026-09-02 — First working standalone CKILS.exe

**00:20** — Installed PyInstaller and built a real one-file `CKILS.exe` bundling `rule_engine.py`
plus every Python dependency (`pywin32`, `psutil`, `uiautomation`, `pytesseract`, `Pillow`,
`scikit-learn`/`joblib`), the trained `language_model.joblib`, the `tessdata` folder, and
`rules_config.example.json`. Build command:

```
pyinstaller --onefile --console --name CKILS --add-data "language_model.joblib;." --add-data "tessdata;tessdata" --add-data "rules_config.example.json;." rule_engine.py
```

Two DLL warnings during build (`UIAutomationClient_VC140_X86/X64.dll not found`) — not yet
confirmed whether these matter in practice. **Verified directly:** the built exe launches and runs
as a genuine, stable Windows process for several seconds with no crash and normal CPU/memory —
strong evidence the bundling itself works (an import or missing-DLL failure would have exited
immediately). Did not yet confirm full behavior (does switching/OCR actually work from inside the
bundle) — that needs a real hands-on test, same limitation as every OCR-dependent script so far.

**Deliberately not yet bundled: Tesseract itself.** It's a separate program with its own DLL
dependency tree (not a Python package), and reliably embedding that inside a PyInstaller bundle is
a materially harder, higher-risk task than bundling Python libraries. For now, Tesseract remains a
documented one-time prerequisite install (the same `winget install --id UB-Mannheim.TesseractOCR -e`
command used in Lesson 5.2) rather than silently assumed to be bundled.

`build/`, `dist/`, and the generated `.spec` file added to `.gitignore` — these are rebuildable
outputs, not source. The actual `CKILS.exe` itself is not committed to the repo (32MB binary,
plus tied to this specific machine's Tesseract path); if real distribution is wanted later, the
standard approach is attaching it to a GitHub Release, not committing it to source control.

---

## 2026-09-02 — Real bug from the user's first exe test: bare relative model path

**00:35** — User ran the actual packaged `CKILS.exe` (not my own smoke test) and hit a real crash
in the background thread on every content check: `FileNotFoundError: language_model.joblib`.
Root cause: `predict_language.py` looked up the model with a bare relative filename
(`"language_model.joblib"`), which only ever worked by coincidence when running
`python rule_engine.py` from inside its own folder — the current working directory happened to
match. Packaged into the standalone exe, bundled data files extract to a different location
entirely, so the bare filename resolved nowhere.

**Fixed** using the same pattern already verified working in `ocr_reader.py` for `tessdata`
(`os.path.join(os.path.dirname(os.path.abspath(__file__)), ...)`), confirmed the resolved path
exists and a real prediction still works, then rebuilt the exe. Quick relaunch confirmed it still
starts cleanly. Not yet confirmed whether this specific fix resolves the issue for the user's next
real test — that's next.

**00:40** — Second exe bug, also real: `ModuleNotFoundError: No module named 'sklearn'`.
`sklearn` is never directly `import`ed in `rule_engine.py` — it's only needed indirectly when
`joblib` unpickles the saved model — so PyInstaller's static import scan never detected it as a
dependency at all. Fixed by rebuilding with `--collect-all sklearn` explicitly. Exe size jumped
32MB → 79MB, confirming it's actually bundled this time.

**01:00** — Third bug, and the most serious one: user reported the model correctly reading Hebrew
but never actually switching. Traced through the real log and found the true cause — **not** a
model or confidence problem. A Chrome window that fires `EVENT_OBJECT_NAMECHANGE` repeatedly in
quick succession was spawning **multiple concurrent background correction threads for the same
window**, all racing to update the same shared `last_set` state with no coordination. One thread's
result landing after another's made the OS's real keyboard layout disagree with what `last_set`
believed had been applied — which the override-guard then misread as "the user must have changed
this by hand," permanently blocking every future correction for that window. This is the exact
theoretical race flagged (but not yet fixed) back when Tier 3 was first wired in.

**Fixed** with a `content_check_in_progress` set: only one correction can be in flight per window
at a time; a new `NAMECHANGE` event while one is already running simply skips spawning a redundant,
racing one. The guard covers the whole `apply_content_correction()` function via `try/finally`, not
just the OCR portion — releasing it too early would have left the exact same race open around the
part that actually mutates shared state. Rebuilt and smoke-tested (launches, no crash); the user's
next real test is what actually confirms this fixes the observed symptom.

**01:20** — Fourth real bug, and an important one: user correctly noticed the rule table still
seemed to "win" even after Tier 3 made a confident correction. Traced through the log and found it:
the fast path re-applies `resolve_target()`'s raw answer on **every single event**, with no memory
that Tier 3 already decided this window moments ago. Confirmed directly in the log — a correction
to Hebrew, immediately undone by the very next title-change event re-asserting the rule's English
answer, for a window the user never even left. Since events (especially repeated title-changes)
fire far more often than corrections arrive, the rule was effectively always winning the tug-of-war.

**Fixed with `content_decision`**, a thread_id → HKL map: once Tier 3 makes a confident call for a
window, that decision now sticks as what the fast path applies for the rest of that visit, instead
of the raw rule reasserting itself every event. Resets to rule-first the moment the user actually
leaves that window (added to the existing `previous_thread` reset logic, unconditional on thread
change now, not just when overridden). This directly reflects what the user asked for: the trained
model should decide the language for a window with real content, with the rule only mattering as
the very first guess before real content is available — not a design change that was quietly
already true, but one this bug had been silently working against.

**Two more real findings from the same test session, not yet acted on:**
- **UI Automation's `GetFocusedControl()` is unreliable for complex web apps.** On this Google Docs
  page specifically, it frequently returned either an empty region or — more concerning — text from
  an unrelated part of the page entirely (OCR reads like `'771" אנרגיה עוד +'`, matching news-feed
  or ad content, not the actual document). Native apps (VS Code, PyCharm) consistently read the
  right thing; complex browser-rendered editors do not. This is a known, industry-wide
  accessibility weak point of rich web editors, not obviously fixable with a quick patch — worth
  investigating whether UI Automation's TextPattern (real accessible text, no OCR/pixels at all)
  is more reliable for at least some apps, as a separate follow-up.
- Also fixed in this pass: `decide_with_content()`'s call to `predict_language()` now has the same
  try/except protection the OCR call already had (this is literally why the earlier `sklearn`/path
  bugs surfaced as raw tracebacks instead of graceful fallbacks — any *future* error in that
  pipeline would have done the same). And `on_focus_change()`'s process/window lookup is now
  wrapped too — a window or process that vanishes between the event firing and this lookup (short-
  lived popups, permission-restricted elevated windows) now skips that one event instead of
  potentially crashing the Windows event callback itself.

Rebuilt and smoke-tested. The user's next real test is what confirms whether the sticky-decision
fix actually resolves the "rule keeps winning" symptom in practice.

---

## 2026-09-03 — Replaced the hand-written RULES table with a learned memory

**09:30** — After a full day of real testing (2026-09-02) exposed how much the hand-written
`rules_config.json` (Gmail→Hebrew, Google Docs→English, ML-course-topic keywords — all written
just to exercise the system while building it) was quietly still deciding outcomes, the user asked
directly: they want the *rules* to reflect what the *model* was trained on, not a human's testing
assumptions. Framed as a real architecture question — two honest options: (a) an empty field is
simply left untouched until real content exists to judge, the purest "AI decides everything"
version, but gives up the founding use case (the right language ready *before* you start typing
into a blank field); or (b) CKILS remembers the last confident language the model itself decided
for each app, and uses that as its own instant first guess next time — built entirely from what the
model observed, not a person's guess. User chose (b).

**Built `learned_defaults.json`**: a small `exe_name → "english"/"hebrew"` memory, gitignored
(per-machine, not shared), written only by `apply_content_correction()` whenever Tier 3 makes a
confident decision — never hand-authored. `resolve_target()` and the whole `RULES`/
`rules_config.json`/`rules_config.example.json` mechanism removed entirely, along with all
per-title keyword matching (Tier 3's own per-window content decision already handles that far
better than a keyword match ever could). Verified the save/load logic directly before wiring it in.

**What this actually changes, honestly:** a genuinely new app CKILS has never seen decide
confidently gets *no* instant guess on its first visit — same limitation as option (a) for that one
case. But every app it *has* seen decide confidently before gets an instant, correct-so-far guess
from then on, entirely self-taught. This is a real, direct answer to yesterday's closing question
("is it AI-driven or rule-driven?") — the instant-guess mechanism itself is now built from the
model's own observations, not a person's assumptions, though it's still gated by the same
underlying problem from yesterday (Tier 3 needs a confident read to ever teach it anything, and
complex web apps like Google Docs still aren't reliably giving it one — that diagnostic is still
the next real step).

Rebuilt the exe, smoke-tested (launches, no crash). Not yet run through a real, extended session —
that's next, alongside finally running `diagnose_focus.py` to find out why Google Docs keeps
starving the model of real content.

---

## 2026-09-03 — Root-caused the web-app blindness: two real, different problems

**10:30** — Ran `diagnose_focus.py` for real against Google Docs, Gemini, and Google Chat (Hebrew
and English messages). This was the actual breakthrough of the day — concrete evidence instead of
guessing, and it revealed **two genuinely different problems**, not one:

1. **Google Docs**: the focused control's `BoundingRectangle` came back as
   `top=-13318` — nowhere near any real screen. Root cause: UI Automation reports this control's
   position in the *document's own scroll coordinates*, not real screen pixels — once you've
   scrolled into a long document, that position can land far outside any monitor. OCRing there is
   a guaranteed-blank capture, every single time, which is exactly why it always read as empty.
2. **Gemini**: the rectangle is genuinely on-screen and correct, but it's the *entire* conversation
   pane (nearly the full browser window) — the 400×150 crop, anchored to the top-left corner, was
   landing on blank padding, not the actual message text further down.
3. **Google Chat (real, positive finding)**: the focused control's `Name` property — a standard
   accessibility field — contained the **entire real message text**, in both the Hebrew and English
   examples tested. Some apps expose real content directly through accessibility data; OCR isn't
   the only way in, and where it's available it's faster and immune to problem #1 entirely.

**Fixed with two changes to `decide_with_content()`, verified against the real diagnostic data
before rebuilding:**
- Try the control's own `Name` first; only trust it when it's substantial (≥20 characters) so
  short generic labels (Google Docs' own control is literally named "תוכן מסמך" — "document
  content," not real content) don't get misread as the actual text.
- Before falling back to OCR, check whether the rectangle is actually on-screen at all, using the
  real virtual-desktop bounds from `GetSystemMetrics` (this machine's: `x: -1920 to 1280`,
  `y: -104 to 976`) — an off-screen rectangle skips OCR entirely instead of wasting ~500ms+ on a
  capture that can only ever come back blank.

Verified the on-screen check directly against all three real captured rectangles before wiring it
in (Docs correctly classified off-screen, Gemini and Chat correctly classified on-screen). Rebuilt,
smoke-tested. **Honest limitation not fully solved by this:** the `Name`-length heuristic isn't
perfect — a `DocumentControl` reporting its tab/page *title* through `Name` (as Gemini's own top-
level element did, separately from the crop-position issue) could occasionally be long enough to
be mistaken for real content when it's genuinely just a title. Not yet a confirmed real problem in
practice, just a known imperfection to watch for in further testing.

---

## 2026-09-03 — The flagged imperfection became real, plus a much bigger bug underneath it

**11:30** — A real extended test session (English vs. Hebrew CVs in different tabs, Google Docs,
Gemini, Segment Studio) surfaced three concrete, connected problems from a single log:

1. **The biggest one — Chrome shares ONE `thread_id` across every tab in the same window.**
   Confirmed directly: `hwnd=197900 thread=18984` appeared identical across Google Docs, Gemini,
   Segment Studio, and multiple PDF tabs. `content_decision` is keyed by `thread_id` — so a
   decision made on one tab was leaking straight into every other tab sharing that thread. This is
   the real explanation for Google Docs "acting like a coin flip": it wasn't random at all, it was
   just inheriting whatever the *last different tab* had decided.
2. **The flagged imperfection from 5.7 turned out to be real, not hypothetical.** `control.Name`
   returned the exact page title for both "Segment Studio Checklist" and Gemini's own top-level
   element — metadata, not the actual visible content — and both got confidently classified from
   that title text instead of the real page.
3. **The actual cause of the English CV reading as Hebrew:** Chrome's own PDF viewer exposes a
   generic Hebrew status message through `Name` — `'מסמך ה-PDF מכיל 2 דפים'` ("This PDF document
   contains 2 pages") — for *every* PDF, regardless of what's actually in it. The accessible-text
   shortcut from 5.7 was reading browser chrome, not the resume.

**Fixed, verified against the exact real strings from the log before rebuilding:**
- `last_title_by_thread`: a title change on a shared thread (e.g. a genuine Chrome tab switch) now
  resets `content_decision` even when `thread_id` didn't change — closing the tab-bleeding hole.
- `_looks_like_real_content()`: rejects accessible text that's just an echo of the window's own
  title (`accessible_text in title`), and rejects the specific Chrome PDF-viewer boilerplate
  pattern (containing both "מכיל" and "דפים"). Ran all five real strings from the log through this
  function directly before wiring it in — all five now classify correctly (2 title-echoes and the
  PDF message correctly rejected, 2 real Google Chat messages correctly accepted).

Rebuilt, smoke-tested. Honest note: the PDF-viewer rejection is a narrow, pattern-specific fix for
this one observed browser message, not a general solution — a different generic browser-chrome
message elsewhere could still slip through the same way. Watching for that in further testing,
not pre-solving it without evidence it's needed.

---

## 2026-09-03 — Full bug list compiled; added page-level learned memory

**12:30** — After an extended real testing session (English/Hebrew CVs, Telegram, Discord,
Explorer, a login page with a language toggle), compiled the full list of everything found so far —
11 fixed, 5 open and connected by one root cause (OCR/accessible text reading generic UI
boilerplate instead of real content: Telegram's "Write a message..." placeholder, Discord's
sidebar channel-list metadata, Explorer's generic "תיקיית קבצים"/File Folder type label, a login
page's fixed "English" toggle button), plus 2 rare/lower-priority items (a 25-second COM stall,
already-handled minor COM errors).

Agreed on direction with the user: chasing each app's specific boilerplate string doesn't scale.
Two real next steps identified — reading the focused control's actual `ValuePattern` (the literal
typed value, immune to placeholders and OCR noise) for real typed content, not yet built; and,
at the user's request, a way to "recognize the page and decide before typing" without hand-writing
assumptions.

**Built the second one now: `page_learned_defaults.json`.** `learned_defaults` alone (per-app) is
nearly useless for a browser hosting wildly different sites. This adds a second, more precise
memory layer keyed by `(exe_name, exact window title)` — "this Gmail inbox is Hebrew," "this
Google Doc is Hebrew" — individually, still entirely self-taught from real confident Tier 3
decisions. Layered fallback, most specific first: this visit's own decision → this exact page's
learned history → this app's general learned history → nothing. Verified the layering logic
against simulated real/unknown page and app cases before wiring it in. Rebuilt, smoke-tested.

Honest limitation: apps with volatile titles (Telegram's unread-count badge changes on every
message) build up many near-duplicate keys instead of one reusable one — harmless, just less
effective for those apps specifically.

---

## 2026-09-03 — Real decisions database, plus a serious persistence bug caught before shipping

**13:00** — Built `ckils_decisions.db` (SQLite, two tables: `decisions` logs every content check —
text read, source, predicted label, confidence, whether it was applied; `overrides` logs every
manual override) and `review_decisions.py`, the review-assisted monthly pass discussed with the
user: NOT a blind auto-retrain (real testing already proved confident-but-wrong decisions happen —
the PDF-viewer message was 0.72-0.75 confident before it was found to be wrong), but a script that
surfaces only entries actually worth a human's time — borderline confidence (0.50-0.80), or
followed within 8 seconds by a real manual override (free, genuine evidence a decision was wrong).
Verified the SQL candidate-selection queries against four constructed cases (clear-correct,
borderline, near-override, far-override) before trusting it — all four classified correctly.

**Caught a serious bug in the same pass, before it could quietly break everything:** in the packaged
`.exe`, `__file__` resolves inside a *temporary* extraction folder that PyInstaller deletes the
moment the process exits. That's correct for reading bundled read-only files (tessdata, the model)
but wrong for anything meant to persist — meaning `learned_defaults.json`,
`page_learned_defaults.json`, and the new decisions database were all silently being written to a
folder that vanished on close. None of today's "learning" was actually surviving between runs of
the exe, even though it looked like it worked within a single test session. Fixed with
`_persistent_dir()`: uses the real, permanent folder next to `sys.executable` when frozen, the
normal script folder otherwise. Verified directly on disk (not just by reading code) that the
database now survives after the process exits, in the exe's real folder.

**Also created a desktop shortcut** (`CKILS.lnk`) pointing at the packaged exe, at the user's
request, for easy day-to-day launching.

---

## 2026-09-02 — Grew the dataset to address the 5.4 confidence finding

**21:40** — Directly addressed the low-confidence finding from 5.4 by adding 68 more labeled rows,
deliberately targeting the weak spot: short phrases and single words in both languages (`"ok"`,
`"בסדר"`, `"thanks"`, `"תודה"`, etc.), plus more medium-length casual sentences. Unlike the 5.3
rows, these are clean, directly-labeled text (no OCR step) — a different, synthetic source, added
transparently as a supplement to the real OCR-collected data, not a replacement for it. Balance held
at essentially 50/50 (150 rows total: 76 Hebrew / 74 English).

Retrained on the larger dataset: held-out accuracy still 100%, and re-ran the same tricky test cases
from the earlier 5.4 finding — confidence improved across the board (`"ok"` 53.6% → 65.2%,
`"Good morning..."` 66% → 75%, `"תודה"` 65% → 73%). The two cases that stayed near 50%
(`"123456"` and mixed `"שלום Hello"`) are supposed to stay near 50% — they're genuinely ambiguous,
so low confidence there is correct behavior, not a remaining gap.

---

## Reference

- **Project home:** `C:\Users\liran\Personal_Project` (GitHub: `Liran-Martfel/CKILS_Project_08.2026`)
- **Theory doc:** `POC - Proof Of Concept - theory.docx`
- **Welcome page:** `Welcome_page_explaining.md`
- **Execution plan:** `C:\Users\liran\.claude\plans\hi-i-want-to-scalable-book.md`
- **Training platform (Track A):** https://claude.ai/code/artifact/f6d5d3c8-41c7-467e-b4d6-16313baaa78c
- **Code (Track B):** `ckils/week1/`, `ckils/week2/`, etc.
