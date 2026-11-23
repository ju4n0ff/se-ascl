import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-no-encontrada',
  imports: [RouterLink],
  template: `
    <section class="tarjeta angosta">
      <h1>No encontramos esta página</h1>
      <p>Puede que el enlace esté mal escrito o que ya no exista.</p>
      <a routerLink="/" class="boton">Ir al traductor</a>
    </section>
  `,
})
export class NoEncontrada {}
