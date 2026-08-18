import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api";
import ComparisonResult from "./ComparisonResult";
import { EmptyState, LoadingState, StatusBadge } from "./ui";

export type CompareView =
  | { kind: "idle" }
  | { kind: "generating" }
  | { kind: "processing" }
  | { kind: "ready"; comparison: api.DocumentComparison }
  | { kind: "failed"; message: string };

export function mapComparisonError(status: number, detail: string): string {
  if (status === 422) {
    const lower = detail.toLowerCase();
    if (lower.includes("context size"))
      return "The selected documents are too large to compare in the current version.";
    if (lower.includes("not ready"))
      return "All selected documents must be ready before comparing.";
    if (lower.includes("no chunks"))
      return "A selected document has no extractable text to compare.";
    if (lower.includes("focus"))
      return "The comparison focus is too long.";
    return detail;
  }
  if (status === 409)
    return "A comparison for these documents is already in progress.";
  if (status === 502)
    return "The comparison could not be completed. Try again.";
  return detail || "The comparison could not be completed.";
}

export default function ComparePanel({
  spaceId,
  documents,
}: {
  spaceId: string;
  documents: api.DocumentResponse[];
}) {
  const [history, setHistory] = useState<api.ComparisonSummary[] | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState("");
  const [view, setView] = useState<CompareView>({ kind: "idle" });
  const [formError, setFormError] = useState("");
  const busyRef = useRef(false);
  const detailControllerRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      detailControllerRef.current?.abort();
    },
    []
  );

  useEffect(() => {
    const controller = new AbortController();
    setHistory(null);
    setHistoryError("");
    api
      .listComparisons(spaceId, controller.signal)
      .then((items) => setHistory(items))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setHistoryError(
          err instanceof Error ? err.message : "Comparisons could not be loaded."
        );
      });
    return () => controller.abort();
  }, [spaceId]);

  const readyDocuments = documents.filter(
    (document) => document.status === "ready"
  );
  const selectedCount = selectedIds.size;

  const toggleDocument = useCallback((documentId: string) => {
    setFormError("");
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(documentId)) {
        next.delete(documentId);
      } else if (next.size < 4) {
        next.add(documentId);
      }
      return next;
    });
  }, []);

  const refreshHistory = useCallback(async () => {
    const items = await api.listComparisons(spaceId).catch(() => null);
    if (items) setHistory(items);
  }, [spaceId]);

  const handleGenerate = useCallback(async () => {
    if (busyRef.current) return;
    const ids = [...selectedIds];
    if (ids.length < 2) {
      setFormError("Select 2 to 4 documents to compare.");
      return;
    }
    busyRef.current = true;
    setFormError("");
    setView({ kind: "generating" });
    try {
      const comparison = await api.createComparison(spaceId, {
        document_ids: ids,
        focus: focus.trim() || null,
      });
      if (comparison.status === "processing") {
        setView({ kind: "processing" });
      } else {
        setView({ kind: "ready", comparison });
      }
      await refreshHistory();
    } catch (err: unknown) {
      if (err instanceof api.ApiError) {
        setView({ kind: "failed", message: mapComparisonError(err.status, err.detail) });
      } else {
        setView({
          kind: "failed",
          message: "The comparison could not be completed. Try again.",
        });
      }
    } finally {
      busyRef.current = false;
    }
  }, [spaceId, selectedIds, focus, refreshHistory]);

  const handleRetry = useCallback(() => {
    setView({ kind: "idle" });
    void handleGenerate();
  }, [handleGenerate]);

  const handleOpenHistory = useCallback(
    async (summary: api.ComparisonSummary) => {
      detailControllerRef.current?.abort();
      const controller = new AbortController();
      detailControllerRef.current = controller;
      setView({ kind: "generating" });
      try {
        const comparison = await api.getComparison(
          spaceId,
          summary.id,
          controller.signal
        );
        setView({ kind: "ready", comparison });
      } catch (err: unknown) {
        if (controller.signal.aborted) return;
        if (err instanceof api.ApiError && err.status === 404) {
          setView({
            kind: "failed",
            message: "This comparison is no longer available.",
          });
          void refreshHistory();
          return;
        }
        setView({
          kind: "failed",
          message:
            err instanceof Error ? err.message : "The comparison could not be loaded.",
        });
      }
    },
    [spaceId, refreshHistory]
  );

  const memberNames = (summary: api.ComparisonSummary) =>
    summary.documents.map((member) => member.original_filename).join(", ");

  return (
    <div className="dm-compare-panel space-y-6">
      <section aria-labelledby="compare-heading">
        <h2 id="compare-heading" className="text-lg font-semibold text-gray-900">
          Compare documents
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          Select 2 to 4 ready documents from this space to compare them side by
          side with source evidence.
        </p>

        <fieldset className="mt-4">
          <legend className="sr-only">Documents to compare</legend>
          <div className="space-y-2">
            {readyDocuments.map((document) => {
              const checked = selectedIds.has(document.id);
              const blocked = !checked && selectedCount >= 4;
              return (
                <label
                  key={document.id}
                  className={`dm-compare-select-row ${
                    checked ? "dm-compare-select-row-active" : ""
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={blocked}
                    onChange={() => toggleDocument(document.id)}
                    className="dm-compare-checkbox"
                  />
                  <span className="min-w-0">
                    <span
                      className="block truncate text-sm font-medium text-gray-900"
                      title={document.original_filename}
                    >
                      {document.original_filename}
                    </span>
                    <span className="block text-xs text-gray-500">
                      {document.page_count}{" "}
                      {document.page_count === 1 ? "page" : "pages"}
                      {blocked && !checked
                        ? " · comparison limit of 4 reached"
                        : ""}
                    </span>
                  </span>
                </label>
              );
            })}
            {readyDocuments.length === 0 && (
              <EmptyState
                title="No ready documents"
                description="Upload and process at least two documents before comparing them."
              />
            )}
          </div>
          {readyDocuments.length > 0 && (
            <p className="mt-2 text-xs text-gray-500" aria-live="polite">
              {selectedCount} of 4 selected. Choose between 2 and 4 documents.
            </p>
          )}
        </fieldset>

        <div className="mt-4">
          <label
            htmlFor="comparison-focus"
            className="block text-sm font-medium text-gray-700"
          >
            Comparison focus (optional)
          </label>
          <input
            id="comparison-focus"
            type="text"
            value={focus}
            onChange={(event) => setFocus(event.target.value)}
            maxLength={500}
            placeholder="e.g. renewal, termination, and fees"
          className="dm-input mt-1"
          />
          <p className="mt-1 text-xs text-gray-500">
            Optional. Directs the comparison toward the topics you care about.
          </p>
        </div>

        {formError && (
          <p role="alert" className="mt-3 text-sm text-red-600">
            {formError}
          </p>
        )}

        <button
          type="button"
          onClick={handleGenerate}
          disabled={
            selectedCount < 2 || busyRef.current || view.kind === "generating"
          }
          className="dm-button dm-button-primary mt-4 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Compare selected
        </button>
      </section>

      {view.kind === "generating" && (
        <LoadingState message="Comparing documents..." />
      )}

      {view.kind === "processing" && (
        <div className="dm-feature-state">
          <p role="status" className="text-sm text-gray-600">
            A comparison for these documents is currently in progress.
          </p>
          <button
            type="button"
            onClick={handleRetry}
            className="dm-button dm-button-primary mt-4"
          >
            Try again
          </button>
        </div>
      )}

      {view.kind === "failed" && (
        <div className="dm-feature-state">
          <p role="alert" className="mx-auto max-w-md text-sm text-red-600">
            {view.message}
          </p>
          <button
            type="button"
            onClick={handleRetry}
            className="dm-button dm-button-primary mt-4"
          >
            Try again
          </button>
        </div>
      )}

      {view.kind === "ready" && <ComparisonResult comparison={view.comparison} />}

      <section aria-labelledby="history-heading">
        <h3 id="history-heading" className="text-lg font-semibold text-gray-900">
          Recent comparisons
        </h3>
        {historyError && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {historyError}
          </p>
        )}
        {history === null ? (
          <LoadingState message="Loading comparison history..." />
        ) : history.length === 0 ? (
          <EmptyState
            className="mt-4"
            title="No comparisons yet"
            description="Select two to four ready documents above to create a comparison."
          />
        ) : (
          <ul className="mt-4 space-y-3">
            {history.map((summary) => (
              <li key={summary.id}>
                  <button
                    type="button"
                    onClick={() => handleOpenHistory(summary)}
                    className="dm-comparison-history-row"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="truncate text-sm font-semibold text-gray-900">
                      {summary.title || "Comparison"}
                    </h4>
                    <StatusBadge status={summary.status} />
                  </div>
                  <p
                    className="mt-1 truncate text-xs text-gray-500"
                    title={memberNames(summary)}
                  >
                    {memberNames(summary)}
                  </p>
                  {summary.focus && (
                    <p className="mt-1 truncate text-xs text-gray-400">
                      Focus: {summary.focus}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-gray-400">
                    {new Date(summary.created_at).toLocaleString()}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
