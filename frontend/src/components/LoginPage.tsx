import { type FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";

import { ErrorCode, SubsonicError } from "../api/subsonic";
import { useAuth } from "../auth/AuthContext";
import { BrandLogo } from "./BrandLogo";

export function LoginPage() {
  const { session, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (session) return <Navigate to="/home" replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(username.trim(), password, remember);
    } catch (e) {
      setError(
        e instanceof SubsonicError && e.code === ErrorCode.WrongCredentials
          ? "Wrong username or password."
          : e instanceof Error
            ? e.message
            : "Login failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login">
      <form className="login__card" onSubmit={onSubmit}>
        <div className="login__brand">
          <BrandLogo />
          <span>Sound-Barrier</span>
        </div>
        <label className="field">
          <span className="field__label">Username</span>
          <input
            className="field__input"
            autoComplete="username"
            autoFocus
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="field__label">Password</span>
          <input
            className="field__input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span>Remember me on this device</span>
        </label>
        {error && (
          <p className="login__error" role="alert">
            {error}
          </p>
        )}
        <button className="button button--primary login__submit" type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
