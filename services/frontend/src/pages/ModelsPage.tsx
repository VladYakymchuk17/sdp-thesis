import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import type { EnsembleInfo } from "../types";

const COLORS = ["#7dd3fc", "#34d399", "#fbbf24", "#fb7185", "#a78bfa"];
const METRIC_LABELS: Record<string, string> = {
  f1: "F1 Score",
  recall: "Recall",
  precision: "Precision",
  auc_roc: "AUC-ROC",
  auc_pr: "AUC-PR",
  mcc: "MCC",
  accuracy: "Accuracy",
};

export function ModelsPage() {
  const [info, setInfo] = useState<EnsembleInfo | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.ensemble().then(setInfo).catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="text-high text-sm">{error}</div>;
  if (!info) return <div className="text-mute">Loading models...</div>;

  const allMetrics = new Set<string>();
  info.models.forEach((m) => Object.keys(m.metrics).forEach((k) => allMetrics.add(k)));
  const metricKeys = Array.from(allMetrics).sort();

  const chartData = info.models.map((m) => ({
    name: m.name.replaceAll("_", " "),
    ...Object.fromEntries(
      metricKeys.map((k) => [k, Number((m.metrics[k] ?? 0).toFixed(4))]),
    ),
  }));

  const comparisonData = metricKeys.map((metric) => ({
    metric: METRIC_LABELS[metric] || metric,
    ...Object.fromEntries(
      info.models.map((m) => [m.name, Number((m.metrics[metric] ?? 0).toFixed(4))]),
    ),
  }));

  return (
    <div className="space-y-8 max-w-7xl">
      <header>
        <h1 className="text-3xl font-semibold">Ensemble models</h1>
        <p className="mt-2 text-mute">
          {info.total_models} models participate in majority voting. Each file is scored
          by all models — the final label is determined by vote count.
        </p>
      </header>

      {/* Model cards */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {info.models.map((model, idx) => (
          <div
            key={model.name}
            className="rounded-2xl border border-line bg-panel/80 p-5 space-y-3"
          >
            <div className="flex items-center gap-3">
              <div
                className="h-3 w-3 rounded-full"
                style={{ background: COLORS[idx % COLORS.length] }}
              />
              <h3 className="font-medium">{model.name.replaceAll("_", " ")}</h3>
            </div>
            <div className="text-xs text-mute">{model.features_count} features</div>
            <div className="grid grid-cols-2 gap-2">
              {metricKeys.map((k) => (
                <div key={k} className="text-sm">
                  <span className="text-mute">{METRIC_LABELS[k] || k}:</span>{" "}
                  <span className="font-mono">
                    {model.metrics[k] != null ? model.metrics[k].toFixed(4) : "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Per-model bar chart */}
      <section className="rounded-2xl border border-line bg-panel/80 p-5">
        <h2 className="text-lg font-medium mb-4">F1 & Recall by model</h2>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ left: 8, right: 8 }}>
              <CartesianGrid stroke="#243049" vertical={false} />
              <XAxis
                dataKey="name"
                stroke="#8b9bb8"
                tick={{ fontSize: 11 }}
                interval={0}
                angle={-12}
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
              <Bar dataKey="f1" fill="#7dd3fc" radius={[6, 6, 0, 0]} />
              <Bar dataKey="recall" fill="#34d399" radius={[6, 6, 0, 0]} />
              <Bar dataKey="precision" fill="#fbbf24" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Comparison chart */}
      <section className="rounded-2xl border border-line bg-panel/80 p-5">
        <h2 className="text-lg font-medium mb-4">Side-by-side metric comparison</h2>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={comparisonData} layout="vertical" margin={{ left: 60, right: 8 }}>
              <CartesianGrid stroke="#243049" horizontal={false} />
              <XAxis
                type="number"
                stroke="#8b9bb8"
                domain={[0, 1]}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                dataKey="metric"
                type="category"
                stroke="#8b9bb8"
                tick={{ fontSize: 11 }}
                width={80}
              />
              <Tooltip
                contentStyle={{
                  background: "#101826",
                  border: "1px solid #243049",
                  borderRadius: 12,
                }}
              />
              <Legend />
              {info.models.map((m, i) => (
                <Bar
                  key={m.name}
                  dataKey={m.name}
                  fill={COLORS[i % COLORS.length]}
                  radius={[0, 4, 4, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}
