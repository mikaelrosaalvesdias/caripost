export default function SectionCard({ title, subtitle, action, children }) {
  return (
    <section className="portal-shell-card rounded-[28px] p-5">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl font-semibold text-white">{title}</h2>
          {subtitle ? <p className="portal-theme-muted mt-1 text-sm">{subtitle}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
