import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { phpBin, phpSqliteArgs } from './php-cli.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const PUBLIC = path.join(ROOT, 'public')
const HOST = process.env.PARTNER_API_HOST || '127.0.0.1'
const PORT = process.env.PARTNER_API_PORT || '8791'
const router = path.join(PUBLIC, 'api', 'router.php')
const dbPath = process.env.PARTNER_DB_PATH || path.join(PUBLIC, 'api', 'data', 'partners.dev.sqlite')

const child = spawn(
  phpBin(),
  [...phpSqliteArgs(), '-S', `${HOST}:${PORT}`, '-t', PUBLIC, router],
  {
    stdio: 'inherit',
    env: { ...process.env, PARTNER_DB_PATH: dbPath },
    windowsHide: true,
  },
)

child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal)
  process.exit(code ?? 1)
})

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    if (!child.killed) child.kill(sig)
  })
}
