import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api";
import IntelligenceSources from "./IntelligenceSources";

type IntelligenceView =
  | { kind: "loading" }
  | { kind: "no_documents" }
  | { kind: "none" }
  | { kind: "generating" }
  | { kind: "processing" }
  | { kind: "ready"; data: api.SpaceIntelligence }
  | { kind: "failed"; message: string };

function mapIntelligenceError(status: number, detail: string): string {
  if (status === 422) {
    const lower = detail.toLowerCase();
    if (lower.includes("context size"))
      return "This space has too much content to synthesize at once.";
    if (lower.includes("no ready"))
      return "Add at least one ready document before generating intelligence.";
    if (lower.includes("too many"))
      return "This space has more documents than can be synthesized at once.";
    return detail;
  }
  if (status === 409)
    return "Intelligence generation is already in progress for this space.";
  if (status === 502)
    return "Intelligence could not be generated. Try again.";
  return detail || "Intelligence could not be generated.";
}

function StaleBanner() {
  return (
    <p
      role="status"
      className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
    >
      Documents changed since this snapshot was generated. Refresh to update.
    </p>
  );
}

function KeyFactCard({ item }: { item: api.IntelligenceKeyFact }) {
  return (
    <li className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
        {item.title}
      </h4>
      <p className="mt-1 break-words font-medium text-gray-900">{item.detail}</p>
      <IntelligenceSources sources={item.sources} />
    </li>
  );
}

function ContradictionCard({ item }: { item: api.IntelligenceContradiction }) {
  return (
    <article className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h4 className="text-sm font-semibold text-gray-900">{item.topic}</h4>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            One document
          </p>
          <p className="mt-1 break-words text-sm text-gray-800">{item.first_claim}</p>
          <IntelligenceSources sources={item.first_sources} />
        </div>
        <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Another document
          </p>
          <p className="mt-1 break-words text-sm text-gray-800">{item.second_claim}</p>
          <IntelligenceSources sources={item.second_sources} />
        </div>
      </div>
    </article>
  );
}

function DateRow({ item }: { item: api.IntelligenceDate }) {
  return (
    <li className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          {item.label}
        </h4>
        <p className="font-medium text-gray-900">{item.date_text}</p>
      </div>
      {item.context && <p className="mt-1 text-sm text-gray-600">{item.context}</p>}
      <IntelligenceSources sources={item.sources} />
    </li>
  );
}

function OpenQuestionRow({ item }: { item: api.IntelligenceOpenQuestion }) {
  return (
    <li className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className="break-words text-sm font-medium text-gray-900">{item.question}</p>
      {item.explanation && (
        <p className="mt-1 text-sm text-gray-600">{item.explanation}</p>
      )}
      <IntelligenceSources sources={item.sources} />
    </li>
  );
}

export default function IntelligencePanel({ spaceId }: { spaceId: string }) {
  const [view, setView] = useState<IntelligenceView>({ kind: "loading" });
  const busyRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    setView({ kind: "loading" });
    api
      .getIntelligence(spaceId, controller.signal)
      .then((data) => setView(toView(data)))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setView({
          kind: "failed",
          message: err instanceof Error ? err.message : "Intelligence could not be loaded.",
        });
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
      const data = await api.generateIntelligence(spaceId);
      setView(toView(data));
    } catch (err: unknown) {
      if (err instanceof api.ApiError) {
        setView({ kind: "failed", message: mapIntelligenceError(err.status, err.detail) });
      } else {
        setView({ kind: "failed", message: "Intelligence could not be generated. Try again." });
      }
    } finally {
      busyRef.current = false;
    }
  }, [spaceId]);

  if (view.kind === "loading") {
    return (
      <p role="status" className="py-8 text-center text-sm text-gray-500">
        Loading intelligence...
      </p>
    );
  }

  if (view.kind === "no_documents") {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-300 p-8 text-center">
        <h2 className="text-lg font-semibold text-gray-900">Workspace intelligence</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-gray-600">
          Upload and process at least one document to generate a cross-document
          intelligence summary of this space.
        </p>
      </div>
    );
  }

  if (view.kind === "none") {
    return (
      <div className="py-8 text-center">
        <h2 className="text-lg font-semibold text-gray-900">Workspace intelligence</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-gray-600">
          Synthesize key facts, contradictions, dates and open questions across
          every ready document in this space.
        </p>
        <button
          type="button"
          onClick={refresh}
          className="mt-4 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          Generate intelligence
        </button>
      </div>
    );
  }

  if (view.kind === "generating" || view.kind === "processing") {
    return (
      <div className="py-8 text-center">
        <p role="status" className="text-sm text-gray-600">
          {view.kind === "generating"
            ? "Generating workspace intelligence..."
            : "Intelligence generation is in progress."}
        </p>
        <p className="mt-1 text-xs text-gray-400">
          This can take a moment for larger spaces.
        </p>
        {view.kind === "processing" && (
          <button
            type="button"
            onClick={refresh}
            className="mt-4 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            Try again
          </button>
        )}
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
          onClick={refresh}
          className="mt-4 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          Try again
        </button>
      </div>
    );
  }

  const { data } = view;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-gray-900">Workspace intelligence</h2>
          <p className="mt-1 text-xs text-gray-400">
            {data.updated_at
              ? `Last generated ${new Date(data.updated_at).toLocaleString()}`
              : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          Refresh
        </button>
      </header>

      {data.is_stale && <StaleBanner />}

      {data.summary && (
        <section aria-labelledby="intelligence-summary-heading">
          <p
            id="intelligence-summary-heading"
            className="max-w-prose leading-7 text-gray-800"
          >
            {data.summary}
          </p>
        </section>
      )}

      <section aria-labelledby="intelligence-facts-heading">
        <h3 id="intelligence-facts-heading" className="text-base font-semibold text-gray-900">
          Key facts
        </h3>
        {data.key_facts.length === 0 ? (
          <p className="mt-3 rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
            No key facts were identified.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {data.key_facts.map((item, index) => (
              <KeyFactCard key={`${item.title}-${index}`} item={item} />
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="intelligence-contradictions-heading">
        <h3 id="intelligence-contradictions-heading" className="text-base font-semibold text-gray-900">
          Contradictions
        </h3>
        {data.contradictions.length === 0 ? (
          <p className="mt-3 rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
            No contradictions identified.
          </p>
        ) : (
          <div className="mt-4 space-y-3">
            {data.contradictions.map((item, index) => (
              <ContradictionCard key={`${item.topic}-${index}`} item={item} />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="intelligence-dates-heading">
        <h3 id="intelligence-dates-heading" className="text-base font-semibold text-gray-900">
          Dates &amp; deadlines
        </h3>
        {data.dates.length === 0 ? (
          <p className="mt-3 rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
            No dates or deadlines were identified.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {data.dates.map((item, index) => (
              <DateRow key={`${item.label}-${index}`} item={item} />
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="intelligence-questions-heading">
        <h3 id="intelligence-questions-heading" className="text-base font-semibold text-gray-900">
          Open questions &amp; gaps
        </h3>
        {data.open_questions.length === 0 ? (
          <p className="mt-3 rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
            No open questions identified.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {data.open_questions.map((item, index) => (
              <OpenQuestionRow key={`${item.question}-${index}`} item={item} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
