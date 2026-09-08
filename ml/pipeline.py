"""
SeñasCL - Full ML Pipeline
Downloads Roboflow LSCh dataset, extracts landmarks, trains model, exports TFLite.

Usage:
    python pipeline.py --api-key YOUR_ROBOFLOW_KEY --action all
    python pipeline.py --action download
    python pipeline.py --action extract
    python pipeline.py --action train
    python pipeline.py --action export

Requires:
    pip install roboflow mediapipe opencv-python tensorflow numpy scikit-learn
"""

import argparse
import json
import os
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent
DATASETS_DIR = ML_DIR / "datasets"
MODELS_DIR = ML_DIR / "models"
EXPORT_DIR = ML_DIR / "export"

# Roboflow dataset: "lengua-de-senas-chilena" (2919 images, alphabet + basic signs)
ROBOFLOW_WORKSPACE = "lengua-de-senas-chilena-j3um3"
ROBOFLOW_PROJECT = "lengua-de-senas-chilena"
ROBOFLOW_VERSION = 7


def download_dataset(api_key: str):
    """Download LSCh dataset from Roboflow."""
    try:
        from roboflow import Roboflow
    except ImportError:
        print("Error: pip install roboflow")
        sys.exit(1)

    print(f"Downloading dataset from Roboflow ({ROBOFLOW_WORKSPACE}/{ROBOFLOW_PROJECT})...")
    rf = Roboflow(api_key=api_key)
    project = rf.workspace(ROBOFLOW_WORKSPACE).project(ROBOFLOW_PROJECT)
    version = project.version(ROBOFLOW_VERSION)
    dataset = version.download("yolov8", location=str(DATASETS_DIR / "roboflow-lsch"))
    print(f"Dataset downloaded to: {dataset.location}")
    return dataset.location


def extract_landmarks_from_dataset(dataset_path: str):
    """Extract hand/face landmarks from dataset images."""
    try:
        import mediapipe as mp
        import cv2
        import numpy as np
    except ImportError:
        print("Error: pip install mediapipe opencv-python numpy")
        sys.exit(1)

    dataset_dir = Path(dataset_path)
    samples = []

    mp_hands = mp.solutions.hands
    mp_face = mp.solutions.face_mesh

    print("Extracting landmarks from dataset images...")

    with mp_hands.Hands(
        static_image_mode=True,
        max_num_hands=2,
        min_detection_confidence=0.5,
    ) as hands, mp_face.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        min_detection_confidence=0.5,
    ) as face_mesh:

        # Process train/valid/test splits
        for split in ["train", "valid", "test"]:
            split_dir = dataset_dir / split
            if not split_dir.exists():
                continue

            # Look for YOLO format labels
            for label_file in split_dir.glob("*.txt"):
                if label_file.name == "classes.txt":
                    continue

                image_path = label_file.with_suffix(".jpg")
                if not image_path.exists():
                    image_path = label_file.with_suffix(".png")
                if not image_path.exists():
                    continue

                # Read YOLO label
                with open(label_file) as f:
                    lines = f.readlines()

                if not lines:
                    continue

                # Get class label from first annotation
                class_id = int(lines[0].split()[0])

                # Read class names
                classes_file = split_dir / "classes.txt"
                if classes_file.exists():
                    with open(classes_file) as f:
                        class_names = [line.strip() for line in f.readlines()]
                    label = class_names[class_id] if class_id < len(class_names) else str(class_id)
                else:
                    label = str(class_id)

                # Extract landmarks
                image = cv2.imread(str(image_path))
                if image is None:
                    continue

                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                hand_results = hands.process(rgb)
                face_results = face_mesh.process(rgb)

                sample = {
                    "image": str(image_path),
                    "label": label,
                    "split": split,
                    "hands": [],
                    "face": None,
                }

                if hand_results.multi_hand_landmarks:
                    for hand_lms in hand_results.multi_hand_landmarks:
                        hand_data = [
                            {"x": lm.x, "y": lm.y, "z": lm.z}
                            for lm in hand_lms.landmark
                        ]
                        sample["hands"].append(hand_data)

                if face_results.multi_face_landmarks:
                    face_lms = face_results.multi_face_landmarks[0]
                    sample["face"] = [
                        {"x": lm.x, "y": lm.y, "z": lm.z}
                        for lm in face_lms.landmark[:468]
                    ]

                if sample["hands"]:
                    samples.append(sample)

                if len(samples) % 100 == 0:
                    print(f"  Processed {len(samples)} samples...")

    # Save landmarks dataset
    output_path = DATASETS_DIR / "landmarks_dataset.json"
    with open(output_path, "w") as f:
        json.dump(samples, f, indent=2)

    print(f"Extracted {len(samples)} samples with landmarks to {output_path}")

    # Print class distribution
    labels = {}
    for s in samples:
        labels[s["label"]] = labels.get(s["label"], 0) + 1
    print(f"Classes: {len(labels)}")
    for label, count in sorted(labels.items()):
        print(f"  {label}: {count}")

    return output_path


def train_model(dataset_path: str, output_path: str = None):
    """Train a sign classifier from landmarks."""
    try:
        import numpy as np
        from sklearn.neural_network import MLPClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report, confusion_matrix
        from sklearn.preprocessing import LabelEncoder
        import joblib
    except ImportError:
        print("Error: pip install scikit-learn joblib")
        sys.exit(1)

    with open(dataset_path) as f:
        data = json.load(f)

    print(f"Training model from {len(data)} samples...")

    X = []
    y = []

    for sample in data:
        if not sample.get("hands"):
            continue

        # Use first hand: 21 landmarks * 3 coords = 63 features
        hand = sample["hands"][0]
        features = []
        for point in hand:
            features.extend([point["x"], point["y"], point["z"]])

        # Add hand centroid as additional features
        xs = [p["x"] for p in hand]
        ys = [p["y"] for p in hand]
        features.extend([np.mean(xs), np.mean(ys)])
        features.extend([np.std(xs), np.std(ys)])

        X.append(features)
        y.append(sample["label"])

    X = np.array(X)
    y = np.array(y)

    print(f"Features shape: {X.shape}")
    print(f"Labels: {len(set(y))} classes")

    # Encode labels
    le = LabelEncoder()
    y_encoded = le.fit_transform(y)

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded
    )

    # Train MLP classifier
    clf = MLPClassifier(
        hidden_layer_sizes=(128, 64, 32),
        activation="relu",
        max_iter=500,
        random_state=42,
        early_stopping=True,
        validation_fraction=0.1,
    )

    clf.fit(X_train, y_train)

    # Evaluate
    y_pred = clf.predict(X_test)
    accuracy = np.mean(y_pred == y_test)
    print(f"\nAccuracy: {accuracy:.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=le.classes_))

    # Save model and encoder
    if output_path is None:
        output_path = str(MODELS_DIR / "sign_classifier.joblib")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, output_path)
    joblib.dump(le, output_path.replace(".joblib", "_encoder.joblib"))

    print(f"Model saved to {output_path}")
    return output_path


def export_to_tflite(model_path: str, output_path: str = None):
    """Export trained model to TFLite format."""
    try:
        import joblib
        import numpy as np
    except ImportError:
        print("Error: pip install joblib numpy")
        sys.exit(1)

    clf = joblib.load(model_path)
    le = joblib.load(model_path.replace(".joblib", "_encoder.joblib"))

    if output_path is None:
        output_path = str(EXPORT_DIR / "sign_classifier.tflite")

    print("Exporting to TFLite...")
    print(f"Note: For full TFLite export, retrain with TensorFlow/Keras.")
    print(f"Current model is scikit-learn MLPClassifier.")
    print(f"\nTo convert, use the Keras retraining script:")
    print(f"  python train_model_keras.py --landmarks {model_path}")

    # For now, save metadata
    metadata = {
        "num_classes": len(le.classes_),
        "classes": list(le.classes_),
        "feature_size": clf.coefs_[0].shape[0],
        "model_type": "MLPClassifier",
        "note": "Convert to TFLite using train_model_keras.py",
    }

    meta_path = Path(output_path).with_suffix(".json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Metadata saved to {meta_path}")
    return meta_path


def main():
    parser = argparse.ArgumentParser(description="SeñasCL ML Pipeline")
    parser.add_argument("--api-key", help="Roboflow API key")
    parser.add_argument(
        "--action",
        choices=["all", "download", "extract", "train", "export"],
        default="all",
        help="Pipeline action to run",
    )
    parser.add_argument("--dataset-path", help="Path to landmarks dataset JSON")
    args = parser.parse_args()

    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    if args.action in ("all", "download"):
        if not args.api_key:
            print("Error: --api-key required for download")
            sys.exit(1)
        dataset_path = download_dataset(args.api_key)
    else:
        dataset_path = str(DATASETS_DIR / "roboflow-lsch")

    if args.action in ("all", "extract"):
        landmarks_path = extract_landmarks_from_dataset(dataset_path)
    else:
        landmarks_path = args.dataset_path or str(DATASETS_DIR / "landmarks_dataset.json")

    if args.action in ("all", "train"):
        model_path = train_model(landmarks_path)
    else:
        model_path = str(MODELS_DIR / "sign_classifier.joblib")

    if args.action in ("all", "export"):
        export_to_tflite(model_path)

    print("\nPipeline complete!")


if __name__ == "__main__":
    main()
