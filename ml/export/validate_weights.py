"""
SeñasCL - Weight Validation Script
Validates that exported weights work correctly with the same inference logic
used in the runtime (TypeScript GRU).

This script replicates the TypeScript forward pass in Python to confirm
that the exported weights produce valid predictions before loading them
in the browser.

Usage:
    python validate_weights.py --weights ml/models/temporal_weights.json
    python validate_weights.py --weights ml/models/temporal_weights.json --test-clips ml/datasets/clips/
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def sigmoid(x):
    """Sigmoid matching TypeScript implementation."""
    return 1.0 / (1.0 + np.exp(-np.clip(x, -10, 10)))


def tanh(x):
    """Tanh matching TypeScript implementation."""
    return np.tanh(x)


def gru_forward(weights, sequence, hidden_size):
    """
    GRU forward pass matching TypeScript implementation exactly.

    This MUST produce the same output as TemporalModel.ts predict().
    """
    Wz = np.array(weights["Wz"])
    bz = np.array(weights["bz"])
    Wr = np.array(weights["Wr"])
    br = np.array(weights["br"])
    Wh = np.array(weights["Wh"])
    bh = np.array(weights["bh"])

    h = np.zeros(hidden_size)

    for t in range(len(sequence)):
        x = sequence[t]
        combined = np.concatenate([h, x])

        # Update gate
        z = sigmoid(Wz @ combined + bz)

        # Reset gate
        r = sigmoid(Wr @ combined + br)

        # Candidate
        r_h = np.concatenate([r * h, x])
        h_hat = tanh(Wh @ r_h + bh)

        # New hidden
        h = (1 - z) * h_hat + z * h

    return h


def classifier_forward(classifier_weights, h):
    """Classifier forward pass matching TypeScript."""
    W = np.array(classifier_weights["W"])
    b = np.array(classifier_weights["b"])
    logits = W @ h + b
    return logits


def softmax(logits):
    """Softmax matching TypeScript."""
    exp_logits = np.exp(logits - np.max(logits))
    return exp_logits / exp_logits.sum()


def validate_weights(weights_path):
    """Validate exported weights."""
    print("=" * 60)
    print("VALIDACIÓN DE PESOS - SeñasCL")
    print("=" * 60)

    # Load weights
    print(f"\nCargando pesos: {weights_path}")
    with open(weights_path) as f:
        data = json.load(f)

    # Check structure
    if "config" not in data:
        print("ERROR: Falta 'config' en el archivo")
        return False

    if "weights" not in data:
        print("ERROR: Falta 'weights' en el archivo")
        return False

    if "labels" not in data:
        print("ERROR: Falta 'labels' en el archivo")
        return False

    config = data["config"]
    weights = data["weights"]
    labels = data["labels"]

    print(f"  Labels: {len(labels)} -> {labels}")
    print(f"  Hidden size: {config.get('hidden_size', 'unknown')}")
    print(f"  Input size: {config.get('input_size', 'unknown')}")

    # Validate weight shapes
    print("\nValidando formas de pesos...")
    gru_weights = weights.get("gru", {})
    classifier_weights = weights.get("classifier", {})

    required_gru_keys = ["Wz", "bz", "Wr", "br", "Wh", "bh"]
    for key in required_gru_keys:
        if key not in gru_weights:
            print(f"  ERROR: Falta '{key}' en pesos GRU")
            return False
        shape = np.array(gru_weights[key]).shape
        print(f"  GRU.{key}: {shape}")

    if "W" not in classifier_weights:
        print("  ERROR: Falta 'W' en pesos del clasificador")
        return False

    if "b" not in classifier_weights:
        print("  ERROR: Falta 'b' en pesos del clasificador")
        return False

    W_shape = np.array(classifier_weights["W"]).shape
    b_shape = np.array(classifier_weights["b"]).shape
    print(f"  Classifier.W: {W_shape}")
    print(f"  Classifier.b: {b_shape}")

    # Verify dimensions match
    hidden_size = config.get("hidden_size", 64)
    num_classes = len(labels)
    input_size = config.get("input_size", 126)

    if W_shape != (num_classes, hidden_size):
        print(f"  ERROR: Classifier.W shape {W_shape} != expected ({num_classes}, {hidden_size})")
        return False

    if b_shape != (num_classes,):
        print(f"  ERROR: Classifier.b shape {b_shape} != expected ({num_classes},)")
        return False

    if np.array(gru_weights["bz"]).shape != (hidden_size,):
        print(f"  ERROR: GRU.bz shape != ({hidden_size},)")
        return False

    print("  ✓ Formas de pesos correctas")

    # Run inference on a synthetic test sequence
    print("\nEjecutando inferencia de prueba...")
    seq_length = config.get("seq_length", 30)

    # Create a synthetic sequence (simulated hand movement)
    test_sequence = np.random.randn(seq_length, input_size) * 0.1

    # Run GRU forward
    h = gru_forward(gru_weights, test_sequence, hidden_size)

    # Run classifier
    logits = classifier_forward(classifier_weights, h)
    probs = softmax(logits)

    predicted = np.argmax(probs)
    confidence = probs[predicted]

    print(f"  Predicción: {labels[predicted]} (confianza: {confidence:.3f})")
    print(f"  Probabilidades por clase:")
    for i, label in enumerate(labels):
        bar = "█" * int(probs[i] * 30)
        print(f"    {label:<12} {probs[i]:.3f} {bar}")

    # Check that output is valid (not NaN, not all same)
    if np.any(np.isnan(probs)):
        print("  ERROR: Probabilidades contienen NaN")
        return False

    if np.all(probs == probs[0]):
        print("  ERROR: Todas las probabilidades son iguales (pesos degenerados)")
        return False

    print("  ✓ Inferencia produce resultados válidos")

    # Print metrics if available
    if "metrics" in data:
        print(f"\nMétricas de entrenamiento:")
        metrics = data["metrics"]
        print(f"  Exactitud de validación: {metrics.get('best_val_accuracy', 'N/A'):.1%}")
        print(f"  Épocas entrenadas: {metrics.get('epochs_trained', 'N/A')}")
        print(f"  Tiempo de entrenamiento: {metrics.get('training_time_seconds', 'N/A'):.1f}s")

    print("\n" + "=" * 60)
    print("✓ VALIDACIÓN EXITOSA - Pesos listos para usar en el runtime")
    print("=" * 60)

    return True


def test_with_clips(weights_path, clips_dir):
    """Test inference on actual clips if available."""
    clips_dir = Path(clips_dir)

    if not clips_dir.exists():
        print(f"\nDirectorio de clips no encontrado: {clips_dir}")
        return

    clip_files = list(clips_dir.glob("*.json"))
    if not clip_files:
        print("\nNo se encontraron clips para probar")
        return

    print(f"\nProbando con {len(clip_files)} clips...")

    with open(weights_path) as f:
        data = json.load(f)

    config = data["config"]
    weights = data["weights"]
    labels = data["labels"]
    hidden_size = config["hidden_size"]
    input_size = config["input_size"]
    seq_length = config["seq_length"]

    correct = 0
    total = 0

    for clip_path in clip_files[:20]:  # Test first 20 clips
        try:
            with open(clip_path) as f:
                clip = json.load(f)

            true_label = clip["label"]
            frames = clip.get("frames", [])

            if not frames:
                continue

            # Extract features (same as training)
            sequence = []
            for frame in frames:
                hands = frame.get("hands", [])
                if hands:
                    hand = hands[0]
                    features = []
                    for lm in hand[:21]:
                        features.extend([lm["x"], lm["y"], lm["z"]])
                    while len(features) < 63:
                        features.extend([0, 0, 0])
                    if len(hands) > 1:
                        hand2 = hands[1]
                        for lm in hand2[:21]:
                            features.extend([lm["x"], lm["y"], lm["z"]])
                        while len(features) < 126:
                            features.extend([0, 0, 0])
                    else:
                        features.extend([0] * 63)
                    sequence.append(features[:126])

            if not sequence:
                continue

            # Normalize landmarks (relative to wrist)
            normalized = []
            for frame in sequence:
                arr = np.array(frame).reshape(-1, 3)
                wrist = arr[0]
                normalized.append((arr - wrist).flatten())
            sequence = normalized

            # Pad/truncate to target length
            if len(sequence) >= seq_length:
                indices = np.linspace(0, len(sequence) - 1, seq_length, dtype=int)
                sequence = [sequence[i] for i in indices]
            else:
                while len(sequence) < seq_length:
                    sequence.append(sequence[-1] if sequence else [0] * input_size)

            seq_array = np.array(sequence)

            # Inference
            h = gru_forward(weights["gru"], seq_array, hidden_size)
            logits = classifier_forward(weights["classifier"], h)
            probs = softmax(logits)
            predicted_label = labels[np.argmax(probs)]
            confidence = probs[np.argmax(probs)]

            is_correct = predicted_label == true_label
            if is_correct:
                correct += 1
            total += 1

            status = "✓" if is_correct else "✗"
            print(f"  {status} {clip_path.name:<25} real={true_label:<12} "
                  f"pred={predicted_label:<12} conf={confidence:.2f}")

        except Exception as e:
            print(f"  Error procesando {clip_path.name}: {e}")

    if total > 0:
        accuracy = correct / total
        print(f"\nExactitud en clips: {correct}/{total} = {accuracy:.1%}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate exported temporal model weights"
    )
    parser.add_argument("--weights", required=True, help="Path to weights JSON")
    parser.add_argument("--test-clips", help="Optional: test with actual clips")
    args = parser.parse_args()

    success = validate_weights(args.weights)

    if args.test_clips:
        test_with_clips(args.weights, args.test_clips)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
