import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Loader2, Sparkles } from "lucide-react";
import { api } from "../api";
import { ExplanationPanel } from "../components/ExplanationPanel";
import { RiskBadge } from "../components/RiskBadge";
import type { FileRow, PredictResponse, RepoStats, RiskLevel } from "../types";

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel/60 p-3">
      <div className="text-xs uppercase tracking-widest text-mute">{label}</div>
      <div className="mt-1 text-xl font-semibold font-mono">{value}</div>
    </div>
  );
}

export function RepoDetailPage() {
  const { repoId } = useParams();
  const id = Number(repoId);
  const [stats, setStats] = useState<RepoStats | null>(null);
  const [files, setFiles] = useState<FileRow[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [riskLevel, setRiskLevel] = useState<RiskLevel | "">("");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<FileRow | null>(null);
  const [explain, setExplain] = useState<PredictResponse | null>(null);
  const [explaining, setExplaining] = useState(false);

  const limit = 40;

  function loadFiles(nextPage = page, q = search, risk = riskLevel) {
    setLoading(true);
    api
      .files(id, {
        search: q,
        riskLevel: risk,
        sortBy: "risk",
        limit,
        offset: nextPage * limit,
      })
      .then((res) => {
        setFiles(res.files);
        setTotal(res.total);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!id) return;
    api.repoStats(id).then(setStats).catch((err) => setError(err.message));
    loadFiles(0);
    setPage(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function runEnsemble() {
    setScoring(true);
    setError("");
    setMessage("Scoring files with 5 models + SHAP... Small repos ~30s, larger ones a few minutes.");
    try {
      const res = await api.savePredictions(id, 500);
      setMessage(`✅ Saved ${res.files_analyzed} predictions for ${res.repo}.`);
      loadFiles(0);
      setPage(0);
      api.repoStats(id).then(setStats).catch(() => undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scoring failed");
      setMessage("");
    } finally {
      setScoring(false);
    }
  }

  async function openFile(file: FileRow) {
    setSelected(file);
    setExplain(null);
    setExplaining(true);
    try {
      const result = await api.explainFile(id, file.file_path);
      setExplain(result);
      setFiles((prev) =>
        prev.map((row) =>
          row.file_path === file.file_path
            ? { ...row, risk_score: result.risk_score, risk_level: result.risk_level }
            : row,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Explain failed");
    } finally {
      setExplaining(false);
    }
  }

  const pages = Math.max(1, Math.ceil(total / limit));

  const highCount = files.filter((f) => f.risk_level === "high").length;
  const medCount = files.filter((f) => f.risk_level === "medium").length;
  const scoredCount = files.filter((f) => f.risk_score != null).length;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">{stats?.repo_name || "Repository"}</h1>
          <p className="mt-2 text-mute text-sm">
            {stats
              ? `${stats.files_with_metrics.toLocaleString()} files · ${stats.buggy_files_szz.toLocaleString()} SZZ-labeled buggy`
              : "Loading stats..."}
          </p>
        </div>
        <button
          onClick={runEnsemble}
          disabled={scoring}
          className="rounded-xl bg-sky-400/15 border border-sky-300/30 px-4 py-2 text-sm hover:bg-sky-400/25 disabled:opacity-50 inline-flex items-center gap-2"
        >
          {scoring ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          Score files (ensemble)
        </button>
      </header>

      {/* Repo stats cards */}
      {stats && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <StatCard label="Total files" value={stats.total_files.toLocaleString()} />
          <StatCard label="With metrics" value={stats.files_with_metrics.toLocaleString()} />
          <StatCard label="Commits" value={stats.total_commits.toLocaleString()} />
          <StatCard label="Avg LOC" value={stats.avg_loc?.toFixed(0) ?? "—"} />
          <StatCard label="Avg complexity" value={stats.avg_complexity?.toFixed(1) ?? "—"} />
          <StatCard label="Avg churn" value={stats.avg_churn?.toFixed(0) ?? "—"} />
        </div>
      )}

      {message && <div className="text-sm text-accent">{message}</div>}
      {error && <div className="text-sm text-high">{error}</div>}

      {/* Quick stats for current page */}
      <div className="flex items-center gap-4 text-xs text-mute">
        <span>{scoredCount}/{files.length} scored on this page</span>
        {highCount > 0 && <span className="text-high">● {highCount} high risk</span>}
        {medCount > 0 && <span className="text-yellow-400">● {medCount} medium</span>}
      </div>

      <div className="flex flex-wrap gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              setPage(0);
              loadFiles(0, search, riskLevel);
            }
          }}
          placeholder="Search path, e.g. Validator.ts"
          className="rounded-xl border border-line bg-panel px-3 py-2 text-sm w-72 outline-none focus:border-accent"
        />
        <select
          value={riskLevel}
          onChange={(e) => {
            const next = e.target.value as RiskLevel | "";
            setRiskLevel(next);
            setPage(0);
            loadFiles(0, search, next);
          }}
          className="rounded-xl border border-line bg-panel px-3 py-2 text-sm"
        >
          <option value="">All risk levels</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <button
          onClick={() => {
            setPage(0);
            loadFiles(0, search, riskLevel);
          }}
          className="rounded-xl border border-line px-3 py-2 text-sm hover:bg-panel-2"
        >
          Apply
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-line">
        <table className="w-full text-sm">
          <thead className="bg-panel-2 text-mute text-left">
            <tr>
              <th className="px-4 py-3 font-medium">File</th>
              <th className="px-4 py-3 font-medium">Risk</th>
              <th className="px-4 py-3 font-medium">LOC</th>
              <th className="px-4 py-3 font-medium">Complexity</th>
              <th className="px-4 py-3 font-medium">Authors</th>
              <th className="px-4 py-3 font-medium">Churn</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-mute">
                  <Loader2 className="h-5 w-5 animate-spin inline mr-2" />
                  Loading files...
                </td>
              </tr>
            ) : files.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-mute">
                  No files. Score the repo first, or clear filters.
                </td>
              </tr>
            ) : (
              files.map((file) => (
                <tr
                  key={file.file_path}
                  onClick={() => openFile(file)}
                  className="border-t border-line hover:bg-panel-2/80 cursor-pointer"
                >
                  <td className="px-4 py-3 font-mono text-xs max-w-xl truncate">{file.file_path}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <RiskBadge level={file.risk_level} />
                      {file.risk_score != null ? (
                        <span className="font-mono text-xs text-mute">{file.risk_score.toFixed(3)}</span>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono">{file.loc ?? "—"}</td>
                  <td className="px-4 py-3 font-mono">{file.cyclomatic_complexity ?? "—"}</td>
                  <td className="px-4 py-3 font-mono">{file.unique_authors ?? "—"}</td>
                  <td className="px-4 py-3 font-mono">{file.churn ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm text-mute">
        <span>
          {total.toLocaleString()} files · page {page + 1} / {pages}
        </span>
        <div className="flex gap-2">
          <button
            disabled={page === 0}
            onClick={() => {
              const next = Math.max(0, page - 1);
              setPage(next);
              loadFiles(next);
            }}
            className="rounded-lg border border-line px-3 py-1 disabled:opacity-40"
          >
            Prev
          </button>
          <button
            disabled={page + 1 >= pages}
            onClick={() => {
              const next = page + 1;
              setPage(next);
              loadFiles(next);
            }}
            className="rounded-lg border border-line px-3 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>

      {/* Explanation side panel */}
      <Dialog.Root open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/60 z-40" />
          <Dialog.Content className="fixed right-0 top-0 h-full w-full max-w-xl overflow-y-auto border-l border-line bg-ink p-6 shadow-2xl z-50">
            <Dialog.Title className="text-lg font-medium">File analysis</Dialog.Title>
            <Dialog.Description className="mt-1 text-xs font-mono text-mute break-all">
              {selected?.file_path}
            </Dialog.Description>

            {explaining ? (
              <div className="mt-8 flex items-center gap-2 text-mute">
                <Loader2 className="h-4 w-4 animate-spin" />
                Running the ensemble, computing SHAP values and writing the explanation...
              </div>
            ) : null}

            {explain ? <ExplanationPanel explain={explain} selected={selected} /> : null}

            <button
              onClick={() => setSelected(null)}
              className="mt-8 rounded-xl border border-line px-4 py-2 text-sm hover:bg-panel-2"
            >
              Close
            </button>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
