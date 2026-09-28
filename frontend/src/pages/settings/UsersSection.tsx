import { type FormEvent, useCallback, useEffect, useState } from "react";

import type { User } from "../../api/types";
import { useSession } from "../../auth/AuthContext";

type Role = "admin" | "user";

/** Admins: list, create, change role, reset password, delete (Subsonic user endpoints). */
export function UsersSection() {
  const { client, user: me } = useSession();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const response = await client.call("getUsers");
      setUsers(response.users.user ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** Runs a user operation, then reloads the list; errors are shown above the table. */
  async function run(operation: () => Promise<unknown>): Promise<boolean> {
    setError(null);
    let ok = true;
    try {
      await operation();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      ok = false;
    }
    await reload();
    return ok;
  }

  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Users</h2>
      {error && <p className="text-error">{error}</p>}
      <table className="users-table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Role</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <UserRow
              key={user.username}
              user={user}
              isMe={user.username === me.username}
              onRole={(role) =>
                run(() => client.call("updateUser", { username: user.username, adminRole: role === "admin" }))
              }
              onPassword={(password) => run(() => client.call("changePassword", { username: user.username, password }))}
              onDelete={() => run(() => client.call("deleteUser", { username: user.username }))}
            />
          ))}
        </tbody>
      </table>
      <CreateUserForm
        onCreate={(username, password, role) =>
          run(() => client.call("createUser", { username, password, adminRole: role === "admin" }))
        }
      />
    </section>
  );
}

function UserRow({
  user,
  isMe,
  onRole,
  onPassword,
  onDelete,
}: {
  user: User;
  isMe: boolean;
  onRole(role: Role): Promise<boolean>;
  onPassword(password: string): Promise<boolean>;
  onDelete(): Promise<boolean>;
}) {
  const [resetting, setResetting] = useState(false);
  const [password, setPassword] = useState("");

  return (
    <tr>
      <td>
        {user.username}
        {isMe && <span className="text-muted"> (you)</span>}
      </td>
      <td>
        <select
          className="field__input users-table__role"
          aria-label={`Role of ${user.username}`}
          value={user.adminRole ? "admin" : "user"}
          disabled={isMe}
          title={isMe ? "You cannot change your own role" : undefined}
          onChange={(e) => void onRole(e.target.value as Role)}
        >
          <option value="user">User</option>
          <option value="admin">Admin</option>
        </select>
      </td>
      <td className="users-table__actions">
        {resetting ? (
          <form
            className="users-table__reset"
            onSubmit={(e) => {
              e.preventDefault();
              void onPassword(password).then((ok) => {
                if (!ok) return;
                setResetting(false);
                setPassword("");
              });
            }}
          >
            <input
              className="field__input"
              type="password"
              autoComplete="new-password"
              placeholder="New password"
              aria-label={`New password for ${user.username}`}
              required
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button className="button button--primary" type="submit">
              Save
            </button>
            <button className="button button--ghost" type="button" onClick={() => setResetting(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <>
            {!isMe && (
              <button className="button button--ghost" type="button" onClick={() => setResetting(true)}>
                Reset password
              </button>
            )}
            {!isMe && (
              <button
                className="button button--ghost button--danger"
                type="button"
                onClick={() => {
                  if (window.confirm(`Delete the user ${user.username}? Their playlists and history are deleted too.`)) {
                    void onDelete();
                  }
                }}
              >
                Delete
              </button>
            )}
          </>
        )}
      </td>
    </tr>
  );
}

function CreateUserForm({
  onCreate,
}: {
  onCreate(username: string, password: string, role: Role): Promise<boolean>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!(await onCreate(username.trim(), password, role))) return;
    setUsername("");
    setPassword("");
    setRole("user");
  }

  return (
    <form className="form-grid form-grid--inline" onSubmit={onSubmit}>
      <label className="field">
        <span className="field__label">New user</span>
        <input
          className="field__input"
          autoComplete="off"
          placeholder="Username"
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
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      <label className="field">
        <span className="field__label">Role</span>
        <select className="field__input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          <option value="user">User</option>
          <option value="admin">Admin</option>
        </select>
      </label>
      <div className="form-grid__actions">
        <button className="button button--primary" type="submit" disabled={!username.trim() || !password}>
          Create user
        </button>
      </div>
    </form>
  );
}
