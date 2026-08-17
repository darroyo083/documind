import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import * as api from "../api";
import ActionsPanel, { ActionsView, mapActionError } from "../components/ActionsPanel";
import AnalysisOverview from "../components/AnalysisOverview";
import ComparePanel from "../components/ComparePanel";
import DocumentUpload from "../components/DocumentUpload";
import IntelligencePanel from "../components/IntelligencePanel";
import {
  AppHeader,
  Button,
  EmptyState,
  LoadingState,
  SourceDisclosure,
  StatusBadge,
} from "../components/ui";

const SCOPE_LABELS: Record<api.KnowledgeScope, string> = {
  private: "My documents",
  reference: "Reference",
  combined: "Both",
};

type Section = "overview" | "actions" | "compare" | "intelligence" | "ask";

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
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [space, setSpace] = useState<api.SpaceResponse | null>(null);
  const [documents, setDocuments] = useState<api.DocumentResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [uploadingCount, setUploadingCount] = useState(0);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<api.AnswerResponse | null>(null);
  const [askError, setAskError] = useState("");
  const [scope, setScope] = useState<api.KnowledgeScope>("private");
  const [answerScope, setAnswerScope] = useState<api.KnowledgeScope | null>(null);
  const [referenceDocuments, setReferenceDocuments] = useState<
    api.ReferenceDocumentResponse[]
  >([]);

  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [section, setSection] = useState<Section>("overview");
  const [analysisView, setAnalysisView] = useState<AnalysisView>({ kind: "loading" });
  const [actionsView, setActionsView] = useState<ActionsView>({ kind: "loading" });
  const actionsDocRef = useRef<string | null>(null);
  const actionsTabRef = useRef<HTMLButtonElement>(null);
  const compareTabRef = useRef<HTMLButtonElement>(null);
  const intelligenceTabRef = useRef<HTMLButtonElement>(null);
  const askTabRef = useRef<HTMLButtonElement>(null);
  const overviewTabRef = useRef<HTMLButtonElement>(null);

  const selectedDocument =
    documents.find((document) => document.id === selectedDocumentId) ?? null;

  useEffect(() => {
    if (!id) return;
    Promise.all([api.getSpace(id), api.listDocuments(id), api.getReferenceLibrary()])
      .then(([spaceResponse, documentResponse, referenceResponse]) => {
        setSpace(spaceResponse);
        setDocuments(documentResponse);
        setReferenceDocuments(referenceResponse);
        setSelectedDocumentId((current) => {
          if (current && documentResponse.some((document) => document.id === current)) {
            return current;
          }
          const requestedDocument = searchParams.get("document");
          if (
            requestedDocument &&
            documentResponse.some((document) => document.id === requestedDocument)
          ) {
            return requestedDocument;
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
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        navigate("/search");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate]);

  useEffect(() => {
    if (!id) return;
    const refetch = () => {
      api
        .listDocuments(id)
        .then(setDocuments)
        .catch(() => undefined);
    };
    window.addEventListener("focus", refetch);
    return () => window.removeEventListener("focus", refetch);
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

  const handleDocumentAdded = useCallback(
    (document: api.DocumentResponse) => {
      setDocuments((current) => {
        const withoutDuplicate = current.filter((item) => item.id !== document.id);
        return [document, ...withoutDuplicate];
      });
      setSelectedDocumentId((current) => current ?? document.id);
    },
    []
  );

  const handleUploadingChange = useCallback((count: number) => {
    setUploadingCount(count);
  }, []);

  const handleRetryDocument = useCallback(
    async (documentId: string) => {
      if (!id) return;
      setUploadError("");
      try {
        const updated = await api.retryDocument(id, documentId);
        setDocuments((current) =>
          current.map((document) => (document.id === updated.id ? updated : document))
        );
      } catch (err: unknown) {
        setUploadError(
          err instanceof api.ApiError && err.status === 409
            ? "This document is already being processed."
            : err instanceof Error
              ? err.message
              : "Retry failed."
        );
      }
    },
    [id]
  );

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
      const result = await api.askDocuments(id, question.trim(), scope);
      setAnswer(result);
      setAnswerScope(scope);
    } catch (err: unknown) {
      setAskError(err instanceof Error ? err.message : "Question failed");
    } finally {
      setAsking(false);
    }
  }

  const SECTION_ORDER: Section[] = ["overview", "actions", "compare", "intelligence", "ask"];

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
          : next === "compare"
            ? compareTabRef.current
            : next === "intelligence"
              ? intelligenceTabRef.current
              : askTabRef.current;
    target?.focus();
  }

  if (loading) {
    return <LoadingState message="Loading Space..." />;
  }

  if (error || !space) {
    return (
      <main className="dm-page grid min-h-screen place-items-center px-4">
        <EmptyState
          title="This Space is unavailable"
          description={error || "We could not find the Space you requested."}
          action={
            <Link to="/" className="dm-button dm-button-secondary">
              Back to Dashboard
            </Link>
          }
        />
      </main>
    );
  }

  const readyCount = documents.filter((document) => document.status === "ready").length;
  const processingCount =
    documents.filter((document) => document.status === "processing").length + uploadingCount;
  const failedCount = documents.filter((document) => document.status === "failed").length;
  const aggregateStatusText =
    `${documents.length} document${documents.length === 1 ? "" : "s"} · ` +
    `${readyCount} ready · ${processingCount} processing · ${failedCount} failed`;

  return (
    <div className="dm-page">
      <AppHeader title={space.name} backTo="/" right={<Link to="/search">Search</Link>} />

      <main className="dm-container dm-page-main">
        {space.description && (
          <p className="mb-7 max-w-prose text-gray-600">{space.description}</p>
        )}
        <div className="space-layout grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
          <section aria-labelledby="documents-heading">
            <div className="dm-surface p-5">
              <h2 id="documents-heading" className="text-lg font-semibold text-gray-900">
                Documents
              </h2>
              <p className="mt-1 text-sm text-gray-500">
                Upload text-based PDFs up to 10 MB. Scanned pages are not supported yet.
              </p>
              <div className="mt-4">
                <DocumentUpload
                  spaceId={id as string}
                  onDocumentAdded={handleDocumentAdded}
                  onUploadingChange={handleUploadingChange}
                />
              </div>
              {uploadError && (
                <p role="alert" className="mt-3 text-sm text-red-600">
                  {uploadError}
                </p>
              )}
              {documents.length > 0 && (
                <div className="mt-4 flex flex-wrap items-center gap-2" aria-live="polite">
                  <span className="text-xs text-gray-500">{documents.length} total</span>
                  <StatusBadge status="ready" />
                  <span className="text-xs text-gray-500">{readyCount}</span>
                  {processingCount > 0 && (
                    <>
                      <StatusBadge status="processing" />
                      <span className="text-xs text-gray-500">{processingCount}</span>
                    </>
                  )}
                  {failedCount > 0 && (
                    <>
                      <StatusBadge status="failed" />
                      <span className="text-xs text-gray-500">{failedCount}</span>
                    </>
                  )}
                  <span className="sr-only">{aggregateStatusText}</span>
                </div>
              )}
            </div>

            <div className="mt-4 space-y-3">
              {documents.length === 0 && (
                <EmptyState
                  title="No documents yet"
                  description="Upload a text-based PDF to start analyzing this Space."
                />
              )}
              {documents.map((document) => {
                const isSelected = document.id === selectedDocumentId;
                return (
                  <article
                    key={document.id}
                    className={`dm-document-row ${
                      isSelected ? "dm-document-row-selected" : ""
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
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <StatusBadge status={document.status} />
                          <span className="text-xs text-gray-500">
                            {document.status === "ready"
                              ? `${document.page_count} ${document.page_count === 1 ? "page" : "pages"}`
                              : `${(document.file_size / 1024).toFixed(1)} KB`}
                          </span>
                        </div>
                      </button>
                      {document.status === "failed" && (
                        <button
                          type="button"
                          onClick={() => handleRetryDocument(document.id)}
                          className="text-sm font-medium text-indigo-600 hover:text-indigo-700"
                        >
                          Retry
                        </button>
                      )}
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
                      <p className="mt-2 text-sm text-red-600">
                        {document.failure_code === "no_extractable_text"
                          ? "No extractable text. Scanned PDFs are not supported."
                          : document.error_message}
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
          </section>

          <section aria-label="Selected document" className="min-w-0">
            {selectedDocument ? (
              <div className="dm-surface p-5">
                <div
                  role="tablist"
                  aria-label="Document sections"
                  onKeyDown={handleSectionKeyDown}
                  className="dm-tabs mb-5 flex gap-1 rounded-lg bg-gray-100 p-1"
                >
                  <button
                    ref={overviewTabRef}
                    type="button"
                    role="tab"
                    id="section-tab-overview"
                    aria-controls="section-panel-overview"
                    aria-selected={section === "overview"}
                    onClick={() => setSection("overview")}
                    className={`dm-tab flex-1 rounded-md px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
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
                    className={`dm-tab flex-1 rounded-md px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                      section === "actions"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    Actions
                  </button>
                  <button
                    ref={compareTabRef}
                    type="button"
                    role="tab"
                    id="section-tab-compare"
                    aria-controls="section-panel-compare"
                    aria-selected={section === "compare"}
                    onClick={() => setSection("compare")}
                    className={`dm-tab flex-1 rounded-md px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                      section === "compare"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    Compare
                  </button>
                  <button
                    ref={intelligenceTabRef}
                    type="button"
                    role="tab"
                    id="section-tab-intelligence"
                    aria-controls="section-panel-intelligence"
                    aria-selected={section === "intelligence"}
                    onClick={() => setSection("intelligence")}
                    className={`dm-tab flex-1 rounded-md px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                      section === "intelligence"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    Intelligence
                  </button>
                  <button
                    ref={askTabRef}
                    type="button"
                    role="tab"
                    id="section-tab-ask"
                    aria-controls="section-panel-ask"
                    aria-selected={section === "ask"}
                    onClick={() => setSection("ask")}
                    className={`dm-tab flex-1 rounded-md px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
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
                ) : section === "compare" ? (
                  <div
                    role="tabpanel"
                    id="section-panel-compare"
                    aria-labelledby="section-tab-compare"
                  >
                    <ComparePanel key={id} spaceId={id as string} documents={documents} />
                  </div>
                ) : section === "intelligence" ? (
                  <div
                    role="tabpanel"
                    id="section-panel-intelligence"
                    aria-labelledby="section-tab-intelligence"
                  >
                    <IntelligencePanel spaceId={id as string} />
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
                    <fieldset className="mt-4">
                      <legend className="text-sm font-medium text-gray-700">
                        Knowledge scope
                      </legend>
                      <div className="mt-2 flex flex-wrap gap-4">
                        <label className="inline-flex items-center gap-2 text-sm text-gray-700">
                          <input
                            type="radio"
                            name="knowledge-scope"
                            value="private"
                            checked={scope === "private"}
                            onChange={() => setScope("private")}
                            className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                          />
                          My documents
                        </label>
                        <label className="inline-flex items-center gap-2 text-sm text-gray-700">
                          <input
                            type="radio"
                            name="knowledge-scope"
                            value="reference"
                            checked={scope === "reference"}
                            onChange={() => setScope("reference")}
                            disabled={referenceDocuments.length === 0}
                            className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
                          />
                          Reference
                        </label>
                        <label className="inline-flex items-center gap-2 text-sm text-gray-700">
                          <input
                            type="radio"
                            name="knowledge-scope"
                            value="combined"
                            checked={scope === "combined"}
                            onChange={() => setScope("combined")}
                            disabled={referenceDocuments.length === 0}
                            className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
                          />
                          Both
                        </label>
                      </div>
                    </fieldset>
                    {referenceDocuments.length === 0 ? (
                      <p className="mt-2 text-xs text-gray-500">
                        No shared reference documents are available.
                      </p>
                    ) : (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs font-medium text-gray-600">
                          {referenceDocuments.length}{" "}
                          reference document
                          {referenceDocuments.length === 1 ? "" : "s"} available
                        </summary>
                        <ul className="mt-2 space-y-1">
                          {referenceDocuments.map((document) => (
                            <li key={document.id} className="text-xs text-gray-500">
                              {document.title}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
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
                      <Button
                        type="submit"
                        disabled={asking || !question.trim()}
                        className="mt-3 bg-gray-900 text-white hover:bg-gray-800"
                      >
                        {asking ? "Finding evidence..." : "Ask question"}
                      </Button>
                    </form>
                    {askError && (
                      <p role="alert" className="mt-4 text-sm text-red-600">
                        {askError}
                      </p>
                    )}
                    {answer && (
                      <div aria-live="polite" className="mt-6 border-t pt-5">
                        {answerScope && (
                          <p className="text-xs text-gray-400">
                            Scope: {SCOPE_LABELS[answerScope]}
                          </p>
                        )}
                        <p className="whitespace-pre-wrap leading-7 text-gray-800">
                          {answer.answer}
                        </p>
                        {answer.citations.length > 0 && (
                          <SourceDisclosure
                            noun="source"
                            sources={answer.citations.map((citation) => ({
                              key: citation.source_id,
                              label: `${citation.source_kind === "reference" ? "Reference" : "Private"} · ${citation.document_name}, page ${citation.page_number}`,
                              excerpt: citation.excerpt,
                            }))}
                          />
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <EmptyState
                title="Select a document"
                description="Choose a document from the list to view its overview, actions or ask questions."
              />
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
