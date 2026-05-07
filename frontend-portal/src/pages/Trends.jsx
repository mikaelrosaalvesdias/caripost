import { useCallback, useEffect, useState } from "react";
import SectionCard from "../components/SectionCard";
import { portalFetch } from "../api/client";

const POTENTIAL_COLOR = {
  viral:  "text-rose-300 border-rose-300/30 bg-rose-400/10",
  high:   "text-emerald-300 border-emerald-300/30 bg-emerald-400/10",
  medium: "text-amber-300 border-amber-300/30 bg-amber-400/10",
  low:    "text-slate-400 border-slate-400/20 bg-slate-400/8",
};
const POTENTIAL_EMOJI = { viral: "🔥", high: "⬆️", medium: "➡️", low: "⬇️" };
const DIFF_LABEL = { easy: "Fácil", medium: "Médio", hard: "Difícil" };

export default function TrendsPage() {
  const [briefings, setBriefings] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(null);

  const PAGE = 6;

  const load = useCallback(async (offset = 0, append = false) => {
    if (offset === 0) setLoading(true);
    else setLoadingMore(true);
    setError("");
    try {
      const data = await portalFetch(`/api/portal/my-trends?limit=${PAGE}&offset=${offset}`);
      const items = data?.briefings || [];
      setTotal(data?.total || 0);
      setBriefings(prev => append ? [...prev, ...items] : items);
      if (items.length && offset === 0) setExpanded(items[0].briefing_id);
    } catch (err) {
      setError(err.message || "Falha ao carregar tendências");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => { load(0); }, [load]);

  function toggleExpand(id) {
    setExpanded(prev => prev === id ? null : id);
  }

  return (
    <SectionCard
      title="Briefings de Tendências"
      subtitle="Sugestões personalizadas baseadas nos seus canais de referência e tendências da plataforma."
    >
      {loading ? <Placeholder /> : null}
      {error ? <ErrorBox text={error} /> : null}

      {!loading && !error && (
        <>
          {!briefings.length ? (
            <EmptyBox />
          ) : (
            <div className="space-y-4">
              {briefings.map((b) => (
                <BriefingCard
                  key={b.briefing_id}
                  briefing={b}
                  isOpen={expanded === b.briefing_id}
                  onToggle={() => toggleExpand(b.briefing_id)}
                />
              ))}

              {briefings.length < total && (
                <button
                  type="button"
                  onClick={() => load(briefings.length, true)}
                  disabled={loadingMore}
                  className="mt-2 w-full rounded-2xl border border-white/10 bg-white/4 py-3 text-sm text-slate-300 transition hover:bg-white/8 disabled:opacity-50"
                >
                  {loadingMore ? "Carregando..." : `Ver mais (${total - briefings.length} restantes)`}
                </button>
              )}
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}

function BriefingCard({ briefing, isOpen, onToggle }) {
  const suggestions = briefing.suggestions || [];
  const insights = briefing.top_channel_insights || [];
  const avoid = briefing.avoid || [];
  const date = String(briefing.generated_at || "").slice(0, 10);

  return (
    <article className="rounded-[26px] border border-white/10 bg-white/5 overflow-hidden">
      {/* Header — always visible */}
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left px-6 py-5 flex flex-wrap items-start justify-between gap-4"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-display text-xl font-semibold text-white">
              Briefing de {date || "data desconhecida"}
            </span>
            <span className="rounded-full border border-cyan-300/25 bg-cyan-300/10 px-3 py-1 text-xs uppercase tracking-[0.24em] text-cyan-100">
              {suggestions.length} sugestões
            </span>
            {briefing.sent_email && (
              <span className="rounded-full border border-emerald-300/20 bg-emerald-400/10 px-3 py-1 text-xs text-emerald-200">
                ✉ enviado
              </span>
            )}
          </div>
          {briefing.market_summary && (
            <p className="mt-2 text-sm leading-6 text-slate-300 line-clamp-2">
              {briefing.market_summary}
            </p>
          )}
        </div>
        <span className="text-slate-400 text-lg mt-1">{isOpen ? "▲" : "▼"}</span>
      </button>

      {/* Expanded content */}
      {isOpen && (
        <div className="border-t border-white/8 px-6 pb-6 pt-5 space-y-6">

          {/* Market summary */}
          {briefing.market_summary && (
            <div className="rounded-2xl border border-white/8 bg-slate-900/60 p-4">
              <div className="text-xs uppercase tracking-[0.28em] text-slate-500 mb-2">Resumo do mercado</div>
              <p className="text-sm leading-6 text-slate-200">{briefing.market_summary}</p>
            </div>
          )}

          {/* Creator profile analysis */}
          {briefing.creator_profile_analysis && (
            <div className="rounded-2xl border border-cyan-300/15 bg-cyan-400/6 p-4">
              <div className="text-xs uppercase tracking-[0.28em] text-cyan-300/70 mb-2">📊 Análise do seu canal</div>
              <p className="text-sm leading-6 text-cyan-100/85">{briefing.creator_profile_analysis}</p>
            </div>
          )}

          {/* Channel insights */}
          {insights.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-[0.28em] text-slate-500 mb-3">Insights dos canais de referência</div>
              <div className="grid gap-3 sm:grid-cols-2">
                {insights.map((ins, i) => (
                  <div key={i} className="rounded-2xl border border-white/8 bg-slate-900/40 p-4">
                    <div className="font-medium text-slate-100 text-sm">{ins.channel || "Canal"}</div>
                    {ins.best_format && <div className="mt-1 text-xs text-slate-400">Formato: {ins.best_format}</div>}
                    {ins.opportunity && <div className="mt-1 text-xs text-cyan-300">{ins.opportunity}</div>}
                    {(ins.top_tags || []).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {ins.top_tags.slice(0, 6).map(tag => (
                          <span key={tag} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-slate-300">{tag}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Suggestions */}
          {suggestions.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-[0.28em] text-slate-500 mb-3">Sugestões de vídeos</div>
              <div className="grid gap-4 md:grid-cols-2">
                {suggestions.map((item, index) => {
                  const potClass = POTENTIAL_COLOR[item.view_potential] || POTENTIAL_COLOR.low;
                  const potEmoji = POTENTIAL_EMOJI[item.view_potential] || "";
                  return (
                    <div key={index} className="rounded-2xl border border-white/8 bg-slate-950/45 p-4 flex flex-col gap-3">
                      <div>
                        <div className="font-semibold text-white text-sm leading-snug">{item.title || "Sugestão"}</div>
                        <div className="mt-1.5 text-xs leading-5 text-slate-300">{item.concept || ""}</div>
                      </div>

                      <div className="flex flex-wrap gap-2 items-center">
                        <span className={`rounded-full border px-2.5 py-0.5 text-xs ${potClass}`}>
                          {potEmoji} {item.view_potential || "n/a"}
                        </span>
                        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-xs text-slate-300">
                          {DIFF_LABEL[item.difficulty] || item.difficulty || "n/a"}
                        </span>
                      </div>

                      {item.why_trending && (
                        <div className="text-xs text-amber-200/80 bg-amber-400/6 border border-amber-300/10 rounded-xl px-3 py-2">
                          💡 {item.why_trending}
                        </div>
                      )}

                      {item.why_fits_creator && (
                        <div className="text-xs text-emerald-200/80 bg-emerald-400/6 border border-emerald-300/10 rounded-xl px-3 py-2">
                          ✅ {item.why_fits_creator}
                        </div>
                      )}

                      {(item.tags || []).length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {item.tags.slice(0, 10).map(tag => (
                            <span key={tag} className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-xs text-slate-300">
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}

                      {item.reference_url && (
                        <a
                          href={item.reference_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-cyan-400 hover:text-cyan-300 truncate"
                        >
                          🔗 Ver referência
                        </a>
                      )}

                      {item.image_prompt && (
                        <ImagePromptBox prompt={item.image_prompt} />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Avoid */}
          {avoid.length > 0 && (
            <div className="rounded-2xl border border-rose-300/15 bg-rose-400/6 p-4">
              <div className="text-xs uppercase tracking-[0.28em] text-rose-300/70 mb-2">⚠️ Evitar esta semana</div>
              <ul className="space-y-1">
                {avoid.map((item, i) => (
                  <li key={i} className="text-sm text-rose-100/80">• {item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function ImagePromptBox({ prompt }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard.writeText(prompt).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }
  return (
    <div className="rounded-xl border border-violet-400/15 bg-violet-500/6 px-3 py-2 flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs uppercase tracking-[0.24em] text-violet-300/70">🖼 Prompt thumbnail IA</span>
        <button
          type="button"
          onClick={copy}
          className="rounded-lg border border-violet-400/20 bg-violet-500/10 px-2.5 py-0.5 text-xs text-violet-200 hover:bg-violet-500/20 transition"
        >
          {copied ? "✓ Copiado" : "Copiar"}
        </button>
      </div>
      <p className="text-xs text-slate-400 leading-5 line-clamp-3">{prompt}</p>
    </div>
  );
}

function Placeholder() {
  return (
    <div className="space-y-4">
      {[1, 2].map(i => (
        <div key={i} className="rounded-[26px] border border-white/8 bg-white/4 h-28 animate-pulse" />
      ))}
    </div>
  );
}

function EmptyBox() {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 px-6 py-10 text-center space-y-2">
      <div className="text-2xl">📊</div>
      <div className="text-sm text-slate-300">Ainda não há briefings gerados para você.</div>
      <div className="text-xs text-slate-500">Os briefings são gerados semanalmente com base nos seus canais de referência.</div>
    </div>
  );
}

function ErrorBox({ text }) {
  return (
    <div className="rounded-2xl border border-rose-300/20 bg-rose-400/10 px-4 py-4 text-sm text-rose-100">
      ⚠️ {text}
    </div>
  );
}
