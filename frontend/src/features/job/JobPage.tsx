import { useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { useApi } from "../../shared/api/context";
import type { Status } from "../../shared/api/client";
import { OutreachPanel } from "./OutreachPanel";
import { StatusForm } from "./StatusForm";

export function JobPage() {
  const { id } = useParams();
  const jobId = Number(id);
  const { api, apiUrl, token } = useApi();
  const { data, isPending, error } = api.$api.useQuery("get", "/api/jobs/{job_id}", { params: { path: { job_id: jobId } } });
  const queryClient = useQueryClient();
  const avoid = api.$api.useMutation("post", "/api/companies/{company_id}", {
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["get", "/api/jobs/{job_id}"] }),
  });

  if (isPending) return <p className="text-gray-500">Loading…</p>;
  if (error || !data) return <p className="text-red-700">Job not found.</p>;
  const { job, company, assessment, application } = data;

  return (
    <article className="space-y-4">
      <Link to="/" className="text-sm text-indigo-700">← Digest</Link>
      <header>
        <h2 className="text-xl font-bold">{job.title}</h2>
        <div className="text-gray-600">
          {company.name} <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-800">{company.tier.replace("_", " ")}</span>
          {job.location_raw && <> · {job.location_raw}</>}
          {company.status === "avoid" && <span className="ml-2 text-red-700">(company blocklisted)</span>}
        </div>
        <a href={job.url} target="_blank" rel="noreferrer" className="mt-2 inline-block rounded bg-gray-900 px-3 py-1 text-white">
          Apply on {company.ats}
        </a>
      </header>

      {assessment && (
        <section className="rounded border border-gray-200 bg-white p-3">
          <div className="flex items-baseline gap-3">
            {assessment.fit_score !== null && assessment.fit_score !== undefined ? (
              <span className="text-3xl font-bold">{assessment.fit_score}</span>
            ) : (
              <span className="text-amber-700">Unscored</span>
            )}
            <span className="uppercase text-gray-500">{assessment.verdict ?? "rules passed"}</span>
          </div>
          {assessment.reason && <p className="mt-1">{assessment.reason}</p>}
          {assessment.years_evidence && (
            <blockquote className="mt-2 border-l-2 border-gray-300 pl-2 text-sm text-gray-600">
              “{assessment.years_evidence}” — bar {assessment.min_years ?? "?"}–{assessment.max_years ?? "∞"} yrs
            </blockquote>
          )}
          <div className="mt-2 text-sm">
            <span className="text-emerald-700">Matched: {assessment.matched_skills.join(", ") || "—"}</span>
            <span className="ml-3 text-gray-500">Missing: {assessment.missing_skills.join(", ") || "—"}</span>
          </div>
          {assessment.rule_fails.length > 0 && <div className="mt-1 text-xs text-red-700">Rule flags: {assessment.rule_fails.join(", ")}</div>}
        </section>
      )}

      <section>
        <h3 className="mb-1 font-semibold">Your status</h3>
        <StatusForm jobId={jobId} current={(application?.status as Status) ?? null} apiUrl={apiUrl} token={token} />
      </section>

      <OutreachPanel jobId={jobId} />

      <section>
        <h3 className="mb-1 font-semibold">Description</h3>
        <pre className="whitespace-pre-wrap rounded bg-white p-3 text-sm text-gray-800">{job.description ?? "No description stored."}</pre>
      </section>

      <button
        type="button"
        className="text-sm text-red-700 underline"
        disabled={avoid.isPending || company.status === "avoid"}
        onClick={() => avoid.mutate({ params: { path: { company_id: company.id } }, body: { status: "avoid", notes: `${company.notes ? company.notes + "; " : ""}blocklisted from job ${jobId}` } })}
      >
        Blocklist {company.name}
      </button>
    </article>
  );
}
