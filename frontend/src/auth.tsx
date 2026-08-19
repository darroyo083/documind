import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import * as api from "./api";
import { PUBLIC_DEMO_MODE } from "./demo";

interface User {
  id: string;
  email: string;
  display_name: string;
}

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    display_name: string
  ) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (PUBLIC_DEMO_MODE) {
      api.clearToken();
      setLoading(false);
      return;
    }
    const token = localStorage.getItem("access_token");
    if (!token) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then((u) => setUser(u))
      .catch(() => {
        localStorage.removeItem("access_token");
      })
      .finally(() => setLoading(false));
  }, []);

  const loginFn = useCallback(async (email: string, password: string) => {
    const res = await api.login({ email, password });
    api.setToken(res.access_token);
    const u = await api.me();
    setUser(u);
  }, []);

  const registerFn = useCallback(
    async (email: string, password: string, display_name: string) => {
      const res = await api.register({ email, password, display_name });
      api.setToken(res.access_token);
      const u = await api.me();
      setUser(u);
    },
    []
  );

  const logoutFn = useCallback(() => {
    api.clearToken();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login: loginFn,
        register: registerFn,
        logout: logoutFn,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
