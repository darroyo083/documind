import type { DocumentAnalysis, DocumentResponse } from "../api";
import { formatIsoDate } from "../utils/date";
import AnalysisSources from "./AnalysisSources";
import { getDocumentTypeLabel } from "./DocumentTypeBadge";

export default function AnalysisOverview({
  analysis,
  document,
}: {
  analysis: DocumentAnalysis;
  document: DocumentResponse;
}) {
  return (
    <div className="dm-brief">
      <header className="dm-brief-header">
        <h2>{analysis.normalized_title || "Untitled document"}</h2>
        <p className="dm-brief-meta">
          <span className="dm-brief-meta-type">{getDocumentTypeLabel(analysis.document_type)}</span>
          <span aria-hidden="true">·</span>
          <span>{document.page_count ?? "?"} {document.page_count === 1 ? "page" : "pages"}</span>
          <span aria-hidden="true">·</span>
          <span>{document.original_filename}</span>
        </p>
      </header>

      <div className="dm-brief-grid mt-6">
        <section className="dm-brief-summary" aria-labelledby="overview-summary-heading">
          <h3 id="overview-summary-heading">Executive summary</h3>
          {analysis.summary ? (
            <p>{analysis.summary}</p>
          ) : (
            <p className="dm-analysis-empty">No summary was identified.</p>
          )}
        </section>

        <section className="dm-brief-facts" aria-labelledby="overview-facts-heading">
          <h3 id="overview-facts-heading">Extracted key facts</h3>
          {analysis.important_dates.length === 0 && analysis.key_facts.length === 0 ? (
            <p className="dm-analysis-empty">No key facts or important dates were identified.</p>
          ) : (
            <div className="dm-brief-fact-list">
              {analysis.important_dates.map((item, index) => (
                <article className="dm-brief-fact" key={`date-${item.label}-${index}`}>
                  <span className="dm-brief-fact-label">{item.label}</span>
                  <div>
                    <p className="dm-brief-fact-value">{item.value}</p>
                    {item.normalized_date && <p className="dm-field-help">Normalized: {formatIsoDate(item.normalized_date)}</p>}
                    <AnalysisSources sources={item.sources} />
                  </div>
                </article>
              ))}
              {analysis.key_facts.map((item, index) => (
                <article className="dm-brief-fact" key={`fact-${item.label}-${index}`}>
                  <span className="dm-brief-fact-label">{item.label}</span>
                  <div>
                    <p className="dm-brief-fact-value">{item.value}</p>
                    <AnalysisSources sources={item.sources} />
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
