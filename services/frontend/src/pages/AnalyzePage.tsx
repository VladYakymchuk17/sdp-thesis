import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Play } from "lucide-react";
import { api } from "../api";
import { JobProgress } from "../components/JobProgress";
import type { Job, PipelineStage } from "../types";

const HISTORY_OPTIONS = [
  { label: "Last 1 year", value: 365 },
  { label: "Last 2 years", value: 730 },
  { label: "Last 5 years", value: 1825 },
  { label: "Full history", value: null },
];

export function AnalyzePage() {
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [sinceDays, setSinceDays] = useState<number | null>(730);
  const [scoreLimit, setScoreLimit] = useState(500);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.pipelineStages().then((r) => setStages(r.stages)).catch(() => undefined);
  }, []);

  // Poll while any job is still moving; stop once everything has settled.
  useEffect(() => {
    function tick() {
      api
        .jobs(10)
        .then((next) => {
          setJobs(next);
          const busy = next.some((j) => j.status === "running" || j.status === "queued");
          if (timer.current) window.clearTimeout(timer.current);
          timer.current = window.setTimeout(tick, busy ? 2000 : 15000);
        })
        .catch((err) => {
          setError(err.message);
          if (timer.current) window.clearTimeout(timer.current);
          timer.current = window.setTimeout(tick, 10000);
        });
    }
    tick();
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, []);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    if (!repoUrl.trim()) return;
    setStarting(true);
    setError("");
    try {
      const job = await api.startFullAnalysis({
        repoUrl: repoUrl.trim(),
        branch: branch.trim() || "main",
        sinceDays,
        scoreLimit,
      });
      setJobs((prev) => [job, ...prev.filter((j) => j.id !== job.id)]);
      setRepoUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the analysis");
    } finally {
      setStarting(false);
    }
  }

  async function cancel(id: number) {
    try {
      const updated = await api.cancelJob(id);
      setJobs((prev) => prev.map((j) => (j.id === id ? updated : j)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed");
    }
  }

  return (
    <div className="max-w-4xl space-y-8">
      <header>
        <h1 className="text-3xl font-semibold">Analyze a repository</h1>
        <p className="mt-2 text-mute">
          Point this at any public TypeScript repository and it will run the whole pipeline:
          clone, mine the commit history, measure complexity, label bug-introducing commits
          with SZZ, then score every file with the ensemble.
        </p>
      </header>

      <form onSubmit={start} className="rounded-2xl border border-line bg-panel/70 p-5 space-y-4">
        <div className="flex flex-wrap gap-3">
          <div className="flex-1 min-w-[280px]">
            <label className="block text-xs uppercase tracking-widest text-mute mb-1">
              Repository URL
            </label>
            <input
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/typestack/class-transformer"
              className="w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-accent"
            />
          </div>
          <div className="w-32">
            <label className="block text-xs uppercase tracking-widest text-mute mb-1">
              Branch
            </label>
            <input
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              placeholder="main"
              className="w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-accent"
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <div className="w-44">
            <label className="block text-xs uppercase tracking-widest text-mute mb-1">
              History depth
            </label>
            <select
              value={String(sinceDays)}
              onChange={(e) =>
                setSinceDays(e.target.value === "null" ? null : Number(e.target.value))
              }
              className="w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-accent"
            >
              {HISTORY_OPTIONS.map((opt) => (
                <option key={String(opt.value)} value={String(opt.value)}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div className="w-44">
            <label className="block text-xs uppercase tracking-widest text-mute mb-1">
              Files to score
            </label>
            <input
              type="number"
              min={1}
              max={5000}
              value={scoreLimit}
              onChange={(e) => setScoreLimit(Number(e.target.value))}
              className="w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-accent"
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={starting || !repoUrl.trim()}
            className="rounded-xl bg-accent/20 border border-accent/40 px-4 py-2 text-sm hover:bg-accent/30 disabled:opacity-50 inline-flex items-center gap-2 transition"
          >
            {starting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Run full analysis
          </button>
          <span className="text-xs text-mute">
            Mining is the slow stage — a mid-sized repo takes a few minutes.
          </span>
        </div>

        {error && (
          <div className="rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        )}

        <p className="text-xs text-mute leading-relaxed border-t border-line pt-3">
          Narrowing the history depth keeps the first run short; you can always re-run with
          the full history later. Cloning is cached, so a repeat run on the same repository
          skips straight to mining.
        </p>
      </form>

      <section className="space-y-4">
        <h2 className="text-lg font-medium">Recent runs</h2>
        {jobs.length === 0 ? (
          <div className="rounded-2xl border border-line bg-panel/50 p-8 text-center text-sm text-mute">
            No analysis runs yet. Submit a repository above to start one.
          </div>
        ) : (
          jobs.map((job) => (
            <div key={job.id} className="space-y-2">
              <JobProgress job={job} stages={stages} onCancel={cancel} />
              {job.status === "done" && job.repo_id && (
                <Link
                  to={`/repos/${job.repo_id}`}
                  className="inline-block text-sm text-accent hover:underline"
                >
                  Open {job.repo_url.split("/").pop()} results →
                </Link>
              )}
            </div>
          ))
        )}
      </section>
    </div>
  );
}
