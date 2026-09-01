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

## Reference

- **Project home:** `C:\Users\liran\Personal_Project` (GitHub: `Liran-Martfel/CKILS_Project_08.2026`)
- **Theory doc:** `POC - Proof Of Concept - theory.docx`
- **Welcome page:** `Welcome_page_explaining.md`
- **Execution plan:** `C:\Users\liran\.claude\plans\hi-i-want-to-scalable-book.md`
- **Training platform (Track A):** https://claude.ai/code/artifact/f6d5d3c8-41c7-467e-b4d6-16313baaa78c
- **Code (Track B):** `ckils/week1/`, `ckils/week2/`, etc.
