import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { ApiError } from "../api";
import { Button, AuthFrame } from "../components/ui";

const PASSWORD_REQUIREMENTS =
  "Password must be at least 8 characters and include one uppercase letter, one lowercase letter and one digit.";

function validatePassword(password: string): string | null {
  if (password.length < 8) return PASSWORD_REQUIREMENTS;
  if (!/[A-Z]/.test(password)) return PASSWORD_REQUIREMENTS;
  if (!/[a-z]/.test(password)) return PASSWORD_REQUIREMENTS;
  if (!/[0-9]/.test(password)) return PASSWORD_REQUIREMENTS;
  return null;
}

export default function Register() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (user) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");

    const passwordError = validatePassword(password);
    if (passwordError) {
      setError(passwordError);
      return;
    }

    setSubmitting(true);
    try {
      await register(email, password, displayName);
      navigate("/");
    } catch (err: unknown) {
      setError(
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Account creation failed"
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthFrame
      variant="register"
      title="Create your account"
      description="Start with a focused space for the documents you need to understand."
      footer={
        <>
          Already have an account? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="dm-auth-form">
        {error && (
          <p className="dm-auth-error" role="alert">
            {error}
          </p>
        )}
        <div className="dm-field">
          <label htmlFor="register-display-name">Display name</label>
          <input
            id="register-display-name"
            type="text"
            required
            autoComplete="name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>
        <div className="dm-field">
          <label htmlFor="register-email">Email</label>
          <input
            id="register-email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="dm-field">
          <label htmlFor="register-password">Password</label>
          <input
            id="register-password"
            type="password"
            required
            minLength={8}
            pattern="(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9]).{8,}"
            title={PASSWORD_REQUIREMENTS}
            aria-describedby="register-password-help"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p id="register-password-help" className="dm-field-help">
            At least 8 characters, with uppercase, lowercase and a number.
          </p>
        </div>
        <Button type="submit" disabled={submitting} className="dm-auth-submit">
          {submitting ? "Creating account..." : "Create account"}
        </Button>
      </form>
    </AuthFrame>
  );
}
