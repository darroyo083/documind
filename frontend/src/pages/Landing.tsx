import { Link } from "react-router-dom";
import { PublicHeader } from "../components/ui";

function ProductPreview() {
  return (
    <div className="dm-product-preview" aria-label="DocuMind product preview">
      <div className="dm-product-preview-bar">
        <div className="dm-product-preview-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
        <span>Contract review</span>
      </div>
      <div className="dm-product-preview-body">
        <aside className="dm-product-preview-sidebar" aria-label="Preview navigation">
          <p>Space</p>
          <div className="dm-preview-space">Contract review</div>
          <div className="dm-preview-doc dm-preview-doc-active">
            <i aria-hidden="true" />
            Lease agreement
          </div>
          <div className="dm-preview-doc">
            <i aria-hidden="true" />
            Renewal terms
          </div>
          <div className="dm-preview-doc">
            <i aria-hidden="true" />
            Service schedule
          </div>
        </aside>
        <section className="dm-product-preview-content" aria-label="Preview analysis">
          <div className="dm-preview-tabs" aria-label="Preview sections">
            <span className="dm-preview-tab-active">Overview</span>
            <span>Compare</span>
            <span>Ask</span>
          </div>
          <h2>Lease agreement</h2>
          <p>
            A focused view of the facts, dates and source passages that matter in the document.
          </p>
          <div className="dm-preview-insights">
            <div className="dm-preview-insight">
              <span>Document type</span>
              <strong>Agreement</strong>
            </div>
            <div className="dm-preview-insight">
              <span>Important date</span>
              <strong>30 September 2026</strong>
            </div>
          </div>
          <div className="dm-preview-source">
            <span>Source, page 4</span>
            <p>“The renewal notice must be delivered before the final quarter.”</p>
          </div>
        </section>
      </div>
    </div>
  );
}

export default function Landing() {
  return (
    <main className="dm-landing">
      <PublicHeader
        actions={
          <>
            <a href="#how-it-works">How it works</a>
            <Link to="/login">Sign in</Link>
            <Link to="/register" className="dm-button dm-button-primary dm-button-small">
              Create a space
            </Link>
          </>
        }
      />

      <section className="dm-container dm-landing-hero" aria-labelledby="landing-title">
        <div className="dm-landing-hero-copy">
          <p className="dm-kicker">A clearer way to work with documents</p>
          <h1 id="landing-title">Read less. Understand more.</h1>
          <p>
            Bring PDFs into one space, then inspect facts, compare sources and ask grounded questions.
          </p>
          <div className="dm-landing-hero-actions">
            <Link to="/register" className="dm-button dm-button-primary">
              Create a space
            </Link>
            <Link to="/login" className="dm-button dm-button-secondary">
              Sign in
            </Link>
          </div>
          <p className="dm-landing-hero-note">Built for careful reading, not noisy automation.</p>
        </div>
        <ProductPreview />
      </section>

      <section className="dm-landing-section" aria-labelledby="capabilities-title">
        <div className="dm-landing-section-header">
          <p className="dm-kicker">The work around a document</p>
          <h2 id="capabilities-title">Keep the important parts in view.</h2>
          <p>
            DocuMind turns scattered reading tasks into a steady path from source material to useful decisions.
          </p>
        </div>
        <div className="dm-capability-layout">
          <div className="dm-capability-lead">
            <h3>One space for the questions documents create.</h3>
            <p>Open a document once, then stay close to the evidence as you analyze, compare and ask.</p>
          </div>
          <div className="dm-capability-list">
            <article className="dm-capability-item">
              <h3>Understand documents</h3>
              <p>See summaries, key facts and important dates without losing the source context.</p>
            </article>
            <article className="dm-capability-item">
              <h3>Compare sources</h3>
              <p>Put ready documents side by side to find differences and shared ground.</p>
            </article>
            <article className="dm-capability-item">
              <h3>Surface open questions</h3>
              <p>Make contradictions, gaps and follow-up work visible across a Space.</p>
            </article>
            <article className="dm-capability-item">
              <h3>Ask with context</h3>
              <p>Ask a focused question and inspect the passages that support the answer.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="dm-how" id="how-it-works" aria-labelledby="how-title">
        <div className="dm-container dm-landing-section">
          <div className="dm-landing-section-header">
            <p className="dm-kicker">A simple working rhythm</p>
            <h2 id="how-title">From file to focus.</h2>
          </div>
          <div className="dm-step-list">
            <article className="dm-step">
              <span className="dm-step-index">01</span>
              <h3>Upload</h3>
              <p>Bring text-based PDFs into a Space and see their processing state.</p>
            </article>
            <article className="dm-step">
              <span className="dm-step-index">02</span>
              <h3>Understand</h3>
              <p>Review structured analysis and keep source passages close to each finding.</p>
            </article>
            <article className="dm-step">
              <span className="dm-step-index">03</span>
              <h3>Decide</h3>
              <p>Compare documents, surface gaps or ask the next question from the same Space.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="dm-container dm-landing-section dm-grounding" aria-labelledby="grounding-title">
        <div className="dm-landing-section-header">
          <p className="dm-kicker">Evidence stays visible</p>
          <h2 id="grounding-title">Answers you can inspect.</h2>
          <p>
            Source grounding is part of the interface. Every useful claim should give you a path back to the page it came from.
          </p>
        </div>
        <div className="dm-grounding-example">
          <span className="dm-grounding-example-label">Supporting source</span>
          <blockquote>“The renewal notice must be delivered before the final quarter.”</blockquote>
          <footer>Lease agreement, page 4</footer>
        </div>
      </section>

      <section className="dm-container dm-landing-section" aria-labelledby="cta-title">
        <div className="dm-landing-cta">
          <h2 id="cta-title">Start with the documents in front of you.</h2>
          <Link to="/register" className="dm-button dm-button-primary">
            Create a space
          </Link>
        </div>
      </section>

      <footer className="dm-landing-footer">
        <div className="dm-container">DocuMind is a local MVP for focused document work.</div>
      </footer>
    </main>
  );
}
