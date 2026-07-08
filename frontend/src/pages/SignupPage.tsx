import { useSearchParams } from "react-router-dom";
import { AcceptInvitePage } from "@/pages/AcceptInvitePage";
import { SetupPage } from "@/pages/SetupPage";

/**
 * Public signup entry: self-serve org setup when no token; invite accept when ?token= is present.
 */
export function SignupPage() {
  const [searchParams] = useSearchParams();
  const inviteToken = searchParams.get("token");

  if (inviteToken) {
    return <AcceptInvitePage />;
  }

  return <SetupPage />;
}
