/* Book a Demo client logic: no DOM access, so it can be unit-tested in Node. */

export const SYDNEY = 'Australia/Sydney'
export const HORIZON_DAYS = 14
export const CONTACT = 'arup@highvolt.tech'

const pad = (n) => String(n).padStart(2, '0')

function sydneyYmd(date) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', { timeZone: SYDNEY, year: 'numeric', month: '2-digit', day: '2-digit' })
      .formatToParts(date)
      .map(({ type, value }) => [type, value]),
  )
  return { year: Number(p.year), month: Number(p.month), day: Number(p.day) }
}

const utcDayFormat = new Intl.DateTimeFormat('en-AU', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' })

function shortDayLabel(utc) {
  const p = Object.fromEntries(utcDayFormat.formatToParts(utc).map(({ type, value }) => [type, value]))
  return `${p.weekday} ${p.day} ${p.month}`
}

const utcLongFormat = new Intl.DateTimeFormat('en-AU', { timeZone: 'UTC', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

/** Sydney calendar days from today through the 14-day horizon. Saturdays are marked closed. */
export function buildDateOptions(now, slots) {
  const today = sydneyYmd(now)
  const byDate = groupSlotsByDate(slots)
  const days = []
  for (let i = 0; i <= HORIZON_DAYS; i++) {
    const utc = new Date(Date.UTC(today.year, today.month - 1, today.day + i))
    const key = `${utc.getUTCFullYear()}-${pad(utc.getUTCMonth() + 1)}-${pad(utc.getUTCDate())}`
    const closed = utc.getUTCDay() === 6
    const daySlots = closed ? [] : byDate.get(key) || []
    days.push({
      date: key,
      label: shortDayLabel(utc),
      longLabel: utcLongFormat.format(utc),
      closed,
      available: daySlots.length > 0,
      slots: daySlots,
    })
  }
  return days
}

export function groupSlotsByDate(slots) {
  const map = new Map()
  for (const s of slots || []) {
    if (!s || typeof s.start !== 'string' || typeof s.date !== 'string') continue
    if (!map.has(s.date)) map.set(s.date, [])
    map.get(s.date).push(s)
  }
  for (const list of map.values()) list.sort((a, b) => a.start.localeCompare(b.start))
  return map
}

export function formatSydneyTime(iso) {
  return new Intl.DateTimeFormat('en-AU', { timeZone: SYDNEY, hour: 'numeric', minute: '2-digit', hour12: true })
    .format(new Date(iso))
    .replace(/\s+/g, ' ')
    .toLowerCase()
}

/** e.g. "AEDT (UTC+11)" for the given instant. */
export function sydneyZoneLabel(date) {
  const name = new Intl.DateTimeFormat('en-AU', { timeZone: SYDNEY, timeZoneName: 'short' })
    .formatToParts(date)
    .find((p) => p.type === 'timeZoneName')?.value
  const minutes = sydneyOffsetMinutes(date)
  const sign = minutes >= 0 ? '+' : '-'
  const abs = Math.abs(minutes)
  const offset = `UTC${sign}${Math.floor(abs / 60)}${abs % 60 ? `:${pad(abs % 60)}` : ''}`
  return name && !/^GMT|^UTC/.test(name) ? `${name} (${offset})` : offset
}

function sydneyOffsetMinutes(date) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', { timeZone: SYDNEY, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
      .formatToParts(date)
      .map(({ type, value }) => [type, value]),
  )
  const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute)
  return Math.round((asUtc - Math.floor(date.getTime() / 60000) * 60000) / 60000)
}

/** The visitor's local equivalent, or null when they are already on Sydney time. */
export function localEquivalent(iso, visitorZone) {
  const zone = visitorZone || Intl.DateTimeFormat().resolvedOptions().timeZone
  const d = new Date(iso)
  if (!zone || sydneyOffsetMinutes(d) === zoneOffsetMinutes(d, zone)) return null
  return new Intl.DateTimeFormat('en-AU', { timeZone: zone, weekday: 'short', hour: 'numeric', minute: '2-digit', hour12: true, timeZoneName: 'short' })
    .format(d)
    .replace(/\s+/g, ' ')
}

const longSydneyDate = new Intl.DateTimeFormat('en-AU', { timeZone: SYDNEY, weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

/** The visitor's local date and time range, or null when they are already on Sydney time. */
export function localAppointment(startIso, endIso, visitorZone) {
  const zone = visitorZone || Intl.DateTimeFormat().resolvedOptions().timeZone
  const start = new Date(startIso)
  if (!zone || sydneyOffsetMinutes(start) === zoneOffsetMinutes(start, zone)) return null
  const time = (iso) =>
    new Intl.DateTimeFormat('en-AU', { timeZone: zone, hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(iso)).replace(/\s+/g, ' ').toLowerCase()
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-AU', { timeZone: zone, weekday: 'long', day: 'numeric', month: 'long', timeZoneName: 'short' })
      .formatToParts(start)
      .map(({ type, value }) => [type, value]),
  )
  const range = endIso ? `${time(startIso)}–${time(endIso)}` : time(startIso)
  return `${parts.weekday} ${parts.day} ${parts.month}, ${range} ${parts.timeZoneName}`
}

/**
 * Everything the confirmation screen shows, derived only from the booking API's confirmed
 * slot and reference plus the email address the visitor entered.
 */
export function confirmationDetails({ slot, reference }, email, visitorZone) {
  const start = new Date(slot.start)
  return {
    date: longSydneyDate.format(start),
    time: slot.end ? `${formatSydneyTime(slot.start)}–${formatSydneyTime(slot.end)}` : formatSydneyTime(slot.start),
    zone: `Sydney time, ${sydneyZoneLabel(start)}`,
    local: localAppointment(slot.start, slot.end, visitorZone),
    email: String(email || '').trim(),
    reference: String(reference),
  }
}

function zoneOffsetMinutes(date, zone) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', { timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
      .formatToParts(date)
      .map(({ type, value }) => [type, value]),
  )
  return Math.round((Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute) - Math.floor(date.getTime() / 60000) * 60000) / 60000)
}

const FIELD_NAMES = ['size', 'system', 'systemName', 'bottleneck', 'first', 'last', 'email', 'phone', 'org', 'state']

/** Builds the exact request body the booking API validates. */
export function buildBookingPayload({ form, slotStart, turnstileToken, idempotencyKey }) {
  const answers = {}
  for (const name of FIELD_NAMES) answers[name] = String(form.get(name) ?? '').trim()
  answers.consent = form.get('consent') === 'yes'
  return { idempotencyKey, slotStart, turnstileToken, answers }
}

/** Reuses the idempotency key only when retrying the identical booking. */
export function idempotencyKeyFor(previous, { slotStart, email }, newKey) {
  const fingerprint = `${slotStart}|${String(email).trim().toLowerCase()}`
  if (previous && previous.fingerprint === fingerprint) return previous
  return { key: newKey(), fingerprint }
}

/** API messages name the service's own contact address; visitors are pointed to CONTACT instead. */
export const withBookingContact = (message) => String(message || '').replace(/[A-Za-z0-9._%+-]+@highvolt\.tech/gi, CONTACT)

const fallback = (message) => withBookingContact(message) || `Something went wrong. Please try again or email ${CONTACT}.`

/** Maps a booking API response to what the page should do next. Never invents a confirmation. */
export function interpretBooking(httpStatus, body) {
  const b = body && typeof body === 'object' ? body : {}
  const message = typeof b.message === 'string' ? withBookingContact(b.message) : ''
  if (httpStatus === 200 && b.status === 'confirmed' && b.slot?.start && b.reference) {
    return { kind: 'confirmed', reference: b.reference, slot: b.slot, message }
  }
  if (httpStatus === 202 && b.status === 'pending') return { kind: 'pending', reference: b.reference, slot: b.slot, message }
  switch (b.status) {
    case 'slot_taken':
    case 'slot_unavailable':
      return { kind: 'slot_gone', message: message || 'That time is no longer available. Please choose another.' }
    case 'already_booked':
      return { kind: 'already_booked', message: fallback(message) }
    case 'idempotency_conflict':
      return { kind: 'new_attempt', message: 'Please choose your time again and resubmit.' }
    case 'invalid':
      return { kind: 'invalid', fields: Array.isArray(b.fields) ? b.fields : [], message: 'Please check the highlighted details.' }
    case 'verification_failed':
      return { kind: 'verification', message: 'The security check expired or failed. Please complete it again.' }
    case 'rate_limited':
      return { kind: 'retry_later', message: fallback(message) }
    case 'unavailable':
      return { kind: 'unavailable', message: fallback(message) }
    default:
      return { kind: 'error', message: fallback(message) }
  }
}

export function interpretAvailability(httpStatus, body) {
  const b = body && typeof body === 'object' ? body : {}
  if (httpStatus === 200 && b.status === 'ok' && Array.isArray(b.slots)) return { kind: 'ok', slots: b.slots }
  if (b.status === 'unavailable') return { kind: 'unavailable', message: fallback(b.message) }
  if (b.status === 'rate_limited') return { kind: 'retry_later', message: fallback(b.message) }
  return { kind: 'error', message: fallback(b.message) }
}

/** Thin HTTPS client. Network failures and timeouts come back as { network: true }. */
export function createBookingApi({ baseUrl, fetchImpl = (...a) => fetch(...a), timeoutMs = 20000 }) {
  const root = String(baseUrl || '').replace(/\/+$/, '')
  async function call(path, init) {
    try {
      const res = await fetchImpl(`${root}${path}`, { ...init, credentials: 'omit', signal: AbortSignal.timeout(timeoutMs) })
      let body = null
      try {
        body = await res.json()
      } catch {
        body = null
      }
      return { httpStatus: res.status, body }
    } catch {
      return { network: true }
    }
  }
  return {
    availability: () => call('/api/availability', { method: 'GET', headers: { Accept: 'application/json' } }),
    book: (payload) =>
      call('/api/bookings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload),
      }),
  }
}

export function isBookingConfigured({ siteKey, apiBase }) {
  const base = String(apiBase || '')
  const secureBase = /^https:\/\/[^/]+/.test(base) || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/?$/.test(base)
  return typeof siteKey === 'string' && siteKey.trim().length > 0 && secureBase
}
