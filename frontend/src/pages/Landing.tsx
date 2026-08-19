import { useState } from "react";
import { Link } from "react-router-dom";
import PublicLayout from "../components/PublicLayout";

type PreviewStepId = "source" | "extract" | "verify";
type PreviewTabId = "overview" | "compare" | "ask";

const PREVIEW_STEPS: Array<{
  id: PreviewStepId;
  label: string;
  status: string;
}> = [
  { id: "source", label: "Source", status: "Page 04 linked" },
  { id: "extract", label: "Extract", status: "3 facts ready" },
  { id: "verify", label: "Verify", status: "Trace confirmed" },
];

const PREVIEW_TABS: Record<PreviewTabId, {
  label: string;
  title: string;
  description: string;
  insights: Array<[string, string]>;
  sourceLabel: string;
  sourceText: string;
}> = {
  overview: {
    label: "Overview",
    title: "Evidence, in context.",
    description: "Find the source passage behind a fact, a date or a decision before you move on.",
    insights: [["Document type", "Agreement"], ["Source trace", "Page 04 / verified"]],
    sourceLabel: "Supporting source / page 04",
    sourceText: "The renewal notice must be delivered before the final quarter.",
  },
  compare: {
    label: "Compare",
    title: "Compare without losing the trail.",
    description: "Keep shared terms and meaningful differences in the same reading frame.",
    insights: [["Documents in view", "3 linked"], ["Shared fact", "Renewal terms"]],
    sourceLabel: "Compared source / page 04",
    sourceText: "The same renewal window appears across the selected documents.",
  },
  ask: {
    label: "Ask",
    title: "Ask with the evidence close.",
    description: "Turn a focused question into an answer that still points back to the record.",
    insights: [["Question", "Why does it matter?"], ["Answer status", "3 passages ready"]],
    sourceLabel: "Answer support / page 04",
    sourceText: "The notice changes the decision window for the member.",
  },
};

function ProductPreview() {
  const [activeStep, setActiveStep] = useState<PreviewStepId>("extract");
  const [activeTab, setActiveTab] = useState<PreviewTabId>("overview");
  const step = PREVIEW_STEPS.find((item) => item.id === activeStep) ?? PREVIEW_STEPS[1];
  const tab = PREVIEW_TABS[activeTab];

  function activateStep(stepId: PreviewStepId) {
    setActiveStep(stepId);
  }

  function activateTab(tabId: PreviewTabId) {
    setActiveTab(tabId);
  }

  return (
    <figure className="dm-product-preview" aria-label="Document intelligence flow preview">
      <div className="dm-product-preview-bar">
        <span className="dm-preview-bar-title">DocuMind / evidence flow</span>
        <span className="dm-preview-bar-code"><i aria-hidden="true" /> Source linked</span>
      </div>
      <div className="dm-product-preview-body">
        <aside className="dm-product-preview-sidebar" aria-label="Preview stages">
          <p>Workspace</p>
          <div className="dm-preview-space">Project documents</div>
          <div className="dm-preview-doc dm-preview-doc-active"><i aria-hidden="true" /> Extract</div>
          <div className="dm-preview-doc"><i aria-hidden="true" /> Compare</div>
          <div className="dm-preview-doc"><i aria-hidden="true" /> Trace</div>
        </aside>
        <div className="dm-product-preview-content">
          <div className="dm-preview-flow" role="group" aria-label="Source to decision flow">
            {PREVIEW_STEPS.map((previewStep, index) => (
              <span className="dm-preview-flow-segment" key={previewStep.id}>
                <button
                  type="button"
                  className={`dm-preview-flow-step ${activeStep === previewStep.id ? "dm-preview-flow-step-active" : ""}`.trim()}
                  aria-pressed={activeStep === previewStep.id}
                  onClick={() => activateStep(previewStep.id)}
                  onFocus={() => activateStep(previewStep.id)}
                  onMouseEnter={() => activateStep(previewStep.id)}
                >
                  <span className={`dm-flow-node ${activeStep === previewStep.id ? "dm-flow-node-blue" : ""} ${previewStep.id === "verify" ? "dm-flow-node-outline" : ""}`.trim()}>
                    0{index + 1}
                  </span>
                  <strong>{previewStep.label}</strong>
                </button>
                {index < PREVIEW_STEPS.length - 1 && <span className="dm-flow-line" aria-hidden="true" />}
              </span>
            ))}
          </div>
          <p className="dm-preview-step-status"><span>{step.label}</span>{step.status}</p>
          <div className="dm-preview-tabs" role="tablist" aria-label="Preview sections">
            {(Object.keys(PREVIEW_TABS) as PreviewTabId[]).map((tabId) => (
              <button
                type="button"
                key={tabId}
                className={activeTab === tabId ? "dm-preview-tab-active" : ""}
                role="tab"
                aria-selected={activeTab === tabId}
                onClick={() => activateTab(tabId)}
                onFocus={() => activateTab(tabId)}
                onMouseEnter={() => activateTab(tabId)}
              >
                {PREVIEW_TABS[tabId].label}
              </button>
            ))}
          </div>
          <h2>{tab.title}</h2>
          <p>{tab.description}</p>
          <div className="dm-preview-insights">
            {tab.insights.map(([label, value]) => (
              <div className="dm-preview-insight" key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <div className="dm-preview-source">
            <span>{tab.sourceLabel}</span>
            <p>“{tab.sourceText}”</p>
          </div>
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
