import { type FormEvent, useState } from "react";

import { useAuth } from "../../auth/AuthContext";

/** The signed-in user's own password (PUT /api/auth/password: keeps this session open). */
export function PasswordSection() {
  const { changeOwnPassword } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setMessage({ ok: false, text: "The passwords do not match." });
      return;
    }
    setSaving(true);
    try {
      await changeOwnPassword(password);
      setPassword("");
      setConfirm("");
      setMessage({ ok: true, text: "Password changed. Other devices have been signed out." });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="settings-section">
      <h2 className="settings-section__title">Password</h2>
      <form className="form-grid" onSubmit={onSubmit}>
        <label className="field">
          <span className="field__label">New password</span>
          <input
            className="field__input"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="field__label">Confirm new password</span>
          <input
            className="field__input"
            type="password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </label>
        <div className="form-grid__actions">
          <button className="button button--primary" type="submit" disabled={saving || !password}>
            Change password
          </button>
        </div>
      </form>
      {message && <p className={message.ok ? "text-success" : "text-error"}>{message.text}</p>}
    </section>
  );
}
