import type {
  ComparisonCommonality,
  ComparisonDimension,
  ComparisonFinding,
  ComparisonKeyDifference,
  DocumentComparison,
} from "../api";
import ComparisonSources, { FindingEvidence } from "./ComparisonSources";

function DocumentChip({ name }: { name: string }) {
  return (
    <span
      title={name}
      className="inline-block max-w-full truncate rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700"
    >
      {name}
    </span>
  );
}

function FindingRow({
  finding,
  documentName,
  documentNameFor,
}: {
  finding: ComparisonFinding;
  documentName: string;
  documentNameFor: (documentId: string) => string;
}) {
  return (
    <li className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
        {documentName}
      </p>
      {finding.not_identified ? (
        <p className="mt-1 text-sm italic text-gray-500">
          Not identified in this document
        </p>
      ) : (
        <p className="mt-1 break-words font-medium text-gray-900">{finding.value}</p>
      )}
      <FindingEvidence finding={finding} documentNameFor={documentNameFor} />
    </li>
  );
}

function DimensionCard({
  dimension,
  comparison,
}: {
  dimension: ComparisonDimension;
  comparison: DocumentComparison;
}) {
  const nameFor = (documentId: string) =>
    comparison.documents.find((member) => member.document_id === documentId)
      ?.original_filename ?? "Document";
  return (
    <article className="rounded-lg border border-gray-200 bg-gray-50 p-4 shadow-sm">
      <h4 className="text-sm font-semibold text-gray-900">{dimension.label}</h4>
      <ul className="mt-3 space-y-3">
        {dimension.findings.map((finding) => (
          <FindingRow
            key={finding.document_id}
            finding={finding}
            documentName={nameFor(finding.document_id)}
            documentNameFor={nameFor}
          />
        ))}
      </ul>
      {dimension.synthesis && (
        <p className="mt-4 text-sm leading-6 text-gray-700">{dimension.synthesis}</p>
      )}
      <ComparisonSources
        sources={dimension.sources}
        documentNameFor={nameFor}
      />
    </article>
  );
}

function DifferenceCard({
  difference,
  comparison,
}: {
  difference: ComparisonKeyDifference;
  comparison: DocumentComparison;
}) {
  const nameFor = (documentId: string) =>
    comparison.documents.find((member) => member.document_id === documentId)
      ?.original_filename ?? "Document";
  return (
    <li className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h4 className="text-sm font-semibold text-gray-900">{difference.title}</h4>
      <p className="mt-1 text-sm leading-6 text-gray-700">{difference.description}</p>
      <ComparisonSources sources={difference.sources} documentNameFor={nameFor} />
    </li>
  );
}

function CommonalityCard({
  commonality,
  comparison,
}: {
  commonality: ComparisonCommonality;
  comparison: DocumentComparison;
}) {
  const nameFor = (documentId: string) =>
    comparison.documents.find((member) => member.document_id === documentId)
      ?.original_filename ?? "Document";
  return (
    <li className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h4 className="text-sm font-semibold text-gray-900">{commonality.title}</h4>
      <p className="mt-1 text-sm leading-6 text-gray-700">{commonality.description}</p>
      <ComparisonSources sources={commonality.sources} documentNameFor={nameFor} />
    </li>
  );
}

export default function ComparisonResult({
  comparison,
}: {
  comparison: DocumentComparison;
}) {
  return (
    <div className="space-y-8">
      <section aria-labelledby="comparison-heading">
        <h2
          id="comparison-heading"
          className="text-2xl font-semibold text-gray-900"
        >
          {comparison.title || "Comparison"}
        </h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {comparison.documents.map((member) => (
            <DocumentChip key={member.document_id} name={member.original_filename} />
          ))}
        </div>
        {comparison.focus && (
          <p className="mt-3 text-sm text-gray-500">
            Focus: {comparison.focus}
          </p>
        )}
        {comparison.summary && (
          <p className="mt-4 max-w-prose leading-7 text-gray-800">
            {comparison.summary}
          </p>
        )}
      </section>

      {comparison.dimensions.length > 0 && (
        <section aria-labelledby="dimensions-heading">
          <h3 id="dimensions-heading" className="text-lg font-semibold text-gray-900">
            Comparison
          </h3>
          <div className="mt-4 space-y-4">
            {comparison.dimensions.map((dimension, index) => (
              <DimensionCard
                key={`${dimension.label}-${index}`}
                dimension={dimension}
                comparison={comparison}
              />
            ))}
          </div>
        </section>
      )}

      {comparison.key_differences.length > 0 && (
        <section aria-labelledby="differences-heading">
          <h3 id="differences-heading" className="text-lg font-semibold text-gray-900">
            Key differences
          </h3>
          <ul className="mt-4 space-y-3">
            {comparison.key_differences.map((difference, index) => (
              <DifferenceCard
                key={`${difference.title}-${index}`}
                difference={difference}
                comparison={comparison}
              />
            ))}
          </ul>
        </section>
      )}

      {comparison.commonalities.length > 0 && (
        <section aria-labelledby="commonalities-heading">
          <h3 id="commonalities-heading" className="text-lg font-semibold text-gray-900">
            Commonalities
          </h3>
          <ul className="mt-4 space-y-3">
            {comparison.commonalities.map((commonality, index) => (
              <CommonalityCard
                key={`${commonality.title}-${index}`}
                commonality={commonality}
                comparison={comparison}
              />
            ))}
          </ul>
        </section>
      )}

      <p className="text-xs text-gray-400">
        AI-generated document comparison with source evidence. Not a statement of
        legal or financial truth.
      </p>
    </div>
  );
}
