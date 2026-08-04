/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BASE_PATH?: string;
  readonly VITE_API_BASE?: string;
  readonly VITE_OPEN_REPLAY_PROJECT_KEY?: string;
  readonly VITE_OPEN_REPLAY_INGEST_POINT?: string;
  readonly VITE_OPEN_REPLAY_DEFAULT_INPUT_MODE?: string;
  readonly VITE_OPEN_REPLAY_OBSCURE_TEXT_NUMBERS?: string;
  readonly VITE_OPEN_REPLAY_OBSCURE_TEXT_EMAILS?: string;
  readonly VITE_OPEN_REPLAY_INLINE_CSS?: string;
  readonly VITE_OPEN_REPLAY_DISABLE_SECURE_MODE?: string;
  readonly VITE_OPEN_REPLAY_ASSIST_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
