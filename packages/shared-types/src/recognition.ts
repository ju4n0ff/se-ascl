export enum ConfidenceLevel {
  LOW = 'low',
  MEDIUM = 'medium',
  HIGH = 'high',
}

export interface RecognitionResult {
  signId: string;
  gloss: string;
  spanishText: string;
  confidence: number;
  confidenceLevel: ConfidenceLevel;
  timestamp: number;
  isFingerspelling: boolean;
}

export interface RecognitionFeedback {
  handsDetected: boolean;
  lightingQuality: 'good' | 'poor';
  distanceQuality: 'optimal' | 'too_close' | 'too_far';
  message?: string;
}
