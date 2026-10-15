"""Builds letter_model.json — the letter-trigram counts letter_model.py
scores with — from two PUBLIC word-frequency lists (one "word count" per
line):

  https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/en/en_50k.txt
  https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/he/he_50k.txt

(FrequencyWords by Hermit Dave, from OpenSubtitles 2018; MIT code,
CC-BY-SA-4.0 content.) Never trained on anything the user typed or saw.

Each word counts by the square root of its frequency: common words matter
more, without "the" and "you" drowning out everything else (measured:
plain counts, log and equal weights all came within ~2 points).

Usage: python build_letter_model.py en_50k.txt he_50k.txt [letter_model.json]
"""
import json
import math
import re
import sys
from collections import Counter

LETTERS = {"english": re.compile(r"^[a-z]+$"), "hebrew": re.compile(r"^[א-ת]+$")}


def count(path, language):
    """Word list -> weighted trigram/bigram/unigram counts and contexts."""
    tri, ctx2, bi, ctx1, uni = Counter(), Counter(), Counter(), Counter(), Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) != 2 or not LETTERS[language].match(parts[0]):
                continue
            weight = math.sqrt(int(parts[1]))
            s = "^^" + parts[0] + "$"
            for i in range(2, len(s)):
                a, b, c = s[i - 2], s[i - 1], s[i]
                tri[a + b + c] += weight
                ctx2[a + b] += weight
                bi[b + c] += weight
                ctx1[b] += weight
                uni[c] += weight
    rounded = lambda counter: {k: round(v, 1) for k, v in counter.items()}
    return {"tri": rounded(tri), "ctx2": rounded(ctx2), "bi": rounded(bi), "ctx1": rounded(ctx1),
            "uni": rounded(uni), "total": round(sum(uni.values()), 1)}


if __name__ == "__main__":
    out = sys.argv[3] if len(sys.argv) > 3 else "letter_model.json"
    model = {"english": count(sys.argv[1], "english"), "hebrew": count(sys.argv[2], "hebrew")}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {out}: " + ", ".join(f"{k} {len(v['tri'])} trigrams" for k, v in model.items()))
