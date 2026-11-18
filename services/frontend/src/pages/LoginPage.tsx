import { useState } from "react";
import { ShieldAlert } from "lucide-react";
import { api } from "../api";
import { saveUser } from "../auth";
import type { AuthUser } from "../types";

export function LoginPage({ onLogin }: { onLogin: (u: AuthUser) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.login(username, password);
      const user: AuthUser = { username: res.username, role: res.role, token: res.token };
      saveUser(user);
      onLogin(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-ink">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-line bg-panel/80 p-8 space-y-6"
      >
        <div className="flex items-center gap-3 justify-center">
          <div className="h-12 w-12 rounded-xl bg-rose-500/15 border border-rose-400/30 grid place-items-center">
            <ShieldAlert className="h-6 w-6 text-high" />
          </div>
          <div>
            <div className="text-xs tracking-[0.2em] uppercase text-mute">Thesis</div>
            <div className="text-xl font-semibold">SDP Console</div>
          </div>
        </div>

        <p className="text-center text-sm text-mute">
          Sign in to access the defect prediction dashboard.
        </p>

        {error && (
          <div className="rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className="block text-xs uppercase tracking-widest text-mute mb-1">Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-accent"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs uppercase tracking-widest text-mute mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-accent"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={loading || !username || !password}
          className="w-full rounded-xl bg-accent/20 border border-accent/40 px-4 py-2.5 text-sm font-medium hover:bg-accent/30 disabled:opacity-50 transition"
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>

        <p className="text-center text-xs text-mute">
          Default: admin / sdp2026
        </p>
      </form>
    </div>
  );
}
