/* LedgerLink invoice upload / poll / patch / confirm for mobile capture. */
(function (global) {
  'use strict';

  var PIPELINE_ACTIVE = {
    pending: 1,
    parsing: 1,
    validating: 1,
    mapping: 1,
    journaling: 1,
    reconciling: 1
  };

  var POLL_MS = 2000;
  var POLL_TIMEOUT_MS = 90000;
  var PENDING_KEY = 'll_mobile_pending';

  function apiBase() {
    return LLSession && typeof LLSession.apiBase === 'function'
      ? LLSession.apiBase()
      : '';
  }

  function authHeaders(extra) {
    return LLSession.authHeaders(extra || {});
  }

  function unwrap(json) {
    if (json && typeof json === 'object' && 'data' in json) return json.data;
    return json;
  }

  function parseError(json, res) {
    var detail =
      (json && (json.detail || (json.error && json.error.message))) || res.statusText;
    if (typeof detail !== 'string') detail = res.statusText || 'Request failed';
    var err = new Error(detail);
    err.status = res.status;
    return err;
  }

  async function apiFetch(path, init) {
    var res = await fetch(apiBase() + path, init);
    var json = null;
    try {
      json = await res.json();
    } catch (e) {
      json = null;
    }
    if (!res.ok) throw parseError(json, res);
    return { data: unwrap(json), meta: json && json.meta, raw: json };
  }

  async function uploadInvoice(file, options) {
    var fd = new FormData();
    var name = (file && file.name) || (file && file.type === 'application/pdf' ? 'capture.pdf' : 'capture.jpg');
    fd.append('file', file, name);
    var params = new URLSearchParams();
    var pdt = options && options.purchaseDocumentType;
    if (pdt === 'po' || pdt === 'grn' || pdt === 'invoice') {
      params.set('purchase_document_type', pdt);
    }
    var intent = options && options.teamExpenseIntent;
    if (
      intent === 'expense_claim' ||
      intent === 'advance_requisition' ||
      intent === 'vendor_invoice'
    ) {
      params.set('team_expense_intent', intent);
    }
    var q = params.toString() ? ('?' + params.toString()) : '';
    var res = await fetch(apiBase() + '/api/invoices/upload' + q, {
      method: 'POST',
      body: fd,
      headers: authHeaders()
    });
    var json = null;
    try {
      json = await res.json();
    } catch (e) {
      json = null;
    }
    if (!res.ok) throw parseError(json, res);
    var invoice = unwrap(json);
    if (invoice && invoice.status === 'duplicate_skipped') {
      var dup = new Error('Duplicate document — already in LedgerLink');
      dup.status = 409;
      dup.invoice = invoice;
      throw dup;
    }
    var segmentCount = (json.meta && json.meta.segment_count) || 1;
    var segmentInvoiceIds =
      json.meta && json.meta.segment_invoice_ids && json.meta.segment_invoice_ids.length
        ? json.meta.segment_invoice_ids
        : [invoice.id];
    return { invoice: invoice, segmentCount: segmentCount, segmentInvoiceIds: segmentInvoiceIds };
  }

  async function listDocumentTypes() {
    var result = await apiFetch('/api/rule-book/config?fields=document_types', {
      method: 'GET',
      headers: authHeaders(),
      cache: 'no-store'
    });
    var rows =
      (result.data && (result.data.document_types || result.data.documentTypes)) ||
      [];
    if (!Array.isArray(rows)) return [];
    return rows
      .filter(function (dt) {
        return dt && dt.enabled !== false && String(dt.code || '').trim();
      })
      .map(function (dt) {
        return {
          code: String(dt.code || '').trim().toUpperCase(),
          title: String(dt.title || dt.short_title || dt.shortTitle || dt.code || '').trim(),
          requiredFields: dt.required_fields || dt.requiredFields || [],
          extractionFields: dt.extraction_fields || dt.extractionFields || [],
          routeTarget: dt.route_target || dt.routeTarget || '',
          teamExpenseKind: dt.team_expense_kind || dt.teamExpenseKind || ''
        };
      })
      .sort(function (a, b) {
        return a.title.localeCompare(b.title);
      });
  }

  function formKeysForDocumentType(dt) {
    var infra = { attachment_name: 1, document_text: 1 };
    function clean(list) {
      var out = [];
      var seen = {};
      (list || []).forEach(function (raw) {
        var key = String(raw || '').trim().toLowerCase();
        if (!key || seen[key] || infra[key]) return;
        seen[key] = 1;
        out.push(key);
      });
      return out;
    }
    var required = clean(dt && dt.requiredFields);
    var extraction = clean(dt && dt.extractionFields);
    var seen = {};
    var out = [];
    required.concat(extraction).forEach(function (key) {
      if (seen[key]) return;
      seen[key] = 1;
      out.push(key);
    });
    // Team expense claims/advances always need multi line-item entry on Fill form.
    var kind = String((dt && dt.teamExpenseKind) || '').trim().toLowerCase();
    var route = String((dt && dt.routeTarget) || '').trim().toLowerCase();
    var isTeamExpense =
      kind === 'expense_claim' ||
      kind === 'advance_requisition' ||
      route.indexOf('team') >= 0;
    if (isTeamExpense && !seen.line_items) {
      out.push('line_items');
    }
    return out;
  }

  function requiredKeysForDocumentType(dt) {
    var infra = { attachment_name: 1, document_text: 1 };
    function clean(list) {
      var out = [];
      var seen = {};
      (list || []).forEach(function (raw) {
        var key = String(raw || '').trim().toLowerCase();
        if (!key || seen[key] || infra[key]) return;
        seen[key] = 1;
        out.push(key);
      });
      return out;
    }
    var required = clean(dt && dt.requiredFields);
    if (!required.length) {
      return formKeysForDocumentType(dt);
    }
    var kind = String((dt && dt.teamExpenseKind) || '').trim().toLowerCase();
    var route = String((dt && dt.routeTarget) || '').trim().toLowerCase();
    var isTeamExpense =
      kind === 'expense_claim' ||
      kind === 'advance_requisition' ||
      route.indexOf('team') >= 0;
    if (isTeamExpense && required.indexOf('line_items') < 0) {
      required = required.concat(['line_items']);
    }
    return required;
  }

  async function manualCapture(file, documentTypeCode, fields) {
    var fd = new FormData();
    var name =
      (file && file.name) ||
      (file && file.type === 'application/pdf' ? 'reference.pdf' : 'reference.jpg');
    fd.append('file', file, name);
    fd.append('document_type_code', String(documentTypeCode || '').trim().toUpperCase());
    fd.append('fields', JSON.stringify(fields || {}));
    var res = await fetch(apiBase() + '/api/invoices/manual-capture', {
      method: 'POST',
      body: fd,
      headers: authHeaders()
    });
    var json = null;
    try {
      json = await res.json();
    } catch (e) {
      json = null;
    }
    if (!res.ok) throw parseError(json, res);
    var invoice = unwrap(json);
    if (invoice && invoice.status === 'duplicate_skipped') {
      var dup = new Error('Duplicate document — already in LedgerLink');
      dup.status = 409;
      dup.invoice = invoice;
      throw dup;
    }
    return { invoice: invoice };
  }

  async function getInvoice(id) {
    var result = await apiFetch('/api/invoices/' + id, {
      method: 'GET',
      headers: authHeaders(),
      cache: 'no-store'
    });
    return result.data;
  }

  async function updateInvoice(id, body) {
    var result = await apiFetch('/api/invoices/' + id, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body || {})
    });
    return result.data;
  }

  async function confirmProcess(id) {
    var result = await apiFetch('/api/invoices/' + id + '/confirm-process', {
      method: 'POST',
      headers: authHeaders()
    });
    return result.data;
  }

  function isPipelineActive(status) {
    return !!PIPELINE_ACTIVE[String(status || '')];
  }

  /**
   * Poll until invoice leaves pipeline statuses.
   * onTick(invoice) optional; returns final invoice.
   */
  async function watchUntilSettled(invoiceId, options) {
    var timeoutMs = (options && options.timeoutMs) || POLL_TIMEOUT_MS;
    var intervalMs = (options && options.intervalMs) || POLL_MS;
    var onTick = options && options.onTick;
    var shouldCancel = options && options.shouldCancel;
    var deadline = Date.now() + timeoutMs;
    var inv = await getInvoice(invoiceId);
    if (onTick) onTick(inv);
    while (isPipelineActive(inv.status)) {
      if (shouldCancel && shouldCancel()) {
        var cancelErr = new Error('Poll cancelled');
        cancelErr.cancelled = true;
        throw cancelErr;
      }
      if (Date.now() > deadline) {
        var t = new Error('Processing is taking longer than expected');
        t.timeout = true;
        t.invoice = inv;
        throw t;
      }
      await new Promise(function (r) { setTimeout(r, intervalMs); });
      inv = await getInvoice(invoiceId);
      if (onTick) onTick(inv);
    }
    return inv;
  }

  function readPending() {
    try {
      var raw = sessionStorage.getItem(PENDING_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  function writePending(list) {
    try {
      sessionStorage.setItem(PENDING_KEY, JSON.stringify(list || []));
    } catch (e) { /* ignore */ }
  }

  function upsertPending(entry) {
    var list = readPending().filter(function (x) {
      return Number(x.invoiceId) !== Number(entry.invoiceId);
    });
    list.unshift(entry);
    writePending(list.slice(0, 20));
    return list;
  }

  function updatePending(invoiceId, patch) {
    var list = readPending().map(function (x) {
      if (Number(x.invoiceId) !== Number(invoiceId)) return x;
      return Object.assign({}, x, patch);
    });
    writePending(list);
    return list;
  }

  function removePending(invoiceId) {
    writePending(
      readPending().filter(function (x) {
        return Number(x.invoiceId) !== Number(invoiceId);
      })
    );
  }

  function clearPending() {
    try {
      sessionStorage.removeItem(PENDING_KEY);
    } catch (e) { /* ignore */ }
  }

  function confidenceBand(score) {
    if (score == null || !isFinite(score)) return 'mid';
    if (score >= 95) return 'hi';
    if (score >= 80) return 'mid';
    return 'low';
  }

  var FIELD_LABELS = {
    vendor: 'Vendor',
    employee_name: 'Employee name',
    abn: 'Business registration number',
    invoice_no: 'Invoice number',
    proforma_invoice_no: 'Proforma invoice number',
    invoice_date: 'Invoice date',
    due_date: 'Due date',
    po_reference: 'PO reference',
    so_reference: 'SO reference',
    cost_centre: 'Cost centre',
    currency: 'Currency',
    subtotal: 'Subtotal',
    gst: 'Tax (GST/VAT)',
    gst_rate: 'Tax rate (%)',
    total: 'Total',
    line_items: 'Line items',
    bank_details: 'Bank details',
    attachment_name: 'Attachment name',
    document_heading: 'Document heading',
    document_text: 'Document text (OCR body)',
    billing_address: 'Billing address',
    seller_name: 'Seller name',
    seller_tax_id: 'Seller tax ID',
    seller_address: 'Seller address',
    buyer_name: 'Buyer name',
    buyer_tax_id: 'Buyer tax ID',
    buyer_address: 'Buyer address',
    email_subject: 'Email subject',
    email_sender: 'Sender (email or mobile)',
    account_code: 'Account code',
    account_name: 'Account name',
    category: 'Category',
    project: 'Project'
  };

  var SCALAR_PATCH_KEYS = {
    vendor: 1,
    abn: 1,
    invoice_no: 1,
    po_reference: 1,
    cost_centre: 1,
    billing_address: 1,
    invoice_date: 1,
    due_date: 1,
    currency: 1,
    subtotal: 1,
    gst: 1,
    total: 1,
    account_code: 1,
    account_name: 1,
    email_sender: 1
  };

  var NON_EDITABLE_KEYS = {
    line_items: 1,
    bank_details: 1,
    attachment_name: 1,
    document_text: 1
  };

  var INTERNAL_EXTRACTED_KEYS = {
    perspective: 1,
    llm_perspective: 1,
    vision_bundle_kind: 1,
    vision_bundle_key: 1,
    vision_bundle_custom_field: 1,
    document_summary: 1,
    document_role_hints: 1,
    vision_type_suggest_confidence: 1,
    vision_header_confidence: 1,
    canonical_document_type: 1,
    translation_applied: 1,
    translation_skip_reason: 1,
    translation_source_language: 1,
    currency_review_required: 1,
    currency_review_reason: 1
  };

  var FALLBACK_FIELD_KEYS = [
    'vendor', 'employee_name', 'abn', 'invoice_no', 'proforma_invoice_no',
    'po_reference', 'so_reference', 'cost_centre', 'invoice_date', 'due_date',
    'subtotal', 'gst', 'gst_rate', 'total', 'currency', 'document_heading',
    'billing_address', 'email_sender', 'email_subject', 'account_code', 'account_name',
    'seller_name', 'seller_tax_id', 'seller_address', 'buyer_name', 'buyer_tax_id', 'buyer_address'
  ];

  function fieldLabel(key) {
    if (FIELD_LABELS[key]) return FIELD_LABELS[key];
    return String(key || '')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function readExtractionValue(inv, key) {
    if (!inv || !key) return '';
    if (key === 'attachment_name') return String(inv.email_attachment_name || '').trim();
    if (key === 'document_text') return String(inv.document_text || '').trim();
    if (key === 'bank_details') {
      var parts = [inv.bank_bsb, inv.bank_account].filter(Boolean);
      return parts.join(' · ');
    }
    if (key === 'line_items') {
      var n = (inv.line_items && inv.line_items.length) || 0;
      return n ? n + ' line' + (n === 1 ? '' : 's') : '';
    }
    var ef = inv.extracted_fields || {};
    if (ef[key] != null && String(ef[key]).trim() !== '') return String(ef[key]).trim();
    if (inv[key] != null && String(inv[key]).trim() !== '') return String(inv[key]).trim();
    return '';
  }

  function extractionKeysForInvoice(inv) {
    var keys = [];
    var fromDt = inv && inv.document_type_extraction_fields;
    if (Array.isArray(fromDt) && fromDt.length) {
      keys = fromDt.slice();
    } else {
      FALLBACK_FIELD_KEYS.forEach(function (k) {
        if (readExtractionValue(inv, k)) keys.push(k);
      });
      Object.keys((inv && inv.extracted_fields) || {}).forEach(function (k) {
        if (INTERNAL_EXTRACTED_KEYS[k]) return;
        if (readExtractionValue(inv, k) && keys.indexOf(k) < 0) keys.push(k);
      });
    }
    // Always surface populated extras that aren't internal
    Object.keys((inv && inv.extracted_fields) || {}).forEach(function (k) {
      if (INTERNAL_EXTRACTED_KEYS[k] || NON_EDITABLE_KEYS[k]) return;
      if (readExtractionValue(inv, k) && keys.indexOf(k) < 0) keys.push(k);
    });
    return keys.filter(function (k, i, arr) {
      return k && arr.indexOf(k) === i && !INTERNAL_EXTRACTED_KEYS[k];
    });
  }

  function isEditableKey(key) {
    return !NON_EDITABLE_KEYS[key];
  }

  function fieldConfidence(inv, key) {
    var conf = (inv && inv.extraction_field_confidence) || {};
    var score = conf[key];
    if (score == null && key === 'invoice_date') score = conf.date;
    if (score == null && key === 'cost_centre') score = conf.cost_center;
    if (score == null && readExtractionValue(inv, key)) score = 86;
    if (score == null) score = 40;
    return confidenceBand(score);
  }

  /** @deprecated alias — prefer readExtractionValue with real keys */
  function fieldValue(inv, key) {
    var aliases = {
      date: 'invoice_date',
      cc: 'cost_centre',
      dt: 'document_type_code'
    };
    var k = aliases[key] || key;
    if (key === 'dt') {
      return String(inv.document_type_code || inv.document_heading || '').trim();
    }
    return readExtractionValue(inv, k);
  }

  function buildUpdatePayload(edits) {
    var body = {};
    var extracted = {};
    Object.keys(edits || {}).forEach(function (key) {
      var val = edits[key];
      if (val == null) return;
      var trimmed = String(val).trim();
      if (SCALAR_PATCH_KEYS[key]) {
        body[key] = trimmed === '' ? null : trimmed;
      } else if (!NON_EDITABLE_KEYS[key]) {
        if (trimmed !== '') extracted[key] = trimmed;
      }
    });
    if (Object.keys(extracted).length) body.extracted_fields = extracted;
    return body;
  }

  async function listRecentInvoices(pageSize) {
    var size = pageSize || 20;
    var result = await apiFetch('/api/invoices?page=1&page_size=' + size, {
      method: 'GET',
      headers: authHeaders(),
      cache: 'no-store'
    });
    var rows = Array.isArray(result.data) ? result.data : [];
    return rows;
  }

  /** Team Expenses / captures for the signed-in employee (mine=self). */
  async function listMyInvoices(options) {
    var opts = options || {};
    var params = new URLSearchParams();
    params.set('page', '1');
    params.set('page_size', String(opts.pageSize || 50));
    params.set('include_total', 'false');
    params.set('mine', 'true');
    params.set('mine_scope', opts.mineScope || 'self');
    if (opts.routeTarget) params.set('route_target', opts.routeTarget);
    if (opts.teamExpenseKind) params.set('team_expense_kind', opts.teamExpenseKind);
    var result = await apiFetch('/api/invoices?' + params.toString(), {
      method: 'GET',
      headers: authHeaders(),
      cache: 'no-store'
    });
    var rows = Array.isArray(result.data) ? result.data : [];
    // Client-side guard: drop anything not clearly this user (stale cache / broad stamps).
    var me = normEmail(
      (typeof LLSession !== 'undefined' && LLSession.getUser && LLSession.getUser() && LLSession.getUser().email) ||
      ''
    );
    if (!me) return rows;
    return rows.filter(function (inv) {
      var emp = normEmail(inv.employee_email);
      var up = normEmail(inv.uploaded_by_email);
      if (emp && emp === me) return true;
      if (up && up === me) {
        var src = String(inv.capture_source || '').toLowerCase();
        if (src === 'upload' || src === 'whatsapp' || src === 'viber' || src === 'slack') return true;
        if (!src && !inv.connected_mailbox_id) return true;
      }
      return false;
    });
  }

  async function listMyClaims(pageSize) {
    return listMyInvoices({
      pageSize: pageSize,
      routeTarget: 'Team Expenses',
      teamExpenseKind: 'expense_claim'
    });
  }

  async function listMyAdvances(pageSize) {
    return listMyInvoices({
      pageSize: pageSize,
      routeTarget: 'Team Expenses',
      teamExpenseKind: 'advance_requisition'
    });
  }

  async function listMyOtherInvoices(pageSize) {
    var rows = await listMyInvoices({ pageSize: pageSize || 50 });
    return rows.filter(function (inv) {
      var route = String(inv.route_target || '').trim();
      var kind = String(inv.team_expense_kind || '').trim().toLowerCase();
      if (route === 'Team Expenses' && kind === 'advance_requisition') return false;
      if (route === 'Team Expenses' && (kind === 'expense_claim' || !kind)) return false;
      return true;
    });
  }

  function statusChip(inv) {
    var status = String(inv.status || '').toLowerCase();
    var evalStatus = String(inv.evaluation_status || '').toLowerCase();
    if (status === 'posted' || status === 'paid' || status === 'exported') {
      return { tone: 'pos', label: status === 'paid' ? 'Paid' : 'Posted', prog: 100 };
    }
    if (status === 'exception' || evalStatus === 'needs_review' || evalStatus === 'pending_approval') {
      return { tone: 'warn', label: 'Needs review', prog: 55 };
    }
    if (status === 'rejected' || status === 'duplicate_skipped') {
      return { tone: 'neg', label: status === 'rejected' ? 'Rejected' : 'Duplicate', prog: 20 };
    }
    if (PIPELINE_ACTIVE[status]) {
      return { tone: 'acc', label: 'Processing', prog: 35 };
    }
    if (status === 'approved' || evalStatus === 'auto_coded') {
      return { tone: 'acc', label: 'In approval', prog: 70 };
    }
    return { tone: 'acc', label: status || 'Open', prog: 45 };
  }

  function formatItemDate(inv) {
    var raw = inv.invoice_date || inv.created_at || '';
    if (!raw) return '';
    try {
      var d = new Date(raw);
      if (isNaN(d.getTime())) return String(raw).slice(0, 10);
      return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' }).format(d);
    } catch (e) {
      return String(raw).slice(0, 10);
    }
  }

  function invoiceToMyItem(inv) {
    var chip = statusChip(inv);
    var amt = Number(inv.total);
    if (!isFinite(amt)) amt = 0;
    var title = String(inv.vendor || inv.document_ref || ('#' + inv.id)).trim();
    var ref = String(inv.document_ref || inv.invoice_no || ('#' + inv.id)).trim();
    var dt = String(inv.document_type_code || '').trim();
    var date = formatItemDate(inv);
    var sub = [ref, date, dt].filter(Boolean).join(' · ');
    return {
      id: Number(inv.id),
      t: title,
      s: sub,
      amt: amt,
      chip: [chip.tone, chip.label],
      prog: chip.prog,
      tone: chip.tone,
      kind: String(inv.team_expense_kind || ''),
      status: String(inv.status || ''),
      route: String(inv.route_target || '')
    };
  }

  function normEmail(value) {
    return String(value || '').trim().toLowerCase();
  }

  function matchEmployeeRow(rows, email) {
    var want = normEmail(email);
    if (!want || !Array.isArray(rows)) return null;
    for (var i = 0; i < rows.length; i++) {
      if (normEmail(rows[i].email) === want) return rows[i];
    }
    return null;
  }

  async function listEmployeeMasters() {
    var result = await apiFetch('/api/employee-masters', {
      method: 'GET',
      headers: authHeaders(),
      cache: 'no-store'
    });
    return Array.isArray(result.data) ? result.data : [];
  }

  async function fetchBudgetUtilization() {
    try {
      var result = await apiFetch('/api/reports/team-expenses/budget-utilization', {
        method: 'GET',
        headers: authHeaders(),
        cache: 'no-store'
      });
      return Array.isArray(result.data) ? result.data : [];
    } catch (e) {
      return null;
    }
  }

  async function fetchAdvanceSettlement() {
    try {
      var result = await apiFetch('/api/reports/team-expenses/advance-settlement', {
        method: 'GET',
        headers: authHeaders(),
        cache: 'no-store'
      });
      return Array.isArray(result.data) ? result.data : [];
    } catch (e) {
      return null;
    }
  }

  /**
   * Home finance strip for the signed-in employee (budget + advance float).
   * Prefers Team Expense reports; falls back to employee master + my advances.
   */
  async function loadMyHomeFinance(userEmail) {
    var email = normEmail(userEmail);
    var out = {
      budget: 0,
      claimed: 0,
      approved: 0,
      remaining: 0,
      hasBudget: false,
      advance: null
    };

    var budgetRows = await fetchBudgetUtilization();
    var budgetRow = budgetRows ? matchEmployeeRow(budgetRows, email) : null;
    if (budgetRow) {
      out.budget = Number(budgetRow.budget_quarterly) || 0;
      out.claimed = Number(budgetRow.qtd_spent) || 0;
      out.remaining =
        budgetRow.quarterly_remaining != null
          ? Number(budgetRow.quarterly_remaining)
          : out.budget - out.claimed;
      out.hasBudget = out.budget > 0 || out.claimed > 0;
    } else {
      try {
        var masters = await listEmployeeMasters();
        var emp = matchEmployeeRow(masters, email);
        if (emp) {
          var limits = emp.spending_limits || emp.budget || {};
          out.budget = Number(limits.quarterly) || 0;
          out.claimed = Number(emp.qtd_spent) || 0;
          out.remaining = out.budget - out.claimed;
          out.hasBudget = out.budget > 0 || out.claimed > 0;
        }
      } catch (e) {
        /* leave zeros */
      }
    }

    try {
      var claims = await listMyClaims(50);
      var approved = 0;
      claims.forEach(function (inv) {
        var st = String(inv.status || '').toLowerCase();
        if (st === 'posted' || st === 'paid' || st === 'exported') {
          var n = Number(inv.total);
          if (isFinite(n)) approved += n;
        }
      });
      out.approved = approved;
      if (!out.hasBudget && claims.length) {
        var claimedSum = 0;
        claims.forEach(function (inv) {
          var n = Number(inv.total);
          if (isFinite(n)) claimedSum += n;
        });
        out.claimed = claimedSum;
      }
    } catch (e) {
      /* keep approved 0 */
    }

    var advRows = await fetchAdvanceSettlement();
    var advRow = advRows ? matchEmployeeRow(advRows, email) : null;
    if (advRow) {
      var taken = Number(advRow.advance_taken) || 0;
      var used = Number(advRow.advance_used) || 0;
      var outstanding =
        Number(advRow.advance_ledger_balance) ||
        Number(advRow.available_advance) ||
        Math.max(taken - used, 0);
      if (outstanding > 0 || taken > 0) {
        out.advance = {
          amount: outstanding > 0 ? outstanding : taken,
          taken: taken,
          acquitted: used,
          outstanding: outstanding,
          purpose: String(advRow.department || advRow.name || 'Staff advance').trim(),
          ref: String(advRow.advance_sub_ledger || advRow.employee_id || '').trim() || 'Advance',
          issued: '',
          due: '',
          daysLeft: null,
          invoiceId: null
        };
      }
    } else {
      try {
        var advances = await listMyAdvances(50);
        if (advances.length) {
          var open = advances[0];
          var amt = Number(open.total) || 0;
          out.advance = {
            amount: amt,
            taken: amt,
            acquitted: 0,
            outstanding: amt,
            purpose: String(open.vendor || 'Staff advance').trim(),
            ref: String(open.document_ref || ('#' + open.id)).trim(),
            issued: formatItemDate(open),
            due: '',
            daysLeft: null,
            invoiceId: Number(open.id)
          };
        }
      } catch (e) {
        /* no advance */
      }
    }

    return out;
  }

  function policyBanner(inv) {
    var evalStatus = String(inv.evaluation_status || '').trim();
    if (inv.status === 'duplicate_skipped') {
      return {
        tone: 'neg',
        title: 'Duplicate detected',
        body: 'This file matches an existing document. It was not queued again.'
      };
    }
    if (evalStatus === 'pending_vendor') {
      return {
        tone: 'warn',
        title: 'Vendor confirmation needed',
        body: 'Extraction found a vendor that is not on your master list yet.'
      };
    }
    if (inv.status === 'exception') {
      return {
        tone: 'warn',
        title: 'Needs review',
        body: inv.exception_reason ||
          inv.validation_message ||
          'Policy or validation flagged this document before it can continue.'
      };
    }
    return null;
  }

  global.LLCaptureApi = {
    PIPELINE_ACTIVE: PIPELINE_ACTIVE,
    POLL_MS: POLL_MS,
    uploadInvoice: uploadInvoice,
    listDocumentTypes: listDocumentTypes,
    formKeysForDocumentType: formKeysForDocumentType,
    requiredKeysForDocumentType: requiredKeysForDocumentType,
    manualCapture: manualCapture,
    getInvoice: getInvoice,
    updateInvoice: updateInvoice,
    confirmProcess: confirmProcess,
    listRecentInvoices: listRecentInvoices,
    listMyInvoices: listMyInvoices,
    listMyClaims: listMyClaims,
    listMyAdvances: listMyAdvances,
    listMyOtherInvoices: listMyOtherInvoices,
    invoiceToMyItem: invoiceToMyItem,
    loadMyHomeFinance: loadMyHomeFinance,
    isPipelineActive: isPipelineActive,
    watchUntilSettled: watchUntilSettled,
    readPending: readPending,
    upsertPending: upsertPending,
    updatePending: updatePending,
    removePending: removePending,
    clearPending: clearPending,
    fieldValue: fieldValue,
    readExtractionValue: readExtractionValue,
    fieldLabel: fieldLabel,
    fieldConfidence: fieldConfidence,
    extractionKeysForInvoice: extractionKeysForInvoice,
    isEditableKey: isEditableKey,
    buildUpdatePayload: buildUpdatePayload,
    policyBanner: policyBanner,
    confidenceBand: confidenceBand
  };
})(window);
