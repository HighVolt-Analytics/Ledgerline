/* LedgerLine Partner Program — prototype
   Sample data only. Stripe, email and payments are simulated in the browser. */
(() => {
  'use strict';

  const RATE = 0.20;
  const HOLD_DAYS = 30;
  const MIN_PAYOUT = 5000;
  const PAYOUT_DAY = 15;
  const TODAY0 = '2026-11-11';
  const SITE = 'https://www.quantumledgerline.com';

  const PLANS = {
    essentials: { name: 'Essentials', price: 7900, desc: 'For sole traders and small teams getting their books automated.',
      mods: ['Automated Bookkeeping', 'Intelligent Record Management', 'Human review of exceptions'], off: ['Invoice-to-Pay', 'Expense Management', 'Bank Intelligence'] },
    growth: { name: 'Growth', price: 15000, desc: 'The full finance automation suite for growing businesses.', popular: true,
      mods: ['Automated Bookkeeping', 'Intelligent Record Management', 'Invoice-to-Pay', 'Expense Management', 'Bank Intelligence', 'Human review of exceptions'], off: [] },
    scale: { name: 'Scale', price: 29900, desc: 'Multi-entity businesses with higher volumes and priority onboarding.',
      mods: ['Everything in Growth', 'Up to 5 entities', 'Priority onboarding and support', 'Advanced approval workflows'], off: [] },
  };
  const TAX = { AU: ['GST', 0.10], NZ: ['GST', 0.15], GB: ['VAT', 0.20] };
  const COUNTRIES = [['AU', 'Australia'], ['NZ', 'New Zealand'], ['GB', 'United Kingdom'], ['US', 'United States'], ['SG', 'Singapore'], ['IN', 'India']];
  const PTYPES = ['Accounting firm', 'Bookkeeper', 'Virtual CFO / outsourced CFO', 'Finance advisor'];

  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const M = (c, o = {}) => { const v = (Math.abs(c) / 100).toLocaleString('en-US', { minimumFractionDigits: o.whole ? 0 : 2, maximumFractionDigits: o.whole ? 0 : 2 }); return (c < 0 ? '\u2212' : '') + 'US$' + v; };
  const D = (s) => new Date(s + 'T00:00:00Z');
  const iso = (d) => d.toISOString().slice(0, 10);
  const addDays = (s, n) => { const d = D(s); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
  const addMonths = (s, n) => { const d = D(s); const day = d.getUTCDate(); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + n); const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate(); d.setUTCDate(Math.min(day, last)); return iso(d); };
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const fd = (s) => { if (!s) return '—'; const d = D(s); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  const fds = (s) => { const d = D(s); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]}`; };
  let seq = 1000;
  const rid = (p, n = 8) => p + Array.from({ length: n }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'[Math.floor(Math.random() * 56)]).join('');
  const nid = (p) => p + (++seq);
  const initials = (s) => s.split(/\s+/).filter((w) => /^[A-Za-z]/.test(w)).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
  const taxFor = (country) => TAX[country] || null;
  const cycleNet = (plan, cycle) => cycle === 'annual' ? PLANS[plan].price * 10 : PLANS[plan].price;
  const monthlyEq = (c) => c.cycle === 'annual' ? Math.round(PLANS[c.plan].price * 10 / 12) : PLANS[c.plan].price;

  const KEY = 'll-partners-v1';
  let mem = null;
  const store = {
    get() {
      try {
        const raw = localStorage.getItem(KEY);
        if (raw) return JSON.parse(raw);
      } catch { /* storage blocked */ }
      return mem ? JSON.parse(mem) : null;
    },
    set(v) {
      const raw = JSON.stringify(v);
      mem = raw;
      try { localStorage.setItem(KEY, raw); } catch { /* keep the in-memory copy */ }
    },
    clear() {
      mem = null;
      try { localStorage.removeItem(KEY); } catch { /* ignore */ }
    },
  };

  let S;
  const UI = { route: 'home', tab: 'overview', signupStep: 1, draft: {}, co: { plan: 'growth', cycle: 'monthly', step: 1, ref: null, done: null }, demoOpen: false, cfilter: 'all', errors: {} };

  function blankState() { return { today: TODAY0, partners: [], clients: [], invoices: [], commissions: [], payouts: [], invites: [], activity: [], session: null }; }

  function seed() {
    const s = blankState();
    const p = { id: 'P-1', code: 'ELMCO20', firm: 'Elm & Co Advisory', name: 'Sarah Chen', email: 'sarah@elmco.example', pw: 'demo1234', type: 'Accounting firm', country: 'AU', abn: '51 824 753 556', phone: '', created: '2026-05-04', status: 'approved', founding: true,
      stripe: { acct: 'acct_1QhL8mElmCo20AU', bank: 'Commonwealth Bank •••• 4821', holder: 'Elm & Co Advisory Pty Ltd', schedule: 'monthly', connected: '2026-05-06' } };
    s.partners.push(p);
    const C = [
      ['Harbour & Vine Café', 'Lena Morris', 'AU', 'growth', 'monthly', '2026-05-12', 'link'],
      ['Coastline Design Studio Pty Ltd', 'Kim Nguyen', 'AU', 'growth', 'monthly', '2026-05-20', 'invite'],
      ['Northside Physio Group', 'Raj Iyer', 'AU', 'scale', 'monthly', '2026-06-03', 'link'],
      ['Redgum Architects', 'Tom Walsh', 'AU', 'growth', 'monthly', '2026-06-18', 'link'],
      ['Bayview Medical Centre', 'Dr Amy Ford', 'AU', 'scale', 'annual', '2026-07-01', 'invite'],
      ['Lumen Dental', 'Priya Shah', 'AU', 'essentials', 'monthly', '2026-07-09', 'link'],
      ['Pixel & Co Studio', 'Jack Bell', 'AU', 'essentials', 'monthly', '2026-07-22', 'link'],
      ['Tidewater Logistics', 'Mark Daly', 'NZ', 'growth', 'monthly', '2026-08-05', 'link'],
      ['Saltbush Landscaping', 'Ben Cole', 'AU', 'essentials', 'monthly', '2026-08-27', 'link'],
      ['Meridian Freight', 'Sophie Lam', 'AU', 'growth', 'monthly', '2026-09-14', 'invite'],
      ['Kestrel Engineering', 'Omar Haddad', 'AU', 'scale', 'monthly', '2026-10-02', 'link'],
      ['Wattle & Pine Joinery', 'Ella Grant', 'AU', 'growth', 'monthly', '2026-10-21', 'link'],
    ];
    C.forEach((r, i) => {
      const c = { id: 'C-' + (101 + i), partnerId: p.id, biz: r[0], contact: r[1], email: r[1].toLowerCase().replace(/[^a-z]+/g, '.').replace(/^\.|\.$/g, '') + '@' + r[0].toLowerCase().replace(/[^a-z]+/g, '').slice(0, 14) + '.example', country: r[2], plan: r[3], cycle: r[4], start: r[5], nextBill: r[5], status: 'active', source: r[6], subId: 'sub_' + rid('', 14), cancelled: null, failNext: false };
      s.clients.push(c);
    });
    s.clients.forEach((c) => {
      while (c.nextBill <= s.today) {
        let fail = c.biz === 'Meridian Freight' && c.nextBill === '2026-10-14';
        billOnce(s, c, c.nextBill, fail, true);
        if (c.biz === 'Saltbush Landscaping' && c.nextBill > '2026-09-27') { c.status = 'cancelled'; c.cancelled = '2026-10-10'; break; }
        if (fail) { c.status = 'past_due'; break; }
      }
    });
    const sb = s.clients.find((c) => c.biz === 'Saltbush Landscaping');
    const sbInv = s.invoices.find((i) => i.clientId === sb.id && i.date === '2026-09-27');
    refundInvoice(s, sbInv, '2026-10-06', true);
    ['2026-06-15', '2026-07-15', '2026-08-15', '2026-09-15', '2026-10-15'].forEach((d) => runPayout(s, p, d, true));
    s.payouts.forEach((po) => { if (po.arrival <= s.today) po.status = 'paid'; });
    settle(s);
    s.invites.push({ id: 'I-1', partnerId: p.id, biz: 'Ironbark Brewing Co', email: 'accounts@ironbark.example', date: '2026-11-03', status: 'sent' });
    s.invites.push({ id: 'I-2', partnerId: p.id, biz: 'Seabreeze Pharmacy', email: 'owner@seabreeze.example', date: '2026-11-09', status: 'opened' });
    s.activity = [];
    s.clients.forEach((c) => s.activity.push({ partnerId: p.id, date: c.start, text: `${c.biz} subscribed to ${PLANS[c.plan].name}${c.cycle === 'annual' ? ' (annual)' : ''}` }));
    s.payouts.forEach((po) => s.activity.push({ partnerId: p.id, date: po.date, text: `Payout of ${M(po.amount)} sent to Stripe` }));
    s.activity.push({ partnerId: p.id, date: '2026-10-06', text: 'Saltbush Landscaping refunded — commission of US$15.80 reversed' });
    s.activity.push({ partnerId: p.id, date: '2026-10-14', text: 'Meridian Freight payment failed — no commission until it is collected' });
    s.activity.push({ partnerId: p.id, date: '2026-11-03', text: 'Invitation sent to Ironbark Brewing Co' });
    s.activity.push({ partnerId: p.id, date: '2026-11-09', text: 'Invitation sent to Seabreeze Pharmacy' });
    return s;
  }

  function billOnce(s, c, date, fail, quiet) {
    const net = cycleNet(c.plan, c.cycle);
    const tx = taxFor(c.country);
    const tax = tx ? Math.round(net * tx[1]) : 0;
    const inv = { id: 'in_' + rid('', 10), num: 'LL-' + (++seq), clientId: c.id, partnerId: c.partnerId, date, net, tax, total: net + tax, status: fail ? 'failed' : 'paid', period: c.cycle };
    s.invoices.push(inv);
    if (!fail && c.partnerId) {
      s.commissions.push({ id: nid('CM-'), partnerId: c.partnerId, clientId: c.id, invoiceId: inv.id, date, net, amount: Math.round(net * RATE), status: 'pending', availableOn: addDays(date, HOLD_DAYS), payoutId: null, kind: 'commission' });
    }
    c.nextBill = addMonths(date, c.cycle === 'annual' ? 12 : 1);
    if (!quiet && c.partnerId) log(s, c.partnerId, date, fail ? `${c.biz} payment of ${M(inv.total)} failed — no commission until collected` : `${c.biz} paid ${M(inv.total)} — commission ${M(Math.round(net * RATE))} pending`);
    return inv;
  }

  function refundInvoice(s, inv, date, quiet) {
    inv.status = 'refunded'; inv.refunded = date;
    const cm = s.commissions.find((x) => x.invoiceId === inv.id && x.kind === 'commission');
    const c = s.clients.find((x) => x.id === inv.clientId);
    if (!cm) return;
    if (cm.status === 'pending' || cm.status === 'available') { cm.status = 'reversed'; if (!quiet) log(s, cm.partnerId, date, `${c.biz} refunded — commission ${M(cm.amount)} reversed`); }
    else if (cm.status === 'paid') {
      s.commissions.push({ id: nid('CM-'), partnerId: cm.partnerId, clientId: cm.clientId, invoiceId: inv.id, date, net: -inv.net, amount: -cm.amount, status: 'available', availableOn: date, payoutId: null, kind: 'clawback' });
      if (!quiet) log(s, cm.partnerId, date, `${c.biz} refunded after payout — ${M(-cm.amount)} adjustment deducted from your next payout`);
    }
  }

  function settle(s) {
    s.commissions.forEach((cm) => { if (cm.status === 'pending' && cm.availableOn <= s.today) cm.status = 'available'; });
    s.payouts.forEach((po) => { if (po.status === 'in_transit' && po.arrival <= s.today) po.status = 'paid'; });
  }

  function availableFor(s, pid, asOf) {
    return s.commissions.filter((cm) => cm.partnerId === pid && !cm.payoutId && cm.status !== 'reversed' && (cm.status === 'available' || (cm.status === 'pending' && asOf && cm.availableOn <= asOf)));
  }

  function runPayout(s, p, date, quiet) {
    if (!p.stripe) return null;
    const items = availableFor(s, p.id, date);
    const amt = items.reduce((t, x) => t + x.amount, 0);
    if (amt < MIN_PAYOUT) return null;
    const po = { id: nid('PO-'), partnerId: p.id, date, amount: amt, tr: 'tr_' + rid('', 16), po: 'po_' + rid('', 16), status: 'in_transit', arrival: addDays(date, 2), count: items.length, dest: p.stripe.bank };
    items.forEach((x) => { x.status = 'paid'; x.payoutId = po.id; });
    s.payouts.push(po);
    if (!quiet) log(s, p.id, date, `Payout of ${M(amt)} sent to Stripe (${po.tr.slice(0, 14)}…)`);
    return po;
  }

  function advanceMonth() {
    const target = addMonths(S.today, 1);
    let d = S.today;
    while (d < target) {
      d = addDays(d, 1);
      S.today = d;
      S.clients.forEach((c) => {
        if (c.status === 'cancelled') return;
        if (c.nextBill <= d) {
          if (c.status === 'past_due') {
            const failed = S.invoices.filter((i) => i.clientId === c.id && i.status === 'failed').pop();
            if (failed) { failed.status = 'paid'; failed.recovered = d; S.commissions.push({ id: nid('CM-'), partnerId: c.partnerId, clientId: c.id, invoiceId: failed.id, date: d, net: failed.net, amount: Math.round(failed.net * RATE), status: 'pending', availableOn: addDays(d, HOLD_DAYS), payoutId: null, kind: 'commission' }); log(S, c.partnerId, d, `${c.biz} overdue payment collected on retry — commission ${M(Math.round(failed.net * RATE))} pending`); }
            c.status = 'active';
          }
          const fail = c.failNext; c.failNext = false;
          billOnce(S, c, d, fail, false);
          if (fail) c.status = 'past_due';
        }
      });
      settle(S);
      if (D(d).getUTCDate() === PAYOUT_DAY) S.partners.forEach((p) => { if (p.stripe && p.stripe.schedule === 'monthly') runPayout(S, p, d, false); });
    }
    save();
  }

  function log(s, pid, date, text) { s.activity.push({ partnerId: pid, date, text }); }

  function me() { return S.partners.find((p) => p.id === S.session); }
  function stats(p) {
    const cl = S.clients.filter((c) => c.partnerId === p.id);
    const active = cl.filter((c) => c.status === 'active' || c.status === 'past_due');
    const mrr = cl.filter((c) => c.status === 'active').reduce((t, c) => t + monthlyEq(c), 0);
    const cms = S.commissions.filter((x) => x.partnerId === p.id && x.status !== 'reversed');
    const sum = (f) => cms.filter(f).reduce((t, x) => t + x.amount, 0);
    return {
      clients: cl, active, mrr, monthlyComm: Math.round(mrr * RATE),
      pending: sum((x) => x.status === 'pending'),
      available: sum((x) => x.status === 'available' && !x.payoutId),
      paid: S.payouts.filter((x) => x.partnerId === p.id).reduce((t, x) => t + x.amount, 0),
      lifetime: sum((x) => x.status !== 'reversed'),
      inTransit: S.payouts.filter((x) => x.partnerId === p.id && x.status === 'in_transit').reduce((t, x) => t + x.amount, 0),
    };
  }
  function nextPayoutDate() { const d = D(S.today); let m = d.getUTCMonth(), y = d.getUTCFullYear(); if (d.getUTCDate() >= PAYOUT_DAY) { m++; if (m > 11) { m = 0; y++; } } return iso(new Date(Date.UTC(y, m, PAYOUT_DAY))); }
  const refLink = (p) => `${SITE}/subscribe?ref=${p.code}`;

  function save() { S.seq = seq; store.set(S); }
  function load() { const v = store.get(); S = v && v.partners ? v : seed(); if (!v) save(); seq = Math.max(seq, S.seq || 0, 2000); }

  const app = $('#app');
  const TAB_SLUGS = new Set(['clients', 'commissions', 'payouts', 'share', 'settings']);

  function canonicalPath() {
    return location.pathname.replace(/\/+$/, '') || '/';
  }

  function pathFor(route) {
    if (route === 'signup' || route === 'signin' || route === 'checkout') return `/partnership/${route}`;
    if (route === 'portal') return UI.tab && UI.tab !== 'overview' ? `/partnership/portal/${UI.tab}` : '/partnership/portal';
    return '/partnership';
  }

  function readLocation() {
    const parts = canonicalPath().split('/').filter(Boolean);
    const view = parts[0] === 'partnership' ? parts[1] : '';
    if (view === 'signup' || view === 'signin' || view === 'checkout') { UI.route = view; return; }
    if (view === 'portal') {
      UI.route = 'portal';
      UI.tab = TAB_SLUGS.has(parts[2]) ? parts[2] : 'overview';
      return;
    }
    UI.route = 'home';
  }

  function syncUrl(replace) {
    const next = pathFor(UI.route);
    if (canonicalPath() === next) return;
    history[replace ? 'replaceState' : 'pushState']({ route: UI.route, tab: UI.tab }, '', next);
  }

  function go(route, opts = {}) {
    if (route === 'portal' && !S.session) route = 'signin';
    UI.route = route; Object.assign(UI, opts); UI.errors = {};
    if (route === 'checkout' && opts.ref === undefined && !UI.co.ref) { const p = me() || S.partners[0]; UI.co.ref = p ? p.code : null; }
    syncUrl(false);
    render(); window.scrollTo(0, 0);
  }
  function render() {
    document.querySelectorAll('#proto-switch button').forEach((b) => b.classList.toggle('on', b.dataset.go === (['signin', 'signup'].includes(UI.route) ? 'portal' : UI.route)));
    const v = { home: vHome, signup: vSignup, signin: vSignin, portal: vPortal, checkout: vCheckout }[UI.route] || vHome;
    app.innerHTML = v();
    afterRender();
  }

  function brandLink() {
    return `<a href="/" class="brand"><img src="/ledgerlink-logo.png" alt=""><span>Quantum Ledger Line</span></a>`;
  }

  function siteHead(minimal) {
    return `<header class="site-head"><div class="in">
      ${brandLink()}
      ${minimal ? '' : `<nav class="site-nav"><a href="#program" data-jump="program">Program</a><a href="#clients" data-jump="clients">For your clients</a><a href="#earn" data-jump="earn">Earnings</a><a href="#how" data-jump="how">How it works</a></nav>`}
      <div class="actions">${S.session ? `<button class="btn sm" data-go="portal">Open partner portal</button>` : `<button class="btn quiet sm" data-go="signin">Sign in</button><button class="btn sm" data-go="signup">Become a partner</button>`}</div>
    </div></header>`;
  }

  function vHome() {
    const rows = [10, 25, 50, 100].map((n) => `<tr><td>${n}</td><td class="num">${M(n * 15000 * RATE, { whole: true })}</td><td class="num">${M(n * 15000 * RATE * 12, { whole: true })}</td></tr>`).join('');
    return `${siteHead()}
    <main>
      <section class="hero wrap">
        <div class="eyebrow">LedgerLine Lifetime Partnership Program</div>
        <h1>Your clients grow.<br>Your revenue grows.</h1>
        <p class="lede">For accountants, bookkeepers, virtual CFOs and finance advisors. Bring LedgerLine to your clients and earn 20% recurring commission for as long as they stay.</p>
        <div class="ctas"><button class="btn lg" data-go="signup">Become a founding partner</button><button class="btn ghost lg" data-jump="earn">See what you could earn</button></div>
      </section>

      <section class="band" id="program"><div class="wrap sec">
        <div class="big-stat">
          <div class="n">20%</div>
          <div>
            <h2>Lifetime recurring commission.</h2>
            <p>Refer a client and earn 20% of eligible net subscription revenue collected, for as long as that client remains an active, paying customer.</p>
            <ul class="checks"><li>No one-time referral fee</li><li>No 12-month limit</li><li>Paid monthly to your Stripe account</li></ul>
          </div>
        </div>
      </div></section>

      <section id="clients"><div class="wrap sec">
        <div class="sec-head"><h2>What your clients get.</h2><p>An AI-powered bookkeeping and finance automation platform that works alongside their existing accounting systems.</p></div>
        <div class="grid3">
          <div><h3>Automated Bookkeeping</h3><p>From invoice capture to GL coding and ERP-ready posting.</p></div>
          <div><h3>Invoice-to-Pay</h3><p>Invoice validation, approvals, matching and payment workflows.</p></div>
          <div><h3>Expense Management</h3><p>Automated employee expenses, claims and approvals.</p></div>
          <div><h3>Bank Intelligence</h3><p>AI-assisted transaction categorisation, reconciliation and financial reporting.</p></div>
          <div><h3>Intelligent Record Management</h3><p>Organised, searchable and audit-ready financial records.</p></div>
          <div><h3>Human Oversight</h3><p>AI handles repetitive processing. Finance professionals review exceptions and stay in control.</p></div>
        </div>
      </div></section>

      <section class="band"><div class="wrap sec">
        <div class="sec-head"><h2>What your firm gets.</h2><p>You bring the relationship. We bring the technology. We grow together.</p></div>
        <div class="list-num">
          <div class="i"><div class="k">01</div><h3>Lifetime recurring revenue</h3><p>20% of eligible net subscription revenue from every approved referred client.</p></div>
          <div class="i"><div class="k">02</div><h3>More value for clients</h3><p>Less manual processing, stronger controls, more time running the business.</p></div>
          <div class="i"><div class="k">03</div><h3>No system replacement</h3><p>Works alongside existing accounting and ERP systems, subject to supported integrations.</p></div>
          <div class="i"><div class="k">04</div><h3>Demos and onboarding</h3><p>Our team demonstrates, onboards and supports your referred clients.</p></div>
          <div class="i"><div class="k">05</div><h3>Long-term growth</h3><p>As your clients grow, your recurring commission grows with them.</p></div>
        </div>
      </div></section>

      <section id="earn"><div class="wrap sec">
        <div class="sec-head"><h2>What could you earn?</h2><p>Move the sliders to model your own client base.</p></div>
        <div class="earn">
          <div class="panel panel-pad calc">
            <div class="row"><label>Active referred clients <span class="val" id="c-n-v">25</span></label><input type="range" id="c-n" min="1" max="200" value="25" aria-label="Active referred clients"></div>
            <div class="row"><label>Average monthly subscription <span class="val" id="c-p-v">US$150</span></label><input type="range" id="c-p" min="50" max="500" step="10" value="150" aria-label="Average monthly subscription"></div>
            <div class="out"><div><div class="l">Monthly commission</div><div class="v" id="c-m">US$750</div></div><div><div class="l">Annualised commission</div><div class="v" id="c-a">US$9,000</div></div></div>
            <p class="fine">20% of net subscription revenue, excluding taxes. Illustrative only.</p>
          </div>
          <div class="panel" style="overflow:hidden">
            <div class="tbl-wrap"><table class="t"><thead><tr><th>Active referred clients</th><th class="num">Monthly commission</th><th class="num">Annualised commission</th></tr></thead><tbody>${rows}</tbody></table></div>
            <p class="fine" style="padding:0 14px 14px">Assumes a US$150 monthly subscription and 20% commission, with all customers active and paying throughout the year, and no refunds or subscription changes.</p>
          </div>
        </div>
      </div></section>

      <section class="band" id="how"><div class="wrap sec">
        <div class="sec-head"><h2>How the partnership works.</h2></div>
        <div class="steps">
          <div class="s"><div class="dot">1</div><h3>Join LedgerLine</h3><p>Create your partner account and accept the partnership terms. Your referral link is ready straight away.</p></div>
          <div class="s"><div class="dot">2</div><h3>Introduce your clients</h3><p>Share your link or invite clients by email. They subscribe online in a few minutes.</p></div>
          <div class="s"><div class="dot">3</div><h3>We demonstrate and onboard</h3><p>Our team supports demonstrations, implementation and customer onboarding.</p></div>
          <div class="s"><div class="dot">4</div><h3>Earn recurring commission</h3><p>20% of eligible net revenue actually collected, paid monthly to your connected Stripe account.</p></div>
        </div>
        <p class="fine" style="margin-top:36px">Commissions are subject to the partner agreement, including referral eligibility, payment terms, exclusions and applicable professional disclosure requirements. <a href="#" data-act="terms">Read the key terms</a>.</p>
      </div></section>

      <section class="cta-final wrap">
        <h2>Become a founding<br>LedgerLine partner.</h2>
        <p>The future of accounting is not more manual work. It is better technology, stronger controls and more valuable client relationships.</p>
        <button class="btn lg" data-go="signup">Create your partner account</button>
      </section>
    </main>
    <footer class="site-foot"><div class="wrap in"><span><b style="color:var(--text)">LedgerLine</b> | High Volt Analytics · Built for Accountants. Powered by AI. Growing Together.</span><a href="${SITE}/" target="_blank" rel="noopener">quantumledgerline.com</a></div></footer>`;
  }

  function vSignup() {
    const d = UI.draft, e = UI.errors, st = UI.signupStep;
    const f = (id, label, type = 'text', ph = '', hint = '', ac = '') => `<div class="field"><label for="${id}">${label}</label><input class="in-t ${e[id] ? 'err' : ''}" id="${id}" type="${type}" placeholder="${esc(ph)}" value="${esc(d[id] || '')}" ${ac ? `autocomplete="${ac}"` : ''}>${e[id] ? `<div class="err-msg">${e[id]}</div>` : hint ? `<div class="hint">${hint}</div>` : ''}</div>`;
    const body = st === 1 ? `
      <h1>Create your partner account</h1><p class="sub">Free to join. Your referral link is ready as soon as you finish.</p>
      <div class="stepper"><span class="on"></span><span></span></div>
      ${f('name', 'Your name', 'text', 'Sarah Chen', '', 'name')}
      ${f('email', 'Work email', 'email', 'you@yourfirm.com.au', '', 'email')}
      ${f('pw', 'Password', 'password', 'At least 8 characters', '', 'new-password')}
      <button class="btn block lg" data-act="su-next">Continue</button>
      <div class="auth-alt">Already a partner? <a href="#" data-go="signin">Sign in</a></div>`
      : `
      <h1>About your practice</h1><p class="sub">This appears to your clients when they subscribe through your link.</p>
      <div class="stepper"><span class="on"></span><span class="on"></span></div>
      ${f('firm', 'Firm or trading name', 'text', 'Elm & Co Advisory', '', 'organization')}
      <div class="row2">
        <div class="field"><label for="type">Partner type</label><select class="sel" id="type">${PTYPES.map((t) => `<option ${d.type === t ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
        <div class="field"><label for="country">Country</label><select class="sel" id="country">${COUNTRIES.map(([k, n]) => `<option value="${k}" ${(d.country || 'AU') === k ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
      </div>
      ${f('abn', 'ABN or business number', 'text', '51 824 753 556', 'Optional. Used on your commission statements.')}
      <label class="chk"><input type="checkbox" id="agree" ${d.agree ? 'checked' : ''}><span>I accept the <a href="#" data-act="terms">LedgerLine partner terms</a>.</span></label>
      <label class="chk"><input type="checkbox" id="disclose" ${d.disclose ? 'checked' : ''}><span>I will disclose my referral commission to clients as required by my professional obligations.</span></label>
      ${e.agree ? `<div class="err-msg" style="margin-bottom:10px">${e.agree}</div>` : ''}
      <div style="display:flex;gap:10px;margin-top:8px"><button class="btn ghost lg" data-act="su-back">Back</button><button class="btn lg" style="flex:1" data-act="su-create">Create account</button></div>`;
    return `<div class="auth">${siteHead(true)}<div class="auth-main"><div class="auth-card">${body}</div></div></div>`;
  }

  function vSignin() {
    const e = UI.errors;
    return `<div class="auth">${siteHead(true)}<div class="auth-main"><div class="auth-card">
      <h1>Partner sign in</h1><p class="sub">Manage referrals, commissions and payouts.</p>
      <div class="field"><label for="si-email">Email</label><input class="in-t ${e.si ? 'err' : ''}" id="si-email" type="email" autocomplete="email"></div>
      <div class="field"><label for="si-pw">Password</label><input class="in-t ${e.si ? 'err' : ''}" id="si-pw" type="password" autocomplete="current-password">${e.si ? `<div class="err-msg">${e.si}</div>` : ''}</div>
      <button class="btn block lg" data-act="signin">Sign in</button>
      <div class="divider">or</div>
      <button class="btn ghost block" data-act="demo-login">Explore the sample partner account</button>
      <p class="hint xs muted" style="margin-top:8px;text-align:center">Elm & Co Advisory · 12 referred clients and six months of history</p>
      <div class="auth-alt">New to LedgerLine? <a href="#" data-go="signup">Become a partner</a></div>
    </div></div></div>`;
  }

  const TABS = [['overview', 'Overview'], ['clients', 'Clients'], ['commissions', 'Commissions'], ['payouts', 'Payouts'], ['share', 'Share & invite'], ['settings', 'Settings']];
  function vPortal() {
    const p = me();
    const st = stats(p);
    const nav = TABS.map(([k, l]) => `<button class="${UI.tab === k ? 'on' : ''}" data-tab="${k}">${l}${k === 'payouts' && !p.stripe ? '<span class="pill warn" style="padding:0 7px">Set up</span>' : ''}</button>`).join('');
    const view = { overview: tOverview, clients: tClients, commissions: tCommissions, payouts: tPayouts, share: tShare, settings: tSettings }[UI.tab](p, st);
    return `<div class="portal">
      <aside class="side">${brandLink()}<nav>${nav}</nav>
        <div class="who"><b>${esc(p.firm)}</b><span class="muted">${esc(p.name)}</span><br><button class="btn quiet sm" style="padding-left:0" data-act="signout">Sign out</button></div></aside>
      <div><div class="mobile-nav">${TABS.map(([k, l]) => `<button class="${UI.tab === k ? 'on' : ''}" data-tab="${k}">${l}</button>`).join('')}</div>
      <main class="main">${view}</main></div>
    </div>
    <button class="btn ghost demo-fab" data-act="demo-toggle" aria-expanded="${UI.demoOpen}">Demo controls</button>
    <div class="demo-pop ${UI.demoOpen ? 'open' : ''}" id="demo-pop">${demoPanel(p)}</div>`;
  }

  function demoPanel(p) {
    const cl = S.clients.filter((c) => c.partnerId === p.id && c.status !== 'cancelled');
    const opts = cl.map((c) => `<option value="${c.id}">${esc(c.biz)}</option>`).join('');
    return `<h3>Demo controls</h3><p class="d">Simulated date: <b>${fd(S.today)}</b>. Move time forward to bill clients, release held commission and run payouts.</p>
      <button class="btn" data-act="advance">Advance one month →</button>
      <button class="btn ghost" data-act="open-checkout">Subscribe a new client via my link</button>
      ${cl.length ? `<div style="border-top:1px solid var(--line);margin:10px 0;padding-top:10px"><select class="sel" id="demo-client" aria-label="Client">${opts}</select>
      <button class="btn ghost sm" data-act="demo-fail">Next payment fails</button>
      <button class="btn ghost sm" data-act="demo-refund">Refund latest payment</button>
      <button class="btn ghost sm" data-act="demo-cancel">Cancel subscription</button></div>` : ''}`;
  }

  function kpis(st) {
    return `<div class="kpis">
      <div><div class="l">Active referred clients</div><div class="v">${st.active.length}</div><div class="s">${st.clients.length} referred in total</div></div>
      <div><div class="l">Client subscriptions</div><div class="v">${M(st.mrr, { whole: true })}</div><div class="s">net monthly, excl. tax</div></div>
      <div><div class="l">Your monthly commission</div><div class="v">${M(st.monthlyComm)}</div><div class="s">20% of collected net revenue</div></div>
      <div><div class="l">Available to pay out</div><div class="v" style="color:${st.available > 0 ? 'var(--ok)' : 'inherit'}">${M(st.available)}</div><div class="s">${M(st.pending)} held in 30-day window</div></div>
      <div><div class="l">Lifetime earned</div><div class="v">${M(st.lifetime)}</div><div class="s">${M(st.paid)} paid out</div></div>
    </div>`;
  }

  function linkBox(p) {
    return `<div class="link-box"><input class="in-t" id="ref-link" readonly value="${esc(refLink(p))}" aria-label="Your referral link"><button class="btn sm" data-act="copy-link">Copy link</button><button class="btn ghost sm" data-act="open-checkout">Preview client page</button></div>`;
  }

  function tOverview(p, st) {
    const first = S.clients.some((c) => c.partnerId === p.id);
    const steps = [
      [true, 'Partner account created', fd(p.created), ''],
      [!!p.shared || first, 'Share your referral link with a client', '', `<button class="btn ghost sm act" data-act="copy-link">Copy link</button>`],
      [first, 'First client subscribes', '', `<button class="btn ghost sm act" data-act="open-checkout">Try it</button>`],
      [!!p.stripe, 'Connect Stripe to receive payouts', '', `<button class="btn stripe sm act" data-act="stripe-connect">Connect Stripe</button>`],
    ];
    const allDone = steps.every((s) => s[0]);
    const acts = S.activity.filter((a) => a.partnerId === p.id).slice().sort((a, b) => b.date.localeCompare(a.date)).slice(0, 8);
    const firstName = p.name.split(' ')[0];
    return `<div class="page-head"><div><h1>Welcome, ${esc(firstName)}</h1><p>${esc(p.firm)} · Partner code <span class="code-chip">${p.code}</span>${p.founding ? ' · Founding partner' : ''}</p></div>
      <button class="btn" data-act="invite">Invite a client</button></div>
      ${kpis(st)}
      <div class="card"><div class="card-head"><h2>Your referral link</h2><span class="small muted">Clients who subscribe through this link are attributed to you for life</span></div><div class="card-body">${linkBox(p)}</div></div>
      <div class="two">
        ${allDone ? `<div class="card"><div class="card-head"><h2>Recent activity</h2></div><ul class="feed">${acts.map((a) => `<li><span class="d">${fds(a.date)}</span><span>${esc(a.text)}</span></li>`).join('') || '<li class="muted">No activity yet</li>'}</ul></div>`
        : `<div class="card"><div class="card-head"><h2>Get set up</h2><span class="small muted">${steps.filter((s) => s[0]).length} of 4 done</span></div><div class="card-body" style="padding-top:4px;padding-bottom:4px"><ul class="checklist">${steps.map(([ok, t, sub, a]) => `<li class="${ok ? 'done' : ''}"><span class="ic">${ok ? '✓' : ''}</span><span class="tx">${t}${sub ? `<br><span class="xs muted">${sub}</span>` : ''}</span>${ok ? '' : a}</li>`).join('')}</ul></div></div>`}
        <div class="card"><div class="card-head"><h2>Next payout</h2>${p.stripe ? '<span class="pill ok">Stripe connected</span>' : '<span class="pill warn">Stripe not connected</span>'}</div><div class="card-body">
          <div style="font-size:28px;font-weight:700;letter-spacing:-0.02em">${M(st.available)}</div>
          <p class="small muted" style="margin-top:4px">${p.stripe ? (p.stripe.schedule === 'monthly' ? `Scheduled for ${fd(nextPayoutDate())} if at least ${M(MIN_PAYOUT, { whole: true })} is available` : 'Manual payouts — request when ready') : 'Connect Stripe to start receiving payouts'}</p>
          <p class="small muted" style="margin-top:12px">${M(st.pending)} is in the 30-day refund window and will become available automatically.</p>
          <div style="margin-top:16px"><button class="btn ghost sm" data-tab="payouts">View payouts</button></div>
        </div></div>
      </div>`;
  }

  function statusPill(c) {
    return { active: '<span class="pill ok">Active</span>', past_due: '<span class="pill warn">Payment failed</span>', cancelled: '<span class="pill neutral">Cancelled</span>' }[c.status];
  }

  function tClients(p, st) {
    const f = UI.cfilter;
    const list = st.clients.filter((c) => f === 'all' || (f === 'active' ? c.status === 'active' : f === 'attention' ? c.status === 'past_due' : c.status === 'cancelled')).slice().sort((a, b) => b.start.localeCompare(a.start));
    const earned = (c) => S.commissions.filter((x) => x.clientId === c.id && x.status !== 'reversed').reduce((t, x) => t + x.amount, 0);
    const inv = S.invites.filter((i) => i.partnerId === p.id);
    const cnt = (k) => st.clients.filter((c) => k === 'active' ? c.status === 'active' : k === 'attention' ? c.status === 'past_due' : c.status === 'cancelled').length;
    return `<div class="page-head"><div><h1>Clients</h1><p>Businesses that subscribed through your link or invitation.</p></div><button class="btn" data-act="invite">Invite a client</button></div>
      <div class="card"><div class="card-head"><div class="seg" role="tablist">${[['all', `All ${st.clients.length}`], ['active', `Active ${cnt('active')}`], ['attention', `Payment failed ${cnt('attention')}`], ['cancelled', `Cancelled ${cnt('cancelled')}`]].map(([k, l]) => `<button class="${f === k ? 'on' : ''}" data-cf="${k}">${l}</button>`).join('')}</div><span class="small muted">Commission is earned only on payments actually collected</span></div>
      ${list.length ? `<div class="tbl-wrap"><table class="t"><thead><tr><th>Business</th><th>Plan</th><th>Status</th><th class="num">Net / month</th><th class="num">Your 20%</th><th class="num">Earned to date</th><th>Subscribed</th><th>Next billing</th><th>Source</th></tr></thead><tbody>
        ${list.map((c) => `<tr><td><b style="font-weight:500">${esc(c.biz)}</b><div class="xs muted">${esc(c.contact)} · ${c.country}</div></td><td>${PLANS[c.plan].name}${c.cycle === 'annual' ? ' <span class="xs muted">annual</span>' : ''}</td><td>${statusPill(c)}</td><td class="num">${M(monthlyEq(c))}</td><td class="num">${c.status === 'cancelled' ? '<span class="muted">—</span>' : M(Math.round(monthlyEq(c) * RATE))}</td><td class="num">${M(earned(c))}</td><td>${fd(c.start)}</td><td>${c.status === 'cancelled' ? `<span class="muted">Ended ${fds(c.cancelled)}</span>` : fd(c.nextBill)}</td><td><span class="xs muted">${c.source === 'invite' ? 'Email invite' : 'Referral link'}</span></td></tr>`).join('')}
      </tbody></table></div>` : `<div class="empty"><b>${st.clients.length ? 'No clients in this view' : 'No referred clients yet'}</b>Share your referral link — new subscriptions appear here automatically.<div style="margin-top:14px"><button class="btn sm" data-act="copy-link">Copy referral link</button></div></div>`}</div>
      <div class="card"><div class="card-head"><h2>Invitations</h2><span class="small muted">${inv.length} sent</span></div>
      ${inv.length ? `<div class="tbl-wrap"><table class="t"><thead><tr><th>Business</th><th>Email</th><th>Sent</th><th>Status</th><th></th></tr></thead><tbody>${inv.slice().reverse().map((i) => `<tr><td>${esc(i.biz)}</td><td class="muted">${esc(i.email)}</td><td>${fd(i.date)}</td><td>${{ sent: '<span class="pill neutral">Sent</span>', opened: '<span class="pill info">Opened</span>', subscribed: '<span class="pill ok">Subscribed</span>' }[i.status]}</td><td class="num">${i.status !== 'subscribed' ? `<button class="btn quiet sm" data-invco="${i.id}">Open as client</button>` : ''}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">No invitations sent yet.</div>'}</div>`;
  }

  function tCommissions(p, st) {
    const list = S.commissions.filter((x) => x.partnerId === p.id).slice().sort((a, b) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id));
    const pill = (x) => x.kind === 'clawback' ? (x.payoutId ? '<span class="pill neutral">Deducted</span>' : '<span class="pill bad">Adjustment</span>') : { pending: '<span class="pill warn">Pending</span>', available: '<span class="pill ok">Available</span>', paid: '<span class="pill neutral">Paid</span>', reversed: '<span class="pill bad">Reversed</span>' }[x.status];
    const cn = (id) => (S.clients.find((c) => c.id === id) || {}).biz || '—';
    const invn = (id) => (S.invoices.find((i) => i.id === id) || {}).num || '';
    return `<div class="page-head"><div><h1>Commissions</h1><p>One line for every client payment collected. 20% of net revenue, excluding tax.</p></div><button class="btn ghost" data-act="export">Download CSV</button></div>
      <div class="card"><div class="balance"><div><div class="l">Pending · 30-day refund window</div><div class="v" style="color:var(--warn)">${M(st.pending)}</div></div><div><div class="l">Available for payout</div><div class="v" style="color:var(--ok)">${M(st.available)}</div></div><div><div class="l">Paid out to date</div><div class="v">${M(st.paid)}</div></div></div></div>
      <div class="card"><div class="card-head"><h2>Commission ledger</h2><span class="small muted">${list.length} entries</span></div>
      ${list.length ? `<div class="tbl-wrap"><table class="t"><thead><tr><th>Date</th><th>Client</th><th>Invoice</th><th class="num">Net collected</th><th class="num">Rate</th><th class="num">Commission</th><th>Status</th><th>Available from</th></tr></thead><tbody>
      ${list.map((x) => `<tr><td>${fd(x.date)}</td><td>${esc(cn(x.clientId))}</td><td class="mono">${invn(x.invoiceId)}${x.kind === 'clawback' ? ' <span class="xs muted">refund</span>' : ''}</td><td class="num">${M(x.net)}</td><td class="num">20%</td><td class="num" style="${x.status === 'reversed' ? 'text-decoration:line-through;color:var(--faint)' : ''}">${M(x.amount)}</td><td>${pill(x)}</td><td>${x.status === 'pending' ? fd(x.availableOn) : x.payoutId ? `<span class="xs muted">${x.payoutId}</span>` : '—'}</td></tr>`).join('')}
      </tbody></table></div>` : '<div class="empty"><b>No commission yet</b>Commission appears here when a referred client\u2019s payment is collected.</div>'}</div>
      <div class="note"><b>How commission is calculated.</b> 20% of the net subscription amount actually collected — excluding GST/VAT, refunds, chargebacks, discounts and credits. Each amount is held for 30 days, then becomes available. Refunds inside the window reverse the commission; refunds after a payout are deducted from the next one. Failed payments earn nothing until they are collected.</div>`;
  }

  function tPayouts(p, st) {
    const pos = S.payouts.filter((x) => x.partnerId === p.id).slice().sort((a, b) => b.date.localeCompare(a.date));
    const stripeCard = p.stripe ? `<div class="card"><div class="card-head"><div class="stripe-row"><span class="stripe-logo">stripe</span><span class="pill ok">Connected</span></div><button class="btn ghost sm" data-act="stripe-manage">Manage</button></div><div class="card-body"><dl class="kv">
        <dt>Connected account</dt><dd class="mono">${p.stripe.acct}</dd><dt>Account holder</dt><dd>${esc(p.stripe.holder)}</dd><dt>Payout destination</dt><dd>${esc(p.stripe.bank)}</dd>
        <dt>Schedule</dt><dd><div class="seg"><button class="${p.stripe.schedule === 'monthly' ? 'on' : ''}" data-sched="monthly">Monthly on the 15th</button><button class="${p.stripe.schedule === 'manual' ? 'on' : ''}" data-sched="manual">Manual</button></div></dd></dl></div></div>`
      : `<div class="card"><div class="card-body" style="display:flex;gap:20px;align-items:center;flex-wrap:wrap"><span class="stripe-logo" style="font-size:24px">stripe</span><div style="flex:1;min-width:240px"><b>Connect Stripe to receive your commission</b><p class="small muted" style="margin-top:2px">LedgerLine uses Stripe Connect to transfer commission to your bank account. Setup takes about five minutes. Your commission keeps accruing in the meantime.</p></div><button class="btn stripe" data-act="stripe-connect">Connect with Stripe</button></div></div>`;
    const canPay = p.stripe && st.available >= MIN_PAYOUT;
    return `<div class="page-head"><div><h1>Payouts</h1><p>Commission transferred from LedgerLine to your Stripe account.</p></div></div>
      ${stripeCard}
      <div class="card"><div class="balance"><div><div class="l">Available now</div><div class="v" style="color:var(--ok)">${M(st.available)}</div></div><div><div class="l">In transit to your bank</div><div class="v">${M(st.inTransit)}</div></div><div><div class="l">${p.stripe && p.stripe.schedule === 'monthly' ? 'Next scheduled payout' : 'Minimum payout'}</div><div class="v" style="font-size:20px;padding-top:6px">${p.stripe && p.stripe.schedule === 'monthly' ? fd(nextPayoutDate()) : M(MIN_PAYOUT, { whole: true })}</div></div></div>
        <div class="card-body" style="border-top:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap"><span class="small muted">${!p.stripe ? 'Connect Stripe to pay out.' : st.available < MIN_PAYOUT ? `At least ${M(MIN_PAYOUT, { whole: true })} must be available to request a payout.` : 'Transfer your available balance now instead of waiting for the schedule.'}</span><button class="btn" data-act="payout" ${canPay ? '' : 'disabled'}>Pay out ${M(st.available)} now</button></div></div>
      <div class="card"><div class="card-head"><h2>Payout history</h2><span class="small muted">${pos.length} payouts</span></div>
      ${pos.length ? `<div class="tbl-wrap"><table class="t"><thead><tr><th>Date</th><th>Payout</th><th>Stripe transfer</th><th class="num">Commission lines</th><th class="num">Amount</th><th>Status</th><th>Arrival</th></tr></thead><tbody>
        ${pos.map((x) => `<tr><td>${fd(x.date)}</td><td class="mono">${x.id}</td><td class="mono xs">${x.tr}</td><td class="num">${x.count}</td><td class="num"><b style="font-weight:600">${M(x.amount)}</b></td><td>${x.status === 'paid' ? '<span class="pill ok">Paid</span>' : '<span class="pill info">In transit</span>'}</td><td>${fd(x.arrival)}</td></tr>`).join('')}
      </tbody></table></div>` : '<div class="empty"><b>No payouts yet</b>Your first payout is sent once at least US$50 of commission is available.</div>'}</div>`;
  }

  function emailTemplate(p) {
    return `Hi {first name},\n\nWe've started recommending LedgerLine to clients who want to spend less time on bookkeeping. It automates invoice capture, expenses, bank categorisation and reconciliation, while we still review the exceptions.\n\nYou can see the plans and subscribe here:\n${refLink(p)}\n\nDisclosure: ${p.firm} is a LedgerLine partner and receives a commission on subscriptions made through this link.\n\nHappy to walk you through it.\n\n${p.name}\n${p.firm}`;
  }

  function tShare(p) {
    return `<div class="page-head"><div><h1>Share & invite</h1><p>Everything you need to introduce LedgerLine to your clients.</p></div></div>
      <div class="card"><div class="card-head"><h2>Referral link</h2><span class="small muted">Attribution lasts 90 days from the first click</span></div><div class="card-body">${linkBox(p)}
        <p class="small muted" style="margin-top:12px">Your code <span class="code-chip">${p.code}</span> can also be entered at checkout.</p></div></div>
      <div class="two">
        <div class="card"><div class="card-head"><h2>Email template</h2><button class="btn ghost sm" data-act="copy-email">Copy</button></div><div class="card-body"><textarea class="in-t" id="email-tpl" rows="15" style="font-size:13.5px;line-height:1.5;resize:vertical">${esc(emailTemplate(p))}</textarea></div></div>
        <div class="stack">
          <div class="card" style="margin:0"><div class="card-head"><h2>Invite by email</h2></div><div class="card-body"><p class="small muted" style="margin-bottom:14px">We send your client a personal invitation with your link and disclosure. You can track it under Clients.</p><button class="btn" data-act="invite">Invite a client</button></div></div>
          <div class="card" style="margin:0"><div class="card-head"><h2>What clients see</h2></div><div class="card-body"><p class="small muted" style="margin-bottom:14px">A short checkout page with your firm's name, the plans and a commission disclosure.</p><button class="btn ghost" data-act="open-checkout">Preview client page</button></div></div>
        </div>
      </div>`;
  }

  function tSettings(p) {
    return `<div class="page-head"><div><h1>Settings</h1><p>Your partner profile and agreement.</p></div></div>
      <div class="two">
        <div class="card"><div class="card-head"><h2>Partner profile</h2><button class="btn sm" data-act="save-profile">Save changes</button></div><div class="card-body">
          <div class="row2"><div class="field"><label for="s-firm">Firm name</label><input class="in-t" id="s-firm" value="${esc(p.firm)}"></div><div class="field"><label for="s-name">Contact name</label><input class="in-t" id="s-name" value="${esc(p.name)}"></div></div>
          <div class="row2"><div class="field"><label for="s-email">Email</label><input class="in-t" id="s-email" type="email" value="${esc(p.email)}"></div><div class="field"><label for="s-abn">ABN or business number</label><input class="in-t" id="s-abn" value="${esc(p.abn)}"></div></div>
          <div class="field"><label for="s-type">Partner type</label><select class="sel" id="s-type">${PTYPES.map((t) => `<option ${p.type === t ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
        </div></div>
        <div class="card"><div class="card-head"><h2>Partner agreement</h2><span class="pill ok">Accepted</span></div><div class="card-body"><dl class="kv">
          <dt>Status</dt><dd>${p.status === 'approved' ? 'Approved partner' : 'Pending'}${p.founding ? ' · Founding partner' : ''}</dd>
          <dt>Commission</dt><dd>20% lifetime recurring</dd><dt>Accepted on</dt><dd>${fd(p.created)}</dd><dt>Partner code</dt><dd><span class="code-chip">${p.code}</span></dd></dl>
          <div style="margin-top:16px"><button class="btn ghost sm" data-act="terms">View key terms</button></div></div></div>
      </div>`;
  }

  function vCheckout() {
    const co = UI.co;
    const p = S.partners.find((x) => x.code === co.ref);
    if (co.done) return vCheckoutDone(p);
    const plan = PLANS[co.plan];
    const country = co.country || 'AU';
    const net = cycleNet(co.plan, co.cycle);
    const tx = taxFor(country);
    const tax = tx ? Math.round(net * tx[1]) : 0;
    const e = UI.errors;
    const banner = p ? `<div class="ref-banner"><div class="av">${esc(initials(p.firm))}</div><div class="t"><b>Recommended by ${esc(p.firm)}</b><span>Your adviser has set you up with LedgerLine. They will stay involved in your books.</span></div></div>`
      : `<div class="ref-banner warn"><div class="t"><b>No partner attached</b><span>${co.ref ? `Referral code ${esc(co.ref)} was not recognised.` : 'You arrived without a referral link.'} You can still subscribe.</span></div></div>`;
    const planCards = Object.entries(PLANS).map(([k, x]) => `<button class="plan ${co.plan === k ? 'on' : ''}" data-plan="${k}" aria-pressed="${co.plan === k}">
      <div class="nm">${x.name}${x.popular ? '<span class="pill info" style="font-weight:500">Most popular</span>' : ''}</div>
      <div class="pr">${M(co.cycle === 'annual' ? Math.round(x.price * 10 / 12) : x.price, { whole: co.cycle !== 'annual' })}<small> / month</small></div>
      <div class="xs muted">${co.cycle === 'annual' ? `Billed ${M(x.price * 10, { whole: true })} yearly` : 'Billed monthly'} · excl. tax</div>
      <div class="ds" style="margin-top:10px">${x.desc}</div>
      <ul>${x.mods.map((m) => `<li>${m}</li>`).join('')}${x.off.map((m) => `<li class="off">${m}</li>`).join('')}</ul></button>`).join('');
    const f = (id, label, ph = '', type = 'text') => `<div class="field"><label for="${id}">${label}</label><input class="in-t ${e[id] ? 'err' : ''}" id="${id}" type="${type}" placeholder="${esc(ph)}" value="${esc(co[id] || '')}">${e[id] ? `<div class="err-msg">${e[id]}</div>` : ''}</div>`;
    const step1 = `<h1>Choose your plan</h1><p class="sub">AI does the processing. Your accountant stays in control.</p>
      <div class="seg" role="tablist"><button class="${co.cycle === 'monthly' ? 'on' : ''}" data-cycle="monthly">Monthly</button><button class="${co.cycle === 'annual' ? 'on' : ''}" data-cycle="annual">Annual · 2 months free</button></div>
      <div class="plans">${planCards}</div>
      <p class="fine">Sample pricing for this prototype, in US dollars.</p>
      <div style="margin-top:24px;display:flex;justify-content:flex-end"><button class="btn lg" data-act="co-next">Continue with ${plan.name}</button></div>`;
    const step2 = `<div class="co-grid"><div>
      <h1 style="font-size:26px">Your business</h1><p class="sub" style="font-size:14.5px">We use this to set up your LedgerLine workspace.</p>
      <div class="panel panel-pad">
        ${f('biz', 'Business name', 'Harbour & Vine Café Pty Ltd')}
        <div class="row2">${f('contact', 'Your name', 'Lena Morris')}${f('cemail', 'Email', 'lena@business.com.au', 'email')}</div>
        <div class="row2"><div class="field"><label for="ccountry">Country</label><select class="sel" id="ccountry">${COUNTRIES.map(([k, n]) => `<option value="${k}" ${country === k ? 'selected' : ''}>${n}</option>`).join('')}</select></div>${f('cabn', 'ABN or tax number', 'Optional')}</div>
        <div class="field" style="margin-top:6px"><label>Payment</label>
          <div class="pay-box"><input class="in-t mono" id="card" value="4242 4242 4242 4242" aria-label="Card number"><div class="split"><input class="in-t mono" id="exp" value="12 / 29" aria-label="Expiry"><input class="in-t mono" id="cvc" value="123" aria-label="CVC"></div></div>
          <div class="stripe-badge">Payments by <b>stripe</b> · Simulated test card — nothing is charged</div></div>
      </div>
      <button class="btn ghost" style="margin-top:16px" data-act="co-back">← Change plan</button>
    </div>
    <aside class="summary panel panel-pad">
      <div class="small muted">Order summary</div>
      <div style="font-weight:600;font-size:17px;margin:4px 0 14px">LedgerLine ${plan.name} · ${co.cycle === 'annual' ? 'Annual' : 'Monthly'}</div>
      <div class="sum-row"><span>Subscription</span><span class="num">${M(net)}</span></div>
      <div class="sum-row"><span>${tx ? `${tx[0]} (${Math.round(tx[1] * 100)}%)` : 'Tax'}</span><span class="num">${tx ? M(tax) : M(0)}</span></div>
      <div class="sum-row tot"><span>Due today</span><span class="num">${M(net + tax)}</span></div>
      <p class="xs muted" style="margin-top:6px">Renews ${co.cycle === 'annual' ? 'yearly' : 'monthly'}. Cancel any time.</p>
      <button class="btn block lg" style="margin-top:18px" data-act="co-pay">Subscribe and pay ${M(net + tax)}</button>
      ${p ? `<div class="disclose"><b style="color:var(--text)">Disclosure.</b> ${esc(p.firm)} is a LedgerLine partner and receives a commission on this subscription. Your price is the same either way.</div>` : ''}
    </aside></div>`;
    return `<div class="co"><header class="co-head"><div class="in">${brandLink()}<span class="small muted">quantumledgerline.com/subscribe${co.ref ? '?ref=' + esc(co.ref) : ''}</span><span class="secure">Secure checkout</span></div></header>
      <main class="co-main">${banner}${co.step === 1 ? step1 : step2}</main></div>`;
  }

  function vCheckoutDone(p) {
    const d = UI.co.done;
    return `<div class="co"><header class="co-head"><div class="in">${brandLink()}<span class="secure">Secure checkout</span></div></header>
      <main class="co-main"><div class="success panel panel-pad">
        <div class="tick">✓</div><h1 style="font-size:26px">Welcome to LedgerLine</h1>
        <p class="muted" style="margin-top:8px">${esc(d.biz)} is subscribed to ${PLANS[d.plan].name}. A receipt for ${M(d.total)} has been sent to ${esc(d.email)}.</p>
        <dl class="kv" style="text-align:left;margin:22px auto 0;max-width:380px"><dt>Subscription</dt><dd class="mono xs">${d.subId}</dd><dt>Invoice</dt><dd class="mono">${d.num}</dd>${p ? `<dt>Your adviser</dt><dd>${esc(p.firm)}</dd>` : ''}<dt>Next step</dt><dd>Our onboarding team will contact you within one business day.</dd></dl>
        <div style="margin-top:26px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
          ${p && S.session === p.id ? `<button class="btn" data-act="co-to-portal">See it in the partner portal</button>` : p ? `<button class="btn" data-act="co-to-portal">Sign in as ${esc(p.firm)}</button>` : ''}
          <button class="btn ghost" data-act="co-again">Subscribe another business</button></div>
        <p class="fine">Prototype: no workspace, email or payment is created.</p>
      </div></main></div>`;
  }

  function modal(html, cls = '') { const m = $('#modal'); m.className = 'modal ' + cls; m.innerHTML = html; $('#modal-wrap').classList.add('open'); $('#modal-wrap').setAttribute('aria-hidden', 'false'); const i = m.querySelector('input,select,textarea,button.btn'); if (i) setTimeout(() => i.focus(), 30); }
  function closeModal() { $('#modal-wrap').classList.remove('open'); $('#modal-wrap').setAttribute('aria-hidden', 'true'); }
  const mHead = (t, s) => `<div class="m-head"><div><h2>${t}</h2>${s ? `<p>${s}</p>` : ''}</div><button class="m-x" data-act="close-modal" aria-label="Close">×</button></div>`;

  function termsModal() {
    modal(`${mHead('Partner program — key terms', 'Summary for this prototype. The signed partner agreement governs.')}
    <div class="m-body terms">
      <h3>Commission</h3><p>20% of eligible net subscription revenue actually collected from each approved referred client, for as long as their subscription remains active and paid.</p>
      <h3>What counts as net revenue</h3><ul><li>Subscription fees received, excluding GST, VAT and other taxes</li><li>Less refunds, chargebacks, discounts and credits</li><li>Excludes one-off implementation or services fees</li></ul>
      <h3>Referral eligibility</h3><ul><li>Client subscribes through your link, code or a registered invitation</li><li>Attribution lasts 90 days from first click</li><li>Existing LedgerLine customers and self-referrals are not eligible</li></ul>
      <h3>Payment</h3><ul><li>Commission is held for 30 days to cover refunds, then becomes available</li><li>Paid monthly on the 15th via Stripe Connect, minimum US$50</li><li>Refunds after payout are deducted from the next payout</li></ul>
      <h3>Professional disclosure</h3><p>You are responsible for disclosing referral commissions to your clients in line with your professional and regulatory obligations. LedgerLine shows a disclosure on the client checkout page.</p>
    </div><div class="m-foot"><button class="btn" data-act="close-modal">Close</button></div>`, 'wide');
  }

  function inviteModal() {
    modal(`${mHead('Invite a client', 'We email your client a personal invitation with your referral link.')}
    <div class="m-body"><div class="field"><label for="iv-biz">Business name</label><input class="in-t" id="iv-biz" placeholder="Ironbark Brewing Co"></div>
    <div class="field"><label for="iv-email">Client email</label><input class="in-t" id="iv-email" type="email" placeholder="accounts@client.com.au"></div>
    <div class="field"><label for="iv-msg">Personal note (optional)</label><textarea class="in-t" id="iv-msg" rows="3" placeholder="Thought this would save you time at month-end."></textarea></div>
    <div class="note">The invitation includes your commission disclosure. Prototype: no email is sent.</div><div class="err-msg" id="iv-err"></div></div>
    <div class="m-foot"><button class="btn ghost" data-act="close-modal">Cancel</button><button class="btn" data-act="invite-send">Send invitation</button></div>`);
  }

  function stripeModal(step) {
    const p = me();
    const steps = {
      1: `${mHead('<span class="stripe-logo">stripe</span> &nbsp;Connect', 'LedgerLine partners with Stripe for secure payouts. Simulated onboarding — no data leaves this page.')}
        <div class="m-body"><p class="small muted" style="margin-bottom:14px">Step 1 of 3 · Business details</p>
        <div class="field"><label for="sx-type">Business type</label><select class="sel" id="sx-type"><option>Company</option><option>Sole trader</option><option>Partnership</option></select></div>
        <div class="field"><label for="sx-holder">Legal business name</label><input class="in-t" id="sx-holder" value="${esc(p.firm)} Pty Ltd"></div>
        <div class="field"><label for="sx-abn">ABN</label><input class="in-t" id="sx-abn" value="${esc(p.abn || '')}" placeholder="51 824 753 556"></div></div>
        <div class="m-foot"><button class="btn ghost" data-act="close-modal">Cancel</button><button class="btn stripe" data-sx="2">Continue</button></div>`,
      2: `${mHead('<span class="stripe-logo">stripe</span> &nbsp;Payout account', 'Step 2 of 3 · Where Stripe sends your commission')}
        <div class="m-body"><div class="row2"><div class="field"><label for="sx-bsb">BSB</label><input class="in-t mono" id="sx-bsb" value="062-000"></div><div class="field"><label for="sx-acc">Account number</label><input class="in-t mono" id="sx-acc" value="1234 4821"></div></div>
        <div class="field"><label for="sx-bank">Bank</label><input class="in-t" id="sx-bank" value="Commonwealth Bank"></div>
        <div class="note">Stripe verifies identity and bank details in a real integration. Here it is skipped.</div></div>
        <div class="m-foot"><button class="btn ghost" data-sx="1">Back</button><button class="btn stripe" data-sx="3">Continue</button></div>`,
      3: `${mHead('<span class="stripe-logo">stripe</span> &nbsp;Review', 'Step 3 of 3')}
        <div class="m-body"><dl class="kv"><dt>Business</dt><dd>${esc(UI.sx.holder)}</dd><dt>Payouts to</dt><dd>${esc(UI.sx.bank)} •••• ${esc(UI.sx.last4)}</dd><dt>Schedule</dt><dd>Monthly on the 15th</dd></dl>
        <p class="xs muted" style="margin-top:16px">By connecting, you agree to the Stripe Connected Account Agreement (shown for illustration).</p></div>
        <div class="m-foot"><button class="btn ghost" data-sx="2">Back</button><button class="btn stripe" data-act="stripe-finish">Agree and connect</button></div>`,
    };
    modal(steps[step], 'stripe-modal');
  }

  let tt;
  function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('show'); clearTimeout(tt); tt = setTimeout(() => t.classList.remove('show'), 2600); }

  function copy(text, msg) {
    const done = () => toast(msg);
    try { if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(done, () => fallback()); return; } } catch { /* ignore */ }
    fallback();
    function fallback() { const ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); } catch { /* ignore */ } ta.remove(); done(); }
  }

  function afterRender() {
    const n = $('#c-n'), pr = $('#c-p');
    if (n && pr) {
      const upd = () => { const m = Math.round(+n.value * +pr.value * 100 * RATE); $('#c-n-v').textContent = n.value; $('#c-p-v').textContent = 'US$' + pr.value; $('#c-m').textContent = M(m, { whole: true }); $('#c-a').textContent = M(m * 12, { whole: true }); };
      n.addEventListener('input', upd); pr.addEventListener('input', upd); upd();
    }
  }

  function readDraft() { ['name', 'email', 'pw', 'firm', 'abn'].forEach((k) => { const el = $('#' + k); if (el) UI.draft[k] = el.value.trim(); }); const t = $('#type'); if (t) UI.draft.type = t.value; const c = $('#country'); if (c) UI.draft.country = c.value; const a = $('#agree'); if (a) UI.draft.agree = a.checked; const ds = $('#disclose'); if (ds) UI.draft.disclose = ds.checked; }
  function readCo() { ['biz', 'contact', 'cemail', 'cabn'].forEach((k) => { const el = $('#' + k); if (el) UI.co[k] = el.value.trim(); }); const c = $('#ccountry'); if (c) UI.co.country = c.value; }
  const validEmail = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);

  function makeCode(firm) {
    const base = (firm.replace(/[^A-Za-z]/g, '').toUpperCase().slice(0, 6) || 'PARTNER');
    let code = base + '20', i = 2;
    while (S.partners.some((p) => p.code === code)) code = base + (20 + i++);
    return code;
  }

  function act(a) {
    const p = me();
    switch (a) {
      case 'close-modal': return closeModal();
      case 'terms': return termsModal();
      case 'su-next': {
        readDraft(); const d = UI.draft, e = {};
        if (!d.name) e.name = 'Enter your name';
        if (!validEmail(d.email || '')) e.email = 'Enter a valid email address';
        else if (S.partners.some((x) => x.email.toLowerCase() === d.email.toLowerCase())) e.email = 'A partner account already uses this email. Sign in instead.';
        if ((d.pw || '').length < 8) e.pw = 'Use at least 8 characters';
        UI.errors = e; if (!Object.keys(e).length) UI.signupStep = 2; return render();
      }
      case 'su-back': readDraft(); UI.signupStep = 1; UI.errors = {}; return render();
      case 'su-create': {
        readDraft(); const d = UI.draft, e = {};
        if (!d.firm) e.firm = 'Enter your firm name';
        if (!d.agree || !d.disclose) e.agree = 'Accept the partner terms and the disclosure commitment to continue';
        UI.errors = e; if (Object.keys(e).length) return render();
        const np = { id: nid('P-'), code: makeCode(d.firm), firm: d.firm, name: d.name, email: d.email, pw: d.pw, type: d.type || PTYPES[0], country: d.country || 'AU', abn: d.abn || '', created: S.today, status: 'approved', founding: true, stripe: null };
        S.partners.push(np); S.session = np.id; log(S, np.id, S.today, 'Partner account created and approved');
        save(); UI.draft = {}; UI.signupStep = 1; UI.tab = 'overview'; UI.co = { plan: 'growth', cycle: 'monthly', step: 1, ref: np.code, done: null };
        go('portal'); return toast(`Welcome to LedgerLine Partners — your code is ${np.code}`);
      }
      case 'signin': {
        const em = $('#si-email').value.trim().toLowerCase(), pw = $('#si-pw').value;
        const x = S.partners.find((q) => q.email.toLowerCase() === em && q.pw === pw);
        if (!x) { UI.errors = { si: 'Email or password is incorrect' }; return render(); }
        S.session = x.id; save(); UI.tab = 'overview'; UI.co.ref = x.code; return go('portal');
      }
      case 'demo-login': S.session = 'P-1'; save(); UI.tab = 'overview'; UI.co.ref = 'ELMCO20'; return go('portal');
      case 'signout': S.session = null; save(); UI.demoOpen = false; return go('home');
      case 'copy-link': p.shared = true; save(); copy(refLink(p), 'Referral link copied'); return render();
      case 'copy-email': { const t = $('#email-tpl'); p.shared = true; save(); return copy(t ? t.value : emailTemplate(p), 'Email template copied'); }
      case 'open-checkout': UI.demoOpen = false; UI.co = { plan: 'growth', cycle: 'monthly', step: 1, ref: p ? p.code : UI.co.ref, done: null }; if (p) { p.shared = true; save(); } return go('checkout');
      case 'invite': return inviteModal();
      case 'invite-send': {
        const biz = $('#iv-biz').value.trim(), em = $('#iv-email').value.trim();
        if (!biz || !validEmail(em)) { $('#iv-err').textContent = 'Enter the business name and a valid email.'; return; }
        S.invites.push({ id: nid('I-'), partnerId: p.id, biz, email: em, date: S.today, status: 'sent' }); p.shared = true;
        log(S, p.id, S.today, `Invitation sent to ${biz}`); save(); closeModal(); render(); return toast(`Invitation sent to ${em}`);
      }
      case 'stripe-connect': UI.sx = {}; return stripeModal(1);
      case 'stripe-manage': return modal(`${mHead('<span class="stripe-logo">stripe</span> &nbsp;Express dashboard', 'In a live integration this opens your Stripe Express dashboard.')}<div class="m-body"><dl class="kv"><dt>Account</dt><dd class="mono">${p.stripe.acct}</dd><dt>Payouts to</dt><dd>${esc(p.stripe.bank)}</dd><dt>Connected</dt><dd>${fd(p.stripe.connected)}</dd></dl></div><div class="m-foot"><button class="btn danger" data-act="stripe-disconnect">Disconnect</button><button class="btn" data-act="close-modal">Done</button></div>`, 'stripe-modal');
      case 'stripe-disconnect': p.stripe = null; log(S, p.id, S.today, 'Stripe disconnected — commission continues to accrue'); save(); closeModal(); render(); return toast('Stripe disconnected');
      case 'stripe-finish': {
        p.stripe = { acct: 'acct_1' + rid('', 15), bank: `${UI.sx.bank} •••• ${UI.sx.last4}`, holder: UI.sx.holder, schedule: 'monthly', connected: S.today };
        log(S, p.id, S.today, 'Stripe connected for payouts'); save(); closeModal(); render(); return toast('Stripe connected — payouts are on');
      }
      case 'payout': {
        const po = runPayout(S, p, S.today, false); save(); render();
        return toast(po ? `${M(po.amount)} sent to Stripe — arrives ${fd(po.arrival)}` : 'Nothing available to pay out');
      }
      case 'save-profile': {
        p.firm = $('#s-firm').value.trim() || p.firm; p.name = $('#s-name').value.trim() || p.name;
        const em = $('#s-email').value.trim(); if (validEmail(em)) p.email = em;
        p.abn = $('#s-abn').value.trim(); p.type = $('#s-type').value; save(); render(); return toast('Profile saved');
      }
      case 'export': {
        const rows = [['Date', 'Client', 'Invoice', 'Net collected (USD)', 'Rate', 'Commission (USD)', 'Status', 'Available from', 'Payout']];
        S.commissions.filter((x) => x.partnerId === p.id).forEach((x) => rows.push([x.date, (S.clients.find((c) => c.id === x.clientId) || {}).biz, (S.invoices.find((i) => i.id === x.invoiceId) || {}).num, (x.net / 100).toFixed(2), '20%', (x.amount / 100).toFixed(2), x.kind === 'clawback' ? 'adjustment' : x.status, x.availableOn, x.payoutId || '']));
        const csv = rows.map((r) => r.map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
        const a2 = document.createElement('a'); a2.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a2.download = `ledgerline-commissions-${p.code}-${S.today}.csv`; document.body.appendChild(a2); a2.click(); a2.remove();
        return toast('Commission statement downloaded');
      }
      case 'demo-toggle': UI.demoOpen = !UI.demoOpen; return render();
      case 'advance': {
        const before = stats(p); advanceMonth(); const after = stats(p);
        render(); return toast(`Now ${fd(S.today)} · commission earned ${M(after.lifetime - before.lifetime)}`);
      }
      case 'demo-fail': case 'demo-refund': case 'demo-cancel': {
        const c = S.clients.find((x) => x.id === $('#demo-client').value); if (!c) return;
        if (a === 'demo-fail') { c.failNext = true; save(); render(); return toast(`${c.biz}'s next payment (${fd(c.nextBill)}) will fail`); }
        if (a === 'demo-cancel') { c.status = 'cancelled'; c.cancelled = S.today; log(S, p.id, S.today, `${c.biz} cancelled — no further commission`); save(); render(); return toast(`${c.biz} cancelled`); }
        const inv = S.invoices.filter((i) => i.clientId === c.id && i.status === 'paid').pop();
        if (!inv) return toast('No paid invoice to refund');
        refundInvoice(S, inv, S.today, false); save(); render(); return toast(`${inv.num} refunded`);
      }
      case 'co-next': UI.co.step = 2; UI.errors = {}; return render();
      case 'co-back': readCo(); UI.co.step = 1; return render();
      case 'co-pay': {
        readCo(); const co = UI.co, e = {};
        if (!co.biz) e.biz = 'Enter your business name';
        if (!co.contact) e.contact = 'Enter your name';
        if (!validEmail(co.cemail || '')) e.cemail = 'Enter a valid email';
        const card = ($('#card').value || '').replace(/\s/g, '');
        if (!/^\d{15,16}$/.test(card)) { toast('Card number looks incomplete'); return; }
        UI.errors = e; if (Object.keys(e).length) return render();
        const ref = S.partners.find((x) => x.code === co.ref);
        const c = { id: nid('C-'), partnerId: ref ? ref.id : null, biz: co.biz, contact: co.contact, email: co.cemail, country: co.country || 'AU', plan: co.plan, cycle: co.cycle, start: S.today, nextBill: S.today, status: 'active', source: 'link', subId: 'sub_' + rid('', 14), cancelled: null, failNext: false };
        const iv = ref && S.invites.find((i) => i.partnerId === ref.id && i.status !== 'subscribed' && (i.email.toLowerCase() === co.cemail.toLowerCase() || i.biz.toLowerCase() === co.biz.toLowerCase()));
        if (iv) { iv.status = 'subscribed'; c.source = 'invite'; }
        S.clients.push(c);
        if (ref) log(S, ref.id, S.today, `${c.biz} subscribed to ${PLANS[c.plan].name}${c.cycle === 'annual' ? ' (annual)' : ''} through your ${c.source === 'invite' ? 'invitation' : 'link'}`);
        const inv = billOnce(S, c, S.today, false, false);
        save(); UI.co.done = { biz: c.biz, plan: c.plan, total: inv.total, email: c.email, subId: c.subId, num: inv.num };
        return render();
      }
      case 'co-to-portal': { const ref = S.partners.find((x) => x.code === UI.co.ref); if (ref) { S.session = ref.id; save(); } UI.tab = 'clients'; UI.cfilter = 'all'; UI.co.done = null; UI.co.step = 1; return go('portal'); }
      case 'co-again': UI.co = { plan: 'growth', cycle: 'monthly', step: 1, ref: UI.co.ref, done: null }; return render();
      default: return undefined;
    }
  }

  document.addEventListener('click', (ev) => {
    const el = ev.target.closest('[data-act],[data-go],[data-tab],[data-jump],[data-plan],[data-cycle],[data-cf],[data-sched],[data-sx],[data-invco]');
    if (!el) return;
    const d = el.dataset;
    if (el.tagName === 'A') ev.preventDefault();
    if (d.act) return act(d.act, el);
    if (d.go) { if (d.go === 'checkout') { const p = me() || S.partners[0]; UI.co = { plan: 'growth', cycle: 'monthly', step: 1, ref: p ? p.code : null, done: null }; } return go(d.go); }
    if (d.tab) { UI.tab = d.tab; UI.route = 'portal'; syncUrl(false); render(); return window.scrollTo(0, 0); }
    if (d.jump) { const t = document.getElementById(d.jump); if (t) window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - 90, behavior: 'smooth' }); return; }
    if (d.plan) { UI.co.plan = d.plan; return render(); }
    if (d.cycle) { UI.co.cycle = d.cycle; return render(); }
    if (d.cf) { UI.cfilter = d.cf; return render(); }
    if (d.sched) { const p = me(); p.stripe.schedule = d.sched; save(); render(); return toast(d.sched === 'monthly' ? 'Payouts scheduled monthly on the 15th' : 'Payouts set to manual'); }
    if (d.sx) {
      const n = +d.sx;
      if (n === 2 && $('#sx-holder')) UI.sx.holder = $('#sx-holder').value.trim() || me().firm;
      if (n === 3 && $('#sx-acc')) { UI.sx.bank = $('#sx-bank').value.trim() || 'Bank'; UI.sx.last4 = ($('#sx-acc').value.replace(/\D/g, '').slice(-4)) || '0000'; }
      return stripeModal(n);
    }
    if (d.invco) { const p = me(); const i = S.invites.find((x) => x.id === d.invco); UI.co = { plan: 'growth', cycle: 'monthly', step: 1, ref: p.code, done: null, biz: i.biz, cemail: i.email }; return go('checkout'); }
  });
  const clearErr = (ev) => { const t = ev.target; if (!t.classList) return; if (t.classList.contains('err')) { t.classList.remove('err'); const m = t.parentNode.querySelector('.err-msg'); if (m) m.remove(); } if (t.type === 'checkbox') { const a = document.getElementById('agree'), d = document.getElementById('disclose'); if (a && d && a.checked && d.checked) document.querySelectorAll('#app .err-msg').forEach((m) => { if (/terms/.test(m.textContent)) m.remove(); }); } };
  document.addEventListener('input', clearErr); document.addEventListener('change', clearErr);
  document.addEventListener('change', (ev) => { if (ev.target.id === 'ccountry') { readCo(); render(); } });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') { if ($('#modal-wrap').classList.contains('open')) closeModal(); else if (UI.demoOpen) { UI.demoOpen = false; render(); } }
    if (ev.key === 'Enter' && ev.target.matches('.auth-card input')) { const b = $('.auth-card [data-act="su-next"], .auth-card [data-act="su-create"], .auth-card [data-act="signin"]'); if (b) b.click(); }
  });
  $('#modal-wrap').addEventListener('click', (ev) => { if (ev.target.id === 'modal-wrap') closeModal(); });
  $('#proto-reset').addEventListener('click', () => { store.clear(); S = seed(); save(); UI.tab = 'overview'; UI.co = { plan: 'growth', cycle: 'monthly', step: 1, ref: null, done: null }; UI.demoOpen = false; go('home'); toast('Sample data restored'); });

  load();
  readLocation();
  if (UI.route === 'portal' && !S.session) UI.route = 'signin';
  if (UI.route === 'checkout' && !UI.co.ref) { const p = me() || S.partners[0]; UI.co.ref = p ? p.code : null; }
  render();
  window.addEventListener('popstate', () => {
    readLocation();
    if (UI.route === 'portal' && !S.session) UI.route = 'signin';
    if (UI.route === 'checkout' && !UI.co.ref) { const p = me() || S.partners[0]; UI.co.ref = p ? p.code : null; }
    UI.errors = {};
    render();
  });
  window.__LP = { S: () => S, UI, stats };
})();
