import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError } from "../api/native";
import { type Credentials, ErrorCode, makeCredentials, SubsonicClient, SubsonicError } from "../api/subsonic";
import type { User } from "../api/types";

const STORAGE_KEY = "sound-barrier.credentials";

interface Session {
  client: SubsonicClient;
  user: User;
  serverVersion?: string;
}

interface AuthState {
  session: Session | null;
  /** True while a stored session is being checked at startup. */
  restoring: boolean;
  login(username: string, password: string, remember: boolean): Promise<void>;
  logout(): void;
  /** Changes the signed-in user's password and keeps them signed in. */
  changeOwnPassword(password: string): Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

// Two credentials are kept: the Subsonic token (for /rest, stored here) and an HttpOnly
// session cookie (for /api, handled by the browser). "Remember me" keeps the token in
// localStorage (and a 30-day cookie); otherwise both last for the browser session.
function loadCredentials(): { credentials: Credentials; remember: boolean } | null {
  for (const [storage, remember] of [
    [sessionStorage, false],
    [localStorage, true],
  ] as const) {
    try {
      const raw = storage.getItem(STORAGE_KEY);
      if (raw) return { credentials: JSON.parse(raw) as Credentials, remember };
    } catch {
      // unavailable storage or corrupted value: ignore
    }
  }
  return null;
}

function saveCredentials(credentials: Credentials, remember: boolean): void {
  clearCredentials();
  try {
    (remember ? localStorage : sessionStorage).setItem(STORAGE_KEY, JSON.stringify(credentials));
  } catch {
    // storage unavailable: the session still works until the page is reloaded
  }
}

function clearCredentials(): void {
  for (const storage of [sessionStorage, localStorage]) {
    try {
      storage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }
}

async function openSession(credentials: Credentials): Promise<Session> {
  const client = new SubsonicClient(credentials);
  const response = await client.call("getUser", { username: credentials.username });
  return { client, user: response.user, serverVersion: response.serverVersion };
}

function isRejected(error: unknown): boolean {
  return (
    (error instanceof SubsonicError && error.code === ErrorCode.WrongCredentials) ||
    (error instanceof ApiError && error.status === 401)
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [remember, setRemember] = useState(false);
  const [restoring, setRestoring] = useState(true);

  useEffect(() => {
    const stored = loadCredentials();
    if (!stored) {
      setRestoring(false);
      return;
    }
    Promise.all([openSession(stored.credentials), api.me()])
      .then(([opened]) => {
        setRemember(stored.remember);
        setSession(opened);
      })
      .catch((error: unknown) => {
        // Forget the credentials only if they were rejected (password changed, session
        // expired), not if the server is down.
        if (isRejected(error)) clearCredentials();
      })
      .finally(() => setRestoring(false));
  }, []);

  const login = useCallback(async (username: string, password: string, rememberMe: boolean) => {
    const credentials = makeCredentials(username, password);
    const opened = await openSession(credentials);
    await api.login(username, password, rememberMe);
    saveCredentials(credentials, rememberMe);
    setRemember(rememberMe);
    setSession(opened);
  }, []);

  const logout = useCallback(() => {
    void api.logout().catch(() => undefined);
    clearCredentials();
    setSession(null);
  }, []);

  const changeOwnPassword = useCallback(
    async (password: string) => {
      if (!session) return;
      await api.changeOwnPassword(password);
      // The Subsonic token is derived from the password: make a new one.
      const credentials = makeCredentials(session.user.username, password);
      saveCredentials(credentials, remember);
      setSession({ ...session, client: new SubsonicClient(credentials) });
    },
    [session, remember],
  );

  const value = useMemo(
    () => ({ session, restoring, login, logout, changeOwnPassword }),
    [session, restoring, login, logout, changeOwnPassword],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

/** The logged-in session. Only use inside routes that require authentication. */
export function useSession(): Session {
  const { session } = useAuth();
  if (!session) throw new Error("useSession requires a logged-in user");
  return session;
}
