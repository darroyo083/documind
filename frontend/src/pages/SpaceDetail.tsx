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
  StatusBadge,
  type WorkspaceTab,
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

const SECTION_ORDER: Section[] = ["overview", "actions", "compare", "intelligence", "ask"];

const SECTION_TABS: WorkspaceTab[] = [
  { id: "overview", label: "Overview" },
  { id: "actions", label: "Actions" },
  { id: "compare", label: "Compare" },
  { id: "intelligence", label: "Intelligence" },
  { id: "ask", label: "Ask" },
];

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
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
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
        const requestedDocument = searchParams.get("document");
        if (requestedDocument) setMobileDetailOpen(true);
        setSelectedDocumentId((current) => {
          if (current && documentResponse.some((document) => document.id === current)) {
            return current;
          }
          if (
            requestedDocument &&
            documentResponse.some((document) => document.id === requestedDocument)
          ) {
            return requestedDocument;
          }
          return documentResponse.find((document) => document.status === "ready")?.id
            ?? documentResponse[0]?.id
            ?? null;
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
      setMobileDetailOpen(true);
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
      <AppHeader
        title={space.name}
        backTo="/"
        right={<Link to="/search">Search</Link>}
        tabs={SECTION_TABS}
        activeTab={section}
        onTabChange={(next) => {
          setSection(next as Section);
          if (selectedDocument) setMobileDetailOpen(true);
        }}
      />

      <main className="dm-container dm-page-main">
        {space.description && (
          <p className="dm-space-description mb-7 max-w-prose text-gray-600">{space.description}</p>
        )}
        {documents.length === 0 ? (
          <section className="dm-empty-space-layout" aria-label="Empty Space">
            <div className="dm-empty-space-content">
              <EmptyState
                title="This space is empty"
                description="Add contracts, reports or research to build a connected intelligence workspace."
                action={
                  <DocumentUpload
                    spaceId={id as string}
                    onDocumentAdded={handleDocumentAdded}
                    onUploadingChange={handleUploadingChange}
                  />
                }
              />
              {uploadError && (
                <p role="alert" className="dm-empty-space-error">
                  {uploadError}
                </p>
              )}
            </div>
          </section>
        ) : (
        <>
        {mobileDetailOpen && (
          <button
            type="button"
            className="dm-mobile-sheet-backdrop"
            aria-label="Close document detail"
            onClick={() => setMobileDetailOpen(false)}
          />
        )}
        <div className="dm-space-layout">
          <section className="dm-space-library" aria-labelledby="documents-heading">
            <div className="dm-surface p-5">
              <div className="dm-space-library-heading">
                <div>
                  <h2 id="documents-heading">Documents</h2>
                  <p>Upload text-based PDFs up to 10 MB. Scanned pages are not supported yet.</p>
                </div>
              </div>
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

            <div className="dm-document-list mt-4 space-y-3">
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
                        onClick={() => {
                          setSelectedDocumentId(document.id);
                          setMobileDetailOpen(true);
                        }}
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

          <section
            aria-label="Selected document"
            className={`dm-space-detail min-w-0${mobileDetailOpen ? " dm-mobile-document-detail-open" : ""}`}
          >
            {selectedDocument ? (
              <div className="dm-surface p-5">
                <button
                  type="button"
                  className="dm-mobile-sheet-close"
                  aria-label="Close document detail"
                  onClick={() => setMobileDetailOpen(false)}
                >
                  Close
                </button>
                <div
                  role="tablist"
                  aria-label="Document sections"
                  onKeyDown={handleSectionKeyDown}
                  className="dm-tabs dm-tabs-secondary mb-5 flex gap-1 rounded-lg bg-gray-100 p-1"
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
                    className="dm-tab-panel"
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
                    className="dm-tab-panel"
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
                    className="dm-tab-panel"
                    role="tabpanel"
                    id="section-panel-compare"
                    aria-labelledby="section-tab-compare"
                  >
                    <ComparePanel key={id} spaceId={id as string} documents={documents} />
                  </div>
                ) : section === "intelligence" ? (
                  <div
                    className="dm-tab-panel"
                    role="tabpanel"
                    id="section-panel-intelligence"
                    aria-labelledby="section-tab-intelligence"
                  >
                    <IntelligencePanel spaceId={id as string} />
                  </div>
                ) : (
                  <div
                    className="dm-tab-panel"
                    role="tabpanel"
                    id="section-panel-ask"
                    aria-labelledby="section-tab-ask"
                  >
                    <div className="dm-ask-workspace">
                      <section className="dm-ask-conversation" aria-label="Ask conversation">
                        <div className={`dm-ask-history ${!question && !answer ? "dm-ask-history-empty" : ""}`} aria-live="polite">
                          {!question && !answer && (
                            <div className="dm-ask-empty">
                              <p className="dm-kicker">Document intelligence</p>
                              <h2>How can I help?</h2>
                              <p>Ask a focused question and keep the supporting passages in view.</p>
                            </div>
                          )}
                          {question && <p className="dm-ask-question">{question}</p>}
                          {answer && (
                            <article className="dm-ask-answer">
                              <div className="dm-ask-answer-heading">Analysis complete</div>
                              {answerScope && <p className="dm-ask-answer-scope">Scope: {SCOPE_LABELS[answerScope]}</p>}
                              <p className="dm-ask-answer-text">{answer.answer}</p>
                            </article>
                          )}
                          {askError && <p role="alert" className="dm-error-state mt-4">{askError}</p>}
                        </div>
                        <form onSubmit={handleAsk} className="dm-ask-composer">
                          <fieldset
                            className="dm-ask-scope"
                            aria-describedby={referenceDocuments.length === 0 ? "knowledge-scope-help" : undefined}
                          >
                            <legend>Scope</legend>
                            <label>
                              <input type="radio" name="knowledge-scope" value="private" checked={scope === "private"} onChange={() => setScope("private")} />
                              My documents
                            </label>
                            <label>
                              <input type="radio" name="knowledge-scope" value="reference" checked={scope === "reference"} onChange={() => setScope("reference")} disabled={referenceDocuments.length === 0} />
                              Reference
                            </label>
                            <label>
                              <input type="radio" name="knowledge-scope" value="combined" checked={scope === "combined"} onChange={() => setScope("combined")} disabled={referenceDocuments.length === 0} />
                              Both
                            </label>
                          </fieldset>
                          {referenceDocuments.length === 0 && (
                            <p id="knowledge-scope-help" className="dm-field-help mb-3">Reference and Both are disabled because no shared reference documents are available.</p>
                          )}
                          <div className="dm-ask-input-wrap">
                            <label htmlFor="question" className="sr-only">Question</label>
                            <textarea
                              id="question"
                              value={question}
                              onChange={(event) => setQuestion(event.target.value)}
                              maxLength={1000}
                              rows={2}
                              required
                              placeholder="Ask a question about your documents..."
                              className="dm-textarea"
                            />
                            <Button type="submit" disabled={asking || !question.trim()} className="dm-ask-submit">
                              {asking ? "Finding..." : "Ask"}
                            </Button>
                          </div>
                        </form>
                      </section>
                      <aside className="dm-ask-sources" aria-label="Active citations">
                        <header>Active citations</header>
                        <div className={`dm-ask-sources-body ${answer && answer.citations.length > 0 ? "" : "dm-ask-sources-body-empty"}`}>
                          {answer && answer.citations.length > 0 ? answer.citations.map((citation, index) => (
                            <article className="dm-ask-source" key={citation.source_id}>
                              <strong>[{index + 1}] {citation.document_name} / page {citation.page_number}</strong>
                              <p>{citation.excerpt}</p>
                            </article>
                          )) : <p className="dm-field-help">Sources will appear here with the answer.</p>}
                        </div>
                      </aside>
                    </div>
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
        </>
        )}
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
      <p role="status" className="dm-feature-state">
        Loading analysis...
      </p>
    );
  }

  if (view.kind === "processing") {
    return (
      <div className="dm-feature-state">
        <p role="status" className="text-sm text-gray-600">
          Analysis is currently in progress.
        </p>
        <p className="mt-1 text-xs text-gray-400">
          The structured overview will appear once it completes.
        </p>
        <Button
          type="button"
          onClick={onAnalyze}
          className="mt-4"
        >
          Try again
        </Button>
      </div>
    );
  }

  if (view.kind === "starting") {
    return (
      <div className="dm-feature-state">
        <p role="status" className="text-sm text-gray-600">
          Analyzing document...
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
        <Button
          type="button"
          onClick={onAnalyze}
          className="mt-4"
        >
          Try again
        </Button>
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
    <div className="dm-feature-state">
      <h2 className="text-lg font-semibold text-gray-900">Structured overview</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-gray-600">
        Generate a structured overview with key facts, important dates and source
        references.
      </p>
      <Button
        type="button"
        onClick={onAnalyze}
        className="mt-4"
      >
        Analyze document
      </Button>
    </div>
  );
}
