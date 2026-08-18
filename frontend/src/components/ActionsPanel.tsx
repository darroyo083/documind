import { useState } from "react";
import type { DocumentActions, DocumentResponse } from "../api";
import ActionChecklist from "./ActionChecklist";

export type ActionsView =
  | { kind: "loading" }
  | { kind: "none" }
  | { kind: "starting" }
  | { kind: "processing" }
  | { kind: "ready"; data: DocumentActions }
  | { kind: "failed"; message: string };

export function mapActionError(status: number, detail: string): string {
  if (status === 422) {
    const lower = detail.toLowerCase();
    if (lower.includes("context size"))
      return "This document is too large for action extraction in the current version.";
    if (lower.includes("not ready"))
      return "Actions become available once document processing is complete.";
    if (lower.includes("no chunks"))
      return "This document has no extractable text.";
    return detail;
  }
  if (status === 409) return "Action extraction is already in progress.";
  if (status === 502)
    return "Action extraction could not be completed. Try again.";
  return detail || "Action extraction could not be completed.";
}

export default function ActionsPanel({
  document,
  view,
  onGenerate,
  onToggleStatus,
}: {
  document: DocumentResponse;
  view: ActionsView;
  onGenerate: () => void;
  onToggleStatus: (
    actionId: string,
    status: "pending" | "completed"
  ) => Promise<void>;
}) {
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  async function handleToggle(actionId: string, status: "pending" | "completed") {
    setError("");
    setBusy((current) => new Set(current).add(actionId));
    try {
      await onToggleStatus(actionId, status);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? "Could not update the checklist item. Please try again."
          : "Could not update the checklist item."
      );
    } finally {
      setBusy((current) => {
        const next = new Set(current);
        next.delete(actionId);
        return next;
      });
    }
  }

  if (view.kind === "loading") {
    return (
      <p role="status" className="dm-feature-state">
        Loading actions...
      </p>
    );
  }

  if (view.kind === "processing") {
    return (
      <div className="dm-feature-state">
        <p role="status" className="text-sm text-gray-600">
          Action extraction is currently in progress.
        </p>
        <p className="mt-1 text-xs text-gray-400">
          The checklist will appear once it completes.
        </p>
        <button
          type="button"
          onClick={onGenerate}
          className="dm-button dm-button-primary mt-4"
        >
          Retry
        </button>
      </div>
    );
  }

  if (view.kind === "starting") {
    return (
      <div className="dm-feature-state">
        <p role="status" className="text-sm text-gray-600">
          Extracting actions...
        </p>
      </div>
    );
  }

  if (view.kind === "failed") {
    return (
      <div className="dm-feature-state">
        <p role="alert" className="mx-auto max-w-md text-sm text-red-600">
          {view.message}
        </p>
        <button
          type="button"
          onClick={onGenerate}
          className="dm-button dm-button-primary mt-4"
        >
          Retry
        </button>
      </div>
    );
  }

  if (view.kind === "ready") {
    return (
      <div className="dm-feature-panel">
        <h2 className="text-lg font-semibold text-gray-900">Checklist</h2>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <ActionChecklist
          actions={view.data.actions}
          busy={busy}
          onToggle={handleToggle}
        />
      </div>
    );
  }

  if (document.status !== "ready") {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-gray-500">
          {document.status === "processing"
            ? "Actions become available once document processing is complete."
            : "This document could not be processed, so actions are not available."}
        </p>
      </div>
    );
  }

  return (
    <div className="dm-feature-state">
      <h2 className="text-lg font-semibold text-gray-900">Checklist</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-gray-600">
        Find deadlines, required actions and important reminders supported by this
        document.
      </p>
      <button
        type="button"
        onClick={onGenerate}
      className="dm-button dm-button-primary mt-4"
      >
        Extract actions
      </button>
    </div>
  );
}
