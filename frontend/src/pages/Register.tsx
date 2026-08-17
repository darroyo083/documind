import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { ApiError } from "../api";
import { Button, AuthFrame } from "../components/ui";

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
      title="Create your account"
      description="Start with a focused space for the documents you need to understand."
      footer={
        <>
          Already have an account? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="dm-auth-form">
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
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={submitting} className="dm-auth-submit">
          {submitting ? "Creating account..." : "Create account"}
        </Button>
      </form>
    </AuthFrame>
  );
}
