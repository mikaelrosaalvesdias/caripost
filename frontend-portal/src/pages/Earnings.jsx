import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { portalFetch } from "../api/client";
import SectionCard from "../components/SectionCard";
import StatCard from "../components/StatCard";

export default function EarningsPage() {
  const [report, setReport] = useState(null);
  const [chart, setChart] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [reportData, chartData] = await Promise.all([
          portalFetch("/api/portal/my-earnings"),
          portalFetch("/api/portal/my-stats/chart?metric=earnings&period=90d&granularity=month"),
        ]);
        if (!alive) return;
        setReport(reportData);
        setChart(chartData?.points || []);
      } catch (err) {
        if (!alive) return;
        setError(err.message || "Falha ao carregar ganhos");
      } finally {
        if (alive) setLoading(false);
      }
    }
    load();
    return () => {
      alive = false;
    };
  }, []);

  const breakdown = Object.entries(report?.platforms_breakdown || {});

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Bruto" value={money(report?.total_gross)} />
        <StatCard label="Taxas plataforma" value={money(report?.total_platform_fees)} />
        <StatCard label="Líquido" value={money(report?.total_net)} tone="highlight" />
        <StatCard label="Comissão agência" value={money(report?.total_agency_commission)} />
        <StatCard label="Repasse criador" value={money(report?.total_creator_payout)} tone="success" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_1fr]">
        <SectionCard title="Receita por período" subtitle="Consolidação de repasse e faturamento por mês.">
          {loading ? <Box text="Carregando curva financeira..." /> : null}
          {error ? <ErrorBox text={error} /> : null}
          {!loading && !error ? (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chart}>
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                  <XAxis dataKey="bucket" stroke="#94a3b8" tickLine={false} axisLine={false} />
                  <YAxis stroke="#94a3b8" tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={{
                      background: "rgba(2,6,23,0.95)",
                      border: "1px solid rgba(148,163,184,0.18)",
                      borderRadius: "16px",
                    }}
                  />
                  <Bar dataKey="value" radius={[12, 12, 0, 0]} fill="#22d3ee" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : null}
        </SectionCard>

        <SectionCard title="Breakdown por plataforma" subtitle="Resumo do mês corrente para cada canal monitorado.">
          <div className="space-y-3">
            {breakdown.map(([platform, item]) => (
              <article key={platform} className="rounded-2xl border border-black/8 bg-black/5 p-4">
                <div className="font-medium text-slate-900">{platform}</div>
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <Mini label="Bruto" value={money(item.total_gross)} />
                  <Mini label="Líquido" value={money(item.total_net)} />
                  <Mini label="Comissão" value={money(item.total_agency_commission)} />
                  <Mini label="Repasse" value={money(item.total_creator_payout)} />
                </div>
              </article>
            ))}
            {!breakdown.length ? <Box text="Nenhum dado financeiro disponível ainda." /> : null}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

function Box({ text }) {
  return <div className="rounded-2xl border border-dashed border-black/10 px-4 py-8 text-center text-sm text-slate-500">{text}</div>;
}

function ErrorBox({ text }) {
  return <div className="rounded-2xl border border-rose-300/20 bg-rose-400/10 px-4 py-4 text-sm text-rose-700">{text}</div>;
}

function Mini({ label, value }) {
  return (
    <div className="rounded-2xl border border-black/8 bg-slate-50/40 px-3 py-2">
      <div className="text-slate-500">{label}</div>
      <div className="mt-1 font-medium text-slate-900">{value}</div>
    </div>
  );
}

function money(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));
}
