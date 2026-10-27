import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../../test/server";
import { renderWithProviders } from "../../test/render";
import { AddCompanyBox } from "./AddCompanyBox";

const API = "http://api.test";
const row = { id: 9, name: "acme", ats: "lever", slug: "acme", board_url: "https://jobs.lever.co/acme", kind: "unknown", tier: "unknown", status: "target", notes: "", last_ok: null };

describe("AddCompanyBox", () => {
  it("posts the pasted board and reports what it became", async () => {
    let body: unknown;
    server.use(http.post(`${API}/api/companies`, async ({ request }) => { body = await request.json(); return HttpResponse.json(row, { status: 201 }); }));
    renderWithProviders(<AddCompanyBox apiUrl={API} token="tok" />);
    await userEvent.type(screen.getByRole("textbox", { name: /board/i }), "https://jobs.lever.co/acme");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /status/i }), "target");
    await userEvent.click(screen.getByRole("button", { name: /add/i }));
    await waitFor(() => expect(body).toEqual({ text: "https://jobs.lever.co/acme", status: "target", notes: null }));
    expect(await screen.findByRole("status")).toHaveTextContent(/added acme \(lever\)/i);
  });

  it("explains when the text is not a board", async () => {
    server.use(http.post(`${API}/api/companies`, () => HttpResponse.json({ detail: "not a Greenhouse/Lever/Ashby board: x" }, { status: 422 })));
    renderWithProviders(<AddCompanyBox apiUrl={API} token="tok" />);
    await userEvent.type(screen.getByRole("textbox", { name: /board/i }), "x");
    await userEvent.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not a .* board/i);
  });
});
