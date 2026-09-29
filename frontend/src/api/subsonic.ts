// Client for the Subsonic API (`/rest`). Our own endpoints will live under `/api`,
// in a separate client, so the two stay independent.
import SparkMD5 from "spark-md5";

import type { SubsonicMethod, SubsonicResponse } from "./types";

export const API_VERSION = "1.16.1";
export const CLIENT_NAME = "sound-barrier-web";

/** Error codes from the Subsonic spec that the UI reacts to. */
export const ErrorCode = {
  Generic: 0,
  WrongCredentials: 40,
  NotAuthorized: 50,
  NotFound: 70,
} as const;

export class SubsonicError extends Error {
  readonly code: number;

  constructor(code: number, message: string) {
    super(message);
    this.name = "SubsonicError";
    this.code = code;
  }
}

/** Token authentication: the password itself is never stored or sent. */
export interface Credentials {
  username: string;
  token: string; // md5(password + salt)
  salt: string;
}

export function makeCredentials(username: string, password: string, salt = randomSalt()): Credentials {
  return { username, salt, token: SparkMD5.hash(password + salt) };
}

function randomSalt(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

type ParamValue = string | number | boolean | undefined;
export type Params = Record<string, ParamValue | ParamValue[]>;

export class SubsonicClient {
  private readonly credentials: Credentials;
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(credentials: Credentials, baseUrl = "/rest", fetchImpl?: typeof fetch) {
    this.credentials = credentials;
    this.baseUrl = baseUrl;
    // Called through a wrapper: invoking `window.fetch` as a method of another object
    // throws "Illegal invocation".
    this.fetchImpl = fetchImpl ?? ((input, init) => fetch(input, init));
  }

  get username(): string {
    return this.credentials.username;
  }

  /** URL of a method, e.g. for `<audio src>` (stream) or `<img src>` (getCoverArt). */
  url(method: string, params: Params = {}): string {
    return `${this.baseUrl}/${method}?${this.query(params).toString()}`;
  }

  /** `keepalive`: the request finishes even if the page is closed (e.g. saving a bookmark). */
  async call<M extends SubsonicMethod>(
    method: M,
    params: Params = {},
    options: { keepalive?: boolean } = {},
  ): Promise<SubsonicResponse<M>> {
    const query = this.query({ ...params, f: "json" });
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/${method}`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: query,
        keepalive: options.keepalive,
      });
    } catch (cause) {
      console.error(`Subsonic ${method} request failed`, cause);
      throw new SubsonicError(ErrorCode.Generic, "Cannot reach the server");
    }
    if (!response.ok) {
      throw new SubsonicError(ErrorCode.Generic, `Server error (HTTP ${response.status})`);
    }
    const body = (await response.json()) as { "subsonic-response"?: SubsonicResponse<M> };
    const payload = body["subsonic-response"];
    if (!payload) {
      throw new SubsonicError(ErrorCode.Generic, "Invalid server response");
    }
    if (payload.status !== "ok") {
      throw new SubsonicError(payload.error?.code ?? ErrorCode.Generic, payload.error?.message ?? "Request failed");
    }
    return payload;
  }

  private query(params: Params): URLSearchParams {
    const query = new URLSearchParams({
      u: this.credentials.username,
      t: this.credentials.token,
      s: this.credentials.salt,
      v: API_VERSION,
      c: CLIENT_NAME,
    });
    for (const [key, value] of Object.entries(params)) {
      for (const item of Array.isArray(value) ? value : [value]) {
        if (item !== undefined) query.append(key, String(item));
      }
    }
    return query;
  }
}
