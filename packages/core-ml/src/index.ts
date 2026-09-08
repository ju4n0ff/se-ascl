import {
  RecognitionResult,
  ConfidenceLevel,
  Landmark3D,
  PipelineConfig,
  ModelConfig,
} from '@senascl/shared-types';

export interface ModelInterpreter {
  loadModel(modelPath: string): Promise<void>;
  predict(input: Float32Array): Promise<RecognitionResult[]>;
  dispose(): void;
}

export class TFLiteModel implements ModelInterpreter {
  private model: unknown = null;
  private config: ModelConfig;

  constructor(config: ModelConfig) {
    this.config = config;
  }

  async loadModel(modelPath: string): Promise<void> {
    // TODO: Load TFLite model via react-native-fast-tflite or ONNX Runtime
    // For now, store the path as placeholder
    this.model = { path: modelPath, loaded: true };
  }

  async predict(input: Float32Array): Promise<RecognitionResult[]> {
    if (!this.model) {
      throw new Error('Model not loaded. Call loadModel() first.');
    }

    // TODO: Run actual inference with TFLite
    // Placeholder: return empty results
    return [];
  }

  dispose(): void {
    this.model = null;
  }
}

export function landmarksToFloat32Array(landmarks: Landmark3D[]): Float32Array {
  const arr = new Float32Array(landmarks.length * 3);
  for (let i = 0; i < landmarks.length; i++) {
    arr[i * 3] = landmarks[i].x;
    arr[i * 3 + 1] = landmarks[i].y;
    arr[i * 3 + 2] = landmarks[i].z;
  }
  return arr;
}

export function getConfidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.8) return ConfidenceLevel.HIGH;
  if (confidence >= 0.5) return ConfidenceLevel.MEDIUM;
  return ConfidenceLevel.LOW;
}
