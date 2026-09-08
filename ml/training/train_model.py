"""
SeñasCL - Model Training Script
Trains a sign classifier from captured landmarks.

Usage:
    python train_model.py --dataset dataset.json --output model.tflite

Requires:
    pip install tensorflow scikit-learn numpy
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    print("Install dependencies: pip install numpy tensorflow scikit-learn")
    sys.exit(1)


def load_dataset(dataset_path: str):
    with open(dataset_path) as f:
        data = json.load(f)

    X = []
    y = []
    labels = set()

    for sample in data:
        if not sample.get("hands"):
            continue

        # Use first hand landmarks (21 points * 3 coords = 63 features)
        hand = sample["hands"][0]
        features = []
        for point in hand:
            features.extend([point["x"], point["y"], point["z"]])

        X.append(features)
        y.append(sample["label"])
        labels.add(sample["label"])

    return np.array(X), np.array(y), sorted(labels)


def train_model(X, y, labels):
    # TODO: Implement actual training with TensorFlow
    # Placeholder: print dataset stats
    print(f"Dataset: {len(X)} samples, {len(labels)} classes")
    print(f"Classes: {labels}")
    print(f"Feature shape: {X.shape}")

    # Simple placeholder model info
    model_info = {
        "num_classes": len(labels),
        "feature_size": X.shape[1] if len(X.shape) > 1 else 0,
        "num_samples": len(X),
        "labels": labels,
    }
    return model_info


def export_to_tflite(model_info, output_path):
    # TODO: Create actual TFLite model
    # For now, save model metadata
    meta_path = Path(output_path).with_suffix(".json")
    with open(meta_path, "w") as f:
        json.dump(model_info, f, indent=2)
    print(f"Model metadata saved to {meta_path}")
    print(f"TODO: Implement TFLite export to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Train LSCh sign classifier")
    parser.add_argument("--dataset", required=True, help="Path to dataset JSON")
    parser.add_argument("--output", default="model.tflite", help="Output model path")
    parser.add_argument("--epochs", type=int, default=50, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    args = parser.parse_args()

    X, y, labels = load_dataset(args.dataset)
    if len(X) == 0:
        print("Error: No valid samples found in dataset")
        sys.exit(1)

    model_info = train_model(X, y, labels)
    export_to_tflite(model_info, args.output)


if __name__ == "__main__":
    main()
