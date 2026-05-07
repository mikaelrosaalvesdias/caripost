export default function StatusPill({ value }) {
  const normalized = String(value || "").toLowerCase();
  const map = {
    active: { background: "rgba(16,185,129,.15)", color: "#d1fae5", borderColor: "rgba(16,185,129,.25)" },
    trial: { background: "color-mix(in srgb, var(--portal-primary) 15%, transparent)", color: "#e0f7ff", borderColor: "color-mix(in srgb, var(--portal-primary) 25%, transparent)" },
    paused: { background: "rgba(245,158,11,.15)", color: "#fef3c7", borderColor: "rgba(245,158,11,.25)" },
    churned: { background: "rgba(244,63,94,.15)", color: "#ffe4e6", borderColor: "rgba(244,63,94,.25)" },
    scheduled: { background: "color-mix(in srgb, var(--portal-primary) 15%, transparent)", color: "#e0f7ff", borderColor: "color-mix(in srgb, var(--portal-primary) 25%, transparent)" },
    done: { background: "rgba(16,185,129,.15)", color: "#d1fae5", borderColor: "rgba(16,185,129,.25)" },
    error: { background: "rgba(244,63,94,.15)", color: "#ffe4e6", borderColor: "rgba(244,63,94,.25)" },
  };
  return (
    <span
      className="inline-flex rounded-full border px-3 py-1 text-xs uppercase tracking-[0.2em]"
      style={map[normalized] || { background: "rgba(255,255,255,.1)", color: "var(--portal-text)", borderColor: "rgba(255,255,255,.12)" }}
    >
      {value || "n/a"}
    </span>
  );
}
