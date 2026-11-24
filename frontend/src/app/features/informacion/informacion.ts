import { Component } from '@angular/core';

@Component({
  selector: 'app-informacion',
  template: `
    <h1>Guía rápida, privacidad y contacto</h1>
    <p class="suave">Todo lo que necesitas para traducir con comodidad y seguridad.</p>

    <section id="guia" class="tarjeta bloque">
      <h2>Guía rápida</h2>
      <ol>
        <li>Enciende la cámara y coloca tu cabeza y ambos hombros dentro del cuadro.</li>
        <li>Elige el modo Automático para señalar sin botones o Manual para controlar cada seña.</li>
        <li>Observa la traducción, usa las alternativas si dudas y escucha la frase con la voz.</li>
        <li>En el glosario, pulsa «Ver cómo se hace» para girar una tarjeta y ver su referencia.</li>
        <li>Desde Accesibilidad puedes cambiar texto, contraste, tema y movimiento.</li>
      </ol>
    </section>

    <section id="privacidad" class="tarjeta bloque">
      <h2>Privacidad</h2>
      <p>
        El video se procesa en tu navegador. Solo se envían vectores de landmarks al servidor para
        la inferencia; no se guardan ni se registran video, cuadros ni puntos del cuerpo.
      </p>
      <p>
        Tu sesión (JWT) vive en <code>sessionStorage</code> y desaparece al cerrar la pestaña. Tus
        preferencias de accesibilidad se guardan en <code>localStorage</code> para que se recuerden
        al volver. Puedes borrar tu cuenta y su historial desde Perfil.
      </p>
    </section>

    <section id="terminos" class="tarjeta bloque">
      <h2>Términos de uso</h2>
      <p>
        SeñaCL es una herramienta de apoyo, no un intérprete certificado. El reconocimiento puede
        fallar, especialmente con poca luz o encuadres parciales. Verifica siempre el resultado
        antes de usarlo para decisiones importantes.
      </p>
    </section>

    <section id="contacto" class="tarjeta bloque">
      <h2>Contacto</h2>
      <p>
        Este proyecto es de código abierto. Puedes reportar errores o sugerir mejoras en el
        <a href="https://github.com/ju4n0ff/se-ascl/issues" target="_blank" rel="noopener noreferrer"
          >repositorio de SeñaCL</a
        >.
      </p>
    </section>
  `,
  styles: `
    .bloque {
      margin-bottom: 1rem;
      scroll-margin-top: 5rem;
    }
    h2 {
      margin-top: 0;
    }
    li {
      margin-bottom: 0.4rem;
    }
    p:last-child {
      margin-bottom: 0;
    }
  `,
})
export class Informacion {}
