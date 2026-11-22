import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ConfidenceLevel, TranscriptEntry } from '@senascl/shared-types';
import { classifySigns } from './classifySigns';
import { useHandDetection } from './useHandDetection';
import { useHolisticCapture } from './useHolisticCapture';
import { useBackendSocket, BackendResult } from './useBackendSocket';
import {
  AlertOverlay,
  Button,
  Card,
  ConfidenceIndicator,
  ProgressBar,
  SignChip,
  Waveform,
} from './components';
import './styles.css';

const HOLD_MS = 1000;
const COOLDOWN_MS = 600;
const LSCH_START_FRAMES = 3;
const LSCH_END_FRAMES = 10;
const LSCH_MIN_FRAMES = 12;
const LSCH_MAX_FRAMES = 90;

type AppMode = 'static' | 'lsch_v3';

const App: React.FC = () => {
  const [mode, setMode] = useState<AppMode>('lsch_v3');
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [confidence, setConfidence] = useState<ConfidenceLevel>(ConfidenceLevel.LOW);
  const [statusMessage, setStatusMessage] = useState('Presiona "Iniciar" para comenzar');
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [fullText, setFullText] = useState('');
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [handsDetected, setHandsDetected] = useState(0);
  const [currentGesture, setCurrentGesture] = useState('');
  const [holdProgress, setHoldProgress] = useState(0);
  const [lastPrediction, setLastPrediction] = useState<BackendResult | null>(null);
  const [isRecordingDynamic, setIsRecordingDynamic] = useState(false);
  const [dynamicFrames, setDynamicFrames] = useState(0);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const entryIdCounter = useRef(0);
  const lastSignRef = useRef('');
  const lastSignTimeRef = useRef(0);
  const holdTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const holdStartTimeRef = useRef(0);
  const holdAnimRef = useRef<number>(0);

  const lschBufferRef = useRef<number[][]>([]);
  const lschPrevRef = useRef<number[][]>([]);
  const lschHandsStreakRef = useRef(0);
  const lschNoHandsStreakRef = useRef(0);
  const lschRecordingRef = useRef(false);
  const lastSentLschAtRef = useRef(0);

  const addTranscript = useCallback((text: string, isFingerspelled: boolean, rawSigns: any[] = []) => {
    if (!text.trim()) return;
    entryIdCounter.current += 1;
    const entry: TranscriptEntry = {
      id: String(entryIdCounter.current),
      text,
      timestamp: Date.now(),
      isFingerspelled,
      rawSigns,
    };
    setTranscript((prev) => [...prev, entry]);
    setFullText((prev) => (prev ? `${prev} ${text}` : text));
  }, []);

  const handleBackendResult = useCallback((result: BackendResult) => {
    setLastPrediction(result);
    if (result.mode === 'lsch_v3') {
      if (result.accepted && result.spanish_text) {
        setConfidence(result.confidence >= 0.75 ? ConfidenceLevel.HIGH : ConfidenceLevel.MEDIUM);
        addTranscript(result.spanish_text, false);
        setStatusMessage(`LSCh v3: ${result.spanish_text} (${Math.round(result.confidence * 100)}%)`);
      } else if (result.predicted_label && result.predicted_label !== 'UNKNOWN') {
        setStatusMessage(`Baja confianza: ${result.predicted_label} (${Math.round(result.confidence * 100)}%)`);
        setConfidence(ConfidenceLevel.LOW);
      }
      return;
    }

    if (result.mode === 'dynamic' && result.confidence > 0.5 && result.spanish_text) {
      addTranscript(result.spanish_text, false);
    }
  }, [addTranscript]);

  const { isConnected: backendConnected, error: backendError, sendLschV3 } = useBackendSocket({
    enabled: isCameraActive,
    onResult: handleBackendResult,
  });

  const updateHoldProgress = useCallback(() => {
    const elapsed = Date.now() - holdStartTimeRef.current;
    const progress = Math.min(1, elapsed / HOLD_MS);
    setHoldProgress(progress);
    if (progress < 1) holdAnimRef.current = requestAnimationFrame(updateHoldProgress);
  }, []);

  const onStaticResults = useCallback((results: { landmarks?: { x: number; y: number; z: number }[][] }) => {
    if (mode !== 'static') return;
    const count = results.landmarks?.length ?? 0;
    setHandsDetected(count);

    if (canvasRef.current && videoRef.current) {
      const ctx = canvasRef.current.getContext('2d');
      if (ctx) {
        canvasRef.current.width = videoRef.current.videoWidth;
        canvasRef.current.height = videoRef.current.videoHeight;
        ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
        for (const hand of results.landmarks ?? []) {
          ctx.fillStyle = '#E8725C';
          for (const p of hand) {
            ctx.beginPath();
            ctx.arc(p.x * canvasRef.current.width, p.y * canvasRef.current.height, 3, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
    }

    if (count === 0) {
      setConfidence(ConfidenceLevel.LOW);
      setStatusMessage('Esperando manos...');
      setCurrentGesture('');
      setHoldProgress(0);
      cancelAnimationFrame(holdAnimRef.current);
      if (holdTimeoutRef.current) { clearTimeout(holdTimeoutRef.current); holdTimeoutRef.current = null; }
      lastSignRef.current = '';
      return;
    }

    setConfidence(ConfidenceLevel.HIGH);
    setStatusMessage(`${count} mano(s) detectada(s)`);
    const detections = classifySigns(results as any);
    const now = Date.now();
    if (detections.length === 0) {
      setCurrentGesture('');
      setHoldProgress(0);
      cancelAnimationFrame(holdAnimRef.current);
      return;
    }

    const best = detections[0];
    const isSame = best.signId === lastSignRef.current;
    const isCoolingDown = now - lastSignTimeRef.current < COOLDOWN_MS;
    setCurrentGesture(best.signId);

    if (isCoolingDown || isSame) return;

    if (holdTimeoutRef.current) clearTimeout(holdTimeoutRef.current);
    cancelAnimationFrame(holdAnimRef.current);
    lastSignRef.current = best.signId;
    holdStartTimeRef.current = now;
    holdAnimRef.current = requestAnimationFrame(updateHoldProgress);

    holdTimeoutRef.current = setTimeout(() => {
      addTranscript(best.spanishText, best.isFingerspelling, [best]);
      lastSignRef.current = '';
      lastSignTimeRef.current = Date.now();
      setHoldProgress(0);
      cancelAnimationFrame(holdAnimRef.current);
    }, HOLD_MS);
  }, [addTranscript, mode, updateHoldProgress]);

  const { isLoaded: staticLoaded, error: staticError, startDetection: startStatic, stopDetection: stopStatic } =
    useHandDetection(videoRef, onStaticResults);

  const onHolisticFrame = useCallback((frame: { vector: number[]; hasLeftHand: boolean; hasRightHand: boolean }) => {
    if (mode !== 'lsch_v3') return;
    const hasHands = frame.hasLeftHand || frame.hasRightHand;
    setHandsDetected((frame.hasLeftHand ? 1 : 0) + (frame.hasRightHand ? 1 : 0));

    if (canvasRef.current && videoRef.current) {
      const ctx = canvasRef.current.getContext('2d');
      if (ctx) {
        canvasRef.current.width = videoRef.current.videoWidth;
        canvasRef.current.height = videoRef.current.videoHeight;
        ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
      }
    }

    if (!lschRecordingRef.current) {
      lschPrevRef.current.push(frame.vector);
      if (lschPrevRef.current.length > LSCH_START_FRAMES) lschPrevRef.current.shift();
      if (hasHands) lschHandsStreakRef.current += 1;
      else lschHandsStreakRef.current = 0;

      if (lschHandsStreakRef.current >= LSCH_START_FRAMES) {
        lschRecordingRef.current = true;
        setIsRecordingDynamic(true);
        lschBufferRef.current = [...lschPrevRef.current];
        lschNoHandsStreakRef.current = 0;
        setStatusMessage('Grabando seña...');
      }
      return;
    }

    lschBufferRef.current.push(frame.vector);
    setDynamicFrames(lschBufferRef.current.length);
    if (hasHands) lschNoHandsStreakRef.current = 0;
    else lschNoHandsStreakRef.current += 1;

    const shouldEnd = lschNoHandsStreakRef.current >= LSCH_END_FRAMES || lschBufferRef.current.length >= LSCH_MAX_FRAMES;
    if (!shouldEnd) return;

    const trimmed = lschNoHandsStreakRef.current > 0
      ? lschBufferRef.current.slice(0, Math.max(0, lschBufferRef.current.length - lschNoHandsStreakRef.current))
      : lschBufferRef.current.slice();

    lschRecordingRef.current = false;
    setIsRecordingDynamic(false);
    setDynamicFrames(0);
    lschBufferRef.current = [];
    lschPrevRef.current = [];
    lschHandsStreakRef.current = 0;
    lschNoHandsStreakRef.current = 0;

    if (trimmed.length < LSCH_MIN_FRAMES) {
      setStatusMessage('Seña muy corta, intenta de nuevo');
      return;
    }

    const now = Date.now();
    if (now - lastSentLschAtRef.current < 300) return;
    lastSentLschAtRef.current = now;

    if (!backendConnected) {
      setStatusMessage('Backend no conectado. Inicia el servidor en localhost:8000');
      return;
    }

    setStatusMessage(`Enviando ${trimmed.length} frames al modelo LSCh v3...`);
    sendLschV3(trimmed, 3);
  }, [backendConnected, mode, sendLschV3]);

  const { isLoaded: holisticLoaded, error: holisticError, start: startHolistic, stop: stopHolistic } =
    useHolisticCapture({ videoRef, onFrame: onHolisticFrame, sampleEveryMs: 66 });

  const activeLoaded = mode === 'static' ? staticLoaded : holisticLoaded;
  const activeError = mode === 'static' ? staticError : holisticError;

  useEffect(() => {
    if (!isCameraActive || !streamRef.current || !activeLoaded) return;
    if (mode === 'static') startStatic();
    else startHolistic();
    return () => {
      if (mode === 'static') stopStatic();
      else stopHolistic();
    };
  }, [activeLoaded, isCameraActive, mode, startHolistic, startStatic, stopHolistic, stopStatic]);

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
      setStatusMessage(mode === 'lsch_v3' ? 'Cámara activa — esperando seña...' : 'Cámara activa — esperando manos...');
    } catch (err) {
      console.error('[App] Camera error:', err);
      setCameraError('No se pudo acceder a la cámara. Verifica los permisos.');
      setStatusMessage('Error de cámara');
    }
  }, [mode]);

  const stopCamera = useCallback(() => {
    stopStatic();
    stopHolistic();
    if (holdTimeoutRef.current) clearTimeout(holdTimeoutRef.current);
    cancelAnimationFrame(holdAnimRef.current);
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    setIsCameraActive(false);
    setIsRecordingDynamic(false);
    setDynamicFrames(0);
    lschRecordingRef.current = false;
    lschBufferRef.current = [];
    lschPrevRef.current = [];
    setCurrentGesture('');
    setHoldProgress(0);
    setStatusMessage('Cámara pausada');
  }, [stopHolistic, stopStatic]);

  useEffect(() => () => stopCamera(), [stopCamera]);

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
    setLastPrediction(null);
    lastSignRef.current = '';
    setStatusMessage('Transcripción limpiada');
  }, []);

  const confidenceLevel: 'high' | 'medium' | 'low' =
    confidence === ConfidenceLevel.HIGH ? 'high' : confidence === ConfidenceLevel.MEDIUM ? 'medium' : 'low';

  return (
    <div className="container">
      <div className="blob blob-1" aria-hidden="true" />
      <div className="blob blob-2" aria-hidden="true" />

      <header className="header">
        <h1 className="header-title">SeñasCL</h1>
        <p className="header-subtitle">Intérprete de Lengua de Señas Chilena</p>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 8, flexWrap: 'wrap' }}>
          <Button variant={mode === 'lsch_v3' ? 'primary' : 'secondary'} size="sm" onClick={() => setMode('lsch_v3')} disabled={isCameraActive}>
            Modelo LSCh v3
          </Button>
          <Button variant={mode === 'static' ? 'primary' : 'secondary'} size="sm" onClick={() => setMode('static')} disabled={isCameraActive}>
            Deletreo estático
          </Button>
        </div>
        {isCameraActive && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 'var(--font-size-xs)', color: backendConnected ? '#2e7d32' : 'var(--color-text-secondary)', marginTop: 4, justifyContent: 'center' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: backendConnected ? '#2e7d32' : '#999' }} />
            {backendConnected ? 'Backend conectado' : 'Sin backend (LSCh v3 requiere backend)'}
          </div>
        )}
      </header>

      {mode === 'static' && isCameraActive && currentGesture && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
          <SignChip letter={currentGesture} />
          <ProgressBar progress={holdProgress} complete={holdProgress >= 1} />
          <p style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--font-size-xs)' }}>
            {holdProgress >= 1 ? '✓ Letra registrada' : `Mantén ${HOLD_MS / 1000}s para registrar`}
          </p>
        </div>
      )}

      {mode === 'lsch_v3' && isCameraActive && (
        <Card variant="default" padding="md">
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontWeight: 700 }}>{isRecordingDynamic ? 'Grabando seña...' : 'Esperando seña'}</div>
              <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>
                Frames: {dynamicFrames} {lastPrediction?.latency_ms ? `· latencia ${lastPrediction.latency_ms}ms` : ''}
              </div>
            </div>
            {lastPrediction?.top_k && lastPrediction.top_k.length > 0 && (
              <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>
                Top: {lastPrediction.top_k.slice(0, 3).map((x) => `${x.texto} ${Math.round(x.confianza * 100)}%`).join(' · ')}
              </div>
            )}
          </div>
        </Card>
      )}

      <div className="camera-container">
        <video ref={videoRef} autoPlay playsInline muted className="camera-video" style={{ display: isCameraActive ? 'block' : 'none' }} />
        <canvas ref={canvasRef} className="camera-canvas" />
        <div className={`camera-frame ${isCameraActive ? 'active' : ''}`} />
        {isCameraActive && <ConfidenceIndicator level={confidenceLevel} handsDetected={handsDetected} />}

        {!isCameraActive && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 'var(--space-4)', padding: 'var(--space-8)' }}>
            <span style={{ fontSize: 64, opacity: 0.4, animation: 'breathe 3s ease-in-out infinite' }} aria-hidden="true">📷</span>
            <p style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600 }}>Cámara inactiva</p>
            <p style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--font-size-sm)' }}>
              {mode === 'lsch_v3' ? 'Inicia para reconocer señas con el modelo entrenado LSCh v3' : 'Inicia para deletreo estático'}
            </p>
          </div>
        )}

        <AlertOverlay icon="💡" message="Mejora la iluminación para mejor detección" visible={isCameraActive && confidence === ConfidenceLevel.LOW && handsDetected > 0 && mode === 'static'} />
        <AlertOverlay icon="👋" message="Acerca tus manos al centro del encuadre" visible={isCameraActive && handsDetected === 0} />
      </div>

      {cameraError && <div role="alert" style={{ padding: 'var(--space-3) var(--space-4)', backgroundColor: 'var(--color-error)', color: 'white', borderRadius: 'var(--radius-lg)', marginTop: 'var(--space-4)' }}>⚠ {cameraError}</div>}
      {activeError && <div role="alert" style={{ padding: 'var(--space-3) var(--space-4)', backgroundColor: 'var(--color-error)', color: 'white', borderRadius: 'var(--radius-lg)', marginTop: 'var(--space-4)' }}>⚠ Error de detección: {activeError}</div>}
      {backendError && isCameraActive && <div role="alert" style={{ padding: 'var(--space-2) var(--space-3)', backgroundColor: 'var(--color-warning, #b26a00)', color: 'white', borderRadius: 'var(--radius-md)', marginTop: 'var(--space-3)', fontSize: 'var(--font-size-xs)', textAlign: 'center' }}>⚠ Backend: {backendError}</div>}

      <p style={{ textAlign: 'center', color: 'var(--color-text-secondary)', margin: 'var(--space-4) 0', fontSize: 'var(--font-size-sm)' }}>{statusMessage}</p>

      <Card variant="default" padding="md">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-4)' }}>
          <h2 style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700 }}>Transcripción</h2>
          {fullText && <Waveform isPlaying={false} barCount={5} />}
        </div>
        <div style={{ minHeight: 120, maxHeight: 300, overflowY: 'auto' }}>
          {transcript.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state-icon" aria-hidden="true">✋</span>
              <p className="empty-state-text">{isCameraActive ? (mode === 'lsch_v3' ? 'Realiza una seña frente a la cámara...' : 'Muestra una seña y mantenla...') : 'Inicia la cámara para comenzar a traducir'}</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              {transcript.map((entry) => (
                <div key={entry.id} className="transcript-entry"><span className="transcript-text">{entry.text}</span></div>
              ))}
            </div>
          )}
        </div>
      </Card>

      <div style={{ display: 'flex', gap: 'var(--space-3)', marginTop: 'var(--space-6)' }}>
        <Button variant="primary" size="lg" onClick={handleToggleCamera} style={{ flex: 1 }}>{isCameraActive ? '⏸ Pausar' : '▶ Iniciar cámara'}</Button>
        <Button variant="success" size="lg" onClick={handleSpeak} disabled={!fullText} style={{ flex: 1 }}>🔊 Hablar</Button>
        <Button variant="secondary" size="lg" onClick={handleClear} disabled={transcript.length === 0}>🗑</Button>
      </div>

      <footer className="footer">
        <p>SeñasCL v0.1.0 — LSCh v3: modelo entrenado + backend + frontend integrados</p>
      </footer>
    </div>
  );
};

export default App;
