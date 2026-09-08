import { RecognitionResult } from '@senascl/shared-types';
import { ALL_SIGNS } from './dictionary';

const signMap = new Map<string, string>();
for (const sign of ALL_SIGNS) {
  signMap.set(sign.gloss, sign.spanishText);
}

export function reconstructWord(letters: string[]): string {
  return letters.join('').toLowerCase();
}

export function lookupSign(gloss: string): string | undefined {
  return signMap.get(gloss);
}

export function signsToSpanish(results: RecognitionResult[]): string {
  if (results.length === 0) return '';

  const words: string[] = [];
  let fingerspellingBuffer: string[] = [];
  let currentWord = '';

  for (const result of results) {
    if (result.isFingerspelling) {
      if (fingerspellingBuffer.length > 0 || currentWord.length > 0) {
        fingerspellingBuffer.push(result.spanishText);
      } else {
        fingerspellingBuffer.push(result.spanishText);
      }
    } else {
      if (fingerspellingBuffer.length > 0) {
        words.push(reconstructWord(fingerspellingBuffer));
        fingerspellingBuffer = [];
      }
      currentWord = result.spanishText;
      if (currentWord) {
        words.push(currentWord);
        currentWord = '';
      }
    }
  }

  if (fingerspellingBuffer.length > 0) {
    words.push(reconstructWord(fingerspellingBuffer));
  }

  return words.join(' ');
}

export function lschToSpanish(signGlosses: string[]): string {
  const results: RecognitionResult[] = signGlosses.map((gloss) => ({
    signId: gloss,
    gloss,
    spanishText: lookupSign(gloss) ?? gloss,
    confidence: 1,
    confidenceLevel: 'high' as const,
    timestamp: Date.now(),
    isFingerspelling: false,
  }));
  return signsToSpanish(results);
}
