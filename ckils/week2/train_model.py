import csv
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

DATA_FILE = "training_data.csv"
MODEL_FILE = "language_model.joblib"


def load_data():
    texts, labels = [], []
    with open(DATA_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            texts.append(row["text"])
            labels.append(row["label"])
    return texts, labels


def main():
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
