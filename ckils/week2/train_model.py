"""
Trains language_model.joblib — the classifier predict_language.py loads and
rule_engine.py's Tier 3 actually runs on. Reads real labeled examples from
training_data.csv (captured from real usage, kept local-only, never
committed — see .gitignore) and fits a TF-IDF character n-gram + logistic
regression model, robust to OCR noise since it works on character shapes,
not whole words. Deliberately NOT run automatically or on a schedule: the
project's policy is to only retrain after a human reviews the newly
captured data first (see review_decisions.py) — blindly retraining on
whatever was captured would just teach the model to repeat its own mistakes.
"""
import csv
import sys

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

# Overridable as `python train_model.py <data.csv> <model.joblib>`, so a new
# model can be trained next to the one CKILS runs without touching it.
DATA_FILE = sys.argv[1] if len(sys.argv) > 1 else "training_data.csv"
MODEL_FILE = sys.argv[2] if len(sys.argv) > 2 else "language_model.joblib"


def load_data():
    """Reads DATA_FILE's labeled rows into two parallel lists: texts and
    their corresponding "hebrew"/"english" labels.
    """
    texts, labels = [], []
    with open(DATA_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            texts.append(row["text"])
            labels.append(row["label"])
    return texts, labels


def main():
    """Loads the labeled data, splits it into train/test sets, fits the
    vectorizer + classifier, prints a held-out accuracy report, and saves
    the trained bundle to MODEL_FILE.
    """
    texts, labels = load_data()
    print(f"Loaded {len(texts)} labeled examples.")

    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=0, stratify=labels
    )

    # char_wb = character n-grams, respecting word boundaries — robust to OCR noise
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3))
    X_train_vec = vectorizer.fit_transform(X_train)
    X_test_vec = vectorizer.transform(X_test)

    clf = LogisticRegression(max_iter=1000)
    clf.fit(X_train_vec, y_train)

    preds = clf.predict(X_test_vec)
    print(classification_report(y_test, preds, zero_division=0))

    joblib.dump({"vectorizer": vectorizer, "clf": clf}, MODEL_FILE)
    print(f"Saved trained model to {MODEL_FILE}")


if __name__ == "__main__":
    main()
