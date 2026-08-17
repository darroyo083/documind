import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./auth";
import { LoadingState } from "./components/ui";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Landing from "./pages/Landing";
import SearchPage from "./pages/SearchPage";
import SpaceDetail from "./pages/SpaceDetail";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return <LoadingState message="Loading your workspace..." />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function HomeRoute() {
  const { user, loading } = useAuth();
  if (loading) return <LoadingState message="Loading DocuMind..." />;
  return user ? <Dashboard /> : <Landing />;
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={<HomeRoute />}
      />
      <Route
        path="/spaces/:id"
        element={
          <ProtectedRoute>
            <SpaceDetail />
          </ProtectedRoute>
        }
      />
      <Route
        path="/search"
        element={
          <ProtectedRoute>
            <SearchPage />
          </ProtectedRoute>
        }
      />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
    </Routes>
  );
}
