import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";

export function renderWithProviders(ui: ReactElement, { route = "/" } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

export const job = {
  job_id: 7,
  company: "Hevo Data",
  tier: "mid",
  title: "SDE I",
  location_raw: "Bangalore",
  posted_age_days: 1,
  score: 88,
  verdict: "apply",
  reason: "Strong Python/FastAPI overlap.",
  years_evidence: "0-2 years of experience with Python.",
  url: "https://jobs.lever.co/hevodata/abc",
  review_url: "https://ui/job/7?t=x",
  is_new: true,
  company_velocity: 0,
  recently_funded: false,
};
