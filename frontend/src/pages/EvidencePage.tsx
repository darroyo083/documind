import { Link } from "react-router-dom";
import PublicLayout from "../components/PublicLayout";

export default function EvidencePage() {
  return (
    <PublicLayout active="evidence">
      <div className="dm-public-page">
        <header className="dm-public-page-header dm-container">
          <div>
            <p className="dm-kicker">Evidence layer / source-first answers</p>
            <h1>Keep the claim and the source in the same frame.</h1>
            <p>DocuMind is built for the moment after extraction, when you need to know why a fact is trustworthy.</p>
          </div>
          <span className="dm-public-page-index" aria-hidden="true">01 / 03</span>
        </header>

        <main className="dm-container dm-evidence-page-main">
          <section className="dm-evidence-feature" aria-labelledby="evidence-feature-title">
            <div className="dm-evidence-feature-copy">
              <p className="dm-kicker">Traceability by default</p>
              <h2 id="evidence-feature-title">An answer is only as useful as the passage behind it.</h2>
              <p>Every useful finding stays connected to its document and page, so review remains part of the workflow instead of a separate audit step.</p>
              <Link to="/register" className="dm-text-link">Start with your documents <span aria-hidden="true">→</span></Link>
            </div>
            <div className="dm-evidence-ledger" aria-label="Evidence ledger example">
              <div className="dm-evidence-ledger-top"><span>CLAIM / 014</span><span className="dm-ledger-status">VERIFIED</span></div>
              <h3>Renewal notice is due before the final quarter.</h3>
              <div className="dm-evidence-ledger-source"><span>Supporting source</span><strong>Agreement.pdf / page 04</strong><p>“The renewal notice must be delivered before the final quarter.”</p></div>
              <div className="dm-evidence-ledger-footer"><span>Confidence</span><span>Source linked</span></div>
            </div>
          </section>

          <section className="dm-evidence-principles" aria-label="Evidence principles">
            <article><span>01</span><h3>Inline sources</h3><p>Open the passage where the finding appears, without leaving the document workspace.</p></article>
            <article><span>02</span><h3>Page-aware context</h3><p>Keep document names and page references visible beside the claim they support.</p></article>
            <article><span>03</span><h3>Reviewable output</h3><p>Use structured answers as a starting point for careful reading and decisions.</p></article>
          </section>
        </main>
      </div>
    </PublicLayout>
  );
}
