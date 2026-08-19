import { useEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { ApiError } from "../api";
import { Button } from "./ui";

export default function SignInDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { login } = useAuth();
  const navigate = useNavigate();
  const emailRef = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    emailRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, open]);

  if (!open) return null;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email, password);
      onClose();
      navigate("/", { replace: true });
    } catch (err: unknown) {
      setError(
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Sign in failed",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return createPortal(
    <div
      className="dm-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="dm-signin-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sign-in-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dm-dialog-topline">
          <p className="dm-kicker">Secure workspace access</p>
          <button type="button" className="dm-dialog-close" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="dm-signin-heading">
          <h2 id="sign-in-dialog-title">Sign in</h2>
          <p>Return to the document spaces you have already set up.</p>
        </div>
        <form onSubmit={handleSubmit} className="dm-auth-form">
          {error && (
            <p className="dm-auth-error" role="alert">
              {error}
            </p>
          )}
          <div className="dm-field">
            <label htmlFor="dialog-login-email">Email</label>
            <input
              ref={emailRef}
              id="dialog-login-email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div className="dm-field">
            <label htmlFor="dialog-login-password">Password</label>
            <input
              id="dialog-login-password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          <Button type="submit" disabled={submitting} className="dm-auth-submit">
            {submitting ? "Signing in..." : "Sign in"}
          </Button>
        </form>
        <div className="dm-auth-footer">
          Don&apos;t have an account? <Link to="/register">Create one</Link>
        </div>
      </section>
    </div>,
    document.body,
  );
}
