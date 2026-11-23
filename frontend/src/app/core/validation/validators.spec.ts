import { FormControl, Validators } from '@angular/forms';

import { PATRON_USERNAME, VALIDADORES_EMAIL, passwordFuerte, textoHistorial } from './validators';

const valido = (valor: string, ...v: ConstructorParameters<typeof FormControl>[1][]) =>
  new FormControl(valor, v.flat() as never).valid;

describe('validadores alineados con el backend', () => {
  it.each(['ana', 'a.b-c_9', 'x'.repeat(50)])('username válido: %s', (u) => {
    expect(valido(u, Validators.pattern(PATRON_USERNAME))).toBe(true);
  });
  it.each(['ab', 'x'.repeat(51), 'con espacio', 'ñandú', 'a/b', 'ana\n'])(
    'username inválido: %j',
    (u) => {
      expect(valido(u, Validators.pattern(PATRON_USERNAME))).toBe(false);
    },
  );

  it.each(['Abcdefg1', 'A1' + 'a'.repeat(126), 'Ñ Clave 1a B'])('password válida', (p) => {
    expect(valido(p, passwordFuerte)).toBe(true);
  });
  it.each([
    ['1234', ['largo', 'mayuscula', 'minuscula']],
    ['abcdefg1', ['mayuscula']],
    ['ABCDEFG1', ['minuscula']],
    ['Abcdefgh', ['digito']],
    ['A1' + 'a'.repeat(127), ['largo']],
  ])('password débil: %s', (p, faltan) => {
    expect(passwordFuerte(new FormControl(p))).toEqual({ passwordDebil: faltan });
  });

  it.each(['a@b.cl', 'nombre.apellido+x@correo.co'])('email válido: %s', (e) => {
    expect(valido(e, VALIDADORES_EMAIL)).toBe(true);
  });
  it.each(['a@b', 'sin-arroba', '@x.cl', 'a'.repeat(95) + '@correo.cl'])(
    'email inválido: %s',
    (e) => {
      expect(valido(e, VALIDADORES_EMAIL)).toBe(false);
    },
  );

  it('texto del historial: 1 a 500 útiles y sin controles', () => {
    expect(textoHistorial(new FormControl(' ¿dónde está? '))).toBeNull();
    expect(textoHistorial(new FormControl('a'.repeat(500)))).toBeNull();
    expect(textoHistorial(new FormControl('   '))).toEqual({ vacio: true });
    expect(textoHistorial(new FormControl('a'.repeat(501)))).toEqual({ largo: true });
    expect(textoHistorial(new FormControl('a\u0000b'))).toEqual({ control: true });
    expect(textoHistorial(new FormControl('línea\notra'))).toBeNull();
  });
});
