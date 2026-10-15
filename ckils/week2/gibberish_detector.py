"""
Tier 4 safety net, piece 1 of 3 (see keyboard_hook.py for the OS-level hook,
layout_remap.py for "what would the other layout have produced"): pure,
OS-independent logic for deciding whether a short piece of typed text is
structurally impossible in a given language — a "CBAW" check ("can't become
a word"), the user's own term for it. Deliberately rule-based, not a trained
model: these are genuine, well-established facts about how Hebrew and
English letters can combine (not a statistical guess), so a real miss can be
fixed by adding one rule, the same way every other UI-noise fix in this
project has been a targeted, explainable addition — not a retraining run.

WHY RULES INSTEAD OF A REAL-WORD DICTIONARY: a dictionary check would
misfire constantly — usernames, code identifiers (`hkl`, `tid`), chat
shorthand (`tbh`, `idk`), proper names, and invented project names are all
real, ordinary things people type that no dictionary contains. None of them
are IMPOSSIBLE letter combinations, though — they're built from ordinary,
legal sequences, just not existing "words". This module only ever flags a
sequence that could not occur in the language AT ALL, which is a much
narrower and safer claim than "not a known word".

HONEST LIMIT, stated up front: this is a seed rule set, not a complete
grammar of either language's phonotactics. It is expected to miss real
gibberish that happens to use only legal letter combinations (a wrong-layout
accident can, by chance, produce something not on any rule here). That is
the entire reason Tier 4 ships as Phase 1 (log-only, corrects nothing) for a
full week before any correction is ever applied — to find real misses from
real typing and expand these rules from evidence, not guesswork.
"""
import re

# ============================================================================
# Hebrew
# ============================================================================
# The one RELIABLE, deterministic rule (not a guess, not curated — an actual,
# absolute fact of Hebrew orthography): five letters have a special "final
# form" used ONLY as the last letter of a word — ך (kaf), ם (mem), ן (nun),
# ף (fey), ץ (tsadi) — versus their regular form כ, מ, נ, פ, צ used
# everywhere else. A final-form letter followed by ANY other Hebrew letter
# can never be a real Hebrew word — this is exactly the user's own example:
# "ןמ" opens with final-nun (ן) followed by another letter, which is
# impossible by definition. This single rule needs no curation and will
# never need "fixing" — it's a hard fact about the alphabet, not a heuristic.
HEBREW_FINAL_FORMS = "ךםןףץ"

# The mirror rule, added 2026-10-14 at the user's request: a Hebrew word never
# ENDS in the regular form of those letters — מ נ צ כ at the very end can't
# be a real word. Only checkable once the word is over, so keyboard_hook.py
# applies it at the space/Enter, not keystroke by keystroke. פ is left out on
# purpose: modern Hebrew writes a final "p" sound in loanwords with a regular
# פ (טיפ, אפ, סקייפ, שופ), so flagging it would hit real words.
HEBREW_NON_FINAL_NEVER_LAST = "מנצכ"


def hebrew_word_cannot_end_with(letter):
    """True if a Hebrew word ending in `letter` can't be a real word."""
    return letter in HEBREW_NON_FINAL_NEVER_LAST
HEBREW_LETTERS = "אבגדהוזחטיכלמנסעפצקרשתךםןףץ"

# Seed list only (see module docstring) — a handful of bigrams that are
# vanishingly rare-to-nonexistent in real Hebrew, unlike the final-form rule
# above these ARE a curated guess and are expected to need correction from
# real Phase 1 data, not treated as authoritative.
# Real finding, 2026-10-15: measured against every real Hebrew word in
# training_data.csv, most of the original seed pairs turned out to be in
# ordinary words — חכ/כח (מחכה, מחכים, שכחת, תשכח), סט/טס (היסטוריה,
# אינסטגרם, אסטרואידים, הסטארטאפ, and טס itself), and שז (שזיף, משזר; none in
# the data, but common words). With Phase 2 live, typing היסטוריה correctly
# could switch the keyboard to English at the end of the word. Removed; only
# the user's own example is left, with no real word found containing it.
HEBREW_SEED_IMPOSSIBLE_BIGRAMS = {
    "זש",  # the user's own example
}

# ============================================================================
# English
# ============================================================================
# Also a seed list, deliberately conservative and small — see the module
# docstring for why a dictionary approach was rejected. J, Q, V never double
# in real English words (unlike, say, "ll" or "ss"); Q is followed by U in
# every common English word (the rare loanword exceptions — qat, qi, qoph,
# proper nouns like Iraq/Qatar — are allowed explicitly below rather than
# risking a false flag on a real name).
ENGLISH_NEVER_DOUBLED = set("jqv")
ENGLISH_Q_NOT_FOLLOWED_BY_U_ALLOWED = {"qat", "qi", "qoph", "qadi", "qanun", "iraq", "qatar", "qatari", "faqs"}
# Real finding, 2026-10-11: user deliberately typed a batch of wrong-layout
# test words (rutv, vcghv, nxni, achea, cghv, ruao, capv, tjr, ...) and the
# ENGLISH side caught none of them — current rules are narrow enough to miss
# plenty of real gibberish that happens to use only legal English letter
# pairs (the honest limit stated in this module's own docstring). Checked
# each candidate bigram from those words by hand against common real English
# words before adding, same bar as the original seed list: "bk"/"dg"/etc.
# above were never corpus-verified either, just confirmed absent from
# ordinary vocabulary. Explicitly did NOT add bigrams that DO appear in real
# words from that same batch — nx (jinx, lynx), ua (usual, language), ao
# (chaos), ap (happy), jr (surnames, "Jr."), ru/ut (rule, cut), gh/ch/he/ea
# (night, chat, the, eat) — adding those would have reintroduced exactly the
# false-positive risk a dictionary approach was rejected for in the first
# place. vc/cg/hv/pv: no common English word was found containing any of
# them. xn/tj deliberately left out — lower confidence, not added without
# real evidence either way.
# Real finding, 2026-10-11 (same day, later): user's real typing produced
# "nv zv" uncaught — checked both by hand before deciding. "nv" is common in
# ordinary English (convenient, environment, invent, convene, canvas, unveil)
# and must NEVER be added. "zv" is genuinely rare-to-absent from ordinary
# vocabulary, so added; "nv" deliberately left out.
# Real finding, 2026-10-15: "dg" was in the original seed list but is in
# common words — edge, judge, bridge, ridge, badge. Typing "judge" correctly
# could switch the keyboard to Hebrew. Removed.
ENGLISH_SEED_IMPOSSIBLE_BIGRAMS = {
    "bk", "fq", "gq", "jq", "kq", "pq", "qb", "qc", "qd", "qf", "qg",
    "qh", "qj", "qk", "ql", "qm", "qn", "qp", "qr", "qs", "qt", "qv", "qw",
    "qx", "qy", "qz", "vq", "wq", "xq", "zq",
    "vc", "cg", "hv", "pv", "zv",
}

# Whole-word English rules (2026-10-15, user's request, after measuring that
# only ~5% of Hebrew words typed on the English layout were caught). These
# can only be judged once the word has ENDED, so keyboard_hook.py applies them
# at the space, like the Hebrew word-end rule. Each was scored against every
# real word in training_data.csv before going in. English has more exceptions
# than Hebrew's final-letter rule (chat slang, code, abbreviations), so a hit
# here only marks the word as suspect — it counts toward the second-word rule
# but never switches the keyboard on its own.
ENGLISH_VOWELS = set("aeiouy")
# Real words and common abbreviations that break a rule below anyway.
ENGLISH_WORD_END_OK = {
    # no vowel
    "tbh", "brb", "pls", "plz", "thx", "msg", "btw", "smh", "ngl", "lmk", "ttyl", "wtf", "hmm", "hmmm",
    "shh", "shhh", "brr", "nth", "html", "http", "https", "css", "sql", "xml", "pdf", "txt", "jpg",
    "png", "gif", "www", "cmd", "npm", "src", "pwd", "csv", "ppl", "srs", "cfg", "ctx", "btn", "tmp",
    "std", "str", "pkg", "cnt", "nxt", "dvd", "sms", "mkt", "sgt", "dr", "mr", "mrs", "st", "kg", "km",
    # ends in v
    "dev", "rev", "gov", "lav", "nav", "luv", "tv", "venv", "env", "div", "kv", "iv", "mv", "srv",
    "priv", "conv", "prev", "adv", "nov", "mov",
    # ends in j
    "raj", "haj", "hajj", "taj",
    # terminal and chat words the letter model would otherwise take for
    # Hebrew (/code-review, 2026-10-15: "npx" scored 1.96, over the line)
    "npx", "zsh", "ssh", "nvm", "pnpm", "rpm", "mph", "gps", "url", "urls", "afk", "cnn", "knn", "rgb",
}
COMMA_INSIDE = "comma inside"
_INTERJECTION_HH = re.compile(r"^[aous]?h+$")  # ahh, ohh, uhh, shh, hhh


def english_word_end_suspect(word, length, has_vowel, ending, comma_inside=False):
    """Whole-word English check, once the word has ended. `word` is the full
    word when it's short enough to have been kept (else None — exceptions
    are all short), `length` its letter count, `has_vowel` whether any of
    a/e/i/o/u/y appeared, `ending` its last two letters, `comma_inside`
    whether a comma sat between two letters (the Hebrew ת mid-word; 2026-10-15).
    Returns a short reason, or None. The comma rule is checked last: a word
    that breaks another rule too is reported by that rule, which needs no
    confirmation — COMMA_INSIDE alone can also be two English words with
    the space missing ("yes,but"), so the caller confirms it."""
    if word is not None and word in ENGLISH_WORD_END_OK:
        return None
    if length >= 3 and not has_vowel:
        return "no vowel"
    if ending.endswith("v"):
        return "ends in v"
    if ending.endswith("j"):
        return "ends in j"
    if ending.endswith("hh") and not (word and _INTERJECTION_HH.match(word)):
        return "ends in hh"
    if comma_inside:
        return COMMA_INSIDE
    return None


WORD_BOUNDARY_PATTERN = re.compile(r"[\s.,!?;:()\[\]{}\"'/\\@#$%^&*+=<>~`|\n\r\t]")


def is_word_boundary_char(ch):
    """True if ch ends the current word (whitespace or common punctuation) —
    used by IncrementalWordBuffer to know when to reset.
    """
    return bool(WORD_BOUNDARY_PATTERN.match(ch))


def _looks_impossible_hebrew(text):
    """Returns a short reason string if text cannot be a real Hebrew word,
    else None. See HEBREW_FINAL_FORMS/HEBREW_SEED_IMPOSSIBLE_BIGRAMS above.
    """
    for i, ch in enumerate(text[:-1]):
        if ch in HEBREW_FINAL_FORMS:
            return f"final-form letter {ch!r} not at the end of the word"
    for i in range(len(text) - 1):
        if text[i:i + 2] in HEBREW_SEED_IMPOSSIBLE_BIGRAMS:
            return f"impossible letter pair {text[i:i + 2]!r}"
    return None


def _looks_impossible_english(text):
    """Returns a short reason string if text cannot be a real English word,
    else None. See ENGLISH_NEVER_DOUBLED/ENGLISH_SEED_IMPOSSIBLE_BIGRAMS above.
    """
    lower = text.lower()
    if lower in ENGLISH_Q_NOT_FOLLOWED_BY_U_ALLOWED:
        return None
    for i in range(len(lower) - 1):
        a, b = lower[i], lower[i + 1]
        if a == b and a in ENGLISH_NEVER_DOUBLED:
            return f"letter {a!r} never doubles in English"
        if a + b in ENGLISH_SEED_IMPOSSIBLE_BIGRAMS:
            return f"impossible letter pair {a + b!r}"
    if "q" in lower:
        for i, ch in enumerate(lower[:-1]):
            if ch == "q" and lower[i + 1] != "u" and lower not in ENGLISH_Q_NOT_FOLLOWED_BY_U_ALLOWED:
                return "'q' not followed by 'u'"
    return None


def looks_impossible(text, language):
    """Returns a short reason string if text structurally cannot be a real
    word in `language` ("hebrew" or "english"), else None. Judges only
    letters — direction marks, digits and punctuation mixed in are ignored
    rather than treated as evidence either way (see DIRECTION_MARKS_PATTERN
    in rule_engine.py for the same principle applied to OCR text).
    """
    letters_only = "".join(ch for ch in text if ch.isalpha())
    if len(letters_only) < 2:
        return None  # nothing to judge a combination from
    if language == "hebrew":
        return _looks_impossible_hebrew(letters_only)
    if language == "english":
        return _looks_impossible_english(letters_only)
    return None


class IncrementalWordBuffer:
    """Accumulates the current in-progress word's characters, one at a time,
    exactly as they're typed — capped at MAX_LENGTH (the user's own "check
    the first N characters" design, lowered from 12 to 4 on 2026-10-08 to
    narrow the window further, then raised from 4 to 5 on 2026-10-14 to give
    Phase 2's auto-correction trigger (CORRECTION_TRIGGER_LENGTH in
    keyboard_hook.py) one letter of margin past the point Phase 1 could
    already detect at: past MAX_LENGTH, a word is left alone entirely for
    the rest of its length, which is also what naturally keeps long
    passwords/paths/identifiers out of consideration, without ever needing
    to recognize them as such). Resets itself the moment a word-boundary
    character arrives. Holds only the current word — never a history of
    anything typed before it.
    """
    MAX_LENGTH = 5

    def __init__(self):
        """Starts empty — no word in progress, nothing capped yet."""
        self._chars = []
        self.capped = False

    def push(self, ch):
        """Adds one typed character. Returns False (and stops accumulating
        further characters) once MAX_LENGTH is reached or ch is a boundary,
        which also clears the buffer for boundary characters — the caller
        should stop checking this word once this returns False.
        """
        if is_word_boundary_char(ch):
            self.reset()
            return False
        if self.capped:
            return False
        self._chars.append(ch)
        if len(self._chars) >= self.MAX_LENGTH:
            self.capped = True
        return True

    def reset(self):
        """Clears the buffer — called on a word boundary, or by the caller
        when focus moves to a different control (a new word starts fresh).
        """
        self._chars = []
        self.capped = False

    def text(self):
        """The current in-progress word, exactly as typed so far."""
        return "".join(self._chars)
