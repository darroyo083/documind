import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { ApiError } from "../api";
import { AuthFrame, Button } from "../components/ui";

const PASSWORD_REQUIREMENTS =
  "Password must be at least 8 characters and include one uppercase letter, one lowercase letter and one digit.";

type AuthMode = "login" | "register";

function validatePassword(password: string): string | null {
  if (password.length < 8 || !/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/[0-9]/.test(password)) {
    return PASSWORD_REQUIREMENTS;
  }
  return null;
}

export default function AuthExperience({ mode }: { mode: AuthMode }) {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (user) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");

    if (mode === "register") {
      const passwordError = validatePassword(password);
      if (passwordError) {
        setError(passwordError);
        return;
      }
    }

    setSubmitting(true);
    try {
      if (mode === "register") {
        await register(email, password, displayName);
      } else {
        await login(email, password);
      }
      navigate("/", { replace: true });
    } catch (err: unknown) {
      setError(
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : mode === "register"
              ? "Account creation failed"
              : "Sign in failed",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const isRegister = mode === "register";

  return (
    <AuthFrame
      key={mode}
      variant={mode}
      title={isRegister ? "Create your account" : "Sign in to your workspace"}
      description={
        isRegister
          ? "Start with a focused space for the documents you need to understand."
          : "Return to the document spaces you have already set up."
      }
      footer={
        isRegister ? (
          <>
            Already have an account? <Link to="/login">Sign in</Link>
          </>
        ) : (
          <>
            New to DocuMind? <Link to="/register">Create an account</Link>
          </>
        )
      }
    >
      <form onSubmit={handleSubmit} noValidate className="dm-auth-form">
        {error && (
          <p className="dm-auth-error" role="alert">
            {error}
          </p>
        )}
        {isRegister && (
          <div className="dm-field">
            <label htmlFor="auth-display-name">Display name</label>
            <input
              id="auth-display-name"
              type="text"
              required
              autoComplete="name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </div>
        )}
        <div className="dm-field">
          <label htmlFor="auth-email">Email</label>
          <input
            id="auth-email"
            type="email"
            required
            autoComplete="email"
            autoFocus
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div className="dm-field">
          <label htmlFor="auth-password">Password</label>
          <input
            id="auth-password"
            type="password"
            required
            minLength={isRegister ? 8 : undefined}
            pattern={isRegister ? "(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9]).{8,}" : undefined}
            title={isRegister ? PASSWORD_REQUIREMENTS : undefined}
            aria-describedby={isRegister ? "auth-password-help" : undefined}
            autoComplete={isRegister ? "new-password" : "current-password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {isRegister && (
            <p id="auth-password-help" className="dm-field-help">
              At least 8 characters, with uppercase, lowercase and a number.
            </p>
          )}
        </div>
        <Button type="submit" disabled={submitting} className="dm-auth-submit">
          {submitting ? (isRegister ? "Creating account..." : "Signing in...") : isRegister ? "Create account" : "Sign in"}
        </Button>
      </form>
    </AuthFrame>
  );
}
