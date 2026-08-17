import type { AnalysisSource } from "../api";
import { SourceDisclosure } from "./ui";

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
  const unique = uniqueSources(sources);
  return (
    <SourceDisclosure
      sources={unique.map((source) => ({
        key: source.chunk_id,
        label: `Source · Page ${source.page_number}`,
        excerpt: source.excerpt,
      }))}
    />
  );
}
