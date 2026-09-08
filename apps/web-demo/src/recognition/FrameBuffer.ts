/**
 * FrameBuffer - Sliding window buffer for hand landmarks.
 *
 * Accumulates the last N frames of landmarks to enable temporal
 * analysis for dynamic sign recognition. Uses a FIFO queue.
 *
 * Each frame stored contains: { landmarks, timestamp, handCount }
 */

export interface LandmarkPoint {
  x: number;
  y: number;
  z: number;
}

export interface FrameData {
  landmarks: LandmarkPoint[][]; // landmarks per hand
  timestamp: number;
  handCount: number;
}

export interface FrameBufferConfig {
  maxFrames: number;        // Window size (N frames). 30-45 at 30fps = 1-1.5s
  fpsSampleRate: number;    // Sample every Nth frame (2 = every other frame)
}

const DEFAULT_CONFIG: FrameBufferConfig = {
  maxFrames: 30,
  fpsSampleRate: 2,
};

export class FrameBuffer {
  private buffer: FrameData[] = [];
  private config: FrameBufferConfig;
  private frameCounter = 0;

  constructor(config: Partial<FrameBufferConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * Push a new frame into the buffer.
   * Respects fpsSampleRate — only stores every Nth frame.
   * Returns true if the frame was stored.
   */
  push(landmarks: LandmarkPoint[][], timestamp: number): boolean {
    this.frameCounter++;

    // Sample at reduced rate to normalize fps across devices
    if (this.frameCounter % this.config.fpsSampleRate !== 0) {
      return false;
    }

    const handCount = landmarks.length;
    const frame: FrameData = { landmarks, timestamp, handCount };

    this.buffer.push(frame);

    // Evict oldest if over capacity
    if (this.buffer.length > this.config.maxFrames) {
      this.buffer.shift();
    }

    return true;
  }

  /** Get all frames in the current window */
  getAll(): readonly FrameData[] {
    return this.buffer;
  }

  /** Get the last frame */
  getLast(): FrameData | undefined {
    return this.buffer[this.buffer.length - 1];
  }

  /** Get the first frame (oldest in window) */
  getFirst(): FrameData | undefined {
    return this.buffer[0];
  }

  /** Number of frames currently in buffer */
  get length(): number {
    return this.buffer.length;
  }

  /** Is buffer at capacity? */
  isFull(): boolean {
    return this.buffer.length >= this.config.maxFrames;
  }

  /** Clear the buffer */
  clear(): void {
    this.buffer = [];
    this.frameCounter = 0;
  }

  /**
   * Compute velocity of hand movement over the buffer.
   * Uses wrist (landmark 0) position across frames.
   * Returns average velocity (pixels per frame).
   */
  computeVelocity(): number {
    if (this.buffer.length < 2) return 0;

    let totalDist = 0;
    let validPairs = 0;

    for (let i = 1; i < this.buffer.length; i++) {
      const prev = this.buffer[i - 1];
      const curr = this.buffer[i];

      // Use first hand's wrist (landmark 0)
      if (prev.landmarks.length > 0 && curr.landmarks.length > 0) {
        const prevWrist = prev.landmarks[0][0];
        const currWrist = curr.landmarks[0][0];

        if (prevWrist && currWrist) {
          const dx = currWrist.x - prevWrist.x;
          const dy = currWrist.y - prevWrist.y;
          totalDist += Math.sqrt(dx * dx + dy * dy);
          validPairs++;
        }
      }
    }

    return validPairs > 0 ? totalDist / validPairs : 0;
  }

  /**
   * Compute total displacement of wrist from first to last frame.
   */
  computeDisplacement(): number {
    if (this.buffer.length < 2) return 0;

    const first = this.buffer[0];
    const last = this.buffer[this.buffer.length - 1];

    if (first.landmarks.length === 0 || last.landmarks.length === 0) return 0;

    const firstWrist = first.landmarks[0][0];
    const lastWrist = last.landmarks[0][0];

    if (!firstWrist || !lastWrist) return 0;

    const dx = lastWrist.x - firstWrist.x;
    const dy = lastWrist.y - firstWrist.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  /**
   * Get flattened feature vector for the current window.
   * Shape: [numFrames * maxHands * 21 * 3]
   * Pads with zeros if fewer hands than expected.
   */
  getFlatFeatures(maxHands: number = 2): Float32Array {
    const featuresPerHand = 21 * 3; // 21 landmarks * 3 coords
    const frameSize = maxHands * featuresPerHand;
    const totalSize = this.buffer.length * frameSize;

    const features = new Float32Array(totalSize);

    for (let f = 0; f < this.buffer.length; f++) {
      const frame = this.buffer[f];
      const offset = f * frameSize;

      for (let h = 0; h < Math.min(frame.landmarks.length, maxHands); h++) {
        const handOffset = offset + h * featuresPerHand;
        const hand = frame.landmarks[h];

        for (let p = 0; p < Math.min(hand.length, 21); p++) {
          const pointOffset = handOffset + p * 3;
          features[pointOffset] = hand[p].x;
          features[pointOffset + 1] = hand[p].y;
          features[pointOffset + 2] = hand[p].z;
        }
      }
    }

    return features;
  }
}
