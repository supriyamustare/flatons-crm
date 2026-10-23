import { AxiosError, AxiosHeaders } from "axios";
import { vi } from "vitest";
import { api } from "../lib/api";
import type { Role, User } from "../lib/types";

export function makeUser(role: Role, overrides: Partial<User> = {}): User {
  return {
    id: 1, email: `${role}@flatons.com`, full_name: `Priya ${role}`, role, is_active: true,
    last_login_at: null, created_at: "2026-10-22T10:00:00Z", ...overrides,
  };
}

export function httpError(status: number, detail: unknown) {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError("Request failed", String(status), config, null, {
    status, statusText: "", data: { detail }, headers: {}, config,
  });
}

type Handler = unknown | Error | ((body: unknown) => unknown);

/** Route GET/POST calls by URL. Values may be data, an Error to throw, or a function of the body. */
export function mockApi(me: User | null, routes: { get?: Record<string, Handler>; post?: Record<string, Handler> } = {}) {
  const respond = async (table: Record<string, Handler> | undefined, url: string, body?: unknown) => {
    const handler = table?.[url];
    if (handler === undefined) throw new Error(`Unexpected request to ${url}`);
    if (handler instanceof Error) throw handler;
    return { data: typeof handler === "function" ? (handler as (b: unknown) => unknown)(body) : handler };
  };
  vi.spyOn(api, "get").mockImplementation(async (url: string) => {
    if (url === "/users/me") {
      if (!me) throw httpError(401, "Not authenticated");
      return { data: me };
    }
    return respond(routes.get, url);
  });
  const post = vi.spyOn(api, "post").mockImplementation(async (url: string, body?: unknown) => {
    if (url === "/auth/refresh" && !routes.post?.[url]) throw httpError(401, "Not authenticated");
    return respond(routes.post, url, body);
  });
  return { post };
}
