import {
  HandLandmarks,
  FaceLandmarks,
  PoseLandmarks,
  Landmark3D,
} from '@senascl/shared-types';

export interface HandLandmarkerResult {
  handLandmarks: HandLandmarks[];
  handWorldLandmarks: Landmark3D[][];
  handednesses: string[];
}

export interface FaceLandmarkerResult {
  faceLandmarks: FaceLandmarks[];
  faceBlendshapes: unknown[];
}

export interface LandmarkExtractor {
  detectHands(imageData: ImageData): Promise<HandLandmarks[]>;
  detectFace(imageData: ImageData): Promise<FaceLandmarks | null>;
  detectPose(imageData: ImageData): Promise<PoseLandmarks | null>;
}

export class MediaPipeLandmarkExtractor implements LandmarkExtractor {
  private handLandmarker: unknown = null;
  private faceLandmarker: unknown = null;
  private initialized = false;

  async initialize(options?: {
    numHands?: number;
    minDetectionConfidence?: number;
    minTrackingConfidence?: number;
    detectFace?: boolean;
  }): Promise<void> {
    // TODO: Initialize MediaPipe Hand Landmarker and Face Landmarker
    // via native bindings (react-native-vision-camera frame processor plugin)
    // or via @mediapipe/tasks-vision for web
    this.initialized = true;
  }

  async detectHands(_imageData: ImageData): Promise<HandLandmarks[]> {
    if (!this.initialized) {
      throw new Error('LandmarkExtractor not initialized');
    }
    // TODO: Run MediaPipe Hand Landmarker inference
    return [];
  }

  async detectFace(_imageData: ImageData): Promise<FaceLandmarks | null> {
    if (!this.initialized) return null;
    // TODO: Run MediaPipe Face Landmarker inference
    return null;
  }

  async detectPose(_imageData: ImageData): Promise<PoseLandmarks | null> {
    // Pose detection is optional and planned for phase 2
    return null;
  }

  dispose(): void {
    this.handLandmarker = null;
    this.faceLandmarker = null;
    this.initialized = false;
  }
}

export { HandLandmarkerResult, FaceLandmarkerResult };
