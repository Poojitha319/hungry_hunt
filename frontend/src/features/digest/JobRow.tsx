import { Link } from "react-router";
import type { DigestJob } from "../../shared/api/client";

export function JobRow({ job }: { job: DigestJob }) {
  const scored = job.score !== null && job.score !== undefined;
  const tone = job.verdict === "apply" ? "text-emerald-700" : "text-amber-700";
  return (
    <li className="flex gap-4 border-b border-gray-200 py-3 last:border-0">
      <div className="min-w-0 flex-1">
        <div className="font-semibold">{job.title}</div>
        <div className="text-sm text-gray-600">
          {job.company}
          <span className="ml-2 rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-800">{job.tier.replace("_", " ")}</span>
          {job.recently_funded && <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-800">recently funded</span>}
          {(job.company_velocity ?? 0) >= 3 && <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-800">hiring fast · {job.company_velocity} junior roles</span>}
          {job.location_raw && <> · {job.location_raw}</>}
          {job.posted_age_days !== null && job.posted_age_days !== undefined && <> · posted {job.posted_age_days}d ago</>}
        </div>
        {job.reason && <div className="mt-1 text-sm text-gray-700">{job.reason}</div>}
        {job.years_evidence && <blockquote className="mt-1 text-xs text-gray-500">“{job.years_evidence}”</blockquote>}
        {job.breakdown && (
          <div className="mt-1 text-xs text-gray-500">
            skills {String(job.breakdown.skills_overlap)}/40 · seniority {String(job.breakdown.seniority_fit)}/25 · domain {String(job.breakdown.domain_fit)}/20 · practical {String(job.breakdown.practical_fit)}/15
          </div>
        )}
      </div>
      <div className="w-16 shrink-0 text-center">
        {scored ? (
          <>
            <div className={`text-2xl font-bold ${tone}`}>{job.score}</div>
            <div className="text-xs uppercase text-gray-500">{job.verdict}</div>
          </>
        ) : (
          <div className="text-xs uppercase text-amber-700">Unscored</div>
        )}
      </div>
      <div className="flex w-20 shrink-0 flex-col items-stretch gap-1 text-sm">
        <a href={job.url} target="_blank" rel="noreferrer" className="rounded bg-gray-900 px-2 py-1 text-center text-white">
          Apply
        </a>
        <Link to={`/job/${job.job_id}`} className="text-center text-indigo-700">
          Review
        </Link>
      </div>
    </li>
  );
}
