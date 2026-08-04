import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { AuthProvider } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { ToastProvider } from "@/context/ToastContext";
import { queryClient } from "@/lib/queryClient";
import { normalizeBareBasenameUrl } from "@/lib/routerBasename";
import { startOpenReplay } from "@/third-party/sessionRecorder/OpenReplay/OpenReplay";
import "./index.css";

normalizeBareBasenameUrl();
void startOpenReplay().catch(() => {
  // startOpenReplay already logs; never let a rejection tear down bootstrap.
});

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
