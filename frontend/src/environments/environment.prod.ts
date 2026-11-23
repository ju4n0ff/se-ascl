// Antes de desplegar en Vercel: reemplazar REPLACE_WITH_RENDER_SERVICE (aparece dos veces)
// por el nombre del servicio de Render. Sin barra final.
export const environment = {
  production: true,
  apiUrl: 'https://REPLACE_WITH_RENDER_SERVICE.onrender.com',
  wsUrl: 'wss://REPLACE_WITH_RENDER_SERVICE.onrender.com/ws/recognize',
};
