import { createContext, useContext, useMemo, type ReactNode } from "react";
import { getToken } from "../auth/token";
import { API_URL, makeApi, type Api } from "./client";

const ApiContext = createContext<{ api: Api; apiUrl: string; token: string | null } | null>(null);

export function ApiProvider({ children, apiUrl = API_URL }: { children: ReactNode; apiUrl?: string }) {
  const token = getToken();
  const value = useMemo(() => ({ api: makeApi(apiUrl, token), apiUrl, token }), [apiUrl, token]);
  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

export function useApi() {
  const ctx = useContext(ApiContext);
  if (!ctx) throw new Error("useApi outside ApiProvider");
  return ctx;
}
