import { useSearchParams } from "react-router";
import { CoverageFooter } from "../coverage/CoverageFooter";
import { useApi } from "../../shared/api/context";
import type { Digest, DigestJob } from "../../shared/api/client";
import { JobRow } from "./JobRow";

const SECTIONS = ["India", "Remote", "Stretch"] as const;

function Sections({ groups, minScore }: { groups: Record<string, DigestJob[]>; minScore: number }) {
  return (
    <>
      {SECTIONS.map((s) => {
        const jobs = (groups[s] ?? []).filter((j) => (j.score ?? 0) >= minScore);
        if (!jobs.length) return null;
        return (
          <section key={s} className="mb-4">
            <h3 className="mb-1 font-semibold">
              {s} <span className="font-normal text-gray-500">({jobs.length})</span>
            </h3>
            <ul>
              {jobs.map((j) => (
                <JobRow key={j.job_id} job={j} />
              ))}
            </ul>
          </section>
        );
      })}
    </>
  );
}

export function DigestPage() {
  const { api } = useApi();
  const [params, setParams] = useSearchParams();
  const days = Number(params.get("days") ?? 1) || 1;
  const minScore = Number(params.get("min") ?? 0);
  const { data, isPending, error } = api.$api.useQuery("get", "/api/digest", { params: { query: { days } } });

  if (isPending) return <p className="text-gray-500">Loading… the server may take ~30 s to wake.</p>;
  if (error || !data) return <p className="text-red-700">Could not load the digest. Is your review link current?</p>;
  const d: Digest = data;
  const count = (g: Record<string, DigestJob[]>) => Object.values(g).reduce((n, v) => n + v.length, 0);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <h2 className="text-xl font-bold">Digest · {d.date_ist}</h2>
        <span className="text-gray-500">
          {count(d.new)} new · {count(d.carried)} carried · {d.unscored.length} unscored
          {d.truncated ? ` · +${d.truncated} rolled over` : ""}
        </span>
        <label className="ml-auto">
          History{" "}
          <select value={String(days)} onChange={(e) => setParams({ days: e.target.value, ...(minScore ? { min: String(minScore) } : {}) })}>
            <option value="1">today</option>
            <option value="7">7 days</option>
            <option value="30">30 days</option>
          </select>
        </label>
        <label>
          Min score{" "}
          <input type="number" min={0} max={100} value={minScore} className="w-16 rounded border px-1"
            onChange={(e) => setParams({ days: String(days), ...(e.target.value ? { min: e.target.value } : {}) })} />
        </label>
      </div>
      {count(d.new) > 0 && (
        <>
          <h2 className="mb-2 text-emerald-700">New since yesterday</h2>
          <Sections groups={d.new} minScore={minScore} />
        </>
      )}
      {count(d.carried) > 0 && (
        <>
          <h2 className="mb-2 text-gray-600">Still open, not yet acted on</h2>
          <Sections groups={d.carried} minScore={minScore} />
        </>
      )}
      {d.unscored.length > 0 && (
        <section className="mb-4">
          <h2 className="mb-2 text-amber-700">Unscored — passed the rules, Gemini quota was hit</h2>
          <ul>
            {d.unscored.map((j) => (
              <JobRow key={j.job_id} job={j} />
            ))}
          </ul>
        </section>
      )}
      {count(d.new) + count(d.carried) + d.unscored.length === 0 && <p className="rounded bg-gray-100 p-4">No genuine openings today.</p>}
      <CoverageFooter coverage={d.coverage} pipeline={d.pipeline} />
    </div>
  );
}
