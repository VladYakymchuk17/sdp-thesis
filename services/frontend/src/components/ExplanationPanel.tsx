import { useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  Brain,
  ChevronDown,
  ChevronRight,
  ListChecks,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { RiskBadge, riskBarColor } from "./RiskBadge";
import type { Factor, FileRow, PredictResponse } from "../types";

/** Renders **bold** segments and `code` spans from the explanation text. */
function RichText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={i} className="font-semibold text-white">
              {part.slice(2, -2)}
            </strong>
          );
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={i} className="font-mono text-xs text-accent bg-panel-2 px-1 py-0.5 rounded">
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

/** Splits the detail blob into headed sections and bullet lists. */
function DetailBlock({ text }: { text: string }) {
  const lines = text.split("\n").filter((l) => l.trim());
  return (
    <div className="space-y-2">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("**") && trimmed.endsWith("**")) {
          return (
            <h4 key={i} className="text-xs uppercase tracking-widest text-mute pt-2">
              {trimmed.slice(2, -2)}
            </h4>
          );
        }
        if (trimmed.startsWith("- ")) {
          return (
            <div key={i} className="flex gap-2 text-sm leading-relaxed">
              <span className="text-mute mt-0.5 shrink-0">•</span>
              <span>
                <RichText text={trimmed.slice(2)} />
              </span>
            </div>
          );
        }
        return (
          <p key={i} className="text-sm leading-relaxed text-mute">
            <RichText text={trimmed} />
          </p>
        );
      })}
    </div>
  );
}

function FactorCard({ factor }: { factor: Factor }) {
  const [open, setOpen] = useState(false);
  const risky = factor.direction === "increases";

  return (
    <div
      className={`rounded-xl border overflow-hidden transition ${
        risky ? "border-rose-400/25 bg-rose-500/5" : "border-emerald-400/20 bg-emerald-500/5"
      }`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-start gap-3 p-3 text-left hover:bg-white/[0.02]"
      >
        {open ? (
          <ChevronDown className="h-4 w-4 mt-0.5 shrink-0 text-mute" />
        ) : (
          <ChevronRight className="h-4 w-4 mt-0.5 shrink-0 text-mute" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-sm font-medium">{factor.label}</span>
            <span className="font-mono text-sm">{factor.value_display}</span>
            {factor.unit && !["score", "ratio"].includes(factor.unit) && (
              <span className="text-xs text-mute">{factor.unit}</span>
            )}
            {factor.is_above_threshold ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 border border-amber-400/30 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-amber-300">
                <AlertTriangle className="h-2.5 w-2.5" />
                over threshold
              </span>
            ) : (
              <span className="rounded-md border border-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-mute">
                {factor.level}
              </span>
            )}
          </div>
          {factor.baseline_comparison && (
            <div className="mt-1 text-xs text-mute">{factor.baseline_comparison}</div>
          )}
          {/* Impact bar: share of total SHAP magnitude */}
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1 h-1.5 rounded-full bg-panel-2 overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.round(factor.impact_share * 100)}%`,
                  background: risky ? "#fb7185" : "#34d399",
                }}
              />
            </div>
            <span className="text-[10px] font-mono text-mute w-20 text-right">
              {(factor.impact_share * 100).toFixed(0)}% impact
            </span>
          </div>
        </div>
      </button>

      {open && (
        <div className="px-3 pb-3 pl-10 space-y-3 text-sm">
          <p className="text-mute leading-relaxed">
            This measures {factor.what}.
          </p>
          <p className="leading-relaxed">
            {factor.interpretation}
            {risky ? ", pushing this prediction toward buggy." : ", pulling it toward clean."}
          </p>
          {factor.advice.length > 0 ? (
            <div className="space-y-1.5 pt-1">
              <div className="text-xs uppercase tracking-widest text-mute">How to reduce it</div>
              {factor.advice.map((item, i) => (
                <div key={i} className="flex gap-2 leading-relaxed">
                  <span className="text-accent shrink-0">→</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          ) : (
            risky && (
              <p className="text-xs text-mute leading-relaxed pt-1">
                This value is {factor.level}, so there is nothing to reduce here — the
                contribution comes from how it combines with the file's other metrics.
              </p>
            )
          )}
          <div className="text-[11px] font-mono text-mute pt-1">
            SHAP {factor.shap_value > 0 ? "+" : ""}
            {factor.shap_value.toFixed(3)} · {factor.feature}
          </div>
        </div>
      )}
    </div>
  );
}

export function ExplanationPanel({
  explain,
  selected,
}: {
  explain: PredictResponse;
  selected: FileRow | null;
}) {
  const risky = explain.factors.filter((f) => f.direction === "increases");
  const protective = explain.factors.filter((f) => f.direction === "decreases");

  return (
    <div className="mt-6 space-y-6">
      {/* Verdict */}
      <div className="flex items-center gap-3">
        <RiskBadge level={explain.risk_level} />
        <span className="font-mono text-2xl">{explain.risk_score.toFixed(3)}</span>
        <span className="text-sm text-mute">
          {explain.votes_buggy}/{explain.total_models} models voted buggy
        </span>
      </div>

      {/* Assessment */}
      <section className="rounded-xl border border-accent/30 bg-accent/5 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-medium text-accent">Assessment</h3>
          <span
            className="ml-auto text-[10px] uppercase tracking-wide rounded-md border px-1.5 py-0.5 border-line text-mute"
            title={
              explain.explanation_source === "llm"
                ? "Written by the configured language model"
                : "Generated from SHAP values and metric thresholds — no LLM was reachable"
            }
          >
            {explain.explanation_source === "llm" ? "LLM" : "rule-based"}
          </span>
        </div>
        <p className="text-sm leading-relaxed">
          <RichText text={explain.explanation} />
        </p>
        {explain.explanation_detail && <DetailBlock text={explain.explanation_detail} />}
      </section>

      {/* Recommendations */}
      {explain.recommendations.length > 0 && (
        <section className="rounded-xl border border-emerald-400/25 bg-emerald-500/5 p-4">
          <div className="flex items-center gap-2 mb-3">
            <ListChecks className="h-4 w-4 text-low" />
            <h3 className="text-sm font-medium text-low">What to do about it</h3>
          </div>
          <ol className="space-y-2.5">
            {explain.recommendations.map((item, i) => (
              <li key={i} className="flex gap-3 text-sm leading-relaxed">
                <span className="shrink-0 h-5 w-5 rounded-md bg-emerald-500/15 border border-emerald-400/30 grid place-items-center text-[11px] font-mono text-low">
                  {i + 1}
                </span>
                <span>
                  <RichText text={item} />
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {/* Drivers */}
      {risky.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="h-4 w-4 text-high" />
            <h3 className="text-sm uppercase tracking-widest text-mute">
              Driving the risk
            </h3>
            <span className="text-xs text-mute">click to expand</span>
          </div>
          <div className="space-y-2">
            {risky.map((f) => (
              <FactorCard key={f.feature} factor={f} />
            ))}
          </div>
        </section>
      )}

      {protective.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <ShieldCheck className="h-4 w-4 text-low" />
            <h3 className="text-sm uppercase tracking-widest text-mute">
              Working in its favour
            </h3>
          </div>
          <div className="space-y-2">
            {protective.map((f) => (
              <FactorCard key={f.feature} factor={f} />
            ))}
          </div>
        </section>
      )}

      {/* Model votes */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <BarChart3 className="h-4 w-4 text-mute" />
          <h3 className="text-sm uppercase tracking-widest text-mute">Ensemble votes</h3>
        </div>
        <div className="space-y-2">
          {explain.per_model.map((vote) => (
            <div key={vote.model_name} className="flex items-center gap-3 text-sm">
              <div className="w-32 font-mono truncate text-xs">{vote.model_name}</div>
              <div className="flex-1 h-2.5 rounded-full bg-panel-2 overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.round(vote.risk_score * 100)}%`,
                    background: riskBarColor(vote.prediction === "buggy" ? "high" : "low"),
                  }}
                />
              </div>
              <div className="w-24 text-right font-mono text-xs">
                <span className={vote.prediction === "buggy" ? "text-high" : "text-low"}>
                  {vote.prediction}
                </span>{" "}
                {vote.risk_score.toFixed(2)}
              </div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-mute">
          Final label is the majority vote; the score is the mean probability.
        </p>
      </section>

      {/* Raw metrics */}
      {selected && (
        <section>
          <h3 className="text-sm uppercase tracking-widest text-mute mb-2">Raw metrics</h3>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {[
              ["LOC", selected.loc],
              ["Complexity", selected.cyclomatic_complexity],
              ["Nesting", selected.max_nesting_depth],
              ["Authors", selected.unique_authors],
              ["Churn", selected.churn],
              ["Commits", selected.commits_count],
            ].map(([label, value]) => (
              <div key={String(label)}>
                <span className="text-mute">{label}:</span>{" "}
                <span className="font-mono">{value ?? "—"}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
