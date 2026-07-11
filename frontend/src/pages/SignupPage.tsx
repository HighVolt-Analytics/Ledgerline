import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AcceptInvitePage } from "@/pages/AcceptInvitePage";
import { SetupPage } from "@/pages/SetupPage";

/**
 * Public signup entry:
 * - ?signup_token= JWT from OAuth/email wizard → self-serve org setup
 * - ?token= opaque invite token → tenant invite accept
 */
export function SignupPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const signupToken = searchParams.get("signup_token");
  const inviteToken = searchParams.get("token");
  const checkout = searchParams.get("checkout");
  const sessionId = searchParams.get("session_id");

  useEffect(() => {
    if (!checkout || !sessionId || signupToken || inviteToken) return;
    navigate(
      `/billing?checkout=${encodeURIComponent(checkout)}&session_id=${encodeURIComponent(sessionId)}`,
      { replace: true },
    );
  }, [checkout, sessionId, signupToken, inviteToken, navigate]);

  if (inviteToken && !signupToken) {
    return <AcceptInvitePage />;
  }

  return <SetupPage />;
}
