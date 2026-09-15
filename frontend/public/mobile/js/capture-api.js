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
    params.set('capture_source', 'app');
    var q = '?' + params.toString();
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
    function inferKindFromLabels(title, shortTitle) {
      var blob = [title, shortTitle]
        .map(function (x) { return String(x || '').trim().toLowerCase(); })
        .filter(Boolean)
        .join(' ')
        .trim();
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
    function reconcileKind(configured, title, shortTitle) {
      var inferred = inferKindFromLabels(title, shortTitle);
      var raw = String(configured || '').trim().toLowerCase();
      if (raw === 'expense_against_advance') raw = 'expense_claim';
      var pinned =
        raw === 'expense_claim' ||
        raw === 'advance_requisition' ||
        raw === 'direct_payment'
          ? raw
          : '';
      if (inferred) {
        if (pinned && pinned !== inferred) return inferred;
        return pinned || inferred;
      }
      return pinned;
    }
    return rows
      .filter(function (dt) {
        return dt && dt.enabled !== false && String(dt.code || '').trim();
      })
      .map(function (dt) {
        var title = String(dt.title || dt.short_title || dt.shortTitle || dt.code || '').trim();
        var shortTitle = String(dt.short_title || dt.shortTitle || '').trim();
        var configured = dt.team_expense_kind || dt.teamExpenseKind || '';
        return {
          code: String(dt.code || '').trim().toUpperCase(),
          title: title,
          requiredFields: dt.required_fields || dt.requiredFields || [],
          extractionFields: dt.extraction_fields || dt.extractionFields || [],
          routeTarget: dt.route_target || dt.routeTarget || '',
          teamExpenseKind: reconcileKind(configured, title, shortTitle) || configured || '',
          shortTitle: shortTitle,
          postTo: (function () {
            var raw = dt.post_to || dt.postTo || {};
            return {
              ledger: String(raw.ledger || '').trim(),
              subLedger: String(raw.sub_ledger || raw.subLedger || '').trim()
            };
          })()
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

  /** Mobile Without document — no file, no placeholder image. */
  async function createWithoutDocument(documentTypeCode, fields) {
    var res = await fetch(apiBase() + '/api/invoices/without-document', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        document_type_code: String(documentTypeCode || '').trim().toUpperCase(),
        fields: fields || {}
      })
    });
    var json = null;
    try {
      json = await res.json();
    } catch (e) {
      json = null;
    }
    if (!res.ok) throw parseError(json, res);
    return { invoice: unwrap(json) };
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

  /** Pin Team Expenses journal kind before confirm/process (advance netting needs expense_claim). */
  async function setTeamExpenseKind(id, kind, linkedAdvanceInvoiceId) {
    var body = { team_expense_kind: String(kind || '').trim().toLowerCase() };
    if (linkedAdvanceInvoiceId != null) {
      body.linked_advance_invoice_id = linkedAdvanceInvoiceId;
    }
    var result = await apiFetch('/api/invoices/' + id + '/team-expense-kind', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body)
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
    var vendor = String(inv.vendor || '').trim();
    var heading = String(inv.document_heading || '').trim();
    var kind = String(inv.team_expense_kind || '').trim().toLowerCase();
    var kindTitle =
      kind === 'advance_requisition'
        ? 'Advance'
        : kind === 'direct_payment'
          ? 'Direct payment'
          : kind === 'vendor_invoice'
            ? 'Vendor'
            : kind === 'expense_claim'
              ? 'Claim'
              : '';
    // Legacy mobile submits stamped vendor as "Employee claim" for every DT.
    var syntheticVendor =
      /^employee claim$/i.test(vendor) ||
      (/^[^·]+ claim$/i.test(vendor) && !heading);
    var title = vendor;
    if (!title || syntheticVendor) {
      if (heading && heading.indexOf('Spent for') !== 0) title = heading;
      else if (kindTitle) title = kindTitle;
      else title = String(inv.document_ref || inv.invoice_no || ('#' + inv.id)).trim();
    }
    var ref = String(inv.document_ref || inv.invoice_no || ('#' + inv.id)).trim();
    var dt = String(inv.document_type_code || '').trim().toUpperCase();
    var date = formatItemDate(inv);
    var subParts = [ref, date];
    if (kindTitle) subParts.push(kindTitle);
    else if (dt) subParts.push(dt);
    var sub = subParts.filter(Boolean).join(' · ');
    return {
      id: Number(inv.id),
      t: title,
      s: sub,
      amt: amt,
      currency: String(inv.currency || '').trim().toUpperCase() || '',
      chip: [chip.tone, chip.label],
      prog: chip.prog,
      tone: chip.tone,
      dt: dt,
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

  async function fetchEmployeeSpendDetail() {
    try {
      var result = await apiFetch('/api/reports/team-expenses/employee-spend-detail', {
        method: 'GET',
        headers: authHeaders(),
        cache: 'no-store'
      });
      return Array.isArray(result.data) ? result.data : [];
    } catch (e) {
      return null;
    }
  }

  async function fetchDepartmentBudgetUtilization() {
    try {
      var result = await apiFetch('/api/reports/team-expenses/department-budget-utilization', {
        method: 'GET',
        headers: authHeaders(),
        cache: 'no-store'
      });
      return Array.isArray(result.data) ? result.data : [];
    } catch (e) {
      return null;
    }
  }

  async function fetchDepartmentBudgets() {
    try {
      var result = await apiFetch('/api/department-budgets', {
        method: 'GET',
        headers: authHeaders(),
        cache: 'no-store'
      });
      return Array.isArray(result.data) ? result.data : [];
    } catch (e) {
      return null;
    }
  }

  function leftPctFromUtil(utilPct) {
    if (utilPct == null || !isFinite(Number(utilPct))) return null;
    var left = 1 - Number(utilPct) / 100;
    if (left < 0) left = 0;
    if (left > 1) left = 1;
    return left;
  }

  function leftPctFromBudget(budgetAmt, spentAmt) {
    var budget = Number(budgetAmt) || 0;
    if (budget <= 0) return null;
    var spent = Number(spentAmt) || 0;
    var left = 1 - spent / budget;
    if (left < 0) left = 0;
    if (left > 1) left = 1;
    return left;
  }

  function filterEmployeeRows(rows, email) {
    var want = normEmail(email);
    if (!want || !Array.isArray(rows)) return [];
    return rows.filter(function (row) {
      return normEmail(row.email) === want;
    });
  }

  function currentPeriodKeys() {
    var d = new Date();
    var y = d.getFullYear();
    var m = d.getMonth() + 1;
    var q = Math.floor((m - 1) / 3) + 1;
    return {
      monthly: y + '-' + (m < 10 ? '0' + m : String(m)),
      quarterly: y + '-Q' + q,
      annual: String(y)
    };
  }

  function periodKindRank(kind) {
    var k = String(kind || '').toLowerCase();
    if (k === 'quarterly') return 3;
    if (k === 'annual') return 2;
    if (k === 'monthly') return 1;
    return 0;
  }

  function isCurrentPeriodRow(row, keys) {
    var kind = String(row.period_kind || '').toLowerCase();
    var periodKey = String(row.period_key || '').trim();
    return !!(keys[kind] && keys[kind] === periodKey);
  }

  /**
   * One row per gl_ledger.
   * Prefer current-period pots; if none, use the newest available pot for that GL
   * (so stale months like 2026-08 still show after month roll).
   */
  function pickGlBudgetRows(rows) {
    var keys = currentPeriodKeys();
    var best = {};
    (rows || []).forEach(function (row) {
      var gl = String(row.gl_ledger || '').trim();
      if (!gl) return;
      var allocated = Number(row.allocated) || 0;
      if (allocated <= 0) return;
      var glKey = gl.toLowerCase();
      var current = isCurrentPeriodRow(row, keys) ? 1 : 0;
      var rank = periodKindRank(row.period_kind);
      var periodKey = String(row.period_key || '');
      var prev = best[glKey];
      if (
        !prev ||
        current > prev.current ||
        (current === prev.current && rank > prev.rank) ||
        (current === prev.current && rank === prev.rank && periodKey > prev.periodKey)
      ) {
        best[glKey] = {
          current: current,
          rank: rank,
          periodKey: periodKey,
          row: row
        };
      }
    });
    return Object.keys(best).map(function (k) {
      return best[k].row;
    });
  }

  function budgetLineFromGlRow(row) {
    var gl = String(row.gl_ledger || '').trim();
    var budgetAmt = Number(row.allocated) || 0;
    var spent = Number(row.consumed) || 0;
    var remaining =
      row.remaining != null && isFinite(Number(row.remaining))
        ? Math.max(0, Number(row.remaining))
        : Math.max(0, budgetAmt - spent);
    var fromUtil = leftPctFromUtil(row.utilization_pct);
    var periodLabel = [row.period_kind, row.period_key].filter(Boolean).join(' ');
    return {
      key: gl.toLowerCase(),
      label: gl,
      sub: periodLabel,
      remaining: remaining,
      approved: 0,
      leftPct: fromUtil != null ? fromUtil : leftPctFromBudget(budgetAmt, spent),
      budgetAmt: budgetAmt,
      spent: spent,
      hasBudget: budgetAmt > 0 || spent > 0
    };
  }

  function budgetLineFromSpendRow(row) {
    var sub = String(row.sub_ledger || '').trim();
    var main = String(row.main_gl || '').trim();
    var budgetAmt = Number(row.sub_gl_budget) || 0;
    var spent = Number(row.employee_spend_ytd) || 0;
    var remaining = Math.max(0, budgetAmt - spent);
    var approved = Number(row.cash_reimbursed_ytd) || 0;
    var fromUtil = leftPctFromUtil(row.pct_of_sub_gl_used);
    var leftPct = fromUtil != null ? fromUtil : leftPctFromBudget(budgetAmt, spent);
    var label = sub || main || 'Expense line';
    var matchKeys = [];
    if (sub) matchKeys.push(sub.toLowerCase());
    if (main) matchKeys.push(main.toLowerCase());
    if (!matchKeys.length) matchKeys.push('line');
    return {
      key: matchKeys[0],
      matchKeys: matchKeys,
      label: label,
      sub: main && sub && main !== sub ? main : '',
      remaining: remaining,
      approved: approved,
      leftPct: leftPct,
      budgetAmt: budgetAmt,
      spent: spent,
      hasBudget: budgetAmt > 0 || spent > 0 || approved > 0
    };
  }

  function mergeGlLinesWithMySpend(glLines, spendLines) {
    var byKey = {};
    (glLines || []).forEach(function (line) {
      byKey[line.key] = Object.assign({}, line);
    });
    (spendLines || []).forEach(function (spend) {
      var keys = spend.matchKeys && spend.matchKeys.length ? spend.matchKeys : [spend.key];
      var existing = null;
      for (var i = 0; i < keys.length; i++) {
        if (byKey[keys[i]]) {
          existing = byKey[keys[i]];
          break;
        }
      }
      if (existing) {
        existing.approved = Number(spend.approved) || 0;
        var spendAmt = Number(spend.spent) || 0;
        if (spendAmt > 0) {
          existing.spent = spendAmt;
          var budgetAmt = Number(existing.budgetAmt) || 0;
          if (budgetAmt > 0) {
            existing.remaining = Math.max(0, budgetAmt - spendAmt);
            existing.leftPct = leftPctFromBudget(budgetAmt, spendAmt);
          }
        }
        if (existing.approved > 0 || spendAmt > 0) {
          existing.hasBudget = true;
        }
      } else if (spend.hasBudget) {
        byKey[spend.key] = Object.assign({}, spend);
      }
    });
    return Object.keys(byKey)
      .map(function (k) {
        return byKey[k];
      })
      .sort(function (a, b) {
        return String(a.label).localeCompare(String(b.label));
      });
  }

  async function fetchChartOfAccounts() {
    try {
      var result = await apiFetch('/api/rule-book/config', {
        method: 'GET',
        headers: authHeaders(),
        cache: 'no-store'
      });
      var data = result.data || {};
      return Array.isArray(data.chart_of_accounts) ? data.chart_of_accounts : [];
    } catch (e) {
      return [];
    }
  }

  /** Map Sub-GL → parent name, and parent → child names from COA. */
  function buildCoaIndex(coa) {
    var subToParent = {};
    var parentChildren = {};
    (coa || []).forEach(function (entry) {
      var parent = String(entry.name || '').trim();
      if (!parent) return;
      var children = [];
      (entry.sub_ledgers || []).forEach(function (sub) {
        var child = String((sub && (sub.name || sub.account_name)) || '').trim();
        if (!child) return;
        children.push(child);
        subToParent[child.toLowerCase()] = parent;
      });
      parentChildren[parent.toLowerCase()] = {
        name: parent,
        children: children
      };
    });
    return { subToParent: subToParent, parentChildren: parentChildren };
  }

  function snapshotFromParts(remaining, approved, budgetAmt, spent, hasBudget) {
    return {
      remaining: remaining,
      approved: approved,
      leftPct: leftPctFromBudget(budgetAmt, spent),
      budgetAmt: budgetAmt,
      spent: spent,
      hasBudget: !!hasBudget || remaining > 0 || approved > 0 || spent > 0
    };
  }

  function aggregateBudgetAll(lines) {
    var remaining = 0;
    var approved = 0;
    var budgetSum = 0;
    var spentSum = 0;
    var hasBudget = false;
    (lines || []).forEach(function (line) {
      remaining += Number(line.remaining) || 0;
      approved += Number(line.approved) || 0;
      budgetSum += Number(line.budgetAmt) || 0;
      spentSum += Number(line.spent) || 0;
      if (line.hasBudget) hasBudget = true;
    });
    return snapshotFromParts(remaining, approved, budgetSum, spentSum, hasBudget);
  }

  /**
   * Group flat GL budget lines into parent → sub-ledger tree using COA.
   * Selectable lines include parents and subs; All sums parent-level nodes only
   * (avoids double-counting parent + child pots).
   */
  function buildBudgetTree(lines, coaIndex) {
    var byKey = {};
    (lines || []).forEach(function (line) {
      byKey[line.key] = Object.assign({}, line);
    });

    var groups = {};
    function ensureGroup(parentName) {
      var pk = parentName.toLowerCase();
      if (!groups[pk]) {
        groups[pk] = {
          key: pk,
          label: parentName,
          children: [],
          childKeys: {}
        };
      }
      return groups[pk];
    }

    Object.keys(byKey).forEach(function (key) {
      var line = byKey[key];
      var parentName = coaIndex.subToParent[key];
      if (parentName) {
        var g = ensureGroup(parentName);
        if (!g.childKeys[key]) {
          g.childKeys[key] = 1;
          g.children.push(line);
        }
        return;
      }
      if (coaIndex.parentChildren[key]) {
        ensureGroup(line.label || key);
        groups[key].parentLine = line;
        return;
      }
      // Standalone budgeted GL (no COA parent/child) — treat as its own parent.
      var solo = ensureGroup(line.label || key);
      solo.parentLine = line;
    });

    // Attach COA sub-ledgers that have budget rows under known parents.
    Object.keys(coaIndex.parentChildren).forEach(function (pk) {
      var info = coaIndex.parentChildren[pk];
      var g = groups[pk];
      if (!g) {
        var anyChildBudget = info.children.some(function (c) {
          return !!byKey[c.toLowerCase()];
        });
        if (!anyChildBudget && !byKey[pk]) return;
        g = ensureGroup(info.name);
      }
      info.children.forEach(function (childName) {
        var ck = childName.toLowerCase();
        if (g.childKeys[ck]) return;
        if (byKey[ck]) {
          g.childKeys[ck] = 1;
          g.children.push(byKey[ck]);
        }
      });
      g.children.sort(function (a, b) {
        return String(a.label).localeCompare(String(b.label));
      });
    });

    var tree = Object.keys(groups)
      .map(function (pk) {
        var g = groups[pk];
        var childAgg = aggregateBudgetAll(g.children);
        var parentLine = g.parentLine;
        var nodeSnap = parentLine
          ? snapshotFromParts(
              Number(parentLine.remaining) || 0,
              Number(parentLine.approved) || 0,
              Number(parentLine.budgetAmt) || 0,
              Number(parentLine.spent) || 0,
              parentLine.hasBudget
            )
          : childAgg;
        var selectable = Object.assign(
          {
            key: g.key,
            label: g.label,
            sub: g.children.length
              ? g.children.length + ' sub-ledger' + (g.children.length === 1 ? '' : 's')
              : 'Parent ledger',
            kind: 'parent'
          },
          nodeSnap
        );
        return {
          key: g.key,
          label: g.label,
          kind: 'parent',
          hasChildren: g.children.length > 0,
          line: selectable,
          children: g.children.map(function (c) {
            return Object.assign({}, c, {
              kind: 'sub',
              parentKey: g.key,
              sub: g.label
            });
          })
        };
      })
      .filter(function (node) {
        return node.line.hasBudget || node.children.length > 0;
      })
      .sort(function (a, b) {
        return String(a.label).localeCompare(String(b.label));
      });

    var flat = [];
    tree.forEach(function (node) {
      flat.push(node.line);
      node.children.forEach(function (c) {
        flat.push(c);
      });
    });

    var all = aggregateBudgetAll(tree.map(function (node) {
      return node.line;
    }));

    return { tree: tree, lines: flat, all: all };
  }

  /**
   * Home finance strip for the signed-in employee.
   * GL department budgets are the source of lines; employee spend-detail
   * overlays Approved Amt when the employee has claim activity on a line.
   */
  async function loadMyHomeFinance(userEmail) {
    var email = normEmail(userEmail);
    var out = {
      remaining: 0,
      approved: 0,
      spent: 0,
      leftPct: null,
      hasBudget: false,
      all: { remaining: 0, approved: 0, spent: 0, leftPct: null, hasBudget: false },
      lines: [],
      tree: [],
      coaParentChildren: {},
      advance: null
    };

    var glUtilPromise = fetchDepartmentBudgetUtilization();
    var coaPromise = fetchChartOfAccounts();
    var spendPromise = fetchEmployeeSpendDetail();
    var advancePromise = fetchAdvanceSettlement();

    var settled = await Promise.all([
      glUtilPromise,
      coaPromise,
      spendPromise,
      advancePromise
    ]);
    var glRows = settled[0];
    var coa = settled[1];
    var spendRows = settled[2];
    var advRows = settled[3];

    var glLines = glRows && glRows.length ? pickGlBudgetRows(glRows).map(budgetLineFromGlRow) : [];

    if (!glLines.length) {
      var budgetList = await fetchDepartmentBudgets();
      if (budgetList && budgetList.length) {
        glLines = pickGlBudgetRows(budgetList).map(budgetLineFromGlRow);
      }
    }

    var spendLines = spendRows
      ? filterEmployeeRows(spendRows, email).map(budgetLineFromSpendRow)
      : [];

    var merged = mergeGlLinesWithMySpend(glLines, spendLines);
    var coaIndex = buildCoaIndex(coa);
    out.coaParentChildren = coaIndex.parentChildren || {};
    var built = buildBudgetTree(merged, coaIndex);
    out.tree = built.tree;
    out.lines = built.lines;
    out.all = built.all;
    out.remaining = out.all.remaining;
    out.approved = out.all.approved;
    out.spent = out.all.spent;
    out.leftPct = out.all.leftPct;
    out.hasBudget = out.all.hasBudget;

    var advRow = advRows ? matchEmployeeRow(advRows, email) : null;
    if (advRow) {
      var taken = Number(advRow.advance_taken) || 0;
      var used = Number(advRow.advance_used) || 0;
      var pending = Number(advRow.pending_against_advance) || 0;
      var ledger = Number(advRow.advance_ledger_balance) || 0;
      // Prefer available (ledger − open claims) so Yes-adjust claims reduce the home card immediately.
      var outstanding =
        advRow.available_advance != null && isFinite(Number(advRow.available_advance))
          ? Math.max(0, Number(advRow.available_advance))
          : Math.max(0, ledger - pending || Math.max(taken - used, 0));
      var acquitted = used + pending;
      if (outstanding > 0 || taken > 0 || acquitted > 0) {
        out.advance = {
          amount: outstanding > 0 ? outstanding : taken,
          taken: taken > 0 ? taken : Math.max(ledger, outstanding + acquitted),
          acquitted: acquitted,
          outstanding: outstanding,
          pending: pending,
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
    createWithoutDocument: createWithoutDocument,
    getInvoice: getInvoice,
    updateInvoice: updateInvoice,
    setTeamExpenseKind: setTeamExpenseKind,
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
