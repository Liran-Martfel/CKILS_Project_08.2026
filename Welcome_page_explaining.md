# Welcome to CKILS

**CKILS** — Contextual Keyboard Input Locale Switcher — is a Windows tool that automatically
switches your keyboard's typing language based on which app or window you're using, so you never
have to press Alt+Shift again.

## The problem

If you type in more than one language (this project focuses on Hebrew and English), you know the
drill: you switch to a different app, forget your keyboard is still set to the other language, and
type a full sentence of gibberish before noticing. Then you delete it, switch layouts manually, and
retype. It happens constantly — in chats, documents, search bars, work tools — and it adds up to
real lost time and real mistakes (imagine this happening in an official document or a form).

## The master goal

This POC's finish line is **AI-driven, not rule-driven**. The rule-based tiers below (Tier 1/2)
are the learning foundation, not the end state. The project is done when CKILS can look at the
screen (image/vision recognition) and how the user is typing, and *decide* the right language to
switch to from that understanding directly — no per-app rule map required at that point. This is
what the theory doc's optional "Tier 3, content-aware" layer grows into: not a stretch goal, but
the mandatory final phase.

## The core idea (the hypothesis this project tests)

> Can a small background service watch what you're doing on Windows — which app, which window —
> and reliably switch your keyboard's input language *for you*, automatically, without ever
> getting in your way or making a mistake itself?

That's the entire question this Proof of Concept exists to answer.

## How it's meant to work

The design has three layers, from simplest to most advanced:

1. **Tier 1 — Process rule.** The simplest layer: "when I'm in Notepad, use Hebrew. When I'm in
   this specific app, use English." A fixed rule per application.
2. **Tier 2 — Window rule.** More precise: different windows *within the same app* can have
   different rules (useful for browsers, where one tab should behave differently from another).
3. **Tier 3 — Content-aware (experimental).** The most ambitious layer: looking at the text
   already in a field and guessing the right language/direction automatically, without any rule at
   all.

Underneath, three mechanisms make this possible:

- **Noticing you switched apps or windows** (a Windows "focus changed" event).
- **Actually changing the keyboard layout** for that specific window, programmatically.
- **A manual override** — if you switch the language yourself, the tool respects that immediately
  and leaves that window alone, with no timer and no button. It quietly forgets the override the
  moment you switch to a different window, so the next time you come back, it's automatically back
  to normal — never fighting you over control of your own keyboard, and never needing you to notice
  anything happened at all.

## What this POC covers — and what it deliberately doesn't

**In scope:** Windows 10/11, Hebrew + English, common apps (Notepad, browsers, Office, web tools
like Gmail/Docs, Slack/Teams), and regular text fields.

**Out of scope (for now):** other operating systems, other languages, remote/virtual desktop
sessions, and — importantly — **password fields are never read or touched**, for obvious privacy
and security reasons. This tool also only switches *which layout is active* — it never touches UI
language, translates anything, or "fixes" text you already typed wrong.

## How we'll know if it worked

The project has concrete, measurable success criteria — not just "it feels fine." A few of the
must-hit ones: switching takes under 150ms (so it feels instant), it correctly identifies the right
app 100% of the time in testing, it never needs administrator permissions, and it never reads
anything from a password field. The full list lives in the theory document
(`POC - Proof Of Concept - theory.docx`).

## Where this is headed

Once the rule-based tiers (Tier 1/2) are solid, the project moves toward the master goal above:
an autonomous, AI-driven system that recognizes the screen and the user's typing itself, instead
of being told per-app what to do.

## Where the project stands right now

This is a **learning project** — it's being built from scratch in Python, one weekly milestone at
a time, as a hands-on way to learn both coding and how a real Windows system-level tool comes
together. **Week 1 and Week 2 are both complete.** CKILS watches two rule-configured apps,
automatically switches each one's keyboard layout, correctly leaves a window alone if you override
it by hand — resuming automatically the moment you move on to something else — and measured
switch latency comes in at well under 1ms per switch (charter target: under 150ms). All of it
verified through real, hands-on debugging, including a few genuine surprises about how Windows
itself behaves (some apps, like Calculator and Notepad, turned out to have their own quirks worth
knowing about). Week 3 (broader app/browser-tab compatibility) is next.

## How to build/run

- Requirements: Windows 10/11, Python 3.10+, with `pywin32` and `psutil` installed
  (`pip install pywin32 psutil`) inside a virtual environment.
- The working code lives under `ckils/week1/` and `ckils/week2/`, one file per lesson.
- To try the current rule-based auto-switcher: edit the `RULES` dictionary near the top of
  `ckils/week2/rule_engine.py` to match two apps you actually have open, then run it
  (`python ckils/week2/rule_engine.py`) and Alt-Tab between them.
