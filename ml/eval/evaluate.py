"""
SeñasCL - Model Evaluation Script
Evaluates model accuracy with confusion matrix and per-sign metrics.

Usage:
    python evaluate.py --model model.tflite --test-data test.json

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
    print("Install: pip install numpy scikit-learn")
    sys.exit(1)


def evaluate(model_path: str, test_data_path: str):
    # TODO: Load model and run inference on test data
    # Metrics to report:
    # - Overall accuracy
    # - Per-sign precision, recall, F1
    # - Confusion matrix
    # - Accuracy by condition (lighting, handedness)
    # - Latency per inference

    print(f"Model: {model_path}")
    print(f"Test data: {test_data_path}")
    print("TODO: Implement evaluation pipeline")
    print()
    print("Expected metrics:")
    print("  - Overall accuracy")
    print("  - Per-sign precision/recall/F1")
    print("  - Confusion matrix")
    print("  - Latency (ms per frame)")


def main():
    parser = argparse.ArgumentParser(description="Evaluate LSCh sign classifier")
    parser.add_argument("--model", required=True, help="Path to .tflite model")
    parser.add_argument("--test-data", required=True, help="Path to test dataset JSON")
    args = parser.parse_args()

    evaluate(args.model, args.test_data)


if __name__ == "__main__":
    main()
