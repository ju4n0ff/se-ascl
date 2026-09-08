export interface Landmark3D {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

export interface HandLandmarks {
  landmarks: Landmark3D[];
  handedness: 'Left' | 'Right';
}

export interface FaceLandmarks {
  landmarks: Landmark3D[];
  leftEyeOpenProbability?: number;
  rightEyeOpenProbability?: number;
  smileProbability?: number;
}

export interface PoseLandmarks {
  landmarks: Landmark3D[];
}
