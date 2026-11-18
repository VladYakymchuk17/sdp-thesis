const express = require("express");

const ML_URL = process.env.ML_SERVICE_URL || "http://127.0.0.1:8000";
const PORT = Number(process.env.PORT || 3001);

const app = express();
app.use(express.json());
app.use((req, res, next) => {
  res.header("Access-Control-Allow-Origin", "*");
  res.header("Access-Control-Allow-Headers", "Content-Type");
  res.header("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "sdp-backend", ml: ML_URL });
});

app.post("/api/v1/jobs/analyze", (req, res) => {
  const repoUrl = req.body && req.body.repo_url;
  if (!repoUrl) {
    return res.status(400).json({ detail: "repo_url is required" });
  }
  return res.json({
    status: "queued",
    repo: repoUrl,
    branch: req.body.branch || "main",
    note: "Full git mining is a long pipeline. Use a mined repo in the dashboard, or run python run_mining.py.",
  });
});

app.use("/api", async (req, res) => {
  try {
    const url = `${ML_URL}${req.originalUrl}`;
    const upstream = await fetch(url, {
      method: req.method,
      headers: { "Content-Type": "application/json" },
      body: req.method === "GET" || req.method === "HEAD" ? undefined : JSON.stringify(req.body || {}),
    });
    const text = await upstream.text();
    res.status(upstream.status);
    res.setHeader("Content-Type", upstream.headers.get("content-type") || "application/json");
    res.send(text);
  } catch (err) {
    res.status(502).json({ detail: String(err.message || err) });
  }
});

app.listen(PORT, () => {
  console.log(`SDP backend on http://localhost:${PORT} (proxy -> ${ML_URL})`);
});
