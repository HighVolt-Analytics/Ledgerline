/* Capture screen: camera, library, multi-page, upload/poll/review/submit. */
(function (global) {
  'use strict';

  var deps = null;
  var stream = null;
  var mode = 'invoice'; // invoice | receipt | multipage
  var teIntent = 'expense_claim'; // expense_claim | advance_requisition | vendor_invoice
  var capturePath = 'scan'; // scan | fill
  var flashMode = 'auto'; // auto | on | off
  var torchSupported = false;
  var pages = []; // { blob, thumbUrl }
  var composedFile = null;
  var activeInvoice = null;
  var fieldEdits = {};
  var pollController = { cancel: false };
  var uploading = false;
  var documentTypes = [];
  var selectedDt = null;
  var fillFields = {};
  var fillPages = []; // { blob, thumbUrl, name, kind: 'image'|'pdf' }
  var fillSubmitting = false;
  var fillLineItems = []; // { description, qty, unit_price, amount, tax_amount }
  /** After photo from a configured Quick Action, show the details form before submit. */
  var preferClaimDetailsForm = true;
  var preferredDtCode = '';
  var activeQaConfig = null;
  var activeQaTitle = '';
  var claimDetailsPhotoFile = null;
  var claimDetailsPhotoUrl = '';

  function emptyLineItem() {
    return { description: '', qty: '1', unit_price: '', amount: '', tax_amount: '' };
  }

  function clearFillPages() {
    fillPages.forEach(function (p) {
      if (p.thumbUrl) URL.revokeObjectURL(p.thumbUrl);
    });
    fillPages = [];
  }

  var MODE_CFG = {
    receipt: {
      allowsMulti: false,
      autoUploadOnCapture: true,
      alwaysPdf: false,
      purchaseDocumentType: null,
      basename: 'receipt',
      hint: 'One clear photo — uploads automatically.',
      pill: 'Receipt · single shot',
      fileMultiple: false,
      stripActions: false
    },
    invoice: {
      allowsMulti: true,
      autoUploadOnCapture: false,
      alwaysPdf: false,
      purchaseDocumentType: 'invoice',
      basename: 'invoice',
      hint: 'Capture the page. Add more if needed, then Review & upload.',
      pill: 'Document · add pages if needed',
      fileMultiple: true,
      stripActions: true
    },
    multipage: {
      allowsMulti: true,
      autoUploadOnCapture: false,
      alwaysPdf: true,
      purchaseDocumentType: 'invoice',
      basename: 'invoice-multipage',
      hint: 'Photograph each sheet in order, then Review & upload.',
      pill: 'Multi-page · each sheet',
      fileMultiple: true,
      stripActions: true
    }
  };

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }

  function toast(msg) { if (deps && deps.toast) deps.toast(msg); }
  function esc(s) { return deps.esc(s); }
  function fmt(n, c) { return deps.fmt(n, c); }

  function cfg() {
    return MODE_CFG[mode] || MODE_CFG.invoice;
  }

  function allowsMultiPages() {
    return !!cfg().allowsMulti;
  }

  function clearPages() {
    pages.forEach(function (p) {
      if (p.thumbUrl) URL.revokeObjectURL(p.thumbUrl);
    });
    pages = [];
    composedFile = null;
    renderPageStrip();
  }

  function discardDraft() {
    clearPages();
    activeInvoice = null;
    fieldEdits = {};
    uploading = false;
    pollController.cancel = true;
    pollController = { cancel: false };
  }

  function renderPageStrip() {
    var strip = $('#capPageStrip');
    if (!strip) return;
    var c = cfg();
    // Receipt: no strip (auto-uploads). Invoice/multi: show when pages exist.
    if (!pages.length || !c.allowsMulti) {
      strip.hidden = true;
      strip.innerHTML = '';
      return;
    }
    strip.hidden = false;
    var actions = c.stripActions
      ? '<div class="cap-page-actions">' +
        '<button type="button" class="btn sm sec" id="capAddPage">Add page</button>' +
        '<button type="button" class="btn sm" id="capReviewUpload">Review &amp; upload</button>' +
        '</div>'
      : '';
    strip.innerHTML =
      '<div class="cap-pages">' +
      pages.map(function (p, i) {
        return '<div class="cap-page" data-pi="' + i + '">' +
          '<img src="' + p.thumbUrl + '" alt="Page ' + (i + 1) + '">' +
          '<button type="button" class="cap-page-x" data-rm="' + i + '" aria-label="Remove page">×</button>' +
          '<span class="cap-page-n">' + (i + 1) + '</span></div>';
      }).join('') +
      '</div>' + actions;

    strip.querySelectorAll('[data-rm]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var idx = Number(btn.getAttribute('data-rm'));
        if (pages[idx] && pages[idx].thumbUrl) URL.revokeObjectURL(pages[idx].thumbUrl);
        pages.splice(idx, 1);
        renderPageStrip();
      });
    });
    var addBtn = $('#capAddPage', strip);
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        toast('Frame the next page, then tap the shutter');
      });
    }
    var rev = $('#capReviewUpload', strip);
    if (rev) {
      rev.addEventListener('click', function () {
        if (mode === 'multipage' && pages.length < 2) {
          toast('Multi-page usually needs 2+ sheets — add another page, or switch to Invoice');
        }
        void startUploadFlow();
      });
    }
  }

  async function ensureCamera() {
    var video = $('#capVideo');
    if (!video) return;
    if (stream) {
      video.srcObject = stream;
      detectTorchSupport();
      void applyFlashMode(false);
      syncModeChrome();
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      $('#camHint').textContent = 'Camera unavailable — use Choose file to pick a photo.';
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1920 },
          height: { ideal: 1080 }
        }
      });
      video.srcObject = stream;
      video.setAttribute('playsinline', 'true');
      video.muted = true;
      await video.play().catch(function () { /* autoplay policies */ });
      var mock = $('.doc-mock', video.parentElement);
      if (mock) mock.style.display = 'none';
      detectTorchSupport();
      applyFlashMode(false);
      syncModeChrome();
    } catch (err) {
      var hint2 = $('#camHint');
      if (hint2) {
        hint2.textContent = 'Camera permission blocked — use Choose file instead.';
      }
      toast('Camera unavailable');
    }
  }

  function videoTrack() {
    if (!stream) return null;
    var tracks = stream.getVideoTracks();
    return tracks && tracks[0] ? tracks[0] : null;
  }

  function detectTorchSupport() {
    torchSupported = false;
    var track = videoTrack();
    if (!track || typeof track.getCapabilities !== 'function') return;
    try {
      var caps = track.getCapabilities();
      torchSupported = !!(caps && caps.torch);
    } catch (e) {
      torchSupported = false;
    }
  }

  async function applyFlashMode(announce) {
    var labels = {
      auto: 'Flash Auto',
      on: 'Flash On',
      off: 'Flash Off'
    };
    var btn = $('#capFlash');
    if (btn) {
      btn.dataset.flash = flashMode;
      btn.textContent = labels[flashMode] || 'Flash Auto';
      btn.setAttribute('aria-label', labels[flashMode] || 'Flash Auto');
    }
    var track = videoTrack();
    if (!track || !torchSupported) {
      if (announce && flashMode === 'on') {
        toast('Torch not available on this camera');
      }
      return;
    }
    try {
      await track.applyConstraints({
        advanced: [{ torch: flashMode === 'on' }]
      });
    } catch (e) {
      if (announce) toast('Could not change flash');
    }
  }

  function cycleFlash() {
    flashMode = flashMode === 'auto' ? 'on' : flashMode === 'on' ? 'off' : 'auto';
    void applyFlashMode(true);
    if (flashMode === 'auto') toast('Flash · Auto (camera decides)');
    else if (flashMode === 'on') toast(torchSupported ? 'Flash · On' : 'Flash · On (torch unavailable)');
    else toast('Flash · Off');
  }

  function syncModeChrome() {
    var c = cfg();
    var route =
      teIntent === 'advance_requisition'
        ? 'Advance'
        : teIntent === 'vendor_invoice'
          ? 'Vendor'
          : 'Claim';
    var hint = $('#camHint');
    if (hint) hint.textContent = c.hint;
    var pill = $('#camPill') || $('.cam-pill');
    if (pill) pill.textContent = route + ' · ' + c.pill;
    var fileInput = $('#capLibraryInput');
    if (fileInput) {
      if (c.fileMultiple) fileInput.setAttribute('multiple', '');
      else fileInput.removeAttribute('multiple');
      fileInput.accept = mode === 'receipt'
        ? 'image/*,.jpg,.jpeg,.png,.webp'
        : 'image/*,application/pdf,.pdf,.jpg,.jpeg,.png,.webp';
    }
    $$('.cam-modes button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.mode === mode);
    });
    renderPageStrip();
  }

  function stopCamera() {
    if (stream) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
    }
    var video = $('#capVideo');
    if (video) video.srcObject = null;
  }

  async function addCompressedPage(source) {
    var prepared = await LLPreprocess.compressImage(source);
    var thumbUrl = URL.createObjectURL(prepared.blob);
    pages.push({ blob: prepared.blob, thumbUrl: thumbUrl });
    renderPageStrip();
    return prepared;
  }

  async function onShutter() {
    var video = $('#capVideo');
    var c = cfg();
    try {
      if (video && video.srcObject && video.videoWidth) {
        var frame = await LLPreprocess.captureVideoFrame(video);
        if (!c.allowsMulti) {
          clearPages();
        }
        var thumbUrl = URL.createObjectURL(frame.blob);
        pages.push({ blob: frame.blob, thumbUrl: thumbUrl });
      } else {
        toast('Camera not ready — choose a file instead');
        return;
      }
    } catch (err) {
      toast(err.message || 'Capture failed');
      return;
    }
    renderPageStrip();
    if (c.autoUploadOnCapture) {
      void startUploadFlow();
    } else {
      toast('Page ' + pages.length + ' added · Add another or Review & upload');
    }
  }

  async function onLibraryFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    var c = cfg();

    if (!c.allowsMulti && files.length > 1) {
      toast('Receipt mode uses one image — using the first file');
      files = files.slice(0, 1);
    }

    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      var lower = (f.name || '').toLowerCase();
      if (lower.endsWith('.pdf')) {
        if (mode === 'receipt') {
          toast('Receipt mode expects a photo — switch to Invoice for PDFs');
          continue;
        }
        composedFile = f;
        clearPages();
        toast('PDF selected · uploading…');
        void startUploadFlow({ file: f });
        return;
      }
      try {
        if (!c.allowsMulti) clearPages();
        await addCompressedPage(f);
      } catch (err) {
        toast(err.message || 'Could not read image');
      }
    }
    if (!pages.length && !composedFile) return;
    if (c.autoUploadOnCapture) {
      void startUploadFlow();
    } else {
      toast(pages.length + ' page' + (pages.length === 1 ? '' : 's') + ' ready · Review & upload');
    }
  }

  function money(n) {
    var num = Number(n);
    if (!isFinite(num)) return String(n || '—');
    return fmt(num, true);
  }

  function buildPatchFromEdits() {
    return LLCaptureApi.buildUpdatePayload(fieldEdits);
  }

  function relativeTime(iso) {
    if (!iso) return '';
    var t = Date.parse(iso);
    if (!isFinite(t)) return '';
    var sec = Math.round((Date.now() - t) / 1000);
    if (sec < 60) return 'just now';
    if (sec < 3600) return Math.floor(sec / 60) + ' min ago';
    if (sec < 86400) return Math.floor(sec / 3600) + ' h ago';
    if (sec < 86400 * 7) return Math.floor(sec / 86400) + ' d ago';
    try {
      return new Date(t).toLocaleDateString();
    } catch (e) {
      return '';
    }
  }

  function statusTone(status) {
    var s = String(status || '');
    if (s === 'exception' || s === 'rejected' || s === 'duplicate_skipped') return 'neg';
    if (LLCaptureApi.isPipelineActive(s)) return 'warn';
    if (s === 'processed') return 'pos';
    return 'acc';
  }

  function expenseTypeOptions() {
    var opts = [];
    var tree = (deps.QLL && deps.QLL.me && deps.QLL.me.budgetTree) || [];
    tree.forEach(function (node) {
      opts.push({ value: node.label, label: node.label, sub: 'Parent' });
      (node.children || []).forEach(function (c) {
        opts.push({ value: c.label, label: c.label, sub: node.label });
      });
    });
    if (!opts.length) {
      opts = [
        { value: 'Travel', label: 'Travel', sub: '' },
        { value: 'Meals', label: 'Meals', sub: '' },
        { value: 'Other', label: 'Other', sub: '' }
      ];
    }
    return opts;
  }

  function resolveQaDocumentType(qaCfg) {
    var code = String(
      (qaCfg && (qaCfg.documentTypeCode || qaCfg.document_type_code)) ||
        preferredDtCode ||
        ''
    )
      .trim()
      .toUpperCase();
    if (!code) return null;
    for (var i = 0; i < documentTypes.length; i++) {
      if (String(documentTypes[i].code || '').toUpperCase() === code) {
        return documentTypes[i];
      }
    }
    return null;
  }

  function parentLedgerOptions(dt) {
    var ledger = String((dt && dt.postTo && dt.postTo.ledger) || '').trim();
    var sub = String((dt && dt.postTo && dt.postTo.subLedger) || '').trim();
    var opts = [];
    var parentKey = ledger.toLowerCase();

    function pushSub(value, parentLabel) {
      var v = String(value || '').trim();
      if (!v) return;
      // Never offer the parent GL itself — only its sub-ledgers.
      if (parentKey && v.toLowerCase() === parentKey) return;
      if (opts.some(function (o) { return o.value.toLowerCase() === v.toLowerCase(); })) return;
      opts.push({
        value: v,
        label: v,
        sub: parentLabel || ledger || 'Sub-ledger'
      });
    }

    if (sub) pushSub(sub, ledger || 'Sub-ledger');

    // Full COA children under the DT Post-to GL (preferred).
    var coaMap = (deps.QLL && deps.QLL.me && deps.QLL.me.coaParentChildren) || {};
    if (parentKey && coaMap[parentKey] && Array.isArray(coaMap[parentKey].children)) {
      var coaParent = coaMap[parentKey].name || ledger;
      coaMap[parentKey].children.forEach(function (c) {
        pushSub(c, coaParent);
      });
    }

    // Budget-tree children under the DT parent ledger (supplement).
    var tree = (deps.QLL && deps.QLL.me && deps.QLL.me.budgetTree) || [];
    if (parentKey) {
      tree.forEach(function (node) {
        if (String(node.label || '').toLowerCase() !== parentKey) return;
        (node.children || []).forEach(function (c) {
          pushSub(c.label, ledger);
        });
      });
    }

    return opts;
  }

  function normalizeMobileQaConfig(raw) {
    var base = {
      enabled: false,
      allowWithDoc: true,
      allowWithoutDoc: true,
      photoRequired: 'none',
      documentTypeCode: '',
      fields: {
        parentLedger: { visible: true, required: true },
        adjustAdvance: { visible: true, required: false },
        spentFor: { visible: true, required: true },
        remarks: { visible: true, required: false }
      }
    };
    if (raw === true) {
      base.enabled = true;
      return base;
    }
    if (!raw || raw === false) return base;
    if (typeof raw !== 'object') return base;
    base.enabled = !!raw.enabled;
    if (raw.allowWithDoc != null) base.allowWithDoc = !!raw.allowWithDoc;
    else if (raw.allow_with_doc != null) base.allowWithDoc = !!raw.allow_with_doc;
    if (raw.allowWithoutDoc != null) base.allowWithoutDoc = !!raw.allowWithoutDoc;
    else if (raw.allow_without_doc != null) base.allowWithoutDoc = !!raw.allow_without_doc;
    base.documentTypeCode = String(
      raw.documentTypeCode || raw.document_type_code || preferredDtCode || ''
    )
      .trim()
      .toUpperCase();
    var photo = String(raw.photoRequired || raw.photo_required || base.photoRequired);
    if (photo === 'compulsory' || photo === 'optional' || photo === 'none') {
      base.photoRequired = photo;
    }
    var fieldsRaw = raw.fields || {};
    function field(camel, snake, fallback) {
      var src = fieldsRaw[camel] || fieldsRaw[snake] || {};
      return {
        visible: src.visible != null ? !!src.visible : fallback.visible,
        required: src.required != null ? !!src.required : fallback.required
      };
    }
    // Legacy expenseType → parentLedger; amount / detailFields ignored (DT owns details).
    var parentSrc =
      fieldsRaw.parentLedger ||
      fieldsRaw.parent_ledger ||
      fieldsRaw.expenseType ||
      fieldsRaw.expense_type;
    base.fields = {
      parentLedger: field('parentLedger', 'parent_ledger', base.fields.parentLedger),
      adjustAdvance: field('adjustAdvance', 'adjust_advance', base.fields.adjustAdvance),
      spentFor: field('spentFor', 'spent_for', base.fields.spentFor),
      remarks: field('remarks', 'remarks', base.fields.remarks)
    };
    if (parentSrc && typeof parentSrc === 'object') {
      base.fields.parentLedger = {
        visible: parentSrc.visible != null ? !!parentSrc.visible : true,
        required: parentSrc.required != null ? !!parentSrc.required : true
      };
    }
    if (base.enabled && !base.allowWithDoc && !base.allowWithoutDoc) {
      base.allowWithDoc = true;
    }
    return base;
  }

  /** DT detail fields for the claim sheet — mirrors Rule Book DT, not QA settings. */
  function dtDetailFields(dt) {
    var keys = [];
    if (dt && LLCaptureApi.formKeysForDocumentType) {
      keys = LLCaptureApi.formKeysForDocumentType(dt).filter(function (k) {
        return k !== 'line_items' && k !== 'bank_details';
      });
    }
    var requiredSet = {};
    if (dt && LLCaptureApi.requiredKeysForDocumentType) {
      LLCaptureApi.requiredKeysForDocumentType(dt).forEach(function (k) {
        requiredSet[String(k || '').toLowerCase()] = true;
      });
    } else {
      (dt && dt.requiredFields ? dt.requiredFields : []).forEach(function (raw) {
        requiredSet[String(raw || '').trim().toLowerCase()] = true;
      });
    }
    return keys.map(function (key) {
      return {
        key: key,
        required: !!requiredSet[String(key).toLowerCase()]
      };
    });
  }

  function visibleDetailFieldKeys(_qaCfg, dt) {
    return dtDetailFields(dt).map(function (row) {
      return row.key;
    });
  }

  function claimDetailsFormHtml(prefill, qaCfg, mode, dt) {
    prefill = prefill || {};
    qaCfg = normalizeMobileQaConfig(qaCfg || { enabled: true });
    mode = mode || 'with_doc';
    dt = dt || resolveQaDocumentType(qaCfg);
    var fields = qaCfg.fields;
    var ledgerOpts = parentLedgerOptions(dt);
    var defaultLedger =
      String(prefill.parentLedger || prefill.expenseType || '').trim() ||
      (dt && dt.postTo && dt.postTo.subLedger) ||
      (ledgerOpts.length === 1 ? ledgerOpts[0].value : '') ||
      '';
    // Never default to the parent GL — only a sub-ledger.
    if (
      defaultLedger &&
      dt &&
      dt.postTo &&
      dt.postTo.ledger &&
      String(defaultLedger).toLowerCase() === String(dt.postTo.ledger).toLowerCase()
    ) {
      defaultLedger =
        (dt.postTo.subLedger || '') ||
        (ledgerOpts.length === 1 ? ledgerOpts[0].value : '');
    }
    var typeOpts = ledgerOpts
      .map(function (t) {
        var sel = String(defaultLedger) === t.value ? ' selected' : '';
        return (
          '<option value="' +
          esc(t.value) +
          '"' +
          sel +
          '>' +
          esc(t.label) +
          (t.sub ? ' (' + esc(t.sub) + ')' : '') +
          '</option>'
        );
      })
      .join('');
    var spentRaw = String(prefill.spentFor || 'Myself');
    var spentOther = String(prefill.spentForOther || '');
    var spent = spentRaw === 'Myself' || spentRaw === 'Others' ? spentRaw : 'Others';
    if (spent === 'Others' && !spentOther && spentRaw && spentRaw !== 'Others') {
      spentOther = spentRaw;
    }
    var adj = !!prefill.adjustAdvance;
    var remarks = String(prefill.remarks || '');
    var detailVals = prefill.detailValues || {};
    var html = '<div style="padding:4px 16px 8px">';
    if (fields.parentLedger.visible) {
      html +=
        '<label class="cap-fill-label" for="claimParentLedger">Sub-ledger' +
        (fields.parentLedger.required ? ' *' : '') +
        '</label>' +
        '<select id="claimParentLedger" class="cap-fill-input" style="appearance:auto">' +
        '<option value="">Select…</option>' +
        typeOpts +
        '</select>';
      if (dt && dt.postTo && dt.postTo.ledger) {
        html +=
          '<p class="claim-photo-hint" style="margin:4px 0 0">Under GL: ' +
          esc(dt.postTo.ledger) +
          '</p>';
      } else if (!ledgerOpts.length) {
        html +=
          '<p class="claim-photo-hint" style="margin:4px 0 0">No sub-ledgers found for this document type.</p>';
      }
    }
    if (fields.adjustAdvance.visible) {
      html +=
        '<label class="cap-fill-label" style="margin-top:14px">Adjust against advance' +
        (fields.adjustAdvance.required ? ' *' : '') +
        '</label>' +
        '<div class="seg" id="claimAdjAdvance" role="group" style="margin:0 0 12px">' +
        '<button type="button" data-adj="0"' +
        (!adj ? ' class="active"' : '') +
        '>No</button>' +
        '<button type="button" data-adj="1"' +
        (adj ? ' class="active"' : '') +
        '>Yes</button></div>';
    }
    if (fields.spentFor.visible) {
      html +=
        '<label class="cap-fill-label" style="margin-top:14px">Spent for' +
        (fields.spentFor.required ? ' *' : '') +
        '</label>' +
        '<div class="seg" id="claimSpentFor" role="group" style="margin:0 0 12px">' +
        ['Myself', 'Others']
          .map(function (s) {
            return (
              '<button type="button" data-spent="' +
              esc(s) +
              '"' +
              (spent === s ? ' class="active"' : '') +
              '>' +
              esc(s) +
              '</button>'
            );
          })
          .join('') +
        '</div>' +
        '<div id="claimSpentForOtherWrap" style="margin:0 0 12px' +
        (spent === 'Others' ? '' : ';display:none') +
        '">' +
        '<label class="cap-fill-label" for="claimSpentForOther">Who' +
        (fields.spentFor.required ? ' *' : '') +
        '</label>' +
        '<input id="claimSpentForOther" class="cap-fill-input" type="text" maxlength="80" placeholder="Enter name or details" value="' +
        esc(spentOther) +
        '">' +
        '</div>';
    }
    var detailRows = dtDetailFields(dt);
    detailRows.forEach(function (row) {
      var key = row.key;
      var label = LLCaptureApi.fieldLabel ? LLCaptureApi.fieldLabel(key) : key;
      var val = detailVals[key] != null ? String(detailVals[key]) : '';
      if (!val && prefill[key] != null) val = String(prefill[key]);
      var inputType =
        key.indexOf('date') >= 0
          ? 'date'
          : key === 'total' || key === 'subtotal' || key === 'gst' || key === 'gst_rate'
            ? 'number'
            : 'text';
      var step = inputType === 'number' ? ' step="0.01"' : '';
      html +=
        '<label class="cap-fill-label" for="claimDetail_' +
        esc(key) +
        '" style="margin-top:14px">' +
        esc(label) +
        (row.required ? ' *' : '') +
        '</label>' +
        '<input id="claimDetail_' +
        esc(key) +
        '" data-detail-field="' +
        esc(key) +
        '" class="cap-fill-input" type="' +
        inputType +
        '"' +
        step +
        ' autocomplete="off" value="' +
        esc(val) +
        '">';
    });
    if (mode === 'with_doc') {
      html +=
        '<div class="claim-photo" id="claimPhotoBlock">' +
        '<label class="cap-fill-label">Document photo *</label>' +
        '<p class="claim-photo-hint">Required — take or choose a clear photo of the document.</p>' +
        '<div class="claim-photo-card" id="claimPhotoCard">' +
        '<div class="claim-photo-empty" id="claimPhotoEmpty">' +
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.7l1.1-1.8h6.4L15.8 6h2.7A2.5 2.5 0 0 1 21 8.5v8A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5v-8Z"/><circle cx="12" cy="12.4" r="3.4"/></svg>' +
        '<span>No picture yet</span>' +
        '</div>' +
        '<div class="claim-photo-preview" id="claimPhotoPreview" hidden>' +
        '<img id="claimPhotoImg" alt="Selected picture">' +
        '<button type="button" class="claim-photo-clear" id="claimPhotoClear" aria-label="Remove picture">×</button>' +
        '<span class="claim-photo-name" id="claimPhotoName"></span>' +
        '</div>' +
        '</div>' +
        '<div class="claim-photo-actions">' +
        '<button type="button" class="btn sec sm" id="claimPhotoCamera">Take photo</button>' +
        '<button type="button" class="btn sec sm" id="claimPhotoLibrary">Choose photo</button>' +
        '</div>' +
        '<input id="claimPhotoCam" type="file" accept="image/*" capture="environment" hidden>' +
        '<input id="claimPhotoLib" type="file" accept="image/*" hidden>' +
        '</div>';
    }
    if (fields.remarks.visible) {
      html +=
        '<label class="cap-fill-label" for="claimRemarks" style="margin-top:14px">Remarks' +
        (fields.remarks.required ? ' *' : '') +
        '</label>' +
        '<textarea id="claimRemarks" class="cap-fill-input" rows="3" placeholder="Optional notes" style="min-height:72px;resize:vertical">' +
        esc(remarks) +
        '</textarea>';
    }
    html += '</div>';
    return html;
  }

  function readClaimDetailsForm() {
    var parentLedger = String(
      ($('#claimParentLedger') && $('#claimParentLedger').value) || ''
    ).trim();
    var adjBtn = $('#claimAdjAdvance button.active');
    var adjustAdvance = !!(adjBtn && adjBtn.getAttribute('data-adj') === '1');
    var spentBtn = $('#claimSpentFor button.active');
    var spentChoice = spentBtn ? String(spentBtn.getAttribute('data-spent') || 'Myself') : 'Myself';
    var spentOther = String(($('#claimSpentForOther') && $('#claimSpentForOther').value) || '').trim();
    var spentFor = spentChoice === 'Others' ? spentOther || 'Others' : spentChoice;
    var remarks = String(($('#claimRemarks') && $('#claimRemarks').value) || '').trim();
    var detailValues = {};
    $$('[data-detail-field]').forEach(function (el) {
      var key = String(el.getAttribute('data-detail-field') || '').trim();
      if (!key) return;
      detailValues[key] = String(el.value || '').trim();
    });
    return {
      parentLedger: parentLedger,
      expenseType: parentLedger,
      amount: detailValues.total || '',
      adjustAdvance: adjustAdvance,
      spentFor: spentFor,
      spentChoice: spentChoice,
      spentForOther: spentOther,
      remarks: remarks,
      detailValues: detailValues,
      photoFile: claimDetailsPhotoFile || null
    };
  }

  function validateClaimDetails(details, qaCfg, mode) {
    qaCfg = normalizeMobileQaConfig(qaCfg || { enabled: true });
    var fields = qaCfg.fields;
    if (fields.parentLedger.visible && fields.parentLedger.required && !details.parentLedger) {
      return 'Select sub-ledger';
    }
    if (fields.spentFor.visible && fields.spentFor.required) {
      if (!details.spentChoice) return 'Select spent for';
      if (details.spentChoice === 'Others' && !details.spentForOther) {
        return 'Enter who it was spent for';
      }
    }
    if (fields.remarks.visible && fields.remarks.required && !details.remarks) {
      return 'Enter remarks';
    }
    if (fields.adjustAdvance.visible && fields.adjustAdvance.required && details.adjustAdvance == null) {
      return 'Select adjust against advance';
    }
    var dt = resolveQaDocumentType(qaCfg);
    var detailRows = dtDetailFields(dt);
    for (var i = 0; i < detailRows.length; i++) {
      var row = detailRows[i];
      if (!row.required) continue;
      var val = details.detailValues && details.detailValues[row.key];
      if (!String(val || '').trim()) {
        var label = LLCaptureApi.fieldLabel ? LLCaptureApi.fieldLabel(row.key) : row.key;
        return 'Enter ' + label;
      }
    }
    if (mode === 'with_doc' && !details.photoFile) {
      return 'Add a document photo';
    }
    return '';
  }

  function clearClaimDetailsPhoto() {
    claimDetailsPhotoFile = null;
    if (claimDetailsPhotoUrl) {
      try {
        URL.revokeObjectURL(claimDetailsPhotoUrl);
      } catch (e) { /* ignore */ }
      claimDetailsPhotoUrl = '';
    }
    var empty = $('#claimPhotoEmpty');
    var preview = $('#claimPhotoPreview');
    var img = $('#claimPhotoImg');
    var nameEl = $('#claimPhotoName');
    var cam = $('#claimPhotoCam');
    var lib = $('#claimPhotoLib');
    if (empty) empty.hidden = false;
    if (preview) preview.hidden = true;
    if (img) img.removeAttribute('src');
    if (nameEl) nameEl.textContent = '';
    if (cam) cam.value = '';
    if (lib) lib.value = '';
  }

  function setClaimDetailsPhoto(file) {
    if (!file) {
      clearClaimDetailsPhoto();
      return;
    }
    claimDetailsPhotoFile = file;
    if (claimDetailsPhotoUrl) {
      try {
        URL.revokeObjectURL(claimDetailsPhotoUrl);
      } catch (e2) { /* ignore */ }
    }
    claimDetailsPhotoUrl = URL.createObjectURL(file);
    var empty = $('#claimPhotoEmpty');
    var preview = $('#claimPhotoPreview');
    var img = $('#claimPhotoImg');
    var nameEl = $('#claimPhotoName');
    if (empty) empty.hidden = true;
    if (preview) preview.hidden = false;
    if (img) img.src = claimDetailsPhotoUrl;
    if (nameEl) nameEl.textContent = file.name || 'Photo';
  }

  function wireClaimDetailsForm(body, options) {
    options = options || {};
    clearClaimDetailsPhoto();
    if (options.initialPhoto) {
      setClaimDetailsPhoto(options.initialPhoto);
    }
    var adj = $('#claimAdjAdvance', body);
    if (adj) {
      adj.addEventListener('click', function (e) {
        var b = e.target.closest('button[data-adj]');
        if (!b) return;
        $$('button[data-adj]', adj).forEach(function (x) {
          x.classList.toggle('active', x === b);
        });
      });
    }
    var spent = $('#claimSpentFor', body);
    var otherWrap = $('#claimSpentForOtherWrap', body);
    var otherInput = $('#claimSpentForOther', body);
    if (spent) {
      spent.addEventListener('click', function (e) {
        var b = e.target.closest('button[data-spent]');
        if (!b) return;
        $$('button[data-spent]', spent).forEach(function (x) {
          x.classList.toggle('active', x === b);
        });
        var isOthers = b.getAttribute('data-spent') === 'Others';
        if (otherWrap) otherWrap.style.display = isOthers ? '' : 'none';
        if (isOthers && otherInput) {
          setTimeout(function () {
            otherInput.focus();
          }, 0);
        }
      });
    }
    var camInput = $('#claimPhotoCam', body);
    var libInput = $('#claimPhotoLib', body);
    var camBtn = $('#claimPhotoCamera', body);
    var libBtn = $('#claimPhotoLibrary', body);
    var clearBtn = $('#claimPhotoClear', body);
    if (camBtn && camInput) {
      camBtn.addEventListener('click', function () {
        camInput.click();
      });
    }
    if (libBtn && libInput) {
      libBtn.addEventListener('click', function () {
        libInput.click();
      });
    }
    function onPick(ev) {
      var input = ev.target;
      var file = input && input.files && input.files[0] ? input.files[0] : null;
      if (!file) return;
      if (file.type && file.type.indexOf('image/') !== 0) {
        toast('Choose an image file');
        input.value = '';
        return;
      }
      setClaimDetailsPhoto(file);
    }
    if (camInput) camInput.addEventListener('change', onPick);
    if (libInput) libInput.addEventListener('change', onPick);
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        clearClaimDetailsPhoto();
      });
    }
  }

  function claimFieldsToPatch(details) {
    var remarksParts = [];
    if (details.spentFor) remarksParts.push('Spent for: ' + details.spentFor);
    if (details.adjustAdvance) remarksParts.push('Adjust against advance: Yes');
    if (details.remarks) remarksParts.push(details.remarks);
    var patch = Object.assign({}, details.detailValues || {});
    if (details.parentLedger || details.expenseType) {
      patch.account_name = details.parentLedger || details.expenseType || '';
      patch.category = details.parentLedger || details.expenseType || '';
    }
    if (details.spentFor) {
      patch.document_heading = 'Spent for ' + details.spentFor;
    }
    if (remarksParts.length) {
      patch.billing_address = remarksParts.join('\n');
    }
    return LLCaptureApi.buildUpdatePayload(patch);
  }

  function claimFieldsToManualFields(details) {
    var total = (details.detailValues && details.detailValues.total) || details.amount || '0';
    var ledger = details.parentLedger || details.expenseType || '';
    var fields = Object.assign({}, details.detailValues || {}, {
      vendor:
        details.spentFor === 'Myself'
          ? 'Employee claim'
          : (details.spentFor || 'Employee') + ' claim',
      total: total,
      account_name: ledger,
      category: ledger,
      document_heading: details.spentFor ? 'Spent for ' + details.spentFor : '',
      cost_centre: details.adjustAdvance
        ? 'Adjust against advance'
        : (details.detailValues && details.detailValues.cost_centre) || '',
      billing_address: details.remarks || '',
      line_items: [
        {
          description: ledger || 'Expense claim',
          qty: 1,
          unit_price: total || 0,
          amount: total || 0,
          tax_amount: 0
        }
      ]
    });
    return fields;
  }

  async function resolvePreferredDocumentTypeCode() {
    await ensureDocumentTypes();
    if (preferredDtCode) {
      var pinnedCode = String(preferredDtCode).trim().toUpperCase();
      if (quickActionCodes().length && !quickActionByCode[pinnedCode]) {
        /* fall through to QA list */
      } else {
        var pinned = documentTypes.filter(function (dt) {
          return String(dt.code || '').toUpperCase() === pinnedCode;
        })[0];
        if (pinned && pinned.code) return String(pinned.code).trim().toUpperCase();
        if (quickActionByCode[pinnedCode]) return pinnedCode;
      }
    }
    var qaVisible = visibleDocumentTypes();
    if (qaVisible.length && qaVisible[0].code) {
      return String(qaVisible[0].code).trim().toUpperCase();
    }
    var qaCodes = quickActionCodes();
    if (qaCodes.length) return qaCodes[0];
    var intentKind = String(teIntent || '').toLowerCase();
    var byIntent = documentTypes.filter(function (dt) {
      return String(dt.teamExpenseKind || '').toLowerCase() === intentKind;
    })[0];
    if (byIntent && byIntent.code) return String(byIntent.code).trim().toUpperCase();
    var any = documentTypes[0];
    if (any && any.code) return String(any.code).trim().toUpperCase();
    throw new Error('No document type configured in Quick Actions');
  }

  function qaDetailsTitle() {
    return String(activeQaTitle || '').trim() || 'Details';
  }

  function openClaimDetailsForm(options) {
    options = options || {};
    var mode = options.mode || 'with_doc';
    var inv = options.invoice || null;
    var prefill = options.prefill || {};
    var initialPhoto = options.photoFile || null;
    var qaCfg = normalizeMobileQaConfig(
      options.qaConfig || activeQaConfig || { enabled: true }
    );
    activeQaConfig = qaCfg;
    if (options.title) activeQaTitle = String(options.title || '').trim();
    var heading = qaDetailsTitle();

    function showForm(dt) {
      if (inv) {
        var ocrTotal = LLCaptureApi.readExtractionValue(inv, 'total');
        prefill.detailValues = prefill.detailValues || {};
        if (ocrTotal && !prefill.detailValues.total) {
          prefill.detailValues.total = String(ocrTotal).replace(/[^0-9.]/g, '');
        }
        if (!prefill.parentLedger && !prefill.expenseType) {
          prefill.parentLedger =
            LLCaptureApi.readExtractionValue(inv, 'account_name') ||
            LLCaptureApi.readExtractionValue(inv, 'category') ||
            (dt && dt.postTo && dt.postTo.subLedger) ||
            '';
        }
        visibleDetailFieldKeys(qaCfg, dt).forEach(function (key) {
          if (prefill.detailValues[key]) return;
          var extracted = LLCaptureApi.readExtractionValue(inv, key);
          if (extracted) prefill.detailValues[key] = String(extracted);
        });
      } else if (dt && dt.postTo) {
        if (!prefill.parentLedger) {
          prefill.parentLedger = dt.postTo.subLedger || '';
        }
      }
      // Drop accidental parent-GL selection — picker is sub-ledgers only.
      if (
        prefill.parentLedger &&
        dt &&
        dt.postTo &&
        dt.postTo.ledger &&
        String(prefill.parentLedger).toLowerCase() === String(dt.postTo.ledger).toLowerCase()
      ) {
        prefill.parentLedger = dt.postTo.subLedger || '';
      }
      var hasAdvance =
        deps.QLL &&
        deps.QLL.me &&
        deps.QLL.me.advance &&
        (Number(deps.QLL.me.advance.outstanding) > 0 || Number(deps.QLL.me.advance.amount) > 0);

      deps.openSheet({
        tall: true,
        title: heading,
        sub:
          mode === 'without_doc'
            ? 'Without document · fill and submit'
            : 'With document · complete details and submit',
        body:
          claimDetailsFormHtml(prefill, qaCfg, mode, dt) +
          (hasAdvance && qaCfg.fields.adjustAdvance.visible
            ? '<p style="padding:0 16px 8px;font-size:12px;color:var(--ink-3);margin:0">You have an advance outstanding — choose Yes to adjust against it.</p>'
            : ''),
        foot:
          '<button class="btn sm sec" data-close style="flex:0 0 96px">Close</button>' +
          '<button class="btn" id="claimFormSubmit" style="flex:1">Submit</button>',
        onMount: function (b, f) {
          wireClaimDetailsForm(b, { initialPhoto: initialPhoto });
          var btn = $('#claimFormSubmit', f);
          if (!btn) return;
          btn.addEventListener('click', function () {
            void submitClaimDetailsForm({ mode: mode, invoice: inv, qaConfig: qaCfg });
          });
        }
      });
    }

    void ensureDocumentTypes()
      .then(function () {
        showForm(resolveQaDocumentType(qaCfg));
      })
      .catch(function () {
        showForm(resolveQaDocumentType(qaCfg));
      });
  }

  async function submitManualCaptureFromForm(details) {
    var dtCode = await resolvePreferredDocumentTypeCode();
    if (!details.photoFile) {
      throw new Error('Add a document photo');
    }
    var file = details.photoFile;
    if (global.LLPreprocess && LLPreprocess.compressImage) {
      try {
        var prepared = await LLPreprocess.compressImage(details.photoFile);
        if (prepared && prepared.blob) {
          file = new File(
            [prepared.blob],
            (details.photoFile.name || 'document.jpg').replace(/\.\w+$/, '') + '.jpg',
            { type: prepared.blob.type || 'image/jpeg' }
          );
        }
      } catch (e) {
        /* keep original file */
      }
    }
    var created = await LLCaptureApi.manualCapture(
      file,
      dtCode,
      claimFieldsToManualFields(details)
    );
    var after = created.invoice;
    var status = String(after.status || '');
    if (status === 'exception' || status === 'duplicate_skipped' || status === 'rejected') {
      after = await LLCaptureApi.confirmProcess(after.id);
    } else {
      try {
        after = await LLCaptureApi.confirmProcess(after.id);
      } catch (e) {
        /* already progressing */
      }
    }
    return after;
  }

  async function submitWithoutDocumentFromForm(details) {
    var dtCode = await resolvePreferredDocumentTypeCode();
    var created = await LLCaptureApi.createWithoutDocument(
      dtCode,
      claimFieldsToManualFields(details)
    );
    var after = created.invoice;
    var status = String(after.status || '');
    if (status === 'exception' || status === 'duplicate_skipped' || status === 'rejected') {
      after = await LLCaptureApi.confirmProcess(after.id);
    } else {
      try {
        after = await LLCaptureApi.confirmProcess(after.id);
      } catch (e) {
        /* already progressing */
      }
    }
    return after;
  }

  async function submitClaimDetailsForm(cfg) {
    var qaCfg = normalizeMobileQaConfig(cfg.qaConfig || activeQaConfig || { enabled: true });
    var details = readClaimDetailsForm();
    var errMsg = validateClaimDetails(details, qaCfg, cfg.mode);
    if (errMsg) {
      toast(errMsg);
      return;
    }
    try {
      toast('Submitting…');
      var after;
      if (cfg.mode === 'without_doc') {
        after = await submitWithoutDocumentFromForm(details);
      } else if (cfg.mode === 'with_doc' && !(cfg.invoice && cfg.invoice.id)) {
        after = await submitManualCaptureFromForm(details);
      } else {
        if (!cfg.invoice || !cfg.invoice.id) throw new Error('Missing captured claim');
        var patch = claimFieldsToPatch(details);
        if (Object.keys(patch).length) {
          after = await LLCaptureApi.updateInvoice(cfg.invoice.id, patch);
        } else {
          after = await LLCaptureApi.getInvoice(cfg.invoice.id);
        }
        var st = String(after.status || '');
        if (st === 'exception' || st === 'duplicate_skipped' || st === 'rejected' || st === 'pending' || st === 'approved') {
          try {
            after = await LLCaptureApi.confirmProcess(after.id);
          } catch (e2) {
            /* keep after */
          }
        }
      }
      LLCaptureApi.updatePending(after.id, {
        status: 'submitted',
        vendor: LLCaptureApi.fieldValue(after, 'vendor'),
        total: (details.detailValues && details.detailValues.total) || details.amount || '',
        label: after.document_ref || ('#' + after.id)
      });
      deps.closeSheet();
      clearPages();
      composedFile = null;
      clearClaimDetailsPhoto();
      toast('Submitted · ' + (after.document_ref || ('#' + after.id)));
      if (deps.onPendingChange) deps.onPendingChange();
      if (deps.showScreen) deps.showScreen('home');
    } catch (err) {
      toast((err && err.message) || 'Submit failed');
    }
  }

  function applyQuickActionContext(opts) {
    opts = opts || {};
    preferredDtCode = String(opts.documentTypeCode || '').trim().toUpperCase();
    if (preferredDtCode) captureRouteDtCode = preferredDtCode;
    activeQaTitle = String(opts.title || '').trim();
    activeQaConfig = normalizeMobileQaConfig(opts.qaConfig || { enabled: true });
    preferClaimDetailsForm = opts.preferDetailsForm != null ? !!opts.preferDetailsForm : true;
    setTeamExpenseIntent(opts.intent || 'expense_claim', { quiet: true, force: true });
    syncIntentChrome(false);
  }

  /** Dedicated photo step for Quick Action "With document" (not the Capture tab). */
  function openQuickActionPhotoSheet() {
    var title = qaDetailsTitle();
    deps.openSheet({
      tall: false,
      title: title,
      sub: 'With document · take or choose a photo',
      body:
        '<div class="claim-photo" id="qaDocPhotoBlock" style="margin:0">' +
        '<p class="claim-photo-hint" style="margin-top:0">Photograph the receipt or document. You will fill details on the next step.</p>' +
        '<div class="claim-photo-card" id="qaDocPhotoCard">' +
        '<div class="claim-photo-empty" id="qaDocPhotoEmpty">' +
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.7l1.1-1.8h6.4L15.8 6h2.7A2.5 2.5 0 0 1 21 8.5v8A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5v-8Z"/><circle cx="12" cy="12.4" r="3.4"/></svg>' +
        '<span>No document photo yet</span>' +
        '</div>' +
        '<div class="claim-photo-preview" id="qaDocPhotoPreview" hidden>' +
        '<img id="qaDocPhotoImg" alt="Document photo">' +
        '<button type="button" class="claim-photo-clear" id="qaDocPhotoClear" aria-label="Remove picture">×</button>' +
        '<span class="claim-photo-name" id="qaDocPhotoName"></span>' +
        '</div></div>' +
        '<div class="claim-photo-actions">' +
        '<button type="button" class="btn sec sm" id="qaDocPhotoCamera">Take photo</button>' +
        '<button type="button" class="btn sec sm" id="qaDocPhotoLibrary">Choose photo</button>' +
        '</div>' +
        '<input id="qaDocPhotoCam" type="file" accept="image/*" capture="environment" hidden>' +
        '<input id="qaDocPhotoLib" type="file" accept="image/*" hidden>' +
        '</div>',
      foot:
        '<button class="btn sm sec" data-close style="flex:0 0 96px">Cancel</button>' +
        '<button class="btn" id="qaDocPhotoContinue" style="flex:1" disabled>Continue</button>',
      onMount: function (b, f) {
        var picked = null;
        var pickedUrl = '';
        var empty = $('#qaDocPhotoEmpty', b);
        var preview = $('#qaDocPhotoPreview', b);
        var img = $('#qaDocPhotoImg', b);
        var nameEl = $('#qaDocPhotoName', b);
        var camInput = $('#qaDocPhotoCam', b);
        var libInput = $('#qaDocPhotoLib', b);
        var camBtn = $('#qaDocPhotoCamera', b);
        var libBtn = $('#qaDocPhotoLibrary', b);
        var clearBtn = $('#qaDocPhotoClear', b);
        var contBtn = $('#qaDocPhotoContinue', f);

        function syncContinue() {
          if (contBtn) contBtn.disabled = !picked;
        }

        function clearPicked() {
          picked = null;
          if (pickedUrl) {
            try {
              URL.revokeObjectURL(pickedUrl);
            } catch (e) { /* ignore */ }
            pickedUrl = '';
          }
          if (empty) empty.hidden = false;
          if (preview) preview.hidden = true;
          if (img) img.removeAttribute('src');
          if (nameEl) nameEl.textContent = '';
          if (camInput) camInput.value = '';
          if (libInput) libInput.value = '';
          syncContinue();
        }

        function setPicked(file) {
          picked = file;
          if (pickedUrl) {
            try {
              URL.revokeObjectURL(pickedUrl);
            } catch (e2) { /* ignore */ }
          }
          pickedUrl = URL.createObjectURL(file);
          if (empty) empty.hidden = true;
          if (preview) preview.hidden = false;
          if (img) img.src = pickedUrl;
          if (nameEl) nameEl.textContent = file.name || 'Photo';
          syncContinue();
        }

        if (camBtn && camInput) {
          camBtn.addEventListener('click', function () {
            camInput.click();
          });
        }
        if (libBtn && libInput) {
          libBtn.addEventListener('click', function () {
            libInput.click();
          });
        }
        function onPick(ev) {
          var input = ev.target;
          var file = input && input.files && input.files[0] ? input.files[0] : null;
          if (!file) return;
          if (file.type && file.type.indexOf('image/') !== 0) {
            toast('Choose an image file');
            input.value = '';
            return;
          }
          setPicked(file);
        }
        if (camInput) camInput.addEventListener('change', onPick);
        if (libInput) libInput.addEventListener('change', onPick);
        if (clearBtn) clearBtn.addEventListener('click', clearPicked);

        if (contBtn) {
          contBtn.addEventListener('click', function () {
            if (!picked) {
              toast('Add a document photo first');
              return;
            }
            var file = picked;
            deps.closeSheet();
            setTimeout(function () {
              openClaimDetailsForm({
                mode: 'with_doc',
                photoFile: file,
                title: activeQaTitle,
                qaConfig: activeQaConfig,
                prefill: { spentFor: 'Myself' }
              });
            }, 40);
          });
        }
        syncContinue();
      }
    });
  }

  /** Config-driven Quick Action: With document → photo sheet → details form (not Capture tab). */
  function startQuickActionWithDoc(opts) {
    opts = opts || {};
    applyQuickActionContext(
      Object.assign({}, opts, {
        preferDetailsForm: opts.preferDetailsForm != null ? !!opts.preferDetailsForm : true
      })
    );
    openQuickActionPhotoSheet();
  }

  /** Config-driven Quick Action: Without document → details form. */
  function startQuickActionWithoutDoc(opts) {
    applyQuickActionContext(Object.assign({}, opts || {}, { preferDetailsForm: true }));
    openClaimDetailsForm({
      mode: 'without_doc',
      title: activeQaTitle,
      prefill: { spentFor: 'Myself' },
      qaConfig: activeQaConfig
    });
  }

  // Back-compat aliases used by older callers / capture tab helpers.
  function startClaimWithDoc(opts) {
    startQuickActionWithDoc(opts);
  }

  function startClaimWithoutDoc(opts) {
    startQuickActionWithoutDoc(opts);
  }

  function startAdvanceCapture(opts) {
    opts = opts || {};
    startQuickActionWithDoc(
      Object.assign({}, opts, {
        intent: opts.intent || 'advance_requisition',
        preferDetailsForm: !!opts.qaConfig
      })
    );
  }

  function openReviewSheet(inv, sourceLabel, options) {
    options = options || {};
    activeInvoice = inv;
    fieldEdits = {};
    var Api = LLCaptureApi;
    var keys = Api.extractionKeysForInvoice(inv);
    if (!keys.length) {
      keys = ['vendor', 'invoice_date', 'total', 'gst', 'abn', 'cost_centre'];
    }

    var vendor = Api.readExtractionValue(inv, 'vendor') || '—';
    var total = Api.readExtractionValue(inv, 'total');
    var gst = Api.readExtractionValue(inv, 'gst');
    var date = Api.readExtractionValue(inv, 'invoice_date') || '—';
    var dtCode = inv.document_type_code || inv.document_heading || 'Document';
    var totalNum = Number(total);
    var gstNum = Number(gst);
    var fromHome = !!options.fromHome;

    function pill(label, key, value, conf, editable) {
      var band = conf === 'hi' ? '' : conf;
      var collapsed = conf === 'hi' ? ' collapsed' : '';
      var wide = key === 'vendor' || key === 'billing_address' || key === 'document_heading' || key === 'email_sender';
      return '<button type="button" class="pill' + (wide ? ' wide' : '') + collapsed +
        (editable ? '' : ' readonly') +
        '" data-field="' + key + '" data-conf="' + conf + '" data-editable="' + (editable ? '1' : '0') + '">' +
        '<span class="pk"><span class="conf ' + band + '"></span>' + esc(label) + '</span>' +
        '<span class="pv" data-val>' + esc(value || '—') + '</span></button>';
    }

    var fieldsHtml = keys.map(function (key) {
      var editable = Api.isEditableKey(key);
      var conf = Api.fieldConfidence(inv, key);
      var val = Api.readExtractionValue(inv, key);
      if ((key === 'total' || key === 'gst' || key === 'subtotal') && val && isFinite(Number(val))) {
        val = money(val);
      }
      return pill(Api.fieldLabel(key), key, val, conf, editable);
    }).join('');

    var hiCount = keys.filter(function (k) {
      return Api.fieldConfidence(inv, k) === 'hi';
    }).length;
    var policy = Api.policyBanner(inv);
    var policyHtml = policy
      ? '<div class="banner ' + policy.tone + '">' + deps.checkIcon(policy.tone) +
        '<span><b>' + esc(policy.title) + '.</b> ' + esc(policy.body) + '</span></div>'
      : '';

    var submitLabel = fromHome
      ? 'Done'
      : (String(inv.status) === 'exception' || String(inv.status) === 'duplicate_skipped' || String(inv.status) === 'rejected'
        ? 'Submit'
        : 'Done');

    deps.openSheet({
      tall: true,
      title: fromHome ? 'Document fields' : 'Review and submit',
      sub: (dtCode ? dtCode + ' · ' : '') +
        (sourceLabel || 'LedgerLink') +
        ' · ' + hiCount + ' of ' + keys.length + ' high confidence',
      body:
        '<div style="display:flex;gap:12px;align-items:flex-start;padding:2px 16px 12px">' +
        '<div class="thumb">' + deps.IC.docLines + '</div>' +
        '<div style="flex:1;min-width:0">' +
        '<div class="amt" style="font-size:28px;font-weight:700;letter-spacing:-.032em">' +
        (isFinite(totalNum) ? money(totalNum) : esc(total || '—')) + '</div>' +
        '<div style="font-size:13px;color:var(--ink-3);margin-top:2px">' +
        (isFinite(gstNum) ? 'incl. GST ' + money(gstNum) + ' · ' : '') + esc(date) + '</div>' +
        '<div style="margin-top:8px"><span class="chip acc">' + esc(dtCode) + '</span></div>' +
        '<div style="font-size:12px;color:var(--ink-3);margin-top:6px">' + esc(vendor) + '</div>' +
        '</div></div>' +
        '<div class="sect-h tight">Extracted fields<span class="r">same as desktop · tap to edit</span></div>' +
        '<div class="fields">' + fieldsHtml + '</div>' +
        '<div style="height:12px"></div>' +
        policyHtml +
        '<div class="kv-list" style="margin-top:12px">' +
        '<div class="kv"><span class="k">Document</span><span class="v">' + esc(inv.document_ref || ('#' + inv.id)) + '</span></div>' +
        '<div class="kv"><span class="k">Status</span><span class="v">' + esc(inv.status || '—') + '</span></div>' +
        '</div><div style="height:10px"></div>',
      foot:
        '<button class="btn sm sec" data-close style="flex:0 0 96px">Close</button>' +
        '<button class="btn" id="submitBtn" style="flex:1">' + submitLabel + '</button>',
      onMount: function (b, f) {
        b.addEventListener('click', function (e) {
          var p = e.target.closest('.pill');
          if (!p) return;
          if (p.dataset.editable !== '1') {
            toast('Edit this field on desktop LedgerLink');
            return;
          }
          var key = p.dataset.field;
          var cur = (fieldEdits[key] != null)
            ? fieldEdits[key]
            : ($('[data-val]', p).textContent || '').replace(/^—$/, '');
          var next = window.prompt('Edit ' + Api.fieldLabel(key), cur === '—' ? '' : cur);
          if (next == null) return;
          var trimmed = next.trim();
          fieldEdits[key] = trimmed;
          $('[data-val]', p).textContent = trimmed || '—';
          p.classList.add('edited');
          p.classList.remove('collapsed');
          var conf = $('.conf', p);
          if (conf) conf.className = 'conf';
          // Two-way: persist immediately so desktop sees the same values
          var patch = Api.buildUpdatePayload(fieldEdits);
          if (!Object.keys(patch).length) return;
          toast('Saving…');
          Api.updateInvoice(inv.id, patch)
            .then(function (updated) {
              activeInvoice = updated;
              fieldEdits = {};
              toast('Saved · synced with LedgerLink');
              if (deps.onPendingChange) deps.onPendingChange();
            })
            .catch(function (err) {
              toast(err.message || 'Save failed');
            });
        });
        $('#submitBtn', f).addEventListener('click', function () {
          if (fromHome) {
            deps.closeSheet();
            if (deps.onPendingChange) deps.onPendingChange();
            return;
          }
          void submitReview(inv.id);
        });
      }
    });
  }

  async function submitReview(invoiceId) {
    try {
      toast('Submitting…');
      var patch = buildPatchFromEdits();
      var after;
      if (Object.keys(patch).length) {
        after = await LLCaptureApi.updateInvoice(invoiceId, patch);
      } else {
        after = await LLCaptureApi.getInvoice(invoiceId);
      }
      var status = String(after.status || '');
      if (status === 'exception' || status === 'duplicate_skipped' || status === 'rejected') {
        after = await LLCaptureApi.confirmProcess(invoiceId);
      }
      LLCaptureApi.updatePending(invoiceId, {
        status: 'submitted',
        vendor: LLCaptureApi.fieldValue(after, 'vendor'),
        total: LLCaptureApi.fieldValue(after, 'total'),
        label: after.document_ref || ('#' + after.id)
      });
      deps.closeSheet();
      showSuccess(after);
      clearPages();
      composedFile = null;
      if (deps.onPendingChange) deps.onPendingChange();
    } catch (err) {
      toast(err.message || 'Submit failed');
    }
  }

  function showSuccess(inv) {
    deps.hideSuccess();
    var vendor = LLCaptureApi.fieldValue(inv, 'vendor') || 'Document';
    var total = LLCaptureApi.fieldValue(inv, 'total');
    var ref = inv.document_ref || ('#' + inv.id);
    var el = document.createElement('div');
    el.className = 'success';
    el.id = 'successOverlay';
    el.innerHTML =
      '<div class="tick"><svg width="34" height="34" viewBox="0 0 34 34" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 17.6l6 6L26 11"/></svg></div>' +
      '<h2>Submitted</h2>' +
      '<p>' + (total ? money(total) + ' · ' : '') + esc(vendor) + '<br>' + esc(ref) +
      '<br><span style="color:var(--ink-3)">Status · ' + esc(inv.status || 'queued') + '</span></p>' +
      '<div class="stamp"><div class="sh">Pipeline</div>' +
      '<div class="sr">' + deps.IC.tick + '<span>Uploaded to LedgerLink</span><span class="m">done</span></div>' +
      '<div class="sr">' + deps.IC.tick + '<span>Fields reviewed</span><span class="m">done</span></div>' +
      '<div class="sr">' + deps.IC.tick + '<span>confirm-process</span><span class="m">done</span></div>' +
      '</div>' +
      '<div style="width:100%;margin-top:20px;display:flex;gap:10px">' +
      '<button class="btn sm sec" id="sucAnother" style="flex:1">Capture another</button>' +
      '<button class="btn sm" id="sucDone" style="flex:1">Done</button></div>';
    $('.screen[data-screen="capture"]').appendChild(el);
    $('#sucDone').addEventListener('click', function () {
      deps.hideSuccess();
      discardDraft();
      deps.showScreen('home');
      if (deps.onPendingChange) deps.onPendingChange();
    });
    $('#sucAnother').addEventListener('click', function () {
      deps.hideSuccess();
      discardDraft();
      void ensureCamera();
    });
  }

  async function startUploadFlow(opts) {
    if (uploading) {
      toast('Upload already in progress');
      return;
    }
    opts = opts || {};
    var file = opts.file || composedFile;
    try {
      if (!file) {
        if (!pages.length) {
          toast('Capture a page first');
          return;
        }
        toast('Preparing…');
        var c = cfg();
        var forcePdf = c.alwaysPdf || pages.length > 1;
        file = await LLPreprocess.composeUploadFile(
          pages.map(function (p) { return p.blob; }),
          { basename: c.basename || 'mobile-capture', forcePdf: forcePdf }
        );
        composedFile = file;
      }
    } catch (err) {
      toast(err.message || 'Could not prepare file');
      return;
    }

    uploading = true;
    toast('Uploading…');
    try {
      var result = await LLCaptureApi.uploadInvoice(file, {
        purchaseDocumentType: cfg().purchaseDocumentType,
        teamExpenseIntent: teIntent
      });
      var inv = result.invoice;
      LLCaptureApi.upsertPending({
        invoiceId: inv.id,
        startedAt: Date.now(),
        status: 'processing',
        label: inv.document_ref || ('#' + inv.id),
        vendor: inv.vendor || '',
        total: inv.total || ''
      });
      if (deps.onPendingChange) deps.onPendingChange();
      toast('Processing…');
      pollController.cancel = false;
      var token = pollController;
      var settled = await LLCaptureApi.watchUntilSettled(inv.id, {
        shouldCancel: function () { return token.cancel; },
        onTick: function (cur) {
          LLCaptureApi.updatePending(inv.id, {
            status: LLCaptureApi.isPipelineActive(cur.status) ? 'processing' : 'ready',
            vendor: LLCaptureApi.fieldValue(cur, 'vendor'),
            total: LLCaptureApi.fieldValue(cur, 'total'),
            label: cur.document_ref || ('#' + cur.id)
          });
          if (deps.onPendingChange) deps.onPendingChange();
        }
      });
      LLCaptureApi.updatePending(settled.id, {
        status: 'ready',
        vendor: LLCaptureApi.fieldValue(settled, 'vendor'),
        total: LLCaptureApi.fieldValue(settled, 'total'),
        label: settled.document_ref || ('#' + settled.id)
      });
      if (deps.onPendingChange) deps.onPendingChange();
      uploading = false;
      if (deps.state && deps.state.screen === 'capture') {
        if (preferClaimDetailsForm) {
          openClaimDetailsForm({
            mode: 'with_doc',
            invoice: settled,
            title: activeQaTitle,
            sourceLabel: file.name || 'Capture'
          });
        } else {
          openReviewSheet(settled, file.name || 'Capture');
        }
      } else {
        toast('Ready for review · open Capture or My items');
      }
    } catch (err) {
      uploading = false;
      if (err && err.cancelled) return;
      if (err && err.status === 409) {
        toast(err.message || 'Duplicate document');
        return;
      }
      // Keep pages + composedFile for retry
      toast((err && err.message ? err.message : 'Upload failed') + ' · tap Review & upload to retry');
      renderPageStrip();
      var strip = $('#capPageStrip');
      if (strip && !pages.length && composedFile) {
        strip.hidden = false;
        strip.innerHTML =
          '<div class="cap-page-actions" style="padding-top:8px">' +
          '<button type="button" class="btn sm" id="capRetryUpload">Retry upload</button></div>';
        $('#capRetryUpload', strip).addEventListener('click', function () {
          void startUploadFlow({ file: composedFile });
        });
      }
    }
  }

  function resumePendingPolls() {
    var list = LLCaptureApi.readPending().filter(function (p) {
      return p.status === 'processing';
    });
    list.forEach(function (p) {
      void LLCaptureApi.watchUntilSettled(p.invoiceId, {
        onTick: function (cur) {
          LLCaptureApi.updatePending(p.invoiceId, {
            status: LLCaptureApi.isPipelineActive(cur.status) ? 'processing' : 'ready',
            vendor: LLCaptureApi.fieldValue(cur, 'vendor'),
            total: LLCaptureApi.fieldValue(cur, 'total'),
            label: cur.document_ref || ('#' + cur.id)
          });
          if (deps.onPendingChange) deps.onPendingChange();
        }
      }).then(function (settled) {
        LLCaptureApi.updatePending(settled.id, {
          status: 'ready',
          vendor: LLCaptureApi.fieldValue(settled, 'vendor'),
          total: LLCaptureApi.fieldValue(settled, 'total'),
          label: settled.document_ref || ('#' + settled.id)
        });
        if (deps.onPendingChange) deps.onPendingChange();
      }).catch(function () { /* leave as processing — user can open from My items */ });
    });
  }

  function setMode(next) {
    if (!MODE_CFG[next]) return;
    var prev = mode;
    mode = next;
    var c = cfg();

    // Switching to receipt collapses multi-page drafts to a single shot
    if (!c.allowsMulti && pages.length > 1) {
      pages.slice(1).forEach(function (p) {
        if (p.thumbUrl) URL.revokeObjectURL(p.thumbUrl);
      });
      pages = pages.slice(0, 1);
      composedFile = null;
      toast('Receipt mode is single-page — kept page 1');
    }

    syncModeChrome();
    if (prev !== mode) {
      toast(
        mode === 'receipt'
          ? 'Receipt · one shot, auto-upload'
          : mode === 'multipage'
            ? 'Multi-page · each sheet'
            : 'Document · add pages, then upload'
      );
    }
  }

  var captureRouteIntents = [];
  /** Selected Quick Action document type for Capture scan. */
  var captureRouteDtCode = '';
  /** documentTypeCode (upper) → quick action item; drives Capture form list. */
  var quickActionByCode = {};

  function routeIntentFromKind(kind) {
    var k = String(kind || '').trim().toLowerCase();
    if (k === 'direct_payment') return 'expense_claim';
    if (k === 'expense_claim' || k === 'advance_requisition' || k === 'vendor_invoice') return k;
    return '';
  }

  function routeIntentLabel(intent, custom) {
    var label = String(custom || '').trim();
    if (label) return label;
    if (intent === 'advance_requisition') return 'Advance';
    if (intent === 'vendor_invoice') return 'Vendor';
    return 'Claim';
  }

  function captureRouteIcon(kind) {
    var k = String(kind || '').toLowerCase();
    if (k === 'advance_requisition') {
      return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8.2"/><path d="M12 8v8M9.5 10.5h5M9.5 13.5h5"/></svg>';
    }
    if (k === 'vendor_invoice') {
      return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7.2A2 2 0 0 1 6 5.2h3.3l1.9 2.2h7.8a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/></svg>';
    }
    return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h8.5L19 7.5V21H6z"/><path d="M14 3v5h5M9 12.5h6M9 16h4"/></svg>';
  }

  var CAP_CHIP_CHECK =
    '<svg class="chip-check" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.2 8.2l3.2 3.2 6.4-6.8"/></svg>';

  function quickActionCodes() {
    return Object.keys(quickActionByCode);
  }

  /** Document types allowed in Capture Fill — Quick Action forms only. */
  function visibleDocumentTypes() {
    var codes = quickActionCodes();
    if (!codes.length) return [];
    var byCode = {};
    documentTypes.forEach(function (dt) {
      var c = String((dt && dt.code) || '').trim().toUpperCase();
      if (c) byCode[c] = dt;
    });
    var rows = [];
    codes.forEach(function (code) {
      var qa = quickActionByCode[code];
      if (!qa) return;
      var intent = routeIntentFromKind(qa.teamExpenseKind || 'expense_claim');
      if (captureRouteIntents.length && teIntent && intent && intent !== teIntent) {
        return;
      }
      var dt = byCode[code];
      if (dt) {
        rows.push(dt);
      } else {
        rows.push({
          code: code,
          title: qa.label || qa.shortTitle || qa.title || code,
          teamExpenseKind: qa.teamExpenseKind || '',
          fields: []
        });
      }
    });
    return rows;
  }

  /** Rebuild Capture form chips + Fill list from Mobile Quick Action forms. */
  function setCaptureRoutesFromQuickActions(items) {
    var host = $('#capIntent');
    quickActionByCode = {};
    var routeItems = [];

    (Array.isArray(items) ? items : []).forEach(function (item) {
      if (!item || item.enabled === false) return;
      var code = String(item.documentTypeCode || '').trim().toUpperCase();
      if (!code) return;
      quickActionByCode[code] = item;
      var intent = routeIntentFromKind(item.teamExpenseKind || 'expense_claim');
      if (!intent) intent = 'expense_claim';
      routeItems.push({
        code: code,
        intent: intent,
        kind: item.teamExpenseKind || intent,
        label: routeIntentLabel(
          intent,
          item.label || item.shortTitle || item.title || code
        )
      });
    });

    var seenIntent = {};
    captureRouteIntents = [];
    routeItems.forEach(function (r) {
      if (!seenIntent[r.intent]) {
        seenIntent[r.intent] = true;
        captureRouteIntents.push(r.intent);
      }
    });

    if (host) {
      host.innerHTML = '';
      if (!routeItems.length) {
        host.hidden = true;
        captureRouteDtCode = '';
        teIntent = 'expense_claim';
      } else {
        host.hidden = false;
        if (
          !captureRouteDtCode ||
          !quickActionByCode[captureRouteDtCode]
        ) {
          captureRouteDtCode = routeItems[0].code;
        }
        var selected = quickActionByCode[captureRouteDtCode];
        teIntent = routeIntentFromKind(
          (selected && selected.teamExpenseKind) || routeItems[0].intent
        ) || routeItems[0].intent;
        preferredDtCode = captureRouteDtCode;

        routeItems.forEach(function (r) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'fchip';
          btn.setAttribute('data-intent', r.intent);
          btn.setAttribute('data-dt', r.code);
          btn.setAttribute('aria-pressed', 'false');
          btn.setAttribute('aria-label', 'Capture as ' + r.label);
          btn.innerHTML =
            CAP_CHIP_CHECK +
            captureRouteIcon(r.kind) +
            '<span>' + esc(r.label) + '</span>';
          host.appendChild(btn);
        });
      }
    }

    if (selectedDt) {
      var selCode = String(selectedDt.code || '').trim().toUpperCase();
      if (!quickActionByCode[selCode]) {
        selectedDt = null;
        fillFields = {};
        fillLineItems = [];
      }
    }

    syncIntentChrome(false);
    syncModeChrome();
    renderDtList();
    syncFillSubmit();
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

  function syncIntentChrome(scroll) {
    var host = $('#capIntent');
    $$('#capIntent .fchip').forEach(function (b) {
      var dt = String(b.getAttribute('data-dt') || '').toUpperCase();
      var on = captureRouteDtCode
        ? dt === String(captureRouteDtCode).toUpperCase()
        : b.dataset.intent === teIntent;
      b.setAttribute('aria-pressed', String(on));
      b.classList.toggle('active', on);
      if (on && scroll) scrollChipIntoBar(host, b);
    });
  }

  function selectCaptureRoute(dtCode, intent, options) {
    var opts = options || {};
    var code = String(dtCode || '').trim().toUpperCase();
    var nextIntent = routeIntentFromKind(intent) || intent || 'expense_claim';
    if (code && quickActionByCode[code]) {
      captureRouteDtCode = code;
      preferredDtCode = code;
      nextIntent =
        routeIntentFromKind(quickActionByCode[code].teamExpenseKind) || nextIntent;
    }
    setTeamExpenseIntent(nextIntent, {
      quiet: !!opts.quiet,
      force: true,
      skipChrome: true
    });
    syncIntentChrome(opts.scroll !== false);
    if (capturePath === 'fill') {
      renderDtList();
      syncFillSubmit();
    }
    if (!opts.quiet) {
      var qa = quickActionByCode[captureRouteDtCode];
      var label =
        (qa && (qa.label || qa.shortTitle || qa.title)) ||
        routeIntentLabel(teIntent);
      toast('Capturing as ' + label);
    }
  }

  function setTeamExpenseIntent(next, options) {
    var opts = options || {};
    var allowed = {
      expense_claim: 1,
      advance_requisition: 1,
      vendor_invoice: 1
    };
    if (!allowed[next]) return;
    // Capture tab buttons are QA-driven; Quick Action flows may force any intent.
    if (!opts.force && captureRouteIntents.length && captureRouteIntents.indexOf(next) < 0) {
      return;
    }
    var prev = teIntent;
    teIntent = next;
    if (!opts.skipChrome) syncIntentChrome(false);
    syncModeChrome();
    if (capturePath === 'fill') {
      if (selectedDt) {
        var selCode = String(selectedDt.code || '').trim().toUpperCase();
        var qa = quickActionByCode[selCode];
        var intent = routeIntentFromKind(
          (qa && qa.teamExpenseKind) || selectedDt.teamExpenseKind || ''
        );
        if (intent && intent !== teIntent) {
          selectedDt = null;
          fillFields = {};
          fillLineItems = [];
        }
      }
      renderDtList();
      syncFillSubmit();
    }
    if (opts.quiet || prev === teIntent) return;
    toast(
      teIntent === 'advance_requisition'
        ? 'Routing as Advance'
        : teIntent === 'vendor_invoice'
          ? 'Routing as Vendor invoice'
          : 'Routing as Claim'
    );
  }

  function syncCapturePathChrome() {
    $$('#capPath button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.path === capturePath);
    });
    var scan = $('#capScanPanel');
    var fill = $('#capFillPanel');
    var flash = $('#capFlash');
    if (scan) scan.hidden = capturePath !== 'scan';
    if (fill) fill.hidden = capturePath !== 'fill';
    if (flash) flash.hidden = capturePath !== 'scan';
  }

  function setCapturePath(next) {
    if (next !== 'scan' && next !== 'fill') return;
    capturePath = next;
    syncCapturePathChrome();
    if (capturePath === 'scan') {
      void ensureCamera();
    } else {
      stopCamera();
      void ensureDocumentTypes();
      renderDtList();
      syncFillSubmit();
    }
  }

  async function ensureDocumentTypes() {
    if (documentTypes.length) return documentTypes;
    try {
      documentTypes = await LLCaptureApi.listDocumentTypes();
    } catch (err) {
      documentTypes = [];
      toast((err && err.message) || 'Could not load document types');
    }
    return documentTypes;
  }

  function renderDtList() {
    var host = $('#capDtList');
    if (!host) return;
    var q = String(($('#capDtSearch') && $('#capDtSearch').value) || '')
      .trim()
      .toLowerCase();
    var rows = visibleDocumentTypes().filter(function (dt) {
      if (!q) return true;
      var code = String(dt.code || '').toUpperCase();
      var qa = quickActionByCode[code];
      var title = String(
        (qa && (qa.label || qa.shortTitle || qa.title)) || dt.title || ''
      ).toLowerCase();
      return (
        title.indexOf(q) >= 0 ||
        String(dt.code || '').toLowerCase().indexOf(q) >= 0
      );
    });
    if (!quickActionCodes().length) {
      host.innerHTML =
        '<div style="padding:14px;font-size:13px;color:var(--ink-3)">No Quick Action forms configured. Add forms in Settings → Mobile.</div>';
      return;
    }
    if (!rows.length) {
      host.innerHTML =
        '<div style="padding:14px;font-size:13px;color:var(--ink-3)">No Quick Action forms for this route</div>';
      return;
    }
    host.innerHTML = rows
      .map(function (dt) {
        var code = String(dt.code || '').toUpperCase();
        var qa = quickActionByCode[code];
        var title =
          (qa && (qa.label || qa.shortTitle || qa.title)) || dt.title || code;
        var on = selectedDt && String(selectedDt.code || '').toUpperCase() === code;
        return (
          '<button type="button" role="option" data-code="' +
          esc(dt.code) +
          '" class="' +
          (on ? 'active' : '') +
          '" aria-selected="' +
          on +
          '">' +
          esc(title) +
          '<span class="code">' +
          esc(dt.code) +
          '</span></button>'
        );
      })
      .join('');
  }

  function isRequiredFillKey(key) {
    if (!selectedDt) return false;
    return LLCaptureApi.requiredKeysForDocumentType(selectedDt).indexOf(key) >= 0;
  }

  function collectFillPayload() {
    var payload = {};
    Object.keys(fillFields).forEach(function (key) {
      var val = String(fillFields[key] || '').trim();
      if (val) payload[key] = val;
    });
    if (fillLineItems.length) {
      payload.line_items = fillLineItems
        .filter(function (row) {
          return String(row.description || '').trim();
        })
        .map(function (row) {
          return {
            description: String(row.description || '').trim(),
            qty: row.qty || '',
            unit_price: row.unit_price || '',
            amount: row.amount || '',
            tax_amount: row.tax_amount || ''
          };
        });
    }
    var bsb = String(fillFields.bank_bsb || '').trim();
    var acct = String(fillFields.bank_account || '').trim();
    if ((bsb || acct) && !payload.bank_details) {
      payload.bank_details = [bsb, acct].filter(Boolean).join(' · ');
    }
    return payload;
  }

  function fillRequiredOk() {
    if (!selectedDt) return false;
    var required = LLCaptureApi.requiredKeysForDocumentType(selectedDt);
    if (!required.length) return false;
    return required.every(function (key) {
      if (key === 'line_items') {
        return fillLineItems.some(function (row) {
          return String(row.description || '').trim();
        });
      }
      if (key === 'bank_details') {
        return (
          String(fillFields.bank_details || '').trim() ||
          String(fillFields.bank_bsb || '').trim() ||
          String(fillFields.bank_account || '').trim()
        );
      }
      return String(fillFields[key] || '').trim();
    });
  }

  function renderLineItemsEditor(host) {
    var wrap = document.createElement('div');
    wrap.className = 'cap-lines';
    wrap.innerHTML =
      '<div class="cap-lines-h">Line items' +
      (isRequiredFillKey('line_items') ? ' <span class="req">*</span>' : '') +
      '</div>' +
      '<p class="cap-lines-hint">Add every expense line — not just one total.</p>' +
      '<div class="cap-lines-rows"></div>' +
      '<button type="button" class="cap-lines-add" data-add-line>+ Add another line</button>';
    host.appendChild(wrap);
    var rowsHost = $('.cap-lines-rows', wrap);
    var required = isRequiredFillKey('line_items');

    function paint() {
      if (!fillLineItems.length) {
        fillLineItems.push(emptyLineItem());
      }
      rowsHost.innerHTML = fillLineItems
        .map(function (row, idx) {
          var canRemove = fillLineItems.length > 1 || !required;
          return (
            '<div class="cap-line-row" data-li="' +
            idx +
            '">' +
            '<div class="cap-line-top">' +
            '<span class="cap-line-idx">Line ' +
            (idx + 1) +
            '</span>' +
            (canRemove
              ? '<button type="button" class="cap-line-x" data-rm="' +
                idx +
                '" aria-label="Remove line ' +
                (idx + 1) +
                '">Remove</button>'
              : '') +
            '</div>' +
            '<input data-k="description" type="text" placeholder="Description (e.g. Taxi to airport)" value="' +
            esc(row.description || '') +
            '">' +
            '<div class="cap-line-nums">' +
            '<input data-k="qty" inputmode="decimal" type="text" placeholder="Qty" value="' +
            esc(row.qty || '') +
            '" aria-label="Quantity">' +
            '<input data-k="unit_price" inputmode="decimal" type="text" placeholder="Unit $" value="' +
            esc(row.unit_price || '') +
            '" aria-label="Unit price">' +
            '<input data-k="amount" inputmode="decimal" type="text" placeholder="Amount $" value="' +
            esc(row.amount || '') +
            '" aria-label="Amount">' +
            '</div></div>'
          );
        })
        .join('');
      $$('.cap-line-row', rowsHost).forEach(function (rowEl) {
        var idx = Number(rowEl.dataset.li);
        $$('input', rowEl).forEach(function (input) {
          input.addEventListener('input', function () {
            if (!fillLineItems[idx]) return;
            fillLineItems[idx][input.dataset.k] = String(input.value || '');
            syncFillSubmit();
          });
        });
      });
      $$('[data-rm]', rowsHost).forEach(function (btn) {
        btn.addEventListener('click', function () {
          var idx = Number(btn.getAttribute('data-rm'));
          if (fillLineItems.length <= 1 && required) return;
          fillLineItems.splice(idx, 1);
          if (!fillLineItems.length) fillLineItems.push(emptyLineItem());
          paint();
          syncFillSubmit();
        });
      });
    }

    $('[data-add-line]', wrap).addEventListener('click', function () {
      fillLineItems.push(emptyLineItem());
      paint();
      syncFillSubmit();
      var last = $$('.cap-line-row input[data-k="description"]', rowsHost);
      var focusEl = last[last.length - 1];
      if (focusEl) focusEl.focus();
    });
    paint();
  }

  function selectDocumentType(code) {
    var want = String(code || '').trim().toUpperCase();
    if (want && quickActionCodes().length && !quickActionByCode[want]) {
      toast('Only Quick Action forms can be used here');
      return;
    }
    selectedDt =
      documentTypes.find(function (dt) {
        return String(dt.code || '').toUpperCase() === want;
      }) || null;
    // Allow selecting a QA code even if full DT catalog row is missing.
    if (!selectedDt && quickActionByCode[want]) {
      var qaStub = quickActionByCode[want];
      selectedDt = {
        code: want,
        title: qaStub.label || qaStub.shortTitle || qaStub.title || want,
        teamExpenseKind: qaStub.teamExpenseKind || '',
        fields: []
      };
    }
    fillFields = {};
    fillLineItems = [];
    var sel = $('#capDtSelected');
    var fieldsHost = $('#capDtFields');
    if (!selectedDt) {
      if (sel) sel.hidden = true;
      if (fieldsHost) {
        fieldsHost.hidden = true;
        fieldsHost.innerHTML = '';
      }
      renderDtList();
      syncFillSubmit();
      return;
    }
    var qa = quickActionByCode[want];
    var displayTitle =
      (qa && (qa.label || qa.shortTitle || qa.title)) || selectedDt.title || want;
    if (sel) {
      sel.hidden = false;
      sel.textContent = displayTitle + ' · ' + selectedDt.code;
    }
    var keys = LLCaptureApi.formKeysForDocumentType(selectedDt);
    if (!keys.length) {
      toast('This document type has no fillable fields');
      selectedDt = null;
      if (sel) sel.hidden = true;
      if (fieldsHost) {
        fieldsHost.hidden = true;
        fieldsHost.innerHTML = '';
      }
      renderDtList();
      syncFillSubmit();
      return;
    }
    if (!fieldsHost) {
      renderDtList();
      syncFillSubmit();
      return;
    }
    fieldsHost.hidden = false;
    fieldsHost.innerHTML = '';
    keys.forEach(function (key) {
      if (key === 'line_items') {
        renderLineItemsEditor(fieldsHost);
        return;
      }
      if (key === 'bank_details') {
        var bank = document.createElement('div');
        bank.className = 'cap-bank';
        bank.innerHTML =
          '<div class="cap-lines-h">Bank details' +
          (isRequiredFillKey('bank_details') ? ' <span class="req">*</span>' : '') +
          '</div>' +
          '<label>BSB<input data-field="bank_bsb" type="text" autocomplete="off"></label>' +
          '<label>Account<input data-field="bank_account" type="text" autocomplete="off"></label>';
        fieldsHost.appendChild(bank);
        return;
      }
      var label = document.createElement('label');
      var reqMark = isRequiredFillKey(key) ? ' <span class="req">*</span>' : '';
      var inputType =
        key.indexOf('date') >= 0
          ? 'date'
          : key === 'total' || key === 'subtotal' || key === 'gst' || key === 'gst_rate'
            ? 'number'
            : 'text';
      var step = inputType === 'number' ? ' step="0.01"' : '';
      label.innerHTML =
        esc(LLCaptureApi.fieldLabel(key)) +
        reqMark +
        '<input data-field="' +
        esc(key) +
        '" type="' +
        inputType +
        '"' +
        step +
        ' autocomplete="off">';
      fieldsHost.appendChild(label);
    });
    $$('input[data-field]', fieldsHost).forEach(function (input) {
      input.addEventListener('input', function () {
        fillFields[input.dataset.field] = String(input.value || '').trim();
        syncFillSubmit();
      });
    });
    renderDtList();
    syncFillSubmit();
  }

  function syncFillFileMeta() {
    var meta = $('#capFillFileMeta');
    var strip = $('#capFillPageStrip');
    if (meta) {
      if (!fillPages.length) {
        meta.textContent = 'No reference images yet';
      } else if (fillPages.length === 1 && fillPages[0].kind === 'pdf') {
        meta.textContent = fillPages[0].name || 'PDF attached';
      } else {
        meta.textContent =
          fillPages.length +
          ' image' +
          (fillPages.length === 1 ? '' : 's') +
          ' attached · combined on submit';
      }
    }
    if (!strip) return;
    if (!fillPages.length) {
      strip.hidden = true;
      strip.innerHTML = '';
      return;
    }
    strip.hidden = false;
    strip.innerHTML =
      '<div class="cap-pages">' +
      fillPages
        .map(function (p, i) {
          if (p.kind === 'pdf') {
            return (
              '<div class="cap-page cap-page--pdf" data-fi="' +
              i +
              '">PDF<button type="button" class="cap-page-x" data-rm="' +
              i +
              '" aria-label="Remove PDF">×</button></div>'
            );
          }
          return (
            '<div class="cap-page" data-fi="' +
            i +
            '">' +
            '<img src="' +
            p.thumbUrl +
            '" alt="Image ' +
            (i + 1) +
            '">' +
            '<button type="button" class="cap-page-x" data-rm="' +
            i +
            '" aria-label="Remove image ' +
            (i + 1) +
            '">×</button>' +
            '<span class="cap-page-n">' +
            (i + 1) +
            '</span></div>'
          );
        })
        .join('') +
      '</div>';
    $$('[data-rm]', strip).forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var idx = Number(btn.getAttribute('data-rm'));
        if (fillPages[idx] && fillPages[idx].thumbUrl) {
          URL.revokeObjectURL(fillPages[idx].thumbUrl);
        }
        fillPages.splice(idx, 1);
        syncFillFileMeta();
        syncFillSubmit();
      });
    });
  }

  function syncFillSubmit() {
    var btn = $('#capFillSubmit');
    if (!btn) return;
    btn.disabled = !(fillRequiredOk() && fillPages.length) || fillSubmitting;
  }

  async function addFillImage(source) {
    var prepared = await LLPreprocess.compressImage(source);
    var thumbUrl = URL.createObjectURL(prepared.blob);
    var name =
      (source && source.name) ||
      'photo-' + (fillPages.length + 1) + '.jpg';
    fillPages.push({
      blob: prepared.blob,
      thumbUrl: thumbUrl,
      name: name,
      kind: 'image'
    });
  }

  async function onFillLibraryFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;

    var pdfs = files.filter(function (f) {
      return /\.pdf$/i.test(f.name || '') || (f.type || '') === 'application/pdf';
    });
    var images = files.filter(function (f) {
      return pdfs.indexOf(f) < 0;
    });

    if (pdfs.length) {
      if (images.length) {
        toast('PDF replaces photos for this submission');
      }
      clearFillPages();
      fillPages.push({
        blob: pdfs[0],
        thumbUrl: '',
        name: pdfs[0].name || 'reference.pdf',
        kind: 'pdf'
      });
      syncFillFileMeta();
      syncFillSubmit();
      toast('PDF attached');
      return;
    }

    // Drop any prior PDF when adding photos
    if (fillPages.length === 1 && fillPages[0].kind === 'pdf') {
      clearFillPages();
    }

    for (var i = 0; i < images.length; i++) {
      try {
        await addFillImage(images[i]);
      } catch (err) {
        toast((err && err.message) || 'Could not read image');
      }
    }
    syncFillFileMeta();
    syncFillSubmit();
    if (fillPages.length) {
      toast(
        fillPages.length +
          ' image' +
          (fillPages.length === 1 ? '' : 's') +
          ' ready · add more or Submit'
      );
    }
  }

  async function buildFillUploadFile() {
    if (!fillPages.length) throw new Error('Attach at least one image or PDF');
    if (fillPages.length === 1 && fillPages[0].kind === 'pdf') {
      return fillPages[0].blob;
    }
    var blobs = fillPages.map(function (p) {
      return p.blob;
    });
    return LLPreprocess.composeUploadFile(blobs, {
      basename: 'manual-capture',
      forcePdf: blobs.length > 1
    });
  }

  async function submitFillForm() {
    if (fillSubmitting || !selectedDt || !fillPages.length) return;
    if (!fillRequiredOk()) {
      toast('Fill all required fields marked *');
      return;
    }
    var payload = collectFillPayload();
    fillSubmitting = true;
    syncFillSubmit();
    toast(
      fillPages.length > 1
        ? 'Combining ' + fillPages.length + ' images…'
        : 'Submitting…'
    );
    try {
      var uploadFile = await buildFillUploadFile();
      var result = await LLCaptureApi.manualCapture(
        uploadFile,
        selectedDt.code,
        payload
      );
      var inv = result.invoice;
      LLCaptureApi.upsertPending({
        invoiceId: inv.id,
        startedAt: Date.now(),
        status: 'processing',
        label: inv.document_ref || ('#' + inv.id),
        vendor: inv.vendor || '',
        total: inv.total || ''
      });
      if (deps.onPendingChange) deps.onPendingChange();
      pollController.cancel = false;
      var token = pollController;
      var settled = await LLCaptureApi.watchUntilSettled(inv.id, {
        shouldCancel: function () {
          return token.cancel;
        },
        onTick: function (cur) {
          LLCaptureApi.updatePending(inv.id, {
            status: LLCaptureApi.isPipelineActive(cur.status) ? 'processing' : 'ready',
            vendor: LLCaptureApi.fieldValue(cur, 'vendor'),
            total: LLCaptureApi.fieldValue(cur, 'total'),
            label: cur.document_ref || ('#' + cur.id)
          });
          if (deps.onPendingChange) deps.onPendingChange();
        }
      });
      LLCaptureApi.updatePending(settled.id, {
        status: 'ready',
        vendor: LLCaptureApi.fieldValue(settled, 'vendor'),
        total: LLCaptureApi.fieldValue(settled, 'total'),
        label: settled.document_ref || ('#' + settled.id)
      });
      if (deps.onPendingChange) deps.onPendingChange();
      fillSubmitting = false;
      clearFillPages();
      syncFillFileMeta();
      syncFillSubmit();
      openReviewSheet(settled, 'Manual entry');
    } catch (err) {
      fillSubmitting = false;
      syncFillSubmit();
      if (err && err.cancelled) return;
      toast((err && err.message) || 'Submit failed');
    }
  }

  function init(d) {
    deps = d;
    var fileInput = $('#capLibraryInput');
    if (!fileInput) return;

    $$('.cam-modes button').forEach(function (b) {
      b.addEventListener('click', function () {
        setMode(b.dataset.mode || 'invoice');
      });
    });
    setMode('invoice');

    var intentHost = $('#capIntent');
    if (intentHost) {
      intentHost.addEventListener('click', function (e) {
        var b = e.target.closest('.fchip[data-dt], button[data-intent]');
        if (!b || !intentHost.contains(b)) return;
        selectCaptureRoute(
          b.getAttribute('data-dt') || '',
          b.dataset.intent || 'expense_claim',
          { scroll: true }
        );
      });
    }
    setTeamExpenseIntent('expense_claim', { quiet: true, force: true });

    $$('#capPath button').forEach(function (b) {
      b.addEventListener('click', function () {
        setCapturePath(b.dataset.path || 'scan');
      });
    });
    setCapturePath('scan');

    var dtList = $('#capDtList');
    if (dtList) {
      dtList.addEventListener('click', function (e) {
        var btn = e.target.closest('button[data-code]');
        if (!btn) return;
        selectDocumentType(btn.dataset.code);
      });
    }
    var dtSearch = $('#capDtSearch');
    if (dtSearch) {
      dtSearch.addEventListener('input', function () {
        renderDtList();
      });
    }
    var fillFileBtn = $('#capFillFile');
    var fillFileInput = $('#capFillLibraryInput');
    if (fillFileBtn && fillFileInput) {
      fillFileBtn.addEventListener('click', function () {
        fillFileInput.removeAttribute('capture');
        fillFileInput.setAttribute(
          'accept',
          'image/*,application/pdf,.pdf,.jpg,.jpeg,.png,.webp'
        );
        fillFileInput.setAttribute('multiple', '');
        fillFileInput.value = '';
        fillFileInput.click();
      });
      fillFileInput.addEventListener('change', function () {
        void onFillLibraryFiles(fillFileInput.files);
      });
    }
    var fillShot = $('#capFillShot');
    if (fillShot && fillFileInput) {
      fillShot.addEventListener('click', function () {
        fillFileInput.setAttribute('capture', 'environment');
        fillFileInput.setAttribute('accept', 'image/*');
        // Camera capture is typically one shot; keep multiple for gallery picks.
        fillFileInput.removeAttribute('multiple');
        fillFileInput.value = '';
        fillFileInput.click();
      });
    }
    var fillSubmit = $('#capFillSubmit');
    if (fillSubmit) {
      fillSubmit.addEventListener('click', function () {
        void submitFillForm();
      });
    }

    var flashBtn = $('#capFlash');
    if (flashBtn) {
      flashBtn.addEventListener('click', function () {
        cycleFlash();
      });
    }

    $('#shutter').addEventListener('click', function () {
      void onShutter();
    });
    $('#capFile').addEventListener('click', function () {
      fileInput.value = '';
      fileInput.click();
    });
    fileInput.addEventListener('change', function () {
      void onLibraryFiles(fileInput.files);
    });

    resumePendingPolls();
  }

  function onShowCapture() {
    if (capturePath === 'fill') {
      void ensureDocumentTypes().then(function () {
        renderDtList();
      });
      return;
    }
    void ensureCamera();
  }

  function onHideCapture() {
    // Keep stream while in app for snappy return; stop only on page hide
  }

  global.addEventListener('pagehide', stopCamera);
  global.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      // keep draft; stop camera to free sensor when backgrounded
      stopCamera();
    } else if (deps && deps.state && deps.state.screen === 'capture') {
      void ensureCamera();
    }
  });

  global.LLCapture = {
    init: init,
    onShowCapture: onShowCapture,
    onHideCapture: onHideCapture,
    discardDraft: discardDraft,
    resumePendingPolls: resumePendingPolls,
    setTeamExpenseIntent: setTeamExpenseIntent,
    setCaptureRoutesFromQuickActions: setCaptureRoutesFromQuickActions,
    startQuickActionWithDoc: startQuickActionWithDoc,
    startQuickActionWithoutDoc: startQuickActionWithoutDoc,
    startClaimWithDoc: startClaimWithDoc,
    startClaimWithoutDoc: startClaimWithoutDoc,
    startAdvanceCapture: startAdvanceCapture,
    openClaimDetailsForm: openClaimDetailsForm,
    openReviewForId: function (id, options) {
      return LLCaptureApi.getInvoice(id).then(function (inv) {
        openReviewSheet(inv, (options && options.sourceLabel) || 'My items', {
          fromHome: !!(options && options.fromHome)
        });
        return inv;
      });
    },
    getPages: function () { return pages; },
    getComposedFile: function () { return composedFile; }
  };
})(window);
