export interface ModelConfig {
  modelPath: string;
  numHands: number;
  minDetectionConfidence: number;
  minTrackingConfidence: number;
  useFaceLandmarks: boolean;
  usePoseLandmarks: boolean;
}

export interface PipelineConfig {
  model: ModelConfig;
  fingerspellingTimeoutMs: number;
  confidenceThreshold: number;
  maxHands: number;
}
