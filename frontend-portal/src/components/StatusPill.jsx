export default function StatusPill({ value }) {
  const normalized = String(value || "").toLowerCase();
  const cls = ["done", "active"].includes(normalized) ? "done"
    : ["pending", "scheduled"].includes(normalized) ? "pending"
    : ["error", "failed", "churned"].includes(normalized) ? "error"
    : ["trial", "paused"].includes(normalized) ? "active"
    : "active";
  return (
    <span className={`portal-status-pill ${cls}`}>
      {value || "n/a"}
    </span>
  );
}
