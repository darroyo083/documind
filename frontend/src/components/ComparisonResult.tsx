import type { DocumentComparison, ComparisonFinding } from "../api";
import ComparisonSources from "./ComparisonSources";

function nameFor(comparison: DocumentComparison, documentId: string) {
  return comparison.documents.find((member) => member.document_id === documentId)?.original_filename ?? "Document";
}

function Finding({ finding, comparison }: { finding: ComparisonFinding; comparison: DocumentComparison }) {
  return (
    <div className="dm-comparison-finding">
      <p className={finding.not_identified ? "dm-comparison-muted" : ""}>
        {finding.not_identified ? "Not identified in this document" : finding.value}
      </p>
      <ComparisonSources sources={finding.sources} documentNameFor={(id) => nameFor(comparison, id)} />
    </div>
  );
}

export default function ComparisonResult({ comparison }: { comparison: DocumentComparison }) {
  return (
    <div className="dm-comparison-result">
      <header className="dm-brief-header">
        <h2>{comparison.title || "Comparison"}</h2>
        <p>{comparison.documents.map((member) => member.original_filename).join(" / ")}</p>
        {comparison.focus && <p>Focus: {comparison.focus}</p>}
        {comparison.summary && <p className="dm-comparison-summary">{comparison.summary}</p>}
      </header>

      {comparison.dimensions.length > 0 && (
        <section className="mt-6" aria-labelledby="comparison-matrix-heading">
          <h3 id="comparison-matrix-heading" className="dm-feature-section-title mb-3">Comparison matrix</h3>
          <div className="dm-comparison-matrix">
            <table className="dm-comparison-table">
              <thead>
                <tr>
                  <th scope="col">Dimension</th>
                  {comparison.documents.map((member) => <th scope="col" key={member.document_id}>{member.original_filename}</th>)}
                </tr>
              </thead>
              <tbody>
                {comparison.dimensions.map((dimension, index) => (
                  <tr key={`${dimension.label}-${index}`}>
                    <th scope="row">{dimension.label}</th>
                    {comparison.documents.map((member) => {
                      const finding = dimension.findings.find((item) => item.document_id === member.document_id);
                      return <td key={member.document_id}>{finding ? <Finding finding={finding} comparison={comparison} /> : <span className="dm-comparison-muted">No finding</span>}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {(comparison.key_differences.length > 0 || comparison.commonalities.length > 0) && (
        <div className="dm-comparison-findings mt-8">
          {comparison.key_differences.length > 0 && (
            <section aria-labelledby="differences-heading">
              <h3 id="differences-heading" className="dm-feature-section-title">Key differences</h3>
              <ul className="dm-comparison-finding-list">
                {comparison.key_differences.map((difference, index) => (
                  <li key={`${difference.title}-${index}`}>
                    <h4>{difference.title}</h4>
                    <p>{difference.description}</p>
                    <ComparisonSources sources={difference.sources} documentNameFor={(id) => nameFor(comparison, id)} />
                  </li>
                ))}
              </ul>
            </section>
          )}
          {comparison.commonalities.length > 0 && (
            <section aria-labelledby="commonalities-heading" className="mt-8">
              <h3 id="commonalities-heading" className="dm-feature-section-title">Common ground</h3>
              <ul className="dm-comparison-finding-list">
                {comparison.commonalities.map((commonality, index) => (
                  <li key={`${commonality.title}-${index}`}>
                    <h4>{commonality.title}</h4>
                    <p>{commonality.description}</p>
                    <ComparisonSources sources={commonality.sources} documentNameFor={(id) => nameFor(comparison, id)} />
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      <p className="dm-feature-disclaimer">AI-generated document comparison with source evidence. Not a statement of legal or financial truth.</p>
    </div>
  );
}
