import { useState } from "react";
import { useApi } from "../../shared/api/context";

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="ml-2 rounded border border-gray-300 px-2 py-0.5 text-xs"
      onClick={() => { void navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}>
      {done ? "copied" : "copy"}
    </button>
  );
}

export function OutreachPanel({ jobId }: { jobId: number }) {
  const { api } = useApi();
  const existing = api.$api.useQuery("get", "/api/jobs/{job_id}/outreach", { params: { path: { job_id: jobId } } }, { retry: false });
  const draft = api.$api.useMutation("post", "/api/jobs/{job_id}/outreach", { onSuccess: () => void existing.refetch() });
  const d = draft.data ?? existing.data;
  return (
    <section className="rounded border border-gray-200 bg-white p-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Outreach (you send it; nothing is sent for you)</h3>
        <button type="button" disabled={draft.isPending} className="rounded bg-indigo-700 px-3 py-1 text-sm text-white disabled:opacity-50"
          onClick={() => draft.mutate({ params: { path: { job_id: jobId }, query: { regenerate: Boolean(d) } } })}>
          {draft.isPending ? "Drafting…" : d ? "Redraft" : "Draft note + referral ask"}
        </button>
      </div>
      {draft.error && <p className="mt-2 text-sm text-red-700">Could not draft — try again.</p>}
      {d && (
        <div className="mt-3 space-y-3 text-sm">
          {d.flags.length > 0 && (
            <div role="alert" className="rounded bg-amber-50 p-2 text-amber-900">Check before sending — {d.flags.join("; ")}</div>
          )}
          <div><span className="font-semibold">Subject</span><Copy text={d.subject} /><div>{d.subject}</div></div>
          <div><span className="font-semibold">Note</span><Copy text={d.note} /><p className="whitespace-pre-wrap">{d.note}</p></div>
          <div><span className="font-semibold">Referral ask</span><Copy text={d.referral_ask} /><p className="whitespace-pre-wrap">{d.referral_ask}</p></div>
          <div className="text-gray-600"><span className="font-semibold text-gray-800">Who to send it to:</span> {d.who_to_contact}</div>
        </div>
      )}
    </section>
  );
}
