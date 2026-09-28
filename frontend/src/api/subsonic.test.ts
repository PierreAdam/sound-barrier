import { describe, expect, it, vi } from "vitest";

import { API_VERSION, makeCredentials, SubsonicClient, SubsonicError } from "./subsonic";

function fakeFetch(body: unknown, status = 200) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

const credentials = makeCredentials("admin", "sesame", "c19b2d");

describe("makeCredentials", () => {
  it("computes the token like the Subsonic documentation example", () => {
    expect(credentials.token).toBe("26719a1196d2a940705a59634eb18eab");
  });

  it("uses a random salt by default", () => {
    expect(makeCredentials("a", "b").salt).not.toBe(makeCredentials("a", "b").salt);
  });
});

describe("SubsonicClient", () => {
  it("sends auth params as a form POST and returns the payload", async () => {
    const fetch = fakeFetch({ "subsonic-response": { status: "ok", version: "1.16.1", license: { valid: true } } });
    const client = new SubsonicClient(credentials, "/rest", fetch);

    const response = await client.call("getLicense");

    expect(response.license.valid).toBe(true);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/rest/getLicense");
    const sent = new URLSearchParams(init.body as URLSearchParams);
    expect(Object.fromEntries(sent)).toMatchObject({
      u: "admin",
      t: credentials.token,
      s: "c19b2d",
      v: API_VERSION,
      f: "json",
    });
    expect(sent.has("p")).toBe(false);
  });

  it("raises Subsonic errors with their code", async () => {
    const fetch = fakeFetch({
      "subsonic-response": { status: "failed", version: "1.16.1", error: { code: 40, message: "Wrong username or password" } },
    });
    const client = new SubsonicClient(credentials, "/rest", fetch);

    const error = await client.call("ping").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(SubsonicError);
    expect((error as SubsonicError).code).toBe(40);
  });

  it("reports HTTP errors", async () => {
    const client = new SubsonicClient(credentials, "/rest", fakeFetch({}, 502));
    await expect(client.call("ping")).rejects.toThrow("HTTP 502");
  });

  it("calls the global fetch when none is injected", async () => {
    // Real browsers reject `fetch` called with another object as `this`.
    const original = globalThis.fetch;
    const strictFetch = vi.fn(function (this: unknown) {
      if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation");
      return Promise.resolve(new Response(JSON.stringify({ "subsonic-response": { status: "ok", version: "1.16.1" } })));
    });
    globalThis.fetch = strictFetch as unknown as typeof fetch;
    try {
      await expect(new SubsonicClient(credentials).call("ping")).resolves.toMatchObject({ status: "ok" });
    } finally {
      globalThis.fetch = original;
    }
  });

  it("builds URLs with repeated params", () => {
    const client = new SubsonicClient(credentials);
    const url = new URL(client.url("star", { id: ["1", "2"] }), "http://x");
    expect(url.pathname).toBe("/rest/star");
    expect(url.searchParams.getAll("id")).toEqual(["1", "2"]);
    expect(url.searchParams.get("u")).toBe("admin");
  });
});
