import type { components } from "../../shared/api/schema";

type Coverage = components["schemas"]["Coverage"];
type Pipeline = Record<string, Record<string, number>> | undefined;

function Pipeline({ pipeline }: { pipeline: Pipeline }) {
  if (!pipeline?.week) return null;
  const line = (p: Record<string, number>) => `${p.applied} applied · ${p.test} test · ${p.interview} interview · ${p.rejected} rejected`;
  return (
    <section className="mt-6 border-t border-gray-200 pt-3 text-sm text-gray-700">
      <strong>Your pipeline</strong> <span className="text-gray-500">(from hiring mail forwarded to the agent)</span>
      <div>Last 7 days: {line(pipeline.week)}</div>
      <div>All time: {line(pipeline.total)}</div>
    </section>
  );
}

export function CoverageFooter({ coverage: c, pipeline }: { coverage: Coverage; pipeline?: Pipeline }) {
  return (
    <>
    <Pipeline pipeline={pipeline} />
    <footer className="mt-6 border-t border-gray-200 pt-3 text-xs leading-relaxed text-gray-600">
      <strong>Coverage</strong>
      <br />
      {c.stats_available ? (
        <>
          Boards: {c.boards_total} fetched · {c.boards_ok} ok · {c.boards_failed} failed · {c.boards_skipped} skipped (dormant or dead, checked weekly) · Lever boards: {c.lever_boards}
          <br />
          Jobs: {c.jobs_seen} seen · {c.jobs_stored} stored · {c.jobs_new} new · {c.jobs_closed} closed · descriptions fetched: {c.descriptions_fetched}
          <br />
          Gemini: {c.gemini_calls} calls
          {c.quota_hit && <span className="text-amber-700"> · quota hit — {c.unscored} left unscored, scored tomorrow</span>}
          <br />
        </>
      ) : (
        <>
          Pipeline stats unavailable for today.
          <br />
        </>
      )}
      {c.blind_spots?.length ? <>Blind spots (hiring systems we can't read yet): {c.blind_spots.join(", ")}<br /></> : null}
      {c.stale_targets?.length ? <>Stale boards (no successful fetch in 3 days): {c.stale_targets.join(", ")}<br /></> : null}
      {c.service_auto ? <>Companies auto-classified as service firms and hidden: {c.service_auto}<br /></> : null}
      {c.stale_hidden ? <>{c.stale_hidden} hidden as stale (posted too long ago)<br /></> : null}
      {c.funded_unwatched?.length ? <>Recently funded, not watched yet: {c.funded_unwatched.join(", ")}<br /></> : null}
    </footer>
    </>
  );
}
