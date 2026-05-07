import { useEffect, useState } from "react";
import { format } from "date-fns";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { portalFetch } from "../api/client";
import SectionCard from "../components/SectionCard";
import StatCard from "../components/StatCard";
import StatusPill from "../components/StatusPill";

export default function DashboardPage() {
  const [overview, setOverview] = useState(null);
  const [chart, setChart] = useState([]);
  const [schedule, setSchedule] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [overviewData, chartData, scheduleData] = await Promise.all([
          portalFetch("/api/portal/my-stats/overview"),
          portalFetch("/api/portal/my-stats/chart?metric=views&period=30d&granularity=day"),
          portalFetch("/api/portal/my-schedule"),
        ]);
        if (!alive) return;
        setOverview(overviewData);
        setChart(chartData?.points || []);
        setSchedule(scheduleData?.entries || []);
      } catch (err) {
        if (!alive) return;
        setError(err.message || "Falha ao carregar dashboard");
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
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Views totais"
          value={formatCompact(overview?.total_views)}
          helper="Somatório da última coleta"
          tone="highlight"
        />
        <StatCard
          label="Vídeos publicados"
          value={formatCompact(overview?.total_videos)}
          helper="Catálogo total monitorado"
        />
        <StatCard
          label="Ganhos estimados no mês"
          value={formatCurrency(overview?.estimated_earnings_this_month)}
          helper="Líquido estimado do criador"
          tone="success"
        />
        <StatCard
          label="Plataformas monitoradas"
          value={formatCompact(overview?.platform_stats?.length || 0)}
          helper="Canais com estatística ativa"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <SectionCard
          title="Curva de views"
          subtitle="Últimos 30 dias consolidados para o criador."
        >
          {loading ? (
            <LoadingBox />
          ) : error ? (
            <ErrorBox message={error} />
          ) : (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chart}>
                  <CartesianGrid stroke="rgba(148,163,184,0.14)" vertical={false} />
                  <XAxis dataKey="bucket" stroke="#94a3b8" tickLine={false} axisLine={false} />
                  <YAxis stroke="#94a3b8" tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={{
                      background: "rgba(2,6,23,0.95)",
                      border: "1px solid rgba(148,163,184,0.18)",
                      borderRadius: "16px",
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke="#67e8f9"
                    strokeWidth={3}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Próximas publicações" subtitle="Agenda recente do pipeline da agência.">
          <div className="space-y-3">
            {(schedule || []).slice(0, 6).map((entry) => (
              <article key={entry.entry_id} className="rounded-2xl border border-white/8 bg-white/5 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-medium text-white">{entry.title || "Publicação agendada"}</div>
                  <StatusPill value={entry.status} />
                </div>
                <div className="mt-2 text-sm text-slate-400">
                  {formatDateTime(entry.publish_at)} • {String(entry.publish_platforms || []).replaceAll(",", ", ")}
                </div>
              </article>
            ))}
            {!schedule?.length ? <EmptyInline text="Nenhuma publicação agendada no momento." /> : null}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

function LoadingBox() {
  return <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-10 text-center text-slate-400">Carregando dados do dashboard...</div>;
}

function ErrorBox({ message }) {
  return <div className="rounded-2xl border border-rose-300/20 bg-rose-400/10 px-4 py-10 text-center text-rose-100">{message}</div>;
}

function EmptyInline({ text }) {
  return <div className="rounded-2xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-400">{text}</div>;
}

function formatCompact(value) {
  return new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value || 0));
}

function formatCurrency(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));
}

function formatDateTime(value) {
  if (!value) return "Sem data";
  try {
    return format(new Date(value), "dd/MM/yyyy HH:mm");
  } catch {
    return String(value);
  }
}
