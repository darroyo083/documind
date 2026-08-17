import type { ComparisonCitation, ComparisonFinding } from "../api";
import { SourceDisclosure } from "./ui";

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
  const unique = uniqueSources(sources);
  return (
    <SourceDisclosure
      noun="evidence"
      sources={unique.map((source) => ({
        key: source.chunk_id,
        label: `${documentNameFor(source.document_id)} · Page ${source.page_number}`,
        excerpt: source.excerpt,
      }))}
    />
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
