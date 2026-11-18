import { NavLink, Outlet } from "react-router-dom";
import { Activity, GitBranch, Cpu, LogOut, Play, ShieldAlert } from "lucide-react";
import { getUser, clearUser } from "../auth";

const links = [
  { to: "/", label: "Overview", icon: Activity, end: true },
  { to: "/repos", label: "Repositories", icon: GitBranch, end: false },
  { to: "/analyze", label: "Analyze repo", icon: Play, end: false },
  { to: "/models", label: "Models", icon: Cpu, end: false },
];

export function Shell({ onLogout }: { onLogout: () => void }) {
  const user = getUser();

  return (
    <div className="min-h-screen flex">
      <aside className="w-64 shrink-0 border-r border-line bg-ink/80 backdrop-blur-md p-5 flex flex-col">
        <div className="flex items-center gap-3 mb-10">
          <div className="h-10 w-10 rounded-xl bg-rose-500/15 border border-rose-400/30 grid place-items-center">
            <ShieldAlert className="h-5 w-5 text-high" />
          </div>
          <div>
            <div className="text-sm tracking-[0.2em] uppercase text-mute">Thesis</div>
            <div className="text-lg font-semibold leading-tight">SDP Console</div>
          </div>
        </div>
        <nav className="space-y-1">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                  isActive
                    ? "bg-panel-2 text-white border border-line"
                    : "text-mute hover:text-white hover:bg-panel"
                }`
              }
            >
              <link.icon className="h-4 w-4" />
              {link.label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto space-y-3">
          {user && (
            <div className="rounded-xl border border-line bg-panel/60 p-3 space-y-2">
              <div className="text-sm font-medium">{user.username}</div>
              <div className="text-xs text-mute capitalize">{user.role}</div>
              <button
                onClick={() => {
                  clearUser();
                  onLogout();
                }}
                className="flex items-center gap-2 text-xs text-mute hover:text-white transition mt-1"
              >
                <LogOut className="h-3 w-3" />
                Sign out
              </button>
            </div>
          )}
          <div className="text-xs text-mute leading-relaxed">
            Ensemble defect prediction for TypeScript files. Risk colors:{" "}
            <span className="text-high">high</span> /{" "}
            <span className="text-yellow-400">medium</span> /{" "}
            <span className="text-low">low</span>.
          </div>
        </div>
      </aside>
      <main className="flex-1 min-w-0 p-6 lg:p-8 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
