import { Link } from "react-router-dom";
import PublicLayout from "../components/PublicLayout";

export default function CapabilitiesPage() {
  return (
    <PublicLayout active="capabilities">
      <div className="dm-public-page">
        <header className="dm-public-page-header dm-container">
          <div>
            <h1>Move from document intake to decision with less friction.</h1>
            <p>Bring the work around a document into a single, structured surface designed for reading, comparison and follow-through.</p>
          </div>
          <span className="dm-public-page-index" aria-hidden="true">02 / 03</span>
        </header>

        <main className="dm-container dm-capabilities-page-main">
          <section className="dm-capability-ledger" aria-label="DocuMind capabilities">
            <article><span>01 / Ingest</span><div><h2>Bring the source set together.</h2><p>Upload text-based PDFs into Spaces and keep processing states visible from the first file to the last.</p></div><Link to="/register" className="dm-text-link">Create a space <span aria-hidden="true">→</span></Link></article>
            <article><span>02 / Understand</span><div><h2>Extract the facts that move the work.</h2><p>Generate structured overviews with normalized dates, key facts and clear source references.</p></div><span className="dm-capability-note">Overview / Actions</span></article>
            <article><span>03 / Compare</span><div><h2>See the difference between documents.</h2><p>Compare ready documents across consistent dimensions and keep the supporting evidence close to each finding.</p></div><span className="dm-capability-note">Compare / Intelligence</span></article>
            <article><span>04 / Ask</span><div><h2>Ask a narrower question.</h2><p>Search your own document scope and receive an answer with active citations instead of an unsupported summary.</p></div><span className="dm-capability-note">Ask / Search</span></article>
          </section>
        </main>
      </div>
    </PublicLayout>
  );
}
