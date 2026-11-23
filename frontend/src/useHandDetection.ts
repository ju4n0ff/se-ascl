import { useEffect, useRef, useCallback, useState } from 'react';
import { HandLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';

interface HandLandmarkerResult {
  landmarks: { x: number; y: number; z: number }[][];
}

export interface HandDetectionState {
  isLoaded: boolean;
  isDetecting: boolean;
  error: string | null;
}

export function useHandDetection(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  onResults: (results: HandLandmarkerResult) => void
) {
  const handLandmarkerRef = useRef<HandLandmarker | null>(null);
  const animFrameRef = useRef<number>(0);
  const onResultsRef = useRef(onResults);
  const [state, setState] = useState<HandDetectionState>({
    isLoaded: false,
    isDetecting: false,
    error: null,
  });

  // Keep ref in sync with latest callback
  onResultsRef.current = onResults;

  const initialize = useCallback(async () => {
    try {
      setState((s) => ({ ...s, error: null }));

      const vision = await FilesetResolver.forVisionTasks(
        'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm'
      );

      const handLandmarker = await HandLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath:
            'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task',
          delegate: 'GPU',
        },
        runningMode: 'VIDEO',
        numHands: 2,
        minHandDetectionConfidence: 0.5,
        minHandPresenceConfidence: 0.5,
        minTrackingConfidence: 0.5,
      });

      handLandmarkerRef.current = handLandmarker;
      setState({ isLoaded: true, isDetecting: false, error: null });
    } catch (err) {
      console.error('[HandDetection] Init error:', err);
      setState((s) => ({
        ...s,
        error: err instanceof Error ? err.message : 'Error initializing hand detection',
      }));
    }
  }, []);

  const startDetection = useCallback(() => {
    if (!handLandmarkerRef.current || !videoRef.current) {
      console.warn('[HandDetection] Cannot start:', {
        handLandmarker: !!handLandmarkerRef.current,
        video: !!videoRef.current,
      });
      return;
    }

    console.log('[HandDetection] Starting detection loop');
    // Cancel any existing loop first
    cancelAnimationFrame(animFrameRef.current);

    let frameCount = 0;
    const detect = () => {
      if (!handLandmarkerRef.current || !videoRef.current) return;
      if (videoRef.current.readyState >= 2) {
        try {
          const results = handLandmarkerRef.current.detectForVideo(
            videoRef.current,
            performance.now()
          );
          if (frameCount % 60 === 0) {
            console.log('[HandDetection] Frame', frameCount, 'landmarks:', results.landmarks?.length ?? 0);
          }
          frameCount++;
          onResultsRef.current(results);
        } catch (err) {
          console.error('[HandDetection] Detection error:', err);
        }
      }
      animFrameRef.current = requestAnimationFrame(detect);
    };

    setState((s) => ({ ...s, isDetecting: true }));
    detect();
  }, [videoRef]);

  const stopDetection = useCallback(() => {
    cancelAnimationFrame(animFrameRef.current);
    setState((s) => ({ ...s, isDetecting: false }));
  }, []);

  useEffect(() => {
    initialize();
    return () => {
      cancelAnimationFrame(animFrameRef.current);
      handLandmarkerRef.current?.close();
    };
  }, [initialize]);

  return { ...state, startDetection, stopDetection };
}
