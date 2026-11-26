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

const signupBody = (email) => ({
  name: 'Grace Hopper',
  email,
  password: 'secure-pass-123',
  firm: 'Compiler Co',
  type: 'Accounting firm',
  country: 'AU',
})

test('signup links the partner to the HighVolt partner service when PARTNER_SERVICE_URL is set', async () => {
  const received = []
  const fake = createServer((req, res) => {
    let data = ''
    req.on('data', (c) => (data += c))
    req.on('end', () => {
      received.push({ method: req.method, url: req.url, body: JSON.parse(data || '{}') })
      res.writeHead(201, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ partner_id: '11111111-2222-3333-4444-555555555555', status: 'APPLIED' }))
    })
  })
  await new Promise((r) => fake.listen(0, '127.0.0.1', r))
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-'))
  const apiServer = await startPartnerApi(path.join(tmp, 'p.sqlite'), {
    PARTNER_SERVICE_URL: `http://127.0.0.1:${fake.address().port}/platform/v1/partners/`,
  })
  try {
    const email = `linked-${Date.now()}@example.test`
    const signup = await api(apiServer.base, '/signup', { method: 'POST', body: signupBody(email) })
    assert.equal(signup.res.status, 201)
    assert.equal(signup.json.partner.programLinked, true)
    assert.ok(!('hva_partner_id' in signup.json.partner))
    assert.equal(received.length, 1)
    assert.equal(received[0].method, 'POST')
    assert.equal(received[0].url, '/platform/v1/partners/applications')
    assert.deepEqual(received[0].body, {
      product_key: 'ledgerline',
      display_name: 'Compiler Co',
      contact_email: email,
      country: 'AU',
      agreement_version: 'ledgerline-partner-terms-2026-11',
      marketing_consent: false,
    })
    assert.ok(!('password' in received[0].body))
    const me = await api(apiServer.base, '/me', { cookie: signup.cookie })
    assert.equal(me.json.partner.programLinked, true)
  } finally {
    await apiServer.close()
    fake.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('partner service address and key id can come from private/partner-secrets.php (no environment on Hostinger)', async () => {
  const received = []
  const fake = createServer((req, res) => {
    let data = ''
    req.on('data', (c) => (data += c))
    req.on('end', () => {
      received.push({ method: req.method, url: req.url })
      res.writeHead(201, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ partner_id: '11111111-2222-3333-4444-555555555555', status: 'APPLIED' }))
    })
  })
  await new Promise((r) => fake.listen(0, '127.0.0.1', r))
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-secrets-'))
  const docRoot = path.join(tmp, 'public_html')
  const privateDir = path.join(tmp, 'private')
  await mkdir(docRoot, { recursive: true })
  await mkdir(privateDir, { recursive: true })
  await writeFile(
    path.join(privateDir, 'partner-secrets.php'),
    `<?php
declare(strict_types=1);
return ['PARTNER_SERVICE_URL' => ${JSON.stringify(`http://127.0.0.1:${fake.address().port}/platform/v1/partners`)}];
`,
    'utf8',
  )
  const apiServer = await startPartnerApi(path.join(tmp, 'p.sqlite'), { PARTNER_SERVICE_URL: '', PARTNER_DOCUMENT_ROOT: docRoot })
  try {
    const signup = await api(apiServer.base, '/signup', { method: 'POST', body: signupBody(`file-url-${Date.now()}@example.test`) })
    assert.equal(signup.res.status, 201)
    assert.equal(signup.json.partner.programLinked, true)
    assert.deepEqual(received, [{ method: 'POST', url: '/platform/v1/partners/applications' }])
  } finally {
    await apiServer.close()
    fake.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('signup still succeeds, unlinked, when the partner service is down or not configured', async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-'))
  const down = await startPartnerApi(path.join(tmp, 'a.sqlite'), { PARTNER_SERVICE_URL: 'http://127.0.0.1:9' })
  const off = await startPartnerApi(path.join(tmp, 'b.sqlite'))
  try {
    for (const server of [down, off]) {
      const signup = await api(server.base, '/signup', {
        method: 'POST',
        body: signupBody(`unlinked-${Date.now()}-${Math.random()}@example.test`),
      })
      assert.equal(signup.res.status, 201)
      assert.equal(signup.json.partner.programLinked, false)
    }
  } finally {
    await down.close()
    await off.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('portal program data uses a 60s signed token for the signed-in partner only', async () => {
  const { generateKeyPairSync, createVerify } = await import('node:crypto')
  const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
  const pem = privateKey.export({ type: 'pkcs8', format: 'pem' })
  const ids = ['aaaaaaaa-0000-4000-8000-000000000001', 'bbbbbbbb-0000-4000-8000-000000000002']
  let next = 0
  const seen = []
  const fake = createServer((req, res) => {
    let data = ''
    req.on('data', (c) => (data += c))
    req.on('end', () => {
      const send = (code, obj) => {
        res.writeHead(code, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify(obj))
      }
      if (req.method === 'POST' && req.url === '/applications') return send(201, { partner_id: ids[next++], status: 'APPLIED' })
      const auth = String(req.headers.authorization || '')
      const [h, p, s] = auth.replace(/^Bearer /, '').split('.')
      const ok = h && createVerify('RSA-SHA256').update(`${h}.${p}`).verify(publicKey, Buffer.from(s, 'base64url'))
      if (!ok) return send(401, { error: 'bad' })
      const header = JSON.parse(Buffer.from(h, 'base64url'))
      const claims = JSON.parse(Buffer.from(p, 'base64url'))
      seen.push({ url: req.url, method: req.method, header, claims })
      const pid = claims.partner_id
      if (req.url === '/site/me') return send(200, { partner_id: pid, status: 'APPLIED' })
      if (req.url === '/site/me/balances') return send(200, [{ currency: 'USD', pending_minor: 1500, approved_minor: 0, paid_minor: 0, debt_minor: 0 }, { currency: 'SGD', pending_minor: 2000, approved_minor: 0, paid_minor: 0, debt_minor: 0 }])
      if (req.url === '/site/me/referral-codes' && req.method === 'GET') return send(200, [{ code: `CODE-${pid.slice(0, 4)}`, status: 'ACTIVE' }])
      if (req.url === '/site/me/referral-codes' && req.method === 'POST') return send(201, { code: 'NEW1', status: 'ACTIVE' })
      return send(404, {})
    })
  })
  await new Promise((r) => fake.listen(0, '127.0.0.1', r))
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-'))
  const apiServer = await startPartnerApi(path.join(tmp, 'p.sqlite'), {
    PARTNER_SERVICE_URL: `http://127.0.0.1:${fake.address().port}`,
    PARTNER_SITE_SIGNING_KEY: pem,
    PARTNER_SITE_KEY_ID: 'test-kid',
  })
  try {
    const anon = await api(apiServer.base, '/program')
    assert.equal(anon.res.status, 401)

    const a = await api(apiServer.base, '/signup', { method: 'POST', body: signupBody(`a-${Date.now()}@example.test`) })
    const b = await api(apiServer.base, '/signup', { method: 'POST', body: signupBody(`b-${Date.now()}@example.test`) })
    const progA = await api(apiServer.base, '/program', { cookie: a.cookie })
    assert.equal(progA.res.status, 200)
    assert.equal(progA.json.linked, true)
    assert.equal(progA.json.available, true)
    assert.equal(progA.json.status, 'APPLIED')
    assert.deepEqual(progA.json.codes, [{ code: 'CODE-aaaa', status: 'ACTIVE' }])
    assert.equal(progA.json.balance.currency, 'USD')
    assert.equal(progA.json.balance.pendingMinor, 1500)
    assert.deepEqual(progA.json.balances.map((x) => x.currency + ':' + x.pendingMinor), ['USD:1500', 'SGD:2000'])
    assert.ok(!JSON.stringify(progA.json).includes(ids[0]), 'service partner id is never sent to the browser')

    const progB = await api(apiServer.base, '/program', { cookie: b.cookie })
    assert.deepEqual(progB.json.codes, [{ code: 'CODE-bbbb', status: 'ACTIVE' }])

    // Every token: right issuer/audience/product/role, the caller's own partner id, at most 60 seconds.
    assert.ok(seen.length >= 6)
    for (const t of seen) {
      assert.equal(t.header.alg, 'RS256')
      assert.equal(t.header.kid, 'test-kid')
      assert.equal(t.claims.aud, 'hva-partner-site')
      assert.equal(t.claims.app_id, 'ledgerline')
      assert.equal(t.claims.role, 'Partner')
      assert.ok(t.claims.exp - t.claims.iat <= 60)
      assert.ok(ids.includes(t.claims.partner_id))
      assert.ok(!('email' in t.claims))
    }
    assert.equal(seen.filter((t) => t.claims.partner_id === ids[1]).length, 8) // /program is public (no token)

    const code = await api(apiServer.base, '/program/code', { method: 'POST', cookie: a.cookie })
    assert.equal(code.res.status, 200)
    assert.ok(seen.some((t) => t.method === 'POST' && t.url === '/site/me/referral-codes' && t.claims.partner_id === ids[0]))

    // Browser cannot pick another partner: query/body ids are ignored.
    const spoof = await api(apiServer.base, `/program?partner_id=${ids[1]}`, { cookie: a.cookie })
    assert.deepEqual(spoof.json.codes, [{ code: 'CODE-aaaa', status: 'ACTIVE' }])
  } finally {
    await apiServer.close()
    fake.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('portal program is safely off without a signing key', async () => {
  const fake = createServer((req, res) => {
    res.writeHead(201, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ partner_id: 'cccccccc-0000-4000-8000-000000000003', status: 'APPLIED' }))
  })
  await new Promise((r) => fake.listen(0, '127.0.0.1', r))
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-'))
  const apiServer = await startPartnerApi(path.join(tmp, 'p.sqlite'), {
    PARTNER_SERVICE_URL: `http://127.0.0.1:${fake.address().port}`,
  })
  try {
    const s = await api(apiServer.base, '/signup', { method: 'POST', body: signupBody(`k-${Date.now()}@example.test`) })
    const prog = await api(apiServer.base, '/program', { cookie: s.cookie })
    assert.equal(prog.res.status, 200)
    assert.deepEqual(prog.json, { linked: true, available: false })
  } finally {
    await apiServer.close()
    fake.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('bank details go server-side to partner-service and are validated first', async () => {
  const { generateKeyPairSync } = await import('node:crypto')
  const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
  const puts = []
  const fake = createServer((req, res) => {
    let data = ''
    req.on('data', (c) => (data += c))
    req.on('end', () => {
      const send = (code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)) }
      if (req.method === 'POST' && req.url === '/applications') return send(201, { partner_id: 'dddddddd-0000-4000-8000-000000000004', status: 'APPLIED' })
      if (req.method === 'PUT' && req.url === '/site/me/payout-account') { puts.push(JSON.parse(data)); return send(200, { id: 'acc-1' }) }
      if (req.url === '/site/me') return send(200, { status: 'ACTIVE' })
      if (req.url === '/site/me/payout-account') return send(200, puts.length ? [{ status: 'PENDING', account_masked: '****5678', account_holder_name: 'Elm & Co' }] : [])
      if (req.url === '/site/me/balances') return send(200, [{ currency: 'USD' }])
      if (req.url === '/site/me/referral-codes') return send(200, [])
      return send(404, {})
    })
  })
  await new Promise((r) => fake.listen(0, '127.0.0.1', r))
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-'))
  const apiServer = await startPartnerApi(path.join(tmp, 'p.sqlite'), {
    PARTNER_SERVICE_URL: `http://127.0.0.1:${fake.address().port}`,
    PARTNER_SITE_SIGNING_KEY: privateKey.export({ type: 'pkcs8', format: 'pem' }),
  })
  try {
    const s = await api(apiServer.base, '/signup', { method: 'POST', body: signupBody(`bank-${Date.now()}@example.test`) })
    const bad = await api(apiServer.base, '/program/bank', { method: 'POST', cookie: s.cookie, body: { holder: '', accountNumber: '12', bankCode: '!' } })
    assert.equal(bad.res.status, 400)
    assert.deepEqual(Object.keys(bad.json.fields).sort(), ['accountNumber', 'bankCode', 'holder'])
    assert.equal(puts.length, 0, 'invalid input never reaches partner-service')

    const ok = await api(apiServer.base, '/program/bank', { method: 'POST', cookie: s.cookie, body: { holder: 'Elm & Co', accountNumber: '1234 5678', bankCode: '062-000' } })
    assert.equal(ok.res.status, 200)
    assert.deepEqual(puts[0], { provider: 'MANUAL_BANK_BATCH', account_holder_name: 'Elm & Co', account_number: '12345678', bank_code: '062000' })
    assert.deepEqual(ok.json.bank, [{ status: 'PENDING', masked: '****5678', holder: 'Elm & Co' }])
    assert.ok(!JSON.stringify(ok.json).includes('12345678'), 'full account number is never sent back to the browser')

    const anon = await api(apiServer.base, '/program/bank', { method: 'POST', body: { holder: 'x', accountNumber: '12345678', bankCode: '062000' } })
    assert.equal(anon.res.status, 401)
  } finally {
    await apiServer.close()
    fake.close()
    await rm(tmp, { recursive: true, force: true })
  }
})

test('apply again only after the partnership ended, with terms accepted, as a new application', async () => {
  const { generateKeyPairSync } = await import('node:crypto')
  const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
  const ended = 'eeeeeeee-0000-4000-8000-000000000005'
  const fresh = 'ffffffff-0000-4000-8000-000000000006'
  const applications = []
  const fake = createServer((req, res) => {
    let data = ''
    req.on('data', (c) => (data += c))
    req.on('end', () => {
      const send = (code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)) }
      if (req.method === 'POST' && req.url === '/applications') {
        applications.push(JSON.parse(data))
        return send(201, { partner_id: applications.length === 1 ? ended : fresh, status: 'APPLIED' })
      }
      const [, p] = String(req.headers.authorization || '').replace(/^Bearer /, '').split('.')
      const pid = p ? JSON.parse(Buffer.from(p, 'base64url')).partner_id : null
      if (req.url === '/site/me') return send(200, { status: pid === ended ? 'TERMINATED' : 'APPLIED' })
      if (req.url === '/site/me/balances') return send(200, [{ currency: 'INR', pending_minor: pid === ended ? 100000 : 0 }])
      if (req.url === '/site/me/referral-codes' || req.url === '/site/me/payout-account') return send(200, [])
      return send(404, {})
    })
  })
  await new Promise((r) => fake.listen(0, '127.0.0.1', r))
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'll-partner-'))
  const apiServer = await startPartnerApi(path.join(tmp, 'p.sqlite'), {
    PARTNER_SERVICE_URL: `http://127.0.0.1:${fake.address().port}`,
    PARTNER_SITE_SIGNING_KEY: privateKey.export({ type: 'pkcs8', format: 'pem' }),
  })
  try {
    const s = await api(apiServer.base, '/signup', { method: 'POST', body: signupBody(`again-${Date.now()}@example.test`) })
    assert.equal((await api(apiServer.base, '/program', { cookie: s.cookie })).json.status, 'TERMINATED')

    const anon = await api(apiServer.base, '/program/reapply', { method: 'POST', body: { acceptTerms: true } })
    assert.equal(anon.res.status, 401)
    const noTerms = await api(apiServer.base, '/program/reapply', { method: 'POST', cookie: s.cookie, body: {} })
    assert.equal(noTerms.res.status, 400)
    assert.equal(applications.length, 1, 'nothing is sent without accepting the terms')

    const ok = await api(apiServer.base, '/program/reapply', { method: 'POST', cookie: s.cookie, body: { acceptTerms: true } })
    assert.equal(ok.res.status, 200)
    assert.equal(ok.json.status, 'APPLIED')
    assert.equal(applications.length, 2)
    assert.equal(applications[1].contact_email, applications[0].contact_email)
    assert.ok(!JSON.stringify(ok.json).includes(fresh), 'service partner id is never sent to the browser')

    const again = await api(apiServer.base, '/program/reapply', { method: 'POST', cookie: s.cookie, body: { acceptTerms: true } })
    assert.equal(again.res.status, 409, 'only an ended partnership can apply again')
    assert.equal(applications.length, 2)
  } finally {
    await apiServer.close()
    fake.close()
    await rm(tmp, { recursive: true, force: true })
  }
})
