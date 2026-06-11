import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { api } from "@/api/client";
import { CaptureChannelsStrip } from "@/components/team-expenses/CaptureChannelsStrip";
import { Button } from "@/components/ui/button";
import type { ClaimChannel } from "@/lib/v4MockData";

type DocType = "po" | "grn" | "invoice";

export function PurchaseCaptureStrip({
  activeRuleCount = 0,
  onUploaded,
}: {
  activeRuleCount?: number;
  onUploaded?: () => void;
}) {
  const { data: mailboxes = [] } = useQuery({
    queryKey: ["mailboxes"],
    queryFn: () => api.listMailboxes(),
  });
  const [uploading, setUploading] = useState<DocType | null>(null);
  const poRef = useRef<HTMLInputElement>(null);
  const grnRef = useRef<HTMLInputElement>(null);
  const invRef = useRef<HTMLInputElement>(null);

  const channels = useMemo((): ClaimChannel[] => {
    const rows: ClaimChannel[] = mailboxes.map((mb) => ({
      id: `mb-${mb.id}`,
      name: "Email capture",
      detail: mb.display_name ? `${mb.email} (${mb.display_name})` : mb.email,
      connected: mb.is_active,
    }));

    if (rows.length === 0) {
      rows.push({
        id: "em-default",
        name: "Email capture",
        detail: "Connect a mailbox on Integrations",
        connected: false,
      });
    }

    rows.push({
      id: "upload-po",
      name: "Upload PO",
      detail: "Purchase order PDF first",
      connected: true,
    });
    rows.push({
      id: "upload-grn",
      name: "Upload GRN",
      detail: "Goods receipt after PO",
      connected: true,
    });
    rows.push({
      id: "upload-inv",
      name: "Upload invoice",
      detail: "Supplier invoice last",
      connected: true,
    });

    if (activeRuleCount > 0) {
      rows.push({
        id: "rules",
        name: "Purchase rules",
        detail: `${activeRuleCount} active PO rule${activeRuleCount === 1 ? "" : "s"}`,
        connected: true,
      });
    }

    return rows;
  }, [mailboxes, activeRuleCount]);

  const handleFile = async (file: File, docType: DocType) => {
    setUploading(docType);
    try {
      await api.uploadInvoice(file, docType);
      onUploaded?.();
    } finally {
      setUploading(null);
    }
  };

  return (
    <div className="space-y-3">
      <CaptureChannelsStrip channels={channels} testIdPrefix="purchase-channel" />
      <div className="flex flex-wrap gap-2">
        <input
          ref={poRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,.docx"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleFile(f, "po");
            e.target.value = "";
          }}
        />
        <input
          ref={grnRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,.docx"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleFile(f, "grn");
            e.target.value = "";
          }}
        />
        <input
          ref={invRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,.docx"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleFile(f, "invoice");
            e.target.value = "";
          }}
        />
        {(
          [
            { type: "po" as const, label: "Upload PO", ref: poRef },
            { type: "grn" as const, label: "Upload GRN", ref: grnRef },
            { type: "invoice" as const, label: "Upload invoice", ref: invRef },
          ] as const
        ).map((item) => (
          <Button
            key={item.type}
            type="button"
            size="sm"
            variant="outline"
            className="h-8 text-xs"
            disabled={uploading != null}
            onClick={() => item.ref.current?.click()}
            data-testid={`button-upload-${item.type}`}
          >
            <Upload className="h-3.5 w-3.5 mr-1" />
            {uploading === item.type ? "Uploading…" : item.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
