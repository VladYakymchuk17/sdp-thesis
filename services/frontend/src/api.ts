import { getToken } from "./auth";
import type {
  DashboardSummary,
  EnsembleInfo,
  FilesResponse,
  Job,
  PipelineStage,
  PredictResponse,
  RepoInfo,
  RepoStats,
  RiskLevel,
} from "./types";

const BASE = "";

function headers(): Record<string, string> {
  const h: Record<string, string> = {};
  const token = getToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: headers() });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const b = await res.json();
      detail = b.detail || JSON.stringify(b);
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

async function sendJson<T>(path: string, method = "POST"): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method, headers: headers() });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => getJson<{ status: string; service: string }>("/health"),
  summary: () => getJson<DashboardSummary>("/api/v1/dashboard-summary"),
  ensemble: () => getJson<EnsembleInfo>("/api/v1/ensemble-info"),
  repos: () => getJson<RepoInfo[]>("/api/v1/repositories"),
  repoStats: (id: number) => getJson<RepoStats>(`/api/v1/repositories/${id}/stats`),
  files: (
    id: number,
    opts: {
      search?: string;
      riskLevel?: RiskLevel | "";
      sortBy?: string;
      limit?: number;
      offset?: number;
      hasPrediction?: boolean;
    } = {},
  ) => {
    const q = new URLSearchParams();
    if (opts.search) q.set("search", opts.search);
    if (opts.riskLevel) q.set("risk_level", opts.riskLevel);
    if (opts.sortBy) q.set("sort_by", opts.sortBy);
    if (opts.limit != null) q.set("limit", String(opts.limit));
    if (opts.offset != null) q.set("offset", String(opts.offset));
    if (opts.hasPrediction) q.set("has_prediction", "true");
    return getJson<FilesResponse>(`/api/v1/repositories/${id}/files?${q.toString()}`);
  },
  explainFile: (id: number, path: string) =>
    getJson<PredictResponse>(
      `/api/v1/analyze/${id}/file?path=${encodeURIComponent(path)}`,
    ),
  savePredictions: (id: number, limit = 80) =>
    sendJson<{ status: string; repo: string; files_analyzed: number }>(
      `/api/v1/analyze/${id}/save?limit=${limit}`,
    ),
  submitRepo: (repoUrl: string, branch = "main") =>
    postJson<{ status: string; repo_id: number | null; message: string }>(
      "/api/v1/submit-repo",
      { repo_url: repoUrl, branch },
    ),
  startFullAnalysis: (opts: {
    repoUrl: string;
    branch?: string;
    sinceDays?: number | null;
    scoreLimit?: number;
  }) =>
    postJson<Job>("/api/v1/jobs/analyze-full", {
      repo_url: opts.repoUrl,
      branch: opts.branch || "main",
      since_days: opts.sinceDays === undefined ? 730 : opts.sinceDays,
      score_limit: opts.scoreLimit ?? 500,
    }),
  jobs: (limit = 20) => getJson<Job[]>(`/api/v1/jobs?limit=${limit}`),
  job: (id: number) => getJson<Job>(`/api/v1/jobs/${id}`),
  cancelJob: (id: number) => sendJson<Job>(`/api/v1/jobs/${id}/cancel`),
  pipelineStages: () => getJson<{ stages: PipelineStage[] }>("/api/v1/pipeline-stages"),
  login: (username: string, password: string) =>
    postJson<{ token: string; username: string; role: string; expires_in: number }>(
      "/api/v1/auth/login",
      { username, password },
    ),
  me: () => getJson<{ username: string; role: string }>("/api/v1/auth/me"),
};
