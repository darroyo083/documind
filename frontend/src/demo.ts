export const PUBLIC_DEMO_MODE = import.meta.env.VITE_PUBLIC_DEMO_MODE === "true";
export const DEMO_SPACE_ID = "demo";
export const DEMO_ASK_QUESTIONS = [
  "What is the monthly membership fee?",
  "What changed in the renewal notice?",
  "Are there any contradictions?",
  "¿De qué va esto?",
] as const;

export const DEMO_READ_ONLY_MESSAGE =
  "This public demo is read-only. Live AI generation and workspace mutations are disabled.";

export function isDemoSpaceId(spaceId: string): boolean {
  return PUBLIC_DEMO_MODE && spaceId === DEMO_SPACE_ID;
}
