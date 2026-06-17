import { AuthProvider, useAuth } from "./auth/AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { Shell } from "./components/Shell";

function Gate() {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <Shell /> : <LoginPage />;
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
