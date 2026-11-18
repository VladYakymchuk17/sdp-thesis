import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import type { DashboardSummary, EnsembleInfo, RepoInfo } from "../types";

function Card({
  label,
  value,
  hint,
  color,
}: {
  label: string;
  value: string;
  hint?: string;
  color?: string;
}) {
  return (
    <div className="rounded-2xl border border-line bg-panel/80 p-5">
      <div className="text-xs uppercase tracking-widest text-mute">{label}</div>
      <div className={`mt-2 text-3xl font-semibold font-mono ${color || ""}`}>{value}</div>
      {hint ? <div className="mt-2 text-xs text-mute">{hint}</div> : null}
    </div>
  );
}

function fmt(n?: number) {
  if (n == null) return "—";
  return n.toLocaleString();
}

const PIE_COLORS = { high: "#fb7185", medium: "#fbbf24", low: "#34d399", none: "#475569" };

export function OverviewPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [ensemble, setEnsemble] = useState<EnsembleInfo | null>(null);
  const [repos, setRepos] = useState<RepoInfo[]>([]);
  const [error, setError] = useState("");
  const [health, setHealth] = useState("checking");

  useEffect(() => {
    Promise.all([api.health(), api.summary(), api.ensemble(), api.repos()])
      .then(([h, s, e, r]) => {
        setHealth(h.status);
        setSummary(s);
        setEnsemble(e);
        setRepos(r);
      })
      .catch((err) => {
        setHealth("down");
        setError(err.message || "Cannot reach ML service on port 8000.");
      });
  }, []);

  const chartData = useMemo(
    () =>
      (ensemble?.models || []).map((m) => ({
        name: m.name.replaceAll("_", " "),
        f1: Number((m.metrics.f1 ?? 0).toFixed(3)),
        recall: Number((m.metrics.recall ?? 0).toFixed(3)),
        precision: Number((m.metrics.precision ?? 0).toFixed(3)),
      })),
    [ensemble],
  );

  const riskPieData = useMemo(() => {
    if (!summary) return [];
    const notScored = Math.max(0, (summary.files_analyzed || 0) - (summary.predictions_saved || 0));
    return [
      { name: "High risk", value: summary.high_risk_files || 0, fill: PIE_COLORS.high },
      { name: "Medium risk", value: summary.medium_risk_files || 0, fill: PIE_COLORS.medium },
      { name: "Low risk", value: summary.low_risk_files || 0, fill: PIE_COLORS.low },
      { name: "Not scored", value: notScored, fill: PIE_COLORS.none },
    ].filter((d) => d.value > 0);
  }, [summary]);

  const coveragePct = summary
    ? summary.files_analyzed
      ? Math.round(((summary.predictions_saved || 0) / summary.files_analyzed) * 100)
      : 0
    : 0;

  return (
    <div className="space-y-8 max-w-6xl">
      <header>
        <h1 className="text-3xl font-semibold">Defect prediction overview</h1>
        <p className="mt-2 text-mute">
          Five models vote on each TypeScript file. Open a repository, score files, then click a row for SHAP + LLM
          explanation.
        </p>
        <div className="mt-3 text-sm">
          ML service:{" "}
          <span className={health === "ok" ? "text-low" : "text-high"}>
            {health === "ok" ? "● online" : `● ${health}`}
          </span>
        </div>
      </header>

      {error ? (
        <div className="rounded-xl border border-rose-400/30 bg-rose-500/10 p-4 text-sm">
          {error} Start FastAPI with{" "}
          <code className="font-mono">python -m uvicorn app.main:app --port 8000</code> in
          <code className="font-mono"> services/ml-service</code>.
        </div>
      ) : null}

      {/* Summary cards */}
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card label="Repositories" value={fmt(summary?.repositories)} hint="Mined TypeScript projects" />
        <Card label="Files with metrics" value={fmt(summary?.files_analyzed)} />
        <Card label="SZZ buggy files" value={fmt(summary?.buggy_files_szz)} hint="Bug-introducing per SZZ" />
        <Card
          label="Ensemble"
          value={`${summary?.ensemble_models ?? 0} models`}
          hint={(summary?.model_names || []).join(" · ")}
        />
      </section>

      {/* Extra stats row */}
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card label="Total commits mined" value={fmt(summary?.total_commits)} />
        <Card
          label="Predictions saved"
          value={fmt(summary?.predictions_saved)}
          hint={`${coveragePct}% coverage`}
        />
        <Card
          label="High-risk files"
          value={fmt(summary?.high_risk_files)}
          color="text-high"
          hint="risk_score ≥ 0.7"
        />
        <Card
          label="Coverage"
          value={`${coveragePct}%`}
          hint={`${fmt(summary?.predictions_saved)} / ${fmt(summary?.files_analyzed)} files`}
        />
      </section>

      {/* Risk distribution pie + model chart side-by-side */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Risk pie */}
        <section className="rounded-2xl border border-line bg-panel/80 p-5">
          <h2 className="text-lg font-medium mb-4">Risk distribution</h2>
          {riskPieData.length > 0 ? (
            <div className="h-64 flex items-center justify-center">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={riskPieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={90}
                    paddingAngle={3}
                    dataKey="value"
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    labelLine={false}
                  >
                    {riskPieData.map((entry, idx) => (
                      <Cell key={idx} fill={entry.fill} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      background: "#101826",
                      border: "1px solid #243049",
                      borderRadius: 12,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-mute text-sm">
              Score some files first to see the distribution.
            </div>
          )}
        </section>

        {/* F1 chart */}
        <section className="rounded-2xl border border-line bg-panel/80 p-5">
          <h2 className="text-lg font-medium mb-4">Model performance (test set)</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ left: 8, right: 8 }}>
                <CartesianGrid stroke="#243049" vertical={false} />
                <XAxis
                  dataKey="name"
                  stroke="#8b9bb8"
                  tick={{ fontSize: 10 }}
                  interval={0}
                  angle={-15}
                  textAnchor="end"
                  height={50}
                />
                <YAxis stroke="#8b9bb8" domain={[0, 1]} tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    background: "#101826",
                    border: "1px solid #243049",
                    borderRadius: 12,
                  }}
                />
                <Legend />
                <Bar dataKey="f1" fill="#7dd3fc" radius={[4, 4, 0, 0]} />
                <Bar dataKey="recall" fill="#34d399" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      {/* Repositories section */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium">Repositories</h2>
          <Link to="/repos" className="text-sm text-accent hover:underline">
            See all →
          </Link>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {repos.slice(0, 6).map((repo) => (
            <Link
              key={repo.id}
              to={`/repos/${repo.id}`}
              className="rounded-2xl border border-line bg-panel/70 p-4 hover:border-accent/40 transition"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium">{repo.name}</div>
                <span className={`text-xs capitalize ${repo.status === "done" || repo.status === "mined" ? "text-low" : repo.status === "pending" ? "text-yellow-400" : "text-mute"}`}>
                  {repo.status}
                </span>
              </div>
              <div className="mt-2 text-xs text-mute font-mono truncate">{repo.url}</div>
              <div className="mt-3 flex items-center gap-4 text-sm text-mute">
                <span>{repo.total_commits.toLocaleString()} commits</span>
                <span className="text-xs">branch: {repo.branch}</span>
              </div>
            </Link>
          ))}
        </div>
        {repos.length > 6 && (
          <div className="mt-3 text-center">
            <Link to="/repos" className="text-sm text-accent hover:underline">
              +{repos.length - 6} more
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
