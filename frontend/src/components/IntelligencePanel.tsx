import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api";
import IntelligenceSources from "./IntelligenceSources";
import { Button, EmptyState, LoadingState } from "./ui";

type IntelligenceView =
  | { kind: "loading" }
  | { kind: "no_documents" }
  | { kind: "none" }
  | { kind: "generating" }
  | { kind: "processing" }
  | { kind: "ready"; data: api.SpaceIntelligence }
  | { kind: "failed"; message: string };

const INTERNAL_SOURCE_LABEL_PATTERN = /\bsource_\d+\b/gi;

function cleanIntelligenceText(value: string): string {
  return value.replace(INTERNAL_SOURCE_LABEL_PATTERN, "the document").replace(/\(\s*\)|\[\s*\]/g, "").replace(/[ \t]+([,.;:!?])/g, "$1").replace(/[ \t]{2,}/g, " ").trim();
}

function mapIntelligenceError(status: number, detail: string): string {
  if (status === 422) {
    const lower = detail.toLowerCase();
    if (lower.includes("context size")) return "This space has too much content to synthesize at once.";
    if (lower.includes("no ready")) return "Add at least one ready document before generating intelligence.";
    if (lower.includes("too many")) return "This space has more documents than can be synthesized at once.";
    return detail;
  }
  if (status === 409) return "Intelligence generation is already in progress for this space.";
  if (status === 502) return "Intelligence could not be generated. Try again.";
  return detail || "Intelligence could not be generated.";
}

function KeyFactRow({ item }: { item: api.IntelligenceKeyFact }) {
  return <li className="dm-intelligence-row"><h4>{cleanIntelligenceText(item.title)}</h4><p>{cleanIntelligenceText(item.detail)}</p><IntelligenceSources sources={item.sources} /></li>;
}

function Contradiction({ item }: { item: api.IntelligenceContradiction }) {
  return <article className="dm-intelligence-contradiction"><h4>{cleanIntelligenceText(item.topic)}</h4><p>{cleanIntelligenceText(item.first_claim)}</p><IntelligenceSources sources={item.first_sources} /><p>{cleanIntelligenceText(item.second_claim)}</p><IntelligenceSources sources={item.second_sources} /></article>;
}

function DateRow({ item }: { item: api.IntelligenceDate }) {
  return <li className="dm-intelligence-row"><h4>{cleanIntelligenceText(item.label)} / {cleanIntelligenceText(item.date_text)}</h4>{item.context && <p>{cleanIntelligenceText(item.context)}</p>}<IntelligenceSources sources={item.sources} /></li>;
}

function QuestionRow({ item }: { item: api.IntelligenceOpenQuestion }) {
  return <li className="dm-intelligence-row"><h4>{cleanIntelligenceText(item.question)}</h4>{item.explanation && <p>{cleanIntelligenceText(item.explanation)}</p>}<IntelligenceSources sources={item.sources} /></li>;
}

export default function IntelligencePanel({ spaceId, readOnly = false }: { spaceId: string; readOnly?: boolean }) {
  const [view, setView] = useState<IntelligenceView>({ kind: "loading" });
  const busyRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    setView({ kind: "loading" });
    api.getIntelligence(spaceId, controller.signal).then((data) => setView(toView(data))).catch((err: unknown) => {
      if (!controller.signal.aborted) setView({ kind: "failed", message: err instanceof Error ? err.message : "Intelligence could not be loaded." });
    });
    return () => controller.abort();
  }, [spaceId]);

  function toView(data: api.SpaceIntelligence): IntelligenceView {
    if (data.ready_document_count === 0) return { kind: "no_documents" };
    if (data.status === "none") return { kind: "none" };
    if (data.status === "processing") return { kind: "processing" };
    if (data.status === "failed") return { kind: "failed", message: "Intelligence generation failed. Try again." };
    return { kind: "ready", data };
  }

  const refresh = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setView({ kind: "generating" });
    try {
      setView(toView(await api.generateIntelligence(spaceId)));
    } catch (err: unknown) {
      setView(err instanceof api.ApiError ? { kind: "failed", message: mapIntelligenceError(err.status, err.detail) } : { kind: "failed", message: "Intelligence could not be generated. Try again." });
    } finally {
      busyRef.current = false;
    }
  }, [spaceId]);

  if (view.kind === "loading") return <LoadingState message="Loading workspace intelligence..." />;
  if (view.kind === "no_documents") return <EmptyState title="Intelligence needs a ready document" description="Upload and process at least one document to generate a cross-document view of this space." />;
  if (view.kind === "none") return <div className="dm-feature-state"><h2>Workspace intelligence</h2><p>Synthesize key facts, contradictions, dates and open questions across every ready document in this space.</p>{!readOnly && <Button type="button" onClick={refresh} className="mt-4">Generate intelligence</Button>}</div>;
  if (view.kind === "generating" || view.kind === "processing") return <div className="dm-feature-state"><p role="status">{view.kind === "generating" ? "Generating workspace intelligence..." : "Intelligence generation is in progress."}</p>{view.kind === "processing" && !readOnly && <Button type="button" onClick={refresh} className="mt-4">Try again</Button>}</div>;
  if (view.kind === "failed") return <div className="dm-feature-state"><p role="alert">{view.message}</p>{!readOnly && <Button type="button" onClick={refresh} className="mt-4">Try again</Button>}</div>;

  const { data } = view;
  return (
    <div className="dm-intelligence">
      <header className="dm-brief-header flex items-start justify-between gap-4">
        <div><h2>Workspace intelligence</h2><p>{data.updated_at ? `Last generated ${new Date(data.updated_at).toLocaleString()}` : ""}</p></div>
        {!readOnly && <Button type="button" onClick={refresh}>Refresh</Button>}
      </header>
      {data.is_stale && <p className="dm-status-banner mt-4" role="status">Documents changed since this snapshot was generated. Refresh to update.</p>}
      <div className="dm-intelligence-hero mt-6">
        <div className="dm-intelligence-summary">
          <section className="dm-intelligence-summary-copy" aria-labelledby="intelligence-summary-heading"><h3 className="dm-feature-section-title" id="intelligence-summary-heading">Executive summary</h3><p>{cleanIntelligenceText(data.summary) || "No summary was identified."}</p></section>
          <section className="dm-intelligence-contradictions" aria-labelledby="intelligence-contradictions-heading"><h3 id="intelligence-contradictions-heading">Contradictions detected</h3>{data.contradictions.length ? data.contradictions.map((item, index) => <Contradiction key={`${item.topic}-${index}`} item={item} />) : <p className="dm-intelligence-empty">No contradictions identified.</p>}</section>
        </div>
      </div>
      <div className="dm-intelligence-grid mt-6">
        <section className="dm-intelligence-section" aria-labelledby="intelligence-facts-heading"><h3 className="dm-feature-section-title" id="intelligence-facts-heading">Key facts</h3>{data.key_facts.length ? <ul className="dm-intelligence-list">{data.key_facts.map((item, index) => <KeyFactRow key={`${item.title}-${index}`} item={item} />)}</ul> : <p className="dm-intelligence-empty">No key facts were identified.</p>}</section>
        <section className="dm-intelligence-section" aria-labelledby="intelligence-dates-heading"><h3 className="dm-feature-section-title" id="intelligence-dates-heading">Dates / deadlines</h3>{data.dates.length ? <ul className="dm-intelligence-list">{data.dates.map((item, index) => <DateRow key={`${item.label}-${index}`} item={item} />)}</ul> : <p className="dm-intelligence-empty">No dates or deadlines were identified.</p>}</section>
        <section className="dm-intelligence-section" aria-labelledby="intelligence-questions-heading"><h3 className="dm-feature-section-title" id="intelligence-questions-heading">Open questions</h3>{data.open_questions.length ? <ul className="dm-intelligence-list">{data.open_questions.map((item, index) => <QuestionRow key={`${item.question}-${index}`} item={item} />)}</ul> : <p className="dm-intelligence-empty">No open questions identified.</p>}</section>
        <section className="dm-intelligence-section" aria-labelledby="intelligence-sources-heading"><h3 className="dm-feature-section-title" id="intelligence-sources-heading">Source trail</h3><p className="dm-intelligence-empty">Every finding keeps its supporting document and page close to the claim.</p></section>
      </div>
    </div>
  );
}
