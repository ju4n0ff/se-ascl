import { RecognitionResult } from './recognition';

export interface TranscriptEntry {
  id: string;
  text: string;
  timestamp: number;
  isFingerspelled: boolean;
  rawSigns: RecognitionResult[];
}

export interface ConversationSession {
  id: string;
  startedAt: number;
  entries: TranscriptEntry[];
  fullTranscript: string;
}
