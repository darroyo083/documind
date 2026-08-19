import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { PublicHeader } from "./ui";
import SignInDialog from "./SignInDialog";
import { PUBLIC_DEMO_MODE } from "../demo";

export type PublicSection = "home" | "evidence" | "capabilities";

export default function PublicLayout({
  children,
  active = "home",
  initialSignInOpen = false,
  onSignInClose,
}: {
  children: ReactNode;
  active?: PublicSection;
  initialSignInOpen?: boolean;
  onSignInClose?: () => void;
}) {
  const [signInOpen, setSignInOpen] = useState(initialSignInOpen && !PUBLIC_DEMO_MODE);

  function closeSignIn() {
    setSignInOpen(false);
    onSignInClose?.();
  }

  return (
    <main className="dm-public-site">
      <PublicHeader
        actions={
          <>
            <Link to="/evidence" aria-current={active === "evidence" ? "page" : undefined}>
              Evidence
            </Link>
            <Link to="/capabilities" aria-current={active === "capabilities" ? "page" : undefined}>
              Capabilities
            </Link>
            {!PUBLIC_DEMO_MODE && (
              <>
                <button type="button" className="dm-public-signin" onClick={() => setSignInOpen(true)}>
                  Sign in
                </button>
                <Link to="/register" className="dm-button dm-button-primary dm-button-small">
                  Get started
                </Link>
              </>
            )}
            {PUBLIC_DEMO_MODE && (
              <>
                <span className="dm-demo-indicator">Public demo · AI disabled</span>
                <Link to="/spaces/demo" className="dm-button dm-button-primary dm-button-small">
                  Explore demo
                </Link>
              </>
            )}
          </>
        }
      />
      {children}
      <footer className="dm-public-footer">
        <div className="dm-container dm-public-footer-inner">
          <span>DocuMind · Document intelligence grounded in evidence.</span>
          <a href="https://github.com/darroyo083/documind" target="_blank" rel="noreferrer">
            GitHub
          </a>
        </div>
      </footer>
      {!PUBLIC_DEMO_MODE && <SignInDialog open={signInOpen} onClose={closeSignIn} />}
    </main>
  );
}
