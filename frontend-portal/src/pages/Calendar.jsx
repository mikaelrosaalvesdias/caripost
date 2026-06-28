import { useEffect, useState } from "react";
import { format } from "date-fns";
import SectionCard from "../components/SectionCard";
import StatusPill from "../components/StatusPill";
import { portalFetch } from "../api/client";

export default function CalendarPage() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await portalFetch("/api/portal/my-schedule");
        if (!alive) return;
        setEntries(data?.entries || []);
      } catch (err) {
        if (!alive) return;
        setError(err.message || "Falha ao carregar agenda");
      } finally {
        if (alive) setLoading(false);
      }
    }
    load();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <SectionCard title="Agenda editorial" subtitle="Calendário das publicações e cross-promotion do criador.">
      {loading ? <Box text="Carregando agenda..." /> : null}
      {error ? <ErrorBox text={error} /> : null}
      {!loading && !error ? (
        <div className="space-y-4">
          {entries.map((entry) => (
            <article key={entry.entry_id} className="rounded-[24px] border border-black/10 bg-black/5 p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-slate-900">{entry.title || "Publicação"}</div>
                  <div className="mt-2 text-sm text-slate-600">
                    {entry.description || "Sem descrição"}
                  </div>
                </div>
                <StatusPill value={entry.status} />
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                <Mini label="Publicar em" value={(entry.publish_platforms || []).join(", ") || "n/a"} />
                <Mini label="Data principal" value={formatDateTime(entry.publish_at)} />
                <Mini label="Cross-promo" value={entry.cross_promote_at ? formatDateTime(entry.cross_promote_at) : "desativado"} />
              </div>
            </article>
          ))}
          {!entries.length ? <Box text="Nenhuma entrada de calendário encontrada." /> : null}
        </div>
      ) : null}
    </SectionCard>
  );
}

function Mini({ label, value }) {
  return (
    <div className="rounded-2xl border border-black/8 bg-slate-50/40 px-3 py-3">
      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</div>
      <div className="mt-2 text-sm text-slate-900">{value}</div>
    </div>
  );
}

function Box({ text }) {
  return <div className="rounded-2xl border border-dashed border-black/10 px-4 py-8 text-center text-sm text-slate-500">{text}</div>;
}

function ErrorBox({ text }) {
  return <div className="rounded-2xl border border-rose-300/20 bg-rose-400/10 px-4 py-4 text-sm text-rose-700">{text}</div>;
}

function formatDateTime(value) {
  if (!value) return "Sem data";
  try {
    return format(new Date(value), "dd/MM/yyyy HH:mm");
  } catch {
    return String(value);
  }
}
