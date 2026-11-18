export type RiskLevel = "high" | "medium" | "low";

export type RepoInfo = {
  id: number;
  name: string;
  url: string;
  branch: string;
  total_commits: number;
  status: string;
};

export type RepoStats = {
  repo_id: number;
  repo_name: string;
  total_files: number;
  files_with_metrics: number;
  total_commits: number;
  buggy_files_szz: number;
  avg_loc: number | null;
  avg_complexity: number | null;
  avg_churn: number | null;
};

export type FileRow = {
  file_path: string;
  loc: number | null;
  cyclomatic_complexity: number | null;
  max_nesting_depth: number | null;
  commits_count: number | null;
  unique_authors: number | null;
  churn: number | null;
  risk_score: number | null;
  risk_level: RiskLevel | null;
};

export type FilesResponse = {
  total: number;
  limit: number;
  offset: number;
  files: FileRow[];
};

export type ModelVote = {
  model_name: string;
  risk_score: number;
  prediction: "buggy" | "clean" | string;
  f1_score: number;
};

export type Factor = {
  feature: string;
  label: string;
  shap_value: number;
  direction: "increases" | "decreases";
  impact_share: number;
  value: number | null;
  value_display: string;
  unit: string;
  what: string;
  interpretation: string;
  baseline_comparison: string | null;
  category: string;
  is_above_threshold: boolean;
  level: "high" | "elevated" | "normal" | "low" | "unknown";
  actionable: boolean;
  advice: string[];
};

export type PredictResponse = {
  file_path: string;
  risk_score: number;
  risk_level: RiskLevel;
  is_buggy: boolean;
  votes_buggy: number;
  votes_clean: number;
  total_models: number;
  per_model: ModelVote[];
  top_features: Record<string, number>;
  explanation: string;
  explanation_detail: string;
  recommendations: string[];
  factors: Factor[];
  explanation_source: "llm" | "generated";
};

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export type Job = {
  id: number;
  repo_id: number | null;
  repo_url: string;
  branch: string;
  submitted_by: string | null;
  status: JobStatus;
  stage: string | null;
  stage_label: string | null;
  stage_index: number;
  total_stages: number;
  progress: number;
  message: string | null;
  error: string | null;
  commits_mined: number;
  files_analyzed: number;
  bug_labels: number;
  files_scored: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type PipelineStage = {
  key: string;
  label: string;
  index: number;
};

export type DashboardSummary = {
  repositories: number;
  files_analyzed: number;
  total_commits: number;
  buggy_files_szz: number;
  predictions_saved: number;
  high_risk_files: number;
  medium_risk_files: number;
  low_risk_files: number;
  avg_risk_score: number | null;
  ensemble_models: number;
  model_names: string[];
};

export type EnsembleInfo = {
  total_models: number;
  models: {
    name: string;
    features_count: number;
    metrics: Record<string, number>;
  }[];
};

export type AuthUser = {
  username: string;
  role: string;
  token: string;
};
