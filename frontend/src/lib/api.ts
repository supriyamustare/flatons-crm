import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

/** All API calls go through this client. Auth lives in HttpOnly cookies, never in JS. */
export const api = axios.create({ baseURL: "/api", withCredentials: true });

/** Fired when the session can't be renewed; the auth provider signs the user out. */
export const authEvents = new EventTarget();

const NO_REFRESH = ["/auth/login", "/auth/refresh", "/auth/logout"];
type RetryableConfig = InternalAxiosRequestConfig & { _retried?: boolean };
let refreshing: Promise<void> | null = null;

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryableConfig | undefined;
    const skip =
      error.response?.status !== 401 ||
      !config ||
      config._retried ||
      NO_REFRESH.some((path) => config.url?.startsWith(path));
    if (skip) return Promise.reject(error);

    // Access token expired: renew once (shared by parallel requests), then retry.
    config._retried = true;
    try {
      refreshing ??= api
        .post("/auth/refresh")
        .then(() => undefined)
        .finally(() => {
          refreshing = null;
        });
      await refreshing;
      return api(config);
    } catch {
      authEvents.dispatchEvent(new Event("expired"));
      return Promise.reject(error);
    }
  },
);

const FIELD_LABELS: Record<string, string> = {
  full_name: "Name",
  email: "Email",
  password: "Password",
  new_password: "New password",
  current_password: "Current password",
  role: "Role",
  name: "Name",
  mobile: "Mobile",
  alt_mobile: "Alternate mobile",
  city: "City",
  source: "Source",
  sub_source: "Sub-source",
  budget_min: "Budget from",
  budget_max: "Budget up to",
  estimated_value: "Estimated value",
  remarks: "Remarks",
  reason: "Reason",
  note: "Note",
};

/** Turn an API error into one sentence a person can act on. */
export function errorMessage(err: unknown, fallback = "Something went wrong. Try again."): string {
  if (!axios.isAxiosError(err)) return fallback;
  if (!err.response) return "Can’t reach the server. Check your internet connection.";

  const detail = (err.response.data as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { loc?: unknown[]; msg?: string };
    const field = String(first.loc?.[first.loc.length - 1] ?? "");
    const msg = (first.msg ?? "is invalid").replace(/^Value error, /, "");
    return FIELD_LABELS[field] ? `${FIELD_LABELS[field]}: ${msg}` : msg;
  }
  return fallback;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "Never";
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}
