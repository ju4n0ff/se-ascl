"""
SeñasCL - Temporal Model Training
Trains a GRU-based model for dynamic sign recognition.

Architecture MUST match the runtime TypeScript implementation exactly:
- GRU(input_size, hidden_size) with specific gate structure
- Linear(hidden_size, num_classes) classifier
- Input: flattened landmarks per frame [x, y, z] for 2 hands (126 features)
- Output: class probabilities over dynamic sign vocabulary

Usage:
    python train_temporal.py --dataset-dir ml/datasets/clips/ --output ml/models/temporal_weights.json
    python train_temporal.py --dataset-dir ml/datasets/clips/ --output ml/models/temporal_weights.json --epochs 100

Requires:
    pip install numpy scikit-learn
"""

import argparse
import json
import sys
import time
from pathlib import Path
from collections import defaultdict
import random

try:
    import numpy as np
except ImportError:
    print("Install dependencies: pip install numpy scikit-learn")
    sys.exit(1)


# ============================================================
# ARCHITECTURE CONFIGURATION
# These values MUST match the TypeScript runtime exactly.
# See: apps/web-demo/src/recognition/TemporalModel.ts
# ============================================================
CONFIG = {
    "input_size": 126,      # 21 landmarks * 3 coords * 2 hands
    "hidden_size": 64,      # GRU hidden state
    "seq_length": 30,       # Normalized sequence length
    "learning_rate": 0.001,
    "epochs": 100,
    "batch_size": 16,
    "train_split": 0.8,     # 80% train, 20% validation
    "seed": 42,
}


# ============================================================
# GRU Implementation (must match TypeScript forward pass)
# ============================================================

def sigmoid(x):
    """Sigmoid activation with numerical stability."""
    return 1.0 / (1.0 + np.exp(-np.clip(x, -10, 10)))


def sigmoid_derivative(x):
    """Derivative of sigmoid for backprop."""
    s = sigmoid(x)
    return s * (1 - s)


class GRUCell:
    """
    GRU Cell matching TypeScript implementation exactly.

    Gate equations (from TypeScript):
        z = sigmoid(Wz @ [h_prev, x] + bz)  # update gate
        r = sigmoid(Wr @ [h_prev, x] + br)  # reset gate
        h_hat = tanh(Wh @ [r * h_prev, x] + bh)  # candidate
        h = (1 - z) * h_hat + z * h_prev  # new hidden
    """

    def __init__(self, input_size, hidden_size):
        self.input_size = input_size
        self.hidden_size = hidden_size
        combined = input_size + hidden_size

        # Xavier initialization for better convergence
        scale_z = np.sqrt(2.0 / combined)
        scale_r = np.sqrt(2.0 / combined)
        scale_h = np.sqrt(2.0 / (hidden_size + input_size))

        # Weights
        self.Wz = np.random.randn(hidden_size, combined) * scale_z
        self.bz = np.zeros(hidden_size)
        self.Wr = np.random.randn(hidden_size, combined) * scale_r
        self.br = np.zeros(hidden_size)
        self.Wh = np.random.randn(hidden_size, hidden_size + input_size) * scale_h
        self.bh = np.zeros(hidden_size)

        # Gradients
        self.dWz = np.zeros_like(self.Wz)
        self.dbz = np.zeros_like(self.bz)
        self.dWr = np.zeros_like(self.Wr)
        self.dbr = np.zeros_like(self.br)
        self.dWh = np.zeros_like(self.Wh)
        self.dbh = np.zeros_like(self.bh)

    def forward(self, x, h_prev):
        """Forward pass for one timestep. Returns new hidden state."""
        combined = np.concatenate([h_prev, x])

        # Update gate
        z_pre = self.Wz @ combined + self.bz
        z = sigmoid(z_pre)

        # Reset gate
        r_pre = self.Wr @ combined + self.br
        r = sigmoid(r_pre)

        # Candidate
        r_h = np.concatenate([r * h_prev, x])
        h_pre = self.Wh @ r_h + self.bh
        h_hat = np.tanh(h_pre)

        # New hidden
        h_new = (1 - z) * h_hat + z * h_prev

        # Cache for backprop
        self._cache = (x, h_prev, combined, z_pre, z, r_pre, r, h_pre, h_hat, h_new)

        return h_new

    def backward(self, dh_new):
        """Backward pass. Returns dh_prev and dx."""
        x, h_prev, combined, z_pre, z, r_pre, r, h_pre, h_hat, h_new = self._cache

        # Gradient of loss w.r.t. h_new
        dh = dh_new.copy()

        # h = (1 - z) * h_hat + z * h_prev
        dh_hat = dh * (1 - z)
        dh_prev = dh * z
        dz = dh * (h_prev - h_hat)

        # h_hat = tanh(h_pre)
        dh_pre = dh_hat * (1 - h_hat ** 2)

        # h_pre = Wh @ r_h + bh
        r_h = np.concatenate([r * h_prev, x])
        self.dWh += np.outer(dh_pre, r_h)
        self.dbh += dh_pre
        dr_h = self.Wh.T @ dh_pre

        # Split r_h into r*h_prev and x
        dr_h_prev = dr_h[:self.hidden_size]
        dx = dr_h[self.hidden_size:]

        # r * h_prev
        dr = dr_h_prev * h_prev
        dh_prev += dr_h_prev * r

        # r = sigmoid(r_pre)
        dr_pre = dr * sigmoid_derivative(r_pre)
        self.dWr += np.outer(dr_pre, combined)
        self.dbr += dr_pre
        dcombined_r = self.Wr.T @ dr_pre

        # z = sigmoid(z_pre)
        dz_pre = dz * sigmoid_derivative(z_pre)
        self.dWz += np.outer(dz_pre, combined)
        self.dbz += dz_pre
        dcombined_z = self.Wz.T @ dz_pre

        # Combined gradients
        dcombined = dcombined_r + dcombined_z
        dh_prev += dcombined[:self.hidden_size]
        dx += dcombined[self.hidden_size:]

        return dh_prev, dx

    def zero_grad(self):
        """Reset gradients."""
        self.dWz[:] = 0
        self.dbz[:] = 0
        self.dWr[:] = 0
        self.dbr[:] = 0
        self.dWh[:] = 0
        self.dbh[:] = 0

    def step(self, lr):
        """Update weights with accumulated gradients."""
        self.Wz -= lr * self.dWz
        self.bz -= lr * self.dbz
        self.Wr -= lr * self.dWr
        self.br -= lr * self.dbr
        self.Wh -= lr * self.dWh
        self.bh -= lr * self.dbh

    def to_dict(self):
        """Export weights to dict (matches TypeScript format)."""
        return {
            "Wz": self.Wz.tolist(),
            "bz": self.bz.tolist(),
            "Wr": self.Wr.tolist(),
            "br": self.br.tolist(),
            "Wh": self.Wh.tolist(),
            "bh": self.bh.tolist(),
        }

    @classmethod
    def from_dict(cls, d):
        """Load weights from dict."""
        cell = cls(len(d["bz"]), len(d["bz"]))
        cell.Wz = np.array(d["Wz"])
        cell.bz = np.array(d["bz"])
        cell.Wr = np.array(d["Wr"])
        cell.br = np.array(d["br"])
        cell.Wh = np.array(d["Wh"])
        cell.bh = np.array(d["bh"])
        return cell


class GRUClassifier:
    """Full GRU classifier: GRU + Linear layer."""

    def __init__(self, input_size, hidden_size, num_classes):
        self.gru = GRUCell(input_size, hidden_size)
        self.hidden_size = hidden_size

        # Classifier weights
        scale = np.sqrt(2.0 / hidden_size)
        self.Wc = np.random.randn(num_classes, hidden_size) * scale
        self.bc = np.zeros(num_classes)

        self.num_classes = num_classes

    def forward(self, sequence):
        """
        Forward pass through sequence.
        sequence: [seq_len, input_size]
        Returns: logits [num_classes]
        """
        h = np.zeros(self.hidden_size)

        for t in range(len(sequence)):
            h = self.gru.forward(sequence[t], h)

        # Classifier
        logits = self.Wc @ h + self.bc
        return logits, h

    def predict(self, sequence):
        """Return predicted class index and probabilities."""
        logits, _ = self.forward(sequence)

        # Softmax
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        predicted = np.argmax(probs)
        return predicted, probs, logits

    def backward(self, sequence, target):
        """
        Backward pass with BPTT (truncated).
        Returns loss (cross-entropy).
        """
        # Forward pass, caching hidden states
        h = np.zeros(self.hidden_size)
        hidden_states = [h]

        for t in range(len(sequence)):
            h = self.gru.forward(sequence[t], h)
            hidden_states.append(h)

        logits = self.Wc @ h + self.bc

        # Softmax
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        # Cross-entropy loss
        loss = -np.log(probs[target] + 1e-8)

        # Backprop through classifier
        dlogits = probs.copy()
        dlogits[target] -= 1

        self.Wc -= 0.001 * np.outer(dlogits, h)
        self.bc -= 0.001 * dlogits

        # Backprop through GRU (truncated BPTT)
        dh = self.Wc.T @ dlogits

        # Only backprop through last few steps (truncated)
        self.gru.zero_grad()
        for t in range(max(0, len(sequence) - 10), len(sequence)):
            dh, _ = self.gru.backward(dh)
            self.gru.step(0.001)

        return loss, probs

    def to_dict(self):
        """Export to dict matching TypeScript format."""
        return {
            "gru": self.gru.to_dict(),
            "classifier": {
                "W": self.Wc.tolist(),
                "b": self.bc.tolist(),
            },
        }


# ============================================================
# Data Loading and Preprocessing
# ============================================================

def load_clips(dataset_dir):
    """Load all clips from directory."""
    dataset_dir = Path(dataset_dir)
    clips = []

    for clip_path in dataset_dir.glob("*.json"):
        try:
            with open(clip_path) as f:
                clip = json.load(f)

            label = clip.get("label", "unknown")
            frames = clip.get("frames", [])

            if not frames:
                continue

            # Extract hand landmarks per frame
            sequence = []
            for frame in frames:
                hands = frame.get("hands", [])
                if hands:
                    # Use first hand, pad to 21 landmarks
                    hand = hands[0]
                    features = []
                    for lm in hand[:21]:
                        features.extend([lm["x"], lm["y"], lm["z"]])
                    # Pad if less than 21 landmarks
                    while len(features) < 63:
                        features.extend([0, 0, 0])
                    # Add second hand (zeros if not present)
                    if len(hands) > 1:
                        hand2 = hands[1]
                        for lm in hand2[:21]:
                            features.extend([lm["x"], lm["y"], lm["z"]])
                        while len(features) < 126:
                            features.extend([0, 0, 0])
                    else:
                        features.extend([0] * 63)
                    sequence.append(features[:126])

            if sequence:
                clips.append({
                    "label": label,
                    "sequence": sequence,
                    "path": str(clip_path),
                })
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Warning: Error loading {clip_path}: {e}")

    return clips


def normalize_sequence(sequence, target_length):
    """Normalize sequence to fixed length by padding or truncating."""
    seq_len = len(sequence)
    features = len(sequence[0]) if sequence else 0

    if seq_len == 0:
        return np.zeros((target_length, features))

    if seq_len >= target_length:
        # Truncate (take evenly spaced frames)
        indices = np.linspace(0, seq_len - 1, target_length, dtype=int)
        return np.array([sequence[i] for i in indices])
    else:
        # Pad with last frame repeated
        padded = np.array(sequence)
        pad_len = target_length - seq_len
        padding = np.tile(padded[-1:], (pad_len, 1))
        return np.vstack([padded, padding])


def normalize_landmarks(sequence):
    """
    Normalize landmarks relative to wrist position.
    This makes the model robust to camera position.
    """
    normalized = []
    for frame in sequence:
        frame = np.array(frame).reshape(-1, 3)  # [num_landmarks, 3]

        # Use wrist (landmark 0) as reference
        wrist = frame[0]
        frame_norm = frame - wrist

        normalized.append(frame_norm.flatten())
    return normalized


def augment_sequence(sequence, augmentation_type):
    """Apply data augmentation to a sequence."""
    seq = np.array(sequence)

    if augmentation_type == "jitter":
        # Add small random noise
        noise = np.random.normal(0, 0.01, seq.shape)
        return (seq + noise).tolist()

    elif augmentation_type == "speed_slow":
        # Slow down by interpolating frames
        new_len = int(len(seq) * 1.2)
        indices = np.linspace(0, len(seq) - 1, new_len)
        return np.array([seq[min(int(i), len(seq) - 1)] for i in indices]).tolist()

    elif augmentation_type == "speed_fast":
        # Speed up by subsampling
        new_len = max(5, int(len(seq) * 0.8))
        indices = np.linspace(0, len(seq) - 1, new_len, dtype=int)
        return seq[indices].tolist()

    elif augmentation_type == "reverse":
        # Reverse the sequence
        return seq[::-1].tolist()

    return sequence


# ============================================================
# Training
# ============================================================

def train_model(model, train_clips, val_clips, labels, config):
    """Train the GRU classifier."""
    label_to_idx = {label: i for i, label in enumerate(labels)}

    print(f"\nEntrenando modelo GRU:")
    print(f"  Input size: {config['input_size']}")
    print(f"  Hidden size: {config['hidden_size']}")
    print(f"  Num classes: {len(labels)}")
    print(f"  Seq length: {config['seq_length']}")
    print(f"  Train clips: {len(train_clips)}, Val clips: {len(val_clips)}")
    print(f"  Epochs: {config['epochs']}, LR: {config['learning_rate']}")
    print()

    best_val_acc = 0
    best_weights = None
    history = []

    for epoch in range(config["epochs"]):
        # Shuffle training data
        random.shuffle(train_clips)

        epoch_loss = 0
        correct = 0
        total = 0

        # Training
        for clip in train_clips:
            label = clip["label"]
            if label not in label_to_idx:
                continue

            target = label_to_idx[label]

            # Preprocess
            seq = normalize_landmarks(clip["sequence"])
            seq = normalize_sequence(seq, config["seq_length"])
            seq = np.array(seq)

            # Random augmentation
            if random.random() < 0.5:
                aug_type = random.choice(["jitter", "speed_slow", "speed_fast"])
                seq = augment_sequence(seq.tolist(), aug_type)
                seq = np.array(seq)

            # Forward + backward
            loss, probs = model.backward(seq, target)
            epoch_loss += loss
            total += 1

            if np.argmax(probs) == target:
                correct += 1

        train_acc = correct / total if total > 0 else 0
        avg_loss = epoch_loss / total if total > 0 else 0

        # Validation
        val_correct = 0
        val_total = 0
        val_confusion = np.zeros((len(labels), len(labels)), dtype=int)

        for clip in val_clips:
            label = clip["label"]
            if label not in label_to_idx:
                continue

            target = label_to_idx[label]
            seq = normalize_landmarks(clip["sequence"])
            seq = normalize_sequence(seq, config["seq_length"])

            predicted, probs, _ = model.predict(np.array(seq))
            val_confusion[target][predicted] += 1

            if predicted == target:
                val_correct += 1
            val_total += 1

        val_acc = val_correct / val_total if val_total > 0 else 0

        # Save best model
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_weights = model.to_dict()

        history.append({
            "epoch": epoch + 1,
            "train_loss": float(avg_loss),
            "train_acc": float(train_acc),
            "val_acc": float(val_acc),
        })

        # Print progress every 10 epochs
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  Epoch {epoch+1:3d}/{config['epochs']}: "
                  f"loss={avg_loss:.4f} train_acc={train_acc:.3f} val_acc={val_acc:.3f}"
                  f"{' *' if val_acc >= best_val_acc else ''}")

    return best_weights, best_val_acc, val_confusion, history


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Train temporal GRU model for dynamic sign recognition"
    )
    parser.add_argument("--dataset-dir", required=True, help="Path to clips directory")
    parser.add_argument("--output", default="ml/models/temporal_weights.json", help="Output weights path")
    parser.add_argument("--epochs", type=int, default=CONFIG["epochs"])
    parser.add_argument("--hidden-size", type=int, default=CONFIG["hidden_size"])
    parser.add_argument("--lr", type=float, default=CONFIG["learning_rate"])
    parser.add_argument("--seed", type=int, default=CONFIG["seed"])
    args = parser.parse_args()

    # Set seed
    random.seed(args.seed)
    np.random.seed(args.seed)

    CONFIG["epochs"] = args.epochs
    CONFIG["hidden_size"] = args.hidden_size
    CONFIG["learning_rate"] = args.lr

    print("=" * 60)
    print("ENTRENAMIENTO DE MODELO TEMPORAL - SeñasCL")
    print("=" * 60)

    # Load dataset
    print("\nCargando dataset...")
    clips = load_clips(args.dataset_dir)

    if not clips:
        print("Error: No se encontraron clips válidos")
        sys.exit(1)

    # Get labels
    labels = sorted(set(c["label"] for c in clips))
    print(f"Palabras encontradas: {len(labels)}")
    for label in labels:
        count = sum(1 for c in clips if c["label"] == label)
        print(f"  {label}: {count} clips")

    # Split train/val (by clip, not by frame)
    random.shuffle(clips)
    split_idx = int(len(clips) * CONFIG["train_split"])
    train_clips = clips[:split_idx]
    val_clips = clips[split_idx:]

    print(f"\nDivisión: {len(train_clips)} train, {len(val_clips)} validation")

    # Create model
    model = GRUClassifier(
        input_size=CONFIG["input_size"],
        hidden_size=CONFIG["hidden_size"],
        num_classes=len(labels),
    )

    # Train
    print("\nIniciando entrenamiento...")
    start_time = time.time()
    best_weights, best_acc, confusion, history = train_model(
        model, train_clips, val_clips, labels, CONFIG
    )
    elapsed = time.time() - start_time

    print(f"\nEntrenamiento completado en {elapsed:.1f}s")
    print(f"Mejor exactitud de validación: {best_acc:.1%}")

    # Print confusion matrix
    print("\nMatriz de confusión (validación):")
    print(f"{'':>15}", end="")
    for label in labels:
        print(f"{label[:8]:>9}", end="")
    print()
    for i, label in enumerate(labels):
        print(f"{label[:14]:>15}", end="")
        for j in range(len(labels)):
            print(f"{confusion[i][j]:>9}", end="")
        print()

    # Export weights
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    export_data = {
        "config": CONFIG,
        "labels": labels,
        "weights": best_weights,
        "metrics": {
            "best_val_accuracy": float(best_acc),
            "epochs_trained": CONFIG["epochs"],
            "training_time_seconds": elapsed,
            "train_clips": len(train_clips),
            "val_clips": len(val_clips),
        },
        "history": history,
    }

    with open(output_path, "w") as f:
        json.dump(export_data, f, indent=2)

    print(f"\nPesos exportados a: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
