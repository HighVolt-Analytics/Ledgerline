import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { phpBin, phpSqliteArgs } from '../scripts/php-cli.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const PUBLIC = path.join(ROOT, 'public')

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = createServer()
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close((err) => (err ? reject(err) : resolve(port)))
    })
  })
}

function parseSetCookie(header) {
  if (!header) return null
  const first = Array.isArray(header) ? header[0] : header
  const match = String(first).match(/ll_partner_session=([^;]+)/)
  return match ? match[1] : null
}

async function startPartnerApi(dbPath, extraEnv = {}) {
  const port = await freePort()
  const router = path.join(PUBLIC, 'api', 'router.php')
  const child = spawn(
    phpBin(),
    [...phpSqliteArgs(), '-S', `127.0.0.1:${port}`, '-t', PUBLIC, router],
    {
      env: { ...process.env, PARTNER_DB_PATH: dbPath, ...extraEnv },
      stdio: ['ignore', 'ignore', 'pipe'],
      windowsHide: true,
    },
  )
  let stderr = ''
  child.stderr.on('data', (chunk) => {
    stderr += String(chunk)
  })
  const base = `http://127.0.0.1:${port}`
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(`${base}/api/partners/me`)
      if (res.status === 401 || res.status === 200) {
        return {
          base,
          async close() {
            child.kill('SIGTERM')
            await new Promise((r) => setTimeout(r, 50))
          },
        }
      }
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 50))
  }
  child.kill('SIGTERM')
  throw new Error(`Partner API failed to start.\n${stderr}`)
}

async function api(base, route, { method = 'GET', body, cookie, authorization, adminToken } = {}) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (cookie) headers.Cookie = `ll_partner_session=${cookie}`
  if (authorization) headers.Authorization = authorization
  if (adminToken) headers['X-Partner-Admin-Token'] = adminToken
  const res = await fetch(`${base}/api/partners${route}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const text = await res.text()
  let json = null
  try {
    json = JSON.parse(text)
  } catch {
    json = null
  }
  const setCookie = typeof res.headers.getSetCookie === 'function' ? res.headers.getSetCookie() : res.headers.get('set-cookie')
  return { res, json, cookie: parseSetCookie(setCookie) }
}

test('partner signup, duplicate email, sign-in, session, portal gate, and sign-out', async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-'))
  const dbPath = path.join(tmp, 'partners.sqlite')
  const apiServer = await startPartnerApi(dbPath)
  try {
    const email = `partner-${Date.now()}@example.test`
    const password = 'secure-pass-123'

    const unauth = await api(apiServer.base, '/me')
    assert.equal(unauth.res.status, 401)
    assert.equal(unauth.json.error, 'unauthenticated')
    assert.equal(unauth.json.signinPath, '/partnership/signin')

    const signup = await api(apiServer.base, '/signup', {
      method: 'POST',
      body: {
        name: 'Ada Lovelace',
        email,
        password,
        firm: 'Analytical Engines',
        type: 'Accounting firm',
        country: 'AU',
        abn: '51 824 753 556',
      },
    })
    assert.equal(signup.res.status, 201)
    assert.ok(signup.json.partner?.id)
    assert.equal(signup.json.partner.email, email)
    assert.equal(signup.json.partner.firm, 'Analytical Engines')
    assert.ok(!('password' in signup.json.partner))
    assert.ok(!('password_hash' in signup.json.partner))
    assert.ok(signup.cookie)

    const me = await api(apiServer.base, '/me', { cookie: signup.cookie })
    assert.equal(me.res.status, 200)
    assert.equal(me.json.partner.email, email)

    const dup = await api(apiServer.base, '/signup', {
      method: 'POST',
      body: {
        name: 'Other Person',
        email,
        password: 'another-pass-123',
        firm: 'Other Firm',
        type: 'Bookkeeper',
        country: 'AU',
      },
    })
    assert.equal(dup.res.status, 409)
    assert.equal(dup.json.error, 'duplicate_email')
    assert.match(dup.json.message, /already uses this email/i)
    assert.equal(dup.json.signinPath, '/partnership/signin')

    await api(apiServer.base, '/signout', { method: 'POST', body: {}, cookie: signup.cookie })
    const afterSignout = await api(apiServer.base, '/me', { cookie: signup.cookie })
    assert.equal(afterSignout.res.status, 401)

    const bad = await api(apiServer.base, '/signin', {
      method: 'POST',
      body: { email, password: 'wrong-password' },
    })
    assert.equal(bad.res.status, 401)
    assert.match(bad.json.message, /incorrect/i)

    const good = await api(apiServer.base, '/signin', {
      method: 'POST',
      body: { email, password },
    })
    assert.equal(good.res.status, 200)
    assert.equal(good.json.partner.email, email)
    assert.ok(good.cookie)

    const persisted = await api(apiServer.base, '/me', { cookie: good.cookie })
    assert.equal(persisted.res.status, 200)
    assert.equal(persisted.json.partner.id, good.json.partner.id)

    const signedOut = await api(apiServer.base, '/signout', {
      method: 'POST',
      body: {},
      cookie: good.cookie,
    })
    assert.equal(signedOut.res.status, 200)
    const gone = await api(apiServer.base, '/me', { cookie: good.cookie })
    assert.equal(gone.res.status, 401)
  } finally {
    await apiServer.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('admin partner list requires token and returns only safe account fields', async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-admin-'))
  const dbPath = path.join(tmp, 'partners.sqlite')
  const adminToken = 'test-admin-token-partner-list'
  const apiServer = await startPartnerApi(dbPath, { PARTNER_ADMIN_TOKEN: adminToken })
  try {
    const email = `admin-list-${Date.now()}@example.test`
    await api(apiServer.base, '/signup', {
      method: 'POST',
      body: {
        name: 'List Partner',
        email,
        password: 'secure-pass-123',
        firm: 'List Firm',
        type: 'Bookkeeper',
        country: 'NZ',
      },
    })

    const denied = await api(apiServer.base, '/admin/list')
    assert.equal(denied.res.status, 401)
    assert.equal(denied.json.error, 'unauthorized')

    const wrong = await api(apiServer.base, '/admin/list', {
      authorization: 'Bearer wrong-token',
    })
    assert.equal(wrong.res.status, 401)

    const cookieOnly = await api(apiServer.base, '/signup', {
      method: 'POST',
      body: {
        name: 'Second',
        email: `second-${Date.now()}@example.test`,
        password: 'secure-pass-123',
        firm: 'Second Firm',
        type: 'Accounting firm',
        country: 'AU',
      },
    })
    const withCookie = await api(apiServer.base, '/admin/list', { cookie: cookieOnly.cookie })
    assert.equal(withCookie.res.status, 401)

    const listed = await api(apiServer.base, '/admin/list', {
      authorization: `Bearer ${adminToken}`,
    })
    assert.equal(listed.res.status, 200)
    assert.ok(Array.isArray(listed.json.partners))
    assert.ok(listed.json.count >= 1)
    const row = listed.json.partners.find((p) => p.email === email)
    assert.ok(row)
    assert.deepEqual(Object.keys(row).sort(), ['country', 'created', 'email', 'firm', 'name', 'type'].sort())
    assert.equal(row.name, 'List Partner')
    assert.equal(row.firm, 'List Firm')
    assert.equal(row.country, 'NZ')
    assert.equal(row.type, 'Bookkeeper')
    assert.match(row.created, /^\d{4}-\d{2}-\d{2}$/)
    assert.equal('password' in row, false)
    assert.equal('password_hash' in row, false)
    assert.equal('id' in row, false)
    assert.equal('code' in row, false)
    assert.equal('sessionId' in listed.json, false)

    const viaHeader = await api(apiServer.base, '/admin/list', { adminToken })
    assert.equal(viaHeader.res.status, 200)
    assert.ok(viaHeader.json.partners.some((p) => p.email === email))
  } finally {
    await apiServer.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('admin partner list fails closed when PARTNER_ADMIN_TOKEN is unset', async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-admin-off-'))
  const docRoot = path.join(tmp, 'public_html')
  await mkdir(docRoot, { recursive: true })
  const dbPath = path.join(tmp, 'partners.sqlite')
  const apiServer = await startPartnerApi(dbPath, {
    PARTNER_ADMIN_TOKEN: '',
    PARTNER_DOCUMENT_ROOT: docRoot,
  })
  try {
    const denied = await api(apiServer.base, '/admin/list', {
      authorization: 'Bearer anything',
    })
    assert.equal(denied.res.status, 401)
  } finally {
    await apiServer.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('admin partner list loads PARTNER_ADMIN_TOKEN from private/partner-secrets.php beside the document root', async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-secrets-'))
  const docRoot = path.join(tmp, 'public_html')
  const privateDir = path.join(tmp, 'private')
  await mkdir(docRoot, { recursive: true })
  await mkdir(privateDir, { recursive: true })
  const fileToken = `file-token-${Date.now()}`
  await writeFile(
    path.join(privateDir, 'partner-secrets.php'),
    `<?php\ndeclare(strict_types=1);\nreturn ['PARTNER_ADMIN_TOKEN' => ${JSON.stringify(fileToken)}];\n`,
    'utf8',
  )
  const dbPath = path.join(tmp, 'partners.sqlite')
  const apiServer = await startPartnerApi(dbPath, {
    PARTNER_ADMIN_TOKEN: '',
    PARTNER_DOCUMENT_ROOT: docRoot,
  })
  try {
    const email = `secrets-file-${Date.now()}@example.test`
    await api(apiServer.base, '/signup', {
      method: 'POST',
      body: {
        name: 'Secrets File Partner',
        email,
        password: 'secure-pass-123',
        firm: 'Secrets Firm',
        type: 'Accounting firm',
        country: 'AU',
      },
    })

    const denied = await api(apiServer.base, '/admin/list', {
      authorization: 'Bearer wrong-token',
    })
    assert.equal(denied.res.status, 401)

    const listed = await api(apiServer.base, '/admin/list', {
      authorization: `Bearer ${fileToken}`,
    })
    assert.equal(listed.res.status, 200)
    assert.ok(listed.json.partners.some((p) => p.email === email))
    assert.equal(JSON.stringify(listed.json).includes(fileToken), false)
  } finally {
    await apiServer.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('admin partner list prefers getenv over the private secrets file', async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-env-wins-'))
  const docRoot = path.join(tmp, 'public_html')
  const privateDir = path.join(tmp, 'private')
  await mkdir(docRoot, { recursive: true })
  await mkdir(privateDir, { recursive: true })
  const fileToken = 'file-token-should-not-win'
  const envToken = 'env-token-should-win'
  await writeFile(
    path.join(privateDir, 'partner-secrets.php'),
    `<?php\nreturn ['PARTNER_ADMIN_TOKEN' => ${JSON.stringify(fileToken)}];\n`,
    'utf8',
  )
  const dbPath = path.join(tmp, 'partners.sqlite')
  const apiServer = await startPartnerApi(dbPath, {
    PARTNER_ADMIN_TOKEN: envToken,
    PARTNER_DOCUMENT_ROOT: docRoot,
  })
  try {
    await api(apiServer.base, '/signup', {
      method: 'POST',
      body: {
        name: 'Env Wins',
        email: `env-wins-${Date.now()}@example.test`,
        password: 'secure-pass-123',
        firm: 'Env Firm',
        type: 'Bookkeeper',
        country: 'NZ',
      },
    })
    const viaFile = await api(apiServer.base, '/admin/list', {
      authorization: `Bearer ${fileToken}`,
    })
    assert.equal(viaFile.res.status, 401)
    const viaEnv = await api(apiServer.base, '/admin/list', {
      authorization: `Bearer ${envToken}`,
    })
    assert.equal(viaEnv.res.status, 200)
  } finally {
    await apiServer.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('admin partner list fails closed when secrets file is inside the document root or invalid', async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-secrets-bad-'))
  const docRoot = path.join(tmp, 'public_html')
  const insidePrivate = path.join(docRoot, 'private')
  await mkdir(insidePrivate, { recursive: true })
  await writeFile(
    path.join(insidePrivate, 'partner-secrets.php'),
    `<?php\nreturn ['PARTNER_ADMIN_TOKEN' => 'inside-docroot-token'];\n`,
    'utf8',
  )
  const dbPath = path.join(tmp, 'partners.sqlite')
  const insideServer = await startPartnerApi(dbPath, {
    PARTNER_ADMIN_TOKEN: '',
    PARTNER_DOCUMENT_ROOT: docRoot,
  })
  try {
    const denied = await api(insideServer.base, '/admin/list', {
      authorization: 'Bearer inside-docroot-token',
    })
    assert.equal(denied.res.status, 401)
  } finally {
    await insideServer.close()
  }

  const outsidePrivate = path.join(tmp, 'private')
  await mkdir(outsidePrivate, { recursive: true })
  await writeFile(path.join(outsidePrivate, 'partner-secrets.php'), '<?php\nreturn "not-an-array";\n', 'utf8')
  const invalidServer = await startPartnerApi(dbPath, {
    PARTNER_ADMIN_TOKEN: '',
    PARTNER_DOCUMENT_ROOT: docRoot,
  })
  try {
    const denied = await api(invalidServer.base, '/admin/list', {
      authorization: 'Bearer anything',
    })
    assert.equal(denied.res.status, 401)
  } finally {
    await invalidServer.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('partner UI removes demo-login and keeps portal behind server auth', async () => {
  const app = await readFile(path.join(PUBLIC, 'partners', 'app.js'), 'utf8')
  assert.equal(/demo-login/.test(app), false)
  assert.match(app, /authFetch\('\/signup'/)
  assert.match(app, /authFetch\('\/signin'/)
  assert.match(app, /authFetch\('\/signout'/)
  assert.match(app, /authFetch\('\/me'/)
  assert.match(app, /credentials: 'include'/)
  assert.match(app, /Prototype portal/)
  assert.equal(/pw: 'demo1234'/.test(app), false)
  assert.match(app, /if \(route === 'portal' && !authPartner\) route = 'signin'/)
})

test('book-demo journey stays on booking flow and is not redirected to partner signup', async () => {
  const nav = await readFile(path.join(ROOT, 'src', 'data', 'navigation.js'), 'utf8')
  assert.match(nav, /export const bookDemoPath = '\/book-demo'/)

  const home = await readFile(path.join(ROOT, 'src', 'pages', 'QuantumLedgerLinkPage.jsx'), 'utf8')
  assert.match(home, /bookDemoPath/)
  assert.match(home, /Book a demo/)
  assert.equal(/to=\{bookDemoPath\}[\s\S]{0,80}partnership\/signup/.test(home), false)

  const bookPage = await readFile(path.join(ROOT, 'src', 'pages', 'BookDemoPage.jsx'), 'utf8')
  assert.match(bookPage, /BOOKING_V2_SITE/)
  assert.match(bookPage, /availabilityV2/)
  assert.match(bookPage, /bookV2/)
  assert.equal(/partnership\/signup/.test(bookPage), false)
  assert.equal(/Become a founding partner/.test(bookPage), false)

  const app = await readFile(path.join(PUBLIC, 'partners', 'app.js'), 'utf8')
  assert.match(app, /Become a founding partner/)
  assert.match(app, /data-go="signup"/)
})
