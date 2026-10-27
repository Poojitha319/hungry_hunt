import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, delay, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import { StatusForm } from "./StatusForm";

const API = "http://api.test";

describe("StatusForm", () => {
  it("updates the status optimistically and keeps it when the server confirms", async () => {
    let body: unknown;
    server.use(
      http.post(`${API}/api/jobs/7/status`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ job_id: 7, status: "applied", applied_at: "2026-10-07T02:00:00Z", notes: "", updated_at: "2026-10-07T02:00:00Z" });
      }),
    );
    renderWithProviders(<StatusForm jobId={7} current={null} apiUrl={API} token="tok" />);
    await userEvent.click(screen.getByRole("button", { name: /applied/i }));
    expect(screen.getByText(/current: applied/i)).toBeInTheDocument();
    await waitFor(() => expect(body).toEqual({ status: "applied", notes: null }));
    expect(screen.getByText(/current: applied/i)).toBeInTheDocument();
  });

  it("rolls back and shows an error when the server fails", async () => {
    server.use(
      http.post(`${API}/api/jobs/7/status`, async () => {
        await delay(50);
        return HttpResponse.json({ detail: "boom" }, { status: 500 });
      }),
    );
    renderWithProviders(<StatusForm jobId={7} current="callback" apiUrl={API} token="tok" />);
    await userEvent.click(screen.getByRole("button", { name: /rejected/i }));
    expect(screen.getByText(/current: rejected/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/current: callback/i)).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/could not save/i);
  });

  it("sends the bearer token", async () => {
    let auth: string | null = null;
    server.use(
      http.post(`${API}/api/jobs/7/status`, ({ request }) => {
        auth = request.headers.get("authorization");
        return HttpResponse.json({ job_id: 7, status: "skipped", applied_at: null, notes: "", updated_at: "2026-10-07T02:00:00Z" });
      }),
    );
    renderWithProviders(<StatusForm jobId={7} current={null} apiUrl={API} token="tok" />);
    await userEvent.click(screen.getByRole("button", { name: /skip/i }));
    await waitFor(() => expect(auth).toBe("Bearer tok"));
  });
});
