import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./auth";
import { AppShell, LoadingState } from "./components/ui";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Landing from "./pages/Landing";
import SearchPage from "./pages/SearchPage";
import SpaceDetail from "./pages/SpaceDetail";
import EvidencePage from "./pages/EvidencePage";
import CapabilitiesPage from "./pages/CapabilitiesPage";
import { PUBLIC_DEMO_MODE } from "./demo";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  if (loading) {
    return <LoadingState message="Loading your workspace..." />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return (
    <AppShell
      userName={user.display_name}
      userEmail={user.email}
      onLogout={logout}
    >
      {children}
    </AppShell>
  );
}

function HomeRoute() {
  const { user, loading, logout } = useAuth();
  if (loading) return <LoadingState message="Loading DocuMind..." />;
  if (!user) return <Landing />;

  return (
    <AppShell
      userName={user.display_name}
      userEmail={user.email}
      onLogout={logout}
    >
      <Dashboard />
    </AppShell>
  );
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={<HomeRoute />}
      />
      <Route
        path="/spaces/demo"
        element={PUBLIC_DEMO_MODE ? <SpaceDetail demo /> : <Navigate to="/" replace />}
      />
      <Route
        path="/spaces/:id"
        element={
          <ProtectedRoute><SpaceDetail /></ProtectedRoute>
        }
      />
      <Route
        path="/search"
        element={
          PUBLIC_DEMO_MODE ? <SearchPage /> : <ProtectedRoute><SearchPage /></ProtectedRoute>
        }
      />
      <Route path="/login" element={PUBLIC_DEMO_MODE ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/register" element={PUBLIC_DEMO_MODE ? <Navigate to="/" replace /> : <Register />} />
      <Route path="/evidence" element={<EvidencePage />} />
      <Route path="/capabilities" element={<CapabilitiesPage />} />
    </Routes>
  );
}
