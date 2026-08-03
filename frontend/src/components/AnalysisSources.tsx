import { useState } from "react";
import type { AnalysisSource } from "../api";

function uniqueSources(sources: AnalysisSource[]): AnalysisSource[] {
  const seen = new Set<string>();
  const unique: AnalysisSource[] = [];
  for (const source of sources) {
    if (seen.has(source.chunk_id)) continue;
    seen.add(source.chunk_id);
    unique.push(source);
  }
  return unique;
}

export default function AnalysisSources({
  sources,
}: {
  sources: AnalysisSource[];
}) {
  const [open, setOpen] = useState(false);
  const unique = uniqueSources(sources);
  if (unique.length === 0) return null;

  const label =
    unique.length === 1
      ? "View source"
      : `View sources (${unique.length})`;

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
      >
        {open ? "Hide sources" : label}
      </button>
      {open && (
        <ul className="mt-3 space-y-3" aria-label="Supporting sources">
          {unique.map((source) => (
            <li
              key={source.chunk_id}
              className="rounded-md border-l-2 border-indigo-200 bg-gray-50 p-3"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Source · Page {source.page_number}
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
