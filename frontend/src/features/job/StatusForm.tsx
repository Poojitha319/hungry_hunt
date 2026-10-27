import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { makeApi, STATUSES, type Status } from "../../shared/api/client";

const LABELS: Record<Status, string> = {
  applied: "Applied",
  callback: "Got a callback",
  test: "Test / OA",
  interview: "Interview",
  rejected: "Rejected",
  skipped: "Skip",
};

export function StatusForm({ jobId, current, apiUrl, token }: { jobId: number; current: Status | null; apiUrl: string; token: string | null }) {
  const api = useMemo(() => makeApi(apiUrl, token), [apiUrl, token]);
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status | null>(current);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async (next: Status) => {
      const { data, error } = await api.fetch.POST("/api/jobs/{job_id}/status", {
        params: { path: { job_id: jobId } },
        body: { status: next, notes: null },
      });
      if (error || !data) throw new Error("save failed");
      return data;
    },
    onMutate: (next) => {
      const previous = status;
      setStatus(next);
      setError(null);
      return { previous };
    },
    onError: (_e, _next, ctx) => {
      setStatus(ctx?.previous ?? null);
      setError("Could not save — try again.");
    },
    onSuccess: (data) => {
      setStatus(data.status as Status);
      void queryClient.invalidateQueries({ queryKey: ["get", "/api/digest"] });
      void queryClient.invalidateQueries({ queryKey: ["get", "/api/jobs/{job_id}"] });
    },
  });

  return (
    <div>
      <div className="mb-2 text-sm text-gray-600">Current: {status ?? "none"}</div>
      <div className="flex flex-wrap gap-2">
        {STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => mutation.mutate(s)}
            disabled={mutation.isPending}
            className={`rounded border px-3 py-1 text-sm ${status === s ? "border-gray-900 bg-gray-900 text-white" : "border-gray-300 bg-white"}`}
          >
            {LABELS[s]}
          </button>
        ))}
      </div>
      {error && (
        <div role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}
