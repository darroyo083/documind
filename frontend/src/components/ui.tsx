import {
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { Link, NavLink } from "react-router-dom";

type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

export type ShellNavItem = {
  label: string;
  to: string;
  end?: boolean;
};

export type WorkspaceTab = {
  id: string;
  label: string;
};

const DEFAULT_SHELL_NAV: ShellNavItem[] = [
  { label: "Dashboard", to: "/", end: true },
  { label: "Search", to: "/search" },
];

function cx(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

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

export function IconButton({
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} className={cx("dm-icon-button", className)} />;
}

export function Input({
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx("dm-input", className)} />;
}

export function Textarea({
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx("dm-textarea", className)} />;
}

export function Select({
  className = "",
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx("dm-select", className)} />;
}

export function FormField({
  label,
  htmlFor,
  help,
  error,
  children,
  className = "",
}: {
  label: string;
  htmlFor?: string;
  help?: string;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  const helpId = htmlFor ? `${htmlFor}-help` : undefined;
  const errorId = htmlFor ? `${htmlFor}-error` : undefined;

  return (
    <div className={cx("dm-form-field", className)}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {help && !error && (
        <p id={helpId} className="dm-field-help">
          {help}
        </p>
      )}
      {error && (
        <p id={errorId} className="dm-field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function Divider({ className = "" }: { className?: string }) {
  return <hr className={cx("dm-divider", className)} />;
}

export function LoadingState({ message }: { message: string }) {
  return (
    <div className="dm-loading" role="status" aria-live="polite">
      <span className="dm-skeleton dm-skeleton-short" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

export function ErrorState({
  message,
  action,
  className = "",
}: {
  message: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("dm-error-state", className)} role="alert">
      <p>{message}</p>
      {action && <div className="dm-error-action">{action}</div>}
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
    <span className={`dm-status dm-status-${status}`} aria-label={label}>
      <span className="dm-status-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

export function StatusIndicator({ status }: { status: string }) {
  return <StatusBadge status={status} />;
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

export function EvidenceSource({ source }: { source: SourceItem }) {
  return (
    <article className="dm-evidence-source">
      <p className="dm-source-label">{source.label}</p>
      <p className="dm-source-excerpt">“{source.excerpt}”</p>
    </article>
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

export function SidebarNavItem({ item }: { item: ShellNavItem }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cx("dm-sidebar-link", isActive && "dm-sidebar-link-active")
      }
    >
      <span>{item.label}</span>
    </NavLink>
  );
}

export function WorkspaceSidebar({
  navItems = DEFAULT_SHELL_NAV,
  userName,
  userEmail,
  onLogout,
}: {
  navItems?: ShellNavItem[];
  userName?: string;
  userEmail?: string;
  onLogout?: () => void;
}) {
  return (
    <aside className="dm-workspace-sidebar" aria-label="Workspace navigation">
      <div className="dm-sidebar-top">
        <Link to="/" aria-label="DocuMind home">
          <BrandMark />
        </Link>
        <p className="dm-sidebar-label">Intelligence Workspace</p>
      </div>
      <nav className="dm-sidebar-nav" aria-label="Primary">
        {navItems.map((item) => (
          <SidebarNavItem key={`${item.to}-${item.label}`} item={item} />
        ))}
      </nav>
      {(userName || userEmail || onLogout) && (
        <div className="dm-sidebar-account">
          <div className="dm-account-avatar" aria-hidden="true">
            {(userName || userEmail || "D").slice(0, 1).toUpperCase()}
          </div>
          <div className="dm-account-copy">
            {userName && <strong>{userName}</strong>}
            {userEmail && <span>{userEmail}</span>}
          </div>
          {onLogout && (
            <button type="button" onClick={onLogout} className="dm-sidebar-logout">
              Sign out
            </button>
          )}
        </div>
      )}
    </aside>
  );
}

export function MobileBottomNav({ navItems = DEFAULT_SHELL_NAV }: { navItems?: ShellNavItem[] }) {
  return (
    <nav className="dm-mobile-bottom-nav" aria-label="Mobile navigation">
      {navItems.slice(0, 3).map((item) => (
        <SidebarNavItem key={`${item.to}-${item.label}`} item={item} />
      ))}
    </nav>
  );
}

export function AppShell({
  children,
  navItems = DEFAULT_SHELL_NAV,
  userName,
  userEmail,
  onLogout,
}: {
  children: ReactNode;
  navItems?: ShellNavItem[];
  userName?: string;
  userEmail?: string;
  onLogout?: () => void;
}) {
  return (
    <div className="dm-app-shell">
      <WorkspaceSidebar
        navItems={navItems}
        userName={userName}
        userEmail={userEmail}
        onLogout={onLogout}
      />
      <div className="dm-app-shell-main">
        {children}
        <MobileBottomNav navItems={navItems} />
      </div>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="dm-page-heading">
      <div>
        {eyebrow && <p className="dm-kicker">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="dm-page-heading-actions">{actions}</div>}
    </div>
  );
}

export function SectionHeading({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="dm-section-heading">
      <h2>{title}</h2>
      {description && <p>{description}</p>}
    </div>
  );
}

export function AppHeader({
  title,
  backTo,
  backLabel = "Dashboard",
  userName,
  onLogout,
  right,
  tabs,
  activeTab,
  onTabChange,
}: {
  title?: string;
  backTo?: string;
  backLabel?: string;
  userName?: string;
  onLogout?: () => void;
  right?: ReactNode;
  tabs?: WorkspaceTab[];
  activeTab?: string;
  onTabChange?: (tab: string) => void;
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
        {tabs && onTabChange && (
          <nav className="dm-workspace-tabs" aria-label="Document sections">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={cx(
                  "dm-workspace-tab",
                  activeTab === tab.id && "dm-workspace-tab-active",
                )}
                aria-current={activeTab === tab.id ? "page" : undefined}
                onKeyDown={(event) => {
                  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                  event.preventDefault();
                  const currentIndex = tabs.findIndex((item) => item.id === tab.id);
                  const offset = event.key === "ArrowRight" ? 1 : -1;
                  const nextIndex = (currentIndex + offset + tabs.length) % tabs.length;
                  const nextTab = tabs[nextIndex];
                  onTabChange(nextTab.id);
                  event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button")[nextIndex]?.focus();
                }}
                onClick={() => onTabChange(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        )}
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

export function PublicHeader({ actions }: { actions: ReactNode }) {
  return (
    <header className="dm-public-header">
      <div className="dm-container dm-public-header-inner">
        <Link to="/" aria-label="DocuMind home">
          <BrandMark />
        </Link>
        <nav className="dm-public-header-actions" aria-label="Primary navigation">
          {actions}
        </nav>
      </div>
    </header>
  );
}

export function AuthFrame({
  title,
  description,
  children,
  footer,
  variant = "login",
}: {
  title: string;
  description: string;
  children: ReactNode;
  footer: ReactNode;
  variant?: "login" | "register";
}) {
  return (
    <main className={`dm-auth-layout dm-auth-layout-${variant}`}>
      <section className="dm-auth-intro" aria-labelledby="auth-intro-title">
        <Link to="/" aria-label="DocuMind home">
          <BrandMark />
        </Link>
        <div className="dm-auth-intro-copy">
          <p className="dm-kicker">System registration / set A</p>
          <h1 id="auth-intro-title">Intelligence Workspace</h1>
          <p>
            Shift from manual searching to intelligent discovery. Join DocuMind to establish your precise, authoritative record-keeping system.
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
