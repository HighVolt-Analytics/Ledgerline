/* Quantum Ledger Link — mobile prototype behaviour
   Vanilla JS, no build step. Pointer events so swipe works with touch AND mouse. */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ---------------- formatting ---------------- */
  function tenantCurrency() {
    return String(state.tenantCurrency || state.currency || 'AUD').trim().toUpperCase() || 'AUD';
  }

  function fmt(n, forceCents, currency) {
    var num = Number(n);
    if (!isFinite(num)) num = 0;
    var cents = forceCents || Math.abs(num % 1) > 0.001;
    var code = String(currency || tenantCurrency()).trim().toUpperCase() || 'AUD';
    try {
      return new Intl.NumberFormat('en-AU', {
        style: 'currency',
        currency: code,
        minimumFractionDigits: cents ? 2 : 0,
        maximumFractionDigits: cents ? 2 : 0
      }).format(num);
    } catch (e) {
      return code + ' ' + num.toLocaleString('en-AU', {
        minimumFractionDigits: cents ? 2 : 0,
        maximumFractionDigits: cents ? 2 : 0
      });
    }
  }

  /** Books / GL / budget / advance float — always tenant currency. */
  function fmtTenant(n, forceCents) {
    return fmt(n, forceCents, tenantCurrency());
  }

  /** Document amounts — invoice currency, fallback tenant. */
  function fmtDoc(n, forceCents, currency) {
    var code = String(currency || '').trim().toUpperCase();
    return fmt(n, forceCents, code || tenantCurrency());
  }

  /** Sum list amounts; use one currency only when all rows share it. */
  function fmtListTotal(list, forceCents) {
    var rows = Array.isArray(list) ? list : [];
    var total = rows.reduce(function (s, i) {
      return s + (Number(i && (i.amt != null ? i.amt : i.amount)) || 0);
    }, 0);
    var codes = {};
    rows.forEach(function (i) {
      var c = String((i && i.currency) || '').trim().toUpperCase();
      if (c) codes[c] = 1;
    });
    var keys = Object.keys(codes);
    if (keys.length === 1) return fmtDoc(total, forceCents, keys[0]);
    if (!keys.length) return fmtTenant(total, forceCents);
    return String(Math.round(total));
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function shortDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' });
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
    tenantRole: '',
    matrixRole: '',
    canApprove: false,
    canReject: false,
    hasEmployeeProfile: false,
    dualRole: false,
    approvals: [],
    selectMode: false,
    selected: {},
    apFilter: 'all',
    apQuery: '',
    itemTab: 'all',
    fileFilter: null,
    fileQuery: '',
    fileView: 'grid',
    detailId: null,
    /** Tenant books currency (budget, advances). Loaded from institution settings. */
    tenantCurrency: 'AUD',
    /** Alias kept for older call sites — always mirrors tenantCurrency. */
    currency: 'AUD',
    receiptsAttached: false,
    edited: {},
    mobileQaItems: [],
    mobileQaExtras: [],
    documentTypes: [],
    employeeProfile: null,
    profilePrefs: {
      delegateOn: false,
      delegateTo: '',
      autoApproveUnder250: true,
      slaAlerts: true,
      dailyDigest: true,
      budgetThreshold: false
    }
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

  function applyIdentity(user) {
    if (!user) {
      location.replace(LLSession.loginUrl());
      return false;
    }

    var name = String(user.full_name || user.email || 'User').trim();
    var roleLabel = LLSession.formatRole(user.role);
    var memberships = LLSession.getMemberships();
    var tenantName = String(user.tenant_name || '').trim();
    state.tenantRole = String(user.role || '').trim().toLowerCase();

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
    if (greet) greet.textContent = isApprover ? 'Approver view' : employeeGreeting();

    syncTabBarForRole();
    applyMobileQuickActions();

    if (!isApprover && (state.screen === 'approvals' || state.screen === 'detail')) {
      showScreen('home');
    }
    if (isApprover && state.screen === 'items') {
      showScreen('home');
    }
  }

  /** Employee: Home · My items · Capture · History · Analysis
      Approver: Home · Approvals · Capture · History · Analysis */
  function syncTabBarForRole() {
    var isApprover = state.role === 'approver';
    var empOrder = { home: 1, items: 2, capture: 3, history: 4, files: 5 };
    var apprOrder = { home: 1, approvals: 2, capture: 3, history: 4, files: 5 };
    var order = isApprover ? apprOrder : empOrder;
    $$('.tabbar .tab').forEach(function (t) {
      var key = t.dataset.tab;
      var show = true;
      if (key === 'approvals') show = isApprover;
      else if (key === 'items') show = !isApprover;
      else if (key === 'history') show = true;
      t.style.display = show ? '' : 'none';
      if (order[key] != null) t.style.order = String(order[key]);
    });
  }

  function applyMobileQuickActions() {
    var items = Array.isArray(state.mobileQaItems) ? state.mobileQaItems : [];
    var isApprover = state.role === 'approver';
    var visible = 0;
    var grid = $('#qaGrid');

    $$('[data-role-panel="employee"] [data-qa-dt="1"]').forEach(function (btn) {
      if (btn.parentNode) btn.parentNode.removeChild(btn);
    });

    var approvalsBtn = document.querySelector(
      '[data-role-panel="employee"] .qa[data-qa="approvals"]'
    );
    if (approvalsBtn) {
      approvalsBtn.style.display = isApprover ? '' : 'none';
      if (isApprover) visible += 1;
    }

    if (grid) {
      items.forEach(function (item) {
        if (!item || !item.documentTypeCode) return;
        var label = item.label || item.shortTitle || item.title || item.documentTypeCode;
        var kind = String(item.teamExpenseKind || 'expense_claim').toLowerCase() || 'expense_claim';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'qa';
        btn.setAttribute('data-qa-dt', '1');
        btn.setAttribute('data-dt-code', item.documentTypeCode);
        btn.setAttribute('data-dt-kind', kind);
        btn.innerHTML =
          '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h8.5L19 7.5V21H6z"/><path d="M14 3v5h5M9 12.5h6M9 16h4"/></svg>' +
          esc(label);
        btn.addEventListener('click', function () {
          openDocumentTypeQuickAction(item);
        });
        if (approvalsBtn && approvalsBtn.parentNode === grid) {
          grid.insertBefore(btn, approvalsBtn);
        } else {
          grid.appendChild(btn);
        }
        visible += 1;
      });
    }

    var sect = $('#qaSectH');
    if (sect) sect.style.display = visible ? '' : 'none';
    if (grid) grid.style.display = visible ? '' : 'none';

    if (window.LLCapture && LLCapture.setCaptureRoutesFromQuickActions) {
      LLCapture.setCaptureRoutesFromQuickActions(items);
    }
    syncMyItemTabsFromQuickActions();
  }

  function myItemTabKey(item) {
    return 'dt:' + String(item.documentTypeCode || '').trim().toUpperCase();
  }

  function myItemChipIcon(kind) {
    var k = String(kind || '').toLowerCase();
    if (k === 'advance_requisition') {
      return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8.2"/><path d="M12 8v8M9.5 10.5h5M9.5 13.5h5"/></svg>';
    }
    if (k === 'vendor_invoice') {
      return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7.2A2 2 0 0 1 6 5.2h3.3l1.9 2.2h7.8a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/></svg>';
    }
    return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h8.5L19 7.5V21H6z"/><path d="M14 3v5h5M9 12.5h6M9 16h4"/></svg>';
  }

  var CHIP_CHECK =
    '<svg class="chip-check" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.2 8.2l3.2 3.2 6.4-6.8"/></svg>';

  function countItemsForDt(code) {
    var want = String(code || '').toUpperCase();
    var all = (QLL.myItems && QLL.myItems.all) || [];
    var n = 0;
    for (var i = 0; i < all.length; i++) {
      if (String((all[i] && all[i].dt) || '').toUpperCase() === want) n += 1;
    }
    return n;
  }

  function syncMyItemTabsFromQuickActions() {
    var host = $('#itemTabs');
    var wrap = document.querySelector('.item-filter');
    if (!host) return;
    var items = (state.mobileQaItems || []).filter(function (item) {
      return item && item.enabled !== false && item.documentTypeCode;
    });

    host.innerHTML = '';
    if (!items.length) {
      host.hidden = true;
      if (wrap) wrap.hidden = true;
      state.itemTab = 'all';
      renderItems();
      return;
    }

    host.hidden = false;
    if (wrap) wrap.hidden = false;
    var valid = {};
    items.forEach(function (item) {
      var key = myItemTabKey(item);
      valid[key] = true;
      var label =
        item.label || item.shortTitle || item.title || item.documentTypeCode;
      var count = countItemsForDt(item.documentTypeCode);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'fchip';
      btn.setAttribute('data-t', key);
      btn.setAttribute('data-dt', item.documentTypeCode);
      btn.setAttribute('aria-pressed', 'false');
      btn.setAttribute('aria-label', 'Show ' + label);
      btn.innerHTML =
        CHIP_CHECK +
        myItemChipIcon(item.teamExpenseKind) +
        '<span>' + esc(label) + '</span>' +
        '<span class="chip-count">' + count + '</span>';
      host.appendChild(btn);
    });

    if (!valid[state.itemTab]) {
      state.itemTab = myItemTabKey(items[0]);
    }
    syncMyItemChipPressed(false);
    renderItems();
  }

  function scrollChipIntoBar(host, chip) {
    if (!host || !chip) return;
    try {
      var left = chip.offsetLeft - (host.clientWidth - chip.offsetWidth) / 2;
      host.scrollTo({
        left: Math.max(0, left),
        behavior: 'smooth'
      });
    } catch (e) {
      try {
        host.scrollLeft = Math.max(
          0,
          chip.offsetLeft - (host.clientWidth - chip.offsetWidth) / 2
        );
      } catch (e2) { /* ignore */ }
    }
  }

  function resetShellScroll() {
    try {
      window.scrollTo(0, 0);
      if (document.documentElement) document.documentElement.scrollLeft = 0;
      if (document.body) document.body.scrollLeft = 0;
      var stage = document.querySelector('.stage');
      if (stage) stage.scrollLeft = 0;
      var viewer = document.querySelector('.viewer');
      if (viewer) viewer.scrollLeft = 0;
    } catch (e) { /* ignore */ }
  }

  function syncMyItemChipPressed(scroll) {
    var host = $('#itemTabs');
    $$('#itemTabs .fchip').forEach(function (b) {
      var on = b.dataset.t === state.itemTab;
      b.setAttribute('aria-pressed', String(on));
      if (on && scroll !== false) {
        scrollChipIntoBar(host, b);
        resetShellScroll();
      }
    });
  }

  function refreshMyItemChipCounts() {
    $$('#itemTabs .fchip').forEach(function (b) {
      var countEl = b.querySelector('.chip-count');
      if (!countEl) return;
      countEl.textContent = String(countItemsForDt(b.getAttribute('data-dt')));
    });
  }

  function itemsForCurrentTab() {
    var all = (QLL.myItems && QLL.myItems.all) || [];
    var tab = String(state.itemTab || '');
    if (tab.indexOf('dt:') === 0) {
      var code = tab.slice(3).toUpperCase();
      return all.filter(function (row) {
        return String((row && row.dt) || '').toUpperCase() === code;
      });
    }
    if (tab === 'all') return all;
    return (QLL.myItems && QLL.myItems[tab]) || [];
  }

  function currentItemTabLabel() {
    var active = document.querySelector('#itemTabs .fchip[aria-pressed="true"] span');
    if (active && active.textContent) return active.textContent.trim();
    var tab = String(state.itemTab || '');
    if (tab.indexOf('dt:') === 0) return tab.slice(3);
    if (!tab || tab === 'all') return 'Items';
    return tab.charAt(0).toUpperCase() + tab.slice(1);
  }

  function normalizeQaItem(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var code = String(raw.documentTypeCode || raw.document_type_code || '').trim().toUpperCase();
    if (!code) return null;
    var allowWith = raw.allowWithDoc != null ? !!raw.allowWithDoc : (raw.allow_with_doc != null ? !!raw.allow_with_doc : true);
    var allowWithout = raw.allowWithoutDoc != null ? !!raw.allowWithoutDoc : (raw.allow_without_doc != null ? !!raw.allow_without_doc : true);
    if (!allowWith && !allowWithout) allowWith = true;
    var photo = String(raw.photoRequired || raw.photo_required || 'optional');
    if (photo !== 'compulsory' && photo !== 'optional' && photo !== 'none') photo = 'optional';
    return {
      id: String(raw.id || code),
      documentTypeCode: code,
      label: String(raw.label || '').trim(),
      enabled: raw.enabled == null ? true : !!raw.enabled,
      allowWithDoc: allowWith,
      allowWithoutDoc: allowWithout,
      photoRequired: photo,
      fields: raw.fields || null,
      teamExpenseKind: String(raw.teamExpenseKind || '').toLowerCase(),
      shortTitle: String(raw.shortTitle || '').trim(),
      title: String(raw.title || '').trim()
    };
  }

  function intentFromDocumentTypeKind(kind) {
    var k = String(kind || '').trim().toLowerCase();
    if (k === 'direct_payment') return 'expense_claim';
    if (k === 'advance_requisition' || k === 'expense_claim' || k === 'vendor_invoice') return k;
    return k || 'expense_claim';
  }

  function openDocumentTypeQuickAction(item) {
    var code = String((item && item.documentTypeCode) || '').trim().toUpperCase();
    var intent = intentFromDocumentTypeKind(item && item.teamExpenseKind);
    var title =
      String((item && (item.label || item.shortTitle || item.title)) || '').trim() || code || 'Quick action';
    var qaCfg = {
      enabled: true,
      allowWithDoc: item.allowWithDoc !== false,
      allowWithoutDoc: item.allowWithoutDoc !== false,
      photoRequired: item.photoRequired || 'optional',
      documentTypeCode: code,
      fields: item.fields || null
    };
    var allowWith = qaCfg.allowWithDoc !== false;
    var allowWithout = qaCfg.allowWithoutDoc !== false;
    if (!allowWith && !allowWithout) allowWith = true;

    function startWithDoc() {
      if (window.LLCapture && LLCapture.startQuickActionWithDoc) {
        LLCapture.startQuickActionWithDoc({
          documentTypeCode: code,
          intent: intent,
          title: title,
          qaConfig: qaCfg
        });
      }
    }

    function startWithoutDoc() {
      if (window.LLCapture && LLCapture.startQuickActionWithoutDoc) {
        LLCapture.startQuickActionWithoutDoc({
          documentTypeCode: code,
          intent: intent,
          title: title,
          qaConfig: qaCfg
        });
      }
    }

    // Path choice comes only from institution Mobile Quick Action settings.
    if (allowWith && !allowWithout) {
      startWithDoc();
      return;
    }
    if (!allowWith && allowWithout) {
      startWithoutDoc();
      return;
    }

    // Defer sheet so the Quick Action tap cannot land on "With document".
    setTimeout(function () {
      openSheet({
        title: title,
        sub: 'Choose how you want to submit.',
        body:
          '<div class="rows" style="border:0">' +
          '<button type="button" class="row" id="qaPathWithDoc">' +
          '<span class="main"><span class="t" style="display:block">With document</span>' +
          '<span class="s" style="display:block">Photo → Details → Submit</span></span>' +
          IC.chev +
          '</button>' +
          '<button type="button" class="row" id="qaPathWithoutDoc">' +
          '<span class="main"><span class="t" style="display:block">Without document</span>' +
          '<span class="s" style="display:block">Details → Submit</span></span>' +
          IC.chev +
          '</button></div>',
        onMount: function (b) {
          var withBtn = $('#qaPathWithDoc', b);
          var withoutBtn = $('#qaPathWithoutDoc', b);
          if (withBtn) {
            withBtn.addEventListener('click', function (ev) {
              if (ev) {
                ev.preventDefault();
                ev.stopPropagation();
              }
              closeSheet();
              setTimeout(startWithDoc, 0);
            });
          }
          if (withoutBtn) {
            withoutBtn.addEventListener('click', function (ev) {
              if (ev) {
                ev.preventDefault();
                ev.stopPropagation();
              }
              closeSheet();
              setTimeout(startWithoutDoc, 0);
            });
          }
        }
      });
    }, 40);
  }

  function canActAsApprover() {
    return !!(state.canApprove || state.canReject);
  }

  /** Team membership role is employee (not admin/manager with Approve). */
  function isEmployeeTenantRole() {
    var r = String(state.tenantRole || '').toLowerCase();
    var m = String(state.matrixRole || '').toLowerCase();
    return r === 'employee' || m === 'employee';
  }

  /** Show Employee | Approver toggle only when both roles apply. */
  function syncRoleSegVisibility() {
    var approver = canActAsApprover();
    var dual = approver && !!state.hasEmployeeProfile;
    state.dualRole = dual;
    var roleSeg = $('#roleSeg');
    if (roleSeg) roleSeg.hidden = !dual;
    if (!dual) {
      // Pure employees stay on employee chrome even if a custom matrix grants Approve.
      state.role = approver && !isEmployeeTenantRole() ? 'approver' : 'employee';
    } else if (state.role !== 'employee' && state.role !== 'approver') {
      // Dual-role default: employee invite path prefers capture; admins prefer approvals.
      state.role = isEmployeeTenantRole() ? 'employee' : 'approver';
    }
    syncRoleChrome();
  }

  function applyPrivileges(perms) {
    var bag = (perms && perms.permissions) || {};
    state.canApprove = !!bag.Approve;
    state.canReject = !!bag.Reject;
    if (perms && perms.role) {
      state.tenantRole = String(perms.role).trim().toLowerCase();
    }
    if (perms && perms.matrix_role) {
      state.matrixRole = String(perms.matrix_role).trim().toLowerCase();
    }
    var mqa = perms && perms.mobile_quick_actions;
    var rawItems = mqa && Array.isArray(mqa.items) ? mqa.items : [];
    state.mobileQaItems = rawItems.map(normalizeQaItem).filter(function (item) {
      return item && item.enabled !== false;
    });
    syncRoleSegVisibility();
    return enrichMobileQuickActions();
  }

  function kindLabel(kind) {
    var k = String(kind || '').trim().toLowerCase();
    if (k === 'expense_claim') return 'Claim';
    if (k === 'advance_requisition') return 'Advance';
    if (k === 'direct_payment') return 'Direct payment';
    if (k === 'vendor_invoice') return 'Vendor';
    return '';
  }

  /** Keep in sync with frontend/src/lib/teamExpenseKind.ts */
  function inferTeamExpenseKindFromLabels() {
    var parts = [];
    for (var i = 0; i < arguments.length; i++) {
      var s = String(arguments[i] == null ? '' : arguments[i]).trim().toLowerCase();
      if (s) parts.push(s);
    }
    var blob = parts.join(' ').trim();
    if (!blob) return '';
    if (blob.indexOf('expense against advance') >= 0) return 'expense_claim';
    if (blob.indexOf('expense claim') >= 0 || blob.indexOf('reimbursement') >= 0) {
      return 'expense_claim';
    }
    if (blob.indexOf('advance requisition') >= 0 || blob.indexOf('advance request') >= 0) {
      return 'advance_requisition';
    }
    if (blob.indexOf('employee advance') >= 0 && blob.indexOf('expense') < 0) {
      return 'advance_requisition';
    }
    if (blob.indexOf('payment voucher') >= 0 || blob.indexOf('direct payment') >= 0) {
      return 'direct_payment';
    }
    return '';
  }

  function canonicalApprovalKind(raw) {
    var k = String(raw || '').trim().toLowerCase();
    if (k === 'expense_against_advance') return 'expense_claim';
    if (kindLabel(k)) return k;
    return '';
  }

  /** Alias used by filter / list matching. */
  function normalizeApprovalKind(raw) {
    return canonicalApprovalKind(raw);
  }

  function resolveDocumentTypeKind(dt) {
    if (!dt) return '';
    var inferred = inferTeamExpenseKindFromLabels(dt.title, dt.shortTitle);
    var pinned = canonicalApprovalKind(dt.teamExpenseKind);
    if (inferred) {
      if (pinned && pinned !== inferred) return inferred;
      return pinned || inferred;
    }
    return pinned;
  }

  function findDocumentTypeByCode(code) {
    var needle = String(code || '').trim().toUpperCase();
    if (!needle) return null;
    var rows = state.documentTypes || [];
    for (var i = 0; i < rows.length; i++) {
      if (String(rows[i].code || '').toUpperCase() === needle) return rows[i];
    }
    return null;
  }

  function resolveInvoiceKind(inv) {
    if (!inv || typeof inv !== 'object') return '';
    var kind = canonicalApprovalKind(inv.team_expense_kind || inv.teamExpenseKind);
    var dtCode = String(inv.document_type_code || inv.purchase_document_type || '').trim();
    var match = findDocumentTypeByCode(dtCode);
    if (!kind && match) kind = resolveDocumentTypeKind(match);
    if (!kind) {
      kind = inferTeamExpenseKindFromLabels(
        inv.document_heading,
        match && match.title,
        match && match.shortTitle,
        dtCode
      );
    }
    return kind || '';
  }

  /** Chips for Approvals: classified document types present in this approver's queue. */
  function approvalFilterDocumentTypes() {
    var seen = {};
    var list = [];
    (state.approvals || []).forEach(function (a) {
      var code = String((a && a.dt) || '').trim().toUpperCase();
      if (!code || code === '—' || seen[code]) return;
      seen[code] = true;
      var match = findDocumentTypeByCode(code);
      var label =
        String((match && (match.shortTitle || match.title)) || '').trim() ||
        String((a && a.heading) || '').trim() ||
        code;
      list.push({ code: code, label: label });
    });
    list.sort(function (x, y) {
      return String(x.label).localeCompare(String(y.label));
    });
    return list;
  }

  function renderApprovalFilterChips() {
    var host = $('#apChips');
    if (!host) return;
    var dts = approvalFilterDocumentTypes();
    var codes = dts.map(function (row) { return row.code; });
    if (state.apFilter !== 'all' && codes.indexOf(String(state.apFilter).toUpperCase()) === -1) {
      state.apFilter = 'all';
    }
    var html =
      '<button type="button" class="fchip" aria-pressed="' +
      String(state.apFilter === 'all') +
      '" data-f="all">All</button>';
    dts.forEach(function (row) {
      html +=
        '<button type="button" class="fchip" aria-pressed="' +
        String(String(state.apFilter).toUpperCase() === row.code) +
        '" data-f="' +
        esc(row.code) +
        '">' +
        esc(row.label) +
        '</button>';
    });
    host.innerHTML = html;
  }

  function refreshApprovalKindsFromDocumentTypes() {
    if (!(state.approvals || []).length) return;
    state.approvals = state.approvals.map(function (a) {
      if (a && a.raw) return invoiceToApproval(a.raw) || a;
      if (!a) return a;
      var kind = resolveInvoiceKind({
        team_expense_kind: a.kind,
        document_type_code: a.dt,
        document_heading: a.heading
      });
      return Object.assign({}, a, { kind: kind || a.kind || '' });
    });
  }

  async function enrichMobileQuickActions() {
    try {
      if (!window.LLCaptureApi || !LLCaptureApi.listDocumentTypes) {
        applyMobileQuickActions();
        renderApprovalFilterChips();
        return;
      }
      var rows = await LLCaptureApi.listDocumentTypes();
      state.documentTypes = (rows || []).map(function (dt) {
        var resolved = resolveDocumentTypeKind(dt);
        return Object.assign({}, dt, {
          teamExpenseKind: resolved || dt.teamExpenseKind || ''
        });
      });
      var byCode = {};
      state.documentTypes.forEach(function (dt) {
        if (dt && dt.code) byCode[String(dt.code).toUpperCase()] = dt;
      });
      state.mobileQaItems = (state.mobileQaItems || []).map(function (item) {
        var dt = byCode[item.documentTypeCode];
        if (!dt) return item;
        return Object.assign({}, item, {
          teamExpenseKind: dt.teamExpenseKind || item.teamExpenseKind,
          shortTitle: dt.shortTitle || dt.title || item.shortTitle,
          title: dt.title || item.title,
          label: item.label || dt.shortTitle || dt.title || item.label,
          postTo: dt.postTo || item.postTo || null
        });
      });
      refreshApprovalKindsFromDocumentTypes();
    } catch (err) {
      /* keep items as-is */
    }
    applyMobileQuickActions();
    renderApprovalFilterChips();
    if ((state.approvals || []).length) renderApprovals();
  }

  function documentDisplayRef(inv) {
    var ref = String((inv && (inv.document_ref || inv.documentRef)) || '').trim();
    if (ref) return ref;
    var id = inv && (inv.id != null ? inv.id : '');
    return id !== '' ? 'DOC-' + id : 'Document';
  }

  function approvalRequester(inv) {
    var kind = resolveInvoiceKind(inv);
    var employee = String((inv && (inv.employee_email || inv.email_sender)) || '').trim();
    var vendor = String((inv && inv.vendor) || '').trim();
    if (kind === 'expense_claim' || kind === 'advance_requisition' || kind === 'direct_payment') {
      return employee || vendor || 'Employee';
    }
    return vendor || employee || 'Document';
  }

  function approvalGroupFromCreated(createdAt) {
    var d = createdAt ? new Date(createdAt) : null;
    if (!d || isNaN(d.getTime())) return 'Earlier';
    var now = new Date();
    var startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (d >= startToday) return 'Today';
    var startWeek = new Date(startToday);
    startWeek.setDate(startWeek.getDate() - 6);
    if (d >= startWeek) return 'This week';
    return 'Earlier';
  }

  function statusFlag(status) {
    var s = String(status || '').toLowerCase();
    if (s === 'exception') return { label: 'Needs review', tone: 'warn' };
    if (s === 'rejected') return { label: 'Rejected', tone: 'neg' };
    if (s === 'duplicate_skipped') return { label: 'Duplicate', tone: 'warn' };
    if (s === 'pending') return { label: 'Pending', tone: '' };
    return { label: s ? s.replace(/_/g, ' ') : 'Queued', tone: '' };
  }

  function checksFromInvoice(inv) {
    var checks = [];
    var summary = String((inv && inv.issue_summary) || '').trim();
    var hint = String((inv && inv.resolution_hint) || '').trim();
    if (summary) checks.push(['warn', 'Issues', summary]);
    if (hint) checks.push(['warn', 'Hint', hint]);
    var issues = Array.isArray(inv && inv.validation_results) ? inv.validation_results : [];
    issues.slice(0, 8).forEach(function (row) {
      if (!row) return;
      var ok = row.passed === true || row.status === 'pass' || row.ok === true;
      checks.push([
        ok ? 'pos' : 'warn',
        row.rule || row.name || 'Check',
        row.message || row.detail || ''
      ]);
    });
    return checks;
  }

  function chainFromInvoice(inv) {
    var raw = inv && inv.approval_chain;
    if (!raw || typeof raw !== 'object') return [];
    var approvals = Array.isArray(raw.approvals) ? raw.approvals : [];
    var required = Number(raw.required) || 0;
    var steps = approvals.map(function (step) {
      var name = String((step && (step.name || step.role)) || 'Approver').trim();
      var when = step && step.at ? shortDate(step.at) : '';
      return [name, when ? ('Approved · ' + when) : 'Approved', 'done'];
    });
    if (required > 0 && approvals.length < required) {
      steps.push([
        'Awaiting approval',
        approvals.length + ' of ' + required + ' approved',
        'now'
      ]);
    }
    return steps;
  }

  function invoiceToApproval(inv) {
    if (!inv || typeof inv !== 'object') return null;
    var amount = Number(inv.total);
    if (!isFinite(amount)) amount = 0;
    var currency = String(inv.currency || state.currency || 'AUD').trim().toUpperCase() || 'AUD';
    var who = approvalRequester(inv);
    var desc = documentDisplayRef(inv);
    var dt = String(inv.document_type_code || inv.purchase_document_type || '').trim() || '—';
    var heading = String(inv.document_heading || '').trim();
    var status = String(inv.status || '').trim();
    var kind = resolveInvoiceKind(inv);
    var flag = statusFlag(status);
    var checks = checksFromInvoice(inv);
    if (!checks.length && flag.label) {
      checks = [['warn', 'Status', flag.label]];
    }
    var chain = chainFromInvoice(inv);
    var createdAt = inv.created_at || inv.createdAt || null;
    return {
      id: String(inv.id),
      invoiceId: Number(inv.id),
      group: approvalGroupFromCreated(createdAt),
      who: who,
      init: LLSession.initialsFromName(who),
      vendor: String(inv.vendor || '').trim(),
      employeeEmail: String(inv.employee_email || '').trim(),
      dept: String(inv.cost_centre || '').trim() || '—',
      amount: amount,
      currency: currency,
      desc: desc,
      invoiceNo: String(inv.invoice_no || '').trim(),
      heading: heading,
      dt: dt,
      kind: kind,
      status: status,
      statusLabel: flag.label,
      sla: flag.label,
      slaTone: flag.tone,
      flag: flag.label !== status.replace(/_/g, ' ') ? flag.label : '',
      flagTone: flag.tone,
      issueSummary: String(inv.issue_summary || '').trim(),
      invoiceDate: inv.invoice_date || inv.invoiceDate || null,
      createdAt: createdAt,
      hasStoredFile: !!(inv.has_stored_file || inv.hasStoredFile),
      checks: checks,
      chain: chain,
      raw: inv
    };
  }

  async function loadLiveApprovals() {
    if (!canActAsApprover()) {
      state.approvals = [];
      renderApprovalFilterChips();
      renderApprovals();
      syncRoleChrome();
      return;
    }
    try {
      var rows = await LLSession.listApprovals(100);
      if (!Array.isArray(rows)) rows = [];
      state.approvals = rows.map(invoiceToApproval).filter(Boolean);
      renderApprovalFilterChips();
      renderApprovals();
      syncRoleChrome();
    } catch (err) {
      toast((err && err.message) || 'Could not load approvals');
      state.approvals = [];
      renderApprovalFilterChips();
      renderApprovals();
    }
  }

  /* =========================================================
     SCREEN NAVIGATION
     ========================================================= */
  var TABS = ['home', 'items', 'capture', 'history', 'files', 'approvals'];

  function showScreen(name, opts) {
    opts = opts || {};
    if ((name === 'approvals' || name === 'detail') && state.role !== 'approver') {
      name = 'home';
    }
    if (name === 'items' && state.role === 'approver') {
      name = 'history';
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
    resetShellScroll();
    var body = $('.body', next);
    if (body && !opts.keepScroll) { body.scrollTop = 0; }
    var nav = $('.nav', next);
    if (nav && name !== 'detail' && body) { nav.classList.toggle('stuck', body.scrollTop > 12); }

    if (name === 'capture') {
      hideSuccess();
      if (window.LLCapture) LLCapture.onShowCapture();
    } else {
      if (window.LLCapture) LLCapture.onHideCapture();
      if (name === 'approvals') {
        void loadLiveApprovals();
      }
      if (name === 'items' || name === 'history') {
        void loadMyItems();
      }
      if (name === 'history') {
        renderHistoryScreen();
      }
      if (name === 'home') {
        void loadHomeFinance();
        void loadMyItems();
      }
      if (name === 'profile') {
        void loadEmployeeProfile();
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
    var appRoot = $('#app');
    if (appRoot) appRoot.classList.add('sheet-open');
    sheet.style.maxHeight = cfg.tall ? '92%' : '88%';
    // Block the opening tap from "falling through" onto sheet rows (e.g. With document → Capture).
    sheet.style.pointerEvents = 'none';
    scrim.style.pointerEvents = 'none';
    if (cfg.onMount) { cfg.onMount($('#sheetBody'), $('#sheetFoot')); }
    setTimeout(function () {
      sheet.style.pointerEvents = '';
      scrim.style.pointerEvents = '';
    }, 320);
  }
  function closeSheet() {
    sheet.classList.remove('show');
    scrim.classList.remove('show');
    var appRoot = $('#app');
    if (appRoot) appRoot.classList.remove('sheet-open');
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

  function currentBudgetSnapshot() {
    var m = QLL.me;
    var key = m.budgetLineKey || 'all';
    if (key !== 'all' && Array.isArray(m.budgetLines)) {
      for (var i = 0; i < m.budgetLines.length; i++) {
        if (m.budgetLines[i].key === key) return m.budgetLines[i];
      }
    }
    return m.budgetAll || {
      remaining: Number(m.remaining) || 0,
      approved: Number(m.approved) || 0,
      leftPct: m.leftPct,
      hasBudget: !!m.hasBudget
    };
  }

  function budgetLineDisplayLabel() {
    var key = QLL.me.budgetLineKey || 'all';
    if (key === 'all') return 'All';
    var lines = QLL.me.budgetLines || [];
    for (var i = 0; i < lines.length; i++) {
      if (lines[i].key === key) return lines[i].label || 'Line';
    }
    var tree = QLL.me.budgetTree || [];
    for (var t = 0; t < tree.length; t++) {
      if (tree[t].key === key) return tree[t].label || 'Parent';
    }
    return 'All';
  }

  function syncBudgetLineBtn() {
    var label = $('#budgetLineLabel');
    var btn = $('#budgetLineBtn');
    if (label) label.textContent = budgetLineDisplayLabel();
    if (btn) {
      btn.hidden = false;
      btn.disabled = false;
      btn.setAttribute('aria-expanded', 'false');
    }
  }

  function applyBudgetLineSelection(key) {
    QLL.me.budgetLineKey = key || 'all';
    var snap = currentBudgetSnapshot();
    QLL.me.remaining = Number(snap.remaining) || 0;
    QLL.me.approved = Number(snap.approved) || 0;
    QLL.me.leftPct = snap.leftPct != null ? snap.leftPct : null;
    QLL.me.hasBudget = !!snap.hasBudget;
    syncBudgetLineBtn();
    renderHomeBudget();
    if (state.role === 'approver') renderHome();
  }

  function budgetOptionRow(opt, current) {
    var selected = opt.key === current;
    var openKids = opt.hasChildren ? ' data-budget-parent="' + esc(String(opt.key)) + '"' : '';
    var selectAttr = opt.hasChildren && !opt.selectable
      ? ''
      : ' data-budget-line="' + esc(String(opt.key)) + '"';
    var right = selected
      ? '<span style="color:var(--accent)">' + IC.tick + '</span>'
      : opt.hasChildren
        ? IC.chev
        : '';
    return '<button type="button" class="row" role="option" aria-selected="' + (selected ? 'true' : 'false') + '"' +
      selectAttr + openKids + '>' +
      '<span class="main"><span class="t" style="display:block">' + esc(opt.label || 'Line') + '</span>' +
      (opt.sub ? '<span class="s" style="display:block">' + esc(opt.sub) + '</span>' : '') +
      '</span>' + right + '</button>';
  }

  function openBudgetSubSheet(parentNode) {
    var current = QLL.me.budgetLineKey || 'all';
    var options = [
      {
        key: parentNode.key,
        label: parentNode.label,
        sub: 'Parent ledger',
        hasChildren: false,
        selectable: true
      }
    ].concat(
      (parentNode.children || []).map(function (c) {
        return {
          key: c.key,
          label: c.label,
          sub: 'Sub-ledger',
          hasChildren: false,
          selectable: true
        };
      })
    );
    openSheet({
      title: parentNode.label || 'Sub-ledgers',
      sub: 'Choose the parent or a sub-ledger.',
      body:
        '<div style="padding:8px 16px 4px">' +
        '<button type="button" id="budgetBackParents" style="width:100%;min-height:40px;border-radius:10px;border:var(--hairline) solid var(--line);background:var(--canvas-2);font-size:13px;font-weight:550;color:var(--ink)">← Parent ledgers</button>' +
        '</div>' +
        '<div class="rows" style="border:0" role="listbox" aria-label="Sub-ledgers">' +
        options.map(function (opt) {
          return budgetOptionRow(opt, current);
        }).join('') +
        '</div>',
      onMount: function (b) {
        var btn = $('#budgetLineBtn');
        if (btn) btn.setAttribute('aria-expanded', 'true');
        var back = $('#budgetBackParents');
        if (back) {
          back.addEventListener('click', function () {
            openBudgetLineSheet();
          });
        }
        b.addEventListener('click', function (e) {
          var row = e.target.closest('[data-budget-line]');
          if (!row) return;
          applyBudgetLineSelection(row.getAttribute('data-budget-line') || 'all');
          closeSheet();
          if (btn) btn.setAttribute('aria-expanded', 'false');
        });
      }
    });
  }

  function openBudgetLineSheet() {
    var tree = QLL.me.budgetTree || [];
    var current = QLL.me.budgetLineKey || 'all';
    var options = [{ key: 'all', label: 'All', sub: 'All parent ledgers', hasChildren: false, selectable: true }];
    tree.forEach(function (node) {
      options.push({
        key: node.key,
        label: node.label,
        sub: node.hasChildren
          ? node.children.length + ' sub-ledger' + (node.children.length === 1 ? '' : 's')
          : 'Parent ledger',
        hasChildren: !!node.hasChildren,
        selectable: !node.hasChildren
      });
    });
    openSheet({
      title: 'Budget line',
      sub: 'Pick a parent ledger, then a sub-ledger if needed.',
      body: '<div class="rows" style="border:0" role="listbox" aria-label="Parent ledgers">' +
        options.map(function (opt) {
          return budgetOptionRow(opt, current);
        }).join('') +
        '</div>',
      onMount: function (b) {
        var btn = $('#budgetLineBtn');
        if (btn) btn.setAttribute('aria-expanded', 'true');
        b.addEventListener('click', function (e) {
          var parentBtn = e.target.closest('[data-budget-parent]');
          if (parentBtn) {
            var pk = parentBtn.getAttribute('data-budget-parent');
            var node = null;
            for (var i = 0; i < tree.length; i++) {
              if (tree[i].key === pk) {
                node = tree[i];
                break;
              }
            }
            if (node && node.hasChildren) {
              openBudgetSubSheet(node);
              return;
            }
          }
          var row = e.target.closest('[data-budget-line]');
          if (!row) return;
          applyBudgetLineSelection(row.getAttribute('data-budget-line') || 'all');
          closeSheet();
          if (btn) btn.setAttribute('aria-expanded', 'false');
        });
      }
    });
  }

  function renderHomeBudget() {
    var snap = currentBudgetSnapshot();
    var rem = Number(snap.remaining) || 0;
    var approved = Number(snap.approved) || 0;
    var hasBudget = !!snap.hasBudget || rem > 0 || approved > 0;
    var leftPct = snap.leftPct != null && isFinite(Number(snap.leftPct))
      ? Math.max(0, Math.min(1, Number(snap.leftPct)))
      : null;
    var remEl = $('#budRem');
    var appEl = $('#budApp');
    var ringEl = $('#budgetRing');
    if (!remEl || !appEl || !ringEl) return;

    syncBudgetLineBtn();

    if (!hasBudget) {
      remEl.textContent = '—';
      appEl.textContent = approved ? fmtTenant(approved) : '—';
      ring(ringEl, 0, 'accent', 'n/a');
      return;
    }

    remEl.textContent = fmtTenant(Math.max(rem, 0));
    appEl.textContent = fmtTenant(approved);
    if (leftPct == null) {
      ring(ringEl, 0, 'accent', 'n/a');
    } else {
      var tone = leftPct < 0.1 ? 'neg' : leftPct < 0.25 ? 'warn' : 'accent';
      ring(ringEl, leftPct, tone, 'left');
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
      amtEl.textContent = fmtTenant(0);
      if (chip) { chip.hidden = true; chip.textContent = ''; }
      if (title) title.textContent = 'No advance outstanding';
      if (meta) meta.textContent = 'Tap to open Analysis';
      if (barWrap) barWrap.hidden = true;
      return;
    }

    var outstanding = Number(a.outstanding != null ? a.outstanding : a.amount) || 0;
    var taken = Number(a.taken != null ? a.taken : a.amount) || outstanding;
    var acquitted = Number(a.acquitted) || 0;
    amtEl.textContent = fmtTenant(outstanding > 0 ? outstanding : taken);
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
        (acquitted ? fmtTenant(acquitted) + ' used' : 'No claims against advance yet') +
        (a.issued ? ' · issued ' + a.issued : '');
    }
    if (barWrap && bar) {
      barWrap.hidden = false;
      var pct = taken > 0 ? Math.min(acquitted / taken, 1) : 0;
      bar.style.width = Math.round(pct * 100) + '%';
      bar.className = pct >= 1 ? 'pos' : 'warn';
    }
  }

  function historyItemRows(limit) {
    var claims = (QLL.myItems && QLL.myItems.claims) || [];
    var advances = (QLL.myItems && QLL.myItems.advances) || [];
    var rows = claims.concat(advances).slice();
    rows.sort(function (a, b) {
      return (Number(b.id) || 0) - (Number(a.id) || 0);
    });
    if (limit != null && limit >= 0) return rows.slice(0, limit);
    return rows;
  }

  function historyRowHtml(i) {
    return '<button type="button" class="row" data-history-id="' + i.id + '">' +
      '<span class="main">' +
      '<span class="t truncate" style="display:block">' + esc(i.t) + '</span>' +
      '<span class="s truncate" style="display:block">' + esc(i.s) + '</span>' +
      '</span>' +
      '<span class="ir" style="text-align:right">' +
      '<span class="amt" style="font-size:14px;font-weight:600;display:block">' +
      fmtDoc(i.amt, i.amt % 1 !== 0, i.currency) +
      '</span>' +
      '<span class="chip ' + esc((i.chip && i.chip[0]) || '') + '" style="margin-top:6px">' + esc((i.chip && i.chip[1]) || '') + '</span>' +
      '</span></button>';
  }

  function renderHistoryScreen() {
    var host = $('#historyList');
    if (!host) return;
    var list = historyItemRows();
    var sub = $('#historySub');
    if (sub) {
      sub.textContent = list.length
        ? list.length + ' item' + (list.length === 1 ? '' : 's')
        : 'Your claims and advances';
    }

    if (myItemsLoading && !list.length) {
      host.innerHTML =
        '<div class="empty" style="padding:24px 16px;font-size:13px;color:var(--ink-3);text-align:center">Loading history…</div>';
      return;
    }
    if (!list.length) {
      host.innerHTML =
        '<div class="empty" style="padding:24px 16px;font-size:13px;color:var(--ink-3);text-align:center">No claims or advances yet.</div>';
      return;
    }
    host.innerHTML = list.map(historyRowHtml).join('');
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
    if (queueAmt) queueAmt.textContent = apN ? fmtListTotal(state.approvals, false) : fmtTenant(0);
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

    var offline = $('#offlineSub');
    var syncSub = $('#profSyncSub');
    var syncLine = '';
    if (window.LLCaptureApi) {
      var processing = LLCaptureApi.readPending().filter(function (p) {
        return p.status === 'processing';
      }).length;
      var draftPages = window.LLCapture && LLCapture.getPages ? LLCapture.getPages().length : 0;
      if (processing || draftPages) {
        syncLine =
          (processing ? processing + ' processing' : '') +
          (processing && draftPages ? ' · ' : '') +
          (draftPages ? draftPages + ' page(s) ready to retry/upload' : '');
      } else {
        syncLine = 'No queued captures';
      }
    }
    if (offline) offline.textContent = syncLine || 'No queued captures';
    if (syncSub) syncSub.textContent = syncLine || 'Offline queue & ledger';

    // Approver spend card: only signed-in employee (no demo teammates).
    var teamHost = $('#teamRows');
    if (teamHost) {
      var snap = currentBudgetSnapshot();
      var rem = Number(snap.remaining) || 0;
      var approved = Number(snap.approved) || 0;
      var hasBudget = !!snap.hasBudget || rem > 0 || approved > 0;
      var leftPct = snap.leftPct != null && isFinite(Number(snap.leftPct))
        ? Math.max(0, Math.min(1, Number(snap.leftPct)))
        : null;
      if (hasBudget) {
        var tone = leftPct != null
          ? (leftPct < 0.1 ? 'neg' : leftPct < 0.25 ? 'warn' : 'pos')
          : 'pos';
        var barPct = leftPct != null ? leftPct : 0;
        teamHost.innerHTML =
          '<div class="row" style="align-items:flex-start;flex-direction:column;gap:7px">' +
          '<div style="display:flex;width:100%;gap:10px;align-items:baseline">' +
          '<span class="t truncate" style="flex:1">' + esc(QLL.me.name || 'You') + '</span>' +
          '<span class="amt" style="font-size:14px;font-weight:600">' + fmtTenant(Math.max(rem, 0)) + '</span>' +
          '<span class="s" style="margin:0">remaining</span></div>' +
          '<div class="bar" style="width:100%"><i class="' + tone + '" style="width:' + (barPct * 100) + '%"></i></div>' +
          '<div style="display:flex;width:100%;gap:8px"><span class="s" style="margin:0;flex:1">' +
          esc(QLL.me.dept || QLL.me.role || '') + '</span>' +
          '<span class="chip ' + tone + '">Spent ' + fmtTenant(approved) + '</span></div></div>';
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
      QLL.me.budgetAll = fin.all || {
        remaining: Number(fin.remaining) || 0,
        approved: Number(fin.approved) || 0,
        leftPct: fin.leftPct != null ? fin.leftPct : null,
        hasBudget: !!fin.hasBudget
      };
      QLL.me.budgetLines = Array.isArray(fin.lines) ? fin.lines : [];
      QLL.me.budgetTree = Array.isArray(fin.tree) ? fin.tree : [];
      QLL.me.coaParentChildren = fin.coaParentChildren || {};
      if (!QLL.me.budgetLineKey) QLL.me.budgetLineKey = 'all';
      if (QLL.me.budgetLineKey !== 'all') {
        var stillThere = QLL.me.budgetLines.some(function (line) {
          return line.key === QLL.me.budgetLineKey;
        });
        if (!stillThere) QLL.me.budgetLineKey = 'all';
      }
      applyBudgetLineSelection(QLL.me.budgetLineKey);
      QLL.me.advance = fin.advance;
      renderHomeAdvance();
      if (state.role === 'approver') renderHome();
    } catch (err) {
      QLL.me.budgetAll = { remaining: 0, approved: 0, leftPct: null, hasBudget: false };
      QLL.me.budgetLines = [];
      QLL.me.budgetTree = [];
      QLL.me.coaParentChildren = {};
      QLL.me.budgetLineKey = 'all';
      QLL.me.remaining = 0;
      QLL.me.approved = 0;
      QLL.me.leftPct = null;
      QLL.me.hasBudget = false;
      QLL.me.advance = null;
      syncBudgetLineBtn();
      renderHomeBudget();
      renderHomeAdvance();
    }
  }

  /* Employee | Approver toggle — visible only for dual-role users */
  $$('#roleSeg button').forEach(function (b) {
    b.addEventListener('click', function () {
      if (!state.dualRole) return;
      var next = b.dataset.role;
      if (next === 'approver' && !canActAsApprover()) return;
      if (next === 'employee' && !state.hasEmployeeProfile) return;
      state.role = next;
      syncRoleChrome();
      $('.body', $('.screen[data-screen="home"]')).scrollTop = 0;
      syncPicker();
    });
  });

  var budgetLineBtn = $('#budgetLineBtn');
  if (budgetLineBtn) {
    budgetLineBtn.addEventListener('click', function (e) {
      if (e) e.stopPropagation();
      openBudgetLineSheet();
    });
  }

  function openAnalysisFromHome() {
    showScreen('files');
  }

  var budgetCard = $('#budgetCard');
  if (budgetCard) {
    budgetCard.addEventListener('click', openAnalysisFromHome);
    budgetCard.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openAnalysisFromHome();
      }
    });
  }

  /* advance card -> Analysis */
  function acquitSheet() {
    openAnalysisFromHome();
  }
  $('#advCard').addEventListener('click', acquitSheet);

  /* legacy stubs */
  function claimChooserSheet() {
    openDocumentTypeQuickAction({
      documentTypeCode: '',
      label: 'Claim',
      shortTitle: 'Claim',
      teamExpenseKind: 'expense_claim',
      allowWithDoc: true,
      allowWithoutDoc: true,
      photoRequired: 'optional',
      fields: null
    });
  }

  function advanceSheet() {
    if (window.LLCapture && LLCapture.startAdvanceCapture) {
      LLCapture.startAdvanceCapture({});
    } else {
      showScreen('capture');
    }
  }

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
      renderHome();
    }
  });


  /* =========================================================
     APPROVALS INBOX
     ========================================================= */
  var APPROVAL_GROUPS = ['Today', 'This week', 'Earlier'];

  function visibleApprovals() {
    var q = state.apQuery.trim().toLowerCase();
    var filterDt = String(state.apFilter || 'all').trim().toUpperCase();
    return state.approvals.filter(function (a) {
      if (filterDt && filterDt !== 'ALL') {
        var rowDt = String((a && a.dt) || '').trim().toUpperCase();
        if (rowDt !== filterDt) return false;
      }
      if (!q) { return true; }
      return (
        a.who +
        ' ' +
        a.desc +
        ' ' +
        a.dt +
        ' ' +
        a.dept +
        ' ' +
        a.vendor +
        ' ' +
        a.employeeEmail +
        ' ' +
        a.amount +
        ' ' +
        (a.kind || '') +
        ' ' +
        (a.status || '')
      )
        .toLowerCase()
        .indexOf(q) > -1;
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
          '<div>Queue clear.<br>Nothing waiting for your approval.</div></div>';
      } else {
        host.innerHTML = '<div class="empty">' +
          '<svg width="30" height="30" viewBox="0 0 30 30" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="13" cy="13" r="8.6"/><path d="M19.4 19.4 26 26"/></svg>' +
          '<div>No approvals match.<br>Clear the search or filter to see your queue.</div></div>';
      }
    } else {
      host.innerHTML = APPROVAL_GROUPS.map(function (g) {
        var items = list.filter(function (a) { return a.group === g; });
        if (!items.length) { return ''; }
        var tot = items.reduce(function (s, a) { return s + a.amount; }, 0);
        return '<div class="sect-h">' + g + '<span class="r">' + items.length + ' · ' + fmtListTotal(items, true) + '</span></div>' +
          '<div class="rows" style="border-radius:0">' + items.map(rowHTML).join('') + '</div>';
      }).join('');
    }
    var total = state.approvals.reduce(function (s, a) { return s + a.amount; }, 0);
    var needsReview = state.approvals.filter(function (a) {
      return String(a.status || '').toLowerCase() === 'exception';
    }).length;
    $('#apSub').textContent = state.approvals.length
      ? (state.approvals.length + ' in queue · ' + fmtListTotal(state.approvals, true) +
        (needsReview ? ' · ' + needsReview + ' need review' : ''))
      : 'No items in queue';
    $('#tabBadge').textContent = state.approvals.length;
    $('#qaBadge').textContent = state.approvals.length;
    $('#tabBadge').style.display = state.approvals.length ? '' : 'none';
    bindSwipes();
    updateBulk();
  }

  function rowHTML(a) {
    var kindChip = kindLabel(a.kind);
    var subWho = a.dept && a.dept !== '—' ? (a.who + ' · ' + a.dept) : a.who;
    return '<div class="swipe' + (state.selectMode ? ' selectmode' : '') + '" data-id="' + a.id + '" data-sel="' + (state.selected[a.id] ? 1 : 0) + '">' +
      '<div class="swipe-bg" aria-hidden="true">' +
      '<span class="ap">' + IC.tick + ' Approve</span>' +
      '<span class="rj">Reject ' + IC.neg + '</span></div>' +
      '<div class="swipe-fg">' +
      '<span class="sel-box">' + IC.tick + '</span>' +
      '<span class="av">' + esc(a.init) + '</span>' +
      '<span class="ai-main">' +
      '<span class="ai-top"><span class="ai-who truncate">' + esc(subWho) + '</span>' +
      '<span class="ai-amt">' + fmtDoc(a.amount, true, a.currency) + '</span></span>' +
      '<span class="ai-desc truncate" style="display:block">' + esc(a.heading || a.desc) + '</span>' +
      '<span class="ai-meta">' +
      '<span class="chip dt">' + esc(a.dt) + '</span>' +
      (kindChip ? '<span class="chip">' + esc(kindChip) + '</span>' : '') +
      (a.statusLabel ? '<span class="chip ' + esc(a.slaTone || '') + '">' + esc(a.statusLabel) + '</span>' : '') +
      '</span>' +
      '<span class="ai-acts">' +
      (state.canApprove
        ? '<button class="ai-approve" data-approve="' + a.id + '">' + IC.tick + ' Approve</button>'
        : '') +
      (state.canApprove
        ? '<button class="ai-escalate" data-escalate="' + a.id + '">Escalate</button>'
        : '') +
      (state.canReject
        ? '<button class="ai-reject" data-reject="' + a.id + '">Reject</button>'
        : '') +
      '<button class="ai-more" data-open="' + a.id + '" aria-label="Open detail">' + IC.chev.replace('class="chev"', '') + '</button>' +
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
    var es = e.target.closest('[data-escalate]');
    if (es) { escalateSheet([es.dataset.escalate], 'row'); return; }
    var rj = e.target.closest('[data-reject]');
    if (rj) { rejectSheet([rj.dataset.reject], 'row'); return; }
    var openBtn = e.target.closest('[data-open]');
    if (openBtn) { openDetail(openBtn.dataset.open); return; }
    openDetail(row.dataset.id);
  });

  /* --- approve / reject sheets --- */
  function approveSheet(ids, via) {
    var items = ids.map(findAp).filter(Boolean);
    if (!items.length) return;
    var tot = items.reduce(function (s, a) { return s + a.amount; }, 0);
    var many = items.length > 1;
    var first = items[0];
    openSheet({
      title: many ? 'Approve ' + items.length + ' items?' : 'Approve ' + fmtDoc(first.amount, true, first.currency) + '?',
      sub: many
        ? fmtListTotal(items, true) + ' total'
        : first.who + ' · ' + first.desc,
      body: '<div class="kv-list">' + (many
        ? items.map(function (a) {
          return '<div class="kv"><span class="k truncate">' + esc(a.who) + ' · ' + esc(a.dt) + '</span><span class="v">' + fmtDoc(a.amount, true, a.currency) + '</span></div>';
        }).join('')
        : [
          ['Reference', first.desc],
          ['Document type', first.dt],
          ['Kind', kindLabel(first.kind) || '—'],
          ['Cost centre', first.dept],
          ['Status', first.statusLabel || first.status || '—'],
          ['Invoice date', first.invoiceDate ? shortDate(first.invoiceDate) : '—']
        ].map(function (r) {
          return '<div class="kv"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) + '</span></div>';
        }).join('')) + '</div>' +
        (first.issueSummary
          ? '<div class="banner warn">' + IC.warn + '<span>' + esc(first.issueSummary) + '</span></div>'
          : '') +
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
              toast(many ? items.length + ' approved · ' + fmtListTotal(items, true) : 'Approved ' + fmtDoc(first.amount, true, first.currency) + ' · ' + first.who);
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
    if (!items.length) return;
    var many = items.length > 1;
    var first = items[0];
    openSheet({
      title: many ? 'Reject ' + items.length + ' items?' : 'Reject ' + fmtDoc(first.amount, true, first.currency) + '?',
      sub: many ? 'These documents will be marked rejected.' : first.who + ' · ' + first.desc,
      body:
        '<div class="kv-list">' +
        [
          ['Reference', first.desc],
          ['Document type', first.dt],
          ['Status', first.statusLabel || first.status || '—']
        ].map(function (r) {
          return '<div class="kv"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) + '</span></div>';
        }).join('') +
        '</div><div style="height:14px"></div>',
      foot: '<button class="btn sm sec" data-close style="flex:0 0 92px">Cancel</button>' +
        '<button class="btn sm danger" id="confirmRj" style="flex:1">Confirm rejection</button>',
      onMount: function (b, f) {
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
              toast(many ? items.length + ' rejected' : 'Rejected · ' + first.who);
              if (state.screen === 'detail') { showScreen('approvals'); }
              if (via === 'bulk') { exitSelect(); }
              void loadLiveApprovals();
            })
            .catch(function (err) {
              btn.disabled = false;
              btn.textContent = 'Confirm rejection';
              toast((err && err.message) || 'Reject failed');
            });
        });
      }
    });
  }

  function escalateSheet(ids, via) {
    var items = ids.map(findAp).filter(Boolean);
    if (!items.length) return;
    var many = items.length > 1;
    openSheet({
      title: many ? 'Escalate ' + items.length + ' items?' : 'Escalate approval?',
      sub: many
        ? 'Add a note for the next reviewer. Items stay in the queue.'
        : items[0].who + ' · ' + items[0].desc,
      body:
        '<div style="padding:0 16px 14px">' +
        '<label class="cap-fill-label" for="escalateNote">Escalation note *</label>' +
        '<textarea id="escalateNote" class="comment" rows="3" placeholder="Why this needs escalation" style="margin:0;width:100%"></textarea>' +
        '</div>',
      foot:
        '<button class="btn sm sec" data-close style="flex:0 0 92px">Cancel</button>' +
        '<button class="btn sm" id="confirmEs" style="flex:1">Confirm escalate</button>',
      onMount: function (b, f) {
        var noteEl = $('#escalateNote', b);
        $('#confirmEs', f).addEventListener('click', function () {
          if (!state.canApprove) {
            toast('Missing Approve privilege');
            return;
          }
          var note = String((noteEl && noteEl.value) || '').trim();
          if (!note) {
            toast('Enter an escalation note');
            if (noteEl) noteEl.focus();
            return;
          }
          var btn = $('#confirmEs', f);
          btn.disabled = true;
          btn.textContent = 'Escalating…';
          Promise.all(items.map(function (a) {
            return LLSession.escalateInvoice(a.invoiceId || a.id, note);
          }))
            .then(function () {
              closeSheet();
              toast(many ? items.length + ' escalated' : 'Escalated · note recorded');
              if (state.screen === 'detail') { showScreen('approvals'); }
              if (via === 'bulk') { exitSelect(); }
              void loadLiveApprovals();
            })
            .catch(function (err) {
              btn.disabled = false;
              btn.textContent = 'Confirm escalate';
              toast((err && err.message) || 'Escalate failed');
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
    var next = String(c.dataset.f || 'all').trim();
    if (next !== 'all') next = next.toUpperCase();
    state.apFilter = (String(state.apFilter).toUpperCase() === String(next).toUpperCase() && next !== 'all')
      ? 'all'
      : next;
    renderApprovalFilterChips();
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
    $('#bulkN').textContent = ids.length + ' selected' + (ids.length ? ' · ' + fmtListTotal(ids.map(findAp).filter(Boolean), false) : '');
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
  function renderApprovalDetailBody(a) {
    var kindChip = kindLabel(a.kind);
    var meta =
      '<span class="chip dt">' + esc(a.dt) + '</span>' +
      (kindChip ? '<span class="chip">' + esc(kindChip) + '</span>' : '') +
      (a.statusLabel ? '<span class="chip ' + esc(a.slaTone || '') + '">' + esc(a.statusLabel) + '</span>' : '');

    var docSub = [];
    if (a.invoiceNo) docSub.push('Invoice ' + a.invoiceNo);
    if (a.invoiceDate) docSub.push(shortDate(a.invoiceDate));
    if (a.vendor && a.vendor !== a.who) docSub.push(a.vendor);

    var checksHtml = (a.checks && a.checks.length)
      ? a.checks.map(function (c) {
          return '<div class="check"><span class="ic ' + c[0] + '">' + checkIcon(c[0]) + '</span>' +
            '<span style="flex:1;min-width:0"><span class="ct" style="display:block">' + esc(c[1]) + '</span>' +
            '<span class="cs" style="display:block">' + esc(c[2]) + '</span></span></div>';
        }).join('')
      : '<div class="pad" style="font-size:13px;color:var(--ink-3)">No issue summary on this document.</div>';

    var chainHtml = (a.chain && a.chain.length)
      ? '<div class="sect-h">Approval chain</div><div class="card"><div class="chain">' +
        a.chain.map(function (s, i) {
          return '<div class="chain-step ' + s[2] + '"><span class="cd">' + (s[2] === 'done' ? '✓' : i + 1) + '</span>' +
            '<span><span class="cn" style="display:block">' + esc(s[0]) + '</span>' +
            '<span class="cm" style="display:block">' + esc(s[1]) + '</span></span></div>';
        }).join('') +
        '</div></div>'
      : '';

    var docAction = a.hasStoredFile
      ? '<button type="button" class="chip acc" id="dOpenDoc" style="border:0;cursor:pointer">Open document</button>'
      : '<span class="chip">No file on file</span>';

    $('#detailBody').innerHTML =
      '<div class="hero">' +
      '<div class="amt-xl">' + fmtDoc(a.amount, true, a.currency) + '</div>' +
      '<div class="who"><span class="av" style="width:24px;height:24px;font-size:10px">' + esc(a.init) + '</span>' +
      esc(a.who) + (a.dept && a.dept !== '—' ? ' · ' + esc(a.dept) : '') + '</div>' +
      '<div class="ai-meta" style="margin-top:10px">' + meta + '</div></div>' +

      '<div class="card"><div class="pad docprev">' +
      '<div class="big">' + IC.docLines + '<div class="l"></div><div class="l md"></div></div>' +
      '<div style="flex:1;min-width:0">' +
      '<div style="font-size:14.5px;letter-spacing:-.012em">' + esc(a.heading || a.desc) + '</div>' +
      '<div style="font-size:12.5px;color:var(--ink-3);margin-top:3px">' +
      esc(docSub.join(' · ') || a.desc) +
      '</div>' +
      '<div style="margin-top:9px">' + docAction + '</div>' +
      '</div></div></div>' +

      '<div class="sect-h">Review notes</div>' +
      '<div class="card">' + checksHtml + '</div>' +
      chainHtml +
      '<div style="height:16px"></div>';

    var openDoc = $('#dOpenDoc');
    if (openDoc) {
      openDoc.addEventListener('click', function () {
        if (window.LLCapture && LLCapture.openReviewForId) {
          LLCapture.openReviewForId(a.invoiceId || a.id, {
            fromHome: false,
            sourceLabel: 'Approvals'
          }).catch(function (err) {
            toast((err && err.message) || 'Could not open document');
          });
        } else {
          toast('Document viewer unavailable');
        }
      });
    }
  }

  function openDetail(id) {
    var a = findAp(id);
    if (!a) { return; }
    state.detailId = id;
    $('#dTitle').textContent = a.who;
    var dAp = $('#dApprove');
    var dRj = $('#dReject');
    var dEs = $('#dEscalate');
    if (dAp) dAp.style.display = state.canApprove ? '' : 'none';
    if (dRj) dRj.style.display = state.canReject ? '' : 'none';
    if (dEs) dEs.style.display = state.canApprove ? '' : 'none';
    showScreen('detail');
    renderApprovalDetailBody(a);

    if (window.LLCaptureApi && LLCaptureApi.getInvoice) {
      $('#detailBody').insertAdjacentHTML(
        'afterbegin',
        '<p id="dDetailLoading" style="padding:0 16px 8px;font-size:12px;color:var(--ink-3);margin:0">Refreshing details…</p>'
      );
      LLCaptureApi.getInvoice(a.invoiceId || a.id)
        .then(function (inv) {
          var enriched = invoiceToApproval(inv);
          if (!enriched) return;
          var idx = -1;
          state.approvals.forEach(function (row, i) {
            if (String(row.id) === String(enriched.id)) idx = i;
          });
          if (idx >= 0) state.approvals[idx] = enriched;
          if (String(state.detailId) === String(enriched.id)) {
            $('#dTitle').textContent = enriched.who;
            renderApprovalDetailBody(enriched);
          }
        })
        .catch(function () {
          var el = $('#dDetailLoading');
          if (el && el.parentNode) el.parentNode.removeChild(el);
        });
    }
  }
  $('#dApprove').addEventListener('click', function () { approveSheet([state.detailId], 'detail'); });
  $('#dReject').addEventListener('click', function () { rejectSheet([state.detailId], 'detail'); });
  $('#dEscalate').addEventListener('click', function () { escalateSheet([state.detailId], 'detail'); });
  $('#dFiles').addEventListener('click', function () {
    var a = findAp(state.detailId);
    if (a && a.hasStoredFile && window.LLCapture && LLCapture.openReviewForId) {
      LLCapture.openReviewForId(a.invoiceId || a.id, {
        fromHome: false,
        sourceLabel: 'Approvals'
      }).catch(function (err) {
        toast((err && err.message) || 'Could not open document');
      });
      return;
    }
    showScreen('files');
  });

  /* =========================================================
     MY ITEMS (live Team Expenses claims/advances for this employee)
     ========================================================= */
  var myItemsLoading = false;

  function renderItems() {
    syncMyItemChipPressed(false);
    refreshMyItemChipCounts();
    var list = itemsForCurrentTab();
    var host = $('#itemsList');
    if (!host) return;
    var label = currentItemTabLabel();

    if (myItemsLoading && !list.length) {
      host.innerHTML =
        '<div class="item-filter-active">Loading <b>' + esc(label) + '</b>…</div>';
      return;
    }

    if (!list.length) {
      host.innerHTML =
        '<div class="item-filter-active">Showing <b>' + esc(label) + '</b></div>' +
        '<div class="empty" style="padding:24px;font-size:13px;color:var(--ink-3)">' +
        'No ' +
        esc(label) +
        ' linked to your employee email yet.' +
        '</div>';
      return;
    }

    var total = list.reduce(function (s, i) { return s + (Number(i.amt) || 0); }, 0);
    host.innerHTML =
      '<div class="item-filter-active">Showing <b>' + esc(label) + '</b> · ' + list.length + ' item' + (list.length === 1 ? '' : 's') + '</div>' +
      '<div class="sect-h">' + esc(label) +
      '<span class="r">' + list.length + ' · ' + fmtListTotal(list, false) + '</span></div>' +
      '<div class="rows" style="border-radius:0">' + list.map(function (i) {
        return '<button type="button" class="item-row" data-item-id="' + i.id + '" style="width:100%;text-align:left">' +
          '<span class="im">' +
          '<span style="display:flex;gap:8px;align-items:baseline"><span class="t truncate" style="font-size:15px;flex:1">' + esc(i.t) + '</span></span>' +
          '<span class="s truncate" style="display:block;font-size:12.5px;color:var(--ink-3);margin-top:2px">' + esc(i.s) + '</span>' +
          '<span class="bar" style="display:block;margin-top:9px;width:100%"><i class="' + esc(i.tone || '') + '" style="width:' + (i.prog || 0) + '%"></i></span>' +
          '</span>' +
          '<span class="ir"><span class="amt" style="font-size:16px;font-weight:650;display:block">' +
          fmtDoc(i.amt, i.amt % 1 !== 0, i.currency) +
          '</span>' +
          '<span class="chip ' + esc(i.chip[0] || '') + '" style="margin-top:7px">' + esc(i.chip[1] || '') + '</span></span>' +
          '</button>';
      }).join('') + '</div>' +
      '<p style="font-size:11.5px;color:var(--ink-3);padding:14px 20px 0;line-height:1.5">' +
      'Tap a filter chip above to switch forms. List matches your employee email.' +
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
      var seen = {};
      QLL.myItems.all = []
        .concat(QLL.myItems.claims, QLL.myItems.advances, QLL.myItems.invoices)
        .filter(function (row) {
          var id = row && row.id;
          if (id == null || seen[id]) return false;
          seen[id] = true;
          return true;
        });
    } catch (err) {
      toast((err && err.message) || 'Could not load your items');
      QLL.myItems.claims = [];
      QLL.myItems.advances = [];
      QLL.myItems.invoices = [];
      QLL.myItems.all = [];
    } finally {
      myItemsLoading = false;
      renderItems();
      if (state.screen === 'history') renderHistoryScreen();
    }
  }

  var itemTabs = $('#itemTabs');
  if (itemTabs) {
    itemTabs.addEventListener('click', function (e) {
      var b = e.target.closest('.fchip');
      if (!b || !itemTabs.contains(b)) return;
      var next = b.dataset.t;
      if (next === state.itemTab) return;
      state.itemTab = next;
      syncMyItemChipPressed(true);
      renderItems();
      toast('Showing ' + currentItemTabLabel());
    });
  }
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

  function openHistoryItem(e) {
    var row = e.target.closest('[data-history-id]');
    if (!row) return;
    var id = Number(row.getAttribute('data-history-id'));
    if (!id || !window.LLCapture || !LLCapture.openReviewForId) return;
    toast('Opening…');
    LLCapture.openReviewForId(id, { fromHome: true, sourceLabel: 'History' }).catch(function (err) {
      toast((err && err.message) || 'Could not open document');
    });
  }
  var historyList = $('#historyList');
  if (historyList) historyList.addEventListener('click', openHistoryItem);

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
  function dashOr(value) {
    var s = String(value == null ? '' : value).trim();
    return s || '—';
  }

  function formatProfileWhen(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString('en-AU', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    });
  }

  function profileKvRows(rows) {
    return (
      '<div class="prof-detail-card"><div class="kv-list">' +
      rows
        .map(function (r) {
          return (
            '<div class="kv"><span class="k">' +
            esc(r[0]) +
            '</span><span class="v">' +
            esc(r[1]) +
            '</span></div>'
          );
        })
        .join('') +
      '</div></div>'
    );
  }

  function profileToggleRow(id, title, sub, on) {
    return (
      '<div class="row">' +
      '<div class="main"><div class="t">' +
      esc(title) +
      '</div><div class="s">' +
      esc(sub) +
      '</div></div>' +
      '<button type="button" class="sw" id="' +
      esc(id) +
      '" role="switch" aria-checked="' +
      String(!!on) +
      '" aria-pressed="' +
      String(!!on) +
      '" aria-label="' +
      esc(title) +
      '"><i></i></button>' +
      '</div>'
    );
  }

  function loadProfilePrefs() {
    try {
      var raw = localStorage.getItem('ll_mobile_profile_prefs');
      if (!raw) return;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return;
      Object.keys(state.profilePrefs).forEach(function (k) {
        if (typeof parsed[k] === 'boolean' || typeof parsed[k] === 'string') {
          state.profilePrefs[k] = parsed[k];
        }
      });
    } catch (e) { /* ignore */ }
  }

  function saveProfilePrefs() {
    try {
      localStorage.setItem('ll_mobile_profile_prefs', JSON.stringify(state.profilePrefs));
    } catch (e) { /* ignore */ }
    refreshProfilePreferenceSubs();
  }

  function refreshProfilePreferenceSubs() {
    var p = state.profilePrefs;
    var ap = $('#profApprovalsSub');
    if (ap) {
      ap.textContent = p.delegateOn
        ? ('Delegating' + (p.delegateTo ? ' · ' + p.delegateTo : ''))
        : (p.autoApproveUnder250 ? 'Auto-approve under A$250 on' : 'Delegation off');
    }
    var n = $('#profNotifySub');
    if (n) {
      var onCount = [p.slaAlerts, p.dailyDigest, p.budgetThreshold].filter(Boolean).length;
      n.textContent = onCount + ' of 3 alerts on';
    }
  }

  function bindProfileSheetToggles(root, map) {
    if (!root) return;
    Object.keys(map).forEach(function (id) {
      var el = root.querySelector('#' + id);
      if (!el) return;
      el.addEventListener('click', function () {
        var on = el.getAttribute('aria-pressed') !== 'true';
        el.setAttribute('aria-pressed', String(on));
        el.setAttribute('aria-checked', String(on));
        map[id](on);
        saveProfilePrefs();
      });
    });
  }

  function employeeProfileSummary(emp) {
    if (!emp) {
      return {
        confirmSub: 'Not linked · ask finance to add you',
        confirmChip: 'Missing',
        confirmTone: 'warn',
        phonesSub: 'No numbers on file',
        bankSub: 'No bank details on file',
        orgSub: 'No organisation details'
      };
    }
    var status = String(emp.status || '').trim();
    var confirmedAt = emp.confirmed_at || emp.confirmedAt || null;
    var sentAt = emp.confirmation_sent_at || emp.confirmationSentAt || null;
    var pending = /pending/i.test(status) || (!confirmedAt && !!sentAt);
    var confirmSub;
    var confirmChip;
    var confirmTone = '';
    if (confirmedAt) {
      confirmSub = 'Confirmed ' + formatProfileWhen(confirmedAt);
      confirmChip = status || 'Active';
      confirmTone = 'pos';
    } else if (sentAt || pending) {
      confirmSub = sentAt
        ? 'Email sent ' + formatProfileWhen(sentAt)
        : 'Awaiting your confirmation';
      confirmChip = status || 'Pending';
      confirmTone = 'warn';
    } else {
      confirmSub = 'On file in LedgerLink';
      confirmChip = status || 'On file';
    }

    var phone1 = String(emp.whatsapp_number || emp.whatsappNumber || '').trim();
    var phone2 = String(emp.whatsapp_number_2 || emp.whatsappNumber2 || '').trim();
    var viber = String(emp.viber_number || emp.viberNumber || '').trim();
    var phones = [phone1, phone2, viber].filter(Boolean);
    var phonesSub = phones.length ? phones[0] + (phones.length > 1 ? ' · +' + (phones.length - 1) : '') : 'No numbers on file';

    var bank = emp.bank || {};
    var bankName = String(bank.bank_name || bank.bankName || '').trim();
    var acct = String(bank.account_number || bank.accountNumber || '').trim();
    var payId = String(bank.pay_id || bank.payId || '').trim();
    var bankBits = [];
    if (bankName) bankBits.push(bankName);
    if (acct) bankBits.push(acct);
    else if (payId) bankBits.push(payId);
    var bankSub = bankBits.length ? bankBits.join(' · ') : 'No bank details on file';

    var dept = String(emp.department || '').trim();
    var loc = String(emp.location || '').trim();
    var orgBits = [dept, loc].filter(Boolean);
    var orgSub = orgBits.length ? orgBits.join(' · ') : (String(emp.role || '').trim() || 'Organisation details');

    return {
      confirmSub: confirmSub,
      confirmChip: confirmChip,
      confirmTone: confirmTone,
      phonesSub: phonesSub,
      bankSub: bankSub,
      orgSub: orgSub
    };
  }

  function renderEmployeeProfile(emp) {
    state.employeeProfile = emp || null;
    state.hasEmployeeProfile = !!(emp && (emp.id || emp.email || emp.name));
    syncRoleSegVisibility();
    var setText = function (id, text) {
      var el = $('#' + id);
      if (el) el.textContent = text;
    };
    var summary = employeeProfileSummary(emp);
    var chip = $('#profConfirmChip');
    setText('profConfirmSub', summary.confirmSub);
    setText('profPhonesSub', summary.phonesSub);
    setText('profBankSub', summary.bankSub);
    setText('profOrgSub', summary.orgSub);
    if (chip) {
      chip.textContent = summary.confirmChip;
      chip.className = 'chip' + (summary.confirmTone ? ' ' + summary.confirmTone : '');
    }

    if (emp && emp.name) {
      setText('profName', emp.name);
      var roleBits = [emp.role || emp.department, emp.division || emp.location]
        .map(function (x) { return String(x || '').trim(); })
        .filter(Boolean);
      if (roleBits.length) setText('profRole', roleBits.join(' · '));
    }
    if (emp && emp.email) setText('profEmail', emp.email);
    refreshProfilePreferenceSubs();
  }

  function openProfileConfirmSheet() {
    var emp = state.employeeProfile;
    var summary = employeeProfileSummary(emp);
    var rows;
    if (!emp) {
      rows = [
        ['Status', 'Not linked'],
        ['Next step', 'Ask finance to add your employee record in LedgerLink']
      ];
    } else {
      rows = [
        ['Status', summary.confirmChip],
        ['Summary', summary.confirmSub],
        ['Confirmation sent', formatProfileWhen(emp.confirmation_sent_at || emp.confirmationSentAt) || '—'],
        ['Confirmed at', formatProfileWhen(emp.confirmed_at || emp.confirmedAt) || '—'],
        ['Employee ID', dashOr(emp.id)]
      ];
    }
    openSheet({
      title: 'Confirmation',
      sub: 'How your LedgerLink employee record is verified',
      body:
        profileKvRows(rows) +
        '<p class="prof-detail-note">When finance adds or updates you, you confirm via email. That status is reflected here.</p>',
      foot: '<button class="btn sm sec" data-close style="flex:1">Close</button>',
      onMount: function (b, f) {
        var btn = f && f.querySelector('[data-close]');
        if (btn) btn.addEventListener('click', closeSheet);
      }
    });
  }

  function openProfileOrgSheet() {
    var emp = state.employeeProfile;
    var rows = emp
      ? [
          ['Role / designation', dashOr(emp.role)],
          ['Department', dashOr(emp.department)],
          ['Division', dashOr(emp.division)],
          ['Location', dashOr(emp.location)],
          ['Supervisor 1', dashOr(emp.supervisor_1 || emp.supervisor1)],
          ['Supervisor 2', dashOr(emp.supervisor_2 || emp.supervisor2)]
        ]
      : [['Status', 'Not linked to an employee master']];
    openSheet({
      title: 'Organisation details',
      sub: 'From your employee master',
      body: profileKvRows(rows),
      foot: '<button class="btn sm sec" data-close style="flex:1">Close</button>',
      onMount: function (b, f) {
        var btn = f && f.querySelector('[data-close]');
        if (btn) btn.addEventListener('click', closeSheet);
      }
    });
  }

  function openProfilePhonesSheet() {
    var emp = state.employeeProfile;
    var rows = emp
      ? [
          ['Mobile 1', dashOr(emp.whatsapp_number || emp.whatsappNumber)],
          ['Mobile 2', dashOr(emp.whatsapp_number_2 || emp.whatsappNumber2)],
          ['Viber', dashOr(emp.viber_number || emp.viberNumber)]
        ]
      : [
          ['Mobile 1', '—'],
          ['Mobile 2', '—'],
          ['Viber', '—']
        ];
    openSheet({
      title: 'Phone numbers',
      sub: 'From your employee master',
      body:
        profileKvRows(rows) +
        '<p class="prof-detail-note">Update phones when you confirm your employee details by email.</p>',
      foot: '<button class="btn sm sec" data-close style="flex:1">Close</button>',
      onMount: function (b, f) {
        var btn = f && f.querySelector('[data-close]');
        if (btn) btn.addEventListener('click', closeSheet);
      }
    });
  }

  function openProfileBankSheet() {
    var emp = state.employeeProfile;
    var bank = (emp && emp.bank) || {};
    var rows = [
      ['Bank', dashOr(bank.bank_name || bank.bankName)],
      ['Account name', dashOr(bank.account_name || bank.accountName)],
      ['BSB', dashOr(bank.bsb)],
      ['Account number', dashOr(bank.account_number || bank.accountNumber)],
      ['PayID', dashOr(bank.pay_id || bank.payId)]
    ];
    openSheet({
      title: 'Bank account',
      sub: 'Reimbursement details on your employee record',
      body:
        profileKvRows(rows) +
        '<p class="prof-detail-note">Bank and PayID come from LedgerLink. Change them through the employee confirmation email from finance.</p>',
      foot: '<button class="btn sm sec" data-close style="flex:1">Close</button>',
      onMount: function (b, f) {
        var btn = f && f.querySelector('[data-close]');
        if (btn) btn.addEventListener('click', closeSheet);
      }
    });
  }

  function openProfileApprovalsSheet() {
    var p = state.profilePrefs;
    openSheet({
      title: 'Approvals',
      sub: 'Delegation and auto-approve preferences on this device',
      body:
        '<div class="rows" style="border:0;margin:0">' +
        profileToggleRow(
          'swDelegate',
          'Delegate my approvals',
          p.delegateOn
            ? (p.delegateTo ? ('On · ' + p.delegateTo) : 'On · choose a delegate')
            : 'Off · queue stays with you',
          p.delegateOn
        ) +
        '<button type="button" class="row" id="delegateTo">' +
        '<div class="main"><div class="t">Delegate to</div><div class="s" id="delTo">' +
        esc(p.delegateTo || 'Not set') +
        '</div></div>' +
        '<svg class="chev" width="9" height="15" viewBox="0 0 9 15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M1.4 1.4 7 7.5l-5.6 6.1"/></svg>' +
        '</button>' +
        profileToggleRow(
          'swAutoApprove',
          'Auto-approve under A$250',
          'Policy-compliant claims only',
          p.autoApproveUnder250
        ) +
        '</div>',
      foot: '<button class="btn sm sec" data-close style="flex:1">Close</button>',
      onMount: function (b, f) {
        var btn = f && f.querySelector('[data-close]');
        if (btn) btn.addEventListener('click', closeSheet);
        bindProfileSheetToggles(b, {
          swDelegate: function (on) {
            state.profilePrefs.delegateOn = on;
            var delSub = b.querySelector('#swDelegate');
            if (delSub && delSub.parentNode) {
              var s = delSub.parentNode.querySelector('.s');
              if (s) {
                s.textContent = on
                  ? (state.profilePrefs.delegateTo
                    ? 'On · ' + state.profilePrefs.delegateTo
                    : 'On · choose a delegate')
                  : 'Off · queue stays with you';
              }
            }
          },
          swAutoApprove: function (on) {
            state.profilePrefs.autoApproveUnder250 = on;
          }
        });
        var delBtn = b.querySelector('#delegateTo');
        if (delBtn) {
          delBtn.addEventListener('click', function () {
            openSheet({
              title: 'Delegate to',
              sub: 'Saved on this device until server-side delegation is available.',
              body:
                '<div style="padding:0 16px 14px">' +
                '<label class="cap-fill-label" for="delegateName">Name or email</label>' +
                '<input id="delegateName" class="cap-fill-input" type="text" maxlength="120" value="' +
                esc(state.profilePrefs.delegateTo || '') +
                '" placeholder="e.g. finance lead" style="width:100%">' +
                '</div>',
              foot:
                '<button class="btn sm sec" data-close style="flex:0 0 92px">Cancel</button>' +
                '<button class="btn sm" id="saveDelegate" style="flex:1">Save</button>',
              onMount: function (b2, f2) {
                var cancel = f2.querySelector('[data-close]');
                if (cancel) cancel.addEventListener('click', closeSheet);
                var save = f2.querySelector('#saveDelegate');
                if (save) {
                  save.addEventListener('click', function () {
                    var input = b2.querySelector('#delegateName');
                    state.profilePrefs.delegateTo = String((input && input.value) || '').trim();
                    if (state.profilePrefs.delegateTo) state.profilePrefs.delegateOn = true;
                    saveProfilePrefs();
                    closeSheet();
                    toast(state.profilePrefs.delegateTo ? 'Delegate saved' : 'Delegate cleared');
                    setTimeout(openProfileApprovalsSheet, 220);
                  });
                }
              }
            });
          });
        }
      }
    });
  }

  function openProfileNotifySheet() {
    var p = state.profilePrefs;
    openSheet({
      title: 'Notifications',
      sub: 'Alert preferences on this device',
      body:
        '<div class="rows" style="border:0;margin:0">' +
        profileToggleRow('swSla', 'SLA breach alerts', 'Push · immediate', p.slaAlerts) +
        profileToggleRow('swDigest', 'Daily approval digest', 'Weekdays 8:00 am AEST', p.dailyDigest) +
        profileToggleRow('swBudget', 'Budget threshold at 90%', 'Push and email', p.budgetThreshold) +
        '</div>',
      foot: '<button class="btn sm sec" data-close style="flex:1">Close</button>',
      onMount: function (b, f) {
        var btn = f && f.querySelector('[data-close]');
        if (btn) btn.addEventListener('click', closeSheet);
        bindProfileSheetToggles(b, {
          swSla: function (on) { state.profilePrefs.slaAlerts = on; },
          swDigest: function (on) { state.profilePrefs.dailyDigest = on; },
          swBudget: function (on) { state.profilePrefs.budgetThreshold = on; }
        });
      }
    });
  }

  function offlineQueueSummary() {
    if (!window.LLCaptureApi) return 'Capture queue unavailable';
    var processing = LLCaptureApi.readPending().filter(function (p) {
      return p.status === 'processing';
    }).length;
    var pending = LLCaptureApi.readPending().length;
    var draftPages = window.LLCapture && LLCapture.getPages ? LLCapture.getPages().length : 0;
    if (!processing && !pending && !draftPages) return 'No queued captures';
    var bits = [];
    if (processing) bits.push(processing + ' processing');
    if (pending) bits.push(pending + ' pending');
    if (draftPages) bits.push(draftPages + ' draft page(s)');
    return bits.join(' · ');
  }

  function openProfileSyncSheet() {
    var queue = offlineQueueSummary();
    openSheet({
      title: 'Sync',
      sub: 'Offline capture queue and ledger connection',
      body:
        profileKvRows([
          ['Offline queue', queue],
          ['Ledger sync', 'Managed in LedgerLink desktop integrations']
        ]) +
        '<p class="prof-detail-note">Queued captures upload when you are online. Ledger posting status is controlled from the desktop workspace.</p>',
      foot: '<button class="btn sm sec" data-close style="flex:1">Close</button>',
      onMount: function (b, f) {
        var btn = f && f.querySelector('[data-close]');
        if (btn) btn.addEventListener('click', closeSheet);
      }
    });
  }

  async function loadEmployeeProfile() {
    if (!LLSession.fetchMyEmployeeMaster) {
      renderEmployeeProfile(null);
      return;
    }
    try {
      var emp = await LLSession.fetchMyEmployeeMaster();
      renderEmployeeProfile(emp || null);
    } catch (err) {
      renderEmployeeProfile(null);
      var sub = $('#profConfirmSub');
      if (sub) {
        sub.textContent = (err && err.message) || 'Could not load employee profile';
      }
    }
  }

  loadProfilePrefs();
  refreshProfilePreferenceSubs();

  var confirmRow = $('#profConfirmRow');
  if (confirmRow) confirmRow.addEventListener('click', openProfileConfirmSheet);
  var orgRow = $('#profOrgRow');
  if (orgRow) orgRow.addEventListener('click', openProfileOrgSheet);
  var phonesRow = $('#profPhonesRow');
  if (phonesRow) phonesRow.addEventListener('click', openProfilePhonesSheet);
  var bankRow = $('#profBankRow');
  if (bankRow) bankRow.addEventListener('click', openProfileBankSheet);
  var approvalsRow = $('#profApprovalsRow');
  if (approvalsRow) approvalsRow.addEventListener('click', openProfileApprovalsSheet);
  var notifyRow = $('#profNotifyRow');
  if (notifyRow) notifyRow.addEventListener('click', openProfileNotifySheet);
  var syncRow = $('#profSyncRow');
  if (syncRow) syncRow.addEventListener('click', openProfileSyncSheet);

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
    items: function () {
      closeSheet();
      if (String(state.itemTab).indexOf('dt:') !== 0) {
        var first = (state.mobileQaItems || []).filter(function (i) {
          return i && i.enabled !== false && i.documentTypeCode;
        })[0];
        state.itemTab = first ? myItemTabKey(first) : 'all';
      }
      renderItems();
      showScreen('items');
    },
    'items-advances': function () {
      closeSheet();
      var adv = (state.mobileQaItems || []).find(function (i) {
        return (
          i &&
          i.enabled !== false &&
          String(i.teamExpenseKind || '').toLowerCase() === 'advance_requisition'
        );
      });
      state.itemTab = adv ? myItemTabKey(adv) : state.itemTab;
      renderItems();
      showScreen('items');
    },
    history: function () { closeSheet(); showScreen('history'); },
    files: function () { closeSheet(); setFileView('grid'); showScreen('files'); },
    analysis: function () { closeSheet(); setFileView('grid'); showScreen('files'); },
    'files-list': function () { closeSheet(); setFileView('list'); showScreen('files'); },
    profile: function () { closeSheet(); showScreen('profile'); }
  };
  function setRole(r) {
    if (!state.dualRole) {
      r = canActAsApprover() && !isEmployeeTenantRole() ? 'approver' : 'employee';
    } else if (r === 'approver' && !canActAsApprover()) {
      r = 'employee';
    } else if (r === 'employee' && !state.hasEmployeeProfile) {
      r = 'approver';
    }
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

  async function loadTenantCurrency() {
    try {
      if (!LLSession.fetchInstitutionSettings) return;
      var inst = await LLSession.fetchInstitutionSettings();
      var code = String((inst && inst.currency) || '').trim().toUpperCase();
      if (!code) return;
      state.tenantCurrency = code;
      state.currency = code;
      renderHomeBudget();
      renderHomeAdvance();
      renderHome();
    } catch (e) {
      /* keep default until institution loads */
    }
  }

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
        return Promise.all([
          LLSession.fetchPermissions(),
          loadTenantCurrency()
        ]);
      })
      .then(function (results) {
        var perms = results && results[0];
        // Resolve employee profile before role chrome so dual-role defaults are correct.
        return loadEmployeeProfile().then(function () {
          return applyPrivileges(perms).then(function () {
            return Promise.all([
              loadLiveApprovals(),
              loadMyItems(),
              loadHomeFinance()
            ]);
          });
        });
      })
      .catch(function (err) {
        if (err && err.status === 401) {
          LLSession.clearSession();
          location.replace(LLSession.loginUrl());
          return;
        }
        // Permissions failed — treat as employee (capture only), still load home finance.
        void loadTenantCurrency();
        void loadEmployeeProfile().then(function () {
          void applyPrivileges({ permissions: {} });
          renderApprovals();
          void Promise.all([loadMyItems(), loadHomeFinance()]);
        });
      });
  })();
})();
