# CKILS — Contextual Keyboard Input Locale Switcher

A Windows tool that switches your keyboard between Hebrew and English by itself — from what's on your
screen and from what you type — so you stop pressing Alt+Shift, and stop typing a whole sentence in the
wrong layout before you notice.

Built from scratch in Python as a learning project, tested on real daily use, and improved one real bug
at a time. The full history — every bug, how it was found, what was measured — is in
[`PROJECT_JOURNEY.md`](PROJECT_JOURNEY.md).

**Before you try it, read [What CKILS Sees](https://claude.ai/artifact/KMiiK4EUXr74emHT2PtYEe)** — a short
page (English and Hebrew) on what it reads, what it keeps, and how to stop it.

## How it decides

Four layers, each stepping in where the one before isn't enough:

1. **What it already knows.** When you arrive in a window, it switches to the language you typed most
   there (remembered per window until you close it), or to what it has learned about that page or app —
   but only once that history agrees with itself (at least 3 decisions, 80% the same).
2. **What's on the screen (Tier 3).** It reads the text you're working in (UI Automation, or OCR with
   Tesseract) and a small model trained on real labeled text decides the language. The model can also
   answer "not real text", and text that repeats identically across pages of the same app — an address
   bar, a player label, an input placeholder — is learned as the app's own interface and ignored.
3. **What you type (Tier 4, the typing safety net).** If a word comes out as gibberish because the
   keyboard is in the wrong layout, it switches when the word ends. Hard spelling rules (a Hebrew word
   never has ם/ן/ץ/ף/ך mid-word, never ends in a regular מ/נ/צ/כ; English words have vowels) plus a
   letter-trigram model that compares both readings of the same keys, trained only on public word lists.
4. **You're always in charge.** A manual switch is respected on that page — unless the next words show
   it was a mistake (2 clear wrong-layout words). Screen reads never change the language while you're
   typing, and a weak read can't undo a stronger one.

## Measured on real use

| | Before | After |
|---|---|---|
| Hebrew typed on English, caught by the 3rd word | 2% | 93% |
| English typed on Hebrew, caught by the 3rd word | 66% | 96% |
| Correct English wrongly switched by the 3rd word (the price) | 0% | 1.6% |
| Wrong screen-read switches on hand-labeled real screen text (old vs new model) | 33 | 23 |
| Real manual corrections per 100 automatic switches (Oct 1–14 vs Oct 15–19) | 9.0 | 4.1 |

The first three rows replay every version of the typing safety net from its Git history, from Oct 14
(when it started switching) to today, on the same 266 Hebrew and 371 English sentences. The last row is
only 5 days of data so far — a promising sign, not proof. It comes from
`measure_corrections.py`, which separates real corrections from CKILS's own lag, carry-over between
windows and deliberate tests.

## Privacy

- Everything stays on your computer. Nothing is uploaded.
- The typing safety net keeps only the current word, in memory. Typed letters are never written to disk,
  and password fields are skipped entirely.
- The decision log keeps what was read and why it decided, for 365 days; screenshots (cropped to the
  region read) for 60 days. The learned interface text is stored as fingerprints (hashes) only.
- To clear everything: delete the `logs` folder, `ckils_decisions.db`, `ckils_skips.db` and the `.json`
  files next to `CKILS.exe`. It simply starts learning again.

## Install and run

1. Install Tesseract OCR once (CKILS uses it to read the screen):
   ```
   winget install --id UB-Mannheim.TesseractOCR -e
   ```
2. Download `CKILS.exe` from the [latest release](https://github.com/Liran-Martfel/CKILS_Project_08.2026/releases/latest)
   and run it. No installation; close its window to stop it.
3. Optional — the typing safety net is off until you turn it on, with empty files next to `CKILS.exe`:

| File | Effect |
|---|---|
| `enable_gibberish_detection.on` | Turns the typing safety net on (log only) |
| `enable_gibberish_autocorrect.on` | Lets it switch the keyboard too |
| `disable_tier4_now.trigger` | Turns the typing safety net off at once |
| `disable_letter_model.on` | Turns off only the letter model |
| `use_old_language_model.on` | Uses the previous screen-reading model |

All of them take effect immediately, no restart.

## From source

Windows 10/11, Python 3.10+ (developed on 3.14), with `pywin32`, `psutil`, `uiautomation`, `pytesseract`,
`Pillow`, `scikit-learn` and `joblib`.

```
python ckils/week2/rule_engine.py          # run CKILS
python ckils/week2/test_regressions.py     # 263 tests, one per real bug found
python ckils/week2/measure_corrections.py  # real corrections, read from your own logs
python ckils/week2/summarize_skips.py      # why CKILS did nothing, when it did nothing
```

The models ship in the repo: `language_model_v2.joblib` (in use), `language_model.joblib` (the previous
one) and `letter_model.json` (rebuilt with `build_letter_model.py` from the public FrequencyWords lists).
Training data is real screen text, so it stays local.

## Repo layout

- `ckils/week2/` — the code. `rule_engine.py` is the entry point; `keyboard_hook.py`,
  `gibberish_detector.py` and `letter_model.py` are the typing safety net; `predict_language.py` and
  `interface_text.py` the screen reading; `test_regressions.py` the tests.
- `ckils/week1/` — the first lessons.
- [`PROJECT_JOURNEY.md`](PROJECT_JOURNEY.md) — the development log.
- `POC - Proof Of Concept - theory.docx` — the original project spec.
