import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const PARTNERSHIP = /^\/partnership(?:\/(?:signup|signin|checkout|portal(?:\/(?:clients|commissions|payouts|share|settings))?))?\/?$/;

function partnershipRoutes() {
  return {
    name: 'partnership-routes',
    configureServer(server) {
      server.middlewares.use(servePartnership);
    },
    configurePreviewServer(server) {
      server.middlewares.use(servePartnership);
    },
  };
}

function servePartnership(req, res, next) {
  const raw = req.url || '/';
  const q = raw.indexOf('?');
  const path = q === -1 ? raw : raw.slice(0, q);
  const search = q === -1 ? '' : raw.slice(q);
  if (path === '/partners' || path === '/partners/' || path === '/partners/index.html') {
    res.statusCode = 302;
    res.setHeader('Location', '/partnership');
    res.end();
    return;
  }
  if (PARTNERSHIP.test(path)) req.url = `/partners/index.html${search}`;
  next();
}

export default defineConfig({
  plugins: [partnershipRoutes(), react()],
});
