import { createContext, useContext, useEffect, useMemo, useState, ReactNode } from "react";
import { accessToken, currentSession, emailFrom, isAdmin, signIn, signOut } from "./cognito";

interface AuthState {
  isAuthenticated: boolean;
  isAdmin: boolean;
  email: string;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  getToken: () => Promise<string>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState("");
  const [authed, setAuthed] = useState(false);
  const [admin, setAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    currentSession().then((s) => {
      if (s) {
        setAuthed(true);
        setEmail(emailFrom(s));
        setAdmin(isAdmin(s));
      }
      setLoading(false);
    });
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      isAuthenticated: authed,
      isAdmin: admin,
      email,
      loading,
      async login(e, p) {
        const s = await signIn(e, p);
        setAuthed(true);
        setEmail(emailFrom(s));
        setAdmin(isAdmin(s));
      },
      logout() {
        signOut();
        setAuthed(false);
        setEmail("");
        setAdmin(false);
      },
      async getToken() {
        const s = await currentSession();
        if (!s) throw new Error("세션이 만료되었습니다. 다시 로그인하세요.");
        return accessToken(s);
      },
    }),
    [authed, admin, email, loading],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used within AuthProvider");
  return v;
}
