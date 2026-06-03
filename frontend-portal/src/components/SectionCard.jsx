export default function SectionCard({ title, subtitle, action, children }) {
  return (
    <section className="portal-card" style={{ marginBottom: 20 }}>
      <div className="portal-card-inner" style={{ borderBottom: "1px solid rgba(255,255,255,.06)", paddingBottom: 16, marginBottom: 16, display: "flex", flexWrap: "wrap", alignItems: "start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <h2 className="portal-section-title font-display">{title}</h2>
          {subtitle ? <p className="portal-section-sub">{subtitle}</p> : null}
        </div>
        {action}
      </div>
      <div className="portal-card-inner" style={{ paddingTop: 0 }}>
        {children}
      </div>
    </section>
  );
}
