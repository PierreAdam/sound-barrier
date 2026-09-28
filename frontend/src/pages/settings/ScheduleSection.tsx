import { type FormEvent, useEffect, useState } from "react";

import { api, type ScanSchedule, type ScheduleResponse } from "../../api/native";

/** Admins: daily automatic scan at a time of day, and the scan at server startup. */
export function ScheduleSection() {
  const [saved, setSaved] = useState<ScheduleResponse | null>(null);
  const [draft, setDraft] = useState<ScanSchedule | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api
      .getSchedule()
      .then((schedule) => {
        setSaved(schedule);
        setDraft({ enabled: schedule.enabled, time: schedule.time, scanOnStartup: schedule.scanOnStartup });
      })
      .catch((e: unknown) => setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) }));
  }, []);

  // Once the announced run has passed, fetch the next one (the page may stay open for days).
  useEffect(() => {
    if (!saved?.nextRunAt) return;
    const delay = Math.max(0, new Date(saved.nextRunAt).getTime() - Date.now()) + 5000;
    const timer = setTimeout(() => {
      api
        .getSchedule()
        .then(setSaved)
        .catch(() => undefined);
    }, Math.min(delay, 2 ** 31 - 1));
    return () => clearTimeout(timer);
  }, [saved?.nextRunAt]);

  if (!draft || !saved) {
    return (
      <section className="settings-section">
        <h2 className="settings-section__title">Scan schedule</h2>
        {message ? <p className="text-error">{message.text}</p> : <p className="text-muted">Loading…</p>}
      </section>
    );
  }

  const dirty =
    draft.enabled !== saved.enabled || draft.time !== saved.time || draft.scanOnStartup !== saved.scanOnStartup;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    try {
      const schedule = await api.setSchedule(draft);
      setSaved(schedule);
      setMessage({ ok: true, text: "Schedule saved." });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <section className="settings-section">
      <h2 className="settings-section__title">Scan schedule</h2>
      <form className="schedule-form" onSubmit={onSubmit}>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
          />
          <span>Scan the library every day at</span>
          <input
            className="field__input schedule-form__time"
            type="time"
            aria-label="Scan time"
            required
            disabled={!draft.enabled}
            value={draft.time}
            onChange={(e) => setDraft({ ...draft, time: e.target.value })}
          />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={draft.scanOnStartup}
            onChange={(e) => setDraft({ ...draft, scanOnStartup: e.target.checked })}
          />
          <span>Also scan when the server starts (catches changes made while it was off)</span>
        </label>
        <p className="text-muted">
          Server time zone: {saved.timeZone}.{" "}
          {saved.nextRunAt ? `Next scan: ${new Date(saved.nextRunAt).toLocaleString()}.` : "Daily scan is off."}
        </p>
        <div>
          <button className="button button--primary" type="submit" disabled={!dirty}>
            Save schedule
          </button>
        </div>
      </form>
      {message && <p className={message.ok ? "text-success" : "text-error"}>{message.text}</p>}
    </section>
  );
}
