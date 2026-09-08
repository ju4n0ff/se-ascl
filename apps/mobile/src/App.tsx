import React, { useState, useCallback, useRef } from 'react';
import {
  SafeAreaView,
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
} from 'react-native';
import { ConfidenceLevel, TranscriptEntry, RecognitionResult } from '@senascl/shared-types';

const App: React.FC = () => {
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [confidence, setConfidence] = useState<ConfidenceLevel>(ConfidenceLevel.LOW);
  const [statusMessage, setStatusMessage] = useState('Presiona para iniciar cámara');
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const entryIdCounter = useRef(0);

  const handleToggleCamera = useCallback(() => {
    setIsCameraActive((prev) => {
      const next = !prev;
      setStatusMessage(next ? 'Cámara activa — esperando señas...' : 'Cámara pausada');
      return next;
    });
  }, []);

  const handleSpeak = useCallback(() => {
    if (transcript.length === 0) return;
    const fullText = transcript.map((e) => e.text).join(' ');
    setIsSpeaking(true);
    // TODO: Use @senascl/tts native module
    console.log(`[TTS] Speaking: "${fullText}"`);
    setTimeout(() => setIsSpeaking(false), 2000);
  }, [transcript]);

  const handleClear = useCallback(() => {
    setTranscript([]);
    setStatusMessage('Transcripción limpiada');
  }, []);

  // Called by frame processor when a sign is recognized
  const onSignRecognized = useCallback((result: RecognitionResult) => {
    entryIdCounter.current += 1;
    const entry: TranscriptEntry = {
      id: String(entryIdCounter.current),
      text: result.spanishText,
      timestamp: result.timestamp,
      isFingerspelled: result.isFingerspelling,
      rawSigns: [result],
    };
    setTranscript((prev) => [...prev, entry]);
    setConfidence(result.confidenceLevel);
  }, []);

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>SeñasCL</Text>
        <Text style={styles.subtitle}>Intérprete LSCh → Texto</Text>
      </View>

      <View style={styles.cameraArea}>
        <View style={styles.cameraPlaceholder}>
          <Text style={styles.cameraText}>
            {isCameraActive ? '📷 Cámara activa' : '📷 Cámara inactiva'}
          </Text>
          <Text style={styles.cameraHint}>
            Encuadra tus manos dentro del recuadro
          </Text>
        </View>

        {isCameraActive && (
          <View style={styles.confidenceBadge}>
            <View
              style={[
                styles.confidenceDot,
                {
                  backgroundColor:
                    confidence === ConfidenceLevel.HIGH
                      ? '#3fb950'
                      : confidence === ConfidenceLevel.MEDIUM
                      ? '#d29922'
                      : '#f85149',
                },
              ]}
            />
            <Text style={styles.confidenceText}>
              {confidence === ConfidenceLevel.HIGH
                ? 'Buena detección'
                : confidence === ConfidenceLevel.MEDIUM
                ? 'Detección regular'
                : 'Detección baja'}
            </Text>
          </View>
        )}
      </View>

      <View style={styles.statusBar}>
        <Text style={styles.statusText}>{statusMessage}</Text>
      </View>

      <ScrollView style={styles.transcriptArea}>
        {transcript.length === 0 ? (
          <Text style={styles.emptyText}>Esperando señas...</Text>
        ) : (
          transcript.map((entry) => (
            <View key={entry.id} style={styles.transcriptEntry}>
              <Text style={styles.transcriptText}>{entry.text}</Text>
            </View>
          ))
        )}
      </ScrollView>

      <View style={styles.controls}>
        <TouchableOpacity
          style={[styles.controlButton, styles.cameraButton]}
          onPress={handleToggleCamera}
          activeOpacity={0.7}
        >
          <Text style={styles.controlButtonText}>
            {isCameraActive ? '⏸ Pausar' : '▶ Iniciar'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.controlButton, styles.speakButton, isSpeaking && styles.disabled]}
          onPress={handleSpeak}
          disabled={isSpeaking || transcript.length === 0}
          activeOpacity={0.7}
        >
          <Text style={styles.controlButtonText}>
            {isSpeaking ? '🔊 Hablando...' : '🔊 Hablar'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.controlButton, styles.clearButton]}
          onPress={handleClear}
          activeOpacity={0.7}
        >
          <Text style={styles.controlButtonText}>🗑 Limpiar</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0d1117',
  },
  header: {
    padding: 16,
    alignItems: 'center',
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#f0f6fc',
  },
  subtitle: {
    fontSize: 14,
    color: '#8b949e',
    marginTop: 4,
  },
  cameraArea: {
    margin: 16,
    height: 320,
    borderRadius: 16,
    backgroundColor: '#161b22',
    overflow: 'hidden',
    position: 'relative',
  },
  cameraPlaceholder: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  cameraText: {
    fontSize: 20,
    color: '#f0f6fc',
    fontWeight: '600',
  },
  cameraHint: {
    fontSize: 14,
    color: '#8b949e',
    marginTop: 8,
  },
  confidenceBadge: {
    position: 'absolute',
    top: 12,
    left: 12,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.6)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
    gap: 6,
  },
  confidenceDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  confidenceText: {
    color: '#f0f6fc',
    fontSize: 12,
    fontWeight: '600',
  },
  statusBar: {
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  statusText: {
    color: '#8b949e',
    fontSize: 14,
    textAlign: 'center',
  },
  transcriptArea: {
    flex: 1,
    marginHorizontal: 16,
    padding: 16,
    backgroundColor: '#161b22',
    borderRadius: 12,
  },
  emptyText: {
    color: '#8b949e',
    textAlign: 'center',
    padding: 24,
    fontSize: 16,
  },
  transcriptEntry: {
    padding: 12,
    backgroundColor: '#21262d',
    borderRadius: 8,
    marginBottom: 8,
  },
  transcriptText: {
    color: '#f0f6fc',
    fontSize: 18,
    lineHeight: 26,
  },
  controls: {
    flexDirection: 'row',
    padding: 16,
    gap: 12,
  },
  controlButton: {
    flex: 1,
    minHeight: 48,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  cameraButton: {
    backgroundColor: '#1a73e8',
  },
  speakButton: {
    backgroundColor: '#238636',
  },
  clearButton: {
    backgroundColor: '#21262d',
  },
  disabled: {
    opacity: 0.5,
  },
  controlButtonText: {
    color: '#f0f6fc',
    fontSize: 14,
    fontWeight: '600',
  },
});

export default App;
