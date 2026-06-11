import { useState } from "react";
import { CheckCircle2, Mail, MessageCircle, Smartphone, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { ClaimChannel } from "@/lib/v4MockData";

function channelIcon(id: string) {
  if (id === "em" || id.startsWith("mb-") || id === "em-default") return Mail;
  if (id === "mob") return Smartphone;
  if (id === "upload") return Upload;
  return MessageCircle;
}

export function CaptureChannelsStrip({
  channels,
  testIdPrefix = "channel",
}: {
  channels: ClaimChannel[];
  testIdPrefix?: string;
}) {
  const [openChannel, setOpenChannel] = useState<string | null>(null);

  return (
    <div className="flex flex-wrap gap-2 mb-5">
      {channels.map((ch) => {
        const Icon = channelIcon(ch.id);
        return (
          <div key={ch.id} className="relative">
            <button
              type="button"
              onClick={() => setOpenChannel(openChannel === ch.id ? null : ch.id)}
              data-testid={`${testIdPrefix}-${ch.id}`}
              className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-xs hover-elevate"
            >
              <Icon className="h-3.5 w-3.5 text-primary" />
              <span className="font-medium">{ch.name}</span>
              <span className="text-muted-foreground hidden md:inline">· {ch.detail}</span>
              {ch.connected && (
                <span className="relative flex h-2 w-2" aria-label="Connected">
                  <span className="absolute inline-flex h-full w-full rounded-full bg-[hsl(145_63%_42%)] opacity-60 animate-ping" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-[hsl(145_63%_42%)]" />
                </span>
              )}
            </button>
            {openChannel === ch.id && (
              <Card className="absolute z-20 mt-1 p-3 w-56 text-xs space-y-2 shadow-md">
                <div className="font-medium">{ch.name}</div>
                <div className="text-muted-foreground">{ch.detail}</div>
                {ch.connected ? (
                  <div className="flex items-center gap-1 text-[hsl(145_55%_38%)] dark:text-[hsl(145_55%_60%)]">
                    <CheckCircle2 className="h-4 w-4 -ml-1" />
                    Connected · healthy
                  </div>
                ) : (
                  <div className="text-muted-foreground">Not connected</div>
                )}
                <div className="flex gap-2 pt-1">
                  <Button size="sm" variant="outline" className="h-7 text-xs flex-1">
                    Reconnect
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 text-xs flex-1">
                    Test
                  </Button>
                </div>
              </Card>
            )}
          </div>
        );
      })}
    </div>
  );
}
