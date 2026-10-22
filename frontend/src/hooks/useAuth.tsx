import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, authEvents } from "../lib/api";
import type { User } from "../lib/types";

interface AuthValue {
  user: User | null;
  /** "loading" until we know whether a session exists. */
  status: "loading" | "ready";
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<"loading" | "ready">("loading");

  useEffect(() => {
    let cancelled = false;
    api
      .get<User>("/users/me")
      .then((r) => !cancelled && setUser(r.data))
      .catch(() => !cancelled && setUser(null))
      .finally(() => !cancelled && setStatus("ready"));

    const onExpired = () => {
      setUser(null);
      queryClient.clear();
    };
    authEvents.addEventListener("expired", onExpired);
    return () => {
      cancelled = true;
      authEvents.removeEventListener("expired", onExpired);
    };
  }, [queryClient]);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await api.post<User>("/auth/login", { email, password });
    setUser(data);
    return data;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setUser(null);
      queryClient.clear();
    }
  }, [queryClient]);

  const value = useMemo(() => ({ user, status, login, logout }), [user, status, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** For pages behind <RequireAuth>, where a user is guaranteed. */
export function useCurrentUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("useCurrentUser used outside an authenticated route");
  return user;
}
