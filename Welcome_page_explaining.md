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
  and steps back for a while, so it never fights you over control of your own keyboard.

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

## Where the project stands right now

This is a **learning project** — it's being built from scratch in Python, one weekly milestone at
a time, as a hands-on way to learn both coding and how a real Windows system-level tool comes
together. It's currently at the very start: environment setup and the first working piece
(noticing when you switch windows).

## How to build/run

Coming soon — this section fills in once the first working code exists (end of Week 1).
