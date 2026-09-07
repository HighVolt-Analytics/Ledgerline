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
      // Keep draft pages until submit success so retry is possible if confirm fails later;
      // clear composed for next capture after successful review open.
      if (deps.state && deps.state.screen === 'capture') {
        openReviewSheet(settled, file.name || 'Capture');
      } else {
        toast('Ready for review · open Capture or tap the activity row');
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
      }).catch(function () { /* leave as processing / user retries via activity */ });
    });
  }

  function prependActivityRows(demoHtml) {
    // Demo activity removed — use refreshHomeActivity instead.
    return demoHtml || '';
  }

  function invoiceActivityRow(inv) {
    var tone = statusTone(inv.status);
    var title = inv.vendor || inv.document_heading || inv.document_ref || ('Document #' + inv.id);
    var amount = inv.total != null && inv.total !== '' ? money(inv.total) : '';
    var meta = [
      inv.document_ref || ('#' + inv.id),
      amount,
      inv.status,
      relativeTime(inv.created_at || inv.updated_at)
    ].filter(Boolean).join(' · ');
    var dt = inv.document_type_code || 'DOC';
    return '<button class="row" type="button" data-invoice-id="' + inv.id + '">' +
      '<span class="tl-dot ' + tone + '"></span>' +
      '<span class="main"><span class="t truncate" style="display:block">' + esc(title) + '</span>' +
      '<span class="s truncate" style="display:block">' + esc(meta) + '</span></span>' +
      '<span class="chip dt">' + esc(dt) + '</span>' + deps.IC.chev + '</button>';
  }

  function pendingActivityRows() {
    return LLCaptureApi.readPending().map(function (p) {
      var tone = p.status === 'processing' ? 'warn' : p.status === 'ready' ? 'acc' : 'pos';
      var title =
        p.status === 'processing'
          ? 'Processing capture…'
          : p.status === 'ready'
            ? 'Ready for review'
            : p.status === 'submitted'
              ? 'Capture submitted'
              : 'Capture';
      var metaParts = [
        p.label || ('#' + p.invoiceId),
        p.vendor,
        p.total ? money(p.total) : '',
        p.status
      ].filter(Boolean);
      return '<button class="row" type="button" data-pending-inv="' + p.invoiceId + '">' +
        '<span class="tl-dot ' + tone + '"></span>' +
        '<span class="main"><span class="t truncate" style="display:block">' + esc(title) + '</span>' +
        '<span class="s truncate" style="display:block">' + esc(metaParts.join(' · ')) + '</span></span>' +
        '<span class="chip dt">CAP</span>' + deps.IC.chev + '</button>';
    }).join('');
  }

  var _homeActivityTimer = null;
  var _homeActivityInFlight = null;
  var _homeActivityQueued = false;

  async function _refreshHomeActivityNow() {
    var host = $('#activityRows');
    var countEl = $('#actCount');
    if (!host) return;
    host.innerHTML =
      '<div class="empty" style="padding:20px;font-size:13px;color:var(--ink-3)">Loading your recent documents…</div>';
    var pendingHtml = pendingActivityRows();
    try {
      // Only documents for this signed-in employee (not the whole tenant).
      var rows = await LLCaptureApi.listMyInvoices({ pageSize: 20 });
      var pendingIds = {};
      LLCaptureApi.readPending().forEach(function (p) {
        pendingIds[Number(p.invoiceId)] = 1;
      });
      var docsHtml = rows
        .filter(function (inv) { return !pendingIds[Number(inv.id)]; })
        .map(invoiceActivityRow)
        .join('');
      var html = pendingHtml + docsHtml;
      if (!html) {
        host.innerHTML =
          '<div class="empty" style="padding:20px;font-size:13px;color:var(--ink-3)">No documents of yours yet. Capture one to get started.</div>';
        if (countEl) countEl.textContent = '0 items';
        return;
      }
      host.innerHTML = html;
      if (countEl) {
        var n = LLCaptureApi.readPending().length + rows.filter(function (inv) {
          return !pendingIds[Number(inv.id)];
        }).length;
        countEl.textContent = n + ' item' + (n === 1 ? '' : 's');
      }
    } catch (err) {
      host.innerHTML = pendingHtml ||
        '<div class="empty" style="padding:20px;font-size:13px;color:var(--ink-3)">' +
        esc(err.message || 'Could not load your recent documents') + '</div>';
      if (countEl) countEl.textContent = LLCaptureApi.readPending().length + ' items';
    }
  }

  /** Debounce + single-flight: Home show + pending updates were stacking 3–4 list GETs. */
  function refreshHomeActivity() {
    _homeActivityQueued = true;
    if (_homeActivityTimer) clearTimeout(_homeActivityTimer);
    _homeActivityTimer = setTimeout(function () {
      _homeActivityTimer = null;
      if (_homeActivityInFlight) return;
      _homeActivityQueued = false;
      _homeActivityInFlight = _refreshHomeActivityNow().finally(function () {
        _homeActivityInFlight = null;
        if (_homeActivityQueued) refreshHomeActivity();
      });
    }, 250);
  }

  function wireActivityClicks(root) {
    (root || document).addEventListener('click', function (e) {
      var pendingBtn = e.target.closest('[data-pending-inv]');
      var docBtn = e.target.closest('[data-invoice-id]');
      var btn = pendingBtn || docBtn;
      if (!btn) return;
      var id = Number(pendingBtn ? btn.getAttribute('data-pending-inv') : btn.getAttribute('data-invoice-id'));
      if (!id) return;
      toast('Opening…');
      LLCaptureApi.getInvoice(id)
        .then(function (inv) {
          if (LLCaptureApi.isPipelineActive(inv.status)) {
            toast('Still processing…');
            deps.showScreen('home');
            return;
          }
          openReviewSheet(inv, 'Recent activity', { fromHome: !pendingBtn });
        })
        .catch(function (err) {
          toast(err.message || 'Could not load document');
        });
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

  function syncIntentChrome() {
    $$('#capIntent button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.intent === teIntent);
    });
  }

  function setTeamExpenseIntent(next, options) {
    var opts = options || {};
    var allowed = {
      expense_claim: 1,
      advance_requisition: 1,
      vendor_invoice: 1
    };
    if (!allowed[next]) return;
    var prev = teIntent;
    teIntent = next;
    syncIntentChrome();
    syncModeChrome();
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
    var rows = documentTypes.filter(function (dt) {
      if (!q) return true;
      return (
        dt.title.toLowerCase().indexOf(q) >= 0 ||
        dt.code.toLowerCase().indexOf(q) >= 0
      );
    });
    if (!rows.length) {
      host.innerHTML =
        '<div style="padding:14px;font-size:13px;color:var(--ink-3)">No matching document types</div>';
      return;
    }
    host.innerHTML = rows
      .map(function (dt) {
        var on = selectedDt && selectedDt.code === dt.code;
        return (
          '<button type="button" role="option" data-code="' +
          esc(dt.code) +
          '" class="' +
          (on ? 'active' : '') +
          '" aria-selected="' +
          on +
          '">' +
          esc(dt.title) +
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
    selectedDt =
      documentTypes.find(function (dt) {
        return dt.code === code;
      }) || null;
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
    if (sel) {
      sel.hidden = false;
      sel.textContent = selectedDt.title + ' · ' + selectedDt.code;
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

    $$('#capIntent button').forEach(function (b) {
      b.addEventListener('click', function () {
        setTeamExpenseIntent(b.dataset.intent || 'expense_claim');
      });
    });
    setTeamExpenseIntent('expense_claim', { quiet: true });

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

    wireActivityClicks(document);
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
    prependActivityRows: prependActivityRows,
    refreshHomeActivity: refreshHomeActivity,
    resumePendingPolls: resumePendingPolls,
    setTeamExpenseIntent: setTeamExpenseIntent,
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
