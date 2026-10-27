import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "../../shared/api/context";
import type { CompanyOut } from "../../shared/api/client";
import { AddCompanyBox } from "./AddCompanyBox";

const STATUSES = ["target", "watch", "avoid"] as const;
const TIERS = ["early_funded", "mid", "big_product", "unknown"] as const;

export function CompaniesPage() {
  const { api, apiUrl, token } = useApi();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [productOnly, setProductOnly] = useState(true);
  const [tiers, setTiers] = useState<string[]>(["early_funded", "mid"]);
  const params = { q: q || undefined, kind: productOnly ? "product" : undefined, tier: tiers.length ? tiers.join(",") : undefined, limit: 500 };
  const { data, isPending } = api.$api.useQuery("get", "/api/companies", { params: { query: params } });
  const update = api.$api.useMutation("post", "/api/companies/{company_id}", {
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["get", "/api/companies"] }),
  });

  const groups = STATUSES.map((s) => [s, (data ?? []).filter((c) => c.status === s)] as const);
  return (
    <div className="space-y-6">
      <AddCompanyBox apiUrl={apiUrl} token={token} />
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <input aria-label="Search companies" className="rounded border border-gray-300 px-2 py-1" placeholder="Search name…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="flex items-center gap-1"><input type="checkbox" checked={productOnly} onChange={(e) => setProductOnly(e.target.checked)} /> product companies only</label>
        {TIERS.map((t) => (
          <label key={t} className="flex items-center gap-1">
            <input type="checkbox" checked={tiers.includes(t)} onChange={(e) => setTiers(e.target.checked ? [...tiers, t] : tiers.filter((x) => x !== t))} /> {t.replace("_", " ")}
          </label>
        ))}
        {data && <span className="text-gray-500">{data.length} shown{data.length === 500 ? " (first 500)" : ""}</span>}
      </div>
      {isPending && <p className="text-gray-500">Loading…</p>}
      {groups.map(([status, rows]) => (
        <section key={status}>
          <h2 className="mb-2 text-lg font-bold capitalize">
            {status} <span className="font-normal text-gray-500">({rows.length})</span>
          </h2>
          <table className="w-full text-sm">
            <tbody>
              {rows.map((c: CompanyOut) => (
                <tr key={c.id} className="border-b border-gray-200">
                  <td className="py-1 pr-2">
                    {c.board_url ? <a href={c.board_url} target="_blank" rel="noreferrer" className="text-indigo-700">{c.name}</a> : c.name}
                    <span className="ml-2 text-xs text-gray-500">{c.ats}{c.kind !== "unknown" ? ` · ${c.kind}` : ""}{c.tier !== "unknown" ? ` · ${c.tier.replace("_", " ")}` : ""}</span>
                  </td>
                  <td className="py-1 pr-2 text-gray-500">{c.notes}</td>
                  <td className="py-1 text-right">
                    <select value={c.status} onChange={(e) => update.mutate({ params: { path: { company_id: c.id } }, body: { status: e.target.value as (typeof STATUSES)[number] } })}>
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}
