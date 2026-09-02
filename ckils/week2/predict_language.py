import os
import joblib

# A bare relative filename only worked by coincidence when running "python
# rule_engine.py" from inside this folder. Packaged into the standalone exe,
# bundled files extract elsewhere - this resolves correctly either way, same
# pattern already used in ocr_reader.py for tessdata (verified working there).
MODEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "language_model.joblib")


def load_model():
    bundle = joblib.load(MODEL_FILE)
    return bundle["vectorizer"], bundle["clf"]


def predict_language(text, vectorizer=None, clf=None):
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
