import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, type ReactNode } from "react";
import { ApiError, getJSON, onUnauthorized, sendJSON, setCsrfToken, startGoogleLogin } from "./api";
import type { Me } from "./types";

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (next?: string) => void;
  logout: (everywhere?: boolean) => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

async function fetchMe(): Promise<Me | null> {
  try {
    const me = await getJSON<Me>("/auth/me");
    setCsrfToken(me.csrf_token);
    return me;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw e;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { data, isPending } = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 5 * 60_000, retry: 1 });

  useEffect(
    () =>
      onUnauthorized(() => {
        setCsrfToken(null);
        qc.setQueryData(["me"], null);
      }),
    [qc],
  );

  const logout = useCallback(
    async (everywhere = false) => {
      try {
        await sendJSON(everywhere ? "/auth/logout-all" : "/auth/logout", {});
      } finally {
        setCsrfToken(null);
        qc.clear();
        qc.setQueryData(["me"], null);
      }
    },
    [qc],
  );

  return (
    <AuthContext.Provider value={{ me: data ?? null, loading: isPending, login: startGoogleLogin, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth phải nằm trong AuthProvider");
  return ctx;
}
