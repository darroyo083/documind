import { useState } from "react";
import type { ComparisonCitation, ComparisonFinding } from "../api";

function uniqueSources(sources: ComparisonCitation[]): ComparisonCitation[] {
  const seen = new Set<string>();
  const unique: ComparisonCitation[] = [];
  for (const source of sources) {
    if (seen.has(source.chunk_id)) continue;
    seen.add(source.chunk_id);
    unique.push(source);
  }
  return unique;
}

export default function ComparisonSources({
  sources,
  documentNameFor,
}: {
  sources: ComparisonCitation[];
  documentNameFor: (documentId: string) => string;
}) {
  const [open, setOpen] = useState(false);
  const unique = uniqueSources(sources);
  if (unique.length === 0) return null;

  const label =
    unique.length === 1
      ? "View evidence"
      : `View evidence (${unique.length})`;

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
      >
        {open ? "Hide evidence" : label}
      </button>
      {open && (
        <ul className="mt-3 space-y-3" aria-label="Supporting evidence">
          {unique.map((source) => (
            <li
              key={source.chunk_id}
              className="rounded-md border-l-2 border-indigo-200 bg-gray-50 p-3"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                {documentNameFor(source.document_id)} · Page {source.page_number}
              </p>
              <p className="mt-1 text-sm leading-6 text-gray-700">
                &ldquo;{source.excerpt}&rdquo;
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FindingEvidence({
  finding,
  documentNameFor,
}: {
  finding: ComparisonFinding;
  documentNameFor: (documentId: string) => string;
}) {
  return <ComparisonSources sources={finding.sources} documentNameFor={documentNameFor} />;
}
