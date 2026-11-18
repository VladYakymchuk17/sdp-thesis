import { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { AnalyzePage } from "./pages/AnalyzePage";
import { LoginPage } from "./pages/LoginPage";
import { ModelsPage } from "./pages/ModelsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RepoDetailPage } from "./pages/RepoDetailPage";
import { ReposPage } from "./pages/ReposPage";
import { getUser } from "./auth";
import type { AuthUser } from "./types";

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(getUser);

  if (!user) {
    return <LoginPage onLogin={(u) => setUser(u)} />;
  }

  return (
    <Routes>
      <Route element={<Shell onLogout={() => setUser(null)} />}>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/repos" element={<ReposPage />} />
        <Route path="/repos/:repoId" element={<RepoDetailPage />} />
        <Route path="/analyze" element={<AnalyzePage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
