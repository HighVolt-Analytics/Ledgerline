import { CaptureChannelsStrip } from "@/components/team-expenses/CaptureChannelsStrip";
import { CLAIM_CHANNELS } from "@/lib/v4MockData";

export function TeamExpenseChannelsStrip() {
  return <CaptureChannelsStrip channels={CLAIM_CHANNELS} testIdPrefix="channel" />;
}
