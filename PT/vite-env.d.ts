/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUTH_ENDPOINT: string;
  readonly VITE_SSE_ENDPOINT: string;
  readonly VITE_GRPC_ENDPOINT: string;
  readonly VITE_APP_TITLE: string;
  readonly VITE_MAX_ALERT_DISPLAY: string;
  readonly VITE_ALERT_AUTO_DISMISS_MS: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
