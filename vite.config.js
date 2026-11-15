import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { spawn } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { phpBin, phpSqliteArgs } from './scripts/php-cli.mjs';

const PARTNERSHIP = /^\/partnership(?:\/(?:signup|signin|checkout|portal(?:\/(?:clients|commissions|payouts|share|settings))?))?\/?$/;
const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PARTNER_API_PORT = Number(process.env.PARTNER_API_PORT || 8791);

function partnershipRoutes() {
  return {
    name: 'partnership-routes',
    configureServer(server) {
      const php = startPartnerApi();
      server.middlewares.use(proxyPartnerApi);
      server.middlewares.use(servePartnership);
      const stop = () => {
        if (php && !php.killed) php.kill('SIGTERM');
      };
      server.httpServer?.once('close', stop);
      process.once('exit', stop);
    },
    configurePreviewServer(server) {
      const php = startPartnerApi();
      server.middlewares.use(proxyPartnerApi);
      server.middlewares.use(servePartnership);
      const stop = () => {
        if (php && !php.killed) php.kill('SIGTERM');
      };
      server.httpServer?.once('close', stop);
      process.once('exit', stop);
    },
  };
}

function startPartnerApi() {
  const publicDir = path.join(ROOT, 'public');
  const router = path.join(publicDir, 'api', 'router.php');
  try {
    return spawn(
      phpBin(),
      [...phpSqliteArgs(), '-S', `127.0.0.1:${PARTNER_API_PORT}`, '-t', publicDir, router],
      {
        stdio: 'ignore',
        windowsHide: true,
        env: {
          ...process.env,
          PARTNER_DB_PATH: process.env.PARTNER_DB_PATH || path.join(publicDir, 'api', 'data', 'partners.dev.sqlite'),
        },
      },
    );
  } catch {
    return null;
  }
}

function proxyPartnerApi(req, res, next) {
  const url = req.url || '/';
  if (!url.startsWith('/api/partners')) return next();
  const headers = { ...req.headers, host: `127.0.0.1:${PARTNER_API_PORT}` };
  const proxy = http.request(
    {
      hostname: '127.0.0.1',
      port: PARTNER_API_PORT,
      path: url,
      method: req.method,
      headers,
    },
    (upstream) => {
      res.writeHead(upstream.statusCode || 502, upstream.headers);
      upstream.pipe(res);
    },
  );
  proxy.on('error', () => {
    res.statusCode = 502;
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ error: 'partner_api_unavailable', message: 'Start PHP partner API (php -S) for local auth.' }));
  });
  req.pipe(proxy);
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
