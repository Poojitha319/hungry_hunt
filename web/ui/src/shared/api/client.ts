import createFetchClient, { type Middleware } from "openapi-fetch";
import createClient from "openapi-react-query";
import type { components, paths } from "./schema";

export type DigestJob = components["schemas"]["DigestJob"];
export type Digest = components["schemas"]["Digest"];
export type JobDetail = components["schemas"]["JobDetail"];
export type CompanyOut = components["schemas"]["CompanyOut"];
export type RunOut = components["schemas"]["RunOut"];
export type Status = components["schemas"]["StatusIn"]["status"];

export const STATUSES: Status[] = ["applied", "callback", "test", "interview", "rejected", "skipped"];

export function makeApi(baseUrl: string, token: string | null) {
  const fetchClient = createFetchClient<paths>({ baseUrl });
  const auth: Middleware = {
    onRequest({ request }) {
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
  };
  fetchClient.use(auth);
  return { fetch: fetchClient, $api: createClient(fetchClient) };
}

export type Api = ReturnType<typeof makeApi>;

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
