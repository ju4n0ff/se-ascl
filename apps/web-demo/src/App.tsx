import React, { useState, useCallback, useRef, useEffect } from 'react';
import { ConfidenceLevel, TranscriptEntry } from '@senascl/shared-types';
import { useHandDetection } from './useHandDetection';
import { classifySigns } from './classifySigns';
import {
  Button,
  Card,
  ConfidenceIndicator,
  SignChip,
  ProgressBar,
  AlertOverlay,
  Waveform,
} from './components';
import './styles.css';

const HOLD_MS = 1000;
const COOLDOWN_MS = 600;

const App: React.FC = () => {
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [confidence, setConfidence] = useState<ConfidenceLevel>(ConfidenceLevel.LOW);
  const [statusMessage, setStatusMessage] = useState('Presiona "Iniciar" para comenzar');
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [fullText, setFullText] = useState('');
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [handsDetected, setHandsDetected] = useState(0);
  const [currentGesture, setCurrentGesture] = useState<string>('');
  const [holdProgress, setHoldProgress] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const entryIdCounter = useRef(0);
  const lastSignRef = useRef('');
  const lastSignTimeRef = useRef(0);
  const holdTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cooldownTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const holdStartTimeRef = useRef(0);
  const holdAnimRef = useRef<number>(0);

  const updateHoldProgress = useCallback(() => {
    const elapsed = Date.now() - holdStartTimeRef.current;
    const progress = Math.min(1, elapsed / HOLD_MS);
    setHoldProgress(progress);
    if (progress < 1) {
      holdAnimRef.current = requestAnimationFrame(updateHoldProgress);
    }
  }, []);

  const onResults = useCallback(
    (results: { landmarks?: { x: number; y: number; z: number }[][] }) => {
      const count = results.landmarks?.length ?? 0;
      setHandsDetected(count);

      if (count > 0) {
        setConfidence(ConfidenceLevel.HIGH);
        setStatusMessage(`${count} mano(s) detectada(s)`);

        const detections = classifySigns(results);
        const now = Date.now();

        if (detections.length > 0) {
          const best = detections[0];
          const isSame = best.signId === lastSignRef.current;
          const isCoolingDown = now - lastSignTimeRef.current < COOLDOWN_MS;

          setCurrentGesture(best.signId);

          if (isCoolingDown) {
            // During cooldown, don't register new signs
          } else if (!isSame) {
            // New gesture detected — start hold timer
            if (holdTimeoutRef.current) clearTimeout(holdTimeoutRef.current);
            cancelAnimationFrame(holdAnimRef.current);
            lastSignRef.current = best.signId;
            holdStartTimeRef.current = now;
            holdAnimRef.current = requestAnimationFrame(updateHoldProgress);

            holdTimeoutRef.current = setTimeout(() => {
              entryIdCounter.current += 1;
              const entry: TranscriptEntry = {
                id: String(entryIdCounter.current),
                text: best.spanishText,
                timestamp: now,
                isFingerspelled: best.isFingerspelling,
                rawSigns: [best],
              };
              setTranscript((prev) => [...prev, entry]);
              setFullText((prev) => prev + best.spanishText);
              lastSignRef.current = '';
              lastSignTimeRef.current = Date.now();
              setHoldProgress(0);
              cancelAnimationFrame(holdAnimRef.current);
            }, HOLD_MS);
          }
        } else {
          setCurrentGesture('');
          setHoldProgress(0);
          cancelAnimationFrame(holdAnimRef.current);
        }
      } else {
        setConfidence(ConfidenceLevel.LOW);
        setStatusMessage('Esperando manos...');
        setCurrentGesture('');
        setHoldProgress(0);
        cancelAnimationFrame(holdAnimRef.current);
        if (holdTimeoutRef.current) {
          clearTimeout(holdTimeoutRef.current);
          holdTimeoutRef.current = null;
        }
        lastSignRef.current = '';
      }

      // Draw landmarks
      if (canvasRef.current && videoRef.current) {
        const ctx = canvasRef.current.getContext('2d');
        if (ctx) {
          canvasRef.current.width = videoRef.current.videoWidth;
          canvasRef.current.height = videoRef.current.videoHeight;
          ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
          if (results.landmarks) {
            for (const hand of results.landmarks) {
              ctx.fillStyle = '#E8725C';
              for (const point of hand) {
                ctx.beginPath();
                ctx.arc(
                  point.x * canvasRef.current.width,
                  point.y * canvasRef.current.height,
                  3,
                  0,
                  2 * Math.PI
                );
                ctx.fill();
              }
            }
          }
        }
      }
    },
    [updateHoldProgress]
  );

  const { isLoaded, error: handError, startDetection, stopDetection } =
    useHandDetection(videoRef, onResults);

  // Auto-start detection when MediaPipe finishes loading and camera is active
  const isDetectionStartedRef = useRef(false);
  useEffect(() => {
    if (isLoaded && isCameraActive && streamRef.current && !isDetectionStartedRef.current) {
      isDetectionStartedRef.current = true;
      startDetection();
    }
    if (!isCameraActive) {
      isDetectionStartedRef.current = false;
    }
  }, [isLoaded, isCameraActive, startDetection]);

  const startCamera = useCallback(async () => {
    try {
      setCameraError(null);
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: 640, height: 480 },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setIsCameraActive(true);
      setStatusMessage('Cámara activa — esperando manos...');
      console.log('[App] Camera started, isLoaded:', isLoaded);
      if (isLoaded) {
        isDetectionStartedRef.current = true;
        startDetection();
      }
    } catch (err) {
      console.error('[App] Camera error:', err);
      setCameraError('No se pudo acceder a la cámara. Verifica los permisos.');
      setStatusMessage('Error de cámara');
    }
  }, [isLoaded, startDetection]);

  const stopCamera = useCallback(() => {
    stopDetection();
    if (holdTimeoutRef.current) clearTimeout(holdTimeoutRef.current);
    if (cooldownTimeoutRef.current) clearTimeout(cooldownTimeoutRef.current);
    cancelAnimationFrame(holdAnimRef.current);
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    setIsCameraActive(false);
    setCurrentGesture('');
    setHoldProgress(0);
    setStatusMessage('Cámara pausada');
  }, [stopDetection]);

  useEffect(() => {
    return () => {
      stopDetection();
      if (holdTimeoutRef.current) clearTimeout(holdTimeoutRef.current);
      if (cooldownTimeoutRef.current) clearTimeout(cooldownTimeoutRef.current);
      cancelAnimationFrame(holdAnimRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
    };
  }, [stopDetection]);

  const handleToggleCamera = useCallback(() => {
    if (isCameraActive) stopCamera();
    else startCamera();
  }, [isCameraActive, startCamera, stopCamera]);

  const handleSpeak = useCallback(() => {
    if (!fullText) return;
    const u = new SpeechSynthesisUtterance(fullText);
    u.lang = 'es-CL';
    window.speechSynthesis.speak(u);
  }, [fullText]);

  const handleClear = useCallback(() => {
    setTranscript([]);
    setFullText('');
    lastSignRef.current = '';
    setStatusMessage('Transcripción limpiada');
  }, []);

  const confidenceLevel: 'high' | 'medium' | 'low' =
    confidence === ConfidenceLevel.HIGH
      ? 'high'
      : confidence === ConfidenceLevel.MEDIUM
      ? 'medium'
      : 'low';

  return (
    <div className="container">
      {/* Decorative background blobs */}
      <div className="blob blob-1" aria-hidden="true" />
      <div className="blob blob-2" aria-hidden="true" />

      {/* Header */}
      <header className="header">
        <h1 className="header-title">SeñasCL</h1>
        <p className="header-subtitle">Intérprete de Lengua de Señas Chilena</p>
      </header>

      {/* Current gesture display */}
      {isCameraActive && currentGesture && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 'var(--space-3)',
            marginBottom: 'var(--space-4)',
          }}
        >
          <SignChip letter={currentGesture} />
          <ProgressBar progress={holdProgress} complete={holdProgress >= 1} />
          <p
            style={{
              color: 'var(--color-text-secondary)',
              fontSize: 'var(--font-size-xs)',
              fontFamily: 'var(--font-family)',
            }}
          >
            {holdProgress >= 1
              ? '✓ Letra registrada'
              : `Mantén ${HOLD_MS / 1000}s para registrar`}
          </p>
        </div>
      )}

      {/* Camera view */}
      <div className="camera-container">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="camera-video"
          style={{ display: isCameraActive ? 'block' : 'none' }}
        />
        <canvas ref={canvasRef} className="camera-canvas" />

        {/* Animated frame border */}
        <div className={`camera-frame ${isCameraActive ? 'active' : ''}`} />

        {/* Confidence indicator */}
        {isCameraActive && (
          <ConfidenceIndicator
            level={confidenceLevel}
            handsDetected={handsDetected}
          />
        )}

        {/* Camera off state */}
        {!isCameraActive && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 'var(--space-4)',
              padding: 'var(--space-8)',
            }}
          >
            <span
              style={{
                fontSize: '64px',
                opacity: 0.4,
                animation: 'breathe 3s ease-in-out infinite',
              }}
              aria-hidden="true"
            >
              📷
            </span>
            <p
              style={{
                fontSize: 'var(--font-size-xl)',
                color: 'var(--color-text-primary)',
                fontWeight: 600,
                fontFamily: 'var(--font-family)',
              }}
            >
              Cámara inactiva
            </p>
            <p
              style={{
                color: 'var(--color-text-secondary)',
                fontSize: 'var(--font-size-sm)',
                fontFamily: 'var(--font-family)',
              }}
            >
              Presiona "Iniciar" para comenzar a interpretar señas
            </p>
          </div>
        )}

        {/* Alert overlays */}
        <AlertOverlay
          icon="💡"
          message="Mejora la iluminación para mejor detección"
          visible={isCameraActive && confidence === ConfidenceLevel.LOW && handsDetected > 0}
        />
        <AlertOverlay
          icon="👋"
          message="Acerca tus manos al centro del encuadre"
          visible={isCameraActive && handsDetected === 0}
        />
      </div>

      {/* Error message */}
      {cameraError && (
        <div
          style={{
            padding: 'var(--space-3) var(--space-4)',
            backgroundColor: 'var(--color-error)',
            color: 'var(--color-text-inverse)',
            borderRadius: 'var(--radius-lg)',
            marginTop: 'var(--space-4)',
            fontSize: 'var(--font-size-sm)',
            fontWeight: 500,
            fontFamily: 'var(--font-family)',
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
          }}
          role="alert"
        >
          <span>⚠</span>
          {cameraError}
        </div>
      )}

      {/* Hand detection error */}
      {handError && (
        <div
          style={{
            padding: 'var(--space-3) var(--space-4)',
            backgroundColor: 'var(--color-error)',
            color: 'var(--color-text-inverse)',
            borderRadius: 'var(--radius-lg)',
            marginTop: 'var(--space-4)',
            fontSize: 'var(--font-size-sm)',
            fontWeight: 500,
            fontFamily: 'var(--font-family)',
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
          }}
          role="alert"
        >
          <span>⚠</span>
          Error de detección: {handError}
        </div>
      )}

      {/* Status message */}
      <p
        style={{
          textAlign: 'center',
          color: 'var(--color-text-secondary)',
          margin: 'var(--space-4) 0',
          fontSize: 'var(--font-size-sm)',
          fontFamily: 'var(--font-family)',
        }}
      >
        {statusMessage}
      </p>

      {/* Transcript */}
      <Card variant="default" padding="md">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 'var(--space-4)',
          }}
        >
          <h2
            style={{
              fontSize: 'var(--font-size-lg)',
              fontWeight: 700,
              color: 'var(--color-text-primary)',
              fontFamily: 'var(--font-family)',
            }}
          >
            Transcripción
          </h2>
          {fullText && <Waveform isPlaying={false} barCount={5} />}
        </div>

        <div
          style={{
            minHeight: '120px',
            maxHeight: '300px',
            overflowY: 'auto',
          }}
        >
          {transcript.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state-icon" aria-hidden="true">
                ✋
              </span>
              <p className="empty-state-text">
                {isCameraActive
                  ? 'Muestra una seña y mantenla...'
                  : 'Inicia la cámara para comenzar a traducir'}
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              {transcript.map((entry) => (
                <div key={entry.id} className="transcript-entry">
                  <span className="transcript-text">{entry.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* Action buttons */}
      <div
        style={{
          display: 'flex',
          gap: 'var(--space-3)',
          marginTop: 'var(--space-6)',
        }}
      >
        <Button
          variant="primary"
          size="lg"
          onClick={handleToggleCamera}
          style={{ flex: 1 }}
        >
          {isCameraActive ? '⏸ Pausar' : '▶ Iniciar cámara'}
        </Button>

        <Button
          variant="success"
          size="lg"
          onClick={handleSpeak}
          disabled={!fullText}
          style={{ flex: 1 }}
        >
          🔊 Hablar
        </Button>

        <Button
          variant="secondary"
          size="lg"
          onClick={handleClear}
          disabled={transcript.length === 0}
        >
          🗑
        </Button>
      </div>

      {/* Footer */}
      <footer className="footer">
        <p>SeñasCL v0.1.0 — Hecho con ❤️ para la comunidad sorda chilena</p>
      </footer>
    </div>
  );
};

export default App;
