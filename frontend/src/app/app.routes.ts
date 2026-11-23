import { Routes } from '@angular/router';

import { authGuard, invitadoGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    title: 'Traductor en vivo · SeñaCL',
    loadComponent: () => import('./features/traductor/traductor').then((m) => m.Traductor),
  },
  {
    path: 'glosario',
    title: 'Glosario · SeñaCL',
    loadComponent: () => import('./features/glosario/glosario').then((m) => m.Glosario),
  },
  {
    path: 'login',
    title: 'Iniciar sesión · SeñaCL',
    canActivate: [invitadoGuard],
    loadComponent: () => import('./features/auth/login').then((m) => m.Login),
  },
  {
    path: 'registro',
    title: 'Crear cuenta · SeñaCL',
    canActivate: [invitadoGuard],
    loadComponent: () => import('./features/auth/registro').then((m) => m.Registro),
  },
  {
    path: 'historial',
    title: 'Historial · SeñaCL',
    canActivate: [authGuard],
    loadComponent: () => import('./features/historial/historial').then((m) => m.Historial),
  },
  {
    path: 'perfil',
    title: 'Mi perfil · SeñaCL',
    canActivate: [authGuard],
    loadComponent: () => import('./features/perfil/perfil').then((m) => m.Perfil),
  },
  {
    path: '**',
    title: 'Página no encontrada · SeñaCL',
    loadComponent: () =>
      import('./features/no-encontrada/no-encontrada').then((m) => m.NoEncontrada),
  },
];
