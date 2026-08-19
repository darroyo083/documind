import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";
import AuthExperience from "./AuthExperience";

export default function Login() {
  const { user } = useAuth();

  if (user) {
    return <Navigate to="/" replace />;
  }

  return <AuthExperience mode="login" />;
}
