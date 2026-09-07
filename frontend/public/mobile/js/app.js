/* Quantum Ledger Link — mobile prototype behaviour
   Vanilla JS, no build step. Pointer events so swipe works with touch AND mouse. */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ---------------- formatting ---------------- */
  function fmt(n, forceCents) {
    var cents = forceCents || Math.abs(n % 1) > 0.001;
    return 'A$' + n.toLocaleString('en-AU', {
      minimumFractionDigits: cents ? 2 : 0,
      maximumFractionDigits: cents ? 2 : 0
    });
  }
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* ---------------- icons ---------------- */
  var IC = {
    chev: '<svg class="chev" width="9" height="15" viewBox="0 0 9 15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M1.4 1.4 7 7.5l-5.6 6.1"/></svg>',
    tick: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M2.4 8.4l3.4 3.4L13.6 4"/></svg>',
    warn: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M8 2.6 14.4 13.4H1.6L8 2.6Z"/><path d="M8 6.6v3.2M8 11.9h.01"/></svg>',
    neg: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="8" cy="8" r="6.2"/><path d="M8 4.8v4.2M8 11.2h.01"/></svg>',
    lock: '<svg width="11" height="11" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><rect x="2.6" y="6" width="8.8" height="6.4" rx="1.6"/><path d="M4.6 6V4.6a2.4 2.4 0 0 1 4.8 0V6"/></svg>',
    clock: '<svg width="11" height="11" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="7" cy="7" r="5.4"/><path d="M7 4.2V7l2 1.4"/></svg>',
    docLines: '<div class="l dk md"></div><div class="l sh"></div><div class="l"></div><div class="l md"></div><div class="l"></div><div class="l dk xs"></div>'
  };
  function checkIcon(tone) { return tone === 'pos' ? IC.tick : tone === 'warn' ? IC.warn : IC.neg; }

  /* ---------------- state ---------------- */
  var state = {
    screen: 'home',
    role: 'employee',
    canApprove: false,
    canReject: false,
    approvals: [],
    selectMode: false,
    selected: {},
    apFilter: 'all',
    apQuery: '',
    itemTab: 'claims',
    fileFilter: null,
    fileQuery: '',
    fileView: 'grid',
    detailId: null,
    advance: { amount: 2500, purpose: 'Client travel' },
    receiptsAttached: false,
    edited: {}
  };

  /* =========================================================
     SESSION IDENTITY (real LedgerLink user / tenant)
     ========================================================= */
  function substituteMe(value, name) {
    if (typeof value === 'string') {
      return value.split('__ME__').join(name);
    }
    if (Array.isArray(value)) {
      return value.map(function (v) { return substituteMe(v, name); });
    }
    if (value && typeof value === 'object') {
      Object.keys(value).forEach(function (k) {
        value[k] = substituteMe(value[k], name);
      });
    }
    return value;
  }

  function employeeGreeting() {
    return LLSession.greetingPrefix() + ', ' + LLSession.firstName(QLL.me.name);
  }

  function employeeHomeSub() {
    var bits = [LLSession.formatToday(), QLL.tenant].filter(Boolean);
    return bits.join(' · ') || '—';
  }

  function approverHomeSub() {
    var n = state.approvals ? state.approvals.length : 0;
    return n + ' decision' + (n === 1 ? '' : 's') + ' in queue · ' + (QLL.tenant || 'your organisation');
  }

  function applyIdentity(user) {
    if (!user) {
      location.replace(LLSession.loginUrl());
      return false;
    }

    var name = String(user.full_name || user.email || 'User').trim();
    var roleLabel = LLSession.formatRole(user.role);
    var memberships = LLSession.getMemberships();
    var tenantName = String(user.tenant_name || '').trim();

    QLL.me.name = name;
    QLL.me.initials = LLSession.initialsFromName(name);
    QLL.me.email = String(user.email || '').trim();
    QLL.me.role = roleLabel;
    QLL.me.dept = tenantName;
    QLL.tenant = tenantName;
    QLL.entities = memberships.length
      ? memberships.map(function (m) {
          return {
            id: m.tenant_id,
            name: m.tenant_name,
            slug: m.tenant_slug,
            role: m.role,
            current: String(m.tenant_id) === String(user.tenant_id)
          };
        })
      : [{
          id: user.tenant_id,
          name: tenantName || 'Current organisation',
          slug: user.tenant_slug || '',
          role: user.role,
          current: true
        }];

    substituteMe(QLL, name);
    // Approvals loaded from API after privileges resolve — do not seed demo queue.

    var setText = function (id, text) {
      var el = $('#' + id);
      if (el) el.textContent = text;
    };

    setText('homeCompact', name);
    setText('homeAv', QLL.me.initials);
    setText('greeting', state.role === 'approver' ? 'Approver view' : employeeGreeting());
    setText('homeSub', state.role === 'approver' ? approverHomeSub() : employeeHomeSub());
    setText('itemsSub', [name, roleLabel, tenantName].filter(Boolean).join(' · '));
    setText('profAv', QLL.me.initials);
    setText('profName', name);
    setText('profRole', [roleLabel, tenantName].filter(Boolean).join(' · '));
    setText('profEmail', QLL.me.email || '—');
    setText('entityTitle', tenantName || 'Organisation');
    setText(
      'entitySub',
      [user.tenant_slug, roleLabel].filter(Boolean).join(' · ') || roleLabel || '—'
    );
    setText('profileFoot', 'LedgerLink · ' + (tenantName || 'signed in'));

    var switchLbl = $('#entitySwitchLabel');
    if (switchLbl) {
      switchLbl.style.display = QLL.entities.length > 1 ? '' : 'none';
    }

    return true;
  }

  function syncRoleChrome() {
    var isApprover = state.role === 'approver';
    $$('#roleSeg button').forEach(function (x) {
      x.classList.toggle('active', x.dataset.role === state.role);
    });
    $$('[data-role-panel]').forEach(function (p) {
      p.hidden = p.dataset.rolePanel !== state.role;
    });
    var greet = $('#greeting');
    var sub = $('#homeSub');
    if (greet) greet.textContent = isApprover ? 'Approver view' : employeeGreeting();
    if (sub) sub.textContent = isApprover ? approverHomeSub() : employeeHomeSub();

    var apTab = document.querySelector('.tabbar [data-tab="approvals"]');
    if (apTab) apTab.style.display = isApprover ? '' : 'none';
    var qa = document.querySelector('[data-role-panel="employee"] .qa[data-go="approvals"]');
    if (qa) qa.style.display = isApprover ? '' : 'none';

    if (!isApprover && (state.screen === 'approvals' || state.screen === 'detail')) {
      showScreen('home');
    }
  }

  function applyPrivileges(perms) {
    var bag = (perms && perms.permissions) || {};
    state.canApprove = !!bag.Approve;
    state.canReject = !!bag.Reject;
    state.role = (state.canApprove || state.canReject) ? 'approver' : 'employee';
    var roleSeg = $('#roleSeg');
    if (roleSeg) roleSeg.hidden = true;
    syncRoleChrome();
  }

  function invoiceToApproval(inv) {
    var amount = Number(inv.total);
    if (!isFinite(amount)) amount = 0;
    var who = String(inv.vendor || inv.employee_email || inv.email_sender || 'Document').trim();
    var desc = String(inv.document_ref || inv.invoice_no || ('#' + inv.id)).trim();
    var dt = String(inv.document_type_code || inv.purchase_document_type || 'Document').trim();
    var status = String(inv.status || '');
    var flag = '';
    var flagTone = '';
    if (status === 'exception') { flag = 'Needs review'; flagTone = 'warn'; }
    else if (status === 'rejected') { flag = 'Rejected'; flagTone = 'neg'; }
    else if (status === 'duplicate_skipped') { flag = 'Duplicate'; flagTone = 'warn'; }
    var issues = Array.isArray(inv.validation_results) ? inv.validation_results : [];
    var checks = issues.slice(0, 6).map(function (row) {
      var ok = row && (row.passed === true || row.status === 'pass' || row.ok === true);
      return [ok ? 'pos' : 'warn', row.rule || row.name || 'Check', row.message || row.detail || ''];
    });
    if (!checks.length && flag) {
      checks = [['warn', 'Status', flag]];
    }
    return {
      id: String(inv.id),
      invoiceId: Number(inv.id),
      group: 'Today',
      who: who,
      init: LLSession.initialsFromName(who),
      dept: String(inv.cost_centre || inv.account_name || '—'),
      amount: amount,
      desc: desc,
      dt: dt,
      sla: status || 'queued',
      slaTone: '',
      flag: flag,
      flagTone: flagTone,
      checks: checks,
      chain: [
        [who, 'In approval queue', 'done'],
        ['__ME__', 'You — awaiting decision', 'now']
      ]
    };
  }

  async function loadLiveApprovals() {
    if (!(state.canApprove || state.canReject)) {
      state.approvals = [];
      renderApprovals();
      syncRoleChrome();
      return;
    }
    try {
      var rows = await LLSession.listApprovals(50);
      if (!Array.isArray(rows)) rows = [];
      state.approvals = rows.map(invoiceToApproval);
      substituteMe(state.approvals, QLL.me.name);
      renderApprovals();
      syncRoleChrome();
    } catch (err) {
      toast((err && err.message) || 'Could not load approvals');
      state.approvals = [];
      renderApprovals();
    }
  }

  /* =========================================================
     SCREEN NAVIGATION
     ========================================================= */
  var TABS = ['home', 'approvals', 'capture', 'items', 'files'];

  function showScreen(name, opts) {
    opts = opts || {};
    if ((name === 'approvals' || name === 'detail') && state.role !== 'approver') {
      name = 'home';
    }
    if (name === state.screen && !opts.force) { return; }
    var cur = $('.screen.active');
    var next = $('.screen[data-screen="' + name + '"]');
    if (!next) { return; }
    if (cur && cur !== next) { cur.classList.remove('active'); }
    next.classList.add('active');
    state.screen = name;

    // tab bar visibility
    var tb = $('#tabbar');
    var hide = (name === 'capture' || name === 'detail' || name === 'profile');
    tb.style.display = hide ? 'none' : '';

    $$('.tab').forEach(function (t) {
      t.classList.toggle('active', t.dataset.tab === name);
    });

    // reset scroll + large title
    var body = $('.body', next);
    if (body && !opts.keepScroll) { body.scrollTop = 0; }
    var nav = $('.nav', next);
    if (nav && name !== 'detail' && body) { nav.classList.toggle('stuck', body.scrollTop > 12); }

    if (name === 'capture') {
      hideSuccess();
      if (window.LLCapture) LLCapture.onShowCapture();
    } else {
      if (window.LLCapture) LLCapture.onHideCapture();
      if (name === 'home' && window.LLCapture && LLCapture.refreshHomeActivity) {
        LLCapture.refreshHomeActivity();
      }
      if (name === 'approvals') {
        void loadLiveApprovals();
      }
      if (name === 'items') {
        void loadMyItems();
      }
      if (name === 'home') {
        void loadHomeFinance();
      }
    }
    syncPicker();
  }

  function syncPicker() {
    /* no-op: prototype screen rail removed */
  }
  function currentPickerKey() {
    if (state.screen === 'home') { return state.role === 'approver' ? 'home-approver' : 'home'; }
    if (state.screen === 'files') { return state.fileView === 'list' ? 'files-list' : 'files'; }
    if (state.screen === 'approvals') { return state.selectMode ? 'approvals-select' : 'approvals'; }
    return state.screen;
  }

  /* collapsing large titles */
  $$('.body[data-scroll]').forEach(function (body) {
    body.addEventListener('scroll', function () {
      var nav = $('.nav', body.closest('.screen'));
      if (nav) { nav.classList.toggle('stuck', body.scrollTop > 12); }
    }, { passive: true });
  });

  /* delegated "data-go" navigation */
  document.addEventListener('click', function (e) {
    var go = e.target.closest('[data-go]');
    if (!go) { return; }
    if (go.dataset.subtab) { state.itemTab = go.dataset.subtab; renderItems(); }
    showScreen(go.dataset.go);
  });

  $$('.tab').forEach(function (t) {
    t.addEventListener('click', function () {
      if (state.selectMode) { exitSelect(); }
      showScreen(t.dataset.tab);
    });
  });

  /* =========================================================
     SHEETS + TOAST
     ========================================================= */
  var sheet = $('#sheet'), scrim = $('#scrim');
  function openSheet(cfg) {
    $('#sheetTitle').textContent = cfg.title || '';
    var sub = $('#sheetSub');
    sub.textContent = cfg.sub || '';
    sub.style.display = cfg.sub ? '' : 'none';
    $('#sheetBody').innerHTML = cfg.body || '';
    $('#sheetFoot').innerHTML = cfg.foot || '';
    $('#sheetFoot').style.display = cfg.foot ? '' : 'none';
    sheet.classList.add('show');
    scrim.classList.add('show');
    sheet.style.maxHeight = cfg.tall ? '92%' : '88%';
    if (cfg.onMount) { cfg.onMount($('#sheetBody'), $('#sheetFoot')); }
  }
  function closeSheet() {
    sheet.classList.remove('show');
    scrim.classList.remove('show');
  }
  scrim.addEventListener('click', closeSheet);
  $('#grabber').addEventListener('click', closeSheet);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeSheet(); } });

  var toastT;
  function toast(msg) {
    var el = $('#toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastT);
    toastT = setTimeout(function () { el.classList.remove('show'); }, 2200);
  }

  /* =========================================================
     HOME
     ========================================================= */
  function ring(el, pct, tone, label) {
    var r = 38, c = 2 * Math.PI * r;
    var col = tone === 'neg' ? 'var(--neg)' : tone === 'warn' ? 'var(--warn)' : 'var(--accent)';
    el.innerHTML =
      '<svg width="92" height="92" viewBox="0 0 92 92" aria-hidden="true">' +
      '<circle cx="46" cy="46" r="' + r + '" fill="none" stroke="var(--line-2)" stroke-width="7"/>' +
      '<circle cx="46" cy="46" r="' + r + '" fill="none" stroke="' + col + '" stroke-width="7" stroke-linecap="round"' +
      ' stroke-dasharray="' + c.toFixed(1) + '" stroke-dashoffset="' + (c * (1 - Math.min(pct, 1))).toFixed(1) + '"/></svg>' +
      '<div class="ring-c"><div class="pct">' + Math.round(pct * 100) + '%</div><div class="pctl">' + label + '</div></div>';
  }

  function renderHomeBudget() {
    var m = QLL.me;
    var used = Number(m.claimed) || 0;
    var alloc = Number(m.budget) || 0;
    var rem = m.remaining != null ? Number(m.remaining) : alloc - used;
    var approved = Number(m.approved) || 0;
    var hasBudget = !!m.hasBudget || alloc > 0 || used > 0;

    if (!hasBudget) {
      $('#budRem').textContent = '—';
      $('#budUsed').textContent = '—';
      $('#budAlloc').textContent = '—';
      $('#budApp').textContent = approved ? fmt(approved) : '—';
      ring($('#budgetRing'), 0, 'accent', 'n/a');
    } else {
      $('#budRem').textContent = fmt(Math.max(rem, 0));
      $('#budUsed').textContent = fmt(used);
      $('#budAlloc').textContent = fmt(alloc);
      $('#budApp').textContent = fmt(approved);
      var pct = alloc > 0 ? used / alloc : 0;
      ring($('#budgetRing'), pct, pct > 0.9 ? 'warn' : 'accent', 'used');
    }
  }

  function renderHomeAdvance() {
    var a = QLL.me.advance;
    var amtEl = $('#advAmt');
    var chip = $('#advChip');
    var title = $('#advTitle');
    var meta = $('#advMeta');
    var barWrap = $('#advBarWrap');
    var bar = $('#advBar');
    if (!amtEl) return;

    if (!a || !(Number(a.amount) > 0 || Number(a.outstanding) > 0 || Number(a.taken) > 0)) {
      amtEl.textContent = fmt(0);
      if (chip) { chip.hidden = true; chip.textContent = ''; }
      if (title) title.textContent = 'No advance outstanding';
      if (meta) meta.textContent = 'Tap to view advances in My items';
      if (barWrap) barWrap.hidden = true;
      return;
    }

    var outstanding = Number(a.outstanding != null ? a.outstanding : a.amount) || 0;
    var taken = Number(a.taken != null ? a.taken : a.amount) || outstanding;
    var acquitted = Number(a.acquitted) || 0;
    amtEl.textContent = fmt(outstanding > 0 ? outstanding : taken);
    if (chip) {
      chip.hidden = false;
      chip.className = 'chip warn';
      chip.textContent = outstanding > 0 ? 'Outstanding' : 'Advance';
    }
    if (title) {
      title.textContent = [a.purpose, a.ref].filter(Boolean).join(' · ') || 'Staff advance';
    }
    if (meta) {
      meta.textContent =
        (acquitted ? fmt(acquitted) + ' used' : 'No claims against advance yet') +
        (a.issued ? ' · issued ' + a.issued : '');
    }
    if (barWrap && bar) {
      barWrap.hidden = false;
      var pct = taken > 0 ? Math.min(acquitted / taken, 1) : 0;
      bar.style.width = Math.round(pct * 100) + '%';
      bar.className = pct >= 1 ? 'pos' : 'warn';
    }
  }

  function renderHome() {
    renderHomeBudget();
    renderHomeAdvance();

    var queueAmt = $('#apQueueAmt');
    var queueSub = $('#apQueueSub');
    var queueChips = $('#apQueueChips');
    var apTotal = state.approvals.reduce(function (s, a) { return s + (Number(a.amount) || 0); }, 0);
    var apN = state.approvals.length;
    var exceptions = state.approvals.filter(function (a) { return a.flag; }).length;
    if (queueAmt) queueAmt.textContent = apN ? fmt(Math.round(apTotal)) : fmt(0);
    if (queueSub) {
      queueSub.textContent = apN
        ? apN + ' item' + (apN === 1 ? '' : 's') + ' awaiting your decision'
        : 'Queue clear';
    }
    if (queueChips) {
      queueChips.innerHTML = exceptions
        ? '<span class="chip warn">' + exceptions + ' exception' + (exceptions === 1 ? '' : 's') + '</span>'
        : '';
    }
    ring($('#queueRing'), apN ? Math.min(apN / 12, 1) : 0, exceptions ? 'neg' : 'accent', 'queue');

    if (window.LLCapture && LLCapture.refreshHomeActivity) {
      void LLCapture.refreshHomeActivity();
    } else {
      $('#activityRows').innerHTML =
        '<div class="empty" style="padding:20px;font-size:13px;color:var(--ink-3)">Sign in to see recent documents.</div>';
      $('#actCount').textContent = '0 items';
    }
    var offline = $('#offlineSub');
    if (offline && window.LLCaptureApi) {
      var processing = LLCaptureApi.readPending().filter(function (p) {
        return p.status === 'processing';
      }).length;
      var draftPages = window.LLCapture && LLCapture.getPages ? LLCapture.getPages().length : 0;
      if (processing || draftPages) {
        offline.textContent =
          (processing ? processing + ' processing' : '') +
          (processing && draftPages ? ' · ' : '') +
          (draftPages ? draftPages + ' page(s) ready to retry/upload' : '');
      } else {
        offline.textContent = 'No queued captures';
      }
    }

    // Approver spend card: only signed-in employee (no demo teammates).
    var teamHost = $('#teamRows');
    if (teamHost) {
      if (QLL.me.hasBudget || (QLL.me.budget > 0 || QLL.me.claimed > 0)) {
        var used = Number(QLL.me.claimed) || 0;
        var alloc = Number(QLL.me.budget) || 0;
        var pct = alloc > 0 ? used / alloc : 0;
        var over = alloc > 0 && used > alloc;
        var tone = over ? 'neg' : pct > 0.9 ? 'warn' : 'pos';
        teamHost.innerHTML =
          '<div class="row" style="align-items:flex-start;flex-direction:column;gap:7px">' +
          '<div style="display:flex;width:100%;gap:10px;align-items:baseline">' +
          '<span class="t truncate" style="flex:1">' + esc(QLL.me.name || 'You') + '</span>' +
          '<span class="amt" style="font-size:14px;font-weight:600">' + fmt(used) + '</span>' +
          '<span class="s" style="margin:0">of ' + fmt(alloc) + '</span></div>' +
          '<div class="bar" style="width:100%"><i class="' + tone + '" style="width:' + Math.min(pct, 1) * 100 + '%"></i></div>' +
          '<div style="display:flex;width:100%;gap:8px"><span class="s" style="margin:0;flex:1">' + esc(QLL.me.dept || QLL.me.role || '') + '</span>' +
          '<span class="chip ' + tone + '">' +
          (over ? fmt(used - alloc) + ' over' : fmt(Math.max(alloc - used, 0)) + ' left') +
          '</span></div></div>';
      } else {
        teamHost.innerHTML =
          '<div class="empty" style="padding:16px;font-size:13px;color:var(--ink-3)">No budget data for your employee profile.</div>';
      }
    }
  }

  async function loadHomeFinance() {
    if (!window.LLCaptureApi || !LLCaptureApi.loadMyHomeFinance) return;
    var email = (QLL.me && QLL.me.email) || (LLSession.getUser() && LLSession.getUser().email) || '';
    try {
      var fin = await LLCaptureApi.loadMyHomeFinance(email);
      QLL.me.budget = fin.budget;
      QLL.me.claimed = fin.claimed;
      QLL.me.approved = fin.approved;
      QLL.me.remaining = fin.remaining;
      QLL.me.hasBudget = fin.hasBudget;
      QLL.me.advance = fin.advance;
      renderHomeBudget();
      renderHomeAdvance();
      if (state.role === 'approver') renderHome();
    } catch (err) {
      QLL.me.budget = 0;
      QLL.me.claimed = 0;
      QLL.me.approved = 0;
      QLL.me.advance = null;
      QLL.me.hasBudget = false;
      renderHomeBudget();
      renderHomeAdvance();
    }
  }

  /* role segmented control — hidden after permissions load */
  $$('#roleSeg button').forEach(function (b) {
    b.addEventListener('click', function () {
      state.role = b.dataset.role;
      syncRoleChrome();
      $('.body', $('.screen[data-screen="home"]')).scrollTop = 0;
      syncPicker();
    });
  });

  /* Recent activity clicks are handled by LLCapture.wireActivityClicks */

  /* advance card -> open real advance / My items */
  function acquitSheet() {
    var a = QLL.me.advance;
    if (a && a.invoiceId && window.LLCapture && LLCapture.openReviewForId) {
      LLCapture.openReviewForId(a.invoiceId, { fromHome: true, sourceLabel: 'Advance' }).catch(function (err) {
        toast((err && err.message) || 'Could not open advance');
      });
      return;
    }
    state.itemTab = 'advances';
    showScreen('items');
    toast(a ? 'Open an advance from My items' : 'No advance outstanding');
  }
  $('#advCard').addEventListener('click', acquitSheet);

  /* quick action: request an advance → Capture with Advance intent */
  function advanceSheet() {
    closeSheet();
    if (window.LLCapture && LLCapture.setTeamExpenseIntent) {
      LLCapture.setTeamExpenseIntent('advance_requisition', { quiet: true });
    }
    showScreen('capture');
    toast('Advance selected · capture or choose the signed request form');
  }
  $('#qaAdvance').addEventListener('click', advanceSheet);

  /* =========================================================
     CAPTURE (real API via LLCapture)
     ========================================================= */
  function hideSuccess() {
    var s = $('#successOverlay');
    if (s) { s.remove(); }
  }

  function reviewSheet(source) {
    toast((source || 'Capture') + ' · use the shutter or Choose file');
  }

  function showSuccess() {
    toast('Submit from the review sheet after upload');
  }

  LLCapture.init({
    toast: toast,
    openSheet: openSheet,
    closeSheet: closeSheet,
    showScreen: showScreen,
    hideSuccess: hideSuccess,
    fmt: fmt,
    esc: esc,
    checkIcon: checkIcon,
    IC: IC,
    QLL: QLL,
    state: state,
    onPendingChange: function () {
      // renderHome already calls refreshHomeActivity — avoid a duplicate list GET.
      renderHome();
    }
  });


  /* =========================================================
     APPROVALS INBOX
     ========================================================= */
  var GROUPS = ['Today', 'This week', 'Overdue SLA'];

  function visibleApprovals() {
    var q = state.apQuery.trim().toLowerCase();
    return state.approvals.filter(function (a) {
      if (state.apFilter === 'exception' && !a.flag) { return false; }
      if (state.apFilter === 'overdue' && a.group !== 'Overdue SLA') { return false; }
      if (state.apFilter === 'advance' && a.dt !== 'DT-12' && a.dt !== 'DT-13') { return false; }
      if (!q) { return true; }
      return (a.who + ' ' + a.desc + ' ' + a.dt + ' ' + a.dept + ' ' + a.amount).toLowerCase().indexOf(q) > -1;
    });
  }

  function renderApprovals() {
    var list = visibleApprovals();
    var st = document.getElementById('selToggle');
    if (st) { st.hidden = !list.length; }
    var host = $('#apList');
    if (!list.length) {
      var filtered = state.apQuery.trim() || state.apFilter !== 'all';
      var noneLeft = !state.approvals.length;
      if (noneLeft && !filtered) {
        host.innerHTML = '<div class="empty">' +
          '<svg width="30" height="30" viewBox="0 0 30 30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="color:var(--pos)"><path d="M7 15.6l5.2 5.2L23 9.4"/></svg>' +
          '<div>Queue clear.<br>Every decision is recorded in the ledger audit trail.</div></div>';
      } else {
        host.innerHTML = '<div class="empty">' +
          '<svg width="30" height="30" viewBox="0 0 30 30" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="13" cy="13" r="8.6"/><path d="M19.4 19.4 26 26"/></svg>' +
          '<div>No approvals match.<br>Clear the search or filter to see your queue.</div></div>';
      }
    } else {
      host.innerHTML = GROUPS.map(function (g) {
        var items = list.filter(function (a) { return a.group === g; });
        if (!items.length) { return ''; }
        var tot = items.reduce(function (s, a) { return s + a.amount; }, 0);
        return '<div class="sect-h">' + g + '<span class="r">' + items.length + ' · ' + fmt(Math.round(tot)) + '</span></div>' +
          '<div class="rows" style="border-radius:0">' + items.map(rowHTML).join('') + '</div>';
      }).join('');
    }
    var total = state.approvals.reduce(function (s, a) { return s + a.amount; }, 0);
    var overdue = state.approvals.filter(function (a) { return a.group === 'Overdue SLA'; }).length;
    $('#apSub').textContent = state.approvals.length + ' items · ' + fmt(Math.round(total)) + ' · ' + overdue + ' overdue SLA';
    $('#tabBadge').textContent = state.approvals.length;
    $('#qaBadge').textContent = state.approvals.length;
    $('#tabBadge').style.display = state.approvals.length ? '' : 'none';
    bindSwipes();
    updateBulk();
  }

  function rowHTML(a) {
    return '<div class="swipe' + (state.selectMode ? ' selectmode' : '') + '" data-id="' + a.id + '" data-sel="' + (state.selected[a.id] ? 1 : 0) + '">' +
      '<div class="swipe-bg" aria-hidden="true">' +
      '<span class="ap">' + IC.tick + ' Approve</span>' +
      '<span class="rj">Reject ' + IC.neg + '</span></div>' +
      '<div class="swipe-fg">' +
      '<span class="sel-box">' + IC.tick + '</span>' +
      '<span class="av">' + a.init + '</span>' +
      '<span class="ai-main">' +
      '<span class="ai-top"><span class="ai-who truncate">' + esc(a.who) + ' · ' + esc(a.dept) + '</span>' +
      '<span class="ai-amt">' + fmt(a.amount, a.amount % 1 !== 0) + '</span></span>' +
      '<span class="ai-desc truncate" style="display:block">' + esc(a.desc) + '</span>' +
      '<span class="ai-meta">' +
      '<span class="chip dt">' + a.dt + '</span>' +
      '<span class="chip ' + (a.slaTone || '') + '">' + IC.clock + a.sla + '</span>' +
      (a.flag ? '<span class="chip ' + a.flagTone + '">' + esc(a.flag) + '</span>' : '') +
      '</span>' +
      '<span class="ai-acts">' +
      (state.canApprove
        ? '<button class="ai-approve" data-approve="' + a.id + '">' + IC.tick + ' Approve</button>'
        : '') +
      (state.canReject
        ? '<button class="ai-reject" data-reject="' + a.id + '">Reject</button>'
        : '') +
      '<button class="ai-reject" data-open="' + a.id + '" style="flex:0 0 44px;background:var(--canvas);color:var(--ink-3)" aria-label="Open detail">' + IC.chev.replace('class="chev"', '') + '</button>' +
      '</span></span></div></div>';
  }

  function findAp(id) {
    return state.approvals.filter(function (a) { return a.id === id; })[0];
  }

  /* --- swipe (pointer events: touch + mouse) --- */
  function bindSwipes() {
    $$('#apList .swipe').forEach(function (row) {
      var fg = $('.swipe-fg', row);
      var startX = 0, startY = 0, dx = 0, dragging = false, decided = false, active = false;
      var TH = 76;

      fg.addEventListener('pointerdown', function (e) {
        if (state.selectMode) { return; }
        if (e.target.closest('button')) { return; }
        active = true; dragging = false; decided = false;
        startX = e.clientX; startY = e.clientY; dx = 0;
        fg.classList.remove('snap');
      });
      fg.addEventListener('pointermove', function (e) {
        if (!active) { return; }
        var mx = e.clientX - startX, my = e.clientY - startY;
        if (!decided) {
          if (Math.abs(mx) < 6 && Math.abs(my) < 6) { return; }
          decided = true;
          dragging = Math.abs(mx) > Math.abs(my);
          if (dragging) { try { fg.setPointerCapture(e.pointerId); } catch (err) {} }
        }
        if (!dragging) { return; }
        e.preventDefault();
        dx = mx;
        var d = Math.sign(dx) * Math.min(Math.abs(dx), 132);
        fg.style.transform = 'translateX(' + d + 'px)';
        row.classList.toggle('armed', Math.abs(dx) > TH);
      });
      function end() {
        if (!active) { return; }
        active = false;
        fg.classList.add('snap');
        fg.style.transform = '';
        row.classList.remove('armed');
        if (dragging && Math.abs(dx) > TH) {
          if (dx > 0) { approveSheet([row.dataset.id], 'swipe'); }
          else { rejectSheet([row.dataset.id], 'swipe'); }
        }
        dx = 0;
      }
      fg.addEventListener('pointerup', end);
      fg.addEventListener('pointercancel', end);
      fg.addEventListener('pointerleave', function () { if (active && !dragging) { active = false; } });
    });
  }

  /* row buttons + select taps */
  $('#apList').addEventListener('click', function (e) {
    var row = e.target.closest('.swipe');
    if (!row) { return; }
    if (state.selectMode) {
      var id = row.dataset.id;
      state.selected[id] = !state.selected[id];
      row.dataset.sel = state.selected[id] ? 1 : 0;
      updateBulk();
      return;
    }
    var ap = e.target.closest('[data-approve]');
    if (ap) { approveSheet([ap.dataset.approve], 'row'); return; }
    var rj = e.target.closest('[data-reject]');
    if (rj) { rejectSheet([rj.dataset.reject], 'row'); return; }
    openDetail(row.dataset.id);
  });

  /* --- approve / reject sheets --- */
  function approveSheet(ids, via) {
    var items = ids.map(findAp).filter(Boolean);
    var tot = items.reduce(function (s, a) { return s + a.amount; }, 0);
    var many = items.length > 1;
    openSheet({
      title: many ? 'Approve ' + items.length + ' items?' : 'Approve ' + fmt(items[0].amount, items[0].amount % 1 !== 0) + '?',
      sub: many
        ? fmt(tot) + ' total · posts to the ledger immediately on confirm'
        : items[0].who + ' · ' + items[0].desc,
      body: '<div class="kv-list">' + (many
        ? items.map(function (a) {
          return '<div class="kv"><span class="k truncate">' + esc(a.who) + ' · ' + esc(a.dt) + '</span><span class="v">' + fmt(a.amount, a.amount % 1 !== 0) + '</span></div>';
        }).join('')
        : [['Document type', items[0].dt], ['Cost centre', items[0].dept], ['SLA', items[0].sla],
          ['Exceptions', items[0].flag || 'None'], ['Posts to', 'Xero · straight-through']]
          .map(function (r) {
            return '<div class="kv"><span class="k">' + r[0] + '</span><span class="v">' + esc(r[1]) + '</span></div>';
          }).join('')) + '</div>' +
        (items.some(function (a) { return a.flag; })
          ? '<div class="banner warn">' + IC.warn + '<span><b>' + (many ? items.filter(function (a) { return a.flag; }).length + ' exceptions' : items[0].flag) +
          '.</b> Approving records your override in the audit trail.</span></div>'
          : '<div class="banner pos">' + IC.tick + '<span><b>All checks passed.</b> Straight-through posting, no override recorded.</span></div>') +
        '<div style="height:14px"></div>',
      foot: '<button class="btn sm sec" data-close style="flex:0 0 92px">Cancel</button>' +
        '<button class="btn sm pos" id="confirmAp" style="flex:1">' + (many ? 'Confirm ' + items.length + ' approvals' : 'Confirm approval') + '</button>',
      onMount: function (b, f) {
        $('#confirmAp', f).addEventListener('click', function () {
          if (!state.canApprove) {
            toast('Missing Approve privilege');
            return;
          }
          var btn = $('#confirmAp', f);
          btn.disabled = true;
          btn.textContent = 'Approving…';
          Promise.all(items.map(function (a) {
            return LLSession.approveInvoice(a.invoiceId || a.id);
          }))
            .then(function () {
              removeItems(ids);
              closeSheet();
              toast(many ? items.length + ' approved · ' + fmt(Math.round(tot)) : 'Approved ' + fmt(items[0].amount, items[0].amount % 1 !== 0) + ' · ' + items[0].who);
              if (state.screen === 'detail') { showScreen('approvals'); }
              if (via === 'bulk') { exitSelect(); }
              void loadLiveApprovals();
            })
            .catch(function (err) {
              btn.disabled = false;
              btn.textContent = many ? 'Confirm ' + items.length + ' approvals' : 'Confirm approval';
              toast((err && err.message) || 'Approve failed');
            });
        });
      }
    });
  }

  function rejectSheet(ids, via) {
    var items = ids.map(findAp).filter(Boolean);
    var many = items.length > 1;
    var reason = null;
    openSheet({
      title: many ? 'Reject ' + items.length + ' items?' : 'Reject ' + fmt(items[0].amount, items[0].amount % 1 !== 0) + '?',
      sub: 'Pick a reason — the requester is notified with it instantly.',
      body: '<div class="chip-bar" id="reasons" style="flex-wrap:wrap">' +
        QLL.rejectReasons.map(function (r) {
          return '<button class="fchip" data-r="' + esc(r) + '" aria-pressed="false">' + esc(r) + '</button>';
        }).join('') + '</div>' +
        '<div style="padding:0 16px 14px"><textarea class="comment" rows="2" placeholder="Add a note (optional)" style="margin:0;width:100%"></textarea></div>',
      foot: '<button class="btn sm sec" data-close style="flex:0 0 92px">Cancel</button>' +
        '<button class="btn sm danger" id="confirmRj" style="flex:1" disabled>Confirm rejection</button>',
      onMount: function (b, f) {
        b.addEventListener('click', function (e) {
          var c = e.target.closest('.fchip');
          if (!c) { return; }
          reason = c.dataset.r;
          $$('.fchip', b).forEach(function (x) { x.setAttribute('aria-pressed', String(x === c)); });
          $('#confirmRj', f).disabled = false;
          $('#confirmRj', f).textContent = 'Confirm — ' + reason;
        });
        $('#confirmRj', f).addEventListener('click', function () {
          if (!state.canReject) {
            toast('Missing Reject privilege');
            return;
          }
          var btn = $('#confirmRj', f);
          btn.disabled = true;
          btn.textContent = 'Rejecting…';
          Promise.all(items.map(function (a) {
            return LLSession.rejectInvoice(a.invoiceId || a.id);
          }))
            .then(function () {
              removeItems(ids);
              closeSheet();
              toast(many ? items.length + ' rejected · ' + reason : 'Rejected · ' + reason);
              if (state.screen === 'detail') { showScreen('approvals'); }
              if (via === 'bulk') { exitSelect(); }
              void loadLiveApprovals();
            })
            .catch(function (err) {
              btn.disabled = false;
              btn.textContent = reason ? ('Confirm — ' + reason) : 'Confirm rejection';
              toast((err && err.message) || 'Reject failed');
            });
        });
      }
    });
  }

  function removeItems(ids) {
    state.approvals = state.approvals.filter(function (a) { return ids.indexOf(a.id) === -1; });
    ids.forEach(function (id) { delete state.selected[id]; });
    renderApprovals();
  }

  /* --- filters + search --- */
  $('#apChips').addEventListener('click', function (e) {
    var c = e.target.closest('.fchip');
    if (!c) { return; }
    state.apFilter = (state.apFilter === c.dataset.f) ? 'all' : c.dataset.f;
    $$('#apChips .fchip').forEach(function (x) {
      x.setAttribute('aria-pressed', String(x.dataset.f === state.apFilter));
    });
    renderApprovals();
  });
  $('#apSearch').addEventListener('input', function () {
    state.apQuery = this.value;
    $('#apClear').hidden = !this.value;
    renderApprovals();
  });
  $('#apClear').addEventListener('click', function () {
    $('#apSearch').value = ''; state.apQuery = ''; this.hidden = true; renderApprovals();
  });

  /* --- multi-select / bulk --- */
  function enterSelectAll() {
    state.selectMode = true;
    state.selected = {};
    visibleApprovals().forEach(function (a) { state.selected[a.id] = true; });
    $('#selToggle').textContent = 'Select none';
    $('#selCancel').hidden = false;
    renderApprovals();
    syncPicker();
  }
  function exitSelect() {
    state.selectMode = false;
    state.selected = {};
    $('#selToggle').textContent = 'Select all';
    $('#selCancel').hidden = true;
    renderApprovals();
    syncPicker();
  }
  $('#selToggle').addEventListener('click', function () {
    if (state.selectMode && Object.keys(state.selected).length) {
      state.selected = {};
      $$('#apList .swipe').forEach(function (r) { r.dataset.sel = 0; });
      $('#selToggle').textContent = 'Select all';
      updateBulk();
    } else { enterSelectAll(); }
  });
  $('#selCancel').addEventListener('click', exitSelect);

  function selectedIds() {
    return Object.keys(state.selected).filter(function (k) { return state.selected[k]; });
  }
  function updateBulk() {
    var ids = selectedIds();
    var tot = ids.map(findAp).filter(Boolean).reduce(function (s, a) { return s + a.amount; }, 0);
    $('#bulkbar').classList.toggle('show', state.selectMode);
    $('#bulkN').textContent = ids.length + ' selected' + (ids.length ? ' · ' + fmt(Math.round(tot)) : '');
    $('#bulkApprove').textContent = 'Approve (' + ids.length + ')';
    $('#bulkApprove').disabled = !ids.length || !state.canApprove;
    $('#bulkApprove').style.display = state.canApprove ? '' : 'none';
    $('#bulkReject').disabled = !ids.length || !state.canReject;
    $('#bulkReject').style.display = state.canReject ? '' : 'none';
    if (state.selectMode) {
      $('#selToggle').textContent = ids.length ? 'Select none' : 'Select all';
    }
  }
  $('#bulkApprove').addEventListener('click', function () { approveSheet(selectedIds(), 'bulk'); });
  $('#bulkReject').addEventListener('click', function () { rejectSheet(selectedIds(), 'bulk'); });

  /* =========================================================
     APPROVAL DETAIL
     ========================================================= */
  function openDetail(id) {
    var a = findAp(id);
    if (!a) { return; }
    state.detailId = id;
    $('#dTitle').textContent = a.who;
    $('#detailBody').innerHTML =
      '<div class="hero">' +
      '<div class="amt-xl">' + fmt(a.amount, a.amount % 1 !== 0) + '</div>' +
      '<div class="who"><span class="av" style="width:24px;height:24px;font-size:10px">' + a.init + '</span>' +
      esc(a.who) + ' · ' + esc(a.dept) + '</div>' +
      '<div class="ai-meta" style="margin-top:10px">' +
      '<span class="chip dt">' + a.dt + '</span>' +
      '<span class="chip ' + (a.slaTone || '') + '">' + IC.clock + a.sla + '</span>' +
      (a.flag ? '<span class="chip ' + a.flagTone + '">' + esc(a.flag) + '</span>' : '') + '</div></div>' +

      '<div class="card"><div class="pad docprev">' +
      '<div class="big">' + IC.docLines + '<div class="l"></div><div class="l md"></div></div>' +
      '<div style="flex:1;min-width:0">' +
      '<div style="font-size:14.5px;letter-spacing:-.012em">' + esc(a.desc) + '</div>' +
      '<div style="font-size:12.5px;color:var(--ink-3);margin-top:3px">2 pages · 214 KB · AES-256</div>' +
      '<div style="margin-top:9px"><span class="chip acc">Open document</span></div>' +
      '</div>' + IC.chev + '</div></div>' +

      '<div class="sect-h">Control checks</div>' +
      '<div class="card">' + a.checks.map(function (c) {
        return '<div class="check"><span class="ic ' + c[0] + '">' + checkIcon(c[0]) + '</span>' +
          '<span style="flex:1;min-width:0"><span class="ct" style="display:block">' + esc(c[1]) + '</span>' +
          '<span class="cs" style="display:block">' + esc(c[2]) + '</span></span>' +
          (c[3] ? '<span class="cr chip ' + (c[0] === 'pos' ? 'pos' : c[0] === 'warn' ? 'warn' : 'neg') + '">' + esc(c[3]) + '</span>' : '') +
          '</div>';
      }).join('') + '</div>' +

      '<div class="sect-h">Approval chain</div>' +
      '<div class="card"><div class="chain">' + a.chain.map(function (s, i) {
        return '<div class="chain-step ' + s[2] + '"><span class="cd">' + (s[2] === 'done' ? '✓' : i + 1) + '</span>' +
          '<span><span class="cn" style="display:block">' + esc(s[0]) + '</span>' +
          '<span class="cm" style="display:block">' + esc(s[1]) + '</span></span></div>';
      }).join('') + '</div></div>' +

      '<div class="sect-h">Comment</div>' +
      '<textarea class="comment" rows="3" placeholder="Add a note for the requester and the audit trail"></textarea>' +
      '<div style="height:16px"></div>';
    var dAp = $('#dApprove');
    var dRj = $('#dReject');
    if (dAp) dAp.style.display = state.canApprove ? '' : 'none';
    if (dRj) dRj.style.display = state.canReject ? '' : 'none';
    showScreen('detail');
  }
  $('#dApprove').addEventListener('click', function () { approveSheet([state.detailId], 'detail'); });
  $('#dReject').addEventListener('click', function () { rejectSheet([state.detailId], 'detail'); });
  $('#dFiles').addEventListener('click', function () {
    showScreen('files');
  });

  /* =========================================================
     MY ITEMS (live Team Expenses claims/advances for this employee)
     ========================================================= */
  var myItemsLoading = false;

  function renderItems() {
    $$('#itemTabs button').forEach(function (b) { b.classList.toggle('active', b.dataset.t === state.itemTab); });
    var list = (QLL.myItems && QLL.myItems[state.itemTab]) || [];
    var host = $('#itemsList');
    if (!host) return;

    if (myItemsLoading && !list.length) {
      host.innerHTML =
        '<div class="empty" style="padding:24px;font-size:13px;color:var(--ink-3)">Loading your ' +
        esc(state.itemTab) + '…</div>';
      return;
    }

    if (!list.length) {
      host.innerHTML =
        '<div class="empty" style="padding:24px;font-size:13px;color:var(--ink-3)">' +
        (state.itemTab === 'advances'
          ? 'No advances linked to your employee email yet.'
          : state.itemTab === 'claims'
            ? 'No claims linked to your employee email yet. Capture a receipt to start.'
            : 'No other invoices linked to your login yet.') +
        '</div>';
      return;
    }

    var total = list.reduce(function (s, i) { return s + (Number(i.amt) || 0); }, 0);
    var label = state.itemTab.charAt(0).toUpperCase() + state.itemTab.slice(1);
    host.innerHTML =
      '<div class="sect-h">' + label +
      '<span class="r">' + list.length + ' · ' + fmt(Math.round(total)) + '</span></div>' +
      '<div class="rows" style="border-radius:0">' + list.map(function (i) {
        return '<button type="button" class="item-row" data-item-id="' + i.id + '" style="width:100%;text-align:left">' +
          '<span class="im">' +
          '<span style="display:flex;gap:8px;align-items:baseline"><span class="t truncate" style="font-size:15px;flex:1">' + esc(i.t) + '</span></span>' +
          '<span class="s truncate" style="display:block;font-size:12.5px;color:var(--ink-3);margin-top:2px">' + esc(i.s) + '</span>' +
          '<span class="bar" style="display:block;margin-top:9px;width:100%"><i class="' + esc(i.tone || '') + '" style="width:' + (i.prog || 0) + '%"></i></span>' +
          '</span>' +
          '<span class="ir"><span class="amt" style="font-size:16px;font-weight:650;display:block">' + fmt(i.amt, i.amt % 1 !== 0) + '</span>' +
          '<span class="chip ' + esc(i.chip[0] || '') + '" style="margin-top:7px">' + esc(i.chip[1] || '') + '</span></span>' +
          '</button>';
      }).join('') + '</div>' +
      '<p style="font-size:11.5px;color:var(--ink-3);padding:14px 20px 0;line-height:1.5">' +
      'Showing documents matched to your employee email in LedgerLink Team Expenses.' +
      '</p>';
  }

  async function loadMyItems() {
    if (!window.LLCaptureApi) return;
    myItemsLoading = true;
    renderItems();
    try {
      var results = await Promise.all([
        LLCaptureApi.listMyClaims(50),
        LLCaptureApi.listMyAdvances(50),
        LLCaptureApi.listMyOtherInvoices(50)
      ]);
      QLL.myItems.claims = results[0].map(LLCaptureApi.invoiceToMyItem);
      QLL.myItems.advances = results[1].map(LLCaptureApi.invoiceToMyItem);
      QLL.myItems.invoices = results[2].map(LLCaptureApi.invoiceToMyItem);
    } catch (err) {
      toast((err && err.message) || 'Could not load your items');
      QLL.myItems.claims = [];
      QLL.myItems.advances = [];
      QLL.myItems.invoices = [];
    } finally {
      myItemsLoading = false;
      renderItems();
    }
  }

  $('#itemTabs').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) { return; }
    state.itemTab = b.dataset.t;
    renderItems();
  });
  $('#itemsList').addEventListener('click', function (e) {
    var row = e.target.closest('[data-item-id]');
    if (!row) return;
    var id = Number(row.getAttribute('data-item-id'));
    if (!id || !window.LLCapture || !LLCapture.openReviewForId) return;
    toast('Opening…');
    LLCapture.openReviewForId(id, { fromHome: true, sourceLabel: 'My items' }).catch(function (err) {
      toast((err && err.message) || 'Could not open document');
    });
  });

  /* =========================================================
     FILES
     ========================================================= */
  function renderFileChips() {
    $('#fChips').innerHTML = QLL.fileFilters.map(function (f) {
      return '<button class="fchip" data-f="' + esc(f) + '" aria-pressed="' + (state.fileFilter === f) + '">' + esc(f) + '</button>';
    }).join('');
  }
  function visibleFiles() {
    var q = state.fileQuery.trim().toLowerCase();
    return QLL.files.filter(function (f) {
      var ff = state.fileFilter;
      if (ff === 'Mine' && !f.mine) { return false; }
      if (ff === 'Invoices' && f.type !== 'Invoice') { return false; }
      if (ff === 'Receipts' && f.type !== 'Receipt') { return false; }
      if (ff === 'Contracts' && f.type !== 'Contract') { return false; }
      if (ff === 'Claims' && f.type !== 'Claim') { return false; }
      if (ff === 'This month' && f.date.indexOf('Sep 2026') === -1) { return false; }
      if (!q) { return true; }
      return (f.n + ' ' + f.vendor + ' ' + f.dt + ' ' + f.type).toLowerCase().indexOf(q) > -1;
    });
  }
  function renderFiles() {
    var list = visibleFiles();
    var host = $('#fList');
    host.className = state.fileView === 'grid' ? 'grid' : 'list';
    $('#fResults').textContent = list.length + ' of ' + QLL.files.length + ' recent documents' +
      (state.fileFilter ? ' · ' + state.fileFilter : '') + (state.fileQuery ? ' · “' + state.fileQuery + '”' : '');
    if (!list.length) {
      host.className = '';
      host.innerHTML = '<div class="empty">' +
        '<svg width="30" height="30" viewBox="0 0 30 30" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="13" cy="13" r="8.6"/><path d="M19.4 19.4 26 26"/></svg>' +
        '<div>Nothing in the vault matches.<br>Try a vendor name or a DT code.</div></div>';
      return;
    }
    host.innerHTML = list.map(function (f, i) {
      return '<button class="doc" data-file="' + i + '">' +
        '<span class="doc-th" style="display:block">' + IC.docLines +
        '<span class="dtc chip dt">' + f.dt + '</span></span>' +
        '<span class="doc-b" style="display:block">' +
        '<span class="dn" style="display:block">' + esc(f.n) + '</span>' +
        '<span class="dm" style="display:block">' + esc(f.date) + ' · ' + esc(f.size) + '</span>' +
        '<span class="db">' +
        '<span class="tag">' + IC.lock + ' ' + f.enc + '</span>' +
        '<span class="tag">' + IC.clock + ' ' + f.ret + '</span>' +
        (f.mine ? '<span class="tag" style="color:var(--accent)">Mine</span>' : '') +
        '</span></span></button>';
    }).join('');
  }
  $('#fChips').addEventListener('click', function (e) {
    var c = e.target.closest('.fchip');
    if (!c) { return; }
    state.fileFilter = state.fileFilter === c.dataset.f ? null : c.dataset.f;
    $$('#fChips .fchip').forEach(function (x) {
      x.setAttribute('aria-pressed', String(x.dataset.f === state.fileFilter));
    });
    renderFiles();
  });
  $('#fSearch').addEventListener('input', function () {
    state.fileQuery = this.value;
    $('#fClear').hidden = !this.value;
    renderFiles();
  });
  $('#fClear').addEventListener('click', function () {
    $('#fSearch').value = ''; state.fileQuery = ''; this.hidden = true; renderFiles();
  });
  $('#viewToggle').addEventListener('click', function () {
    state.fileView = state.fileView === 'grid' ? 'list' : 'grid';
    this.setAttribute('aria-label', state.fileView === 'grid' ? 'Switch to list view' : 'Switch to grid view');
    this.innerHTML = state.fileView === 'grid'
      ? '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M3 5h14M3 10h14M3 15h14"/></svg>'
      : '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="3" width="6" height="6" rx="1.4"/><rect x="11" y="3" width="6" height="6" rx="1.4"/><rect x="3" y="11" width="6" height="6" rx="1.4"/><rect x="11" y="11" width="6" height="6" rx="1.4"/></svg>';
    renderFiles();
    syncPicker();
  });
  $('#fList').addEventListener('click', function (e) {
    var b = e.target.closest('[data-file]');
    if (!b) { return; }
    var f = visibleFiles()[Number(b.dataset.file)];
    openSheet({
      title: f.n,
      sub: f.dt + ' · ' + f.type + ' · ' + f.date,
      body: '<div style="display:flex;gap:14px;padding:2px 20px 12px">' +
        '<div class="thumb" style="width:70px;height:92px">' + IC.docLines + '</div>' +
        '<div class="kv-list" style="flex:1;padding:0">' +
        '<div class="kv"><span class="k">Vendor</span><span class="v">' + esc(f.vendor) + '</span></div>' +
        '<div class="kv"><span class="k">Encryption</span><span class="v">' + f.enc + ' at rest</span></div>' +
        '<div class="kv"><span class="k">Retention</span><span class="v">' + f.ret + ' · ATO</span></div>' +
        '<div class="kv"><span class="k">Size</span><span class="v">' + f.size + '</span></div>' +
        '</div></div>' +
        '<div class="sect-h tight">Share</div>' +
        '<div class="chip-bar" style="flex-wrap:wrap">' +
        ['Copy secure link', 'Email to approver', 'Attach to claim', 'Download PDF'].map(function (s) {
          return '<button class="fchip" data-share="' + s + '">' + s + '</button>';
        }).join('') + '</div>' +
        '<p style="font-size:11.5px;color:var(--ink-3);padding:2px 20px 12px;line-height:1.5">' +
        'Links expire in 24 h and are logged against your user ID in the immutable audit trail.</p>',
      foot: '<button class="btn sm sec" data-close style="flex:0 0 92px">Close</button>' +
        '<button class="btn sm" id="openDoc" style="flex:1">Open document</button>',
      onMount: function (b2, f2) {
        b2.addEventListener('click', function (e2) {
          var s = e2.target.closest('[data-share]');
          if (s) { closeSheet(); toast(s.dataset.share + ' · logged'); }
        });
        $('#openDoc', f2).addEventListener('click', function () { closeSheet(); toast('Opening ' + f.dt + ' viewer'); });
      }
    });
  });

  /* =========================================================
     PROFILE
     ========================================================= */
  $$('.sw').forEach(function (sw) {
    sw.addEventListener('click', function () {
      var on = sw.getAttribute('aria-pressed') !== 'true';
      sw.setAttribute('aria-pressed', String(on));
      sw.setAttribute('aria-checked', String(on));
      if (sw.id === 'swDelegate') {
        $('#delSub').textContent = on ? 'On · Aisha Karim is approving for you' : 'Off · queue stays with you';
        toast(on ? 'Approvals delegated to Aisha Karim' : 'Delegation off');
      }
    });
  });
  $('#delegateTo').addEventListener('click', function () {
    openSheet({
      title: 'Delegate to',
      sub: 'Delegation is logged and expires at the end of the quarter.',
      body: '<div class="rows" style="border:0">' +
        ['Aisha Karim · Sales', 'Daniel Okafor · Operations', 'Mei Lin Tan · Logistics', 'Sofia Almeida · Corporate']
          .map(function (n, i) {
            return '<button class="row" data-del="' + esc(n) + '"><span class="av">' + n.split(' ').map(function (w) { return w[0]; }).slice(0, 2).join('') +
              '</span><span class="main"><span class="t" style="display:block">' + esc(n.split(' · ')[0]) + '</span>' +
              '<span class="s" style="display:block">' + esc(n.split(' · ')[1]) + '</span></span>' +
              (i === 0 ? '<span class="chip acc">Current</span>' : '') + '</button>';
          }).join('') + '</div>',
      onMount: function (b) {
        b.addEventListener('click', function (e) {
          var d = e.target.closest('[data-del]');
          if (!d) { return; }
          $('#delTo').textContent = d.dataset.del;
          closeSheet();
          toast('Delegate set · ' + d.dataset.del.split(' · ')[0]);
        });
      }
    });
  });
  $('#entityRow').addEventListener('click', function () {
    var entities = QLL.entities || [];
    if (entities.length <= 1) {
      toast('Only one organisation on this account');
      return;
    }
    openSheet({
      title: 'Switch organisation',
      sub: 'Approval limits and budgets follow the organisation you select.',
      body: '<div class="rows" style="border:0">' + entities.map(function (ent) {
        var id = typeof ent === 'string' ? ent : ent.id;
        var label = typeof ent === 'string' ? ent : (ent.name || ent.id);
        var sub = typeof ent === 'string'
          ? ''
          : [ent.slug, LLSession.formatRole(ent.role)].filter(Boolean).join(' · ');
        var current = typeof ent === 'object' && ent.current;
        return '<button class="row" data-ent-id="' + esc(String(id)) + '"><span class="main"><span class="t" style="display:block">' +
          esc(label) + '</span>' +
          (sub ? '<span class="s" style="display:block">' + esc(sub) + '</span>' : '') +
          '</span>' +
          (current ? '<span style="color:var(--accent)">' + IC.tick + '</span>' : IC.chev) +
          '</button>';
      }).join('') + '</div>',
      onMount: function (b) {
        b.addEventListener('click', function (e) {
          var d = e.target.closest('[data-ent-id]');
          if (!d) { return; }
          var tid = d.dataset.entId;
          var cur = LLSession.getUser();
          if (cur && String(cur.tenant_id) === String(tid)) {
            closeSheet();
            toast('Already on this organisation');
            return;
          }
          closeSheet();
          toast('Switching organisation…');
          LLSession.switchTenant(tid).catch(function (err) {
            toast(err && err.message ? err.message : 'Could not switch organisation');
          });
        });
      }
    });
  });
  $('#signOut').addEventListener('click', function () {
    toast('Signing out…');
    LLSession.logout();
  });

  /* close buttons inside sheets */
  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-close]')) { closeSheet(); }
  });

  /* =========================================================
     DEEP LINKS + APPEARANCE
     ========================================================= */
  var SCREEN_BOOT = {
    home: function () { setRole('employee'); showScreen('home'); },
    'home-approver': function () { setRole('approver'); showScreen('home'); },
    capture: function () { closeSheet(); showScreen('capture'); },
    approvals: function () { if (state.selectMode) { exitSelect(); } closeSheet(); showScreen('approvals'); },
    detail: function () { closeSheet(); openDetail(state.approvals[0] && state.approvals[0].id); },
    items: function () { closeSheet(); state.itemTab = 'claims'; renderItems(); showScreen('items'); },
    'items-advances': function () { closeSheet(); state.itemTab = 'advances'; renderItems(); showScreen('items'); },
    files: function () { closeSheet(); setFileView('grid'); showScreen('files'); },
    'files-list': function () { closeSheet(); setFileView('list'); showScreen('files'); },
    profile: function () { closeSheet(); showScreen('profile'); }
  };
  function setRole(r) {
    state.role = r;
    syncRoleChrome();
  }
  function setFileView(v) {
    if (state.fileView !== v) { $('#viewToggle').click(); }
  }

  /* appearance lives on Profile; persists across reloads */
  var APPEAR_KEY = 'qll_mobile_appearance';
  function syncAppearButtons(mode) {
    $$('#profileAppearSeg button').forEach(function (x) {
      x.classList.toggle('active', (x.dataset.appear || '') === mode);
    });
  }
  function applyAppearance(mode) {
    var token = (mode === 'light' || mode === 'dark') ? mode : 'auto';
    if (token === 'auto') {
      document.documentElement.removeAttribute('data-appearance');
    } else {
      document.documentElement.setAttribute('data-appearance', token);
    }
    try { localStorage.setItem(APPEAR_KEY, token); } catch (e) { /* ignore */ }
    syncAppearButtons(token);
  }
  function onAppearClick(e) {
    var b = e.target.closest('button[data-appear]');
    if (!b) { return; }
    applyAppearance(b.dataset.appear);
  }
  var appearProfile = $('#profileAppearSeg');
  if (appearProfile) { appearProfile.addEventListener('click', onAppearClick); }
  (function restoreAppearance() {
    var saved = 'auto';
    try { saved = localStorage.getItem(APPEAR_KEY) || 'auto'; } catch (e) { /* ignore */ }
    applyAppearance(saved);
  })();

  /* =========================================================
     BOOT
     ========================================================= */
  function bootUi() {
    renderHome();
    renderApprovals();
    renderItems();
    renderFileChips();
    renderFiles();
    updateBulk();

    // deep link: ?screen=files
    var q = new URLSearchParams(location.search).get('screen');
    if (q && SCREEN_BOOT[q]) { SCREEN_BOOT[q](); }
  }

  (function boot() {
    var cached = LLSession.getUser();
    if (!LLSession.getAccessToken() || !cached) {
      location.replace(LLSession.loginUrl());
      return;
    }
    applyIdentity(cached);
    bootUi();
    LLSession.refreshMe()
      .then(function (me) {
        if (me) {
          applyIdentity(me);
          renderHome();
          renderItems();
        }
        return LLSession.fetchPermissions();
      })
      .then(function (perms) {
        applyPrivileges(perms);
        return Promise.all([loadLiveApprovals(), loadMyItems(), loadHomeFinance()]);
      })
      .catch(function (err) {
        if (err && err.status === 401) {
          LLSession.clearSession();
          location.replace(LLSession.loginUrl());
          return;
        }
        // Permissions failed — treat as employee (capture only)
        applyPrivileges({ permissions: {} });
        renderApprovals();
      });
  })();
})();
