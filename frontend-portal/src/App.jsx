import { lazy, Suspense, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import PortalShell from "./components/PortalShell";
import { clearSession, fetchPortalBrandingBySlug, getStoredCreator, getToken, portalFetch } from "./api/client";
import { buildPortalThemeStyle, getPortalBranding } from "./lib/branding";
import LoginPage from "./pages/Login";

const DashboardPage = lazy(() => import("./pages/Dashboard"));
const MyVideosPage = lazy(() => import("./pages/MyVideos"));
const EarningsPage = lazy(() => import("./pages/Earnings"));
const TrendsPage = lazy(() => import("./pages/Trends"));
const UploadPage = lazy(() => import("./pages/Upload"));
const CalendarPage = lazy(() => import("./pages/Calendar"));
const ProfilePage = lazy(() => import("./pages/Profile"));

const RESERVED_PUBLIC_PATHS = new Set(["", "login", "videos", "ganhos", "tendencias", "upload", "agenda", "perfil"]);

function resolvePublicPortalSlug(pathname = "") {
  const segments = String(pathname || "")
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean);
  if (!segments.length) return "";
  if (segments[0] === "login") return "";
  if (segments.length >= 2 && segments[1] === "login") return segments[0];
  if (segments.length === 1 && !RESERVED_PUBLIC_PATHS.has(segments[0])) return segments[0];
  return "";
}

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const [token, setToken] = useState(() => getToken());
  const [creator, setCreator] = useState(() => (getToken() ? getStoredCreator() : null));
  const [booting, setBooting] = useState(Boolean(getToken()));
  const [publicCreator, setPublicCreator] = useState(null);
  const publicSlug = resolvePublicPortalSlug(location.pathname);

  useEffect(() => {
    let alive = true;
    async function bootstrap() {
      if (!token) {
        setBooting(false);
        return;
      }
      try {
        const me = await portalFetch("/api/portal/me");
        if (!alive) return;
        setCreator(me);
      } catch {
        if (!alive) return;
        handleLogout();
      } finally {
        if (alive) setBooting(false);
      }
    }
    bootstrap();
    return () => {
      alive = false;
    };
  }, [token]);

  useEffect(() => {
    let alive = true;
    async function loadPublicBranding() {
      if (token || !publicSlug) {
        setPublicCreator(null);
        return;
      }
      try {
        const publicData = await fetchPortalBrandingBySlug(publicSlug);
        if (!alive) return;
        setPublicCreator(publicData || null);
      } catch {
        if (!alive) return;
        setPublicCreator(null);
      }
    }
    loadPublicBranding();
    return () => {
      alive = false;
    };
  }, [token, publicSlug]);

  function handleLogin(session) {
    setToken(session?.token || "");
    setCreator(session?.creator || null);
    setPublicCreator(null);
    navigate("/", { replace: true });
  }

  function handleLogout() {
    const returnSlug = creator?.slug || publicCreator?.slug || publicSlug;
    clearSession();
    setToken("");
    setCreator(null);
    navigate(returnSlug ? `/${returnSlug}` : "/login", { replace: true });
  }

  if (!token) {
    return <LoginPage onLogin={handleLogin} creator={publicCreator || creator} entrySlug={publicSlug} />;
  }

  if (booting) {
    return <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-300">Validando sessão do portal...</div>;
  }

  const branding = getPortalBranding(creator);

  return (
    <PortalShell creator={creator} branding={branding} themeStyle={buildPortalThemeStyle(branding)} onLogout={handleLogout}>
      <Suspense fallback={<div className="rounded-[28px] border border-white/10 bg-white/6 px-5 py-10 text-center text-slate-300">Carregando página do portal...</div>}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/videos" element={<MyVideosPage />} />
          <Route path="/ganhos" element={<EarningsPage />} />
          <Route path="/tendencias" element={<TrendsPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/agenda" element={<CalendarPage />} />
          <Route path="/perfil" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </PortalShell>
  );
}
