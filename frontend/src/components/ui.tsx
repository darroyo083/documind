import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link } from "react-router-dom";

type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      {...props}
      className={`dm-button dm-button-${variant} ${className}`.trim()}
    />
  );
}

export function LoadingState({ message }: { message: string }) {
  return (
    <div className="dm-loading" role="status" aria-live="polite">
      <span className="dm-skeleton dm-skeleton-short" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  className = "",
}: {
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`dm-empty-state ${className}`.trim()}>
      <div className="dm-empty-mark" aria-hidden="true">
        +
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      {action && <div className="dm-empty-action">{action}</div>}
    </div>
  );
}

const STATUS_LABELS: Record<string, string> = {
  ready: "Ready",
  processing: "Processing",
  failed: "Failed",
  stale: "Needs refresh",
};

export function StatusBadge({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status;
  return (
    <span className={`dm-status dm-status-${status}`}>
      <span className="dm-status-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

export interface SourceItem {
  key: string;
  label: string;
  excerpt: string;
}

export function SourceDisclosure({
  sources,
  noun = "source",
}: {
  sources: SourceItem[];
  noun?: string;
}) {
  const [open, setOpen] = useState(false);
  if (sources.length === 0) return null;
  const label = sources.length === 1 ? `View ${noun}` : `View ${noun}s (${sources.length})`;

  return (
    <div className="dm-source-disclosure">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="dm-source-toggle"
      >
        <span>{open ? `Hide ${noun}${sources.length === 1 ? "" : "s"}` : label}</span>
        <span aria-hidden="true">{open ? "⌃" : "⌄"}</span>
      </button>
      {open && (
        <ul className="dm-source-list" aria-label={`Supporting ${noun}s`}>
          {sources.map((source) => (
            <li key={source.key} className="dm-source-item">
              <p className="dm-source-label">{source.label}</p>
              <p className="dm-source-excerpt">“{source.excerpt}”</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`dm-brand ${compact ? "dm-brand-compact" : ""}`.trim()}>
      <span className="dm-brand-mark" aria-hidden="true" />
      DocuMind
    </span>
  );
}

export function AppHeader({
  title,
  backTo,
  backLabel = "Dashboard",
  userName,
  onLogout,
  right,
}: {
  title?: string;
  backTo?: string;
  backLabel?: string;
  userName?: string;
  onLogout?: () => void;
  right?: ReactNode;
}) {
  return (
    <header className="dm-app-header">
      <div className="dm-container dm-header-inner">
        <div className="dm-header-leading">
          {backTo ? (
            <Link to={backTo} className="dm-back-link">
              <span aria-hidden="true">←</span> {backLabel}
            </Link>
          ) : (
            <Link to="/" aria-label="DocuMind home">
              <BrandMark compact />
            </Link>
          )}
          {title && <h1 className="dm-header-title">{title}</h1>}
        </div>
        <div className="dm-header-actions">
          {right}
          {userName && <span className="dm-header-user">{userName}</span>}
          {onLogout && (
            <button type="button" onClick={onLogout} className="dm-button dm-button-quiet dm-button-small">
              Sign out
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

export function AuthFrame({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <main className="dm-auth-layout">
      <section className="dm-auth-intro" aria-labelledby="auth-intro-title">
        <Link to="/" aria-label="DocuMind home">
          <BrandMark />
        </Link>
        <div className="dm-auth-intro-copy">
          <p className="dm-kicker">Document intelligence, grounded in your files</p>
          <h1 id="auth-intro-title">Read less. Understand more.</h1>
          <p>
            Bring your documents into a focused workspace for analysis, comparison and clear answers.
          </p>
        </div>
        <p className="dm-auth-note">Private local MVP. Built for careful reading.</p>
      </section>
      <section className="dm-auth-panel" aria-labelledby="auth-title">
        <div className="dm-auth-card">
          <div className="dm-auth-heading">
            <p className="dm-kicker">Welcome to DocuMind</p>
            <h2 id="auth-title">{title}</h2>
            <p>{description}</p>
          </div>
          {children}
          <div className="dm-auth-footer">{footer}</div>
        </div>
      </section>
    </main>
  );
}
