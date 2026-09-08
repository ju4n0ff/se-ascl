import { RecognitionResult, ConfidenceLevel } from '@senascl/shared-types';

interface Landmark {
  x: number;
  y: number;
  z: number;
}

function dist(a: Landmark, b: Landmark): number {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

function classifyAlphabet(landmarks: Landmark[]): { letter: string; confidence: number } | null {
  const wrist = landmarks[0];

  // Finger extension: tip must be clearly above PIP
  const indexUp = landmarks[8].y < landmarks[6].y - 0.03;
  const middleUp = landmarks[12].y < landmarks[10].y - 0.03;
  const ringUp = landmarks[16].y < landmarks[14].y - 0.03;
  const pinkyUp = landmarks[20].y < landmarks[18].y - 0.03;

  // Thumb: tip far from index MCP (open hand spread)
  const thumbTip = landmarks[4];
  const indexMcp = landmarks[5];
  const thumbSpread = dist(thumbTip, indexMcp) > 0.08;

  const upCount = [indexUp, middleUp, ringUp, pinkyUp].filter(Boolean).length;

  // Y: shaka — thumb + pinky ONLY
  if (thumbSpread && !indexUp && !middleUp && !ringUp && pinkyUp)
    return { letter: 'Y', confidence: 0.9 };

  // I: pinky ONLY
  if (!thumbSpread && !indexUp && !middleUp && !ringUp && pinkyUp)
    return { letter: 'I', confidence: 0.9 };

  // L: thumb + index, others down
  if (thumbSpread && indexUp && !middleUp && !ringUp && !pinkyUp)
    return { letter: 'L', confidence: 0.9 };

  // V: index + middle up, ring + pinky down
  if (!thumbSpread && indexUp && middleUp && !ringUp && !pinkyUp)
    return { letter: 'V', confidence: 0.9 };

  // D: index ONLY up
  if (!thumbSpread && indexUp && !middleUp && !ringUp && !pinkyUp)
    return { letter: 'D', confidence: 0.85 };

  // W: index + middle + ring, pinky down
  if (!thumbSpread && indexUp && middleUp && ringUp && !pinkyUp)
    return { letter: 'W', confidence: 0.85 };

  // K: index + middle up, thumb spread (but not V)
  if (thumbSpread && indexUp && middleUp && !ringUp && !pinkyUp)
    return { letter: 'K', confidence: 0.7 };

  // T: thumb between index and middle (index curved)
  if (thumbSpread && indexUp && middleUp && ringUp && pinkyUp)
    return { letter: 'T', confidence: 0.6 };

  // F: index down, middle + ring + pinky up
  if (!thumbSpread && !indexUp && middleUp && ringUp && pinkyUp)
    return { letter: 'F', confidence: 0.8 };

  // H: index + middle up (same as V but different context)
  if (!thumbSpread && indexUp && middleUp && ringUp && pinkyUp)
    return { letter: 'H', confidence: 0.7 };

  // S: closed fist — nothing up, thumb in
  if (upCount === 0 && !thumbSpread)
    return { letter: 'S', confidence: 0.85 };

  // A: thumb out, fingers closed
  if (thumbSpread && upCount === 0)
    return { letter: 'A', confidence: 0.85 };

  // B: all fingers up, thumb in
  if (!thumbSpread && upCount === 4)
    return { letter: 'B', confidence: 0.85 };

  // Numbers
  if (!thumbSpread && indexUp && !middleUp && !ringUp && !pinkyUp)
    return { letter: '1', confidence: 0.8 };
  if (!thumbSpread && indexUp && middleUp && !ringUp && !pinkyUp)
    return { letter: '2', confidence: 0.8 };
  if (!thumbSpread && indexUp && middleUp && ringUp && !pinkyUp)
    return { letter: '3', confidence: 0.8 };

  return null;
}

export function classifySigns(results: {
  landmarks?: { x: number; y: number; z: number }[][];
}): RecognitionResult[] {
  const detections: RecognitionResult[] = [];

  if (!results.landmarks || results.landmarks.length === 0) {
    return detections;
  }

  for (const handLandmarks of results.landmarks) {
    const classification = classifyAlphabet(handLandmarks);

    if (classification) {
      detections.push({
        signId: classification.letter,
        gloss: classification.letter,
        spanishText: classification.letter,
        confidence: classification.confidence,
        confidenceLevel:
          classification.confidence >= 0.8
            ? ConfidenceLevel.HIGH
            : classification.confidence >= 0.6
            ? ConfidenceLevel.MEDIUM
            : ConfidenceLevel.LOW,
        timestamp: Date.now(),
        isFingerspelling: true,
      });
    }
  }

  return detections;
}
