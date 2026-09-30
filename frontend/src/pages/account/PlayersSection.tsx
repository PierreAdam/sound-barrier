import { type FormEvent, useCallback, useEffect, useState } from "react";

import { api, type WebPlayers } from "../../api/native";
import { useSession } from "../../auth/AuthContext";
import { SWITCH_HINT } from "../../components/PlayerSwitch";
import { plural } from "../../format";
import { setWebPlayerId, useWebPlayerId } from "../../player/webPlayer";

const formatDate = (value: string | null) =>
  value ? new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never";

/** The user's players (each with its own queue), and the one this browser plays. */
export function PlayersSection() {
  const { username } = useSession().user;
  const playerId = useWebPlayerId(username);
  const [players, setPlayers] = useState<WebPlayers | null>(null);
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(
    () =>
      api
        .getPlayers()
        .then(setPlayers)
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e))),
    [],
  );
  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (await run(() => api.createPlayer(name))) setName("");
  }

  async function onRename(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const { id, name } = editing;
    if (await run(() => api.renamePlayer(id, name))) setEditing(null);
  }

  function onDelete(id: string, playerName: string) {
    const question =
      `Delete the player “${playerName}” and its queue? ` +
      "The browsers that use it go back to the Shared player.";
    if (!window.confirm(question)) return;
    void run(async () => {
      await api.deletePlayer(id);
      if (id === playerId) setWebPlayerId(username, null);
    });
  }

  const full = players !== null && players.players.length >= players.maxPlayers;
  const thisBrowser = <span className="badge">this browser</span>;
  const use = (id: string | null) => (
    <button className="button" type="button" onClick={() => setWebPlayerId(username, id)}>
      Use on this browser
    </button>
  );

  return (
    <section className="settings-section settings-section--wide" id="players">
      <h2 className="settings-section__title">Players and their queues</h2>
      <p className="text-muted">
        A player is where your web queue lives. Every browser plays the Shared queue, unless you give it a player of
        its own here (e.g. “Phone”): your phone then keeps its queue while your computer keeps the Shared one. What
        you listened to in audiobooks and podcasts follows your account, whatever the player.
      </p>
      <p className="text-muted">{SWITCH_HINT} Switch from here, or from the queue (above the player bar).</p>

      {players && (
        <table className="users-table players-table">
          <thead>
            <tr>
              <th>Player</th>
              <th>Queue</th>
              <th>Last saved</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                Shared {playerId === null && thisBrowser}
                <div className="text-muted players-table__note">Every browser without a player; cannot be removed</div>
              </td>
              <td>{plural(players.shared.songCount, "track")}</td>
              <td>{formatDate(players.shared.updatedAt)}</td>
              <td className="users-table__actions">{playerId !== null && use(null)}</td>
            </tr>
            {players.players.map((player) => (
              <tr key={player.id}>
                <td>
                  {editing?.id === player.id ? (
                    <form className="players-table__rename" onSubmit={onRename}>
                      <input
                        className="field__input"
                        aria-label="New name"
                        autoComplete="off"
                        maxLength={40}
                        required
                        autoFocus
                        value={editing.name}
                        onChange={(e) => setEditing({ id: player.id, name: e.target.value })}
                      />
                      <button className="button button--primary" type="submit" disabled={busy}>
                        Save
                      </button>
                      <button className="button" type="button" onClick={() => setEditing(null)}>
                        Cancel
                      </button>
                    </form>
                  ) : (
                    <>
                      {player.name} {player.id === playerId && thisBrowser}
                    </>
                  )}
                </td>
                <td>{plural(player.songCount, "track")}</td>
                <td>{formatDate(player.updatedAt)}</td>
                <td className="users-table__actions">
                  {player.id !== playerId && use(player.id)}
                  <button
                    className="button"
                    type="button"
                    disabled={busy}
                    onClick={() => setEditing({ id: player.id, name: player.name })}
                  >
                    Rename
                  </button>
                  <button
                    className="button button--danger"
                    type="button"
                    disabled={busy}
                    onClick={() => onDelete(player.id, player.name)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <form className="players-create" onSubmit={onCreate}>
        <label className="field">
          <span className="field__label">New player</span>
          <input
            className="field__input"
            autoComplete="off"
            maxLength={40}
            placeholder="e.g. Phone"
            required
            disabled={full}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <button className="button button--primary" type="submit" disabled={busy || full || !name.trim()}>
          Create player
        </button>
      </form>
      {full && <p className="text-muted">You have {players.maxPlayers} players, the most there can be.</p>}
      {error && <p className="text-error">{error}</p>}
    </section>
  );
}
