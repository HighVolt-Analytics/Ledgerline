import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type { WhatsappConnection } from "@/api/types";
import {
  CaptureChannelsStrip,
  type CaptureChannelItem,
} from "@/components/team-expenses/CaptureChannelsStrip";
import { useToast } from "@/context/ToastContext";

function whatsappChannelRow(conn: WhatsappConnection | null): CaptureChannelItem {
  if (!conn || conn.connection_status !== "connected") {
    return {
      id: "wa",
      name: "WhatsApp Business",
      detail: "Connect in Integrations",
      connected: false,
    };
  }
  const health =
    conn.integration_health === "connected"
      ? "healthy"
      : conn.integration_health.replace(/_/g, " ");
  return {
    id: "wa",
    name: "WhatsApp Business",
    detail: conn.phone_number || conn.display_name || conn.phone_number_id,
    connected: true,
    connectionId: conn.id,
    healthLabel: health,
  };
}

export function TeamExpenseChannelsStrip() {
  const { toast } = useToast();
  const [channels, setChannels] = useState<CaptureChannelItem[]>([
    whatsappChannelRow(null),
  ]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const status = await api.getWhatsappStatus();
      const wa = status.connections.find((c) => c.connection_status === "connected");
      setChannels([whatsappChannelRow(wa ?? status.connections[0] ?? null)]);
    } catch {
      setChannels([whatsappChannelRow(null)]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleReconnect(channel: CaptureChannelItem) {
    if (channel.id !== "wa") return;
    setBusyId(channel.id);
    try {
      const { authorize_url } = await api.getWhatsappAuthorizeUrl();
      window.location.href = authorize_url;
    } catch (err) {
      toast({
        title: "Could not start WhatsApp connection",
        description: err instanceof Error ? err.message : "Try again",
        variant: "destructive",
      });
      setBusyId(null);
    }
  }

  async function handleTest(channel: CaptureChannelItem) {
    if (channel.id !== "wa" || channel.connectionId == null) return;
    setBusyId(channel.id);
    try {
      const result = await api.testWhatsappConnection(channel.connectionId);
      if (result.ok) {
        toast({ title: "WhatsApp connection OK", description: "Webhook resubscribed." });
      } else {
        toast({
          title: "WhatsApp needs attention",
          description: result.warnings.join(" · ") || result.integration_health,
          variant: "destructive",
        });
      }
      await load();
    } catch (err) {
      toast({
        title: "WhatsApp test failed",
        description: err instanceof Error ? err.message : "Try again",
        variant: "destructive",
      });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <CaptureChannelsStrip
      channels={channels}
      testIdPrefix="channel"
      onReconnect={handleReconnect}
      onTest={handleTest}
      actionBusyId={busyId}
    />
  );
}
