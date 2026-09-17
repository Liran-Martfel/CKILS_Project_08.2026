"""
The AI classifier itself. Loads the trained TF-IDF + logistic regression
model (language_model.joblib, trained by train_model.py from real captured
usage) and predicts whether a given piece of text is Hebrew or English —
this is what Tier 3 in rule_engine.py calls once it has real text to
classify (from accessible text, OCR, or a Google Docs title). Also runnable
directly for a quick manual check against arbitrary typed-in text.
"""
import os
import joblib

# A bare relative filename only worked by coincidence when running "python
# rule_engine.py" from inside this folder. Packaged into the standalone exe,
# bundled files extract elsewhere - this resolves correctly either way, same
# pattern already used in ocr_reader.py for tessdata (verified working there).
MODEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "language_model.joblib")


def load_model():
    """Loads the trained model bundle from disk and returns its (vectorizer,
    classifier) pair, ready to transform and classify text.
    """
    bundle = joblib.load(MODEL_FILE)
    return bundle["vectorizer"], bundle["clf"]


def predict_language(text, vectorizer=None, clf=None):
    """Classifies text as "hebrew" or "english". Loads the model itself if
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
