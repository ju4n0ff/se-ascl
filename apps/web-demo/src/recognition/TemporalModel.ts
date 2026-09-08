/**
 * TemporalModel - Lightweight GRU for dynamic sign classification.
 *
 * Processes a sequence of landmark frames and outputs a classification
 * for the entire gesture. Uses a Gated Recurrent Unit (GRU) which is
 * more lightweight than LSTM while still capturing temporal dependencies.
 *
 * Architecture:
 *   Input: [batch, seq_len, features] (flattened landmarks per frame)
 *   GRU(input_size, hidden_size) -> hidden state
 *   Linear(hidden_size, num_classes) -> logits
 *   Softmax -> probabilities
 *
 * NOTE: This is a skeleton with the forward pass structure.
 * Training and weight loading are placeholder — see train_temporal.py
 * for the Python training script that produces compatible weights.
 */

export interface TemporalModelConfig {
  inputSize: number;    // Features per frame (e.g., 21*3*2 = 126 for 2 hands)
  hiddenSize: number;   // GRU hidden state size
  numClasses: number;   // Number of dynamic signs to recognize
  seqLength: number;    // Expected sequence length (padded/truncated)
}

export interface TemporalResult {
  /** Predicted class index */
  predictedClass: number;
  /** Predicted gloss/label */
  gloss: string;
  /** Confidence score (0-1) */
  confidence: number;
  /** Raw logits for all classes */
  logits: Float32Array;
  /** Probabilities for all classes */
  probabilities: Float32Array;
}

// Default dynamic signs in LSCh (expandable)
export const DYNAMIC_SIGN_LABELS: string[] = [
  'HOLA',        // Hello — wave
  'GRACIAS',     // Thanks — hand from chin forward
  'POR_FAVOR',   // Please — circular motion on chest
  'SI',          // Yes — nodding fist
  'NO',          // No — index side to side
  'YO',          // I/me — point to self
  'TU',          // You — point forward
  'QUE',         // What — open hand shake
  'COMO',        // How — two hands parallel
  'BIEN',        // Good — thumbs up
  'MAL',         // Bad — thumbs down
  'AYUDA',       // Help — fist on palm
  'FAMILIA',     // Family — circle with both hands
  'AMIGO',       // Friend — interlock fingers
  'COMIDA',      // Food — fingers to mouth
  'AGUA',        // Water — W handshape to mouth
  'TRABAJO',     // Work — tap fist on wrist
  'CASA',        // Home — two hands form roof
  'ESCUELA',     // School — clap alternating
  'TIEMPO',      // Time — tap wrist
];

// Sigmoid activation (for GRU gates)
function sigmoid(x: number): number {
  return 1 / (1 + Math.exp(-Math.max(-10, Math.min(10, x))));
}

// Tanh activation
function tanh(x: number): number {
  return Math.tanh(x);
}

/**
 * GRU Cell — processes one timestep.
 *
 * Gate equations:
 *   z = sigmoid(W_z * [h_prev, x] + b_z)  // update gate
 *   r = sigmoid(W_r * [h_prev, x] + b_r)  // reset gate
 *   h_hat = tanh(W * [r * h_prev, x] + b) // candidate
 *   h = (1 - z) * h_hat + z * h_prev       // new hidden state
 */
interface GRUWeights {
  Wz: number[][];   // [hiddenSize, inputSize + hiddenSize]
  bz: number[];
  Wr: number[][];   // [hiddenSize, inputSize + hiddenSize]
  br: number[];
  Wh: number[][];   // [hiddenSize, inputSize + hiddenSize]
  bh: number[];
}

interface LinearWeights {
  W: number[][];    // [outputSize, inputSize]
  b: number[];
}

export class TemporalModel {
  private config: TemporalModelConfig;
  private gruWeights: GRUWeights | null = null;
  private classifierWeights: LinearWeights | null = null;
  private labels: string[];
  private initialized = false;

  constructor(config?: Partial<TemporalModelConfig>) {
    this.config = {
      inputSize: config?.inputSize ?? 126,     // 21 landmarks * 3 coords * 2 hands
      hiddenSize: config?.hiddenSize ?? 64,
      numClasses: config?.numClasses ?? DYNAMIC_SIGN_LABELS.length,
      seqLength: config?.seqLength ?? 30,
    };
    this.labels = [...DYNAMIC_SIGN_LABELS];
  }

  /**
   * Load trained weights from a JSON file.
   * Expected format from Python training script.
   */
  async loadWeights(url: string): Promise<boolean> {
    try {
      const response = await fetch(url);
      if (!response.ok) return false;

      const weights = await response.json();

      if (weights.gru && weights.classifier) {
        this.gruWeights = weights.gru;
        this.classifierWeights = weights.classifier;
        this.initialized = true;
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }

  /**
   * Initialize with random weights (for testing/demo).
   * NOT suitable for real inference — use loadWeights() for production.
   */
  initWithRandomWeights(): void {
    const { inputSize, hiddenSize, numClasses } = this.config;
    const combined = inputSize + hiddenSize;

    const randomMatrix = (rows: number, cols: number): number[][] =>
      Array.from({ length: rows }, () =>
        Array.from({ length: cols }, () => (Math.random() - 0.5) * 0.1)
      );

    const zeros = (n: number): number[] => Array(n).fill(0);

    this.gruWeights = {
      Wz: randomMatrix(hiddenSize, combined),
      bz: zeros(hiddenSize),
      Wr: randomMatrix(hiddenSize, combined),
      br: zeros(hiddenSize),
      Wh: randomMatrix(hiddenSize, combined),
      bh: zeros(hiddenSize),
    };

    this.classifierWeights = {
      W: randomMatrix(numClasses, hiddenSize),
      b: zeros(numClasses),
    };

    this.initialized = true;
  }

  /**
   * Forward pass: process a sequence of frames through GRU + classifier.
   *
   * @param sequence - Flattened features, shape [seqLength * inputSize]
   *                  or 2D array [seqLength][inputSize]
   * @returns Classification result
   */
  predict(sequence: number[][] | Float32Array): TemporalResult {
    if (!this.initialized || !this.gruWeights || !this.classifierWeights) {
      // Fallback: return low-confidence random prediction
      return this.getRandomPrediction();
    }

    const { hiddenSize, numClasses, inputSize } = this.config;
    const gru = this.gruWeights;

    // Initialize hidden state to zeros
    let h = new Array(hiddenSize).fill(0) as number[];

    // Determine sequence length
    let seqLen: number;
    let getValue: (frame: number, idx: number) => number;

    if (Array.isArray(sequence[0])) {
      // 2D array: [seqLen][inputSize]
      seqLen = sequence.length;
      getValue = (frame: number, idx: number) => (sequence[frame] as number[])[idx] ?? 0;
    } else {
      // Flat array: [seqLen * inputSize]
      const flat = sequence as Float32Array;
      seqLen = Math.floor(flat.length / inputSize);
      getValue = (frame: number, idx: number) => flat[frame * inputSize + idx] ?? 0;
    }

    // Process each timestep through GRU
    for (let t = 0; t < seqLen; t++) {
      // Concatenate [h_prev, x_t]
      const combined = new Array(hiddenSize + inputSize);
      for (let i = 0; i < hiddenSize; i++) combined[i] = h[i];
      for (let i = 0; i < inputSize; i++) combined[hiddenSize + i] = getValue(t, i);

      // Update gate: z = sigmoid(Wz * combined + bz)
      const z = new Array(hiddenSize);
      for (let i = 0; i < hiddenSize; i++) {
        let sum = gru.bz[i];
        for (let j = 0; j < combined.length; j++) {
          sum += gru.Wz[i][j] * combined[j];
        }
        z[i] = sigmoid(sum);
      }

      // Reset gate: r = sigmoid(Wr * combined + br)
      const r = new Array(hiddenSize);
      for (let i = 0; i < hiddenSize; i++) {
        let sum = gru.br[i];
        for (let j = 0; j < combined.length; j++) {
          sum += gru.Wr[i][j] * combined[j];
        }
        r[i] = sigmoid(sum);
      }

      // Candidate: h_hat = tanh(Wh * [r * h_prev, x] + bh)
      const rH = new Array(hiddenSize + inputSize);
      for (let i = 0; i < hiddenSize; i++) rH[i] = r[i] * h[i];
      for (let i = 0; i < inputSize; i++) rH[hiddenSize + i] = getValue(t, i);

      const hHat = new Array(hiddenSize);
      for (let i = 0; i < hiddenSize; i++) {
        let sum = gru.bh[i];
        for (let j = 0; j < rH.length; j++) {
          sum += gru.Wh[i][j] * rH[j];
        }
        hHat[i] = tanh(sum);
      }

      // New hidden: h = (1 - z) * h_hat + z * h_prev
      const hNew = new Array(hiddenSize);
      for (let i = 0; i < hiddenSize; i++) {
        hNew[i] = (1 - z[i]) * hHat[i] + z[i] * h[i];
      }

      h = hNew;
    }

    // Classifier: logits = W * h + b
    const logits = new Float32Array(numClasses);
    for (let i = 0; i < numClasses; i++) {
      let sum = this.classifierWeights.b[i];
      for (let j = 0; j < hiddenSize; j++) {
        sum += this.classifierWeights.W[i][j] * h[j];
      }
      logits[i] = sum;
    }

    // Softmax
    const probs = this.softmax(logits);

    // Find best
    let bestIdx = 0;
    let bestProb = probs[0];
    for (let i = 1; i < numClasses; i++) {
      if (probs[i] > bestProb) {
        bestProb = probs[i];
        bestIdx = i;
      }
    }

    return {
      predictedClass: bestIdx,
      gloss: this.labels[bestIdx] ?? `CLASS_${bestIdx}`,
      confidence: bestProb,
      logits,
      probabilities: probs,
    };
  }

  /**
   * Normalize a sequence to fixed length by padding or truncating.
   */
  normalizeSequence(sequence: number[][], targetLength: number): number[][] {
    const { inputSize } = this.config;
    const result: number[][] = [];

    for (let t = 0; t < targetLength; t++) {
      if (t < sequence.length) {
        // Pad or truncate feature vector
        const frame = sequence[t];
        const padded = new Array(inputSize).fill(0);
        for (let i = 0; i < Math.min(frame.length, inputSize); i++) {
          padded[i] = frame[i];
        }
        result.push(padded);
      } else {
        // Zero-pad missing frames
        result.push(new Array(inputSize).fill(0));
      }
    }

    return result;
  }

  /**
   * Convert FrameData[] sequence to flat feature array for the model.
   */
  framesToFeatures(frames: { landmarks: { x: number; y: number; z: number }[][] }[]): number[][] {
    const { inputSize } = this.config;
    const maxHands = 2;
    const landmarksPerHand = 21;
    const coordsPerLandmark = 3;
    const handFeatures = landmarksPerHand * coordsPerLandmark;

    return frames.map((frame) => {
      const features: number[] = [];

      for (let h = 0; h < maxHands; h++) {
        if (h < frame.landmarks.length) {
          const hand = frame.landmarks[h];
          for (let p = 0; p < landmarksPerHand; p++) {
            if (p < hand.length) {
              features.push(hand[p].x, hand[p].y, hand[p].z);
            } else {
              features.push(0, 0, 0);
            }
          }
        } else {
          // Pad missing hand with zeros
          features.push(...new Array(handFeatures).fill(0));
        }
      }

      // Ensure correct size
      while (features.length < inputSize) features.push(0);
      return features.slice(0, inputSize);
    });
  }

  private softmax(logits: Float32Array): Float32Array {
    const maxLogit = Math.max(...logits);
    const exps = logits.map((x) => Math.exp(x - maxLogit));
    const sumExps = exps.reduce((a, b) => a + b, 0);
    return exps.map((x) => x / sumExps);
  }

  private getRandomPrediction(): TemporalResult {
    const { numClasses } = this.config;
    const probs = new Float32Array(numClasses);
    const logits = new Float32Array(numClasses);

    for (let i = 0; i < numClasses; i++) {
      logits[i] = (Math.random() - 0.5) * 0.1;
      probs[i] = 1 / numClasses;
    }

    return {
      predictedClass: 0,
      gloss: this.labels[0] ?? 'UNKNOWN',
      confidence: 0,
      logits,
      probabilities: probs,
    };
  }

  isReady(): boolean {
    return this.initialized;
  }

  getLabels(): readonly string[] {
    return this.labels;
  }

  getConfig(): Readonly<TemporalModelConfig> {
    return this.config;
  }
}
