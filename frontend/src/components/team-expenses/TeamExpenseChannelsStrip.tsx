import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import type { SlackConnection, ViberConnection, WhatsappConnection } from "@/api/types";
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

function slackChannelRow(conn: SlackConnection | null): CaptureChannelItem {
  if (!conn || conn.connection_status !== "connected") {
    return {
      id: "sl",
      name: "Slack",
      detail: "Connect in Integrations",
      connected: false,
    };
  }
  const health =
    conn.integration_health === "connected"
      ? "healthy"
      : conn.integration_health.replace(/_/g, " ");
  return {
    id: "sl",
    name: "Slack",
    detail: conn.team_name || conn.team_id,
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
    slackChannelRow(null),
    viberChannelRow(null),
  ]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [waStatus, slackStatus, vbStatus] = await Promise.all([
        api.getWhatsappStatus(),
        api.getSlackStatus(),
        api.getViberStatus(),
      ]);
      const wa = waStatus.connections.find((c) => c.connection_status === "connected");
      const sl = slackStatus.connections.find((c) => c.connection_status === "connected");
      const vb = vbStatus.connections.find((c) => c.connection_status === "connected");
      setChannels([
        whatsappChannelRow(wa ?? waStatus.connections[0] ?? null),
        slackChannelRow(sl ?? slackStatus.connections[0] ?? null),
        viberChannelRow(vb ?? vbStatus.connections[0] ?? null),
      ]);
    } catch {
      setChannels([whatsappChannelRow(null), slackChannelRow(null), viberChannelRow(null)]);
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
    if (channel.id === "sl") {
      setBusyId(channel.id);
      try {
        const { authorize_url } = await api.getSlackAuthorizeUrl();
        window.location.href = authorize_url;
      } catch (err) {
        toast({
          title: "Could not start Slack connection",
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
      } else if (channel.id === "sl") {
        const result = await api.testSlackConnection(channel.connectionId);
        if (result.ok) {
          toast({ title: "Slack connection OK", description: "auth.test succeeded." });
        } else {
          toast({
            title: "Slack needs attention",
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
