/**
 * SignDecider - Orchestrates static vs dynamic sign recognition.
 *
 * This is the brain of the dual-path architecture:
 * - Path A (Static): Single frame → heuristic classifier → letter
 * - Path B (Dynamic): Frame sequence → temporal model → word
 *
 * The decider manages the FrameBuffer, GestureSegmenter, and TemporalModel
 * to decide which path to use based on hand movement analysis.
 */

import { RecognitionResult, ConfidenceLevel } from '@senascl/shared-types';
import { lookupSign } from '@senascl/nlp-lsch';
import { FrameBuffer, LandmarkPoint } from './FrameBuffer';
import { GestureSegmenter, SegmenterResult } from './GestureSegmenter';
import { TemporalModel, TemporalResult } from './TemporalModel';

export interface DeciderConfig {
  /** Velocity below which hand is considered "still" for static classification */
  staticVelocityThreshold: number;
  /** How many frames of stillness before attempting static classification */
  staticStabilityFrames: number;
  /** Minimum confidence from temporal model to accept a dynamic result */
  dynamicMinConfidence: number;
  /** Maximum time (ms) to wait for dynamic gesture before falling back to static */
  dynamicTimeoutMs: number;
}

export type RecognitionMode = 'static' | 'dynamic' | 'transitioning';

export interface DeciderState {
  mode: RecognitionMode;
  /** Current static classification (if any) */
  staticResult: { letter: string; confidence: number } | null;
  /** Current dynamic classification (if gesture just completed) */
  dynamicResult: TemporalResult | null;
  /** Is a gesture currently being tracked? */
  gestureActive: boolean;
  /** Frames since gesture started */
  gestureProgress: number;
  /** Overall progress (0-1) for UI feedback */
  progress: number;
  /** Raw velocity for debugging */
  velocity: number;
  /** Segmenter state for debugging */
  segmenterState: string;
}

const DEFAULT_CONFIG: DeciderConfig = {
  staticVelocityThreshold: 0.004,
  staticStabilityFrames: 5,
  dynamicMinConfidence: 0.6,
  dynamicTimeoutMs: 2000,
};

export class SignDecider {
  private frameBuffer: FrameBuffer;
  private segmenter: GestureSegmenter;
  private temporalModel: TemporalModel;
  private config: DeciderConfig;

  private staticResult: { letter: string; confidence: number } | null = null;
  private stableFrameCount = 0;
  private gestureStartTime = 0;

  constructor(config?: Partial<DeciderConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.frameBuffer = new FrameBuffer({ maxFrames: 30, fpsSampleRate: 2 });
    this.segmenter = new GestureSegmenter();
    this.temporalModel = new TemporalModel();
  }

  /**
   * Process a new frame of landmarks.
   * Returns the current recognition state.
   */
  processFrame(
    landmarks: LandmarkPoint[][],
    timestamp: number,
    staticClassifier: (landmarks: LandmarkPoint[][]) => { letter: string; confidence: number } | null
  ): DeciderState {
    // 1. Push frame to buffer
    this.frameBuffer.push(landmarks, timestamp);

    // 2. Run gesture segmentation
    const segmenterResult = this.segmenter.process(this.frameBuffer);

    // 3. Check if a gesture just completed
    if (segmenterResult.completedGesture) {
      return this.handleCompletedGesture(segmenterResult);
    }

    // 4. If gesture is active, track progress
    if (segmenterResult.isActive) {
      this.gestureStartTime = this.gestureStartTime || timestamp;
      const elapsed = timestamp - this.gestureStartTime;
      const progress = Math.min(1, elapsed / this.config.dynamicTimeoutMs);

      return {
        mode: 'dynamic',
        staticResult: null,
        dynamicResult: null,
        gestureActive: true,
        gestureProgress: segmenterResult.gestureFrameCount,
        progress,
        velocity: segmenterResult.velocity,
        segmenterState: segmenterResult.state,
      };
    }

    // 5. No gesture active — check for static classification
    const velocity = segmenterResult.velocity;

    if (velocity < this.config.staticVelocityThreshold) {
      // Hand is still — accumulate stability
      this.stableFrameCount++;

      if (this.stableFrameCount >= this.config.staticStabilityFrames) {
        // Hand stable enough for static classification
        this.staticResult = staticClassifier(landmarks);
      }
    } else {
      // Hand is moving — reset stability
      this.stableFrameCount = 0;
      this.staticResult = null;
    }

    return {
      mode: this.stableFrameCount >= this.config.staticStabilityFrames ? 'static' : 'transitioning',
      staticResult: this.staticResult,
      dynamicResult: null,
      gestureActive: false,
      gestureProgress: 0,
      progress: 0,
      velocity,
      segmenterState: segmenterResult.state,
    };
  }

  private handleCompletedGesture(segmenterResult: SegmenterResult): DeciderState {
    const gestureFrames = segmenterResult.completedGesture!;

    let dynamicResult: TemporalResult | null = null;

    if (this.temporalModel.isReady()) {
      // Run temporal model on the completed gesture
      const features = this.temporalModel.framesToFeatures(gestureFrames);
      const normalized = this.temporalModel.normalizeSequence(features, 30);
      dynamicResult = this.temporalModel.predict(normalized);

      // Only accept if confidence is above threshold
      if (dynamicResult.confidence < this.config.dynamicMinConfidence) {
        dynamicResult = null;
      }
    }

    this.gestureStartTime = 0;
    this.stableFrameCount = 0;

    return {
      mode: 'static',
      staticResult: null,
      dynamicResult,
      gestureActive: false,
      gestureProgress: 0,
      progress: 1,
      velocity: 0,
      segmenterState: 'ended',
    };
  }

  /**
   * Convert DeciderState to RecognitionResult[] for the UI.
   */
  toRecognitionResults(state: DeciderState): RecognitionResult[] {
    const results: RecognitionResult[] = [];
    const now = Date.now();

    // Static result
    if (state.staticResult) {
      results.push({
        signId: state.staticResult.letter,
        gloss: state.staticResult.letter,
        spanishText: state.staticResult.letter,
        confidence: state.staticResult.confidence,
        confidenceLevel:
          state.staticResult.confidence >= 0.8
            ? ConfidenceLevel.HIGH
            : state.staticResult.confidence >= 0.6
            ? ConfidenceLevel.MEDIUM
            : ConfidenceLevel.LOW,
        timestamp: now,
        isFingerspelling: true,
      });
    }

    // Dynamic result — translate gloss to Spanish via NLP dictionary
    if (state.dynamicResult) {
      const gloss = state.dynamicResult.gloss;
      // Look up Spanish translation; if not found, use gloss as-is (uppercase)
      const spanishText = lookupSign(gloss) ?? gloss;

      results.push({
        signId: gloss,
        gloss,
        spanishText,
        confidence: state.dynamicResult.confidence,
        confidenceLevel:
          state.dynamicResult.confidence >= 0.8
            ? ConfidenceLevel.HIGH
            : state.dynamicResult.confidence >= 0.6
            ? ConfidenceLevel.MEDIUM
            : ConfidenceLevel.LOW,
        timestamp: now,
        isFingerspelling: false,
      });
    }

    return results;
  }

  /** Load temporal model weights */
  async loadTemporalModel(url: string): Promise<boolean> {
    return this.temporalModel.loadWeights(url);
  }

  /** Initialize temporal model with random weights (for demo/testing) */
  initTemporalModel(): void {
    this.temporalModel.initWithRandomWeights();
  }

  /** Get the temporal model for direct access */
  getTemporalModel(): TemporalModel {
    return this.temporalModel;
  }

  /** Reset all state */
  reset(): void {
    this.frameBuffer.clear();
    this.segmenter.reset();
    this.staticResult = null;
    this.stableFrameCount = 0;
    this.gestureStartTime = 0;
  }
}
