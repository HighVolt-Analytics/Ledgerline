import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { tourPath } from '../data/navigation';
import { Clock, FileCheck2, Hand, Play, ShieldCheck, Target } from 'lucide-react';
import Header from '../components/layout/Header';
import SiteFooter from '../components/layout/SiteFooter';
import {
  CONTACT,
  buildBookingPayload,
  buildDateOptions,
  confirmationDetails,
  createBookingApi,
  formatSydneyTime,
  idempotencyKeyFor,
  interpretAvailability,
  interpretBooking,
  isBookingConfigured,
  localEquivalent,
  sydneyZoneLabel,
} from '../lib/bookingClient';
import '../qll.css';

const API_BASE = 'https://func-qvm-bookdemo-prod-aue.azurewebsites.net';
const SITE_KEY = '0x4AAAAAAFdkE2jqh1bsE-WB';
const TURNSTILE_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
const BOOKING_READY = isBookingConfigured({ siteKey: SITE_KEY, apiBase: API_BASE });
const MAILTO = `mailto:${CONTACT}?subject=Book%20a%20Demo`;
const PARTNER = 'We are an accounting, audit or vCFO firm';

const EMPTY = {
  size: '',
  partner: false,
  system: '',
  systemName: '',
  bottleneck: [],
  first: '',
  last: '',
  email: '',
  phone: '',
  org: '',
  state: 'Australia',
  consent: false,
};

const SIZE_OPTIONS = ['Solo / small team', '2–10 people', '11–50 people', '51+ people'];

const SYSTEMS = [
  'Xero',
  'QuickBooks',
  'MYOB',
  'SAP / Oracle / NetSuite',
  'Microsoft Dynamics / Business Central',
  'Tally / Zoho Books',
  'Other / multiple systems',
];

const BOTTLENECKS = [
  'Manual invoice data entry',
  'Collecting invoices from email',
  'Slow approval workflows',
  'Duplicate invoices or payment risk',
  'PO / GRN / invoice matching',
  'Supplier onboarding and bank checks',
  'Bank reconciliation and reporting',
  'Managing multiple entities or clients',
];

const COUNTRY_CODES = 'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS XK YE YT ZA ZM ZW'.split(' ');

const COUNTRIES = (() => {
  const display = new Intl.DisplayNames(['en'], { type: 'region' });
  const names = COUNTRY_CODES.map((code) => display.of(code)).filter((name) => name && !COUNTRY_CODES.includes(name));
  const rest = [...new Set(names)].filter((name) => name !== 'Australia');
  rest.sort((a, b) => a.localeCompare(b, 'en'));
  return ['Australia', ...rest];
})();

const EXPECT = [
  [Clock, '30 minutes on video, at a time that suits you.'],
  [Target, 'We map your invoice-to-pay workflow and current ERP.'],
  [FileCheck2, 'See invoice capture, validation, coding and matching.'],
  [ShieldCheck, 'Review approvals, exceptions, audit trail and integration.'],
  [Hand, 'No obligation. Pricing follows document volumes and setup.'],
];

let turnstileLoading = null;
function loadTurnstile() {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  turnstileLoading ??= new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = TURNSTILE_SRC;
    script.async = true;
    script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error('turnstile')));
    script.onerror = () => {
      turnstileLoading = null;
      reject(new Error('turnstile'));
    };
    document.head.appendChild(script);
  });
  return turnstileLoading;
}

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function scrollToNode(node) {
  node?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });
}

function validate(values) {
  const errors = {};
  if (!values.size) errors.size = 'Please select your business or practice size.';
  if (!values.system) errors.system = 'Please select your accounting or ERP software.';
  if (!values.bottleneck.length) errors.bottleneck = 'Please choose at least one bottleneck.';
  if (!values.first.trim()) errors.first = 'Please enter your first name.';
  if (!values.last.trim()) errors.last = 'Please enter your last name.';
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email.trim())) errors.email = 'Please enter a valid email address.';
  if (values.phone.trim() && !/^[0-9+()\s.-]{6,32}$/.test(values.phone.trim())) {
    errors.phone = 'Please enter a valid phone number.';
  }
  if (!values.org.trim()) errors.org = 'Please enter your business or accounting firm.';
  if (!values.consent) errors.consent = 'Please confirm so we can contact you.';
  return errors;
}

function Choice({ name, value, checked, onChange, children, center, stack, disabled, label, type = 'radio' }) {
  return (
    <label className={`choice${center ? ' choice--center' : ''}${stack ? ' choice--stack' : ''}`}>
      <input
        type={type}
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        aria-label={label}
        onChange={onChange}
      />
      <span>{children}</span>
    </label>
  );
}

export default function BookDemoPage() {
  const api = useRef(createBookingApi({ baseUrl: API_BASE })).current;
  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [stage, setStage] = useState('questions');
  const [days, setDays] = useState([]);
  const [date, setDate] = useState(null);
  const [slot, setSlot] = useState(null);
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState('');
  const [status, setStatus] = useState('');
  const [stepError, setStepError] = useState(false);
  const [tsError, setTsError] = useState(false);
  const [confirmation, setConfirmation] = useState(null);
  const [pending, setPending] = useState(null);
  const attemptRef = useRef(null);
  const widgetId = useRef(null);
  const tsBox = useRef(null);
  const formRef = useRef(null);
  const stepRef = useRef(null);
  const resultRef = useRef(null);

  useEffect(() => {
    document.body.classList.add('qll-page');
    document.title = 'Book a demo — Quantum Ledger Line';
    window.scrollTo(0, 0);
    return () => document.body.classList.remove('qll-page');
  }, []);

  useEffect(() => {
    if (stage !== 'times') return undefined;
    let cancelled = false;
    loadTurnstile()
      .then((turnstile) => {
        if (cancelled || !tsBox.current || widgetId.current !== null) return;
        widgetId.current = turnstile.render(tsBox.current, {
          sitekey: SITE_KEY,
          action: 'book_demo',
          theme: 'dark',
          size: 'flexible',
          callback: (next) => {
            setToken(next);
            setTsError(false);
          },
          'expired-callback': () => setToken(''),
          'timeout-callback': () => setToken(''),
          'error-callback': () => {
            setToken('');
            setStatus(`The security check couldn't run. Please refresh the page, or email ${CONTACT}.`);
          },
        });
      })
      .catch(() => {
        if (!cancelled) setStatus(`The security check couldn't load. Please refresh the page, or email ${CONTACT}.`);
      });
    return () => {
      cancelled = true;
      if (widgetId.current !== null && window.turnstile) {
        try {
          window.turnstile.remove(widgetId.current);
        } catch {
          /* widget already gone */
        }
        widgetId.current = null;
      }
    };
  }, [stage]);

  useEffect(() => {
    if (stage !== 'booked' && stage !== 'pending' && stage !== 'unavailable') return;
    const node = resultRef.current;
    node?.focus({ preventScroll: true });
    scrollToNode(node);
  }, [stage]);

  const activeDay = days.find((day) => day.date === date);
  const zoneNote = activeDay?.slots?.[0]
    ? `All times are Sydney time, ${sydneyZoneLabel(new Date(activeDay.slots[0].start))}.`
    : 'All times are Sydney time.';
  const timesHint = !activeDay?.slots?.length
    ? 'Choose a date to see available times.'
    : `${activeDay.slots.length} available ${activeDay.slots.length === 1 ? 'time' : 'times'} on ${activeDay.longLabel}.`;

  function setField(name, value) {
    setValues((current) => ({ ...current, [name]: value }));
    setErrors((current) => {
      if (!current[name]) return current;
      const next = { ...current };
      delete next[name];
      return next;
    });
  }

  function resetTurnstile() {
    setToken('');
    if (window.turnstile && widgetId.current !== null) {
      try {
        window.turnstile.reset(widgetId.current);
      } catch {
        widgetId.current = null;
      }
    }
  }

  async function loadTimes() {
    setBusy(true);
    setBusyLabel('Loading times…');
    const res = await api.availability();
    setBusy(false);
    if (res.network) {
      setStatus(`We couldn't load available times. Check your connection and try again, or email ${CONTACT}.`);
      return false;
    }
    const parsed = interpretAvailability(res.httpStatus, res.body);
    if (parsed.kind === 'unavailable') {
      setStage('unavailable');
      return false;
    }
    if (parsed.kind !== 'ok') {
      setStatus(parsed.message);
      return false;
    }
    const nextDays = buildDateOptions(new Date(), parsed.slots);
    const first = nextDays.find((day) => day.available);
    setDays(nextDays);
    setDate(first ? first.date : null);
    setSlot(null);
    setStepError(false);
    if (!parsed.slots.length) {
      setStatus(`No times are available in the next 14 days. Please email ${CONTACT} and we'll arrange one.`);
    }
    return true;
  }

  async function book() {
    if (!slot) {
      setStepError(true);
      setStatus('Please choose a time.');
      scrollToNode(stepRef.current);
      return;
    }
    if (!token) {
      setTsError(true);
      setStatus('Please complete the security check.');
      scrollToNode(tsBox.current?.closest('.field') || tsBox.current);
      return;
    }
    const email = values.email.trim();
    attemptRef.current = idempotencyKeyFor(
      attemptRef.current,
      { slotStart: slot.start, email },
      () => crypto.randomUUID(),
    );
    const payload = buildBookingPayload({
      form: {
        get: (name) => {
          if (name === 'consent') return values.consent ? 'yes' : '';
          if (name === 'bottleneck') return values.bottleneck.join(', ');
          if (name === 'size') return [values.size, values.partner ? PARTNER : ''].filter(Boolean).join(' — ');
          return String(values[name] ?? '');
        },
      },
      slotStart: slot.start,
      turnstileToken: token,
      idempotencyKey: attemptRef.current.key,
    });
    setBusy(true);
    setBusyLabel('Booking…');
    setStatus('');
    const res = await api.book(payload);
    setBusy(false);
    resetTurnstile();
    if (res.network) {
      setStatus("We couldn't reach the booking service. Please complete the security check and press Confirm booking again — you won't be booked twice.");
      return;
    }
    const parsed = interpretBooking(res.httpStatus, res.body);
    if (parsed.kind === 'confirmed') {
      setConfirmation(confirmationDetails(parsed, email));
      setStage('booked');
      return;
    }
    if (parsed.kind === 'pending') {
      setPending(parsed);
      setStage('pending');
      return;
    }
    attemptRef.current = null;
    if (parsed.kind === 'slot_gone') {
      setStatus(parsed.message);
      await loadTimes();
      scrollToNode(stepRef.current);
      return;
    }
    if (parsed.kind === 'invalid') {
      setStatus(parsed.message);
      const next = {};
      for (const field of parsed.fields) {
        next[field] = field === 'consent' ? 'Please confirm so we can contact you.' : 'Please check this detail.';
      }
      setErrors((current) => ({ ...current, ...next }));
      requestAnimationFrame(() => scrollToNode(formRef.current?.querySelector('.has-error')));
      return;
    }
    if (parsed.kind === 'verification') {
      setTsError(true);
      setStatus(parsed.message);
      return;
    }
    if (parsed.kind === 'unavailable') {
      setStage('unavailable');
      return;
    }
    setStatus(parsed.message);
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (busy || stage === 'booked' || stage === 'pending' || stage === 'unavailable') return;
    const nextErrors = validate(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      requestAnimationFrame(() => scrollToNode(formRef.current?.querySelector('.has-error')));
      return;
    }
    if (!BOOKING_READY) {
      setStage('unavailable');
      return;
    }
    if (stage === 'questions') {
      setStatus('');
      const loaded = await loadTimes();
      if (!loaded) return;
      setStage('times');
      requestAnimationFrame(() => {
        stepRef.current?.querySelector('legend')?.focus({ preventScroll: true });
        scrollToNode(stepRef.current);
      });
      return;
    }
    await book();
  }

  const showingForm = stage === 'questions' || stage === 'times';
  const submitLabel = busy ? busyLabel : stage === 'times' ? 'Confirm booking' : BOOKING_READY ? 'Choose a time' : 'Book my demo';

  return (
    <div className="qll-site book-demo-page">
      <Header />
      <main className="book-demo-main">
        <section className="book-hero">
          <div className="wrap">
            <span className="eyebrow">Book a Demo</span>
            <h1 className="h1">See your workflow, done for you.</h1>
            <p className="lead">Four quick questions. We’ll tailor a 30-minute demonstration to your invoice-to-pay workflow.</p>
          </div>
        </section>

        <section className="book-body">
          <div className="wrap book-split">
            <div className="book-panel">
              {showingForm ? (
                <form className="book-form" ref={formRef} onSubmit={onSubmit} noValidate>
                  <fieldset className={`book-fieldset${errors.size ? ' has-error' : ''}`}>
                    <legend>
                      <span className="n">01</span>Business or practice size
                    </legend>
                    <div className="choice-grid choice-grid--4" role="radiogroup" aria-label="Business or practice size">
                      {SIZE_OPTIONS.map((label) => (
                        <Choice
                          key={label}
                          name="size"
                          value={label}
                          center
                          checked={values.size === label}
                          onChange={() => setField('size', label)}
                        >
                          {label}
                        </Choice>
                      ))}
                    </div>
                    <Choice
                      name="partner"
                      type="checkbox"
                      value="yes"
                      checked={values.partner}
                      onChange={() => setField('partner', !values.partner)}
                    >
                      {PARTNER}
                    </Choice>
                    <span className="err">{errors.size}</span>
                  </fieldset>

                  <fieldset className="book-fieldset">
                    <legend>
                      <span className="n">02</span>Current accounting system
                    </legend>
                    <div className={`book-field${errors.system ? ' has-error' : ''}`}>
                      <label htmlFor="sys">What accounting or ERP software do you use?</label>
                      <select
                        className="book-input"
                        id="sys"
                        name="system"
                        value={values.system}
                        aria-invalid={errors.system ? 'true' : undefined}
                        onChange={(event) => setField('system', event.target.value)}
                      >
                        <option value="">Select one</option>
                        {SYSTEMS.map((system) => (
                          <option key={system}>{system}</option>
                        ))}
                      </select>
                      <span className="err">{errors.system}</span>
                    </div>
                    <div className="book-field">
                      <label htmlFor="sysname">
                        System name / details <span className="muted">(optional)</span>
                      </label>
                      <input
                        className="book-input"
                        id="sysname"
                        name="systemName"
                        placeholder="Optional: ERP, invoice volume or existing AP tools"
                        value={values.systemName}
                        onChange={(event) => setField('systemName', event.target.value)}
                      />
                    </div>
                  </fieldset>

                  <fieldset className={`book-fieldset${errors.bottleneck ? ' has-error' : ''}`}>
                    <legend>
                      <span className="n">03</span>Biggest bottleneck
                    </legend>
                    <div className="choice-grid" role="group" aria-label="Select biggest bottlenecks">
                      {BOTTLENECKS.map((label) => (
                        <Choice
                          key={label}
                          name="bottleneck"
                          type="checkbox"
                          value={label}
                          checked={values.bottleneck.includes(label)}
                          onChange={() =>
                            setField(
                              'bottleneck',
                              values.bottleneck.includes(label)
                                ? values.bottleneck.filter((item) => item !== label)
                                : [...values.bottleneck, label],
                            )
                          }
                        >
                          {label}
                        </Choice>
                      ))}
                    </div>
                    <span className="err">{errors.bottleneck}</span>
                  </fieldset>

                  <fieldset className={`book-fieldset${errors.consent ? ' has-error' : ''}`}>
                    <legend>
                      <span className="n">04</span>Contact details
                    </legend>
                    <div className="book-row">
                      <div className={`book-field${errors.first ? ' has-error' : ''}`}>
                        <label htmlFor="first">First name</label>
                        <input
                          className="book-input"
                          id="first"
                          name="first"
                          autoComplete="given-name"
                          aria-invalid={errors.first ? 'true' : undefined}
                          value={values.first}
                          onChange={(event) => setField('first', event.target.value)}
                        />
                        <span className="err">{errors.first}</span>
                      </div>
                      <div className={`book-field${errors.last ? ' has-error' : ''}`}>
                        <label htmlFor="last">Last name</label>
                        <input
                          className="book-input"
                          id="last"
                          name="last"
                          autoComplete="family-name"
                          aria-invalid={errors.last ? 'true' : undefined}
                          value={values.last}
                          onChange={(event) => setField('last', event.target.value)}
                        />
                        <span className="err">{errors.last}</span>
                      </div>
                      <div className={`book-field${errors.email ? ' has-error' : ''}`}>
                        <label htmlFor="email">Work email</label>
                        <input
                          className="book-input"
                          id="email"
                          name="email"
                          type="email"
                          autoComplete="email"
                          aria-invalid={errors.email ? 'true' : undefined}
                          value={values.email}
                          onChange={(event) => setField('email', event.target.value)}
                        />
                        <span className="err">{errors.email}</span>
                      </div>
                      <div className={`book-field${errors.phone ? ' has-error' : ''}`}>
                        <label htmlFor="phone">
                          Phone <span className="muted">(optional)</span>
                        </label>
                        <input
                          className="book-input"
                          id="phone"
                          name="phone"
                          type="tel"
                          autoComplete="tel"
                          placeholder="04xx xxx xxx"
                          aria-invalid={errors.phone ? 'true' : undefined}
                          value={values.phone}
                          onChange={(event) => setField('phone', event.target.value)}
                        />
                        <span className="err">{errors.phone}</span>
                      </div>
                      <div className={`book-field${errors.org ? ' has-error' : ''}`}>
                        <label htmlFor="org">Business or accounting firm</label>
                        <input
                          className="book-input"
                          id="org"
                          name="org"
                          autoComplete="organization"
                          aria-invalid={errors.org ? 'true' : undefined}
                          value={values.org}
                          onChange={(event) => setField('org', event.target.value)}
                        />
                        <span className="err">{errors.org}</span>
                      </div>
                      <div className="book-field">
                        <label htmlFor="country">Country</label>
                        <select
                          className="book-input"
                          id="country"
                          name="state"
                          autoComplete="country-name"
                          value={values.state}
                          onChange={(event) => setField('state', event.target.value)}
                        >
                          {COUNTRIES.map((item) => (
                            <option key={item}>{item}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <label className="book-consent">
                      <input
                        type="checkbox"
                        name="consent"
                        value="yes"
                        checked={values.consent}
                        onChange={(event) => setField('consent', event.target.checked)}
                      />
                      <span>
                        I agree to High Volt Analytics contacting me about this demonstration, as described in the Privacy Policy (link to be added).
                      </span>
                    </label>
                    <span className="err">{errors.consent}</span>
                  </fieldset>

                  {stage === 'times' ? (
                    <fieldset
                      className={`book-fieldset${stepError ? ' has-error' : ''}`}
                      ref={stepRef}
                      data-booking-step
                    >
                      <legend tabIndex={-1}>
                        <span className="n">05</span>Choose a time
                      </legend>
                      <p className="book-zone">{zoneNote}</p>
                      <div className="book-field">
                        <span className="book-label" id="bk-date-label">
                          Date
                        </span>
                        <div className="choice-grid booking-dates" role="radiogroup" aria-labelledby="bk-date-label">
                          {days.map((day) => {
                            const unavailable = day.closed || !day.available;
                            const sub = day.closed ? 'Closed' : day.available ? `${day.slots.length} ${day.slots.length === 1 ? 'time' : 'times'}` : 'No times';
                            return (
                              <Choice
                                key={day.date}
                                name="bookingDate"
                                value={day.date}
                                center
                                stack
                                disabled={unavailable}
                                checked={date === day.date}
                                label={`${day.longLabel}${day.closed ? ', closed' : !day.available ? ', no times available' : ''}`}
                                onChange={() => {
                                  setDate(day.date);
                                  setSlot(null);
                                  setStepError(false);
                                  setStatus('');
                                }}
                              >
                                <b>{day.label}</b>
                                <small>{sub}</small>
                              </Choice>
                            );
                          })}
                        </div>
                      </div>
                      <div className="book-field">
                        <span className="book-label" id="bk-time-label">
                          Time <span className="muted">(30 minutes)</span>
                        </span>
                        <div className="choice-grid booking-times" role="radiogroup" aria-labelledby="bk-time-label">
                          {(activeDay?.slots || []).map((item) => {
                            const local = localEquivalent(item.start);
                            return (
                              <Choice
                                key={item.start}
                                name="bookingSlot"
                                value={item.start}
                                center
                                stack
                                checked={slot?.start === item.start}
                                onChange={() => {
                                  setSlot(item);
                                  setStepError(false);
                                  setStatus('');
                                }}
                              >
                                <b>{formatSydneyTime(item.start)}</b>
                                {local ? <small>{local} your time</small> : null}
                              </Choice>
                            );
                          })}
                        </div>
                        <p className="book-hint">{timesHint}</p>
                      </div>
                      <span className="err">Please choose a time.</span>
                      <div className={`book-field${tsError ? ' has-error' : ''}`}>
                        <span className="book-label">Security check</span>
                        <div className="turnstile-box" ref={tsBox} />
                        <span className="err">Please complete the security check.</span>
                      </div>
                      <p className="book-fine">
                        Your demo is booked in High Volt Analytics’ Microsoft 365 calendar, which sends your Microsoft Teams invitation.
                        Cloudflare Turnstile checks that this request comes from a person.
                      </p>
                    </fieldset>
                  ) : null}

                  <p className={`book-status${status ? ' is-on' : ''}`} role="status" aria-live="polite">
                    {status}
                  </p>
                  <div className="book-submit">
                    <p className="book-note">
                      {stage === 'times' ? (
                        'Your time is reserved only when this page confirms the booking.'
                      ) : BOOKING_READY ? (
                        'Next, choose a 30-minute time. Times are shown in Sydney time.'
                      ) : (
                        <>
                          Online scheduling is temporarily unavailable. To arrange a demo, email{' '}
                          <a className="book-link" href={MAILTO}>
                            {CONTACT}
                          </a>
                          .
                        </>
                      )}
                    </p>
                    <button className="btn btn-primary" type="submit" disabled={busy} aria-busy={busy}>
                      {busy ? <span className="book-spinner" aria-hidden="true" /> : null}
                      {submitLabel}
                    </button>
                  </div>
                </form>
              ) : null}

              {stage === 'booked' && confirmation ? (
                <div className="book-success booked is-on is-celebrating" ref={resultRef} role="status" tabIndex={-1}>
                  <div className="booked-mark" aria-hidden="true">
                    <span className="booked-glow" />
                    <span className="booked-sparks">
                      <i /><i /><i /><i /><i /><i />
                    </span>
                    <span className="ok">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M5 12.5l4.5 4.5L19 7.5" />
                      </svg>
                    </span>
                  </div>
                  <h2 className="h2" id="booked-title">You’re booked in.</h2>
                  <p className="book-lead">Your demonstration is confirmed. A Microsoft Teams invitation is on its way.</p>
                  <dl className="booked-summary">
                    <div className="booked-row"><dt>Date</dt><dd>{confirmation.date}</dd></div>
                    <div className="booked-row">
                      <dt>Time</dt>
                      <dd>
                        <span>{confirmation.time}</span>
                        <span className="booked-zone">{confirmation.zone}</span>
                      </dd>
                    </div>
                    {confirmation.local ? (
                      <div className="booked-row"><dt>Your local time</dt><dd>{confirmation.local}</dd></div>
                    ) : null}
                    <div className="booked-row"><dt>Invitation sent to</dt><dd>{confirmation.email}</dd></div>
                    <div className="booked-row"><dt>Booking reference</dt><dd className="booked-ref">{confirmation.reference}</dd></div>
                  </dl>
                  <p className="book-help">
                    Accept the invitation to add the demo to your calendar. Not in your inbox within a few minutes? Check your junk or spam folder, or email{' '}
                    <a className="book-link" href={MAILTO}>{CONTACT}</a> with your reference. To change the time, reply to the invitation.
                  </p>
                  <div className="book-actions">
                    <Link className="btn btn-ghost" to="/interactive-tour">Explore the interactive tour</Link>
                    <Link className="btn btn-ghost" to="/">Back to home</Link>
                  </div>
                </div>
              ) : null}

              {stage === 'pending' && pending ? (
                <div className="book-success is-on" ref={resultRef} role="status" tabIndex={-1}>
                  <span className="ok" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 10.5v6" />
                      <path d="M12 7.5h.01" />
                    </svg>
                  </span>
                  <h2 className="h2">We’re finalising your booking.</h2>
                  <p className="book-lead">
                    {pending.message || `Your Teams invitation should arrive within a few minutes. If it doesn't, email ${CONTACT}.`}
                  </p>
                  <p className="book-help">
                    Reference <b>{pending.reference || '—'}</b>
                  </p>
                </div>
              ) : null}

              {stage === 'unavailable' ? (
                <div className="book-success is-on" ref={resultRef} role="status" tabIndex={-1}>
                  <span className="ok" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 10.5v6" />
                      <path d="M12 7.5h.01" />
                    </svg>
                  </span>
                  <h2 className="h2">Online scheduling is temporarily unavailable.</h2>
                  <p className="book-lead">
                    No demo has been booked. To arrange one, please email{' '}
                    <a className="book-link" href={MAILTO}>{CONTACT}</a>.
                  </p>
                  <div className="book-actions">
                    <a className="btn btn-primary" href={MAILTO}>Email {CONTACT}</a>
                    <button className="btn btn-ghost" type="button" onClick={() => setStage('questions')}>
                      Back to the form
                    </button>
                  </div>
                </div>
              ) : null}
            </div>

            <aside className="book-aside">
              <div>
                <h2 className="h3">What to expect</h2>
                <ul className="book-expect">
                  {EXPECT.map(([Icon, text]) => (
                    <li key={text}>
                      <Icon aria-hidden="true" />
                      <span>{text}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="book-watch">
                <span className="eyebrow">Prefer a quick look first?</span>
                <p>Watch the email-to-ERP workflow and see where human review fits into the process.</p>
                <Link className="book-link book-watch-btn" to={tourPath}>
                  <Play aria-hidden="true" /> Watch It Work
                </Link>
              </div>
            </aside>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}
