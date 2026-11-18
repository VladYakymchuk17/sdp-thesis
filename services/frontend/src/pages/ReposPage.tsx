import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, Loader2, Play } from "lucide-react";
import { api } from "../api";
import type { RepoInfo } from "../types";

export function ReposPage() {
  const navigate = useNavigate();
  const [repos, setRepos] = useState<RepoInfo[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [submitting, setSubmitting] = useState(false);

  function loadRepos() {
    api.repos().then(setRepos).catch((err) => setError(err.message));
  }

  useEffect(() => {
    loadRepos();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!repoUrl.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      await api.startFullAnalysis({
        repoUrl: repoUrl.trim(),
        branch: branch.trim() || "main",
      });
      // The job page is where progress lives, so follow the run there.
      navigate("/analyze");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the analysis");
    } finally {
      setSubmitting(false);
    }
  }

  const statusColor = (s: string) => {
    if (s === "analyzed" || s === "done" || s === "mined") return "text-low";
    if (s === "pending" || s === "partial") return "text-yellow-400";
    if (s === "error") return "text-high";
    return "text-mute";
  };

  return (
    <div className="max-w-5xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Repositories</h1>
          <p className="mt-2 text-mute">
            All registered TypeScript projects. Click a repo to explore its files and run predictions.
          </p>
        </div>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="rounded-xl bg-accent/20 border border-accent/40 px-4 py-2 text-sm hover:bg-accent/30 inline-flex items-center gap-2 transition"
        >
          <Plus className="h-4 w-4" />
          Add repository
        </button>
      </header>

      {showAdd && (
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-accent/30 bg-panel/80 p-5 space-y-4"
        >
          <h3 className="text-sm font-medium">Run the full pipeline on a GitHub repository</h3>
          <div className="flex flex-wrap gap-3">
            <div className="flex-1 min-w-[300px]">
              <label className="block text-xs uppercase tracking-widest text-mute mb-1">Repository URL</label>
              <input
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/user/repo"
                className="w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-accent"
                autoFocus
              />
            </div>
            <div className="w-36">
              <label className="block text-xs uppercase tracking-widest text-mute mb-1">Branch</label>
              <input
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                placeholder="main"
                className="w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-accent"
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting || !repoUrl.trim()}
              className="rounded-xl bg-accent/20 border border-accent/40 px-4 py-2 text-sm hover:bg-accent/30 disabled:opacity-50 inline-flex items-center gap-2 transition"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Run full analysis
            </button>
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="rounded-xl border border-line px-4 py-2 text-sm hover:bg-panel-2 transition"
            >
              Cancel
            </button>
            <Link to="/analyze" className="text-xs text-accent hover:underline">
              more options
            </Link>
          </div>
          <p className="text-xs text-mute leading-relaxed">
            Clones the repository, mines its commit history, measures complexity, labels
            bug-introducing commits with SZZ and scores every file. You will be taken to the
            progress view.
          </p>
        </form>
      )}

      {error && <div className="text-high text-sm">{error}</div>}

      <div className="overflow-hidden rounded-2xl border border-line">
        <table className="w-full text-sm">
          <thead className="bg-panel-2 text-mute text-left">
            <tr>
              <th className="px-4 py-3 font-medium">Name</th>
              <th className="px-4 py-3 font-medium">Branch</th>
              <th className="px-4 py-3 font-medium">Commits</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {repos.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-mute">
                  No repositories registered yet. Add one above.
                </td>
              </tr>
            ) : (
              repos.map((repo) => (
                <tr key={repo.id} className="border-t border-line hover:bg-panel/80">
                  <td className="px-4 py-3">
                    <Link to={`/repos/${repo.id}`} className="text-accent hover:underline">
                      {repo.name}
                    </Link>
                    <div className="text-xs text-mute font-mono truncate max-w-md">{repo.url}</div>
                  </td>
                  <td className="px-4 py-3 font-mono text-mute">{repo.branch}</td>
                  <td className="px-4 py-3 font-mono">{repo.total_commits.toLocaleString()}</td>
                  <td className={`px-4 py-3 capitalize ${statusColor(repo.status)}`}>{repo.status}</td>
                  <td className="px-4 py-3">
                    <Link
                      to={`/repos/${repo.id}`}
                      className="rounded-lg border border-line px-3 py-1 text-xs hover:bg-panel-2 transition"
                    >
                      Open
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-mute">
        Total: {repos.length} repositories · Admin can see all repos
      </div>
    </div>
  );
}
