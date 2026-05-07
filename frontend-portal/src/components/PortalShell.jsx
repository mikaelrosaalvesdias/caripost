import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/videos", label: "Meus Vídeos" },
  { to: "/ganhos", label: "Ganhos" },
  { to: "/tendencias", label: "Tendências" },
  { to: "/upload", label: "Upload" },
  { to: "/agenda", label: "Agenda" },
  { to: "/perfil", label: "Meu Perfil" },
];

export default function PortalShell({ creator, branding = {}, themeStyle = {}, onLogout, children }) {
  return (
    <div
      className="portal-theme min-h-screen text-slate-100"
      style={{
        ...themeStyle,
        background: `radial-gradient(circle at top, var(--portal-bg-end) 0%, var(--portal-bg-mid) 38%, var(--portal-bg-start) 100%)`,
        color: "var(--portal-text)",
      }}
    >
      <div className="mx-auto flex min-h-screen max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <aside className="portal-shell-card hidden w-72 shrink-0 p-6 md:flex md:flex-col">
          <div>
            <div className="flex items-center gap-3">
              {branding.logo_b64 ? (
                <img
                  src={branding.logo_b64}
                  alt={branding.brand_name || "Logo"}
                  className="h-14 w-14 rounded-2xl border border-white/10 bg-white/5 object-contain p-2"
                />
              ) : null}
              <div className="min-w-0">
                <div className="text-xs uppercase tracking-[0.35em]" style={{ color: "var(--portal-primary)" }}>
                  {branding.brand_name || "MetaPorn"}
                </div>
                <h1 className="mt-2 font-display text-3xl font-semibold">
                  {branding.headline || "Creator Portal"}
                </h1>
              </div>
            </div>
            <p className="mt-3 text-sm portal-theme-muted">
              {branding.tagline || "Seu painel de performance, uploads, tendências e ganhos em um só lugar."}
            </p>
          </div>

          <div className="portal-soft-panel mt-8 rounded-3xl p-4">
            <div className="text-sm portal-theme-muted">Criador conectado</div>
            <div className="mt-1 text-lg font-semibold">{creator?.name || "Criador"}</div>
            <div className="text-sm" style={{ color: "var(--portal-primary)" }}>{creator?.email || ""}</div>
          </div>

          <nav className="mt-8 flex flex-1 flex-col gap-2">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `portal-nav-link rounded-2xl px-4 py-3 text-sm transition ${
                    isActive
                      ? "is-active"
                      : ""
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <button
            type="button"
            onClick={onLogout}
            className="portal-secondary-btn rounded-2xl px-4 py-3 text-sm transition"
          >
            Sair
          </button>
        </aside>

        <main className="min-w-0 flex-1">
          <div className="portal-shell-card mb-6 flex items-center justify-between px-5 py-4">
            <div>
              <div className="text-xs uppercase tracking-[0.28em]" style={{ color: "var(--portal-primary)" }}>
                Área do criador
              </div>
              <div className="mt-1 font-display text-2xl font-semibold">
                {branding.brand_name || creator?.name || "Portal"}
              </div>
            </div>
            <button
              type="button"
              onClick={onLogout}
              className="portal-secondary-btn rounded-2xl px-4 py-2 text-sm transition"
            >
              Encerrar sessão
            </button>
          </div>
          {children}
        </main>
      </div>
    </div>
  );
}
