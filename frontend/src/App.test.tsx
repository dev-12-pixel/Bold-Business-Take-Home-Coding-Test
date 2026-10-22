import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const recruiters = [
  { recruiter_id: "R-101", full_name: "Dana Whitmore", is_admin: true, regions: [] },
  {
    recruiter_id: "R-102",
    full_name: "Caleb Nguyen",
    is_admin: false,
    regions: ["US-MW", "US-NE"],
  },
  {
    recruiter_id: "R-103",
    full_name: "Marisol Vega",
    is_admin: false,
    regions: ["CO-BOG", "PH-MNL"],
  },
];

const candidate = (id: string, first: string, last: string, region: string) => ({
  candidate_id: id,
  first_name: first,
  last_name: last,
  email: `${id}@example.com`,
  region_code: region,
  desired_role: "QA Engineer",
  status: "on_hold",
  applied_date: "2026-05-25",
});

const byRecruiter: Record<string, unknown[]> = {
  "R-102": [candidate("C-1001", "Alicia", "Trent", "US-MW")],
  "R-103": [candidate("C-1008", "Nguyễn", "Thị Hoa", "PH-MNL")],
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/v1/recruiters") return Response.json(recruiters);
    const id = new Headers(init?.headers).get("X-Recruiter-Id") ?? "";
    if (!(id in byRecruiter))
      return Response.json({ detail: "unknown recruiter" }, { status: 403 });
    const items = byRecruiter[id];
    return Response.json({ items, total: items.length, page: 1, page_size: 25 });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const candidateCalls = () =>
  fetchMock.mock.calls.filter(([url]) => String(url).startsWith("/api/v1/candidates?"));

describe("recruiter view", () => {
  it("starts as Caleb and sends his id", async () => {
    render(<App />);
    expect(await screen.findByText("Alicia Trent")).toBeTruthy();
    const [, init] = candidateCalls().at(-1)!;
    expect(new Headers(init.headers).get("X-Recruiter-Id")).toBe("R-102");
  });

  it("switching recruiter changes the header and the data", async () => {
    render(<App />);
    await screen.findByText("Alicia Trent");

    fireEvent.change(screen.getByLabelText("Recruiter"), { target: { value: "R-103" } });

    expect(await screen.findByText("Nguyễn Thị Hoa")).toBeTruthy();
    expect(screen.queryByText("Alicia Trent")).toBeNull();
    const [, init] = candidateCalls().at(-1)!;
    expect(new Headers(init.headers).get("X-Recruiter-Id")).toBe("R-103");
  });

  it("status filter is sent as a query parameter", async () => {
    render(<App />);
    await screen.findByText("Alicia Trent");

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "on_hold" } });

    await waitFor(() => expect(String(candidateCalls().at(-1)![0])).toContain("status=on_hold"));
    expect(screen.getAllByText("On hold").length).toBeGreaterThan(0);
  });

  it("shows the API error instead of an empty table", async () => {
    render(<App />);
    await screen.findByText("Alicia Trent");

    fireEvent.change(screen.getByLabelText("Recruiter"), { target: { value: "R-101" } });

    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "403: unknown recruiter",
    );
  });
});
