import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import {
  BOOKING_V2_SITE,
  COUNTRY_CODES,
  buildBookingPayload,
  buildCalendarMonth,
  buildMarketDateOptions,
  calendarMonthFromDays,
  countryNameForApi,
  countryOptions,
  interpretAvailability,
  interpretBooking,
  isBookingConfigured,
  shiftCalendarMonth,
  statesForCountry,
} from './bookingClient.js'

test('Ledgerline booking site id is ledgerline only', () => {
  assert.equal(BOOKING_V2_SITE, 'ledgerline')
})

test('country catalog is searchable ISO list including Kosovo', () => {
  const options = countryOptions()
  assert.ok(options.length > 200)
  assert.ok(COUNTRY_CODES.includes('XK'))
  assert.ok(options.some((item) => item.code === 'XK'))
  assert.equal(
    options.some((item) => /other/i.test(item.name) && item.code === 'OTHER'),
    false,
  )
  assert.equal(countryNameForApi('AU', options), 'Australia')
  assert.ok((statesForCountry('AU')?.length || 0) > 0)
  assert.equal(statesForCountry('ZZ'), null)
})

test('buildBookingPayload keeps ledgerline questionnaire answers, state, and consent', () => {
  const payload = buildBookingPayload({
    form: {
      get: (name) => {
        const values = {
          size: '2–10 people',
          system: 'Xero',
          systemName: '',
          bottleneck: 'Manual invoice data entry',
          first: 'Ada',
          last: 'Lovelace',
          email: 'ada@example.test',
          phone: '+61 400 000 000',
          org: 'Analytical Engines',
          state: 'New South Wales',
          country: 'Australia',
          consent: 'yes',
        }
        return values[name] || ''
      },
    },
    slotStart: '2026-11-18T00:00:00.000Z',
    turnstileToken: 'tok',
    idempotencyKey: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  })
  assert.equal(payload.answers.first, 'Ada')
  assert.equal(payload.answers.state, 'New South Wales')
  assert.equal(payload.answers.country, 'Australia')
  assert.equal(payload.answers.consent, true)
})

test('availability and booking interpreters stay contract-safe', () => {
  const avail = interpretAvailability(200, {
    status: 'ok',
    slots: [{ start: '2026-11-18T00:00:00.000Z', date: '2026-11-18', time: '11:00' }],
    timeZone: 'Australia/Sydney',
    openWeekdays: [1, 2, 3, 4, 5],
    horizonDays: 14,
  })
  assert.equal(avail.kind, 'ok')
  assert.equal(avail.timeZone, 'Australia/Sydney')
  const days = buildMarketDateOptions(new Date('2026-11-15T00:00:00Z'), avail.slots, avail)
  assert.ok(days.some((day) => day.date === '2026-11-18' && day.available))
  const month = calendarMonthFromDays(days, '2026-11-18')
  const grid = buildCalendarMonth(month.year, month.month, days, '2026-11-18')
  assert.equal(grid.weekdays[0], 'Mon')
  assert.equal(grid.cells.length, 42)
  assert.ok(grid.cells.some((cell) => cell.date === '2026-11-18' && cell.available && !cell.disabled))
  assert.deepEqual(shiftCalendarMonth(2026, 10, 1), { year: 2026, month: 11 })

  const booked = interpretBooking(200, {
    status: 'confirmed',
    reference: 'LL-1',
    slot: {
      start: '2026-11-18T00:00:00.000Z',
      end: '2026-11-18T00:30:00.000Z',
      timeZone: 'Australia/Sydney',
    },
  })
  assert.equal(booked.kind, 'confirmed')
  assert.equal(interpretAvailability(503, { status: 'unavailable' }).kind, 'unavailable')

  const already = interpretBooking(409, { status: 'already_booked' })
  assert.equal(already.kind, 'already_booked')
  assert.match(already.message, /already has an upcoming booking/i)

  const limited = interpretBooking(429, { status: 'rate_limited', retryAfterSeconds: 90 })
  assert.equal(limited.kind, 'retry_later')
  assert.match(limited.message, /too many attempts/i)
})

test('booking is configured only with https API base and Turnstile site key', () => {
  assert.equal(isBookingConfigured({ siteKey: '0xpublic', apiBase: 'https://booking.example.test' }), true)
  assert.equal(isBookingConfigured({ siteKey: '', apiBase: 'https://booking.example.test' }), false)
  assert.equal(isBookingConfigured({ siteKey: '0xpublic', apiBase: 'http://evil.example' }), false)
})

test('primary demo CTAs target /book-demo with ledgerline site wiring and calendar UX', async () => {
  const nav = await readFile(new URL('../data/navigation.js', import.meta.url), 'utf8')
  assert.match(nav, /export const bookDemoPath = '\/book-demo'/)

  const home = await readFile(new URL('../pages/QuantumLedgerLinkPage.jsx', import.meta.url), 'utf8')
  assert.match(home, /bookDemoPath/)
  assert.match(home, /Book a demo/)

  const page = await readFile(new URL('../pages/BookDemoPage.jsx', import.meta.url), 'utf8')
  assert.match(page, /BOOKING_V2_SITE/)
  assert.match(page, /availabilityV2/)
  assert.match(page, /bookV2/)
  assert.match(page, /CountryCombobox/)
  assert.match(page, /role="combobox"/)
  assert.equal(/statesForCountry/.test(page), false)
  assert.equal(/State \/ province/.test(page), false)
  assert.equal(/Privacy Policy \(link to be added\)/.test(page), false)
  assert.match(page, /buildCalendarMonth/)
  assert.match(page, /Refresh times/)
  assert.match(page, /timeZone/)
  assert.equal(/Load available times/.test(page), false)
  assert.equal(/id="country-search"/.test(page), false)

  const client = await readFile(new URL('./bookingClient.js', import.meta.url), 'utf8')
  assert.match(client, /export const BOOKING_V2_SITE = 'ledgerline'/)
  assert.equal(/BOOKING_V2_SITE = 'agent'/.test(client), false)
  assert.equal(/BOOKING_V2_SITE = 'hva'/.test(client), false)
  assert.equal(/BOOKING_V2_SITE = 'qvm'/.test(client), false)
})
