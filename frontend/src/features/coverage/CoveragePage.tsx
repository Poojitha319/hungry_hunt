import { useApi } from "../../shared/api/context";
import type { RunOut } from "../../shared/api/client";

export function CoveragePage() {
  const { api } = useApi();
  const { data, isPending } = api.$api.useQuery("get", "/api/coverage", { params: { query: { days: 14 } } });
  if (isPending || !data) return <p className="text-gray-500">Loading…</p>;
  return (
    <div>
      <h2 className="mb-2 text-lg font-bold">Pipeline runs · last 14 days</h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500">
            <th className="py-1">Started (UTC)</th>
            <th>Stage</th>
            <th>Stats</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r: RunOut) => (
            <tr key={r.id} className="border-b border-gray-200 align-top">
              <td className="py-1 pr-2 whitespace-nowrap">{r.started_at.replace("T", " ").slice(0, 16)}</td>
              <td className="pr-2">{r.stage}</td>
              <td className="font-mono text-xs text-gray-700">
                {Object.entries(r.stats)
                  .filter(([, v]) => !Array.isArray(v) || (v as unknown[]).length)
                  .map(([k, v]) => `${k}=${Array.isArray(v) ? (v as unknown[]).join("|") : String(v)}`)
                  .join("  ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
