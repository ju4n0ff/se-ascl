export interface TextToSpeech {
  speak(text: string): Promise<void>;
  stop(): void;
  isSpeaking(): boolean;
  isAvailable(): boolean;
  setLanguage(lang: string): void;
  setRate(rate: number): void;
  setPitch(pitch: number): void;
}

export class NativeTextToSpeech implements TextToSpeech {
  private speaking = false;
  private language = 'es-CL';
  private rate = 1.0;
  private pitch = 1.0;

  async speak(text: string): Promise<void> {
    if (this.speaking) this.stop();
    this.speaking = true;
    // TODO: Use platform-specific TTS
    // Android: react-native-tts or Android TextToSpeech
    // iOS: AVSpeechSynthesizer via native module
    // Web: SpeechSynthesis API
    console.log(`[TTS] Speaking: "${text}" (lang: ${this.language})`);
    this.speaking = false;
  }

  stop(): void {
    this.speaking = false;
    // TODO: Stop native TTS engine
  }

  isSpeaking(): boolean {
    return this.speaking;
  }

  isAvailable(): boolean {
    // TODO: Check native TTS availability
    return true;
  }

  setLanguage(lang: string): void {
    this.language = lang;
  }

  setRate(rate: number): void {
    this.rate = Math.max(0.1, Math.min(2.0, rate));
  }

  setPitch(pitch: number): void {
    this.pitch = Math.max(0.5, Math.min(2.0, pitch));
  }
}

export const createTTS = (): TextToSpeech => {
  return new NativeTextToSpeech();
};
