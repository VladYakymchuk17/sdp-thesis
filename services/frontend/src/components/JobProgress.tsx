import { Check, Loader2, X, Ban } from "lucide-react";
import type { Job, PipelineStage } from "../types";

function StageDot({ state }: { state: "done" | "active" | "pending" | "failed" }) {
  if (state === "done")
    return (
      <div className="h-6 w-6 rounded-full bg-emerald-500/20 border border-emerald-400/40 grid place-items-center shrink-0">
        <Check className="h-3 w-3 text-low" />
      </div>
    );
  if (state === "active")
    return (
      <div className="h-6 w-6 rounded-full bg-sky-500/20 border border-sky-400/40 grid place-items-center shrink-0">
        <Loader2 className="h-3 w-3 text-accent animate-spin" />
      </div>
    );
  if (state === "failed")
    return (
      <div className="h-6 w-6 rounded-full bg-rose-500/20 border border-rose-400/40 grid place-items-center shrink-0">
        <X className="h-3 w-3 text-high" />
      </div>
    );
  return (
    <div className="h-6 w-6 rounded-full bg-panel-2 border border-line grid place-items-center shrink-0">
      <div className="h-1.5 w-1.5 rounded-full bg-mute" />
    </div>
  );
}

const STATUS_STYLES: Record<string, string> = {
  queued: "text-mute border-line",
  running: "text-accent border-accent/40 bg-accent/10",
  done: "text-low border-emerald-400/40 bg-emerald-500/10",
  failed: "text-high border-rose-400/40 bg-rose-500/10",
  cancelled: "text-mute border-line bg-panel-2",
};

export function JobProgress({
  job,
  stages,
  onCancel,
}: {
  job: Job;
  stages: PipelineStage[];
  onCancel?: (id: number) => void;
}) {
  const active = job.status === "running" || job.status === "queued";

  function stageState(index: number): "done" | "active" | "pending" | "failed" {
    if (job.status === "failed" && index === job.stage_index) return "failed";
    if (job.status === "done") return "done";
    if (index < job.stage_index) return "done";
    if (index === job.stage_index && active) return "active";
    return "pending";
  }

  const repoLabel = job.repo_url.replace(/^https?:\/\/(www\.)?github\.com\//, "");

  return (
    <div className="rounded-2xl border border-line bg-panel/70 p-5 space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium truncate">{repoLabel}</span>
            <span className="text-xs text-mute font-mono">{job.branch}</span>
            <span
              className={`rounded-md border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                STATUS_STYLES[job.status] || "text-mute border-line"
              }`}
            >
              {job.status}
            </span>
          </div>
          <div className="mt-1 text-xs text-mute">
            job #{job.id}
            {job.submitted_by ? ` · submitted by ${job.submitted_by}` : ""}
          </div>
        </div>
        {active && onCancel && (
          <button
            onClick={() => onCancel(job.id)}
            className="rounded-lg border border-line px-3 py-1.5 text-xs hover:bg-panel-2 inline-flex items-center gap-1.5 transition"
          >
            <Ban className="h-3 w-3" />
            Cancel
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div>
        <div className="h-2 rounded-full bg-panel-2 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              job.status === "failed"
                ? "bg-rose-400"
                : job.status === "done"
                  ? "bg-emerald-400"
                  : "bg-sky-400"
            }`}
            style={{ width: `${Math.round(job.progress * 100)}%` }}
          />
        </div>
        <div className="mt-1.5 flex justify-between text-xs text-mute">
          <span>{job.stage_label || "Waiting to start"}</span>
          <span className="font-mono">{Math.round(job.progress * 100)}%</span>
        </div>
      </div>

      {/* Stage checklist */}
      <div className="space-y-2">
        {stages.map((stage) => {
          const state = stageState(stage.index);
          return (
            <div key={stage.key} className="flex items-center gap-3">
              <StageDot state={state} />
              <span
                className={`text-sm ${
                  state === "pending"
                    ? "text-mute"
                    : state === "failed"
                      ? "text-high"
                      : "text-white"
                }`}
              >
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>

      {job.message && (
        <p className="text-xs text-mute leading-relaxed border-t border-line pt-3">
          {job.message}
        </p>
      )}

      {job.error && (
        <div className="rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300 font-mono break-all">
          {job.error}
        </div>
      )}

      {/* Result counters, once there is something to show */}
      {(job.commits_mined > 0 || job.files_analyzed > 0) && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 border-t border-line pt-3">
          {[
            ["Commits", job.commits_mined],
            ["Files", job.files_analyzed],
            ["Bug labels", job.bug_labels],
            ["Scored", job.files_scored],
          ].map(([label, value]) => (
            <div key={String(label)}>
              <div className="text-[10px] uppercase tracking-widest text-mute">{label}</div>
              <div className="font-mono text-sm mt-0.5">
                {Number(value).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
