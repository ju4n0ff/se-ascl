import React, { useState, useCallback, useRef, useEffect } from 'react';
import { ConfidenceLevel, TranscriptEntry } from '@senascl/shared-types';
import { useHandDetection } from './useHandDetection';
import { classifySigns } from './classifySigns';

const HOLD_MS = 1000;
const COOLDOWN_MS = 600;

const App: React.FC = () => {
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [confidence, setConfidence] = useState<ConfidenceLevel>(ConfidenceLevel.LOW);
  const [statusMessage, setStatusMessage] = useState('Presiona "Iniciar cámara" para comenzar');
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
              ctx.fillStyle = '#1a73e8';
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
      if (isLoaded) startDetection();
    } catch {
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

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 16 }}>
      <header style={{ textAlign: 'center', padding: '24px 0' }}>
        <h1 style={{ fontSize: 36, fontWeight: 700, color: '#f0f6fc' }}>SeñasCL</h1>
        <p style={{ color: '#8b949e', marginTop: 4 }}>Intérprete LSCh → Texto</p>
      </header>

      {/* Gesto actual */}
      {isCameraActive && currentGesture && (
        <div style={{ textAlign: 'center', marginBottom: 12 }}>
          <div
            style={{
              display: 'inline-block',
              fontSize: 64,
              fontWeight: 700,
              color: '#f0f6fc',
              padding: '8px 24px',
              backgroundColor: '#21262d',
              borderRadius: 16,
              minWidth: 80,
            }}
          >
            {currentGesture}
          </div>
          <div
            style={{
              marginTop: 8,
              height: 4,
              backgroundColor: '#21262d',
              borderRadius: 2,
              overflow: 'hidden',
              maxWidth: 200,
              marginLeft: 'auto',
              marginRight: 'auto',
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${holdProgress * 100}%`,
                backgroundColor: holdProgress >= 1 ? '#3fb950' : '#1a73e8',
                borderRadius: 2,
                transition: 'width 0.05s linear',
              }}
            />
          </div>
          <p style={{ color: '#8b949e', fontSize: 12, marginTop: 4 }}>
            {holdProgress >= 1
              ? '✓ Letra registrada'
              : `Mantén ${HOLD_MS / 1000}s para registrar`}
          </p>
        </div>
      )}

      {/* Cámara */}
      <div
        style={{
          position: 'relative',
          borderRadius: 16,
          overflow: 'hidden',
          backgroundColor: '#161b22',
          marginBottom: 16,
        }}
      >
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          style={{
            width: '100%',
            display: isCameraActive ? 'block' : 'none',
            transform: 'scaleX(-1)',
          }}
        />
        <canvas
          ref={canvasRef}
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            height: '100%',
            pointerEvents: 'none',
            transform: 'scaleX(-1)',
          }}
        />
        {!isCameraActive && (
          <div
            style={{
              height: 360,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              alignItems: 'center',
            }}
          >
            <p style={{ fontSize: 20, color: '#f0f6fc' }}>📷 Cámara inactiva</p>
            <p style={{ color: '#8b949e', marginTop: 8 }}>
              Presiona "Iniciar" para comenzar
            </p>
          </div>
        )}
        {isCameraActive && (
          <div
            style={{
              position: 'absolute',
              top: 12,
              left: 12,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              backgroundColor: 'rgba(0,0,0,0.6)',
              padding: '6px 12px',
              borderRadius: 20,
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                backgroundColor: '#3fb950',
              }}
            />
            <span style={{ color: '#f0f6fc', fontSize: 12, fontWeight: 600 }}>
              {handsDetected} mano(s)
            </span>
          </div>
        )}
      </div>

      {cameraError && (
        <div
          style={{
            padding: '10px 16px',
            backgroundColor: '#f85149',
            color: '#fff',
            borderRadius: 8,
            marginBottom: 16,
            fontSize: 14,
          }}
        >
          {cameraError}
        </div>
      )}

      <p style={{ textAlign: 'center', color: '#8b949e', marginBottom: 16, fontSize: 14 }}>
        {statusMessage}
      </p>

      {/* Transcript */}
      <div
        style={{
          backgroundColor: '#161b22',
          borderRadius: 12,
          padding: 16,
          minHeight: 120,
          marginBottom: 16,
        }}
      >
        {transcript.length === 0 ? (
          <p style={{ color: '#8b949e', textAlign: 'center', padding: 24 }}>
            {isCameraActive ? 'Muestra una seña y mantenla...' : 'Inicia la cámara para comenzar'}
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {transcript.map((entry) => (
              <div
                key={entry.id}
                style={{
                  padding: '8px 12px',
                  backgroundColor: '#21262d',
                  borderRadius: 8,
                  fontSize: 18,
                  color: '#f0f6fc',
                }}
              >
                {entry.text}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Botones */}
      <div style={{ display: 'flex', gap: 12 }}>
        <button
          onClick={handleToggleCamera}
          style={{
            flex: 1,
            minHeight: 48,
            padding: '12px 24px',
            backgroundColor: '#1a73e8',
            color: '#fff',
            border: 'none',
            borderRadius: 12,
            fontSize: 16,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          {isCameraActive ? '⏸ Pausar' : '▶ Iniciar'}
        </button>
        <button
          onClick={handleSpeak}
          disabled={!fullText}
          style={{
            flex: 1,
            minHeight: 48,
            padding: '12px 24px',
            backgroundColor: '#238636',
            color: '#fff',
            border: 'none',
            borderRadius: 12,
            fontSize: 16,
            fontWeight: 600,
            cursor: fullText ? 'pointer' : 'not-allowed',
            opacity: fullText ? 1 : 0.5,
          }}
        >
          🔊 Hablar
        </button>
        <button
          onClick={handleClear}
          style={{
            flex: 1,
            minHeight: 48,
            padding: '12px 24px',
            backgroundColor: '#21262d',
            color: '#fff',
            border: 'none',
            borderRadius: 12,
            fontSize: 16,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          🗑 Limpiar
        </button>
      </div>

      <footer style={{ textAlign: 'center', padding: '32px 0', color: '#8b949e', fontSize: 12 }}>
        SeñasCL v0.1.0
      </footer>
    </div>
  );
};

export default App;
