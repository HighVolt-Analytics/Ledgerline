import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import type { ViberConnection, WhatsappConnection } from "@/api/types";
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

function viberChannelRow(conn: ViberConnection | null): CaptureChannelItem {
  if (!conn || conn.connection_status !== "connected") {
    return {
      id: "vb",
      name: "Viber",
      detail: "Connect in Integrations",
      connected: false,
    };
  }
  const health =
    conn.integration_health === "connected"
      ? "healthy"
      : conn.integration_health.replace(/_/g, " ");
  return {
    id: "vb",
    name: "Viber",
    detail: conn.bot_id,
    connected: true,
    connectionId: conn.id,
    healthLabel: health,
  };
}

export function TeamExpenseChannelsStrip({ enabled = true }: { enabled?: boolean }) {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [channels, setChannels] = useState<CaptureChannelItem[]>([
    whatsappChannelRow(null),
    viberChannelRow(null),
  ]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [waStatus, vbStatus] = await Promise.all([
        api.getWhatsappStatus(),
        api.getViberStatus(),
      ]);
      const wa = waStatus.connections.find((c) => c.connection_status === "connected");
      const vb = vbStatus.connections.find((c) => c.connection_status === "connected");
      setChannels([
        whatsappChannelRow(wa ?? waStatus.connections[0] ?? null),
        viberChannelRow(vb ?? vbStatus.connections[0] ?? null),
      ]);
    } catch {
      setChannels([whatsappChannelRow(null), viberChannelRow(null)]);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void load();
  }, [load, enabled]);

  async function handleReconnect(channel: CaptureChannelItem) {
    if (channel.id === "wa") {
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
      return;
    }
    if (channel.id === "vb") {
      navigate("/integrations#viber-integration");
    }
  }

  async function handleTest(channel: CaptureChannelItem) {
    if (channel.connectionId == null) return;
    setBusyId(channel.id);
    try {
      if (channel.id === "wa") {
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
      } else if (channel.id === "vb") {
        const result = await api.testViberConnection(channel.connectionId);
        if (result.ok) {
          toast({ title: "Viber connection OK", description: "Webhook resubscribed." });
        } else {
          toast({
            title: "Viber needs attention",
            description: result.warnings.join(" · ") || result.integration_health,
            variant: "destructive",
          });
        }
      }
      await load();
    } catch (err) {
      toast({
        title: `${channel.name} test failed`,
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
