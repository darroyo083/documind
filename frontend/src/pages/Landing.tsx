import { Link } from "react-router-dom";
import PublicLayout from "../components/PublicLayout";

function ProductPreview() {
  return (
    <figure className="dm-product-preview" aria-label="Document intelligence flow preview">
      <div className="dm-product-preview-bar"><span>DocuMind / evidence flow</span><span className="dm-preview-bar-code">Source linked</span></div>
      <div className="dm-product-preview-body">
        <aside className="dm-product-preview-sidebar" aria-label="Preview stages">
          <p>Workspace</p>
          <div className="dm-preview-space">Project documents</div>
          <div className="dm-preview-doc dm-preview-doc-active"><i aria-hidden="true" /> Extract</div>
          <div className="dm-preview-doc"><i aria-hidden="true" /> Compare</div>
          <div className="dm-preview-doc"><i aria-hidden="true" /> Trace</div>
        </aside>
        <div className="dm-product-preview-content">
          <div className="dm-preview-flow" aria-hidden="true">
            <span className="dm-flow-node dm-flow-node-blue">01</span>
            <span className="dm-flow-line" />
            <span className="dm-flow-node">02</span>
            <span className="dm-flow-line dm-flow-line-blue" />
            <span className="dm-flow-node dm-flow-node-outline">03</span>
          </div>
          <div className="dm-preview-tabs" aria-label="Preview sections"><span className="dm-preview-tab-active">Overview</span><span>Compare</span><span>Ask</span></div>
          <h2>Evidence, in context.</h2>
          <p>Find the source passage behind a fact, a date or a decision before you move on.</p>
          <div className="dm-preview-insights">
            <div className="dm-preview-insight"><span>Document type</span><strong>Agreement</strong></div>
            <div className="dm-preview-insight"><span>Source trace</span><strong>Page 04 / verified</strong></div>
          </div>
          <div className="dm-preview-source"><span>Supporting source / page 04</span><p>“The renewal notice must be delivered before the final quarter.”</p></div>
        </div>
      </div>
    </figure>
  );
}

export default function Landing({
  initialSignInOpen = false,
  onSignInClose,
}: {
  initialSignInOpen?: boolean;
  onSignInClose?: () => void;
}) {
  return (
    <PublicLayout initialSignInOpen={initialSignInOpen} onSignInClose={onSignInClose}>
      <div className="dm-landing">
        <section className="dm-container dm-landing-hero" aria-labelledby="landing-title">
        <div className="dm-landing-hero-copy">
          <p className="dm-kicker">Document intelligence / grounded in evidence</p>
          <h1 id="landing-title">Clarity from complexity. Document intelligence grounded in evidence.</h1>
          <p>A workspace designed for precision. Extract, compare and trace critical data across documents.</p>
          <div className="dm-landing-hero-actions">
            <Link to="/register" className="dm-button dm-button-primary">Start analyzing</Link>
            <Link to="/capabilities" className="dm-button dm-button-secondary">View capabilities</Link>
          </div>
          <p className="dm-landing-hero-note">Keep the source close to every decision.</p>
        </div>
        <ProductPreview />
        </section>

        <section className="dm-container dm-landing-proof" aria-labelledby="proof-title">
          <div className="dm-landing-proof-heading">
            <p className="dm-kicker">A calmer way to read</p>
            <h2 id="proof-title">Make the source part of the answer.</h2>
            <p>DocuMind keeps extraction, comparison and traceability in one deliberate workflow.</p>
          </div>
          <div className="dm-landing-proof-list">
            <article><span>01</span><h3>Collect</h3><p>Bring related text-based PDFs into a focused Space.</p></article>
            <article><span>02</span><h3>Understand</h3><p>Extract facts, dates and actions without losing context.</p></article>
            <article><span>03</span><h3>Verify</h3><p>Return to the page behind the claim before you decide.</p></article>
          </div>
          <Link to="/evidence" className="dm-text-link">Explore the evidence layer <span aria-hidden="true">→</span></Link>
        </section>

        <section className="dm-container dm-landing-cta" aria-labelledby="deploy-title">
          <div><p className="dm-kicker">Ready when the record matters</p><h2 id="deploy-title">Deploy intelligence securely.</h2><p>Keep your files close to the workspace where the decisions are made.</p></div>
          <Link to="/register" className="dm-button dm-button-primary">Create a workspace</Link>
        </section>

      </div>
    </PublicLayout>
  );
}
