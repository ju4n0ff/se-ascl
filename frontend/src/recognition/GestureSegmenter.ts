/**
 * GestureSegmenter - Detects start/end of gestures from hand movement.
 *
 * Uses wrist velocity to determine when a gesture begins (movement above
 * threshold) and ends (movement below threshold for N consecutive frames).
 *
 * This is a velocity-based VAD (Voice Activity Detector) for hands.
 */

import { FrameBuffer, FrameData } from './FrameBuffer';

export interface SegmenterConfig {
  /** Velocity threshold to START a gesture (movement detected) */
  startThreshold: number;
  /** Velocity threshold to END a gesture (hand is still) */
  endThreshold: number;
  /** How many consecutive "still" frames needed to confirm end */
  stillFramesToEnd: number;
  /** Minimum frames in a gesture to be considered valid */
  minGestureFrames: number;
  /** Maximum frames before force-ending the gesture */
  maxGestureFrames: number;
}

export type GestureState = 'idle' | 'detecting' | 'active' | 'ended';

export interface SegmenterResult {
  state: GestureState;
  /** Is a gesture currently in progress? */
  isActive: boolean;
  /** Did a gesture just end? If so, contains the buffered frames */
  completedGesture: FrameData[] | null;
  /** Current velocity */
  velocity: number;
  /** Frames since gesture started */
  gestureFrameCount: number;
}

const DEFAULT_CONFIG: SegmenterConfig = {
  startThreshold: 0.008,     // Movement above this = gesture started
  endThreshold: 0.004,       // Movement below this = potential end
  stillFramesToEnd: 8,       // 8 consecutive still frames to confirm end
  minGestureFrames: 6,       // Minimum ~200ms at 30fps
  maxGestureFrames: 60,      // Maximum ~2s at 30fps
};

export class GestureSegmenter {
  private config: SegmenterConfig;
  private state: GestureState = 'idle';
  private stillFrameCount = 0;
  private gestureFrames = 0;
  private gestureBuffer: FrameData[] = [];

  constructor(config: Partial<SegmenterConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * Process a new frame from the buffer.
   * Returns the current segmentation state.
   */
  process(frameBuffer: FrameBuffer): SegmenterResult {
    const velocity = frameBuffer.computeVelocity();
    this.gestureFrames++;

    switch (this.state) {
      case 'idle':
        return this.processIdle(velocity, frameBuffer);

      case 'detecting':
        return this.processDetecting(velocity, frameBuffer);

      case 'active':
        return this.processActive(velocity, frameBuffer);

      case 'ended':
        return this.processEnded();
    }
  }

  private processIdle(velocity: number, buffer: FrameBuffer): SegmenterResult {
    this.stillFrameCount = 0;
    this.gestureFrames = 0;
    this.gestureBuffer = [];

    if (velocity > this.config.startThreshold) {
      // Movement detected — start gesture
      this.state = 'detecting';
      this.gestureBuffer = [...buffer.getAll()];
      this.gestureFrames = this.gestureBuffer.length;
    }

    return {
      state: this.state,
      isActive: false,
      completedGesture: null,
      velocity,
      gestureFrameCount: 0,
    };
  }

  private processDetecting(velocity: number, buffer: FrameBuffer): SegmenterResult {
    // Accumulate frames
    this.gestureBuffer = [...buffer.getAll()];
    this.gestureFrames = this.gestureBuffer.length;

    if (velocity < this.config.endThreshold) {
      this.stillFrameCount++;
    } else {
      this.stillFrameCount = 0;
    }

    // If enough frames accumulated with consistent movement, transition to active
    if (this.gestureFrames >= this.config.minGestureFrames && velocity > this.config.endThreshold) {
      this.state = 'active';
    }

    // If too many still frames at start, it was noise — go back to idle
    if (this.stillFrameCount >= this.config.stillFramesToEnd) {
      this.state = 'idle';
    }

    return {
      state: this.state,
      isActive: false,
      completedGesture: null,
      velocity,
      gestureFrameCount: this.gestureFrames,
    };
  }

  private processActive(velocity: number, buffer: FrameBuffer): SegmenterResult {
    this.gestureBuffer = [...buffer.getAll()];
    this.gestureFrames = this.gestureBuffer.length;

    // Check for end conditions
    if (velocity < this.config.endThreshold) {
      this.stillFrameCount++;
    } else {
      this.stillFrameCount = 0;
    }

    // End gesture if:
    // 1. Enough consecutive still frames
    // 2. Or max frames exceeded
    const shouldEnd =
      this.stillFrameCount >= this.config.stillFramesToEnd ||
      this.gestureFrames >= this.config.maxGestureFrames;

    if (shouldEnd) {
      this.state = 'ended';
      this.stillFrameCount = 0;
    }

    return {
      state: this.state,
      isActive: true,
      completedGesture: null,
      velocity,
      gestureFrameCount: this.gestureFrames,
    };
  }

  private processEnded(): SegmenterResult {
    const completed = this.gestureBuffer.length >= this.config.minGestureFrames
      ? this.gestureBuffer
      : null;

    this.state = 'idle';
    this.gestureBuffer = [];
    this.gestureFrames = 0;
    this.stillFrameCount = 0;

    return {
      state: this.state,
      isActive: false,
      completedGesture: completed,
      velocity: 0,
      gestureFrameCount: 0,
    };
  }

  /** Reset the segmenter to idle state */
  reset(): void {
    this.state = 'idle';
    this.stillFrameCount = 0;
    this.gestureFrames = 0;
    this.gestureBuffer = [];
  }

  /** Get current state */
  getState(): GestureState {
    return this.state;
  }
}
