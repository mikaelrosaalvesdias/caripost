import { useEffect, useState } from "react";
import { format } from "date-fns";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
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
    return () => { alive = false; };
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Stats row */}
      <div style={{ display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
        <StatCard label="Views totais" value={formatCompact(overview?.total_views)} helper="Somatório da última coleta" tone="highlight" />
        <StatCard label="Vídeos publicados" value={formatCompact(overview?.total_videos)} helper="Catálogo total" />
        <StatCard label="Ganhos este mês" value={formatCurrency(overview?.estimated_earnings_this_month)} helper="Líquido estimado" tone="success" />
        <StatCard label="Plataformas" value={formatCompact(overview?.platform_stats?.length || 0)} helper="Com estatística ativa" />
      </div>

      {/* Chart + Schedule */}
      <div style={{ display: "grid", gap: 20, gridTemplateColumns: "1fr" }}>
        <SectionCard title="Curva de views" subtitle="Últimos 30 dias consolidados.">
          {loading ? <LoadingBox /> : error ? <ErrorBox message={error} /> : (
            <div style={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chart}>
                  <CartesianGrid stroke="rgba(148,163,184,0.1)" vertical={false} />
                  <XAxis dataKey="bucket" stroke="#64748b" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
                  <YAxis stroke="#64748b" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: "rgba(6,6,18,.96)", border: "1px solid rgba(255,255,255,.12)", borderRadius: 14, fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="value" stroke="var(--portal-primary)" strokeWidth={2.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Próximas publicações" subtitle="Agenda do pipeline da agência.">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {(schedule || []).slice(0, 6).map((entry) => (
              <article key={entry.entry_id} className="portal-video-card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, color: "#fff", fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {entry.title || "Publicação agendada"}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--portal-muted)", marginTop: 3 }}>
                    {formatDateTime(entry.publish_at)} · {String(entry.publish_platforms || []).replaceAll(",", ", ")}
                  </div>
                </div>
                <StatusPill value={entry.status} />
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
  return <div className="portal-empty">Carregando dados do dashboard...</div>;
}
function ErrorBox({ message }) {
  return <div style={{ padding: "16px 20px", borderRadius: 14, background: "rgba(248,113,113,.1)", border: "1px solid rgba(248,113,113,.2)", color: "#fca5a5", fontSize: 13 }}>{message}</div>;
}
function EmptyInline({ text }) {
  return <div className="portal-empty" style={{ padding: "24px 16px", fontSize: 12 }}>{text}</div>;
}

function formatCompact(value) {
  return new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value || 0));
}
function formatCurrency(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));
}
function formatDateTime(value) {
  if (!value) return "Sem data";
  try { return format(new Date(value), "dd/MM/yyyy HH:mm"); } catch { return String(value); }
}
