/* Caripost OS — Fluxo de Conteúdo (standalone, fora do cliente)
   Passos: 0 Cliente · 1 Briefing · 2 Criação · 3 Aprovação · 4 Agendamento
   Reaproveita os endpoints existentes (social/companies/posts). */

// Modelos de imagem agrupados por PROVEDOR (OmniRoute/CometAPI/PiAPI/OpenRouter) — seletor provedor+modelo.
const IMG_PROV_LABELS = { omniroute: 'OmniRoute (grátis · assinatura)', cometapi: 'CometAPI', piapi: 'PiAPI', openrouter: 'OpenRouter' };
function imgGroups(list) {
  const g = {}; (list || []).forEach(m => { const p = m.provider || 'outros'; (g[p] = g[p] || []).push(m); });
  return Object.keys(g).map(p => ({ provider: p, label: IMG_PROV_LABELS[p] || p, models: g[p] }));
}
function imgOptLabel(m) { return m.name + (m.price_brl ? ' · R$ ' + Number(m.price_brl).toFixed(2) : (m.free ? ' · grátis' : '')); }

function _videoNum(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function _videoProviderPct(s) {
  let p = _videoNum(s && s.provider_progress);
  if (p == null) return null;
  if (p > 0 && p <= 1) p *= 100;
  return Math.max(0, Math.min(100, p));
}
function _videoProgressPct(s, fallbackTotal, startedAt, lastPct) {
  const total = Math.max(1, _videoNum(s && s.total) || fallbackTotal || 1);
  const scene = Math.max(1, Math.min(total, _videoNum(s && s.scene) || 1));
  const providerPct = _videoProviderPct(s);
  let inside = providerPct;
  if (inside == null || inside <= 0) {
    const prov = String((s && s.provider) || '').toLowerCase();
    const perSceneMs = prov === 'cometapi' ? 20 * 60 * 1000 : 8 * 60 * 1000;
    const elapsed = Math.max(0, Date.now() - (startedAt || Date.now()));
    inside = Math.min(85, Math.max(8, ((elapsed % perSceneMs) / perSceneMs) * 85));
  }
  const pct = 5 + (((scene - 1) + Math.min(0.98, inside / 100)) / total) * 88;
  return Math.max(lastPct || 0, Math.min(92, pct));
}
function _videoStatusDetail(s, fallbackTotal, costText) {
  const total = Math.max(1, _videoNum(s && s.total) || fallbackTotal || 1);
  const scene = Math.max(1, Math.min(total, _videoNum(s && s.scene) || 1));
  const provider = s && s.provider ? ' · ' + String(s.provider) : '';
  const pstatus = s && s.provider_status ? ' · status: ' + String(s.provider_status).replace(/_/g, ' ') : '';
  const ppct = _videoProviderPct(s);
  const prog = ppct != null && ppct > 0 ? ' · provedor ' + Math.round(ppct) + '%' : '';
  const cost = costText ? ' · ' + costText : '';
  return 'Gerando cena ' + scene + '/' + total + ' (com áudio)' + provider + pstatus + prog + cost;
}
function _videoCostText(s, brl) {
  const label = s && s.cost_source === 'catalog_estimate' ? 'custo estimado' : 'gasto';
  return label + ' ' + brl(s && s.cost_usd);
}

function VideoCreator({ company }) {
  const st = ContState.get(company.id);
  const theme = ((st.briefing || '').trim() || (st.assunto || '').trim());
  const [dur, setDur] = React.useState(st.videoSeconds || 0);
  const [vmodels, setVmodels] = React.useState([]);
  const [model, setModel] = React.useState('');
  const [pf, setPf] = React.useState(null);
  const [planning, setPlanning] = React.useState(false);
  const [status, setStatus] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [proc, setProc] = React.useState({ open: false });   // mesma animação (ProcessModal) da geração de imagem
  const videoStartRef = React.useRef(0);
  const lastPctRef = React.useRef(3);
  const brl = (usd) => {
    const rate = pf && Number(pf.total_usd) > 0 && Number(pf.total_brl) > 0
      ? Number(pf.total_brl) / Number(pf.total_usd)
      : 5.15;
    return 'R$ ' + (Number(usd || 0) * rate).toFixed(2);
  };
  React.useEffect(() => {
    window.mpApi.aiModels().then(r => { const v = r.video || []; setVmodels(v); setModel(m => m || r.video_current || (v[0] && v[0].id) || ''); }).catch(() => {});
  }, []);
  React.useEffect(() => {
    if (!model || !theme) return;
    setPlanning(true);
    window.mpApi.videoPreflight(company.id, theme, dur).then(setPf).catch(() => {}).finally(() => setPlanning(false));
  }, [model, dur]);   // custo AUTOMÁTICO (sem botão "calcular")
  async function selectModel(id) { setModel(id); setPf(null); try { await window.mpApi.setAiModel({ video_model: id }); } catch (e) {} }
  function setDuration(d) { setDur(d); ContState.set(company.id, { videoSeconds: d }); }
  async function gerar() {
    if (!pf || !pf.configured) { setMsg('Erro: escolha um modelo de vídeo (configure a chave no painel de IA).'); return; }
    if (!window.confirm('O briefing virou ' + pf.scenes + ' cena(s) (~' + pf.total_seconds + 's) ≈ R$ ' + pf.total_brl + '.\n\nISSO GASTA DINHEIRO REAL. Confirmar?')) return;
    setBusy(true); setMsg(''); setStatus(null);
    videoStartRef.current = Date.now();
    lastPctRef.current = 3;
    setProc({ open: true, pct: 3, detail: 'Iniciando a geração do vídeo…', phase: '' });
    try {
      const sceneSeconds = pf.seconds_per_scene || ((pf.scene_seconds || [])[0]) || 8;
      const r = await window.mpApi.generateBrandedVideo({ company_id: company.id, theme, storyboard: pf.storyboard, seconds: sceneSeconds });
      if (!r || !r.job) { setProc({ open: true, phase: 'error', detail: ((r && r.detail) || 'não consegui iniciar') }); setBusy(false); return; }
      const tot = r.scenes || pf.scenes || 1;
      for (let i = 0; i < 360; i++) {
        await new Promise(res => setTimeout(res, 6000));
        const s = await window.mpApi.brandedVideoStatus(company.id, r.job);
        setStatus(s);
        if (s.status === 'generating') {
          const pct = _videoProgressPct(s, tot, videoStartRef.current, lastPctRef.current);
          lastPctRef.current = pct;
          setProc({ open: true, pct, detail: _videoStatusDetail(s, tot, _videoCostText(s, brl)), phase: '' });
        }
        else if (s.status === 'composing') { lastPctRef.current = 95; setProc({ open: true, pct: 95, detail: 'Juntando as cenas em 1 vídeo só + logo e CTA da marca…', phase: '' }); }
        else if (s.status === 'done') {
          const costLabel = s.cost_source === 'catalog_estimate' ? 'Custo estimado' : 'Custo REAL';
          setProc({ open: true, pct: 100, phase: 'done', detail: 'Vídeo pronto! ' + costLabel + ': ' + brl(s.cost_usd) });
          setBusy(false); return;
        }
        else if (s.status === 'error') { setProc({ open: true, phase: 'error', detail: (s.detail || 'falhou') + ' · ' + _videoCostText(s, brl) }); setBusy(false); return; }
      }
      setProc({ open: true, phase: 'error', detail: 'Demorando demais — recarregue a página pra ver o status.' }); setBusy(false);
    } catch (e) { setProc({ open: true, phase: 'error', detail: e.message }); setBusy(false); }
  }
  const DURS = [[0, 'Livre (IA decide)'], [8, '8s'], [15, '15s'], [30, '30s'], [60, '60s']];
  const PLAB = { cometapi: 'CometAPI', openrouter: 'OpenRouter', openai: 'OpenAI' };
  const vgroups = (() => { const g = {}; vmodels.forEach(m => { const p = m.provider || 'outros'; (g[p] = g[p] || []).push(m); }); return Object.keys(g).map(p => ({ provider: p, label: PLAB[p] || p, models: g[p] })); })();
  const vlabel = (m) => (m.name || m.id) + (m.quality ? ' (' + m.quality + ')' : '') + (m.max_seconds ? ' · até ' + m.max_seconds + 's' : '') + (m.price_brl ? ' · R$ ' + Number(m.price_brl).toFixed(2) + '/clipe' : '');
  if (!theme) return <div className="panel stack"><div className="hint">Volte ao Briefing, escreva o assunto e gere o roteiro do vídeo primeiro.</div></div>;
  return <div className="panel stack">
    <div className="sec"><Icon name="video" />Gerar vídeo branded (9:16, com áudio)</div>
    <Field label="Duração — TRAVE quantos segundos quer, ou deixe LIVRE pra IA decidir pelo briefing">
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {DURS.map(([v, t]) => <button key={v} className={'btn sm' + (dur === v ? ' pri' : ' ghost')} onClick={() => setDuration(v)}>{t}</button>)}
      </div>
    </Field>
    <Field label="Modelo de VÍDEO (OpenRouter / CometAPI)">
      <select className="inp" value={model} onChange={e => selectModel(e.target.value)}>
        {vgroups.length ? vgroups.map(g => <optgroup key={g.provider} label={g.label}>
          {g.models.map(m => <option key={m.id} value={m.id}>{vlabel(m)}</option>)}
        </optgroup>) : <option value="">Configure CometAPI/OpenRouter no painel de IA</option>}
      </select>
    </Field>
    <div className="sec mut">Assunto: {theme.slice(0, 100)}</div>
    {planning && <div className="hint">Montando o roteiro e calculando o custo…</div>}
    {pf && pf.configured && !planning && <div className="hint">→ <b>{pf.scenes} cena(s)</b> (~{pf.total_seconds}s) · custo estimado ≈ <b>R$ {pf.total_brl}</b> <span style={{ opacity: .7 }}>(o real vem ao final). As cenas viram <b>1 vídeo só</b>.</span></div>}
    {pf && !pf.configured && !planning && <div className="hint" style={{ color: 'var(--pri)' }}>⚠ Escolha um modelo de vídeo acima (e configure a chave no painel de IA).</div>}
    {status && status.status === 'done' && status.url && <video src={status.url} controls style={{ width: '100%', maxWidth: 300, borderRadius: 12 }} />}
    {msg && <div className={(msg.startsWith('Erro') || msg.startsWith('Falhou')) ? 'err' : 'ok'}>{msg}</div>}
    <button className="btn pri" disabled={busy || !pf || !pf.configured} onClick={gerar}>{busy ? 'Gerando… (pode levar minutos)' : ('Gerar vídeo' + (pf && pf.total_brl ? ' (≈ R$ ' + pf.total_brl + ')' : ''))}</button>
    {proc.open && <ProcessModal open={proc.open} title="Gerando vídeo" detail={proc.detail} pct={proc.pct} phase={proc.phase} onClose={() => setProc({ open: false })} />}
  </div>;
}

const CONT_STEPS = [
  { k: 'cliente', ic: 'users', t: 'Cliente' },
  { k: 'briefing', ic: 'sparkles', t: 'Briefing' },
  { k: 'criacao', ic: 'image', t: 'Criação' },
  { k: 'aprovacao', ic: 'shield', t: 'Aprovação' },
  { k: 'agenda', ic: 'calendar', t: 'Agendamento' },
];

const CONT_NETS = ['instagram', 'facebook'];

function ConteudoApp() {
  const [i, setI] = React.useState(0);
  const [companyId, setCompanyId] = React.useState('');
  const [company, setCompany] = React.useState(null);
  const [pjKey, setPjKey] = React.useState(0);   // muda ao abrir/criar projeto → remonta Briefing/Criação (lê o projeto ativo)

  const canNext = (() => {
    if (i === 0) return !!companyId;
    return true;
  })();

  function Steps() {
    return <div className="wiz-steps">
      {CONT_STEPS.map((s, idx) => <React.Fragment key={s.k}>
        <button className={'wstep' + (idx < i ? ' done' : idx === i ? ' on' : '')}
          onClick={() => { if (idx === 0 || companyId) setI(idx); }}>
          <span className="wd">{idx < i ? <Icon name="check" style={{ width: 12, height: 12 }} /> : idx + 1}</span>{s.t}
        </button>
        {idx < CONT_STEPS.length - 1 && <span className={'wsep' + (idx < i ? ' done' : '')} />}
      </React.Fragment>)}
    </div>;
  }

  return <div className="app">
    <div className="app-head">
      <div className="tb-ic" style={{ width: 40, height: 40, borderRadius: 12 }}><Icon name="post" style={{ width: 20, height: 20 }} /></div>
      <div className="lead">
        <div className="app-title">Fluxo de Conteúdo</div>
        <div className="app-desc">Briefing → criação → aprovação → agendamento. Sem entrar no cliente.</div>
      </div>
      {company && <Pill kind="cy" dot>{company.name}</Pill>}
    </div>

    <Steps />

    <div className="panel stack" style={{ minHeight: 320 }}>
      {i === 0 && <StepCliente companyId={companyId}
        onPick={(id, c) => { setCompanyId(id); setCompany(c); ContState.novo(id); /* entra LIMPO */ }}
        onContinue={() => { setPjKey(k => k + 1); setI(1); }} />}
      {i === 1 && company && <StepBriefing key={companyId + ':' + pjKey} company={company} />}
      {i === 2 && company && <StepCriacao key={companyId + ':' + pjKey} company={company} />}
      {i === 3 && company && <StepAprovacao company={company} />}
      {i === 4 && company && <StepAgenda company={company} />}
    </div>

    <div className="rowx" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
      <button className="btn ghost" disabled={i === 0} onClick={() => setI(Math.max(0, i - 1))}><Icon name="play" style={{ transform: 'rotate(180deg)' }} />Voltar</button>
      {i === CONT_STEPS.length - 1
        ? <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button className="btn" onClick={() => setI(1)}><Icon name="bolt" />Criar novo conteúdo</button>
            <button className="btn pri" onClick={() => window.__mpOpen && window.__mpOpen('painel')}><Icon name="grid" />Voltar ao painel</button>
          </div>
        : <button className="btn pri" disabled={!canNext} onClick={() => setI(Math.min(CONT_STEPS.length - 1, i + 1))}>Próximo<Icon name="play" /></button>}
    </div>
  </div>;
}

/* ── Passo 0: Cliente ── */
function StepCliente({ companyId, onPick, onContinue }) {
  const [companies, setCompanies] = React.useState([]);
  const [q, setQ] = React.useState('');
  const [accounts, setAccounts] = React.useState([]);
  const [posts, setPosts] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [projetos, setProjetos] = React.useState([]);   // trabalhos salvos desta empresa (caixinhas p/ continuar)
  React.useEffect(() => { setProjetos(companyId ? ContState.projetos(companyId) : []); }, [companyId]);
  function continuar(pid) { ContState.abrir(companyId, pid); onContinue && onContinue(); }      // CONTINUAR projeto salvo
  function novoProjeto() { ContState.novo(companyId); onContinue && onContinue(); }              // começar LIMPO
  function excluirPj(pid) { if (!window.confirm('Excluir este projeto salvo?')) return; ContState.excluir(companyId, pid); setProjetos(ContState.projetos(companyId)); }
  function continuarDb(p, urls) {   // reabre um carrossel do ACERVO (banco) como projeto → traz as artes pra Criação
    const m = p.meta || {};
    const ex = ContState.projetos(companyId).find(pj => (pj.carouselResults || []).some(v => v.post_id === p.id));
    if (ex) { continuar(ex.id); return; }
    ContState.novo(companyId);
    ContState.set(companyId, {
      carouselResults: [{ model: m.model || 'editorial', slides: (urls || []).map(u => ({ url: u })), cost: 0, post_id: p.id }],
      telas: [], assunto: p.title || '', assuntoTema: p.title || '', briefing: '',
      formato: m.content_type === 'carousel' ? 'carrossel' : (m.content_type || 'post'), copy: p.copy, hashtags: p.hashtags,
    });
    onContinue && onContinue();
  }
  const _lsIds = new Set(projetos.flatMap(p => (p.carouselResults || []).map(v => v.post_id).filter(Boolean)));
  const _db = (posts || []).map(p => {
    const m = p.meta || {}; const urls = (m.carousel_urls && m.carousel_urls.length) ? m.carousel_urls : (p.media_url ? [p.media_url] : []);
    return urls.length ? { __db: true, _post: p, _urls: urls, id: 'db_' + p.id, label: p.title || 'Post',
      fmt: m.content_type === 'carousel' ? 'carrossel' : (m.content_type || 'post'), nArtes: urls.length,
      ts: p.created_at ? (Date.parse(p.created_at) || 0) : 0, thumb: urls[0] } : null;
  }).filter(x => x && !_lsIds.has(x._post.id));
  const caixas = [...projetos.map(p => ({ ...p, thumb: ((((p.carouselResults || [])[0] || {}).slides || [])[0] || {}).url })), ..._db].sort((a, b) => (b.ts || 0) - (a.ts || 0));

  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.listCompanies().then(r => { setCompanies(r || []); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  React.useEffect(() => {
    if (!companyId || !window.mpApi) { setAccounts([]); setPosts([]); return; }
    window.mpApi.socialAccounts(companyId).then(a => setAccounts(a || [])).catch(() => {});
    window.mpApi.listPosts().then(r => setPosts((r.posts || []).filter(p => p.company_id === companyId).slice(0, 50))).catch(() => {});
  }, [companyId]);

  const filtered = companies.filter(c => (c.name || c.n || '').toLowerCase().includes(q.toLowerCase()));

  async function pick(c) {
    const id = c.id || c.company_id;
    let full = c;
    try { full = await window.mpApi.getCompany(id); } catch (e) {}
    onPick(id, full);
  }

  return <div className="split">
    <div className="stack">
      <Field label="Buscar cliente"><input className="inp" value={q} onChange={e => setQ(e.target.value)} placeholder="Nome do cliente…" /></Field>
      {loading && <div className="hint">Carregando clientes…</div>}
      <div className="stack" style={{ maxHeight: 320, overflow: 'auto' }}>
        {filtered.map(c => {
          const id = c.id || c.company_id;
          return <div key={id} className={'litem' + (id === companyId ? ' on' : '')} style={{ padding: 10, cursor: 'pointer', borderColor: id === companyId ? 'var(--pri)' : undefined }} onClick={() => pick(c)}>
            <span className="li-ic"><Icon name="users" /></span>
            <div className="li-main"><b>{c.name || c.n}</b><small>{c.segment || ''}</small></div>
            {id === companyId && <Pill kind="good" dot>selecionado</Pill>}
          </div>;
        })}
        {!loading && !filtered.length && <div className="hint">Nenhum cliente. Cadastre em Clientes.</div>}
      </div>
    </div>
    <div className="stack">
      <div className="sec mut">Conexões</div>
      {!companyId && <div className="hint">Selecione um cliente.</div>}
      {companyId && CONT_NETS.map(p => {
        const acc = accounts.find(a => a.platform === p);
        const ok = acc && (acc.status === 'connected' || acc.status === 'active');
        return <div key={p} className="litem" style={{ padding: 8 }}>
          <div className="li-main"><b style={{ textTransform: 'capitalize' }}>{p}</b></div>
          <Pill kind={ok ? 'good' : acc ? 'warn' : ''} dot>{acc ? acc.status : 'não conectado'}</Pill>
        </div>;
      })}
      {companyId && <button className="btn sm ghost" onClick={() => window.__mpOpen && window.__mpOpen('clientes')}><Icon name="pen" />Editar cliente/produtos</button>}
      {companyId && <>
        <div className="sec mut" style={{ marginTop: 8 }}>Continuar de onde parou?</div>
        <div className="hint">Marque um trabalho salvo pra continuar (briefing + artes prontos), ou comece do zero.</div>
        <div className="stack" style={{ maxHeight: 280, overflow: 'auto' }}>
          {caixas.map(c => <div key={c.id} className="litem" style={{ padding: 8, cursor: 'pointer' }} onClick={() => c.__db ? continuarDb(c._post, c._urls) : continuar(c.id)} title="Continuar este trabalho">
            {c.thumb ? <img loading="lazy" decoding="async" src={c.thumb} style={{ width: 42, height: 52, borderRadius: 6, objectFit: 'cover', flex: 'none' }} /> : <span className="li-ic"><Icon name="post" /></span>}
            <div className="li-main"><b>{c.label || 'Projeto'}</b><small>{(c.fmt || 'carrossel')} · {c.nArtes || 0} arte(s){c.__db ? ' · acervo' : ''} · {c.ts ? new Date(c.ts).toLocaleDateString() : ''}</small></div>
            {!c.__db && <button className="btn sm ghost" onClick={e => { e.stopPropagation(); excluirPj(c.id); }} title="Excluir"><Icon name="trash" /></button>}
          </div>)}
          {!caixas.length && <div className="hint">Nenhum trabalho salvo ainda.</div>}
        </div>
        <button className="btn sm pri" onClick={novoProjeto}><Icon name="bolt" />Começar do zero (novo)</button>
      </>}
    </div>
  </div>;
}

/* ── Passo 1: Briefing ── */
function StepBriefing({ company }) {
  const st = ContState.get(company.id);
  const [mode, setMode] = React.useState(st.briefingMode || 'auto');
  const [briefing, setBriefing] = React.useState(st.briefing || '');
  const [objetivo, setObjetivo] = React.useState(st.objetivo || 'vender');
  const [tom, setTom] = React.useState(st.tom || (company.brand_kit || {}).voice || '');
  const [cta, setCta] = React.useState(st.cta || '');
  const [networks, setNetworks] = React.useState(st.networks || ['instagram']);
  const [products, setProducts] = React.useState([]);
  const [sources, setSources] = React.useState(st.sources || {});
  const [ideasCount, setIdeasCount] = React.useState(st.ideasCount || 5);
  const [assunto, setAssunto] = React.useState(st.assunto || '');
  const [formato, setFormato] = React.useState(st.formato || 'carrossel');
  const [vsec, setVsec] = React.useState(st.videoSeconds || 0);   // duração do vídeo (0=livre) — TRAVA o briefing
  const [intent, setIntent] = React.useState(st.intent || 'produtos');   // MODO: produtos | evento | criativo
  const [eventId, setEventId] = React.useState(st.eventId || '');
  const [events, setEvents] = React.useState([]);
  React.useEffect(() => { window.mpApi.listEvents(company.id).then(l => setEvents(l || [])).catch(() => {}); }, [company.id]);
  const INTENTS = [['produtos', 'Produtos / institucional'], ['evento', 'Divulgar evento'], ['criativo', 'Criativo livre (meme/data)']];
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const assuntoList = (((company.brand_kit || {}).assuntos) || '').split('\n').map(s => s.trim()).filter(Boolean);
  const FORMATOS = [['carrossel', 'Carrossel'], ['post', 'Post fixo'], ['story', 'Story'], ['video', 'Vídeo']];
  const fmtLabel = { carrossel: 'plano de telas', video: 'roteiro', post: 'pauta', story: 'arte de story' }[formato] || 'plano';

  React.useEffect(() => {
    window.mpApi.listProducts(company.id).then(p => {
      setProducts(p || []);
      if (!st.sources) { const all = {}; (p || []).forEach(x => all[x.id] = true); setSources(all); }
    }).catch(() => {});
  }, [company.id]);

  function persist(patch) { ContState.set(company.id, { briefingMode: mode, briefing, objetivo, tom, cta, networks, sources, assunto, formato, intent, eventId, ...patch }); }

  function pushBlock(blocks, g, label) {
    const idea = (g.headline || g.title || '').trim() || label;
    const sub = (g.subheadline || '').trim();
    const bens = (g.benefits || []).join(' · ');
    const vis = (g.visual_prompt || '').trim();
    blocks.push(`${blocks.length + 1}. ${label} — ${idea}`
      + (sub ? `\n   Mensagem: ${sub}` : '')
      + (bens ? `\n   Destaques: ${bens}` : '')
      + (vis ? `\n   Visual: ${vis}` : ''));
  }

  async function gen1(brief, net) {
    let g = null;
    for (let attempt = 0; attempt < 2 && !g; attempt++) {
      try { g = await window.mpApi.generatePostAI({ company_id: company.id, briefing: brief, networks: [net] }); }
      catch (_) { /* tenta de novo */ }
    }
    return g;
  }

  async function gerarAuto() {
    const selProds = products.filter(p => sources[p.id]);
    const seed = (assunto || '').trim();
    if (!selProds.length && !seed) { setMsg('Marque um app em "Fontes" OU escreva/escolha um assunto.'); return; }
    if (intent === 'evento' && !eventId) { setMsg('Modo "Divulgar evento" precisa de um evento cadastrado selecionado (senão a IA inventaria datas). Escolha o evento ou troque o modo.'); return; }
    setBusy(true);
    try {
      // ASSUNTO definido → PLANO COMPLETO adaptado ao OBJETIVO + FORMATO (telas/roteiro/pauta)
      if (seed) {
        setMsg(`Montando ${fmtLabel} sobre "${seed}" (objetivo: ${objetivo}, formato: ${formato})…`);
        // post/story = 1 arte RICA (capa pela máquina do carrossel, no backend); carrossel = plano completo.
        const isSingle = formato === 'post' || formato === 'story';
        const r = await window.mpApi.generateBriefing({ company_id: company.id, theme: seed, objetivo, formato, n_telas: isSingle ? 1 : 0, intent, event_id: eventId, apps: selProds.map(p => p.name), seconds: (formato === 'video' ? vsec : 0) });
        const text = ((r && r.briefing) || '').trim();
        if (!text) { setMsg('Não consegui gerar agora. Tente de novo.'); return; }
        let tl = (r && r.telas) || [];
        if (isSingle && !tl.length) {   // garante 1 tela "capa" pra render mesmo se o briefing só devolveu texto
          const hook = (text.split('\n').map(s => s.trim()).find(Boolean) || seed).slice(0, 64);
          tl = [{ type: 'cover', eyebrow: (objetivo || 'Oferta'), title: hook }];
        } else if (isSingle) {
          tl = [tl[0]];   // 1 arte só
        }
        setBriefing(text); persist({ briefing: text, telas: tl, formato, assuntoTema: seed });
        setMsg(`Briefing (${fmtLabel}) pronto — revise e vá para Criação${formato === 'carrossel' ? ' (modo Carrossel com ' + tl.length + ' telas)' : ' (1 arte ' + (formato === 'story' ? '9:16' : '4:5') + ')'}.`);
        return;
      }
      // sem assunto → pautas pelos apps marcados
      const net = networks[0] || 'instagram';
      const blocks = [];
      const recipe = 'Crie uma PAUTA FORTE e CRIATIVA: um gancho marcante (headline), o ângulo (pra quem fala), '
        + 'os destaques (benefits) e principalmente uma CENA VISUAL concreta, cinematográfica e original '
        + '(ambiente, ação, clima e luz — fuja de clichê de banco de imagem).';
      for (let i = 0; i < selProds.length; i++) {
        const p = selProds[i];
        setMsg(`Gerando pauta ${i + 1}/${selProds.length} — ${p.name}…`);
        const brief = `Objetivo: ${objetivo}${cta ? ' · CTA: ' + cta : ''}. App em foco: "${p.name}". ${p.objective || ''} ` + recipe;
        const g = await gen1(brief, net);
        if (g) pushBlock(blocks, g, p.name);
      }
      if (!blocks.length) { setMsg('Não consegui gerar agora. Tente de novo ou escreva o briefing manual.'); return; }
      const text = 'Pautas (apps selecionados):\n\n' + blocks.join('\n\n');
      setBriefing(text); persist({ briefing: text });
      setMsg(`${blocks.length} pauta(s) rica(s) gerada(s). Revise e siga para Criação.`);
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  return <div className="split">
    <div className="stack">
      <div className="row" style={{ gap: 8 }}>
        <button className={'btn sm' + (mode === 'auto' ? ' pri' : ' ghost')} onClick={() => { setMode('auto'); persist({ briefingMode: 'auto' }); }}>Automático</button>
        <button className={'btn sm' + (mode === 'manual' ? ' pri' : ' ghost')} onClick={() => { setMode('manual'); persist({ briefingMode: 'manual' }); }}>Manual</button>
      </div>
      {mode === 'auto' && <Field label="Assunto / pauta (foca a IA no tema — opcional)">
        <input className="inp" value={assunto} onChange={e => { setAssunto(e.target.value); persist({ assunto: e.target.value }); }} placeholder="Ex.: segurança digital para a família" />
        {assuntoList.length > 0 && <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
          {assuntoList.map((a, i) => <button key={i} className={'btn sm' + (assunto === a ? ' pri' : ' ghost')} onClick={() => { setAssunto(a); persist({ assunto: a }); }}>{a}</button>)}
        </div>}
        {!assuntoList.length && <small className="hint">Cadastre assuntos do cliente em Clientes → empresa → Assuntos/Pautas pra aparecerem aqui.</small>}
      </Field>}
      {mode === 'auto' && <Field label="Tipo de conteúdo (MODO — muda COMO a IA pensa, não só a arte)">
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          {INTENTS.map(([k, t]) => <button key={k} className={'btn sm' + (intent === k ? ' pri' : ' ghost')} onClick={() => { setIntent(k); persist({ intent: k }); }}>{t}</button>)}
        </div>
        {intent === 'evento' && <select className="inp" style={{ marginTop: 6 }} value={eventId} onChange={e => { setEventId(e.target.value); persist({ eventId: e.target.value }); }}>
          <option value="">Escolha o evento cadastrado…</option>
          {events.map(ev => <option key={ev.id} value={ev.id}>{ev.name}{ev.date_start ? ' · ' + ev.date_start : ''}{ev.location ? ' · ' + ev.location : ''}</option>)}
        </select>}
        <small className="hint">Produtos = institucional dos apps · Evento = divulga um evento cadastrado (datas/logos/local reais) · Criativo = meme/data/oportunidade (livre).</small>
      </Field>}
      {mode === 'auto' && <Field label="Formato (carrossel / post / story / vídeo)">
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          {FORMATOS.map(([k, t]) => <button key={k} className={'btn sm' + (formato === k ? ' pri' : ' ghost')} onClick={() => { setFormato(k); persist({ formato: k }); }}>{t}</button>)}
        </div>
        {formato === 'video' && <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 8, alignItems: 'center' }}>
          <span className="hint">Duração do vídeo:</span>
          {[[0, 'Livre (IA decide)'], [8, '8s'], [15, '15s'], [30, '30s'], [60, '60s']].map(([v, t]) => <button key={v} className={'btn sm' + (vsec === v ? ' pri' : ' ghost')} onClick={() => { setVsec(v); persist({ videoSeconds: v }); }}>{t}</button>)}
        </div>}
        <small className="hint">Carrossel → plano de telas · Post fixo → pauta · Vídeo → roteiro em cenas (trave a duração aqui).</small>
      </Field>}
      {mode === 'auto' && <button className="btn pri" disabled={busy} onClick={gerarAuto}>{busy ? 'Gerando…' : (assunto.trim() ? ('Gerar ' + fmtLabel + ' do assunto') : 'Gerar briefing com IA (apps marcados)')}</button>}
      {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
      <Field label="Briefing"><textarea className="inp" rows={8} value={briefing} onChange={e => { setBriefing(e.target.value); persist({ briefing: e.target.value }); }} placeholder="Ex.: fale sobre o Look Diesel, destaque conforto e estilo…" style={{ resize: 'vertical', minHeight: 160 }} /></Field>
      {mode === 'auto' && formato === 'video' && <small className="hint">Vídeo: <b>trave a duração acima</b>, gere o roteiro, depois <b>Próximo</b> pra escolher o modelo e gerar (a duração já vai travada, com o custo na tela).</small>}
    </div>
    <div className="stack">
      <Field label="Objetivo">
        <select className="inp" value={objetivo} onChange={e => { setObjetivo(e.target.value); persist({ objetivo: e.target.value }); }}>
          {['vender', 'engajar', 'educar', 'lançar', 'awareness'].map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      </Field>
      <Field label="Tom de voz"><input className="inp" value={tom} onChange={e => { setTom(e.target.value); persist({ tom: e.target.value }); }} placeholder="Ex.: descontraído, premium…" /></Field>
      <Field label="CTA + link"><input className="inp" value={cta} onChange={e => { setCta(e.target.value); persist({ cta: e.target.value }); }} placeholder="Ex.: Compre em site.com/look" /></Field>
      <Field label="Redes alvo">
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          {CONT_NETS.map(n => <button key={n} className={'btn sm' + (networks.includes(n) ? ' pri' : ' ghost')} onClick={() => { const ns = networks.includes(n) ? networks.filter(x => x !== n) : [...networks, n]; setNetworks(ns); persist({ networks: ns }); }}>{n}</button>)}
        </div>
      </Field>
      <div className="sec mut">Apps que viram ideias (marque os que entram no briefing)</div>
      {products.map(p => <label key={p.id} className="litem" style={{ padding: 8, cursor: 'pointer' }}>
        <input type="checkbox" checked={!!sources[p.id]} onChange={e => { const s = { ...sources, [p.id]: e.target.checked }; setSources(s); persist({ sources: s }); }} />
        <div className="li-main" style={{ marginLeft: 8 }}><b>{p.name}</b><small>{(p.solutions || []).length} solução(ões)</small></div>
      </label>)}
      {!products.length && <div className="hint">Sem produtos cadastrados (fonte do briefing). Cadastre em Clientes → Produtos.</div>}
    </div>
  </div>;
}

/* ── Salvar/editar perfil (template) — maleável ── */
function PerfilSaver({ company, type, current, onSaved }) {
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState('');
  const [variant, setVariant] = React.useState('escuro');
  const [structure, setStructure] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  React.useEffect(() => { if (open) setStructure(current || ''); }, [open]);
  async function save() {
    if (!name.trim() || !structure.trim()) { setMsg('Nome e estrutura são obrigatórios.'); return; }
    setBusy(true); setMsg('');
    try {
      await window.mpApi.saveImageTemplate({ company_id: company.id, type, name: name.trim(), variant, structure: structure.trim() });
      setMsg('Perfil salvo!'); setOpen(false); setName(''); onSaved && onSaved();
    } catch (e) { setMsg('Erro: ' + (e.message || e)); } finally { setBusy(false); }
  }
  if (!open) return <button className="btn sm ghost" onClick={() => setOpen(true)}>+ Salvar como perfil</button>;
  return <div className="panel stack" style={{ gap: 6 }}>
    <Field label="Nome do perfil"><input className="inp" value={name} onChange={e => setName(e.target.value)} placeholder="Ex.: Editorial Escuro v2" /></Field>
    <div className="row" style={{ gap: 6 }}>
      {['escuro', 'claro'].map(v => <button key={v} className={'btn sm' + (variant === v ? ' pri' : ' ghost')} onClick={() => setVariant(v)}>{v}</button>)}
    </div>
    <Field label="Estrutura (a diagramação fixa que a IA segue — edite à vontade)">
      <textarea className="inp" rows={5} value={structure} onChange={e => setStructure(e.target.value)} style={{ resize: 'vertical', fontSize: 12 }} placeholder="Ex.: ESTRUTURA FIXA: fundo escuro, título topo-esquerda, foto à direita…" />
    </Field>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <div className="row" style={{ gap: 6 }}>
      <button className="btn sm pri" disabled={busy} onClick={save}>{busy ? 'Salvando…' : 'Salvar perfil'}</button>
      <button className="btn sm ghost" onClick={() => setOpen(false)}>Cancelar</button>
    </div>
  </div>;
}

/* ── Carrossel: cria a partir do PLANO de telas (do Briefing) ── */
function CarrosselCreator({ company, format }) {
  const st = ContState.get(company.id);
  const fmt = format || 'carrossel';
  const allTelas = st.telas || [];
  const telas = fmt === 'carrossel' ? allTelas : allTelas.slice(0, 1);   // post/story = 1 arte; carrossel = N telas
  const fmtName = { carrossel: 'Carrossel', post: 'Post fixo', story: 'Story (9:16)' }[fmt] || 'Carrossel';
  const [imgModels, setImgModels] = React.useState([]);
  const [versions, setVersions] = React.useState(st.carouselVersions || [{ model: 'editorial' }]);  // modelo escolhido PERSISTIDO (não reseta no F5)
  const [results, setResults] = React.useState(st.carouselResults || []);   // [{model, slides, cost, post_id}] — persistido
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [proc, setProc] = React.useState({ open: false });   // modal de loading fullscreen (igual teaser)
  const [influencers, setInfluencers] = React.useState([]);
  const [useInf, setUseInf] = React.useState(st.useInfluencer || false);   // opt-in: usar influencer na capa/CTA
  const [infId, setInfId] = React.useState(st.influencerId || '');
  const [viewer, setViewer] = React.useState(null);   // {vi, si}
  const [templates, setTemplates] = React.useState([]);
  const [templateId, setTemplateId] = React.useState('');
  function loadTemplates() {
    return window.mpApi.imageTemplates(company.id, 'carrossel').then(r => {
      const t = r.templates || []; setTemplates(t); setTemplateId(id => id || (t[0] && t[0].id) || '');
    }).catch(() => {});
  }
  React.useEffect(() => { loadTemplates(); }, [company.id]);

  React.useEffect(() => {
    if (!viewer) return;
    const onKey = (e) => {
      if (e.key === 'Escape') { setViewer(null); return; }
      const sl = (results[viewer.vi] || {}).slides || [];
      if (e.key === 'ArrowRight') setViewer(v => ({ vi: v.vi, si: Math.min(sl.length - 1, v.si + 1) }));
      if (e.key === 'ArrowLeft') setViewer(v => ({ vi: v.vi, si: Math.max(0, v.si - 1) }));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [viewer, results]);

  React.useEffect(() => { window.mpApi.aiModels().then(r => setImgModels(r.image || [])).catch(() => {}); }, []);
  React.useEffect(() => { window.mpApi.listInfluencers(company.id).then(l => setInfluencers((l || []).filter(i => (i.photos || []).length))).catch(() => {}); }, [company.id]);
  React.useEffect(() => { ContState.set(company.id, { useInfluencer: useInf, influencerId: infId }); }, [useInf, infId]);
  React.useEffect(() => { ContState.set(company.id, { carouselVersions: versions }); }, [versions]);  // salva a escolha do modelo
  React.useEffect(() => {   // sem escolha salva + modelos carregados → padrão = 1º modelo de IA (gera imagem, não editorial)
    if (!st.carouselVersions && imgModels.length && versions.length === 1 && versions[0].model === 'editorial') {
      setVersions([{ model: imgModels[0].id }]);
    }
  }, [imgModels]);
  const MODEL_OPTS = [{ id: 'editorial', name: 'Editorial — só tipografia (grátis, instantâneo)' }, ...imgModels];
  const PROV_LABELS = { omniroute: 'OmniRoute (grátis · assinatura)', cometapi: 'CometAPI', piapi: 'PiAPI', openrouter: 'OpenRouter' };
  const MODEL_GROUPS = (() => {
    const g = {}; imgModels.forEach(m => { const p = m.provider || 'outros'; (g[p] = g[p] || []).push(m); });
    return Object.keys(g).map(p => ({ provider: p, label: PROV_LABELS[p] || p, models: g[p] }));
  })();
  const optLabel = (m) => m.name + (m.price_brl ? ' · R$ ' + Number(m.price_brl).toFixed(2) : (m.free ? ' · grátis' : ''));

  function setVerModel(i, m) { setVersions(vs => vs.map((v, k) => k === i ? { model: m } : v)); }
  function addVer() { setVersions(vs => vs.length < 4 ? [...vs, { model: (imgModels[0] && imgModels[0].id) || 'editorial' }] : vs); }
  function delVer(i) { setVersions(vs => vs.length > 1 ? vs.filter((_, k) => k !== i) : vs); }
  const totalImgs = telas.length * versions.length;


  async function gerar() {
    setBusy(true); setResults([]); setMsg('');
    const out = [];
    const aiVers = versions.filter(v => v.model && v.model !== 'editorial').length;
    const estMs = Math.max(6000, telas.length * versions.length * (aiVers ? 11000 : 1200));  // IA+visão ~11s/tela
    const t0 = Date.now();
    setProc({ open: true, pct: 1, detail: 'Preparando a geração…', phase: '' });
    const tick = setInterval(() => {
      const pct = Math.min(95, ((Date.now() - t0) / estMs) * 100);
      setProc(p => (p.open && p.phase !== 'done' && p.phase !== 'error') ? { ...p, pct } : p);
    }, 400);
    try {
      for (let i = 0; i < versions.length; i++) {
        setProc(p => ({ ...p, detail: `Versão ${i + 1}/${versions.length} — gerando a arte com IA e checando a composição (juiz de visão)…` }));
        setMsg(`Renderizando versão ${i + 1}/${versions.length} (${versions[i].model})…`);
        const r = await window.mpApi.renderCarousel({ company_id: company.id, telas, model: versions[i].model, template_id: templateId, use_influencer: useInf, influencer_id: infId, format: fmt, event_id: st.eventId });
        out.push({ model: r.model, slides: r.slides || [], cost: r.cost || 0, warning: r.warning || '', post_id: r.post_id, base_urls: r.base_urls || [] });
        setResults([...out]); ContState.set(company.id, { carouselResults: out });
      }
      const cost = out.reduce((a, b) => a + (b.cost || 0), 0);
      const warns = out.filter(o => o.warning);
      clearInterval(tick);
      setProc({ open: true, pct: 100, phase: 'done', detail: `${out.length} versão(ões) × ${telas.length} telas prontas · Custo: R$ ${cost.toFixed(2)}` });
      setMsg((warns.length ? '⚠ ' + warns[0].warning + ' ' : '')
        + `${out.length} versão(ões) × ${telas.length} telas = ${telas.length * out.length} imagens. Custo: R$ ${cost.toFixed(2)}. Clique numa imagem pra ver a instrução + modo Instagram.`);
    } catch (e) { clearInterval(tick); setProc({ open: true, phase: 'error', detail: String(e.message || e) }); setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  // Re-render GRÁTIS (cache): reusa as fotos já geradas (base_urls) e só redesenha a arte
  // (texto/logo/rodapé) — não chama a IA, custo R$ 0. Útil pra iterar diagramação sem pagar.
  async function regerarArte(rv, vi) {
    if (!(rv.base_urls || []).some(Boolean)) { setMsg('Esta versão não tem fotos salvas pra reusar (gere com um modelo de IA primeiro).'); return; }
    setBusy(true); setMsg(`Regerando a arte da versão ${vi + 1} (grátis — reusando as fotos)…`);
    try {
      const r = await window.mpApi.renderCarousel({ company_id: company.id, telas, model: rv.model, template_id: templateId, base_urls: rv.base_urls, use_influencer: useInf, influencer_id: infId, format: fmt, event_id: st.eventId });
      const nv = { model: r.model, slides: r.slides || [], cost: r.cost || 0, warning: r.warning || '', post_id: r.post_id, base_urls: r.base_urls || [] };
      setResults(rs => { const c = rs.slice(); c[vi] = nv; ContState.set(company.id, { carouselResults: c }); return c; });
      setMsg(`Arte da versão ${vi + 1} regerada. Custo: R$ ${(r.cost || 0).toFixed(2)} (reusou as fotos, não pagou IA).`);
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  async function regerarSlide(rv, vi, si) {
    setBusy(true); setMsg(`Regerando só a tela ${si + 1} (paga só ela)…`);
    try {
      const bases = (rv.base_urls && rv.base_urls.length ? rv.base_urls.slice() : telas.map(() => null));
      bases[si] = null;   // zera SÓ esta → regenera (paga 1 slide); as outras reusam a foto salva (grátis)
      const r = await window.mpApi.renderCarousel({ company_id: company.id, telas, model: rv.model, template_id: templateId, use_influencer: useInf, influencer_id: infId, format: fmt, event_id: st.eventId, base_urls: bases });
      const nv = { model: r.model, slides: r.slides || [], cost: r.cost || 0, warning: r.warning || '', post_id: r.post_id, base_urls: r.base_urls || [] };
      setResults(rs => { const c = rs.slice(); c[vi] = nv; ContState.set(company.id, { carouselResults: c }); return c; });
      setMsg(`Tela ${si + 1} regenerada. Custo: R$ ${(r.cost || 0).toFixed(2)} (só ela — as outras reusaram a foto).`);
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  async function enviarAprovacao(rv, vi) {
    if (!rv.slides || !rv.slides.length) return;
    setBusy(true); setMsg(`Enviando versão ${vi + 1} para Aprovação…`);
    try {
      if (rv.post_id) {
        // já existe o post DRAFT criado na geração → só promove pra REVIEW (sem duplicar)
        await window.mpApi.transitionPost(rv.post_id, 'REVIEW');
      } else {
        const urls = rv.slides.map(s => s.url);
        await window.mpApi.createPost({
          company_id: company.id, title: st.assuntoTema || 'Carrossel',
          copy: (st.briefing || '').split('\n')[0] || (telas[0] && telas[0].title) || '',
          networks: ['instagram'], media_url: urls[0], intent: 'review',
          meta: { content_type: 'carousel', carousel_urls: urls, model: rv.model, telas_count: telas.length },
        });
      }
      setMsg(`Versão ${vi + 1} enviada para Aprovação (carrossel ${rv.slides.length} telas). Veja na aba Aprovação.`);
    } catch (e) { setMsg('Erro ao enviar: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  if (!telas.length) {
    return <div className="stack"><div className="hint" style={{ padding: 16 }}>
      Esse conteúdo é um <b>Carrossel</b>, mas ainda não há plano de telas.<br />
      Volte ao <b>Briefing</b>, escolha um <b>assunto</b> + formato <b>Carrossel</b> e clique em <b>“Gerar plano de telas”</b>. As telas aparecem aqui pra renderizar.
    </div></div>;
  }

  return <div className="stack">
    {proc.open && <ProcessModal open={proc.open} title="Gerando carrossel" detail={proc.detail} pct={proc.pct} phase={proc.phase} onClose={() => setProc({ open: false })} />}
    <div className="sec mut">{fmtName} · <b>{telas.length} {telas.length === 1 ? 'arte' : 'telas'}</b> {fmt === 'carrossel' ? 'do plano' : (fmt === 'story' ? '(vertical 9:16)' : '(4:5)')} (vindas do Briefing). Sem selecionar app — só escolha o modelo.</div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(190px,1fr))', gap: 6 }}>
      {telas.map((t, i) => <div key={i} className="card" style={{ padding: 8 }}>
        <small className="mut">{i + 1}. {({ cover: 'capa', cta: 'CTA' }[t.type]) || 'conteúdo'}</small>
        <div style={{ fontWeight: 600, fontSize: 13 }}>{t.title}</div>
      </div>)}
    </div>
    {templates.length > 0 && <Field label="Padrão visual (mesma diagramação em todas as telas = identidade)">
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {templates.map(t => <button key={t.id} className={'btn sm' + (templateId === t.id ? ' pri' : ' ghost')} onClick={() => setTemplateId(t.id)}>{t.name}</button>)}
      </div>
      <small className="hint">A IA cria a arte livre, mas segue SEMPRE este padrão → consistência. Troque o padrão pra mudar a estrutura.</small>
      <PerfilSaver company={company} type="carrossel" current={(templates.find(t => t.id === templateId) || {}).structure} onSaved={loadTemplates} />
    </Field>}
    <Field label={`Versões (cada uma = 1 modelo · ${totalImgs} imagens no total)`}>
      <div className="stack" style={{ gap: 6 }}>
        {versions.map((v, i) => <div key={i} className="row" style={{ gap: 6, alignItems: 'center' }}>
          <b style={{ width: 30 }}>v{i + 1}</b>
          <select className="inp" value={v.model} onChange={e => setVerModel(i, e.target.value)} style={{ flex: 1 }}>
            <option value="editorial">Editorial — só tipografia (grátis, instantâneo)</option>
            {MODEL_GROUPS.map(grp => <optgroup key={grp.provider} label={grp.label}>
              {grp.models.map(m => <option key={m.id} value={m.id}>{optLabel(m)}</option>)}
            </optgroup>)}
          </select>
          {versions.length > 1 && <button className="btn sm ghost" onClick={() => delVer(i)}>✕</button>}
        </div>)}
        {versions.length < 4 && <button className="btn sm ghost" onClick={addVer}>+ versão (outro modelo)</button>}
      </div>
    </Field>
    {influencers.length > 0 && <Field label="Influencer (opcional — entra só na capa e no CTA)">
      <label className="row" style={{ gap: 8, alignItems: 'center', cursor: 'pointer' }}>
        <input type="checkbox" checked={useInf} onChange={e => setUseInf(e.target.checked)} />
        <span>Usar influencer — foto real composta na <b>capa</b> e no <b>CTA</b> (custa nano-banana). Desligue p/ não ficar repetitivo.</span>
      </label>
      {useInf && <select className="inp" value={infId} onChange={e => setInfId(e.target.value)} style={{ marginTop: 6 }}>
        <option value="">Automático (1º cadastrado)</option>
        {influencers.map(i => <option key={i.id} value={i.id}>{i.name}{i.handle ? ' · @' + i.handle : ''} ({(i.photos || []).length} fotos)</option>)}
      </select>}
    </Field>}
    <button className="btn pri" disabled={busy} onClick={gerar}>{busy ? 'Renderizando…' : (fmt === 'carrossel' ? `Gerar carrossel (${totalImgs} imagens)` : `Gerar ${fmtName.toLowerCase()} (${versions.length} ${versions.length === 1 ? 'versão' : 'versões'})`)}</button>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    {results.map((rv, vi) => <div key={vi} className="stack" style={{ gap: 6 }}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <div className="sec mut">Versão {vi + 1} · {rv.model}{rv.cost ? ` · R$ ${rv.cost.toFixed(2)}` : ' · grátis'}</div>
        <div className="row" style={{ gap: 6 }}>
          {(rv.base_urls || []).some(Boolean) && <button className="btn sm ghost" disabled={busy} title="Reusa as fotos já geradas e só redesenha a arte — não paga IA" onClick={() => regerarArte(rv, vi)}>↻ Regerar arte (grátis)</button>}
          <button className="btn sm pri" disabled={busy} onClick={() => enviarAprovacao(rv, vi)}>Enviar esta versão → Aprovação</button>
        </div>
      </div>
      {rv.warning && <div className="err" style={{ fontSize: 12 }}>⚠ {rv.warning}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: 8 }}>
        {rv.slides.map((s, si) => <div key={si} style={{ position: 'relative' }}>
          <img loading="lazy" decoding="async" src={s.url} onClick={() => setViewer({ vi, si })} style={{ width: '100%', borderRadius: 8, cursor: 'zoom-in', display: 'block' }} />
          <button className="btn sm" disabled={busy} title="Regenerar SÓ esta tela (paga só ela; as outras reusam a foto)" onClick={() => regerarSlide(rv, vi, si)}
            style={{ position: 'absolute', top: 4, right: 4, padding: '2px 8px', fontSize: 12, background: 'rgba(0,0,0,.72)', color: '#fff', borderRadius: 6, border: 'none' }}>↻</button>
        </div>)}
      </div>
    </div>)}
    {viewer && (() => {
      const rv = results[viewer.vi]; const sl = rv.slides; const si = viewer.si;
      const go = d => setViewer(v => ({ vi: v.vi, si: Math.max(0, Math.min(sl.length - 1, v.si + d)) }));
      return <div onClick={() => setViewer(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.92)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 99999, padding: 16, boxSizing: 'border-box' }}>
        <button onClick={e => { e.stopPropagation(); setViewer(null); }} title="Fechar (Esc)" style={{ position: 'fixed', top: 16, right: 20, zIndex: 100000, background: '#fff', color: '#111', border: 'none', borderRadius: 999, width: 44, height: 44, fontSize: 22, lineHeight: '44px', cursor: 'pointer', fontWeight: 700 }}>✕</button>
        <button onClick={e => { e.stopPropagation(); go(-1); }} disabled={si === 0} style={{ position: 'fixed', left: 20, top: '50%', transform: 'translateY(-50%)', zIndex: 100000, background: 'rgba(255,255,255,.92)', color: '#111', border: 'none', borderRadius: 999, width: 52, height: 52, fontSize: 22, cursor: si === 0 ? 'default' : 'pointer', opacity: si === 0 ? .4 : 1 }}>◀</button>
        <div onClick={e => e.stopPropagation()} style={{ textAlign: 'center', maxHeight: '96vh', overflow: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <img loading="lazy" decoding="async" src={sl[si].url} style={{ maxHeight: '70vh', maxWidth: '86vw', borderRadius: 12, display: 'block', objectFit: 'contain' }} />
          <div style={{ color: '#fff', marginTop: 10, opacity: .9 }}>{si + 1} / {sl.length} · versão {viewer.vi + 1} ({rv.model}) · {sl[si].image_ok ? 'foto IA' : 'editorial (sem foto)'}</div>
          {sl[si].prompt && <div style={{ color: '#ddd', marginTop: 8, maxWidth: '86vw', fontSize: 12, textAlign: 'left', maxHeight: '14vh', overflow: 'auto', background: 'rgba(255,255,255,.07)', padding: 10, borderRadius: 8 }}><b style={{ color: '#fff' }}>Instrução enviada ao modelo:</b> {sl[si].prompt}{sl[si].image_error ? ' — ❌ ' + sl[si].image_error : ''}</div>}
        </div>
        <button onClick={e => { e.stopPropagation(); go(1); }} disabled={si === sl.length - 1} style={{ position: 'fixed', right: 20, top: '50%', transform: 'translateY(-50%)', zIndex: 100000, background: 'rgba(255,255,255,.92)', color: '#111', border: 'none', borderRadius: 999, width: 52, height: 52, fontSize: 22, cursor: si === sl.length - 1 ? 'default' : 'pointer', opacity: si === sl.length - 1 ? .4 : 1 }}>▶</button>
      </div>;
    })()}
  </div>;
}

/* ── Passo 2: Criação ── */
function StepCriacao({ company }) {
  // A tela de Criação ADAPTA ao tipo escolhido no Briefing.
  const st = ContState.get(company.id);
  const f = st.formato || 'carrossel';
  // carrossel/post/story usam o MESMO criador moderno (modelo, versões, influencer, card de vidro) — só muda a dimensão.
  if (f === 'carrossel' || f === 'post' || f === 'story') return <CarrosselCreator company={company} format={f} />;
  return <VideoCreator company={company} />;   // VÍDEO tem tela PRÓPRIA (duração + modelo de vídeo + cenas), não a de imagem
}

function StepCriacaoPost({ company }) {
  const st = ContState.get(company.id);
  const networks = st.networks || ['instagram'];
  const [products, setProducts] = React.useState([]);
  const [sel, setSel] = React.useState({});        // appId -> marcado
  const [themes, setThemes] = React.useState({});  // appId -> tema opcional
  const [qty, setQty] = React.useState({});        // appId -> nº de variações
  const [perModels, setPerModels] = React.useState({}); // appId -> [modelo por variação]
  const [drafts, setDrafts] = React.useState(st.drafts || []);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [imgModels, setImgModels] = React.useState([]);
  const [imgDefault, setImgDefault] = React.useState('');
  const [templates, setTemplates] = React.useState([]);
  const [templateId, setTemplateId] = React.useState('');
  function loadTemplates() {
    return window.mpApi.imageTemplates(company.id, 'post').then(r => {
      const t = r.templates || []; setTemplates(t); setTemplateId(id => id || (t[0] && t[0].id) || '');
    }).catch(() => {});
  }
  React.useEffect(() => { loadTemplates(); }, [company.id]);

  const INST = { id: '__inst__', name: 'Institucional (Cariap)', __inst: true };
  const allApps = [...products, INST];

  React.useEffect(() => {
    window.mpApi.listProducts(company.id).then(r => {
      const arr = Array.isArray(r) ? r : (r.products || []);
      setProducts(arr);
      const src = ContState.get(company.id).sources;   // carrega a seleção do Briefing
      const s = {}, q = {}; arr.forEach(p => { s[p.id] = src ? !!src[p.id] : true; q[p.id] = 2; });
      s[INST.id] = false; q[INST.id] = 1;
      setSel(s); setQty(q);
    }).catch(() => {});
    window.mpApi.aiModels().then(r => {
      const list = r.image || [];
      setImgModels(list);
      setImgDefault(r.image_current || (list[0] && list[0].id) || '');
    }).catch(() => {});
  }, [company.id]);

  const defModel = () => imgDefault || (imgModels[0] && imgModels[0].id) || '';
  const toggle = (id) => setSel(s => ({ ...s, [id]: !s[id] }));
  function setQtyFor(id, n) {
    n = Math.max(1, Math.min(6, parseInt(n) || 1));
    setQty(q => ({ ...q, [id]: n }));
    setPerModels(pm => { const cur = pm[id] || []; return { ...pm, [id]: Array.from({ length: n }, (_, i) => cur[i] || defModel()) }; });
  }
  const modelFor = (id, k) => (perModels[id] && perModels[id][k]) || defModel();
  function setModelFor(id, k, model) {
    setPerModels(pm => { const arr = [...(pm[id] || [])]; while (arr.length <= k) arr.push(defModel()); arr[k] = model; return { ...pm, [id]: arr }; });
  }
  const modelLabel = (id) => { const m = imgModels.find(x => x.id === id); return m ? (m.name + (m.price_brl ? ' R$ ' + Number(m.price_brl).toFixed(2) : '')) : id; };

  function fullBriefing() {
    const parts = [st.briefing || ''];
    if (st.objetivo) parts.push('Objetivo: ' + st.objetivo);
    if (st.tom) parts.push('Tom: ' + st.tom);
    if (st.cta) parts.push('CTA: ' + st.cta);
    return parts.filter(Boolean).join('\n');
  }

  async function genImage(d, model) {
    const r = await window.mpApi.generatePostImage({
      company_id: company.id, theme: st.briefing || '', visual_prompt: d.visual_prompt || '',
      product: d.product || '', title: d.title || '',
      headline: d.headline || d.title || '', subheadline: d.subheadline || '',
      benefits: d.benefits || [], cta: d.cta || '',
      model: model || undefined, template_id: templateId || undefined,
    });
    return r || {};
  }

  async function gerar() {
    const chosen = allApps.filter(p => sel[p.id]);
    if (!chosen.length) { setMsg('Selecione ao menos um app (ou Institucional).'); return; }
    let total = 0, est = 0;
    chosen.forEach(p => { const c = qty[p.id] || 1; total += c; for (let k = 0; k < c; k++) { const pm = (imgModels.find(m => m.id === modelFor(p.id, k)) || {}).price_brl; est += pm || 0; } });
    if (est >= 1.5 && !window.confirm(`Vai gerar ${total} imagens ≈ R$ ${est.toFixed(2)}.\n\nContinuar?`)) return;
    setBusy(true);
    const net = networks[0] || 'instagram';
    const out = [...drafts];
    let n = 0;
    try {
      for (const p of chosen) {
        const cnt = qty[p.id] || 1;
        for (let k = 0; k < cnt; k++) {
          n++;
          const model = modelFor(p.id, k);
          setMsg(`${p.name} — v${k + 1} (${n}/${total}): copy…`);
          const brief = fullBriefing()
            + (p.__inst ? '\nPost INSTITUCIONAL da Cariap (a marca/portfólio, não um app específico).'
                        : `\nProduto/app ALVO (foque exclusivamente neste app): ${p.name}.`)
            + (themes[p.id] ? ` Tema do post: ${themes[p.id]}.` : '');
          const g = await window.mpApi.generatePostAI({ company_id: company.id, briefing: brief, networks: [net] });
          const d = { uid: p.id + '-' + k + '-' + Date.now(), network: net, product: p.__inst ? '' : (g.product || p.name), label: p.name, variant: k + 1, title: g.title || '', headline: g.headline || g.title || '', subheadline: g.subheadline || '', benefits: g.benefits || [], cta: g.cta || '', copy: g.copy || '', hashtags: g.hashtags || '', visual_prompt: g.visual_prompt || '', video_prompt: g.video_prompt || '', media_type: (g.media_type === 'video' ? 'video' : 'image'), media_kind: 'image', media_url: '' };
          setMsg(`${p.name} — v${k + 1}: imagem (${String(model).split('/').pop()})…`);
          try { const im = await genImage(d, model); d.media_url = im.url || ''; d.cost = im.cost; d.model = im.model; d.compose_warning = (im.composed === false) ? (im.warning || 'Composição da marca falhou — saiu só o fundo.') : ''; }
          catch (e) { d.image_error = (e.message || '' + e); }
          out.push(d);
          setDrafts([...out]); ContState.set(company.id, { drafts: [...out] });
        }
      }
      const totalCost = out.reduce((s, d) => s + (Number(d.cost) || 0), 0);
      setMsg(`${total} peças geradas. Apague as piores e deixe as melhores.` + (totalCost ? ` Custo: R$ ${totalCost.toFixed(2)}.` : ''));
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  function update(uid, patch) {
    const next = drafts.map(d => d.uid === uid ? { ...d, ...patch } : d);
    setDrafts(next); ContState.set(company.id, { drafts: next });
  }
  function remove(uid) {
    const next = drafts.filter(d => d.uid !== uid);
    setDrafts(next); ContState.set(company.id, { drafts: next });
  }
  async function regenerate(uid, net) {
    setBusy(true);
    try {
      const g = await window.mpApi.generatePostAI({ company_id: company.id, briefing: fullBriefing(), networks: [net] });
      update(uid, { title: g.title || '', copy: g.copy || '', hashtags: g.hashtags || '', product: g.product || '', visual_prompt: g.visual_prompt || '' });
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }
  async function regenImage(uid) {
    const d = drafts.find(x => x.uid === uid); if (!d) return;
    setBusy(true); setMsg('Gerando imagem…');
    try { const im = await genImage(d, d.model); update(uid, { media_url: im.url || '', cost: im.cost, model: im.model, media_kind: 'image', image_error: '', compose_warning: (im.composed === false) ? (im.warning || 'Composição da marca falhou — saiu só o fundo.') : '' }); setMsg('Imagem gerada' + (im.cost ? ` (R$ ${Number(im.cost).toFixed(2)})` : '') + '.'); }
    catch (e) { setMsg('Erro na imagem: ' + (e.message || e)); }
    finally { setBusy(false); }
  }
  async function genVideo(uid) {
    const d = drafts.find(x => x.uid === uid); if (!d) return;
    setBusy(true); setMsg('Iniciando vídeo (Sora-2): gerando cenas e juntando — pode levar minutos…');
    try {
      const j = await window.mpApi.generatePostVideo({ company_id: company.id, theme: st.briefing || '', video_prompt: d.video_prompt || d.visual_prompt || '', scenes: 3 });
      const jobsCsv = (j.jobs || []).join(',');
      if (!jobsCsv) throw new Error(j.detail || 'sem jobs');
      update(uid, { video_status: 'rendering' });
      const total = j.count || (j.jobs || []).length;
      for (let i = 0; i < 100; i++) {             // ~10 min máx (100 x 6s)
        await new Promise(r => setTimeout(r, 6000));
        const s = await window.mpApi.videoStatus(jobsCsv, company.id);
        if (s.status === 'completed' && s.url) { update(uid, { media_url: s.url, media_kind: 'video', video_status: 'done' }); setMsg('Vídeo pronto (cenas juntadas)!'); setBusy(false); return; }
        if (s.status === 'failed') { update(uid, { video_status: 'failed' }); setMsg('Vídeo falhou: ' + (s.error || '')); setBusy(false); return; }
        setMsg(`Renderizando vídeo… (${s.done || 0}/${s.total || total} cenas prontas)`);
      }
      setMsg('Vídeo demorando — tente Atualizar mais tarde.'); update(uid, { video_status: 'timeout' });
    } catch (e) { setMsg('Erro no vídeo: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  return <div className="stack">
    {templates.length > 0 && <div className="panel stack">
      <div className="sec"><Icon name="image" />Perfil visual (mesma diagramação = identidade)</div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {templates.map(t => <button key={t.id} className={'btn sm' + (templateId === t.id ? ' pri' : ' ghost')} onClick={() => setTemplateId(t.id)}>{t.name}</button>)}
      </div>
      <small className="hint">A IA cria a arte livre, mas segue SEMPRE este perfil → consistência da marca.</small>
      <PerfilSaver company={company} type="post" current={(templates.find(t => t.id === templateId) || {}).structure} onSaved={loadTemplates} />
    </div>}
    <div className="panel stack">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <div className="sec"><Icon name="layers" />Marque os apps · defina quantas peças · escolha o modelo de cada</div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn sm ghost" onClick={() => { const s = {}; allApps.forEach(p => { s[p.id] = true; }); setSel(s); }}>Marcar todos</button>
          <button className="btn sm ghost" onClick={() => setSel({})}>Limpar</button>
        </div>
      </div>
      {!imgModels.length && <div className="hint">Carregando modelos de imagem…</div>}
      {allApps.map(p => {
        const on = !!sel[p.id]; const cnt = qty[p.id] || 1;
        return <div key={p.id} className="panel" style={{ padding: 10, borderColor: on ? 'var(--cyan)' : undefined }}>
          <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input type="checkbox" checked={on} onChange={() => toggle(p.id)} />
            <b style={{ minWidth: 160 }}>{p.name}</b>
            {on && <>
              <span className="hint">Qtd:</span>
              <input className="inp" type="number" min={1} max={6} value={cnt} onChange={e => setQtyFor(p.id, e.target.value)} style={{ width: 64 }} />
              {!p.__inst && <input className="inp" value={themes[p.id] || ''} onChange={e => setThemes(t => ({ ...t, [p.id]: e.target.value }))} placeholder="tema (opcional)" style={{ flex: 1, minWidth: 140 }} />}
            </>}
          </div>
          {on && imgModels.length > 0 && <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
            {Array.from({ length: cnt }, (_, k) => <div key={k} className="row" style={{ gap: 4, alignItems: 'center' }}>
              <span className="hint" style={{ fontWeight: 700 }}>v{k + 1}</span>
              <select className="inp" value={modelFor(p.id, k)} onChange={e => setModelFor(p.id, k, e.target.value)} style={{ maxWidth: 250 }}>
                {imgGroups(imgModels).map(grp => <optgroup key={grp.provider} label={grp.label}>
                  {grp.models.map(m => <option key={m.id} value={m.id}>{imgOptLabel(m)}</option>)}
                </optgroup>)}
              </select>
            </div>)}
          </div>}
        </div>;
      })}
      <div className="row" style={{ gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="hint">{(() => {
          let n = 0, e = 0;
          allApps.filter(p => sel[p.id]).forEach(p => { const c = qty[p.id] || 1; n += c; for (let k = 0; k < c; k++) { const pm = (imgModels.find(m => m.id === modelFor(p.id, k)) || {}).price_brl; e += pm || 0; } });
          return `${n} peças` + (e ? ` · estimativa ≈ R$ ${e.toFixed(2)}` : '');
        })()}</div>
        <button className="btn pri" disabled={busy} onClick={gerar}>{busy ? 'Gerando…' : 'Gerar'}</button>
      </div>
    </div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <div className="grid2">
      {drafts.map(d => <div key={d.uid} className="panel stack">
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <div className="row" style={{ gap: 6 }}>
            <Pill kind="cy" dot>{d.network}</Pill>
            {(d.label || d.product) ? <Pill kind="gd">{d.label || d.product}{d.variant ? ' · v' + d.variant : ''}</Pill> : null}
            <Pill kind={d.media_type === 'video' ? 'gd' : ''}>sugerido: {d.media_type === 'video' ? 'vídeo' : 'imagem'}</Pill>
            {d.model ? <Pill>{String(d.model).split('/').pop()}</Pill> : null}
            {d.cost ? <Pill>R$ {Number(d.cost).toFixed(2)}</Pill> : null}
          </div>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn sm ghost" disabled={busy} onClick={() => regenImage(d.uid)}><Icon name="image" />Imagem</button>
            <button className={'btn sm' + (d.media_type === 'video' ? ' pri' : ' ghost')} disabled={busy} onClick={() => genVideo(d.uid)}><Icon name="play" />Vídeo</button>
            <button className="btn sm ghost" disabled={busy} onClick={() => regenerate(d.uid, d.network)}><Icon name="bolt" />Copy</button>
            <button className="btn sm ghost" onClick={() => remove(d.uid)}><Icon name="trash" /></button>
          </div>
        </div>
        {d.media_url && d.media_kind === 'video'
          ? <video src={d.media_url} controls style={{ width: '100%', borderRadius: 8, border: '1px solid var(--line)' }} />
          : d.media_url
            ? <img loading="lazy" decoding="async" src={d.media_url} style={{ width: '100%', borderRadius: 8, border: '1px solid var(--line)' }} />
            : <div className="hint" style={{ textAlign: 'center', padding: 16, border: '1px dashed var(--line)', borderRadius: 8 }}>{d.video_status === 'rendering' ? 'Renderizando vídeo…' : d.image_error ? ('Imagem falhou: ' + d.image_error) : 'Sem mídia'}</div>}
        {d.compose_warning && <div style={{ background: '#3a2f10', color: '#ffd479', borderRadius: 8, padding: '8px 12px', fontSize: 13 }}>⚠ {d.compose_warning} <button className="btn sm ghost" disabled={busy} onClick={() => regenImage(d.uid)} style={{ marginLeft: 6 }}>Tentar de novo</button></div>}
        <input className="inp" value={d.title} onChange={e => update(d.uid, { title: e.target.value })} placeholder="Título interno" />
        <textarea className="inp" rows={5} value={d.copy} onChange={e => update(d.uid, { copy: e.target.value })} style={{ resize: 'vertical' }} placeholder="Copy" />
        <input className="inp" value={d.hashtags} onChange={e => update(d.uid, { hashtags: e.target.value })} placeholder="#hashtags" />
      </div>)}
      {!drafts.length && <div className="hint">Nenhuma peça ainda. Clique em “Gerar peças”.</div>}
    </div>
  </div>;
}

/* ── Passo 3: Aprovação ── */
function StepAprovacao({ company }) {
  const st = ContState.get(company.id);
  const [posts, setPosts] = React.useState([]);
  const [preview, setPreview] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [channel, setChannel] = React.useState('whatsapp');
  const [recipient, setRecipient] = React.useState('');
  const [linkUrl, setLinkUrl] = React.useState('');
  const [sending, setSending] = React.useState(false);

  const load = React.useCallback(() => {
    window.mpApi.listPosts().then(r => setPosts((r.posts || []).filter(p => p.company_id === company.id))).catch(() => {});
  }, [company.id]);
  React.useEffect(() => { load(); }, [load]);

  async function sendToClient() {
    setSending(true); setMsg('Criando as peças e gerando o link…');
    try {
      // 1) transforma as peças geradas (rascunho local) em posts REVIEW (com a imagem)
      const drafts = (ContState.get(company.id).drafts) || [];
      for (const d of drafts) {
        await window.mpApi.createPost({ company_id: company.id, title: d.title, copy: d.copy, hashtags: d.hashtags, networks: [d.network], media_url: d.media_url || null, intent: 'review',
          meta: { product: d.product, visual_prompt: d.visual_prompt, headline: d.headline, subheadline: d.subheadline, benefits: d.benefits, cta: d.cta, model: d.model } });
      }
      if (drafts.length) ContState.set(company.id, { drafts: [] });
      // 2) 1 link com TODAS as peças em revisão do cliente
      const all = await window.mpApi.listPosts();
      const reviewIds = (all.posts || []).filter(p => p.company_id === company.id && p.status === 'REVIEW').map(p => p.id);
      if (!reviewIds.length) { setMsg('Nenhuma peça gerada para enviar. Gere na Criação.'); setSending(false); return; }
      const r = await window.mpApi.createApprovalLink({ company_id: company.id, post_ids: reviewIds, stage: 'client' });
      setLinkUrl(r.url || '');
      if (recipient.trim()) {
        const text = `Olá! Tem conteúdo novo da ${company.name} para aprovar: ${r.url}`;
        const sent = await window.mpApi.notifyTest({ company_id: company.id, channel, to: recipient.trim(), message: text });
        setMsg(sent.ok ? `Link gerado (${reviewIds.length} peças) e notificação enviada.` : ('Link gerado. Falha na notificação: ' + (sent.error || sent.detail || '')));
      } else {
        setMsg(`Link gerado com ${reviewIds.length} peça(s). Copie e envie ao cliente.`);
      }
      load();
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setSending(false); }
  }

  async function enviarTodos() {
    const drafts = (ContState.get(company.id).drafts) || [];
    if (!drafts.length) { setMsg('Sem peças. Gere na etapa de Criação.'); return; }
    setBusy(true); setMsg('Enviando para aprovação…');
    try {
      for (const d of drafts) {
        await window.mpApi.createPost({ company_id: company.id, title: d.title, copy: d.copy, hashtags: d.hashtags, networks: [d.network], media_url: d.media_url || null, intent: 'review' });
      }
      ContState.set(company.id, { drafts: [] });
      setMsg('Enviado para aprovação.'); load();
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }
  async function transition(id, to) { try { await window.mpApi.transitionPost(id, to); load(); } catch (e) { setMsg('Erro: ' + e.message); } }
  async function del(id) { if (!window.confirm('Excluir este post?')) return; try { await window.mpApi.deletePost(id); load(); } catch (e) { setMsg('Erro: ' + e.message); } }

  async function regenWithFeedback(p) {
    const m = p.meta || {};
    setBusy(true); setMsg('Regenerando com o pedido do cliente…');
    try {
      const im = await window.mpApi.generatePostImage({
        company_id: company.id, product: m.product || '',
        visual_prompt: (m.visual_prompt || '') + ' | AJUSTE PEDIDO PELO CLIENTE (aplique): ' + (p.review_comment || ''),
        headline: m.headline || p.title || '', subheadline: m.subheadline || '', benefits: m.benefits || [], cta: m.cta || '',
        model: m.model || undefined,
      });
      await window.mpApi.updatePost(p.id, { media_url: im.url || p.media_url, review_decision: '', review_comment: '' });
      setMsg('✓ Regenerado com o ajuste do cliente. Reenvie o link pra ele aprovar.'); load();
    } catch (e) { setMsg('Erro ao regenerar: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  async function approveOne(p) {
    if (p.status === 'APPROVED' || p.status === 'SCHEDULED') { setMsg('Já aprovado.'); return; }
    try {
      if (p.status === 'DRAFT') { try { await window.mpApi.transitionPost(p.id, 'REVIEW'); } catch (_) {} }
      await window.mpApi.transitionPost(p.id, 'APPROVED');
      load();
    } catch (e) { setMsg('Erro: ' + e.message); }
  }

  async function aprovarTudo() {
    setBusy(true); setMsg('Aprovando tudo…');
    try {
      // cria as peças que ainda estão como rascunho na sessão
      const drafts = (ContState.get(company.id).drafts) || [];
      for (const d of drafts) {
        await window.mpApi.createPost({ company_id: company.id, title: d.title, copy: d.copy, hashtags: d.hashtags, networks: [d.network], media_url: d.media_url || null, intent: 'review' });
      }
      if (drafts.length) ContState.set(company.id, { drafts: [] });
      const r = await window.mpApi.listPosts();
      const pend = (r.posts || []).filter(p => p.company_id === company.id && (p.status === 'REVIEW' || p.status === 'DRAFT'));
      for (const p of pend) {
        if (p.status === 'DRAFT') { try { await window.mpApi.transitionPost(p.id, 'REVIEW'); } catch (_) {} }
        try { await window.mpApi.transitionPost(p.id, 'APPROVED'); } catch (_) {}
      }
      setMsg(`${pend.length} peça(s) aprovada(s). Vá para Agendamento e publique.`); load();
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  const review = posts.filter(p => p.status === 'REVIEW' || p.status === 'DRAFT');
  const approved = posts.filter(p => p.status === 'APPROVED' || p.status === 'SCHEDULED');

  return <div className="stack">
    <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <button className="btn pri" disabled={busy} onClick={enviarTodos}><Icon name="send" />Enviar peças p/ aprovação</button>
      <button className="btn" disabled={busy} onClick={aprovarTudo}><Icon name="check" />Aprovar tudo (teste)</button>
      <button className="btn sm ghost" onClick={load}><Icon name="refs" />Atualizar</button>
    </div>
    <div className="hint">Modo teste: "Aprovar tudo" cria as peças e marca como aprovado direto, sem mandar pro cliente.</div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}

    {(() => {
      const dr = (ContState.get(company.id).drafts) || [];
      if (!dr.length) return null;
      return <div className="panel stack">
        <div className="sec mut"><Icon name="image" />Peças geradas — prontas para enviar ({dr.length})</div>
        <div className="grid2">{dr.map(d => <div key={d.uid} className="panel stack">
          {d.media_url ? <img loading="lazy" decoding="async" src={d.media_url} style={{ width: '100%', borderRadius: 8, border: '1px solid var(--line)' }} /> : <div className="hint">sem imagem</div>}
          <b>{d.label || d.product || 'Peça'}{d.variant ? ' · v' + d.variant : ''}</b>
          <div className="hint" style={{ whiteSpace: 'pre-wrap', maxHeight: 90, overflow: 'auto' }}>{d.copy}</div>
        </div>)}</div>
        <div className="hint">Use "Gerar link + notificar" abaixo: cria as peças e gera 1 link com todas pro cliente decidir.</div>
      </div>;
    })()}

    <div className="panel stack">
      <div className="sec mut"><Icon name="send" />Enviar ao cliente (link público + notificação)</div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <select className="inp" value={channel} onChange={e => setChannel(e.target.value)} style={{ maxWidth: 150 }}>
          <option value="whatsapp">WhatsApp</option>
          <option value="email">E-mail</option>
        </select>
        <input className="inp" value={recipient} onChange={e => setRecipient(e.target.value)} placeholder={channel === 'whatsapp' ? 'Número (DDD+telefone)' : 'email@cliente.com'} style={{ flex: 1, minWidth: 200 }} />
        <button className="btn pri" disabled={sending} onClick={sendToClient}>{sending ? 'Enviando…' : 'Gerar link + notificar'}</button>
      </div>
      {linkUrl && <div className="row" style={{ gap: 8, alignItems: 'center' }}>
        <input className="inp" readOnly value={linkUrl} style={{ flex: 1 }} onFocus={e => e.target.select()} />
        <a className="btn sm ghost" href={linkUrl} target="_blank" rel="noopener noreferrer"><Icon name="globe" />Abrir</a>
      </div>}
      <div className="hint">Configure WhatsApp (Evolution) e SMTP no app <b>Notificações</b>.</div>
    </div>
    <div className="sec mut">Aguardando aprovação ({review.length})</div>
    {review.map(p => <div key={p.id} className="panel stack">
      <b>{p.title || 'Post'} · <small>{(p.networks || []).join(', ')}</small></b>
      {p.media_url && <img loading="lazy" decoding="async" src={p.media_url} onClick={() => setPreview(p)} title="Clique para expandir" style={{ width: '100%', maxWidth: 360, borderRadius: 8, border: '1px solid var(--line)', cursor: 'zoom-in' }} />}
      {p.review_decision === 'changes' && <div style={{ background: '#3a2f10', color: '#ffd479', borderRadius: 8, padding: '8px 12px' }}>⚠ Cliente aprovou <b>com ressalvas</b>: {p.review_comment}</div>}
      {p.review_decision === 'rejected' && <div className="err">✕ Cliente <b>reprovou</b>: {p.review_comment}</div>}
      <div className="hint" style={{ whiteSpace: 'pre-wrap' }}>{p.copy}</div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {(p.review_decision === 'changes' || p.review_decision === 'rejected') && <button className="btn sm pri" disabled={busy} onClick={() => regenWithFeedback(p)}><Icon name="bolt" />Regenerar com o feedback</button>}
        <button className="btn sm" onClick={() => approveOne(p)}><Icon name="check" />Aprovar</button>
        <button className="btn sm ghost" onClick={() => del(p.id)}><Icon name="trash" />Excluir</button>
      </div>
    </div>)}
    {!review.length && <div className="hint">Nada aguardando.</div>}
    <div className="sec mut">Aprovados ({approved.length})</div>
    {approved.map(p => <div key={p.id} className="litem" style={{ padding: 8, gap: 8, cursor: 'pointer' }} onClick={() => setPreview(p)}>
      {p.media_url && <img loading="lazy" decoding="async" src={p.media_url} style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 6 }} />}
      <div className="li-main"><b>{p.title || 'Post'}</b><small>{p.status === 'SCHEDULED' ? 'agendado' : (p.status === 'PUBLISHED' ? 'publicado' : 'aprovado')}{p.reviewed_at ? ' · cliente em ' + new Date(p.reviewed_at).toLocaleString('pt-BR') : ''}</small></div>
      <button className="btn sm ghost" onClick={e => { e.stopPropagation(); del(p.id); }}><Icon name="trash" /></button>
    </div>)}

    {preview && <div onClick={() => setPreview(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'grid', placeItems: 'center', zIndex: 9999, padding: 16 }}>
      <div onClick={e => e.stopPropagation()} className="panel stack" style={{ maxWidth: 440, maxHeight: '92vh', overflow: 'auto' }}>
        <div className="rowx" style={{ justifyContent: 'space-between' }}>
          <b>{preview.title || 'Post'}</b>
          <button className="btn sm ghost" onClick={() => setPreview(null)}><Icon name="x" /></button>
        </div>
        {preview.media_url && <img loading="lazy" decoding="async" src={preview.media_url} style={{ width: '100%', borderRadius: 8, border: '1px solid var(--line)' }} />}
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <Pill kind={preview.status === 'APPROVED' ? 'good' : 'cy'} dot>{preview.status}</Pill>
          {preview.review_decision && <Pill kind={preview.review_decision === 'rejected' ? 'pri' : ''}>{preview.review_decision === 'approved' ? 'cliente: 100%' : preview.review_decision === 'changes' ? 'cliente: ressalvas' : 'cliente: reprovou'}</Pill>}
          {(preview.networks || []).map(n => <Pill key={n} kind="cy">{n}</Pill>)}
        </div>
        {preview.review_comment && <div style={{ background: '#3a2f10', color: '#ffd479', borderRadius: 8, padding: '8px 12px' }}>Devolutiva do cliente: {preview.review_comment}</div>}
        <div className="hint" style={{ whiteSpace: 'pre-wrap' }}>{preview.copy}</div>
        {preview.hashtags && preview.hashtags.length ? <div className="hint" style={{ color: 'var(--accent)' }}>{(preview.hashtags || []).join(' ')}</div> : null}
      </div>
    </div>}
  </div>;
}

/* ── Passo 4: Agendamento ── */
function StepAgenda({ company }) {
  const [posts, setPosts] = React.useState([]);
  const [accounts, setAccounts] = React.useState([]);
  const [when, setWhen] = React.useState({});
  const [busy, setBusy] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [storyOn, setStoryOn] = React.useState({});   // por post: publicar a CAPA como Story junto do feed
  const [collabs, setCollabs] = React.useState({});   // por post: lista de @ colaboradores (collab) — editável
  const [collabIn, setCollabIn] = React.useState({});  // input de @ por post
  const [influencers, setInfluencers] = React.useState([]);   // cadastrados (pra adicionar rápido)
  const [orgs, setOrgs] = React.useState([]);                 // empresas de evento (pra marcar o @ do evento)
  const [infcos, setInfcos] = React.useState([]);             // empresas influencer (ex.: loucosdatelecom) — @ marcável
  React.useEffect(() => { window.mpApi.listInfluencers(company.id).then(l => setInfluencers(l || [])).catch(() => {}); }, [company.id]);
  React.useEffect(() => { window.mpApi.listOrganizers(company.id).then(l => setOrgs(l || [])).catch(() => {}); }, [company.id]);
  React.useEffect(() => { window.mpApi.listInfCompanies(company.id).then(l => setInfcos(l || [])).catch(() => {}); }, [company.id]);
  function curCollabs(p) { return collabs[p.id] || []; }   // VAZIO por padrão — collab é opção MANUAL por post (nunca automático)
  function addCollab(p, h) { h = (h || '').trim().replace(/^@/, ''); if (!h) return; const cur = curCollabs(p); if (cur.includes(h) || cur.length >= 3) return; setCollabs(s => ({ ...s, [p.id]: [...cur, h] })); setCollabIn(s => ({ ...s, [p.id]: '' })); }
  function rmCollab(p, h) { setCollabs(s => ({ ...s, [p.id]: curCollabs(p).filter(x => x !== h) })); }

  const load = React.useCallback(() => {
    window.mpApi.listPosts().then(r => setPosts((r.posts || []).filter(p => p.company_id === company.id && ['REVIEW', 'DRAFT', 'APPROVED', 'SCHEDULED'].includes(p.status)))).catch(() => {});
    window.mpApi.socialAccounts(company.id).then(a => setAccounts(a || [])).catch(() => {});
  }, [company.id]);
  React.useEffect(() => { load(); }, [load]);

  const connected = accounts.filter(a => a.status === 'connected' || a.status === 'active');
  function channelsFor(p) {
    const nets = p.networks || [];
    let chans = connected.filter(a => nets.includes(a.platform));
    if (!chans.length) chans = connected;        // sem match: usa todas conectadas
    return chans.map(a => ({ socialConnectionId: a.id, platform: a.platform }));
  }
  function contentType(p) {
    const u = (p.media_url || '').toLowerCase();
    if (u.endsWith('.mp4')) return 'video';
    if (u) return 'image';
    return 'text';
  }

  async function del(id) { if (!window.confirm('Excluir este post?')) return; try { await window.mpApi.deletePost(id); load(); } catch (e) { setMsg('Erro: ' + e.message); } }

  async function doPublish(p, scheduledAt) {
    const channels = channelsFor(p);
    if (!channels.length) { setMsg('Nenhuma rede conectada. Conecte Instagram/Facebook no cliente.'); return; }
    setBusy(p.id); setMsg(scheduledAt ? 'Agendando…' : 'Publicando agora…');
    try {
      // Modo teste: auto-aprova a peça antes de publicar (sem precisar passar pela aprovação).
      if (p.status !== 'APPROVED' && p.status !== 'SCHEDULED') {
        if (p.status === 'DRAFT') { try { await window.mpApi.transitionPost(p.id, 'REVIEW'); } catch (_) {} }
        try { await window.mpApi.transitionPost(p.id, 'APPROVED'); } catch (_) {}
      }
      // Composio/Instagram exige URL pública ABSOLUTA da mídia.
      const toAbs = u => u ? (/^https?:/i.test(u) ? u : (window.location.origin + u)) : '';
      const meta = p.meta || {};
      const isCarousel = meta.content_type === 'carousel' && Array.isArray(meta.carousel_urls) && meta.carousel_urls.length > 1;
      const abs = toAbs(p.media_url);
      const assetUrls = isCarousel ? meta.carousel_urls.map(toAbs).filter(Boolean) : (abs ? [abs] : []);
      await window.mpApi.socialCreatePost({
        brandId: company.id, sourcePostId: p.id, channels,
        assetUrls,
        contentType: isCarousel ? 'carousel' : (meta.content_type === 'story' ? 'story' : contentType(p)), scheduledAt: scheduledAt || null,
        collaborators: curCollabs(p),               // COLLAB: lista editável (influencer + quem você adicionar)
      });
      try {
        if (scheduledAt) {
          if (window.mpApi.updatePost) await window.mpApi.updatePost(p.id, { scheduled_at: scheduledAt });
          await window.mpApi.transitionPost(p.id, 'SCHEDULED');
        } else {
          await window.mpApi.transitionPost(p.id, 'PUBLISHED');   // marca como publicado (Painel/Agenda)
        }
      } catch (_) {}
      setMsg(scheduledAt ? 'Agendado nas redes conectadas.' : 'Publicado nas redes (via Composio).'); load();
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(''); }
  }
  function agendar(p) {
    if (!when[p.id]) { setMsg('Defina data/hora para ' + (p.title || 'post')); return; }
    doPublish(p, when[p.id]);
  }

  return <div className="stack">
    <div className="sec mut">Redes conectadas</div>
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
      {['instagram', 'facebook'].map(net => {
        const acc = accounts.find(a => a.platform === net);
        const ok = acc && (acc.status === 'connected' || acc.status === 'active');
        return <Pill key={net} kind={ok ? 'good' : acc ? 'warn' : ''} dot>{net}: {acc ? acc.status : 'não conectado'}</Pill>;
      })}
      <button className="btn sm ghost" onClick={() => window.__mpOpen && window.__mpOpen('clientes')}><Icon name="link" />Conectar</button>
    </div>
    <div className="hint">Publica direto nas redes sociais conectadas (Composio). Publique agora ou agende.</div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    {posts.map(p => <div key={p.id} className="panel stack">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <b>{p.title || 'Post'} · <small>{(p.networks || []).join(', ')}</small></b>
        <Pill kind={p.status === 'SCHEDULED' ? 'good' : 'cy'} dot>{p.status}</Pill>
      </div>
      {(p.meta || {}).content_type === 'carousel' && Array.isArray((p.meta || {}).carousel_urls)
        ? <div>
            <Pill kind="cy">Carrossel · {p.meta.carousel_urls.length} telas</Pill>
            <div style={{ display: 'flex', gap: 6, overflowX: 'auto', marginTop: 6 }}>
              {p.meta.carousel_urls.map((u, k) => <img loading="lazy" decoding="async" key={k} src={u} style={{ height: 110, borderRadius: 6, flex: '0 0 auto' }} />)}
            </div>
          </div>
        : (p.media_url && (contentType(p) === 'video'
          ? <video src={p.media_url} controls style={{ maxHeight: 120, borderRadius: 6 }} />
          : <img loading="lazy" decoding="async" src={p.media_url} style={{ maxHeight: 120, borderRadius: 6, alignSelf: 'flex-start' }} />))}
      <div className="stack" style={{ gap: 4 }}>
        <div className="mut" style={{ fontSize: 12 }}>🤝 Colaboradores no Instagram (collab — até 3):</div>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {curCollabs(p).map(h => <Pill key={h} kind="cy">@{h} <span style={{ cursor: 'pointer', fontWeight: 700 }} onClick={() => rmCollab(p, h)}>✕</span></Pill>)}
          {curCollabs(p).length < 3 && <>
            <input className="inp" style={{ width: 150 }} placeholder="@ outro perfil" value={collabIn[p.id] || ''}
              onChange={e => setCollabIn(s => ({ ...s, [p.id]: e.target.value }))}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCollab(p, collabIn[p.id]); } }} />
            <button className="btn sm ghost" onClick={() => addCollab(p, collabIn[p.id])}>+ marcar</button>
            {influencers.filter(i => i.handle).length > 0 && <select className="inp" style={{ width: 170 }} value="" onChange={e => { if (e.target.value) addCollab(p, e.target.value); }}>
              <option value="">+ influencer cadastrado…</option>
              {influencers.filter(i => i.handle).map(i => <option key={i.id} value={i.handle}>{i.name} · @{String(i.handle).replace(/^@/, '')}</option>)}
            </select>}
            {orgs.filter(o => o.instagram).length > 0 && <select className="inp" style={{ width: 170 }} value="" onChange={e => { if (e.target.value) addCollab(p, e.target.value); }}>
              <option value="">+ @ do evento/empresa…</option>
              {orgs.filter(o => o.instagram).map(o => <option key={o.id} value={o.instagram}>{o.name} · @{String(o.instagram).replace(/^@/, '')}</option>)}
            </select>}
            {infcos.filter(c => c.handle).length > 0 && <select className="inp" style={{ width: 170 }} value="" onChange={e => { if (e.target.value) addCollab(p, e.target.value); }}>
              <option value="">+ @ empresa influencer…</option>
              {infcos.filter(c => c.handle).map(c => <option key={c.id} value={c.handle}>{c.name} · @{String(c.handle).replace(/^@/, '')}</option>)}
            </select>}
            {((p.meta || {}).collab_handle || '').trim() && !curCollabs(p).includes(String(p.meta.collab_handle).replace(/^@/, '')) &&
              <button className="btn sm ghost" onClick={() => addCollab(p, p.meta.collab_handle)} title="Influencer usado nesta arte (sugestão)">+ @{String(p.meta.collab_handle).replace(/^@/, '')} (da arte)</button>}
          </>}
        </div>
      </div>
      {(p.meta || {}).content_type === 'story'
        ? <div className="hint" style={{ fontSize: 12, color: 'var(--cyan)' }}>📲 É um <b>Story (9:16)</b> — "Publicar agora" posta direto no seu story.</div>
        : <div className="hint" style={{ fontSize: 12 }}>📲 Pra <b>compartilhar este post no seu story</b> (clicável, abre o post): use <b>"Adicionar ao story"</b> no app do Instagram — 1 toque, nativo. A <b>API não tem</b> essa função (conferido nas 36 ações do Composio).</div>}
      <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="btn sm pri" disabled={busy === p.id} onClick={() => doPublish(p, null)}><Icon name="send" />Publicar agora</button>
        <input className="inp" type="datetime-local" value={when[p.id] || ''} onChange={e => setWhen(w => ({ ...w, [p.id]: e.target.value }))} />
        <button className="btn sm" disabled={busy === p.id} onClick={() => agendar(p)}><Icon name="clock" />Agendar</button>
        <button className="btn sm ghost" disabled={busy === p.id} onClick={() => del(p.id)}><Icon name="trash" />Excluir</button>
      </div>
    </div>)}
    {!posts.length && <div className="hint">Nenhum post aprovado. Aprove na etapa anterior.</div>}
  </div>;
}

/* ── Config de Notificações (Evolution WhatsApp + SMTP) ── */
function NotifConfigApp() {
  const [status, setStatus] = React.useState(null);
  const [evoUrl, setEvoUrl] = React.useState('');
  const [evoInstance, setEvoInstance] = React.useState('');
  const [evoKey, setEvoKey] = React.useState('');
  const [smtpHost, setSmtpHost] = React.useState('');
  const [smtpPort, setSmtpPort] = React.useState('587');
  const [smtpUser, setSmtpUser] = React.useState('');
  const [smtpPass, setSmtpPass] = React.useState('');
  const [smtpFrom, setSmtpFrom] = React.useState('');
  const [smtpFromName, setSmtpFromName] = React.useState('');
  const [testTo, setTestTo] = React.useState('');
  const [testCh, setTestCh] = React.useState('whatsapp');
  const [msg, setMsg] = React.useState('');

  const load = React.useCallback(() => {
    window.mpApi.notifyConfig().then(s => {
      setStatus(s);
      setEvoUrl((s.whatsapp || {}).url || '');
      setEvoInstance((s.whatsapp || {}).instance || '');
      setSmtpHost((s.smtp || {}).host || '');
      setSmtpFrom((s.smtp || {}).from || '');
    }).catch(() => {});
  }, []);
  React.useEffect(() => { load(); }, [load]);

  async function save() {
    setMsg('Salvando…');
    try {
      await window.mpApi.saveNotifyConfig({
        evolution: { url: evoUrl, instance: evoInstance, ...(evoKey ? { apiKey: evoKey } : {}) },
        smtp: { host: smtpHost, port: smtpPort, user: smtpUser, from: smtpFrom, fromName: smtpFromName, ...(smtpPass ? { pass: smtpPass } : {}) },
      });
      setEvoKey(''); setSmtpPass(''); setMsg('Configuração salva.'); load();
    } catch (e) { setMsg('Erro: ' + e.message); }
  }
  async function test() {
    if (!testTo.trim()) { setMsg('Informe destinatário de teste.'); return; }
    setMsg('Enviando teste…');
    try {
      const r = await window.mpApi.notifyTest({ channel: testCh, to: testTo.trim(), message: 'Teste de notificação do Caripost ✅' });
      setMsg(r.ok ? 'Teste enviado!' : ('Falha: ' + (r.error || r.detail || JSON.stringify(r))));
    } catch (e) { setMsg('Erro: ' + e.message); }
  }

  return <div className="app">
    <div className="app-head">
      <div className="tb-ic" style={{ width: 40, height: 40, borderRadius: 12 }}><Icon name="bell" style={{ width: 20, height: 20 }} /></div>
      <div className="lead"><div className="app-title">Notificações</div><div className="app-desc">WhatsApp (Evolution API) e e-mail (SMTP).</div></div>
    </div>
    {msg && <div className={msg.startsWith('Erro') || msg.startsWith('Falha') ? 'err' : 'ok'}>{msg}</div>}
    <div className="split">
      <div className="panel stack">
        <div className="sec cy">WhatsApp · Evolution API {status && status.whatsapp && status.whatsapp.configured && <Pill kind="good" dot>ok</Pill>}</div>
        <Field label="URL"><input className="inp" value={evoUrl} onChange={e => setEvoUrl(e.target.value)} placeholder="https://evolution.seudominio.com" /></Field>
        <Field label="Instância"><input className="inp" value={evoInstance} onChange={e => setEvoInstance(e.target.value)} placeholder="nome-da-instancia" /></Field>
        <Field label="API Key"><input className="inp" type="password" value={evoKey} onChange={e => setEvoKey(e.target.value)} placeholder={status && status.whatsapp && status.whatsapp.configured ? '•••••• (salvo)' : 'apikey global'} /></Field>
      </div>
      <div className="panel stack">
        <div className="sec mut">E-mail · SMTP {status && status.smtp && status.smtp.configured && <Pill kind="good" dot>ok</Pill>}</div>
        <div className="split">
          <Field label="Host"><input className="inp" value={smtpHost} onChange={e => setSmtpHost(e.target.value)} placeholder="smtp.gmail.com" /></Field>
          <Field label="Porta"><input className="inp" value={smtpPort} onChange={e => setSmtpPort(e.target.value)} placeholder="587" /></Field>
        </div>
        <Field label="Usuário"><input className="inp" value={smtpUser} onChange={e => setSmtpUser(e.target.value)} /></Field>
        <Field label="Senha"><input className="inp" type="password" value={smtpPass} onChange={e => setSmtpPass(e.target.value)} placeholder={status && status.smtp && status.smtp.configured ? '•••••• (salvo)' : ''} /></Field>
        <div className="split">
          <Field label="From"><input className="inp" value={smtpFrom} onChange={e => setSmtpFrom(e.target.value)} placeholder="noreply@dominio.com" /></Field>
          <Field label="Nome remetente"><input className="inp" value={smtpFromName} onChange={e => setSmtpFromName(e.target.value)} placeholder="Caripost" /></Field>
        </div>
      </div>
    </div>
    <button className="btn pri" onClick={save}>Salvar configuração</button>
    <div className="panel stack">
      <div className="sec mut">Testar envio</div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <select className="inp" value={testCh} onChange={e => setTestCh(e.target.value)} style={{ maxWidth: 150 }}>
          <option value="whatsapp">WhatsApp</option>
          <option value="email">E-mail</option>
        </select>
        <input className="inp" value={testTo} onChange={e => setTestTo(e.target.value)} placeholder={testCh === 'whatsapp' ? 'Número (DDD+telefone)' : 'email@teste.com'} style={{ flex: 1, minWidth: 200 }} />
        <button className="btn" onClick={test}><Icon name="send" />Enviar teste</button>
      </div>
    </div>
  </div>;
}

/* ── Dashboard da agência (visão de todos os clientes) ── */
function PainelApp() {
  const [companies, setCompanies] = React.useState([]);
  const [posts, setPosts] = React.useState([]);
  const [accountsByCo, setAccountsByCo] = React.useState({});
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    if (!window.mpApi) return;
    setLoading(true);
    try {
      const [cos, pr] = await Promise.all([window.mpApi.listCompanies(), window.mpApi.listPosts()]);
      const list = cos || [];
      setCompanies(list);
      setPosts((pr.posts) || []);
      const accs = {};
      await Promise.all(list.map(async c => {
        const id = c.id || c.company_id;
        try { accs[id] = await window.mpApi.socialAccounts(id); } catch (e) { accs[id] = []; }
      }));
      setAccountsByCo(accs);
    } catch (e) {}
    setLoading(false);
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const by = s => posts.filter(p => p.status === s).length;
  const problems = [];
  companies.forEach(c => {
    const id = c.id || c.company_id;
    const accs = accountsByCo[id] || [];
    const bad = accs.filter(a => a.status && a.status !== 'connected' && a.status !== 'active');
    if (bad.length) problems.push({ company: c, bad });
  });

  return <div className="app">
    <div className="app-head">
      <div className="tb-ic" style={{ width: 40, height: 40, borderRadius: 12 }}><Icon name="grid" style={{ width: 20, height: 20 }} /></div>
      <div className="lead"><div className="app-title">Painel da Agência</div><div className="app-desc">Visão geral de todos os clientes.</div></div>
      <button className="btn sm ghost" onClick={load}><Icon name="refs" />Atualizar</button>
    </div>
    {loading && <div className="hint">Carregando…</div>}
    <div className="grid3">
      <div className="stat"><div className="sv">{companies.length}</div><div className="sl">Clientes</div></div>
      <div className="stat"><div className="sv">{by('REVIEW')}</div><div className="sl">Aguardando aprovação</div></div>
      <div className="stat"><div className="sv">{by('APPROVED')}</div><div className="sl">Aprovados</div></div>
      <div className="stat"><div className="sv">{by('SCHEDULED')}</div><div className="sl">Agendados</div></div>
      <div className="stat"><div className="sv">{by('PUBLISHED')}</div><div className="sl">Publicados</div></div>
      <div className="stat"><div className="sv">{problems.length}</div><div className="sl">Conexões c/ problema</div></div>
    </div>

    <div className="split">
      <div className="panel stack">
        <div className="sec mut">Pendências por cliente</div>
        {companies.map(c => {
          const id = c.id || c.company_id;
          const rev = posts.filter(p => p.company_id === id && p.status === 'REVIEW').length;
          const sch = posts.filter(p => p.company_id === id && p.status === 'SCHEDULED').length;
          return <div key={id} className="litem" style={{ padding: 8 }}>
            <div className="li-main"><b>{c.name || c.n}</b><small>{rev} p/ aprovar · {sch} agendados</small></div>
            <button className="btn sm ghost" onClick={() => window.__mpOpen && window.__mpOpen('conteudo')}><Icon name="post" />Fluxo</button>
          </div>;
        })}
        {!loading && !companies.length && <div className="hint">Nenhum cliente.</div>}
      </div>
      <div className="panel stack">
        <div className="sec mut">Conexões com problema</div>
        {problems.map(({ company, bad }) => <div key={company.id || company.company_id} className="litem" style={{ padding: 8 }}>
          <div className="li-main"><b>{company.name || company.n}</b><small>{bad.map(b => b.platform + ':' + b.status).join(', ')}</small></div>
          <button className="btn sm ghost" onClick={() => window.__mpOpen && window.__mpOpen('clientes')}><Icon name="link" />Reconectar</button>
        </div>)}
        {!problems.length && <div className="hint">Tudo conectado 👍</div>}
      </div>
    </div>
  </div>;
}

/* ── Acervo / biblioteca por cliente ── */
function AcervoApp() {
  const [companies, setCompanies] = React.useState([]);
  const [companyId, setCompanyId] = React.useState('');
  const [logos, setLogos] = React.useState([]);
  const [refs, setRefs] = React.useState([]);
  const [posts, setPosts] = React.useState([]);
  const [cat, setCat] = React.useState('tudo');
  const [sel, setSel] = React.useState(null);

  React.useEffect(() => { window.mpApi.listCompanies().then(c => setCompanies(c || [])).catch(() => {}); }, []);
  React.useEffect(() => {
    window.mpApi.listPosts().then(r => setPosts((r.posts || []).filter(p => p.media_url))).catch(() => {});
    if (companyId) {
      window.mpApi.listLogos(companyId).then(l => setLogos(l || [])).catch(() => {});
      window.mpApi.getCompany(companyId).then(c => setRefs((c.references) || [])).catch(() => {});
    } else { setLogos([]); setRefs([]); }
  }, [companyId]);

  const cname = (id) => { const c = companies.find(x => (x.id || x.company_id) === id) || {}; return c.name || c.n || ''; };
  const SL = { REVIEW: 'gerado', DRAFT: 'gerado', APPROVED: 'aprovado', SCHEDULED: 'agendado', PUBLISHED: 'publicado', FAILED: 'falhou' };
  const tone = (s) => s === 'publicado' || s === 'aprovado' ? 'good' : s === 'agendado' ? 'cy' : '';
  const dt = (p) => { const v = p.published_at || p.scheduled_at || p.reviewed_at || p.created_at; return v ? new Date(v).toLocaleDateString('pt-BR') : ''; };
  const fp = posts.filter(p => !companyId || p.company_id === companyId);
  const CATS = [['tudo', 'Tudo'], ['gerado', 'Gerados'], ['aprovado', 'Aprovados'], ['agendado', 'Agendados'], ['publicado', 'Publicados'], ['logos', 'Logos'], ['ref', 'Referências']];
  let items;
  if (cat === 'logos') items = logos.map(l => ({ id: 'l' + l.id, url: l.url, title: 'Logo', contain: true }));
  else if (cat === 'ref') items = refs.map(r => ({ id: 'r' + r.id, url: r.url, title: 'Referência' }));
  else { const all = fp.map(p => ({ id: 'p' + p.id, url: p.media_url, title: p.title || 'Peça', sub: SL[p.status] || p.status, post: p, company: cname(p.company_id) })); items = cat === 'tudo' ? all : all.filter(it => it.sub === cat); }

  return <div className="app">
    <div className="app-head">
      <div className="tb-ic" style={{ width: 40, height: 40, borderRadius: 12 }}><Icon name="media" style={{ width: 20, height: 20 }} /></div>
      <div className="lead"><div className="app-title">Acervo</div><div className="app-desc">Logos, referências e peças — por cliente e status. Clique para expandir.</div></div>
    </div>
    <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
      <select className="inp" value={companyId} onChange={e => setCompanyId(e.target.value)} style={{ maxWidth: 220 }}>
        <option value="">Todos os clientes</option>
        {companies.map(c => <option key={c.id || c.company_id} value={c.id || c.company_id}>{c.name || c.n}</option>)}
      </select>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {CATS.map(([k, l]) => <button key={k} className={'btn sm' + (cat === k ? ' pri' : ' ghost')} onClick={() => setCat(k)} disabled={(k === 'logos' || k === 'ref') && !companyId}>{l}</button>)}
      </div>
    </div>
    {(cat === 'logos' || cat === 'ref') && !companyId && <div className="hint">Selecione um cliente para ver logos/referências.</div>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 12, marginTop: 8 }}>
      {items.map(it => <div key={it.id} className="panel" style={{ padding: 8, cursor: it.post ? 'zoom-in' : 'default' }} onClick={() => it.post && setSel(it.post)}>
        <img loading="lazy" decoding="async" src={it.url} style={{ width: '100%', height: 150, objectFit: it.contain ? 'contain' : 'cover', borderRadius: 6, background: it.contain ? '#fff' : 'transparent' }} />
        <div className="li-main" style={{ marginTop: 6 }}><b style={{ fontSize: 13 }}>{it.title}</b>{it.sub && <small>{it.sub}{it.company ? ' · ' + it.company : ''}</small>}</div>
      </div>)}
      {!items.length && <div className="hint">Nada nesta categoria ainda.</div>}
    </div>
    {sel && <div onClick={() => setSel(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'grid', placeItems: 'center', zIndex: 9999, padding: 16 }}>
      <div onClick={e => e.stopPropagation()} className="panel stack" style={{ maxWidth: 440, maxHeight: '92vh', overflow: 'auto' }}>
        <div className="rowx" style={{ justifyContent: 'space-between' }}><b>{sel.title || 'Peça'}</b><button className="btn sm ghost" onClick={() => setSel(null)}><Icon name="x" /></button></div>
        <img loading="lazy" decoding="async" src={sel.media_url} style={{ width: '100%', borderRadius: 8, border: '1px solid var(--line)' }} />
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <Pill kind={tone(SL[sel.status])} dot>{SL[sel.status] || sel.status}</Pill>
          {(sel.networks || []).map(n => <Pill key={n} kind="cy">{n}</Pill>)}
          {cname(sel.company_id) && <Pill>{cname(sel.company_id)}</Pill>}
          {dt(sel) && <Pill>{dt(sel)}</Pill>}
        </div>
        <div className="hint" style={{ whiteSpace: 'pre-wrap' }}>{sel.copy}</div>
        {sel.hashtags && sel.hashtags.length ? <div className="hint" style={{ color: 'var(--accent)' }}>{(sel.hashtags || []).join(' ')}</div> : null}
      </div>
    </div>}
  </div>;
}

/* Estado em memória do fluxo, por cliente (rascunho retomável na sessão). */
// Persiste em localStorage → NÃO perde os carrosséis (que custaram IA) ao fechar/recarregar a tela.
// Mantém um cache em memória pra leitura rápida; toda escrita grava no disco do navegador.
// PROJETOS por empresa: cada projeto = 1 trabalho (briefing + telas + artes + settings).
// Entrar é LIMPO por padrão (activeId=null → get() vazio). As caixinhas deixam CONTINUAR um projeto salvo.
// get()/set() operam TRANSPARENTE no projeto ATIVO (componentes não mudam). 1º write cria projeto sozinho.
const ContState = {
  _key: 'mp_cont_state_v2',
  _d: (() => {
    let d = {};
    try { d = JSON.parse(localStorage.getItem('mp_cont_state_v2') || '{}'); } catch (e) { d = {}; }
    try {   // MIGRA o trabalho antigo (chave v1, achatada) → projetos v2, uma única vez
      if (!d.__mig1) {
        const v1 = JSON.parse(localStorage.getItem('mp_cont_state_v1') || '{}');
        const nA = rs => (rs || []).reduce((a, v) => a + ((v.slides || []).length), 0);
        Object.keys(v1).forEach(cid => {
          if (!cid || cid.indexOf('__') === 0) return;
          const b = v1[cid] || {};
          const co = d[cid] || (d[cid] = { projetos: {}, activeId: null });
          if (!co.projetos) co.projetos = {};
          if (Object.keys(co.projetos).length) return;   // já tem projeto → não duplica
          (b.carouselSessions || []).forEach((s, k) => {   // sessões arquivadas ("Novo do zero")
            const pid = s.id || ('pjm_' + cid + '_' + k);
            co.projetos[pid] = { id: pid, ts: s.ts || (Date.now() - k), label: s.label || 'Projeto',
              assunto: s.assunto || '', assuntoTema: s.assunto || '', briefing: s.briefing || '',
              telas: s.telas || [], carouselResults: s.results || [], formato: 'carrossel', fmt: 'carrossel', nArtes: nA(s.results) };
          });
          if ((b.telas || []).length || (b.carouselResults || []).length || b.briefing) {   // trabalho ATUAL achatado
            const pid = 'pjm_cur_' + cid;
            co.projetos[pid] = { id: pid, ts: Date.now(),
              label: ((b.assuntoTema || b.assunto || (b.telas && b.telas[0] && b.telas[0].title) || 'Projeto') + '').slice(0, 50),
              assunto: b.assunto || '', assuntoTema: b.assuntoTema || '', briefing: b.briefing || '',
              telas: b.telas || [], carouselResults: b.carouselResults || [], carouselVersions: b.carouselVersions,
              useInfluencer: b.useInfluencer, influencerId: b.influencerId,
              formato: b.formato || 'carrossel', fmt: b.formato || 'carrossel', nArtes: nA(b.carouselResults) };
          }
        });
        d.__mig1 = true;
        try { localStorage.setItem('mp_cont_state_v2', JSON.stringify(d)); } catch (e) {}
      }
    } catch (e) {}
    return d;
  })(),
  _save() { try { localStorage.setItem(this._key, JSON.stringify(this._d)); } catch (e) {} },
  _co(id) { const c = this._d[id] || (this._d[id] = { projetos: {}, activeId: null }); if (!c.projetos) c.projetos = {}; return c; },
  get(id) { const c = this._co(id); return (c.activeId && c.projetos[c.activeId]) ? c.projetos[c.activeId] : {}; },
  set(id, patch) {
    const c = this._co(id);
    if (!c.activeId || !c.projetos[c.activeId]) { c.activeId = 'pj_' + Date.now(); c.projetos[c.activeId] = { id: c.activeId, createdAt: Date.now() }; }
    const p = { ...c.projetos[c.activeId], ...patch };
    p.id = c.activeId; p.ts = Date.now();
    p.label = ((p.assuntoTema || p.assunto || (p.telas && p.telas[0] && p.telas[0].title) || 'Sem título') + '').slice(0, 50);
    p.fmt = p.formato || p.fmt || 'carrossel';
    p.nArtes = (p.carouselResults || []).reduce((a, v) => a + ((v.slides || []).length), 0);
    c.projetos[c.activeId] = p; this._save();
  },
  projetos(id) { return Object.values(this._co(id).projetos || {}).filter(p => p && (p.telas || []).length || (p.carouselResults || []).length || p.briefing).sort((a, b) => (b.ts || 0) - (a.ts || 0)); },
  activeId(id) { return this._co(id).activeId; },
  novo(id) { this._co(id).activeId = null; this._save(); },            // começar LIMPO (nenhum projeto ativo)
  abrir(id, pid) { const c = this._co(id); if (c.projetos[pid]) { c.activeId = pid; this._save(); } },   // CONTINUAR um projeto
  excluir(id, pid) { const c = this._co(id); delete c.projetos[pid]; if (c.activeId === pid) c.activeId = null; this._save(); },
};

Object.assign(window, { ConteudoApp, NotifConfigApp, PainelApp, AcervoApp, ContState });
