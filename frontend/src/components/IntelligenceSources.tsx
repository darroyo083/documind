import type { IntelligenceCitation } from "../api";
import { SourceDisclosure } from "./ui";

function uniqueSources(sources: IntelligenceCitation[]): IntelligenceCitation[] {
  const seen = new Set<string>();
  const unique: IntelligenceCitation[] = [];
  for (const source of sources) {
    if (seen.has(source.chunk_id)) continue;
    seen.add(source.chunk_id);
    unique.push(source);
  }
  return unique;
}

export default function IntelligenceSources({
  sources,
}: {
  sources: IntelligenceCitation[];
}) {
  const unique = uniqueSources(sources);
  return (
    <SourceDisclosure
      sources={unique.map((source) => ({
        key: source.chunk_id,
        label: `${source.document_name} · Page ${source.page_number}`,
        excerpt: source.excerpt,
      }))}
    />
  );
}
