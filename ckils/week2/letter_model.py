"""Tier 4's letter model (2026-10-15): which reading of the same keys is more
typical — the English one or the Hebrew one?

The CBAW rules only ask "is this word impossible in English?", and English
letters allow almost anything: "juac" (חושב), "scrho" (דברים) and "atpar"
(שאפשר) break no rule. A person catches them by comparing — "juac" is an odd
English word, חושב a very common Hebrew one. This does that comparison with
a letter-trigram model per language: how likely each letter is after the two
before it, learned from PUBLIC word-frequency lists (FrequencyWords,
OpenSubtitles 2018, github.com/hermitdave/FrequencyWords — MIT code,
CC-BY-SA-4.0 content), never from anything the user typed or saw. Built by
build_letter_model.py into letter_model.json.

Measured before going in (read-only, on 4,553 Hebrew / 6,822 English words of
the user's labeled screen text, which the model never saw): Hebrew typed on
the English layout caught by word 3 in 93% of sentences (rules alone: 65%),
English on Hebrew 95% (82%) — through the real hook, after the /code-review
fixes; correct English sentences wrongly switched by word 3 fell 2.2% -> 1.6%,
Hebrew unchanged at 3.4% (the rules' own, mostly OCR noise in the test text).

Only ever scores the current word, in memory; nothing typed is stored.
"""
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
LAMBDAS = (0.6, 0.3, 0.1)  # trigram, bigram, unigram

# How much more typical (average natural log per letter) the other reading
# must be. Above SWITCH_THRESHOLD a word switches the layout on its own
# (1.25 = about 3.5x more likely per letter); above MARK_THRESHOLD it only
# marks itself for the second-word rule. Chosen from the measurement: one
# level at 1.0 caught 95% but added wrong switches on Hebrew; this pair
# catches about the same and adds none.
SWITCH_THRESHOLD = 1.25
MARK_THRESHOLD = 0.5
# A word caught only by the comma-inside rule switches only if its Hebrew
# reading beats the English pieces either side of the comma by this much —
# "yes,but" is two English words with the space missing, not one Hebrew word.
COMMA_WORD_THRESHOLD = 0.0
MIN_LETTERS = 3   # 2-letter words are too short to judge by letter statistics
MAX_LETTERS = 20  # longer than any real word — a run of keys, not a word


class LanguageModel:
    """One language's letter-trigram counts, with interpolated scoring."""

    def __init__(self, counts):
        self.tri, self.ctx2 = counts["tri"], counts["ctx2"]
        self.bi, self.ctx1 = counts["bi"], counts["ctx1"]
        self.uni, self.total = counts["uni"], counts["total"]
        self.vocab = len(self.uni)

    def logprob(self, word):
        """Average natural-log probability per symbol (each letter, then the
        word end), so words of different lengths compare fairly."""
        s = "^^" + word + "$"
        l3, l2, l1 = LAMBDAS
        total = 0.0
        for i in range(2, len(s)):
            a, b, c = s[i - 2], s[i - 1], s[i]
            ctx2, ctx1 = self.ctx2.get(a + b, 0), self.ctx1.get(b, 0)
            p3 = self.tri.get(a + b + c, 0) / ctx2 if ctx2 else 0.0
            p2 = self.bi.get(b + c, 0) / ctx1 if ctx1 else 0.0
            p1 = (self.uni.get(c, 0) + 1) / (self.total + self.vocab + 1)
            total += math.log(l3 * p3 + l2 * p2 + l1 * p1)
        return total / (len(s) - 2)


def _model_path():
    """Bundled next to the code, or in the exe's extraction folder."""
    base = getattr(sys, "_MEIPASS", _HERE)
    return os.path.join(base, "letter_model.json")


_models = None


def models():
    """{"english": LanguageModel, "hebrew": LanguageModel}, loaded once.
    None if the file is missing or broken — the letter model then simply
    never fires, and the rules work as before."""
    global _models
    if _models is None:
        try:
            with open(_model_path(), encoding="utf-8") as f:
                data = json.load(f)
            _models = {lang: LanguageModel(data[lang]) for lang in ("english", "hebrew")}
        except Exception:
            _models = {}
    return _models or None


def pieces_margin(english_pieces, hebrew):
    """For a comma word: how much more typical the Hebrew reading of the
    whole word is than the English pieces either side of the comma, each
    scored as its own word (weighted by length). Positive = Hebrew fits
    better. None if the model isn't available or there's nothing to score."""
    m = models()
    if m is None or not english_pieces or not hebrew:
        return None
    weights = [len(p) + 1 for p in english_pieces]
    english = sum(m["english"].logprob(p) * w for p, w in zip(english_pieces, weights)) / sum(weights)
    return m["hebrew"].logprob(hebrew) - english


def other_reading_margin(english, hebrew, typed_language):
    """How much more typical the OTHER layout's reading is than the one
    actually typed, per letter. Positive = the other language fits better.
    None if the model isn't available."""
    m = models()
    if m is None:
        return None
    en, he = m["english"].logprob(english), m["hebrew"].logprob(hebrew)
    return he - en if typed_language == "english" else en - he
