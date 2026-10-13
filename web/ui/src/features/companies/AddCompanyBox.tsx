import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { makeApi, type CompanyOut } from "../../shared/api/client";

const STATUSES = ["target", "watch", "avoid"] as const;

export function AddCompanyBox({ apiUrl, token }: { apiUrl: string; token: string | null }) {
  const api = useMemo(() => makeApi(apiUrl, token), [apiUrl, token]);
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("watch");
  const [added, setAdded] = useState<CompanyOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.fetch.POST("/api/companies", { body: { text: text.trim(), status, notes: null } });
      if (error || !data) throw new Error(typeof error === "object" && error && "detail" in error ? String((error as { detail: unknown }).detail) : `HTTP ${response.status}`);
      return data;
    },
    onSuccess: (row) => {
      setAdded(row);
      setError(null);
      setText("");
      void queryClient.invalidateQueries({ queryKey: ["get", "/api/companies"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <form className="flex flex-wrap items-end gap-2 rounded border border-gray-200 p-3" onSubmit={(e) => { e.preventDefault(); if (text.trim()) mutation.mutate(); }}>
      <label className="flex grow flex-col text-sm">
        Board URL or slug (e.g. lever:hevodata, https://jobs.lever.co/hevodata, careers:https://acme.com/jobs)
        <input className="mt-1 rounded border border-gray-300 px-2 py-1" value={text} onChange={(e) => setText(e.target.value)} placeholder="https://boards.greenhouse.io/acme" />
      </label>
      <label className="flex flex-col text-sm">
        Status
        <select className="mt-1 rounded border border-gray-300 px-2 py-1" value={status} onChange={(e) => setStatus(e.target.value as (typeof STATUSES)[number])}>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      <button type="submit" disabled={mutation.isPending || !text.trim()} className="rounded bg-indigo-600 px-3 py-1 text-white disabled:opacity-50">Add</button>
      {added && <p role="status" className="w-full text-sm text-green-700">Added {added.name} ({added.ats}) as {added.status}.</p>}
      {error && <p role="alert" className="w-full text-sm text-red-700">{error}</p>}
    </form>
  );
}
