import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/",           label: "Dashboard",    icon: "◎" },
  { to: "/videos",     label: "Meus Vídeos",  icon: "▣" },
  { to: "/ganhos",     label: "Ganhos",       icon: "◔" },
  { to: "/tendencias", label: "Tendências",   icon: "↗" },
  { to: "/upload",     label: "Upload",       icon: "⬆" },
  { to: "/agenda",     label: "Agenda",       icon: "◌" },
  { to: "/perfil",     label: "Meu Perfil",   icon: "◍" },
];

export default function PortalShell({ creator, branding = {}, themeStyle = {}, onLogout, children }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="portal-root" style={themeStyle}>
      {/* Background aurora */}
      <div className="portal-aurora" aria-hidden="true">
        <div className="portal-aurora-1" />
        <div className="portal-aurora-2" />
      </div>

      {/* Mobile topbar */}
      <header className="portal-topbar">
        <div className="portal-topbar-brand">
          {branding.logo_b64 ? (
            <img src={branding.logo_b64} alt="Logo" className="portal-logo-img" />
          ) : (
            <div className="portal-logo-mark">{(branding.brand_name || "M")[0]}</div>
          )}
          <span className="portal-topbar-name">{branding.brand_name || "Portal"}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="portal-creator-badge">
            <span className="portal-creator-initial">{(creator?.name || "?")[0]}</span>
          </div>
          <button
            type="button"
            className="portal-menu-btn"
            onClick={() => setMenuOpen(o => !o)}
            aria-label="Menu"
          >
            {menuOpen ? "✕" : "☰"}
          </button>
        </div>
      </header>

      {/* Mobile drawer */}
      {menuOpen && (
        <div className="portal-drawer-overlay" onClick={() => setMenuOpen(false)}>
          <nav className="portal-drawer" onClick={e => e.stopPropagation()}>
            <div className="portal-drawer-head">
              <div className="portal-creator-info">
                <div className="portal-creator-avatar">{(creator?.name || "?")[0]}</div>
                <div>
                  <div className="portal-creator-name">{creator?.name || "Criador"}</div>
                  <div className="portal-creator-email">{creator?.email || ""}</div>
                </div>
              </div>
            </div>
            {NAV_ITEMS.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) => `portal-nav-link ${isActive ? "is-active" : ""}`}
                onClick={() => setMenuOpen(false)}
              >
                <span className="portal-nav-icon">{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
            <button type="button" className="portal-logout-btn" onClick={onLogout}>
              Encerrar sessão
            </button>
          </nav>
        </div>
      )}

      <div className="portal-layout">
        {/* Desktop sidebar */}
        <aside className="portal-sidebar">
          <div className="portal-sidebar-brand">
            {branding.logo_b64 ? (
              <img src={branding.logo_b64} alt="Logo" className="portal-logo-img-lg" />
            ) : (
              <div className="portal-logo-mark-lg">{(branding.brand_name || "M")[0]}</div>
            )}
            <div className="portal-sidebar-brand-text">
              <div className="portal-brand-label">{branding.brand_name || "MetaPorn"}</div>
              <div className="portal-brand-headline">{branding.headline || "Creator Portal"}</div>
            </div>
          </div>

          <div className="portal-tagline">{branding.tagline || "Seu painel de performance em um só lugar."}</div>

          <div className="portal-creator-panel">
            <div className="portal-creator-avatar">{(creator?.name || "?")[0]}</div>
            <div>
              <div className="portal-creator-name">{creator?.name || "Criador"}</div>
              <div className="portal-creator-email">{creator?.email || ""}</div>
            </div>
          </div>

          <nav className="portal-nav">
            {NAV_ITEMS.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) => `portal-nav-link ${isActive ? "is-active" : ""}`}
              >
                <span className="portal-nav-icon">{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
          </nav>

          <button type="button" className="portal-logout-btn" onClick={onLogout}>
            Encerrar sessão
          </button>
        </aside>

        {/* Main content */}
        <main className="portal-main">
          {children}
        </main>
      </div>

      {/* Mobile bottom nav */}
      <nav className="portal-bottom-nav" aria-label="Navegação mobile">
        {NAV_ITEMS.slice(0, 5).map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) => `portal-bottom-nav-item ${isActive ? "is-active" : ""}`}
          >
            <span className="portal-bottom-nav-icon">{item.icon}</span>
            <span className="portal-bottom-nav-label">{item.label.split(" ")[0]}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
