import { elegirVoz } from './speech.service';

const voz = (lang: string) => ({ lang, name: lang }) as SpeechSynthesisVoice;

describe('elegirVoz', () => {
  it.each([
    [['en-US', 'es-ES', 'es-CL'], 'es-CL'],
    [['es-MX', 'es_ES'], 'es_ES'],
    [['en-US', 'es-MX'], 'es-MX'],
    [['en-US', 'es'], 'es'],
  ])('%j -> %s', (langs, esperada) => {
    expect(elegirVoz(langs.map(voz))?.lang).toBe(esperada);
  });
  it('sin español devuelve null', () => {
    expect(elegirVoz([voz('en-US'), voz('est-EE')])).toBeNull();
  });
});
