import { useCallback, useEffect, useRef, useState } from 'react';
import { FaceLandmarker, FilesetResolver, HandLandmarker, PoseLandmarker } from '@mediapipe/tasks-vision';

export interface HolisticFrame {
  vector: number[]; // 1629 floats
  hasLeftHand: boolean;
  hasRightHand: boolean;
  hasPose: boolean;
}

interface UseHolisticCaptureOptions {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  onFrame?: (frame: HolisticFrame) => void;
  sampleEveryMs?: number;
}

const WASM_ROOT = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm';

function blockFromLandmarks(
  landmarks: Array<{ x: number; y: number; z: number }> | undefined,
  expected: number,
  aspect: number,
): number[] {
  const out = new Array(expected * 3).fill(0);
  if (!landmarks || landmarks.length === 0) return out;
  const n = Math.min(expected, landmarks.length);
  for (let i = 0; i < n; i++) {
    const lm = landmarks[i];
    out[i * 3] = lm.x;
    out[i * 3 + 1] = lm.y * aspect; // isotropic Y, same as training contract
    out[i * 3 + 2] = lm.z ?? 0;
  }
  return out;
}

export function useHolisticCapture({ videoRef, onFrame, sampleEveryMs = 66 }: UseHolisticCaptureOptions) {
  const [isLoaded, setIsLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  const poseRef = useRef<PoseLandmarker | null>(null);
  const handRef = useRef<HandLandmarker | null>(null);
  const faceRef = useRef<FaceLandmarker | null>(null);
  const rafRef = useRef<number>(0);
  const lastSampleRef = useRef(0);
  const onFrameRef = useRef(onFrame);
  onFrameRef.current = onFrame;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setError(null);
        const vision = await FilesetResolver.forVisionTasks(WASM_ROOT);
        const [pose, hands, face] = await Promise.all([
          PoseLandmarker.createFromOptions(vision, {
            baseOptions: {
              modelAssetPath:
                'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task',
              delegate: 'GPU',
            },
            runningMode: 'VIDEO',
            numPoses: 1,
            minPoseDetectionConfidence: 0.5,
            minPosePresenceConfidence: 0.5,
            minTrackingConfidence: 0.5,
          }),
          HandLandmarker.createFromOptions(vision, {
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
          }),
          FaceLandmarker.createFromOptions(vision, {
            baseOptions: {
              modelAssetPath:
                'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task',
              delegate: 'GPU',
            },
            runningMode: 'VIDEO',
            numFaces: 1,
            minFaceDetectionConfidence: 0.5,
            minFacePresenceConfidence: 0.5,
            minTrackingConfidence: 0.5,
            outputFaceBlendshapes: false,
            outputFacialTransformationMatrixes: false,
          }),
        ]);
        if (cancelled) {
          pose.close(); hands.close(); face.close();
          return;
        }
        poseRef.current = pose;
        handRef.current = hands;
        faceRef.current = face;
        setIsLoaded(true);
      } catch (e) {
        console.error('[HolisticCapture] init error', e);
        if (!cancelled) setError(e instanceof Error ? e.message : 'Error inicializando MediaPipe');
      }
    })();
    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);
      poseRef.current?.close(); poseRef.current = null;
      handRef.current?.close(); handRef.current = null;
      faceRef.current?.close(); faceRef.current = null;
    };
  }, []);

  const start = useCallback(() => {
    if (!poseRef.current || !handRef.current || !faceRef.current || !videoRef.current) return;
    cancelAnimationFrame(rafRef.current);
    setIsRunning(true);

    const loop = () => {
      const video = videoRef.current;
      const pose = poseRef.current;
      const hand = handRef.current;
      const face = faceRef.current;
      if (!video || !pose || !hand || !face) return;

      const now = performance.now();
      if (video.readyState >= 2 && now - lastSampleRef.current >= sampleEveryMs) {
        lastSampleRef.current = now;
        try {
          const w = video.videoWidth || 640;
          const h = video.videoHeight || 480;
          const aspect = h / w;

          const poseRes = pose.detectForVideo(video, now);
          const handRes = hand.detectForVideo(video, now);
          const faceRes = face.detectForVideo(video, now);

          const poseLm = poseRes.landmarks?.[0];
          const faceLm = faceRes.faceLandmarks?.[0];

          // HandLandmarker: handedness is from the subject's perspective in MediaPipe tasks;
          // we map to dataset convention where left/right are subject hands.
          let left: Array<{ x: number; y: number; z: number }> | undefined;
          let right: Array<{ x: number; y: number; z: number }> | undefined;
          const handed = handRes.handedness ?? [];
          const hLms = handRes.landmarks ?? [];
          for (let i = 0; i < hLms.length; i++) {
            const label = handed[i]?.[0]?.categoryName;
            if (label === 'Left') left = hLms[i] as any;
            else if (label === 'Right') right = hLms[i] as any;
            else if (!right) right = hLms[i] as any;
            else if (!left) left = hLms[i] as any;
          }

          const vector = [
            ...blockFromLandmarks(poseLm as any, 33, aspect),
            ...blockFromLandmarks(faceLm as any, 468, aspect),
            ...blockFromLandmarks(left, 21, aspect),
            ...blockFromLandmarks(right, 21, aspect),
          ];

          onFrameRef.current?.({
            vector,
            hasLeftHand: !!left,
            hasRightHand: !!right,
            hasPose: !!poseLm,
          });
        } catch (e) {
          console.error('[HolisticCapture] frame error', e);
        }
      }
      rafRef.current = requestAnimationFrame(loop);
    };

    rafRef.current = requestAnimationFrame(loop);
  }, [sampleEveryMs, videoRef]);

  const stop = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    setIsRunning(false);
  }, []);

  return { isLoaded, isRunning, error, start, stop };
}
