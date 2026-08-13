import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { AuthProvider } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { ToastProvider } from "@/context/ToastContext";
import { queryClient } from "@/lib/queryClient";
import { normalizeBareBasenameUrl } from "@/lib/routerBasename";
import "./index.css";

normalizeBareBasenameUrl();

function deferOpenReplay(): void {
  const run = () => {
    void import("@/third-party/sessionRecorder/OpenReplay/OpenReplay")
      .then((m) => m.startOpenReplay())
      .catch(() => {
        // startOpenReplay already logs; never let a rejection tear down bootstrap.
      });
  };
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(run, { timeout: 4000 });
  } else {
    window.setTimeout(run, 2000);
  }
}

deferOpenReplay();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>
);
