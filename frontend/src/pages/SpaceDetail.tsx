import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api";
import ActionsPanel, { ActionsView, mapActionError } from "../components/ActionsPanel";
import AnalysisOverview from "../components/AnalysisOverview";

type Section = "overview" | "actions" | "ask";

type AnalysisView =
  | { kind: "loading" }
  | { kind: "none" }
  | { kind: "starting" }
  | { kind: "processing" }
  | { kind: "ready"; analysis: api.DocumentAnalysis }
  | { kind: "failed"; message: string };

function mapAnalysisError(status: number, detail: string): string {
  if (status === 422) {
    const lower = detail.toLowerCase();
    if (lower.includes("context size"))
      return "This document is too large for structured analysis in the current version.";
    if (lower.includes("not ready"))
      return "Structured analysis is available once document processing is complete.";
    if (lower.includes("no chunks"))
      return "This document has no extractable text to analyze.";
    return detail;
  }
  if (status === 409) return "Analysis is already in progress.";
  if (status === 502)
    return "Document analysis could not be completed. Try again.";
  return detail || "Document analysis could not be completed.";
}

export default function SpaceDetail() {
  const { id } = useParams<{ id: string }>();
  const [space, setSpace] = useState<api.SpaceResponse | null>(null);
  const [documents, setDocuments] = useState<api.DocumentResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<api.AnswerResponse | null>(null);
  const [askError, setAskError] = useState("");

  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [section, setSection] = useState<Section>("overview");
  const [analysisView, setAnalysisView] = useState<AnalysisView>({ kind: "loading" });
  const [actionsView, setActionsView] = useState<ActionsView>({ kind: "loading" });
  const actionsDocRef = useRef<string | null>(null);
  const actionsTabRef = useRef<HTMLButtonElement>(null);
  const askTabRef = useRef<HTMLButtonElement>(null);
  const overviewTabRef = useRef<HTMLButtonElement>(null);

  const selectedDocument =
    documents.find((document) => document.id === selectedDocumentId) ?? null;

  useEffect(() => {
    if (!id) return;
    Promise.all([api.getSpace(id), api.listDocuments(id)])
      .then(([spaceResponse, documentResponse]) => {
        setSpace(spaceResponse);
        setDocuments(documentResponse);
        setSelectedDocumentId((current) => {
          if (current && documentResponse.some((document) => document.id === current)) {
            return current;
          }
          return documentResponse[0]?.id ?? null;
        });
      })
      .catch((err: unknown) => {
        if (err instanceof Error) setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (!id || !selectedDocumentId) return;
    const controller = new AbortController();
    setSection("overview");
    setAnalysisView({ kind: "loading" });
    api
      .getDocumentAnalysis(id, selectedDocumentId, controller.signal)
      .then((analysis) => {
        if (analysis.status === "processing") {
          setAnalysisView({ kind: "processing" });
        } else if (analysis.status === "failed") {
          setAnalysisView({
            kind: "failed",
            message: "Document analysis could not be completed. Try again.",
          });
        } else {
          setAnalysisView({ kind: "ready", analysis });
        }
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof api.ApiError && err.status === 404) {
          setAnalysisView({ kind: "none" });
        } else {
          setAnalysisView({
            kind: "failed",
            message:
              err instanceof Error
                ? err.message
                : "Document analysis could not be loaded.",
          });
        }
      });
    return () => controller.abort();
  }, [id, selectedDocumentId]);

  useEffect(() => {
    if (!id || !selectedDocumentId) return;
    const controller = new AbortController();
    actionsDocRef.current = selectedDocumentId;
    setActionsView({ kind: "loading" });
    api
      .getDocumentActions(id, selectedDocumentId, controller.signal)
      .then((data) => {
        if (data.status === "processing") {
          setActionsView({ kind: "processing" });
        } else if (data.status === "failed") {
          setActionsView({
            kind: "failed",
            message: "Action extraction could not be completed. Try again.",
          });
        } else {
          setActionsView({ kind: "ready", data });
        }
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof api.ApiError && err.status === 404) {
          setActionsView({ kind: "none" });
        } else {
          setActionsView({
            kind: "failed",
            message:
              err instanceof Error
                ? err.message
                : "Action extraction could not be loaded.",
          });
        }
      });
    return () => controller.abort();
  }, [id, selectedDocumentId]);

  const handleGenerateActions = useCallback(async () => {
    if (!id || !selectedDocumentId) return;
    setActionsView({ kind: "starting" });
    try {
      const data = await api.generateActions(id, selectedDocumentId);
      if (data.status === "processing") {
        setActionsView({ kind: "processing" });
      } else {
        setActionsView({ kind: "ready", data });
      }
    } catch (err: unknown) {
      if (err instanceof api.ApiError) {
        setActionsView({ kind: "failed", message: mapActionError(err.status, err.detail) });
      } else {
        setActionsView({
          kind: "failed",
          message: "Action extraction could not be completed. Try again.",
        });
      }
    }
  }, [id, selectedDocumentId]);

  const handleToggleAction = useCallback(
    async (actionId: string, status: "pending" | "completed") => {
      if (!id || !selectedDocumentId) return;
      const documentId = selectedDocumentId;
      const updated = await api.updateActionStatus(id, documentId, actionId, status);
      if (actionsDocRef.current !== documentId) return;
      setActionsView((current) => {
        if (current.kind !== "ready") return current;
        return {
          kind: "ready",
          data: {
            ...current.data,
            actions: current.data.actions.map((action) =>
              action.id === updated.id ? updated : action
            ),
          },
        };
      });
    },
    [id, selectedDocumentId]
  );

  const handleAnalyze = useCallback(async () => {
    if (!id || !selectedDocumentId) return;
    setAnalysisView({ kind: "starting" });
    try {
      const analysis = await api.analyzeDocument(id, selectedDocumentId);
      if (analysis.status === "processing") {
        setAnalysisView({ kind: "processing" });
      } else {
        setAnalysisView({ kind: "ready", analysis });
      }
    } catch (err: unknown) {
      if (err instanceof api.ApiError) {
        setAnalysisView({ kind: "failed", message: mapAnalysisError(err.status, err.detail) });
      } else {
        setAnalysisView({
          kind: "failed",
          message: "Document analysis could not be completed. Try again.",
        });
      }
    }
  }, [id, selectedDocumentId]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!id) return;
    const form = event.currentTarget;
    const input = form.elements.namedItem("document") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadError("");
    try {
      const uploaded = await api.uploadDocument(id, file);
      setDocuments((current) => [uploaded, ...current]);
      setSelectedDocumentId((current) => current ?? uploaded.id);
      form.reset();
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
      const refreshed = await api.listDocuments(id).catch(() => null);
      if (refreshed) setDocuments(refreshed);
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId: string, filename: string) {
    if (!id) return;
    if (!window.confirm(`Delete "${filename}"? This cannot be undone.`)) return;
    setUploadError("");
    try {
      await api.deleteDocument(id, documentId);
      setDocuments((current) => {
        const remaining = current.filter((document) => document.id !== documentId);
        if (selectedDocumentId === documentId) {
          setSelectedDocumentId(remaining[0]?.id ?? null);
        }
        return remaining;
      });
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!id || !question.trim()) return;
    setAsking(true);
    setAskError("");
    setAnswer(null);
    try {
      setAnswer(await api.askDocuments(id, question.trim()));
    } catch (err: unknown) {
      setAskError(err instanceof Error ? err.message : "Question failed");
    } finally {
      setAsking(false);
    }
  }

  const SECTION_ORDER: Section[] = ["overview", "actions", "ask"];

  function handleSectionKeyDown(event: React.KeyboardEvent) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const index = SECTION_ORDER.indexOf(section);
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const next = SECTION_ORDER[(index + direction + SECTION_ORDER.length) % SECTION_ORDER.length];
    setSection(next);
    const target =
      next === "overview"
        ? overviewTabRef.current
        : next === "actions"
          ? actionsTabRef.current
          : askTabRef.current;
    target?.focus();
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  if (error || !space) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="mb-4 text-red-600">{error || "Space not found"}</p>
          <Link to="/" className="text-indigo-600 hover:underline">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white shadow-sm">
        <div className="mx-auto flex max-w-6xl items-center px-4 py-3">
          <Link to="/" className="mr-4 text-indigo-600 hover:underline">
            &larr; Dashboard
          </Link>
          <h1 className="text-xl font-bold text-indigo-600">{space.name}</h1>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">
        {space.description && (
          <p className="mb-6 text-gray-600">{space.description}</p>
        )}
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
          <section aria-labelledby="documents-heading">
            <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
              <h2 id="documents-heading" className="text-lg font-semibold text-gray-900">
                Documents
              </h2>
              <p className="mt-1 text-sm text-gray-500">
                Upload text-based PDFs up to 10 MB. Scanned pages are not supported yet.
              </p>
              <form onSubmit={handleUpload} className="mt-4">
                <label className="block text-sm font-medium text-gray-700" htmlFor="document">
                  PDF file
                </label>
                <input
                  id="document"
                  name="document"
                  type="file"
                  accept="application/pdf,.pdf"
                  required
                  disabled={uploading}
                  className="mt-2 block w-full text-sm text-gray-600 file:mr-3 file:rounded-md file:border-0 file:bg-indigo-50 file:px-3 file:py-2 file:font-medium file:text-indigo-700 hover:file:bg-indigo-100"
                />
                <button
                  type="submit"
                  disabled={uploading}
                  className="mt-3 w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {uploading ? "Processing PDF..." : "Upload and process"}
                </button>
              </form>
              {uploadError && (
                <p role="alert" className="mt-3 text-sm text-red-600">
                  {uploadError}
                </p>
              )}
            </div>

            <div className="mt-4 space-y-3">
              {documents.length === 0 && (
                <div className="rounded-lg border-2 border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
                  No PDFs have been uploaded.
                </div>
              )}
              {documents.map((document) => {
                const isSelected = document.id === selectedDocumentId;
                return (
                  <article
                    key={document.id}
                    className={`rounded-lg border bg-white p-4 shadow-sm ${
                      isSelected ? "border-indigo-300 ring-2 ring-indigo-100" : ""
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <button
                        type="button"
                        onClick={() => setSelectedDocumentId(document.id)}
                        className="min-w-0 flex-1 rounded p-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                        aria-current={isSelected ? "true" : undefined}
                      >
                        <h3 className="truncate font-medium text-gray-900">
                          {document.original_filename}
                        </h3>
                        <p className="mt-1 text-xs text-gray-500">
                          {document.status === "ready"
                            ? `${document.page_count} ${document.page_count === 1 ? "page" : "pages"}`
                            : document.status}
                          {` · ${(document.file_size / 1024).toFixed(1)} KB`}
                        </p>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(document.id, document.original_filename)}
                        className="text-sm font-medium text-red-600 hover:text-red-700"
                        aria-label={`Delete ${document.original_filename}`}
                      >
                        Delete
                      </button>
                    </div>
                    {document.error_message && (
                      <p className="mt-2 text-sm text-red-600">{document.error_message}</p>
                    )}
                  </article>
                );
              })}
            </div>
          </section>

          <section aria-label="Selected document" className="min-w-0">
            {selectedDocument ? (
              <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
                <div
                  role="tablist"
                  aria-label="Document sections"
                  onKeyDown={handleSectionKeyDown}
                  className="mb-5 flex gap-1 rounded-lg bg-gray-100 p-1"
                >
                  <button
                    ref={overviewTabRef}
                    type="button"
                    role="tab"
                    id="section-tab-overview"
                    aria-controls="section-panel-overview"
                    aria-selected={section === "overview"}
                    onClick={() => setSection("overview")}
                    className={`flex-1 rounded-md px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                      section === "overview"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    Overview
                  </button>
                  <button
                    ref={actionsTabRef}
                    type="button"
                    role="tab"
                    id="section-tab-actions"
                    aria-controls="section-panel-actions"
                    aria-selected={section === "actions"}
                    onClick={() => setSection("actions")}
                    className={`flex-1 rounded-md px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                      section === "actions"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    Actions
                  </button>
                  <button
                    ref={askTabRef}
                    type="button"
                    role="tab"
                    id="section-tab-ask"
                    aria-controls="section-panel-ask"
                    aria-selected={section === "ask"}
                    onClick={() => setSection("ask")}
                    className={`flex-1 rounded-md px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                      section === "ask"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    Ask
                  </button>
                </div>

                {section === "overview" ? (
                  <div
                    role="tabpanel"
                    id="section-panel-overview"
                    aria-labelledby="section-tab-overview"
                  >
                    <AnalysisPanel
                      document={selectedDocument}
                      view={analysisView}
                      onAnalyze={handleAnalyze}
                    />
                  </div>
                ) : section === "actions" ? (
                  <div
                    role="tabpanel"
                    id="section-panel-actions"
                    aria-labelledby="section-tab-actions"
                  >
                    <ActionsPanel
                      document={selectedDocument}
                      view={actionsView}
                      onGenerate={handleGenerateActions}
                      onToggleStatus={handleToggleAction}
                    />
                  </div>
                ) : (
                  <div
                    role="tabpanel"
                    id="section-panel-ask"
                    aria-labelledby="section-tab-ask"
                  >
                    <h2 className="text-lg font-semibold text-gray-900">Ask this space</h2>
                    <p className="mt-1 text-sm text-gray-500">
                      Answers are limited to evidence found in ready documents.
                    </p>
                    <form onSubmit={handleAsk} className="mt-4">
                      <label htmlFor="question" className="sr-only">
                        Question
                      </label>
                      <textarea
                        id="question"
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        maxLength={1000}
                        rows={4}
                        required
                        placeholder="What do these documents say about...?"
                        className="w-full resize-y rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                      />
                      <button
                        type="submit"
                        disabled={asking || !question.trim()}
                        className="mt-3 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {asking ? "Finding evidence..." : "Ask question"}
                      </button>
                    </form>
                    {askError && (
                      <p role="alert" className="mt-4 text-sm text-red-600">
                        {askError}
                      </p>
                    )}
                    {answer && (
                      <div aria-live="polite" className="mt-6 border-t pt-5">
                        <p className="whitespace-pre-wrap leading-7 text-gray-800">
                          {answer.answer}
                        </p>
                        {answer.citations.length > 0 && (
                          <div className="mt-5">
                            <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                              Sources
                            </h3>
                            <ol className="mt-3 space-y-3">
                              {answer.citations.map((citation) => (
                                <li
                                  key={citation.source_id}
                                  className="rounded-md bg-gray-50 p-3"
                                >
                                  <p className="text-sm font-medium text-gray-800">
                                    {citation.document_name}, page {citation.page_number}
                                  </p>
                                  <p className="mt-1 line-clamp-3 text-sm text-gray-600">
                                    {citation.excerpt}
                                  </p>
                                </li>
                              ))}
                            </ol>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-lg border-2 border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">
                Select a document to view its overview or ask questions.
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

function AnalysisPanel({
  document,
  view,
  onAnalyze,
}: {
  document: api.DocumentResponse;
  view: AnalysisView;
  onAnalyze: () => void;
}) {
  if (view.kind === "loading") {
    return (
      <p role="status" className="py-8 text-center text-sm text-gray-500">
        Loading analysis...
      </p>
    );
  }

  if (view.kind === "processing") {
    return (
      <div className="py-8 text-center">
        <p role="status" className="text-sm text-gray-600">
          Analysis is currently in progress.
        </p>
        <p className="mt-1 text-xs text-gray-400">
          The structured overview will appear once it completes.
        </p>
      </div>
    );
  }

  if (view.kind === "starting") {
    return (
      <div className="py-8 text-center">
        <p role="status" className="text-sm text-gray-600">
          Analyzing document...
        </p>
      </div>
    );
  }

  if (view.kind === "failed") {
    return (
      <div className="py-8 text-center">
        <p role="alert" className="mx-auto max-w-md text-sm text-red-600">
          {view.message}
        </p>
        <button
          type="button"
          onClick={onAnalyze}
          className="mt-4 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          Try again
        </button>
      </div>
    );
  }

  if (view.kind === "ready") {
    return <AnalysisOverview analysis={view.analysis} document={document} />;
  }

  if (document.status !== "ready") {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-gray-500">
          {document.status === "processing"
            ? "Structured analysis is available once document processing is complete."
            : "This document could not be processed, so structured analysis is not available."}
        </p>
      </div>
    );
  }

  return (
    <div className="py-8 text-center">
      <h2 className="text-lg font-semibold text-gray-900">Structured overview</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-gray-600">
        Generate a structured overview with key facts, important dates and source
        references.
      </p>
      <button
        type="button"
        onClick={onAnalyze}
        className="mt-4 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
      >
        Analyze document
      </button>
    </div>
  );
}
