import type {
  AnalysisImportantDate,
  AnalysisKeyFact,
  DocumentAnalysis,
  DocumentResponse,
} from "../api";
import AnalysisSources from "./AnalysisSources";
import DocumentTypeBadge from "./DocumentTypeBadge";

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function formatIsoDate(iso: string): string {
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  if (!year || !month || !day || month < 1 || month > 12) return iso;
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

function DevelopmentIndicator() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800"
      title="Generated using the local deterministic development provider."
    >
      Development analysis
    </span>
  );
}

function DateCard({ item }: { item: AnalysisImportantDate }) {
  return (
    <article className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
        {item.label}
      </h4>
      <p className="mt-1 font-medium text-gray-900">{item.value}</p>
      {item.normalized_date && (
        <p className="mt-1 text-sm text-gray-500">
          Normalized: {formatIsoDate(item.normalized_date)}
        </p>
      )}
      <AnalysisSources sources={item.sources} />
    </article>
  );
}

function FactRow({ item }: { item: AnalysisKeyFact }) {
  return (
    <li className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            {item.label}
          </h4>
          <p className="mt-1 break-words font-medium text-gray-900">{item.value}</p>
        </div>
      </div>
      <AnalysisSources sources={item.sources} />
    </li>
  );
}

export default function AnalysisOverview({
  analysis,
  document,
}: {
  analysis: DocumentAnalysis;
  document: DocumentResponse;
}) {
  return (
    <div className="space-y-8">
      <section aria-labelledby="overview-heading">
        <div className="flex flex-wrap items-center gap-3">
          {analysis.provider === "mock" && <DevelopmentIndicator />}
        </div>
        <h2 id="overview-heading" className="mt-3 text-2xl font-semibold text-gray-900">
          {analysis.normalized_title}
        </h2>
        <p className="mt-1 text-sm text-gray-500">{document.original_filename}</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <DocumentTypeBadge documentType={analysis.document_type} />
          <p className="text-xs text-gray-400">
            {analysis.provider} · {analysis.model}
          </p>
        </div>
        {analysis.summary && (
          <p className="mt-4 max-w-prose leading-7 text-gray-800">{analysis.summary}</p>
        )}
      </section>

      <section aria-labelledby="dates-heading">
        <h3 id="dates-heading" className="text-lg font-semibold text-gray-900">
          Important dates
        </h3>
        {analysis.important_dates.length === 0 ? (
          <p className="mt-3 rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
            No important dates were identified.
          </p>
        ) : (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {analysis.important_dates.map((item, index) => (
              <DateCard key={`${item.label}-${index}`} item={item} />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="facts-heading">
        <h3 id="facts-heading" className="text-lg font-semibold text-gray-900">
          Key facts
        </h3>
        {analysis.key_facts.length === 0 ? (
          <p className="mt-3 rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
            No key facts were identified.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {analysis.key_facts.map((item, index) => (
              <FactRow key={`${item.label}-${index}`} item={item} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
