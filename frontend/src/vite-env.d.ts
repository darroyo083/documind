/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PUBLIC_DEMO_MODE?: string;
  readonly VITE_DEMO_VIDEO_SRC?: string;
  readonly VITE_DEMO_VIDEO_POSTER?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
