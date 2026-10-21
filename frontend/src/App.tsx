import { useEffect, useState } from "react";
import {
  Candidate,
  fetchCandidates,
  fetchRecruiters,
  PAGE_SIZE,
  Page,
  Recruiter,
  Status,
  STATUSES,
  statusLabel,
} from "./api";

const DEFAULT_RECRUITER = "R-102"; // Caleb: a scoped recruiter makes the RLS visible at once.
const SEARCH_DEBOUNCE_MS = 300;

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export default function App() {
  const [recruiters, setRecruiters] = useState<Recruiter[]>([]);
  const [recruiterId, setRecruiterId] = useState(DEFAULT_RECRUITER);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<Status | "">("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page<Candidate> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const debouncedSearch = useDebounced(search, SEARCH_DEBOUNCE_MS);

  useEffect(() => {
    const controller = new AbortController();
    fetchRecruiters(controller.signal)
      .then(setRecruiters)
      .catch((e: Error) => e.name !== "AbortError" && setError(e.message));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    // Aborting the previous request means a slow response for the old recruiter
    // can never overwrite the table after a switch.
    const controller = new AbortController();
    setLoading(true);
    fetchCandidates(recruiterId, { search: debouncedSearch, status, page }, controller.signal)
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        setData(null);
        setError(e.message);
      })
      .finally(() => !controller.signal.aborted && setLoading(false));
    return () => controller.abort();
  }, [recruiterId, debouncedSearch, status, page]);

  useEffect(() => setPage(1), [recruiterId, debouncedSearch, status]);

  const pageCount = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const current = recruiters.find((r) => r.recruiter_id === recruiterId);

  return (
    <main>
      <h1>TechForce candidates</h1>

      <div className="controls">
        <label>
          Recruiter{" "}
          <select value={recruiterId} onChange={(e) => setRecruiterId(e.target.value)}>
            {recruiters.length === 0 && <option value={recruiterId}>{recruiterId}</option>}
            {recruiters.map((r) => (
              <option key={r.recruiter_id} value={r.recruiter_id}>
                {r.full_name} ({r.recruiter_id})
              </option>
            ))}
          </select>
        </label>
        <label>
          Search{" "}
          <input
            type="search"
            value={search}
            placeholder="name, email or role"
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label>
          Status{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value as Status | "")}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {current && (
        <p className="scope">
          Scope: {current.is_admin ? "all regions (admin)" : current.regions.join(", ")}
        </p>
      )}

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <table aria-busy={loading}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Region</th>
            <th>Role</th>
            <th>Status</th>
            <th>Applied</th>
          </tr>
        </thead>
        <tbody>
          {data?.items.map((c) => (
            <tr key={c.candidate_id}>
              <td>{`${c.first_name} ${c.last_name}`}</td>
              <td className="muted">{c.email}</td>
              <td>
                <span className="region">{c.region_code}</span>
              </td>
              <td className="muted">{c.desired_role ?? ""}</td>
              <td>
                <span className={`pill ${c.status}`}>{statusLabel(c.status)}</span>
              </td>
              <td className="date">{c.applied_date}</td>
            </tr>
          ))}
          {data && data.items.length === 0 && (
            <tr>
              <td colSpan={6} className="empty">
                No candidates match.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {data && (
        <div className="pager">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Prev
          </button>
          <span>
            Page {page} of {pageCount} ({data.total} total)
          </span>
          <button disabled={page >= pageCount} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      )}
    </main>
  );
}
