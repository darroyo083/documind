import { Link } from "react-router-dom";
import { PublicHeader } from "../components/ui";

function ProductPreview() {
  return (
    <figure className="dm-product-preview" aria-label="Document intelligence flow preview">
      <div className="dm-product-preview-bar"><span>DocuMind / evidence flow</span><span className="dm-preview-bar-code">READY</span></div>
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

export default function Landing() {
  return (
    <main className="dm-landing">
      <PublicHeader
        actions={
          <>
            <a href="#evidence">Evidence</a>
            <a href="#capabilities">Capabilities</a>
            <Link to="/login">Sign in</Link>
            <Link to="/register" className="dm-button dm-button-primary dm-button-small">Get started</Link>
          </>
        }
      />

      <section className="dm-container dm-landing-hero" aria-labelledby="landing-title">
        <div className="dm-landing-hero-copy">
          <p className="dm-kicker">Document intelligence / grounded in evidence</p>
          <h1 id="landing-title">Clarity from complexity. Document intelligence grounded in evidence.</h1>
          <p>A workspace designed for precision. Extract, compare and trace critical data across documents.</p>
          <div className="dm-landing-hero-actions">
            <Link to="/register" className="dm-button dm-button-primary">Start analyzing</Link>
            <a href="#capabilities" className="dm-button dm-button-secondary">View capabilities</a>
          </div>
        </div>
        <ProductPreview />
      </section>

      <section className="dm-landing-section" id="capabilities" aria-labelledby="capabilities-title">
        <div className="dm-landing-section-header">
          <h2 id="capabilities-title">System capabilities</h2>
          <p className="dm-kicker dm-capability-kicker">MODULE_01 / INTELLIGENCE_ROUTING</p>
        </div>
        <div className="dm-capability-layout">
          <div className="dm-capability-lead"><h3>Built for the work around a document.</h3><p>Keep extraction, comparison and source traceability in one focused workspace.</p></div>
          <div className="dm-capability-list">
            <article className="dm-capability-item"><h3>Bulk ingestion</h3><p>Bring text-based PDFs into a Space and keep processing states visible.</p></article>
            <article className="dm-capability-item"><h3>Cross-reference</h3><p>Compare ready documents and surface differences with the evidence beside them.</p></article>
            <article className="dm-capability-item"><h3>Source traceability</h3><p>Return to the document and page behind every useful answer.</p></article>
          </div>
        </div>
      </section>

      <section className="dm-container dm-landing-section dm-landing-deploy" id="evidence" aria-labelledby="deploy-title">
        <div className="dm-landing-cta">
          <div><h2 id="deploy-title">Deploy intelligence securely.</h2><p>Keep your files close to the workspace where the decisions are made.</p></div>
          <Link to="/register" className="dm-button dm-button-primary">Create a workspace</Link>
        </div>
      </section>

      <footer className="dm-landing-footer"><div className="dm-container">DocuMind / Focused document work / 2026</div></footer>
    </main>
  );
}
