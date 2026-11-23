/** JWT sin firma válida, solo para tests: el cliente únicamente lee `exp`. */
export function jwtDePrueba(expEnSegundos = 3600, sub = '1'): string {
  const b64 = (o: object): string =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const exp = Math.floor(Date.now() / 1000) + expEnSegundos;
  return `${b64({ alg: 'HS256' })}.${b64({ sub, exp, type: 'access' })}.firma`;
}
