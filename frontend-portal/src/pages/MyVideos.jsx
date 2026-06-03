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
    return () => { alive = false; };
  }, []);

  async function openStats(video) {
    setSelected(video);
    setStats(null);
    try {
      const payload = await portalFetch(`/api/portal/my-videos/${encodeURIComponent(video.video_id)}/stats`);
      setStats(payload);
    } catch (err) {
      setStats({ error: err.message || "Falha ao carregar stats." });
    }
  }

  return (
    <div style={{ display: "grid", gap: 20, gridTemplateColumns: "1fr" }}>
      <SectionCard title="Meus vídeos" subtitle="Últimos títulos, plataformas e desempenho.">
        {loading ? <div className="portal-empty">Carregando vídeos...</div> : null}
        {error ? <ErrorBox text={error} /> : null}
        {!loading && !error ? (
          <div style={{ display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
            {videos.map((video, index) => (
              <article
                key={video.publication_id || video.video_id || index}
                className="portal-video-card"
              >
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontWeight: 600, color: "#fff", fontSize: 13.5, lineHeight: 1.3 }}>
                      {video.title || "Vídeo sem título"}
                    </div>
                    <div style={{ fontSize: 12, color: "var(--portal-muted)", marginTop: 4 }}>
                      {(video.platforms || []).join(", ") || video.platform || "Sem plataforma"}
                    </div>
                  </div>
                  <StatusPill value={video.status || "done"} />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 14 }}>
                  <div className="portal-mini-stat">
                    <div className="portal-mini-stat-label">Views</div>
                    <div className="portal-mini-stat-value">{formatNumber(video.total_views || video.views || 0)}</div>
                  </div>
                  <div className="portal-mini-stat">
                    <div className="portal-mini-stat-label">Publicação</div>
                    <div className="portal-mini-stat-value">{video.published_at ? String(video.published_at).slice(0, 10) : "n/a"}</div>
                  </div>
                </div>
                <button
                  type="button"
                  className="portal-btn portal-btn-secondary portal-btn-sm"
                  style={{ width: "100%", marginTop: 12 }}
                  onClick={() => openStats(video)}
                >
                  Ver stats por plataforma
                </button>
              </article>
            ))}
            {!videos.length ? <Box text="Nenhum vídeo publicado ainda." /> : null}
          </div>
        ) : null}
      </SectionCard>

      {selected ? (
        <SectionCard title={selected.title || "Vídeo"} subtitle="Comparativo por plataforma.">
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {stats?.error ? <ErrorBox text={stats.error} /> : null}
            {(stats?.latest_by_platform ? Object.entries(stats.latest_by_platform) : []).map(([platform, item]) => (
              <article key={platform} className="portal-video-card">
                <div style={{ fontWeight: 600, color: "var(--portal-primary)", fontSize: 13, marginBottom: 12 }}>{platform}</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: 10 }}>
                  <MiniStat label="Views" value={formatNumber(item.total_views || item.views || 0)} />
                  <MiniStat label="Likes" value={formatNumber(item.likes || 0)} />
                  <MiniStat label="Comentários" value={formatNumber(item.comments || 0)} />
                  <MiniStat label="Rating" value={String(item.rating || 0)} />
                </div>
              </article>
            ))}
          </div>
        </SectionCard>
      ) : null}
    </div>
  );
}

function Box({ text }) {
  return <div className="portal-empty">{text}</div>;
}
function ErrorBox({ text }) {
  return <div style={{ padding: "14px 16px", borderRadius: 12, background: "rgba(248,113,113,.08)", border: "1px solid rgba(248,113,113,.2)", color: "#fca5a5", fontSize: 13 }}>{text}</div>;
}
function MiniStat({ label, value }) {
  return (
    <div className="portal-mini-stat">
      <div className="portal-mini-stat-label">{label}</div>
      <div className="portal-mini-stat-value">{value}</div>
    </div>
  );
}
function formatNumber(value) {
  return new Intl.NumberFormat("pt-BR").format(Number(value || 0));
}
