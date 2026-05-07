export default function StatCard({ label, value, helper, tone = "default" }) {
  const toneStyle =
    tone === "highlight"
      ? {
          background: "linear-gradient(135deg, color-mix(in srgb, var(--portal-primary) 24%, transparent), color-mix(in srgb, var(--portal-accent) 12%, transparent))",
          borderColor: "color-mix(in srgb, var(--portal-primary) 34%, transparent)",
        }
      : tone === "success"
        ? {
            background: "linear-gradient(135deg, rgba(16,185,129,.18), rgba(16,185,129,.06))",
            borderColor: "rgba(16,185,129,.3)",
          }
        : {
            background: "linear-gradient(135deg, rgba(255,255,255,.12), rgba(255,255,255,.05))",
            borderColor: "rgba(255,255,255,.1)",
          };

  return (
    <article
      className="rounded-[24px] border p-5 shadow-xl shadow-black/10"
      style={toneStyle}
    >
      <div className="text-sm portal-theme-muted">{label}</div>
      <div className="mt-3 font-display text-3xl font-semibold text-white">{value}</div>
      {helper ? <div className="portal-theme-muted mt-2 text-sm">{helper}</div> : null}
    </article>
  );
}
