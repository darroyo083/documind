import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import Landing from "./Landing";

export default function Login() {
  const { user } = useAuth();
  const navigate = useNavigate();

  if (user) {
    return <Navigate to="/" replace />;
  }

  return <Landing initialSignInOpen onSignInClose={() => navigate("/", { replace: true })} />;
}
