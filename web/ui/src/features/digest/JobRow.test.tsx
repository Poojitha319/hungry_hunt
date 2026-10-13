import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { job, renderWithProviders } from "../../test/render";
import { JobRow } from "./JobRow";

describe("JobRow", () => {
  it("shows the quoted years evidence, reason, score and verdict", () => {
    renderWithProviders(<JobRow job={job} />);
    expect(screen.getByText(/0-2 years of experience with Python/)).toBeInTheDocument();
    expect(screen.getByText("Strong Python/FastAPI overlap.")).toBeInTheDocument();
    expect(screen.getByText("88")).toBeInTheDocument();
    expect(screen.getByText("apply")).toBeInTheDocument();
  });

  it("links Apply to the company's own posting and Review to the job page", () => {
    renderWithProviders(<JobRow job={job} />);
    expect(screen.getByRole("link", { name: /apply/i })).toHaveAttribute("href", "https://jobs.lever.co/hevodata/abc");
    expect(screen.getByRole("link", { name: /review/i })).toHaveAttribute("href", "/job/7");
  });

  it("marks unscored jobs instead of showing a score", () => {
    renderWithProviders(<JobRow job={{ ...job, score: null, verdict: null, reason: null }} />);
    expect(screen.getByText(/unscored/i)).toBeInTheDocument();
    expect(screen.queryByText("88")).not.toBeInTheDocument();
  });
});
