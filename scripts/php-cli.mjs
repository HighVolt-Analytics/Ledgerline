/**
 * Resolve PHP argv so local WinGet/dev builds without php.ini still load pdo_sqlite.
 * Hostinger production typically already has SQLite enabled.
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const PHP = process.env.PHP_BIN || 'php'

function phpProbe(args) {
  const result = spawnSync(
    PHP,
    [...args, '-r', 'echo in_array("sqlite", PDO::getAvailableDrivers(), true) ? "1" : "0";'],
    { encoding: 'utf8', windowsHide: true },
  )
  return result.status === 0 && String(result.stdout || '').trim() === '1'
}

function findExtensionDir() {
  const which = spawnSync(PHP, ['-r', 'echo PHP_BINARY;'], { encoding: 'utf8', windowsHide: true })
  if (which.status !== 0) return null
  const bin = String(which.stdout || '').trim()
  if (!bin) return null
  const ext = path.join(path.dirname(bin), 'ext')
  const hasDll = fs.existsSync(path.join(ext, 'php_pdo_sqlite.dll'))
  const hasSo = fs.existsSync(path.join(ext, 'pdo_sqlite.so'))
  if (!hasDll && !hasSo) return null
  return ext
}

let cachedArgs = null

export function phpBin() {
  return PHP
}

export function phpSqliteArgs() {
  if (cachedArgs) return cachedArgs
  if (phpProbe([])) {
    cachedArgs = []
    return cachedArgs
  }
  const extDir = process.env.PHP_EXTENSION_DIR || findExtensionDir()
  if (!extDir) {
    cachedArgs = []
    return cachedArgs
  }
  const args = ['-d', `extension_dir=${extDir}`, '-d', 'extension=pdo_sqlite', '-d', 'extension=sqlite3']
  // openssl signs the partner-service site token (Hostinger ships it enabled).
  if (fs.existsSync(path.join(extDir, 'php_openssl.dll')) || fs.existsSync(path.join(extDir, 'openssl.so'))) {
    args.push('-d', 'extension=openssl')
  }
  cachedArgs = phpProbe(args) ? args : []
  return cachedArgs
}
