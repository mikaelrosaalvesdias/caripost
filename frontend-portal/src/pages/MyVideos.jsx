import { useEffect, useState } from "react";
import { portalFetch } from "../api/client";
import SectionCard from "../components/SectionCard";
import StatusPill from "../components/StatusPill";

export default function MyVideosPage() {
  const [videos, setVideos] = useState([]);
  const [selected, setSelected] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await portalFetch("/api/portal/my-videos?page=1&limit=24&sort=date");
        if (!alive) return;
        setVideos(data?.videos || []);
      } catch (err) {
        if (!alive) return;
        setError(err.message || "Falha ao carregar vídeos");
      } finally {
        if (alive) setLoading(false);
      }
    }
    load();
    return () => {
      alive = false;
    };
  }, []);

  async function openStats(video) {
    setSelected(video);
    setStats(null);
    try {
      const payload = await portalFetch(`/api/portal/my-videos/${encodeURIComponent(video.video_id)}/stats`);
      setStats(payload);
    } catch (err) {
      setStats({ error: err.message || "Falha ao carregar stats do vídeo." });
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
      <SectionCard title="Meus vídeos" subtitle="Últimos títulos, plataformas e desempenho consolidado.">
        {loading ? <Box text="Carregando vídeos..." /> : null}
        {error ? <ErrorBox text={error} /> : null}
        {!loading && !error ? (
          <div className="grid gap-4 md:grid-cols-2">
            {videos.map((video, index) => (
              <article
                key={video.publication_id || video.video_id || index}
                className="rounded-[24px] border border-white/10 bg-white/5 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-medium text-white">{video.title || "Vídeo sem título"}</div>
                    <div className="mt-2 text-sm text-slate-400">
                      {(video.platforms || []).join(", ") || video.platform || "Sem plataforma"}
                    </div>
                  </div>
                  <StatusPill value={video.status || "done"} />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-300">
                  <div className="rounded-2xl border border-white/8 bg-slate-950/40 px-3 py-2">
                    <div className="text-slate-500">Views</div>
                    <div className="mt-1 text-base font-medium text-white">{formatNumber(video.total_views || video.views || 0)}</div>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-slate-950/40 px-3 py-2">
                    <div className="text-slate-500">Publicação</div>
                    <div className="mt-1 text-base font-medium text-white">{video.published_at ? String(video.published_at).slice(0, 10) : "n/a"}</div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => openStats(video)}
                  className="mt-4 rounded-2xl border border-cyan-300/25 bg-cyan-300/10 px-4 py-2 text-sm text-cyan-100 transition hover:bg-cyan-300/18"
                >
                  Ver stats detalhados
                </button>
              </article>
            ))}
            {!videos.length ? <Box text="Nenhum vídeo publicado ainda." /> : null}
          </div>
        ) : null}
      </SectionCard>

      <SectionCard title="Detalhes" subtitle="Comparativo por plataforma para o vídeo selecionado.">
        {!selected ? <Box text="Selecione um vídeo para ver o histórico por plataforma." /> : null}
        {selected ? (
          <div className="space-y-4">
            <div>
              <div className="font-medium text-white">{selected.title || "Vídeo"}</div>
              <div className="mt-1 text-sm text-slate-400">{selected.video_id || selected.publication_id || ""}</div>
            </div>
            {stats?.error ? <ErrorBox text={stats.error} /> : null}
            {(stats?.latest_by_platform ? Object.entries(stats.latest_by_platform) : []).map(([platform, item]) => (
              <article key={platform} className="rounded-2xl border border-white/8 bg-white/5 p-4">
                <div className="font-medium text-white">{platform}</div>
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <Mini label="Views" value={formatNumber(item.total_views || item.views || 0)} />
                  <Mini label="Likes" value={formatNumber(item.likes || 0)} />
                  <Mini label="Comentários" value={formatNumber(item.comments || 0)} />
                  <Mini label="Rating" value={String(item.rating || 0)} />
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </SectionCard>
    </div>
  );
}

function Box({ text }) {
  return <div className="rounded-2xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-400">{text}</div>;
}

function ErrorBox({ text }) {
  return <div className="rounded-2xl border border-rose-300/20 bg-rose-400/10 px-4 py-4 text-sm text-rose-100">{text}</div>;
}

function Mini({ label, value }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-slate-950/40 px-3 py-2">
      <div className="text-slate-500">{label}</div>
      <div className="mt-1 font-medium text-white">{value}</div>
    </div>
  );
}

function formatNumber(value) {
  return new Intl.NumberFormat("pt-BR").format(Number(value || 0));
}
