import { api, ApiError } from "@/api/client";

/** Serial uploads avoid overloading the API/pipeline; backend still accepts parallel clients. */
export const BULK_UPLOAD_CONCURRENCY = 1;
export const BULK_UPLOAD_MAX_FILES = 50;

export const UPLOAD_ACCEPT = ".pdf,.jpg,.jpeg,.png,.docx";
export const UPLOAD_ACCEPT_LABEL = "PDF, JPG, PNG, DOCX";

const UPLOAD_EXTENSIONS = new Set([".pdf", ".jpg", ".jpeg", ".png", ".docx"]);
const UPLOAD_RETRY_STATUSES = new Set([500, 502, 503, 504]);

export type BulkUploadItemResult =
  | { ok: true; fileName: string; invoiceId: number }
  | { ok: false; fileName: string; reason: "duplicate" | "failed"; message: string };

export type BulkUploadSummary = {
  uploaded: number;
  duplicate: number;
  failed: number;
  results: BulkUploadItemResult[];
};

export function formatBulkUploadNotice(summary: BulkUploadSummary): string {
  const parts: string[] = [];
  if (summary.uploaded > 0) {
    parts.push(
      `${summary.uploaded} document${summary.uploaded === 1 ? "" : "s"} uploaded — processing in background`
    );
  }
  if (summary.duplicate > 0) {
    parts.push(`${summary.duplicate} duplicate${summary.duplicate === 1 ? "" : "s"} skipped`);
  }
  if (summary.failed > 0) {
    parts.push(`${summary.failed} failed`);
  }
  if (parts.length === 0) {
    return "No files were uploaded.";
  }

  let notice = `${parts.join("; ")}.`;
  const failedNames = summary.results
    .filter((row): row is Extract<BulkUploadItemResult, { ok: false }> => !row.ok && row.reason === "failed")
    .map((row) => row.fileName);
  if (failedNames.length > 0 && failedNames.length <= 3) {
    notice += ` Failed: ${failedNames.join(", ")}.`;
  } else if (failedNames.length > 3) {
    notice += ` Failed: ${failedNames.slice(0, 3).join(", ")} (+${failedNames.length - 3} more).`;
  }
  return notice;
}

function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot < 0) return "";
  return name.slice(dot).toLowerCase();
}

/** Keep supported capture types; skip folders and unknown extensions. */
export function filterUploadFiles(files: Iterable<File>): { accepted: File[]; skipped: number } {
  const accepted: File[] = [];
  let skipped = 0;
  for (const file of files) {
    const ext = fileExtension(file.name);
    if (!ext || !UPLOAD_EXTENSIONS.has(ext)) {
      skipped += 1;
      continue;
    }
    accepted.push(file);
  }
  return { accepted, skipped };
}

async function uploadOneFile(file: File): Promise<BulkUploadItemResult> {
  let lastError: unknown;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const inv = await api.uploadInvoice(file, undefined, { deferProcessing: true });
      return { ok: true, fileName: file.name, invoiceId: inv.id };
    } catch (err) {
      lastError = err;
      if (err instanceof ApiError) {
        if (err.status === 409) {
          return {
            ok: false,
            fileName: file.name,
            reason: "duplicate",
            message: err.message || "Duplicate file already uploaded",
          };
        }
        if (attempt === 0 && UPLOAD_RETRY_STATUSES.has(err.status)) {
          await new Promise((r) => setTimeout(r, 400));
          continue;
        }
      }
      break;
    }
  }
  return {
    ok: false,
    fileName: file.name,
    reason: "failed",
    message: lastError instanceof Error ? lastError.message : "Upload failed",
  };
}

export async function uploadFilesInBatch(
  files: File[],
  options?: {
    concurrency?: number;
    onProgress?: (completed: number, total: number) => void;
  }
): Promise<BulkUploadSummary> {
  const concurrency = options?.concurrency ?? BULK_UPLOAD_CONCURRENCY;
  const total = files.length;
  const results: BulkUploadItemResult[] = [];
  let completed = 0;
  let index = 0;

  async function worker() {
    while (index < files.length) {
      const current = index;
      index += 1;
      const file = files[current]!;
      const result = await uploadOneFile(file);
      results.push(result);
      completed += 1;
      options?.onProgress?.(completed, total);
    }
  }

  const workerCount = Math.min(concurrency, Math.max(files.length, 1));
  await Promise.all(Array.from({ length: workerCount }, () => worker()));

  const uploadedIds = results
    .filter((row): row is Extract<BulkUploadItemResult, { ok: true }> => row.ok)
    .map((row) => row.invoiceId);
  if (uploadedIds.length > 0) {
    await api.processInvoicesBatch(uploadedIds);
  }

  return {
    uploaded: results.filter((r) => r.ok).length,
    duplicate: results.filter((r) => !r.ok && r.reason === "duplicate").length,
    failed: results.filter((r) => !r.ok && r.reason === "failed").length,
    results,
  };
}
