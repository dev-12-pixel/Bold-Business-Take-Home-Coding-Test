export const STATUSES = ["active", "screening", "interviewing", "withdrawn", "on_hold"] as const;
export type Status = (typeof STATUSES)[number];

export const PAGE_SIZE = 25;

export interface Recruiter {
  recruiter_id: string;
  full_name: string;
  is_admin: boolean;
  regions: string[];
}

export interface Candidate {
  candidate_id: string;
  first_name: string;
  last_name: string;
  email: string;
  region_code: string;
  desired_role: string | null;
  status: Status;
  applied_date: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface CandidateQuery {
  search: string;
  status: Status | "";
  page: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    detail: string,
  ) {
    super(`${status}: ${detail}`);
  }
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : response.statusText;
    throw new ApiError(response.status, detail);
  }
  return body as T;
}

export function fetchRecruiters(signal?: AbortSignal): Promise<Recruiter[]> {
  return getJson("/api/v1/recruiters", { signal });
}

export function fetchCandidates(
  recruiterId: string,
  query: CandidateQuery,
  signal?: AbortSignal,
): Promise<Page<Candidate>> {
  const params = new URLSearchParams({ page: String(query.page), page_size: String(PAGE_SIZE) });
  if (query.search.trim()) params.set("search", query.search.trim());
  if (query.status) params.set("status", query.status);
  return getJson(`/api/v1/candidates?${params}`, {
    headers: { "X-Recruiter-Id": recruiterId },
    signal,
  });
}

export function statusLabel(status: Status): string {
  const text = status.replace("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
