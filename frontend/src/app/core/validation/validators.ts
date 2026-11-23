import { AbstractControl, ValidationErrors, ValidatorFn, Validators } from '@angular/forms';

/** Reglas idénticas a backend/app/schemas/schemas.py. */
export const PATRON_USERNAME = /^[a-zA-Z0-9_.-]{3,50}$/;
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;
export const EMAIL_MAX = 100;
export const TEXTO_MAX = 500;

export interface RequisitoPassword {
  id: string;
  texto: string;
  cumple: (valor: string) => boolean;
}

// Python cuenta puntos de código, no unidades UTF-16.
const largo = (v: string): number => [...v].length;

export const REQUISITOS_PASSWORD: readonly RequisitoPassword[] = [
  {
    id: 'largo',
    texto: `Entre ${PASSWORD_MIN} y ${PASSWORD_MAX} caracteres`,
    cumple: (v) => largo(v) >= PASSWORD_MIN && largo(v) <= PASSWORD_MAX,
  },
  { id: 'mayuscula', texto: 'Al menos una mayúscula', cumple: (v) => /[A-Z]/.test(v) },
  { id: 'minuscula', texto: 'Al menos una minúscula', cumple: (v) => /[a-z]/.test(v) },
  { id: 'digito', texto: 'Al menos un número', cumple: (v) => /[0-9]/.test(v) },
];

export const passwordFuerte: ValidatorFn = (control: AbstractControl): ValidationErrors | null => {
  const valor = String(control.value ?? '');
  if (!valor) return null;
  const faltan = REQUISITOS_PASSWORD.filter((r) => !r.cumple(valor)).map((r) => r.id);
  return faltan.length ? { passwordDebil: faltan } : null;
};

/** Texto del historial: 1 a 500 caracteres útiles y sin caracteres de control. */
export const textoHistorial: ValidatorFn = (control: AbstractControl): ValidationErrors | null => {
  const valor = String(control.value ?? '').trim();
  if (!valor) return { vacio: true };
  if (largo(valor) > TEXTO_MAX) return { largo: true };
  return /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(valor) ? { control: true } : null;
};

/** `Validators.email` acepta "a@b"; el backend exige un dominio con punto. */
const emailConDominio: ValidatorFn = (control: AbstractControl): ValidationErrors | null => {
  const valor = String(control.value ?? '');
  return !valor || /@[^@\s]+\.[^@\s.]{2,}$/.test(valor) ? null : { email: true };
};

export const VALIDADORES_EMAIL: ValidatorFn[] = [
  Validators.email,
  emailConDominio,
  Validators.maxLength(EMAIL_MAX),
];
