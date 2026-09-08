"""
SeñasCL - TensorFlow/Keras Training + TFLite Export
Retrains the landmark classifier with TensorFlow for TFLite export.

Usage:
    python train_model_keras.py --landmarks ../datasets/landmarks_dataset.json

Requires:
    pip install tensorflow numpy scikit-learn
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    print("Error: pip install numpy")
    sys.exit(1)


def load_landmarks(dataset_path: str):
    with open(dataset_path) as f:
        data = json.load(f)

    X, y = [], []
    for sample in data:
        if not sample.get("hands"):
            continue
        hand = sample["hands"][0]
        features = []
        for point in hand:
            features.extend([point["x"], point["y"], point["z"]])
        xs = [p["x"] for p in hand]
        ys = [p["y"] for p in hand]
        features.extend([np.mean(xs), np.mean(ys), np.std(xs), np.std(ys)])
        X.append(features)
        y.append(sample["label"])

    return np.array(X, dtype=np.float32), np.array(y)


def train_and_export(dataset_path: str, output_path: str):
    try:
        import tensorflow as tf
        from sklearn.preprocessing import LabelEncoder
        from sklearn.model_selection import train_test_split
    except ImportError:
        print("Error: pip install tensorflow scikit-learn")
        sys.exit(1)

    X, y = load_landmarks(dataset_path)
    print(f"Loaded {len(X)} samples, {X.shape[1]} features")

    le = LabelEncoder()
    y_encoded = le.fit_transform(y)
    num_classes = len(le.classes_)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded
    )

    # One-hot encode
    y_train_oh = tf.keras.utils.to_categorical(y_train, num_classes)
    y_test_oh = tf.keras.utils.to_categorical(y_test, num_classes)

    # Build model
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(X.shape[1],)),
        tf.keras.layers.Dense(128, activation="relu"),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(64, activation="relu"),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(32, activation="relu"),
        tf.keras.layers.Dense(num_classes, activation="softmax"),
    ])

    model.compile(
        optimizer="adam",
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )

    model.summary()

    # Train
    history = model.fit(
        X_train, y_train_oh,
        validation_data=(X_test, y_test_oh),
        epochs=100,
        batch_size=32,
        callbacks=[
            tf.keras.callbacks.EarlyStopping(patience=10, restore_best_weights=True),
            tf.keras.callbacks.ReduceLROnPlateau(factor=0.5, patience=5),
        ],
    )

    # Evaluate
    loss, accuracy = model.evaluate(X_test, y_test_oh)
    print(f"\nTest accuracy: {accuracy:.4f}")

    # Convert to TFLite
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_types = [tf.float16]
    tflite_model = converter.convert()

    # Save
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(tflite_model)

    size_mb = len(tflite_model) / (1024 * 1024)
    print(f"TFLite model saved to {output_path} ({size_mb:.2f} MB)")

    # Save class mapping
    class_map = {i: cls for i, cls in enumerate(le.classes_)}
    meta_path = Path(output_path).with_suffix(".json")
    with open(meta_path, "w") as f:
        json.dump({
            "num_classes": num_classes,
            "classes": class_map,
            "feature_size": int(X.shape[1]),
            "accuracy": float(accuracy),
        }, f, indent=2)

    print(f"Class mapping saved to {meta_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--landmarks", required=True, help="Path to landmarks JSON")
    parser.add_argument("--output", default=str(Path(__file__).parent / "models" / "lsch_classifier.tflite"))
    args = parser.parse_args()
    train_and_export(args.landmarks, args.output)


if __name__ == "__main__":
    main()
