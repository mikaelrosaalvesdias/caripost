export default function StatCard({ label, value, helper, tone = "default" }) {
  const toneClass = tone === "highlight" ? "tone-highlight"
    : tone === "success" ? "tone-success"
    : tone === "warn" ? "tone-warn"
    : "";
  return (
    <article className={`portal-stat ${toneClass}`}>
      <div className="portal-stat-label">{label}</div>
      <div className="portal-stat-value">{value}</div>
      {helper ? <div className="portal-stat-helper">{helper}</div> : null}
    </article>
  );
}
