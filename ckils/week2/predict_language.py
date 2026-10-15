"""
The AI classifier itself. Loads the trained TF-IDF + logistic regression
model (language_model.joblib, trained by train_model.py from real captured
usage) and predicts whether a given piece of text is Hebrew or English —
this is what Tier 3 in rule_engine.py calls once it has real text to
classify (from accessible text, OCR, or a Google Docs title). Also runnable
directly for a quick manual check against arbitrary typed-in text.
"""
import os
import sys

import joblib

# A bare relative filename only worked by coincidence when running "python
# rule_engine.py" from inside this folder. Packaged into the standalone exe,
# bundled files extract elsewhere - this resolves correctly either way, same
# pattern already used in ocr_reader.py for tessdata (verified working there).
_HERE = os.path.dirname(os.path.abspath(__file__))
# 2026-10-15: retrained on the 228 originals plus 700 real texts the user
# hand-labeled, with a third answer, "noise" (not real text). Measured before
# the swap: wrong switches on real text 33 -> 23, acting on junk 65 -> 53,
# unchanged (99.1%, 0 wrong) on the original 228. Costs fewer reads acted on
# (89% -> 81%). The previous model is kept, untouched, as OLD_MODEL_FILE.
MODEL_FILE = os.path.join(_HERE, "language_model_v2.joblib")
OLD_MODEL_FILE = os.path.join(_HERE, "language_model.joblib")
# The user's rollback switch: while this file exists next to CKILS.exe, the
# previous model is used instead. Checked on every read, so it takes effect
# live — no rebuild, no restart.
USE_OLD_MODEL_FILENAME = "use_old_language_model.on"


def _persistent_dir():
    """The exe's own folder when packaged (never the temporary extraction
    folder), or this script's folder from source — same rule as skip_logger."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return _HERE


def active_model_file():
    """The model to use right now: the old one while the rollback file
    exists, otherwise the current one."""
    if os.path.exists(os.path.join(_persistent_dir(), USE_OLD_MODEL_FILENAME)):
        return OLD_MODEL_FILE
    return MODEL_FILE


_loaded = {}  # model file -> (vectorizer, clf), so each model is read from disk once


def load_model():
    """Returns the active model's (vectorizer, classifier) pair, ready to
    transform and classify text.
    """
    path = active_model_file()
    if path not in _loaded:
        bundle = joblib.load(path)
        _loaded[path] = (bundle["vectorizer"], bundle["clf"])
    return _loaded[path]


def predict_language(text, vectorizer=None, clf=None):
    """Classifies text as "hebrew", "english", or (current model only)
    "noise" — not real text, which callers must treat as no decision. Loads the model itself if
    vectorizer/clf aren't already provided (callers that classify repeatedly,
    like rule_engine.py, load once and pass them in to avoid reloading the
    model from disk on every call). Returns (predicted_label, {label:
    probability} for every class), so a caller can apply its own confidence
    threshold instead of trusting the raw prediction blindly.
    """
    if vectorizer is None or clf is None:
        vectorizer, clf = load_model()
    vec = vectorizer.transform([text])
    label = clf.predict(vec)[0]
    proba = dict(zip(clf.classes_, clf.predict_proba(vec)[0]))
    return label, proba


if __name__ == "__main__":
    text = input("Type or paste some text: ")
    label, proba = predict_language(text)
    print(f"Predicted: {label}  ({proba})")
