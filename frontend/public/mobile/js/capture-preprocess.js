/* Client-side image prep for mobile capture: orient, compress, multi-page PDF. */
(function (global) {
  'use strict';

  var MAX_EDGE = 1600;
  var JPEG_QUALITY = 0.82;

  function readJpegSize(bytes) {
    var view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    var i = 2;
    while (i < view.length) {
      if (view[i] !== 0xff) break;
      var marker = view[i + 1];
      if (marker === 0xc0 || marker === 0xc1 || marker === 0xc2) {
        return {
          height: (view[i + 5] << 8) | view[i + 6],
          width: (view[i + 7] << 8) | view[i + 8]
        };
      }
      var len = (view[i + 2] << 8) | view[i + 3];
      i += 2 + len;
    }
    return { width: 0, height: 0 };
  }

  function blobToArrayBuffer(blob) {
    return blob.arrayBuffer ? blob.arrayBuffer() : new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(r.result); };
      r.onerror = reject;
      r.readAsArrayBuffer(blob);
    });
  }

  async function loadBitmap(source) {
    if (typeof createImageBitmap === 'function') {
      try {
        return await createImageBitmap(source, { imageOrientation: 'from-image' });
      } catch (e1) {
        try {
          return await createImageBitmap(source);
        } catch (e2) { /* fall through */ }
      }
    }
    return new Promise(function (resolve, reject) {
      var url = typeof source === 'string' ? source : URL.createObjectURL(source);
      var img = new Image();
      img.onload = function () {
        if (typeof source !== 'string') URL.revokeObjectURL(url);
        resolve(img);
      };
      img.onerror = function () {
        if (typeof source !== 'string') URL.revokeObjectURL(url);
        reject(new Error('Could not load image'));
      };
      img.src = url;
    });
  }

  function drawToCanvas(bitmap, maxEdge) {
    var w = bitmap.width || bitmap.naturalWidth;
    var h = bitmap.height || bitmap.naturalHeight;
    var scale = 1;
    var longEdge = Math.max(w, h);
    if (longEdge > maxEdge) scale = maxEdge / longEdge;
    var cw = Math.max(1, Math.round(w * scale));
    var ch = Math.max(1, Math.round(h * scale));
    var canvas = document.createElement('canvas');
    canvas.width = cw;
    canvas.height = ch;
    var ctx = canvas.getContext('2d');
    ctx.drawImage(bitmap, 0, 0, cw, ch);
    if (bitmap.close) {
      try { bitmap.close(); } catch (e) { /* ignore */ }
    }
    return canvas;
  }

  function canvasToJpegBlob(canvas, quality) {
    return new Promise(function (resolve, reject) {
      if (canvas.toBlob) {
        canvas.toBlob(function (b) {
          if (b) resolve(b);
          else reject(new Error('JPEG encode failed'));
        }, 'image/jpeg', quality);
        return;
      }
      try {
        var dataUrl = canvas.toDataURL('image/jpeg', quality);
        var bin = atob(dataUrl.split(',')[1]);
        var arr = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        resolve(new Blob([arr], { type: 'image/jpeg' }));
      } catch (e) {
        reject(e);
      }
    });
  }

  /** Normalize orientation + compress a File/Blob/canvas frame to JPEG. */
  async function compressImage(source, options) {
    var maxEdge = (options && options.maxEdge) || MAX_EDGE;
    var quality = (options && options.quality) || JPEG_QUALITY;
    var bitmap = await loadBitmap(source);
    var canvas = drawToCanvas(bitmap, maxEdge);
    var blob = await canvasToJpegBlob(canvas, quality);
    return {
      blob: blob,
      width: canvas.width,
      height: canvas.height,
      mime: 'image/jpeg'
    };
  }

  /** Grab current video frame → compressed JPEG. */
  async function captureVideoFrame(video, options) {
    if (!video || !video.videoWidth) {
      throw new Error('Camera not ready');
    }
    var canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    return compressImage(canvas, options);
  }

  function utf8(str) {
    return new TextEncoder().encode(str);
  }

  function concatBytes(parts) {
    var total = 0;
    parts.forEach(function (p) { total += p.length; });
    var out = new Uint8Array(total);
    var off = 0;
    parts.forEach(function (p) {
      out.set(p, off);
      off += p.length;
    });
    return out;
  }

  /**
   * Build a minimal multi-page PDF embedding JPEG page bytes.
   * @param {{ bytes: Uint8Array, width: number, height: number }[]} pages
   */
  function jpegPagesToPdf(pages) {
    if (!pages.length) throw new Error('No pages');
    var objs = [];
    function addObj(bodyBytes) {
      objs.push(bodyBytes);
      return objs.length;
    }

    var catalogId = 1;
    var pagesId = 2;
    // Reserve ids: catalog=1, pages=2, then per page: page, content, image
    var kids = [];
    var bodyParts = [];
    var offsets = [0];

    function pushObj(id, content) {
      // placeholder — we rebuild linearly below
      return { id: id, content: content };
    }

    var entries = [];
    entries.push(pushObj(catalogId, utf8('<< /Type /Catalog /Pages 2 0 R >>')));
    // pages kids filled later
    var pageEntries = [];
    var nextId = 3;
    pages.forEach(function (pg) {
      var pageId = nextId++;
      var contentId = nextId++;
      var imageId = nextId++;
      kids.push(pageId + ' 0 R');
      var w = pg.width;
      var h = pg.height;
      var contentStream = 'q ' + w + ' 0 0 ' + h + ' 0 0 cm /Im0 Do Q\n';
      var contentBytes = utf8(contentStream);
      pageEntries.push({
        pageId: pageId,
        contentId: contentId,
        imageId: imageId,
        w: w,
        h: h,
        contentBytes: contentBytes,
        jpeg: pg.bytes
      });
    });

    entries[0] = pushObj(1, utf8('<< /Type /Catalog /Pages 2 0 R >>'));
    entries.push(pushObj(2, utf8(
      '<< /Type /Pages /Kids [' + kids.join(' ') + '] /Count ' + pages.length + ' >>'
    )));

    pageEntries.forEach(function (pe) {
      entries.push(pushObj(pe.pageId, utf8(
        '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ' + pe.w + ' ' + pe.h + '] ' +
        '/Contents ' + pe.contentId + ' 0 R ' +
        '/Resources << /XObject << /Im0 ' + pe.imageId + ' 0 R >> >> >>'
      )));
      entries.push(pushObj(pe.contentId, concatBytes([
        utf8('<< /Length ' + pe.contentBytes.length + ' >>\nstream\n'),
        pe.contentBytes,
        utf8('\nendstream')
      ])));
      entries.push(pushObj(pe.imageId, concatBytes([
        utf8(
          '<< /Type /XObject /Subtype /Image /Width ' + pe.w +
          ' /Height ' + pe.h +
          ' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ' +
          pe.jpeg.length + ' >>\nstream\n'
        ),
        pe.jpeg,
        utf8('\nendstream')
      ])));
    });

    // Sort by id and write
    entries.sort(function (a, b) { return a.id - b.id; });
    var chunks = [utf8('%PDF-1.4\n')];
    var xref = [];
    var offset = chunks[0].length;
    entries.forEach(function (ent) {
      xref[ent.id] = offset;
      var header = utf8(ent.id + ' 0 obj\n');
      var footer = utf8('\nendobj\n');
      chunks.push(header, ent.content, footer);
      offset += header.length + ent.content.length + footer.length;
    });

    var xrefStart = offset;
    var xrefLines = ['xref', '0 ' + (entries.length + 1), '0000000000 65535 f '];
    for (var id = 1; id <= entries.length; id++) {
      var off = xref[id] || 0;
      xrefLines.push(String(off).padStart(10, '0') + ' 00000 n ');
    }
    var xrefBlock = utf8(xrefLines.join('\n') + '\n');
    var trailer = utf8(
      'trailer\n<< /Size ' + (entries.length + 1) + ' /Root 1 0 R >>\n' +
      'startxref\n' + xrefStart + '\n%%EOF\n'
    );
    chunks.push(xrefBlock, trailer);
    return new Blob([concatBytes(chunks)], { type: 'application/pdf' });
  }

  /** Compose one or more compressed JPEG page blobs into upload File. */
  async function composeUploadFile(pageBlobs, options) {
    var nameBase = (options && options.basename) || 'capture';
    if (!pageBlobs || !pageBlobs.length) {
      throw new Error('No pages to upload');
    }
    if (pageBlobs.length === 1 && !(options && options.forcePdf)) {
      var single = pageBlobs[0];
      try {
        return new File([single], nameBase + '.jpg', { type: 'image/jpeg' });
      } catch (e) {
        return single;
      }
    }
    var pages = [];
    for (var i = 0; i < pageBlobs.length; i++) {
      var buf = await blobToArrayBuffer(pageBlobs[i]);
      var bytes = new Uint8Array(buf);
      var size = readJpegSize(bytes);
      if (!size.width || !size.height) {
        throw new Error('Invalid JPEG page');
      }
      pages.push({ bytes: bytes, width: size.width, height: size.height });
    }
    var pdf = jpegPagesToPdf(pages);
    try {
      return new File([pdf], nameBase + '.pdf', { type: 'application/pdf' });
    } catch (e2) {
      return pdf;
    }
  }

  global.LLPreprocess = {
    MAX_EDGE: MAX_EDGE,
    JPEG_QUALITY: JPEG_QUALITY,
    compressImage: compressImage,
    captureVideoFrame: captureVideoFrame,
    composeUploadFile: composeUploadFile,
    jpegPagesToPdf: jpegPagesToPdf,
    readJpegSize: readJpegSize
  };
})(window);
