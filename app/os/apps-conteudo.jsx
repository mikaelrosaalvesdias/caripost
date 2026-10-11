/* Caripost OS — Fluxo de Conteúdo (standalone, fora do cliente)
   Passos: 0 Cliente · 1 Briefing · 2 Criação · 3 Aprovação · 4 Agendamento
   Reaproveita os endpoints existentes (social/companies/posts). */

// Modelos de imagem agrupados por PROVEDOR (OmniRoute/CometAPI/PiAPI/OpenRouter) — seletor provedor+modelo.
function isClientUser() { const u = window.__mpUser; return !!(u && (u.role === 'owner' || u.role === 'agency')); }
function clientMaxVer() { const u = window.__mpUser; const f = (u && u.features) || {}; return Math.max(1, Math.min(4, parseInt(f.versoes_max) || 2)); }
const IMG_PROV_LABELS = { omniroute: 'OmniRoute (grátis · assinatura)', cometapi: 'CometAPI', piapi: 'PiAPI', openrouter: 'OpenRouter', kie: 'kie.ai (créditos)' };
function addRunPosts(cid, ids) {   // registra os posts criados NESTE run/projeto (a Aprovação mostra só eles)
  const cur = (ContState.get(cid).runPostIds) || [];
  ContState.set(cid, { runPostIds: Array.from(new Set([...cur, ...(ids || []).filter(Boolean)])) });
}
async function copyContentText(value) {
  const text = String(value || '');
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    const el = document.createElement('textarea');
    el.value = text;
    el.setAttribute('readonly', '');
    el.style.position = 'fixed'; el.style.opacity = '0';
    document.body.appendChild(el); el.select();
    try { return document.execCommand('copy'); }
    finally { document.body.removeChild(el); }
  }
}
function imgGroups(list) {
  const g = {}; (list || []).forEach(m => { const p = m.provider || 'outros'; (g[p] = g[p] || []).push(m); });
  return Object.keys(g).map(p => ({ provider: p, label: IMG_PROV_LABELS[p] || p, models: g[p] }));
}
function imgPriceKind(m) {
  if (m.free) return '';
  if (m.price_source === 'usage_learned') return ' · real';
  if (m.price_source === 'catalog_api') return ' · catálogo';
  if (m.price_source) return ' · estimado';
  return '';
}
function imgOptLabel(m) { return m.name + (m.credits ? ' · ' + m.credits + ' cr/img' + (m.credits_learned ? '' : '~') : (m.price_brl ? ' · R$ ' + Number(m.price_brl).toFixed(2) + imgPriceKind(m) : (m.free ? ' · grátis' : ''))); }

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
  const offerRefs = Array.isArray(st.offer_refs) ? st.offer_refs : [];
  const theme = ((st.briefing || '').trim() || (st.assunto || '').trim());
  const [dur, setDur] = React.useState(st.videoSeconds || 0);
  const [vmodels, setVmodels] = React.useState([]);
  const [model, setModel] = React.useState('');
  const [pf, setPf] = React.useState(null);
  const [scenes, setScenes] = React.useState([]);      // roteiro por cena (editável antes de gastar)
  const [nonce, setNonce] = React.useState(0);          // ↻ regerar roteiro
  const [style, setStyle] = React.useState(st.videoStyle || 'auto');   // Fase 3: estilo viral
  const [styleList, setStyleList] = React.useState([]);
  const [regening, setRegening] = React.useState(-1);   // índice da cena sendo regerada
  const [planning, setPlanning] = React.useState(false);
  const [status, setStatus] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [proc, setProc] = React.useState({ open: false });   // mesma animação (ProcessModal) da geração de imagem
  const [costAsk, setCostAsk] = React.useState(false);       // confirmação de GASTO REAL (substitui window.confirm)
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
  React.useEffect(() => { window.mpApi.videoStyles(company.id).then(setStyleList).catch(() => {}); }, [company.id]);
  React.useEffect(() => {
    if (!model || !theme) return;
    setPlanning(true);
    // REUSA o roteiro do BRIEFING (determinístico, sem re-gerar e sem custo). "↻ Regerar roteiro" (nonce>0) força nova geração.
    const _seed = (nonce === 0) ? ((ContState.get(company.id) || {}).videoStoryboard || []) : [];
    window.mpApi.videoPreflight(company.id, theme, dur, style, _seed, [], model, offerRefs).then(p => { setPf(p); setScenes((p && p.scene_descs) || []); }).catch(() => {}).finally(() => setPlanning(false));
  }, [model, dur, nonce, style]);   // custo AUTOMÁTICO · nonce = ↻ regerar roteiro · style = estilo viral
  async function selectModel(id) { setModel(id); setPf(null); try { await window.mpApi.setAiModel({ video_model: id }); } catch (e) {} }
  function setDuration(d) { setDur(d); ContState.set(company.id, { videoSeconds: d }); }
  function setStyleSel(s) { setStyle(s); ContState.set(company.id, { videoStyle: s }); }
  async function regenScene(idx) {
    setRegening(idx);
    try {
      const r = await window.mpApi.regenScene({ company_id: company.id, theme, scene_descs: scenes, index: idx, character: (pf && pf.character) || '', style });
      if (r && r.desc) setScenes(s => s.map((x, i) => i === idx ? r.desc : x));
    } catch (e) { /* mantém a cena atual */ }
    finally { setRegening(-1); }
  }
  function pedirGerar() {
    if (!pf || !pf.configured) { setMsg('Erro: escolha um modelo de vídeo (configure a chave no painel de IA).'); return; }
    setCostAsk(true);
  }
  async function gerar() {
    if (!pf || !pf.configured) { setMsg('Erro: escolha um modelo de vídeo (configure a chave no painel de IA).'); return; }
    setCostAsk(false);
    setBusy(true); setMsg(''); setStatus(null);
    videoStartRef.current = Date.now();
    lastPctRef.current = 3;
    setProc({ open: true, pct: 3, detail: 'Iniciando a geração do vídeo…', phase: '' });
    try {
      const currentState = ContState.get(company.id) || {};
      const targetSeconds = Number(dur) || Number(currentState.videoSeconds) || 0;
      const sceneSeconds = pf.seconds_per_scene || ((pf.scene_seconds || [])[0]) || 8;
      const r = await window.mpApi.generateBrandedVideo({
        company_id: company.id,
        model,
        theme,
        storyboard: pf.storyboard,
        scene_descs: scenes,              // roteiro (possivelmente editado) por cena
        character: pf.character || '',     // mapa do personagem travado (re-injetado no backend)
        style,                             // estilo viral escolhido (Fase 3)
        target_seconds: targetSeconds,
        seconds: targetSeconds,
        scene_seconds: sceneSeconds,
        cta: currentState.cta || '',
        offer_refs: offerRefs,
      });
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
          const costLabel = s.is_credits ? ('Consumiu ' + s.credits_used + ' créditos kie') : ((s.cost_source === 'catalog_estimate' ? 'Custo estimado' : 'Custo REAL') + ': ' + brl(s.cost_usd));
          setProc({ open: true, pct: 100, phase: 'done', detail: 'Vídeo pronto! ' + costLabel });
          setBusy(false); return;
        }
        else if (s.status === 'error') { setProc({ open: true, phase: 'error', detail: (s.detail || 'falhou') + ' · ' + _videoCostText(s, brl) }); setBusy(false); return; }
      }
      setProc({ open: true, phase: 'error', detail: 'Demorando demais — recarregue a página pra ver o status.' }); setBusy(false);
    } catch (e) { setProc({ open: true, phase: 'error', detail: e.message }); setBusy(false); }
  }
  const DURS = [[0, 'Livre (IA decide)'], [8, '8s'], [15, '15s'], [30, '30s'], [60, '60s']];
  const PLAB = { kie: 'kie.ai (créditos)', cometapi: 'CometAPI', openrouter: 'OpenRouter', openai: 'OpenAI' };
  const vgroups = (() => { const g = {}; vmodels.forEach(m => { const p = m.provider || 'outros'; (g[p] = g[p] || []).push(m); }); return Object.keys(g).map(p => ({ provider: p, label: PLAB[p] || p, models: g[p] })); })();
  const vlabel = (m) => (m.name || m.id) + (m.max_seconds ? ' · até ' + m.max_seconds + 's' : '') + (m.credits ? ' · ' + m.credits + ' cr/clipe' + (m.credits_learned ? '' : '~') : (m.price_brl ? ' · R$ ' + Number(m.price_brl).toFixed(2) + '/clipe' + imgPriceKind(m) : ''));
  if (!theme) return <div className="panel stack"><div className="hint">Volte ao Briefing, escreva o assunto e gere o roteiro do vídeo primeiro.</div></div>;
  return <div className="panel stack">
    <div className="sec"><Icon name="video" />Gerar vídeo branded (9:16, com áudio)</div>
    <Field label="Duração — TRAVE quantos segundos quer, ou deixe LIVRE pra IA decidir pelo briefing">
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {DURS.map(([v, t]) => <button key={v} className={'btn sm' + (dur === v ? ' pri' : ' ghost')} onClick={() => setDuration(v)}>{t}</button>)}
      </div>
    </Field>
    {!isClientUser() && <Field label="Modelo de VÍDEO (OpenRouter / CometAPI)">
      <select className="inp" value={model} onChange={e => selectModel(e.target.value)}>
        {vgroups.length ? vgroups.map(g => <optgroup key={g.provider} label={g.label}>
          {g.models.map(m => <option key={m.id} value={m.id}>{vlabel(m)}</option>)}
        </optgroup>) : <option value="">Configure CometAPI/OpenRouter no painel de IA</option>}
      </select>
    </Field>}
    {styleList.length > 0 && <Field label="Estilo do vídeo (vira a linguagem das cenas)">
      <select className="inp" value={style} onChange={e => setStyleSel(e.target.value)}>
        {styleList.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
    </Field>}
    <div className="sec mut">Assunto: {theme.slice(0, 100)}</div>
    {planning && <div className="hint">Montando o roteiro e calculando o custo…</div>}
    {pf && pf.configured && !planning && <div className="hint">→ <b>{pf.scenes} cena(s)</b> (~{pf.total_seconds}s) · {pf.is_credits ? <span>custo ≈ <b>{pf.total_credits} créditos kie</b> <span style={{ opacity: .7 }}>({pf.credits_per_clip}/clipe{pf.credits_learned ? '' : ', estimado'})</span></span> : <span>custo estimado ≈ <b>R$ {pf.total_brl}</b></span>} <span style={{ opacity: .7 }}>(o real vem ao final). As cenas viram <b>1 vídeo só</b>.</span></div>}
    {pf && pf.configured && !planning && scenes.length > 0 && <Field label="Roteiro por cena — edite antes de gerar (gasto só ao confirmar)">
      <div className="stack" style={{ gap: 6 }}>
        {pf.character && <div className="hint" style={{ opacity: .85 }}>🎭 <b>Personagem travado</b> (igual em todas as cenas): {String(pf.character).replace(/^PERSONAGEM FIXO[^:]*:\s*/, '').slice(0, 180)}</div>}
        {scenes.map((d, idx) => <div key={idx} className="row" style={{ gap: 6, alignItems: 'flex-start' }}>
          <span className="hint" style={{ minWidth: 54, paddingTop: 8 }}>Cena {idx + 1}</span>
          <textarea className="inp" rows={2} value={d} style={{ flex: 1, resize: 'vertical' }}
            onChange={e => { const v = e.target.value; setScenes(s => s.map((x, i) => i === idx ? v : x)); }} />
          <button className="btn ghost sm" disabled={regening === idx || planning} title="Regerar só esta cena (sem custo)" style={{ paddingTop: 6 }} onClick={() => regenScene(idx)}>{regening === idx ? '…' : <Icon name="refresh" />}</button>
        </div>)}
        <button className="btn ghost sm" disabled={planning} onClick={() => setNonce(n => n + 1)}><Icon name="refresh" />Regerar roteiro inteiro</button>
      </div>
    </Field>}
    {pf && !pf.configured && !planning && <Callout kind="warn">Escolha um modelo de vídeo acima (e configure a chave no painel de IA).</Callout>}
    {status && status.status === 'done' && status.url && <video src={status.url} controls style={{ width: '100%', maxWidth: 300, borderRadius: 12 }} />}
    {msg && <div className={(msg.startsWith('Erro') || msg.startsWith('Falhou')) ? 'err' : 'ok'}>{msg}</div>}
    <button className="btn pri" disabled={busy || !pf || !pf.configured} onClick={pedirGerar}>{busy ? 'Gerando… (pode levar minutos)' : ('Gerar vídeo' + (pf && pf.total_brl ? ' (≈ R$ ' + pf.total_brl + ')' : ''))}</button>
    {costAsk && pf && <CostConfirm
      kind={pf.is_credits ? 'credits' : 'money'}
      title="Gerar vídeo branded"
      amount={pf.is_credits ? String(pf.total_credits) : `R$ ${pf.total_brl}`}
      unit={pf.is_credits ? 'créditos kie' : 'estimado'}
      confirmLabel="Gerar vídeo"
      lines={[
        { k: 'Cenas', v: `${pf.scenes} (~${pf.total_seconds}s)` },
        ...(pf.is_credits ? [{ k: 'Créditos por clipe', v: String(pf.credits_per_clip) }] : []),
      ]}
      note={pf.is_credits && !pf.credits_learned ? 'Valor estimado.' : ''}
      onConfirm={gerar} onClose={() => setCostAsk(false)} />}
    {proc.open && <ProcessModal open={proc.open} title="Gerando vídeo" detail={proc.detail} pct={proc.pct} phase={proc.phase} onClose={() => setProc({ open: false })} />}
  </div>;
}

/* ══════════════ APP VÍDEO — hub findável das 3 funções: Criar / Animar / Editar bruto ══════════════ */
function VideoCriarStandalone({ company }) {
  const [theme, setTheme] = React.useState(((ContState.get(company.id) || {}).assunto || '').trim());
  const [go, setGo] = React.useState(false);
  function start() { const t = theme.trim(); if (!t) return; ContState.set(company.id, { assunto: t, formato: 'video' }); setGo(true); }
  if (go) return <div className="stack">
    <button className="btn sm ghost" onClick={() => setGo(false)}>← Trocar assunto</button>
    <VideoCreator key={company.id + ':' + theme} company={company} />
  </div>;
  return <div className="panel stack">
    <div className="sec"><Icon name="video" />Criar vídeo do zero</div>
    <div className="hint">Escreva o assunto. A IA monta o roteiro em cenas, você trava a duração e vê o custo ANTES de gerar. Sai um vídeo 9:16 com áudio, logo e CTA da marca.</div>
    <Field label="Assunto do vídeo">
      <textarea className="inp" rows={3} value={theme} onChange={e => setTheme(e.target.value)}
        placeholder="Ex.: Plano gamer 500 Mega com baixa latência pra jogar sem lag" />
    </Field>
    <button className="btn pri" disabled={!theme.trim()} onClick={start}>Montar roteiro →</button>
  </div>;
}

function VideoAnimar({ company }) {
  const [arts, setArts] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [sel, setSel] = React.useState('');
  const [motion, setMotion] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [out, setOut] = React.useState('');
  const [msg, setMsg] = React.useState('');
  React.useEffect(() => {
    setLoading(true); setSel(''); setOut('');
    window.mpApi.listPosts().then(r => {
      const list = (r.posts || []).filter(p => p.company_id === company.id && p.media_url)
        .map(p => ({ id: p.id, url: p.media_url, title: p.title || 'Peça', status: p.status }));
      setArts(list); setLoading(false);
    }).catch(() => setLoading(false));
  }, [company.id]);
  async function animar() {
    if (!sel) { setMsg('Escolha uma arte do portfólio.'); return; }
    setBusy(true); setMsg('Animando… (pode levar ~1–2 min)'); setOut('');
    try {
      const r = await window.mpApi.animateArt(company.id, sel, motion.trim() || undefined);
      if (r && r.url) { setOut(r.url); setMsg('Pronto!'); } else setMsg('Falhou: ' + ((r && (r.detail || r.error)) || 'sem retorno'));
    } catch (err) { setMsg('Erro: ' + (err.message || err)); }
    finally { setBusy(false); }
  }
  return <div className="panel stack">
    <div className="sec"><Icon name="video" />Animar uma arte do portfólio</div>
    <div className="hint">Clique numa arte JÁ criada desta empresa e transforme num clipe curto com movimento (paga em créditos kie). Nada de subir imagem — é o portfólio dela.</div>
    <Field label="Movimento (opcional)"><input className="inp" value={motion} onChange={e => setMotion(e.target.value)} placeholder="Ex.: leve zoom in, partículas, brilho pulsando" /></Field>
    {loading ? <div className="hint">Carregando portfólio de {company.name}…</div>
      : arts.length === 0 ? <div className="hint">Nenhuma arte gerada ainda para <b>{company.name}</b>. Gere na aba <b>Criar vídeo</b> ou no app <b>Conteúdo</b> primeiro.</div>
      : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(108px,1fr))', gap: 8 }}>
          {arts.map(a => <div key={a.id} title={a.title} onClick={() => setSel(a.url)}
            style={{ cursor: 'pointer', border: '2px solid ' + (sel === a.url ? 'var(--pri)' : 'transparent'), borderRadius: 8, overflow: 'hidden', position: 'relative' }}>
            <img loading="lazy" decoding="async" src={a.url} style={{ width: '100%', height: 120, objectFit: 'cover', display: 'block' }} />
            {sel === a.url && <div style={{ position: 'absolute', top: 4, right: 4, background: 'var(--pri)', color: '#fff', borderRadius: 999, width: 20, height: 20, fontSize: 13, textAlign: 'center', lineHeight: '20px' }}>✓</div>}
          </div>)}
        </div>}
    {msg && <div className={(msg.startsWith('Erro') || msg.startsWith('Falhou')) ? 'err' : 'ok'}>{msg}</div>}
    <button className="btn pri" disabled={busy || !sel} onClick={animar}>{busy ? 'Animando…' : (sel ? 'Animar arte selecionada' : 'Escolha uma arte acima')}</button>
    {out && <video src={out} controls style={{ width: '100%', maxWidth: 300, borderRadius: 12 }} />}
  </div>;
}

function VideoEditarBruto({ company }) {
  return <div className="panel stack">
    <div className="sec"><Icon name="video" />Editar um vídeo bruto</div>
    <div className="hint">Sobe um vídeo seu (gravado no celular, sem edição) e a plataforma aplica a identidade da marca: cortes, transições, logo, legendas e CTA. <b>Em construção</b> — é a próxima função de vídeo do roadmap.</div>
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
      <button className="btn ghost" onClick={() => window.__mpOpen && window.__mpOpen('enhancer')}><Icon name="enhance" />Melhorar vídeo (upscale) — disponível agora</button>
    </div>
    <small className="hint">Enquanto a edição com marca não fica pronta, o <b>Video Enhancer</b> já melhora a qualidade/resolução de vídeos antigos ou de baixa resolução.</small>
  </div>;
}

function VideoApp() {
  const [companies, setCompanies] = React.useState([]);
  const [companyId, setCompanyId] = React.useState('');
  const [company, setCompany] = React.useState(null);
  const [tab, setTab] = React.useState('criar');
  React.useEffect(() => { window.mpApi.listCompanies().then(r => setCompanies(r || [])).catch(() => {}); }, []);
  function pick(id) { setCompanyId(id); setCompany((companies || []).find(x => x.id === id) || null); }
  const TABS = [['criar', 'Criar vídeo'], ['animar', 'Animar imagem'], ['editar', 'Editar vídeo bruto']];
  return <div className="app">
    <div className="app-head">
      <div className="tb-ic" style={{ width: 40, height: 40, borderRadius: 12 }}><Icon name="video" style={{ width: 20, height: 20 }} /></div>
      <div className="lead">
        <div className="app-title">Vídeo</div>
        <div className="app-desc">Três jeitos de fazer vídeo com a marca: criar do zero, animar uma arte ou editar um vídeo seu.</div>
      </div>
      {company && <Pill kind="cy" dot>{company.name}</Pill>}
    </div>
    <div className="panel stack">
      <Field label="Empresa">
        <select className="inp" value={companyId} onChange={e => pick(e.target.value)}>
          <option value="">— escolha a empresa —</option>
          {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </Field>
    </div>
    {!company ? <div className="panel stack"><div className="hint">Escolha a empresa acima para começar.</div></div> : <div className="stack">
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {TABS.map(([k, t]) => <button key={k} className={'btn sm' + (tab === k ? ' pri' : ' ghost')} onClick={() => setTab(k)}>{t}</button>)}
      </div>
      {tab === 'criar' && <VideoCriarStandalone key={company.id} company={company} />}
      {tab === 'animar' && <VideoAnimar key={company.id} company={company} />}
      {tab === 'editar' && <VideoEditarBruto company={company} />}
    </div>}
  </div>;
}

function TemplateVideoCreator({ company, onUseGenerative }) {
  const st = ContState.get(company.id);
  const offerRefs = Array.isArray(st.offer_refs) ? st.offer_refs : [];
  const baseSubject = (st.assuntoTema || st.assunto || (st.briefing || '').split('\n').find(Boolean) || '').trim();
  const [templates, setTemplates] = React.useState([]);
  const [templateId, setTemplateId] = React.useState('brand_pulse_15s');
  const [format, setFormat] = React.useState(st.videoTemplateFormat || 'story');
  const [duration, setDuration] = React.useState(st.videoTemplateDuration || st.videoSeconds || 12);
  const [subject, setSubject] = React.useState(baseSubject || 'Oferta da marca');
  const [eyebrow, setEyebrow] = React.useState(company.name || '');
  const [title, setTitle] = React.useState(baseSubject || '');
  const [subtitle, setSubtitle] = React.useState('');
  const [cta, setCta] = React.useState(st.cta || 'Fale com a gente');
  const [offer, setOffer] = React.useState('');
  const [quote, setQuote] = React.useState('');
  const [stat, setStat] = React.useState('');
  const [leftLabel, setLeftLabel] = React.useState('ANTES');
  const [leftText, setLeftText] = React.useState('');
  const [rightLabel, setRightLabel] = React.useState(company.name || 'MARCA');
  const [rightText, setRightText] = React.useState('');
  const [punchline, setPunchline] = React.useState('');
  const [benefits, setBenefits] = React.useState('');
  const [scenes, setScenes] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [result, setResult] = React.useState(st.templateVideoResult || null);
  const [proc, setProc] = React.useState({ open: false });

  React.useEffect(() => {
    window.mpApi.templateVideoTemplates().then(r => {
      const list = r.templates || [];
      setTemplates(list);
      setTemplateId(id => id || (list[0] && list[0].id) || 'brand_pulse_15s');
    }).catch(() => {});
  }, []);

  function persist(patch) {
    ContState.set(company.id, { videoTemplateFormat: format, videoTemplateDuration: duration, templateVideoResult: result, ...patch });
  }

  function applySuggestion(s) {
    if (!s) return;
    if (s.template_id) setTemplateId(s.template_id);
    if (s.eyebrow) setEyebrow(s.eyebrow);
    if (s.title) setTitle(s.title);
    if (s.subtitle) setSubtitle(s.subtitle);
    if (s.cta) setCta(s.cta);
    if (s.offer) setOffer(s.offer);
    if (s.quote) setQuote(s.quote);
    if (s.stat) setStat(s.stat);
    if (Array.isArray(s.benefits)) setBenefits(s.benefits.join('\n'));
    if (Array.isArray(s.scenes)) setScenes(s.scenes.join('\n'));
    if (s.left_label) setLeftLabel(s.left_label);
    if (s.left_text) setLeftText(s.left_text);
    if (s.right_label) setRightLabel(s.right_label);
    if (s.right_text) setRightText(s.right_text);
    if (s.punchline) setPunchline(s.punchline);
    if (s.duration_sec) { setDuration(Number(s.duration_sec) || duration); persist({ videoTemplateDuration: Number(s.duration_sec) || duration }); }
  }

  async function sugerir() {
    if (!subject.trim()) { setMsg('Escreva o assunto primeiro.'); return; }
    setBusy(true); setMsg('IA criando uma direcao de video controlada pela marca…');
    try {
      const r = await window.mpApi.suggestTemplateVideo({
        company_id: company.id, subject, template_id: templateId, format,
        objective: st.objetivo || 'engajar', cta: cta || st.cta || '', offer_refs: offerRefs
      });
      applySuggestion(r.suggestion);
      setMsg((r.source === 'ai_text' ? 'Sugestao criativa pronta.' : 'Sugestao base pronta.') + (r.warning ? ' Aviso: ' + r.warning : ''));
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  function payload() {
    return {
      company_id: company.id,
      template_id: templateId,
      format,
      duration_sec: Number(duration) || 12,
      eyebrow,
      title: title || subject,
      subtitle,
      cta,
      offer,
      quote,
      stat,
      benefits: benefits.split('\n').map(s => s.trim()).filter(Boolean),
      scenes: scenes.split('\n').map(s => s.trim()).filter(Boolean),
      left_label: leftLabel,
      left_text: leftText,
      right_label: rightLabel,
      right_text: rightText,
      punchline: punchline || title || subject,
      offer_refs: offerRefs,
    };
  }

  async function renderizar() {
    if (!(title || subject).trim()) { setMsg('Titulo/assunto obrigatorio.'); return; }
    setBusy(true); setResult(null); setMsg('');
    setProc({ open: true, pct: 8, detail: 'Montando video por template, sem token de imagem/video…', phase: '' });
    try {
      const started = Date.now();
      const timer = setInterval(() => {
        const pct = Math.min(94, 8 + ((Date.now() - started) / 14000) * 86);
        setProc(p => p.open && !p.phase ? { ...p, pct } : p);
      }, 500);
      const r = await window.mpApi.renderTemplateVideo(payload());
      clearInterval(timer);
      setResult(r); persist({ templateVideoResult: r });
      setProc({ open: true, pct: 100, phase: 'done', detail: 'Video pronto. Render com token zero.' });
      setMsg('Video pronto: ' + r.artifact_type.toUpperCase() + ' · token_cost=' + r.token_cost);
    } catch (e) {
      setProc({ open: true, phase: 'error', detail: e.message || String(e) });
      setMsg('Erro: ' + (e.message || e));
    } finally { setBusy(false); }
  }

  async function enviarAprovacao() {
    if (!result || !result.url) return;
    setBusy(true); setMsg('Enviando video para aprovacao…');
    try {
      const post = await window.mpApi.createPost({
        company_id: company.id,
        title: title || subject || 'Video',
        copy: subtitle || st.briefing || '',
        networks: st.networks || ['instagram'],
        media_url: result.url,
        intent: 'review',
        meta: {
          content_type: 'video',
          engine: result.engine,
          template_id: templateId,
          preview_url: result.preview_url,
          manifest_url: result.manifest_url,
          token_cost: result.token_cost,
          offer_refs: offerRefs,
        },
      });
      if (post && post.id) { addRunPosts(company.id, [post.id]); await window.mpApi.transitionPost(post.id, 'REVIEW'); }
      setMsg('Video enviado para Aprovação.');
    } catch (e) { setMsg('Erro ao enviar: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  const current = templates.find(t => t.id === templateId) || {};
  return <div className="stack">
    {proc.open && <ProcessModal open={proc.open} title="Video por template" detail={proc.detail} pct={proc.pct} phase={proc.phase} onClose={() => setProc({ open: false })} />}
    <div className="row" style={{ justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
      <div className="sec"><Icon name="video" />Video Studio Template</div>
      <button className="btn sm ghost" onClick={onUseGenerative}>Usar video IA generativo</button>
    </div>
    <div className="hint">A IA ajuda na ideia e no texto. O render respeita logo, cores, layout e CTA com custo zero de token de video.</div>
    <Field label="Template criativo">
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {templates.map(t => <button key={t.id} className={'btn sm' + (templateId === t.id ? ' pri' : ' ghost')} onClick={() => setTemplateId(t.id)} title={t.description}>{t.name}</button>)}
      </div>
      {current.description && <small className="hint">{current.description}</small>}
    </Field>
    <div className="grid2">
      <Field label="Assunto para a IA"><input className="inp" value={subject} onChange={e => setSubject(e.target.value)} placeholder="Ex.: jogar online sem lag" /></Field>
      <Field label="Formato / duração"><div className="row" style={{ gap: 6 }}>
        <select className="inp" value={format} onChange={e => { setFormat(e.target.value); persist({ videoTemplateFormat: e.target.value }); }}><option value="story">Story 9:16</option><option value="feed">Feed 4:5</option></select>
        <select className="inp" value={duration} onChange={e => { setDuration(Number(e.target.value)); persist({ videoTemplateDuration: Number(e.target.value) }); }}><option value="8">8s</option><option value="10">10s</option><option value="12">12s</option><option value="15">15s</option><option value="20">20s</option></select>
      </div></Field>
    </div>
    <button className="btn pri" disabled={busy} onClick={sugerir}>{busy ? 'Processando…' : 'IA sugerir roteiro controlado'}</button>
    <div className="grid2">
      <Field label="Selo / editoria"><input className="inp" value={eyebrow} onChange={e => setEyebrow(e.target.value)} /></Field>
      <Field label="CTA"><input className="inp" value={cta} onChange={e => setCta(e.target.value)} /></Field>
    </div>
    <Field label="Titulo"><input className="inp" value={title} onChange={e => setTitle(e.target.value)} /></Field>
    <Field label="Subtitulo"><textarea className="inp" rows={2} value={subtitle} onChange={e => setSubtitle(e.target.value)} /></Field>
    {templateId === 'offer_snap_10s' && <Field label="Oferta / beneficio destaque"><input className="inp" value={offer} onChange={e => setOffer(e.target.value)} placeholder="Ex.: planos com streaming incluso" /></Field>}
    {templateId === 'proof_wave_12s' && <div className="grid2"><Field label="Frase de prova"><textarea className="inp" rows={2} value={quote} onChange={e => setQuote(e.target.value)} /></Field><Field label="Selo / métrica"><input className="inp" value={stat} onChange={e => setStat(e.target.value)} placeholder="Ex.: mais estabilidade" /></Field></div>}
    {templateId === 'meme_vs_10s' && <div className="grid2"><Field label="Lado A"><input className="inp" value={leftLabel} onChange={e => setLeftLabel(e.target.value)} /><textarea className="inp" rows={2} value={leftText} onChange={e => setLeftText(e.target.value)} /></Field><Field label="Lado B"><input className="inp" value={rightLabel} onChange={e => setRightLabel(e.target.value)} /><textarea className="inp" rows={2} value={rightText} onChange={e => setRightText(e.target.value)} /></Field><Field label="Punchline"><input className="inp" value={punchline} onChange={e => setPunchline(e.target.value)} /></Field></div>}
    {templateId === 'benefit_stack_12s' && <Field label="Beneficios (1 por linha)"><textarea className="inp" rows={4} value={benefits} onChange={e => setBenefits(e.target.value)} /></Field>}
    {templateId === 'cinematic_story_15s' && <Field label="Cenas (1 por linha)"><textarea className="inp" rows={4} value={scenes} onChange={e => setScenes(e.target.value)} /></Field>}
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
      <button className="btn pri" disabled={busy} onClick={renderizar}>Renderizar MP4 token zero</button>
      <button className="btn" disabled={!result || busy} onClick={() => result && window.open(result.url, '_blank')}>Abrir video</button>
      <button className="btn" disabled={!result || busy} onClick={enviarAprovacao}>Enviar para Aprovação</button>
    </div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    {result && <div className="panel stack">
      <div className="sec mut">{result.artifact_type.toUpperCase()} · {result.width}×{result.height} · {result.duration_sec}s · token_cost={result.token_cost}</div>
      {result.url && result.artifact_type === 'mp4' ? <video src={result.url} controls style={{ width: '100%', maxWidth: 360, borderRadius: 10 }} /> : result.preview_url ? <img src={result.preview_url} style={{ width: '100%', maxWidth: 260, borderRadius: 10 }} /> : null}
      <small className="hint">{location.origin + result.url}</small>
    </div>}
  </div>;
}

const CONT_STEPS = [
  { k: 'cliente', ic: 'users', t: 'Marca-alvo' },
  { k: 'briefing', ic: 'sparkles', t: 'Briefing' },
  { k: 'criacao', ic: 'image', t: 'Criação' },
  { k: 'aprovacao', ic: 'shield', t: 'Aprovação' },
  { k: 'agenda', ic: 'calendar', t: 'Agendamento' },
];

const CONT_NETS = ['instagram', 'facebook'];

function ConteudoApp() {
  const initialCompanyId = (window.mpCtx && window.mpCtx.contentCompanyId) || '';
  const [i, setI] = React.useState(0);
  const [companyId, setCompanyId] = React.useState(initialCompanyId);
  const [company, setCompany] = React.useState(null);
  const [initialLoadError, setInitialLoadError] = React.useState('');
  const [pjKey, setPjKey] = React.useState(0);   // muda ao abrir/criar projeto → remonta Briefing/Criação (lê o projeto ativo)

  React.useEffect(() => {
    if (!initialCompanyId || !window.mpApi) return;
    window.mpApi.getCompany(initialCompanyId).then(c => {
      if (!c) return;
      setCompany(c); setCompanyId(initialCompanyId); ContState.novo(initialCompanyId);
      if (window.mpCtx) delete window.mpCtx.contentCompanyId;
    }).catch(e => { setCompanyId(''); setInitialLoadError(e.message || 'Não foi possível abrir a empresa selecionada.'); });
  }, []);

  const canNext = (() => {
    if (i === 0) return !!companyId && !!company;
    return true;
  })();

  function Steps() {
    const prospectMode = company && ['prospect', 'lost'].includes(company.lifecycle_stage || 'managed');
    return <div className="wiz-steps">
      {CONT_STEPS.map((s, idx) => <React.Fragment key={s.k}>
        <button className={'wstep' + (idx < i ? ' done' : idx === i ? ' on' : '')}
          onClick={() => { if (idx === 0 || companyId) setI(idx); }}>
          <span className="wd">{idx < i ? <Icon name="check" style={{ width: 12, height: 12 }} /> : idx + 1}</span>{prospectMode && s.k === 'agenda' ? 'Entrega' : s.t}
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

    {initialLoadError && <div className="err">{initialLoadError}</div>}

    <div className="panel stack" style={{ minHeight: 320 }}>
      {i === 0 && <StepCliente companyId={companyId} company={company}
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
function StepCliente({ companyId, company, onPick, onContinue }) {
  const [companies, setCompanies] = React.useState([]);
  const [q, setQ] = React.useState('');
  const [accounts, setAccounts] = React.useState([]);
  const [posts, setPosts] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [projetos, setProjetos] = React.useState([]);   // trabalhos salvos desta empresa (caixinhas p/ continuar)
  const [delPj, setDelPj] = React.useState(null);       // projeto salvo a excluir (substitui window.confirm)
  React.useEffect(() => { setProjetos(companyId ? ContState.projetos(companyId) : []); }, [companyId]);
  function continuar(pid) { ContState.abrir(companyId, pid); onContinue && onContinue(); }      // CONTINUAR projeto salvo
  function novoProjeto() { ContState.novo(companyId); onContinue && onContinue(); }              // começar LIMPO
  function excluirPj(pid) { ContState.excluir(companyId, pid); setProjetos(ContState.projetos(companyId)); setDelPj(null); }
  function continuarDb(p, urls) {   // reabre um carrossel do ACERVO (banco) como projeto → traz as artes pra Criação
    const m = p.meta || {};
    const ex = ContState.projetos(companyId).find(pj => (pj.carouselResults || []).some(v => v.post_id === p.id));
    if (ex) { continuar(ex.id); return; }
    ContState.novo(companyId);
    ContState.set(companyId, {
      carouselResults: [{ model: m.model || 'Estúdio IA', slides: (urls || []).map(u => ({ url: u })), cost: 0, post_id: p.id }],
      telas: [], assunto: p.title || '', assuntoTema: p.title || '', briefing: '',
      formato: m.content_type === 'carousel' ? 'carrossel' : (m.content_type || 'post'), copy: p.copy, hashtags: p.hashtags,
      ...(Object.prototype.hasOwnProperty.call(m, 'offer_refs') ? { offer_refs: m.offer_refs || [] } : {}),
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
  const prospectMode = company && ['prospect', 'lost'].includes(company.lifecycle_stage || 'managed');

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

  return <div className="stack">
    <FlowHead icon="users" title="Escolher a marca-alvo"
      sub="A identidade da arte é sempre desta empresa — a oferta pode vir do catálogo de outra."
      right={company ? <Pill kind="cy" dot>{company.name}</Pill> : null} />
    <div className="split">
    <div className="stack">
      <Field label="Buscar marca-alvo"><input className="inp" value={q} onChange={e => setQ(e.target.value)} placeholder="Nome do prospect, cliente ou marca interna…" /></Field>
      {loading && <div className="hint">Carregando clientes…</div>}
      <div className="stack" style={{ maxHeight: 320, overflow: 'auto' }}>
        {filtered.map(c => {
          const id = c.id || c.company_id;
          const stage = c.lifecycle_stage || 'managed';
          const stageMeta = stage === 'lost' ? ['warn', 'inativo'] : stage === 'prospect' ? ['cy', 'prospecto'] : stage === 'internal' ? ['good', 'interno'] : ['good', 'cliente'];
          return <div key={id} className={'litem' + (id === companyId ? ' on' : '')} style={{ padding: 10, cursor: 'pointer', borderColor: id === companyId ? 'var(--pri)' : undefined }} onClick={() => pick(c)}>
            <span className="li-ic"><Icon name="users" /></span>
            <div className="li-main"><b>{c.name || c.n}</b><small>{c.segment || ''}</small></div>
            <Pill kind={stageMeta[0]}>{stageMeta[1]}</Pill>
            {id === companyId && <Pill kind="good" dot>selecionado</Pill>}
          </div>;
        })}
        {!loading && !filtered.length && <div className="hint">Nenhuma marca. Cadastre o prospect ou cliente em Clientes.</div>}
      </div>
    </div>
    <div className="stack">
      <div className="sec mut">{prospectMode ? 'Modo da produção' : 'Conexões'}</div>
      {!companyId && <div className="hint">Selecione um cliente.</div>}
      {companyId && prospectMode && <div className="panel stack" style={{ borderColor: 'var(--cyan)' }}>
        <Pill kind={company.lifecycle_stage === 'lost' ? 'warn' : 'cy'} dot>{company.lifecycle_stage === 'lost' ? 'Cadastro inativo' : 'Proposta comercial'}</Pill>
        <div className="hint">Criação, download e link de apresentação liberados. Nenhum login ou publicação nas redes desta marca.</div>
      </div>}
      {companyId && !prospectMode && CONT_NETS.map(p => {
        const acc = accounts.find(a => a.platform === p);
        const ok = acc && (acc.status === 'connected' || acc.status === 'active');
        return <div key={p} className="litem" style={{ padding: 8 }}>
          <div className="li-main"><b style={{ textTransform: 'capitalize' }}>{p}</b></div>
          <Pill kind={ok ? 'good' : acc ? 'warn' : ''} dot>{acc ? (acc.status === 'inactive' ? 'inativo' : acc.status) : 'não conectado'}</Pill>
        </div>;
      })}
      {companyId && <button className="btn sm ghost" onClick={() => window.__mpOpen && window.__mpOpen('clientes')}><Icon name="pen" />Editar empresa/identidade</button>}
      {companyId && <>
        <div className="sec mut" style={{ marginTop: 8 }}>Continuar de onde parou?</div>
        <div className="hint">Marque um trabalho salvo pra continuar (briefing + artes prontos), ou comece do zero.</div>
        <div className="stack" style={{ maxHeight: 280, overflow: 'auto' }}>
          {caixas.map(c => <div key={c.id} className="litem" style={{ padding: 8, cursor: 'pointer' }} onClick={() => c.__db ? continuarDb(c._post, c._urls) : continuar(c.id)} title="Continuar este trabalho">
            {c.thumb ? <img loading="lazy" decoding="async" src={c.thumb} style={{ width: 42, height: 52, borderRadius: 6, objectFit: 'cover', flex: 'none' }} /> : <span className="li-ic"><Icon name="post" /></span>}
            <div className="li-main"><b>{c.label || 'Projeto'}</b><small>{(c.fmt || 'carrossel')} · {c.nArtes || 0} arte(s){c.__db ? ' · acervo' : ''} · {c.ts ? new Date(c.ts).toLocaleDateString() : ''}</small></div>
            {!c.__db && <button className="btn sm ghost" onClick={e => { e.stopPropagation(); setDelPj(c); }} title="Excluir"><Icon name="trash" /></button>}
          </div>)}
          {!caixas.length && <EmptyState icon="layers" title="Nenhum trabalho salvo ainda">Comece do zero e o projeto aparece aqui pra continuar depois.</EmptyState>}
        </div>
        <button className="btn sm pri" onClick={novoProjeto}><Icon name="bolt" />Começar do zero (novo)</button>
      </>}
    </div>
    {delPj && <Confirm title="Excluir este projeto salvo?"
      message={`"${delPj.label || 'Projeto'}" sai da lista de trabalhos salvos. As peças já enviadas para aprovação continuam salvas.`}
      confirmLabel="Excluir"
      onConfirm={() => excluirPj(delPj.id)} onClose={() => setDelPj(null)} />}
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
  const [catalogs, setCatalogs] = React.useState([]);
  const [catalogCompanyId, setCatalogCompanyId] = React.useState(st.offerCatalogCompanyId || ((st.offer_refs || [])[0] || {}).source_company_id || '');
  const [offerRefs, setOfferRefs] = React.useState(Array.isArray(st.offer_refs) ? st.offer_refs : []);
  const [sources, setSources] = React.useState(st.sources || {});
  const [ideasCount, setIdeasCount] = React.useState(st.ideasCount || 5);
  const [idea, setIdea] = React.useState(st.idea || '');   // ideia do operador em texto livre → vira briefing
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
  const [catalogError, setCatalogError] = React.useState('');
  const assuntoList = (((company.brand_kit || {}).assuntos) || '').split('\n').map(s => s.trim()).filter(Boolean);
  const FORMATOS = [['carrossel', 'Carrossel'], ['post', 'Post fixo'], ['story', 'Story'], ['video', 'Vídeo']];
  const fmtLabel = { carrossel: 'plano de telas', video: 'roteiro', post: 'pauta', story: 'arte de story' }[formato] || 'plano';

  React.useEffect(() => {
    let cancelled = false;
    window.mpApi.offerCatalog(company.id).then(list => {
      if (cancelled) return;
      const cats = list || [];
      setCatalogs(cats);
      setCatalogError('');
      const hasSavedRefs = Object.prototype.hasOwnProperty.call(st, 'offer_refs');
      const savedRefs = Array.isArray(st.offer_refs) ? st.offer_refs : [];
      const validRefs = savedRefs.filter(ref => {
        const cat = cats.find(c => c.company_id === ref.source_company_id);
        return !!(cat && (cat.products || []).some(p => p.id === ref.product_id));
      });
      const savedSource = (validRefs[0] || {}).source_company_id;
      const target = cats.find(c => c.company_id === company.id);
      const external = cats.find(c => c.company_id !== company.id && c.lifecycle_stage === 'internal')
        || cats.find(c => c.company_id !== company.id && /cariap/i.test(c.company_name || ''))
        || cats.find(c => c.company_id !== company.id);
      const stage = company.lifecycle_stage || 'managed';
      const automatic = ['prospect', 'lost'].includes(stage) ? (external || target) : (target || external);
      const preferred = cats.find(c => c.company_id === (savedSource || st.offerCatalogCompanyId)) || automatic || cats[0];
      const preferredId = (preferred && preferred.company_id) || '';
      setCatalogCompanyId(preferredId);
      if (!hasSavedRefs) {
        const target = cats.find(c => c.company_id === company.id);
        const legacySources = (st.sources && typeof st.sources === 'object') ? st.sources : {};
        const migrated = (target ? target.products : []).filter(p => !!legacySources[p.id])
          .map(p => ({ source_company_id: company.id, product_id: p.id }));
        const sourceMap = {}; migrated.forEach(ref => { sourceMap[ref.product_id] = true; });
        setOfferRefs(migrated); setSources(sourceMap);
        ContState.set(company.id, { offer_refs: migrated, offerCatalogCompanyId: preferredId, sources: sourceMap });
      } else {
        const sourceMap = {}; validRefs.forEach(ref => { sourceMap[ref.product_id] = true; });
        setOfferRefs(validRefs); setSources(sourceMap);
        if (validRefs.length !== savedRefs.length) {
          ContState.set(company.id, { offer_refs: validRefs, offerCatalogCompanyId: preferredId, sources: sourceMap });
        }
      }
    }).catch(e => { if (!cancelled) setCatalogError(e.message || 'Não foi possível carregar os catálogos.'); });
    return () => { cancelled = true; };
  }, [company.id]);

  function persist(patch) { ContState.set(company.id, { briefingMode: mode, briefing, objetivo, tom, cta, networks, sources, offer_refs: offerRefs, offerCatalogCompanyId: catalogCompanyId, assunto, idea, formato, intent, eventId, videoSeconds: vsec, ...patch }); }

  const activeCatalog = catalogs.find(c => c.company_id === catalogCompanyId);
  const selectedProducts = [];
  (catalogs || []).forEach(cat => (cat.products || []).forEach(product => {
    if (offerRefs.some(ref => ref.source_company_id === cat.company_id && ref.product_id === product.id)) {
      selectedProducts.push({ ...product, source_company_id: cat.company_id, source_company_name: cat.company_name });
    }
  }));

  function chooseCatalog(sourceCompanyId) {
    setCatalogCompanyId(sourceCompanyId);
    setOfferRefs([]); setSources({});
    persist({ offerCatalogCompanyId: sourceCompanyId, offer_refs: [], sources: {} });
  }

  function toggleOffer(product, checked) {
    const ref = { source_company_id: catalogCompanyId, product_id: product.id };
    const next = checked
      ? [...offerRefs.filter(x => x.product_id !== product.id || x.source_company_id !== catalogCompanyId), ref]
      : offerRefs.filter(x => x.product_id !== product.id || x.source_company_id !== catalogCompanyId);
    const nextSources = {}; next.forEach(x => { nextSources[x.product_id] = true; });
    setOfferRefs(next); setSources(nextSources);
    persist({ offer_refs: next, sources: nextSources });
  }

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
      try { g = await window.mpApi.generatePostAI({ company_id: company.id, briefing: brief, networks: [net], offer_refs: offerRefs }); }
      catch (_) { /* tenta de novo */ }
    }
    return g;
  }

  async function gerarAuto() {
    const selProds = selectedProducts;
    // A ideia escrita pelo operador vale como tema quando não há assunto escolhido.
    const seed = (assunto || '').trim() || (idea || '').trim();
    if (!selProds.length && !seed) { setMsg('Escreva a ideia, escolha um assunto ou selecione uma oferta do catálogo.'); return; }
    if (intent === 'evento' && !eventId) { setMsg('Modo "Divulgar evento" precisa de um evento cadastrado selecionado (senão a IA inventaria datas). Escolha o evento ou troque o modo.'); return; }
    setBusy(true);
    try {
      // ASSUNTO definido → PLANO COMPLETO adaptado ao OBJETIVO + FORMATO (telas/roteiro/pauta)
      if (seed) {
        setMsg(`Montando ${fmtLabel} sobre "${seed}" (objetivo: ${objetivo}, formato: ${formato})…`);
        // post/story = 1 arte RICA (capa pela máquina do carrossel, no backend); carrossel = plano completo.
        const isSingle = formato === 'post' || formato === 'story';
        const _vsecEff = (formato === 'video') ? (Number(vsec) || Number((ContState.get(company.id) || {}).videoSeconds) || 0) : 0;
        const r = await window.mpApi.generateBriefing({ company_id: company.id, theme: seed, idea: (idea || '').trim(), objetivo, formato, n_telas: isSingle ? 1 : 0, intent, event_id: eventId, apps: selProds.map(p => p.name), offer_refs: offerRefs, seconds: _vsecEff });
        const text = ((r && r.briefing) || '').trim();
        if (!text) { setMsg('Não consegui gerar agora. Tente de novo.'); return; }
        let tl = (r && r.telas) || [];
        if (isSingle && !tl.length) {   // garante 1 tela "capa" pra render mesmo se o briefing só devolveu texto
          const hook = (text.split('\n').map(s => s.trim()).find(Boolean) || seed).slice(0, 64);
          tl = [{ type: 'cover', eyebrow: (objetivo || 'Oferta'), title: hook }];
        } else if (isSingle) {
          tl = [tl[0]];   // 1 arte só
        }
        setBriefing(text); persist({ briefing: text, telas: tl, formato, assuntoTema: seed, videoStoryboard: (r && r.storyboard) || [], videoSceneSecs: (r && r.scene_seconds) || [] });
        setMsg(`Briefing (${fmtLabel}) pronto — revise e vá para Criação${formato === 'carrossel' ? ' (modo Carrossel com ' + tl.length + ' telas)' : ' (1 arte ' + (formato === 'story' ? '9:16' : '4:5') + ')'}.`);
        return;
      }
      // sem assunto → pautas pelas ofertas vinculadas
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
      const text = 'Pautas (ofertas selecionadas):\n\n' + blocks.join('\n\n');
      setBriefing(text); persist({ briefing: text });
      setMsg(`${blocks.length} pauta(s) rica(s) gerada(s). Revise e siga para Criação.`);
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  return <div className="split">
    <div className="stack">
      <FlowHead icon="sparkles" title="Briefing"
        sub={`Escreva a ideia e a IA monta o plano de conteúdo para ${company.name}.`}
        right={<Segmented value={mode} onChange={m => { setMode(m); persist({ briefingMode: m }); }}
          options={[['auto', 'Automático'], ['manual', 'Manual']]} />} />
      {mode === 'auto' && <IdeaInput value={idea} onChange={v => { setIdea(v); persist({ idea: v }); }}
        onGenerate={gerarAuto} busy={busy}
        seeds={['foco em família', 'tom leve', 'destacar o preço', 'urgência', 'prova social']} />}
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
      {mode === 'auto' && <button className="btn pri" disabled={busy} onClick={gerarAuto}>{busy ? 'Gerando…' : (assunto.trim() ? ('Gerar ' + fmtLabel + ' do assunto' + (formato === 'video' ? ' · ' + (vsec ? vsec + 's' : 'livre') : '')) : 'Gerar briefing com IA (ofertas selecionadas)')}</button>}
      {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
      {busy && !briefing
        ? <SkeletonRows rows={2} />
        : <Field label={mode === 'auto' ? 'Briefing gerado pela IA (editável)' : 'Briefing'}>
            <textarea className="inp" rows={8} value={briefing} onChange={e => { setBriefing(e.target.value); persist({ briefing: e.target.value }); }} placeholder="Ex.: fale sobre o Look Diesel, destaque conforto e estilo…" style={{ resize: 'vertical', minHeight: 160 }} />
          </Field>}
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
      <div className="panel stack" style={{ gap: 8 }}>
        <div className="sec mut">Marca-alvo + oferta</div>
        <div className="hint">A identidade da arte é sempre <b>{company.name}</b>. A oferta pode vir do catálogo de outra empresa, sem copiar produto e sem login do prospect.</div>
        {catalogError && <div className="err">{catalogError} Reabra esta etapa para tentar novamente.</div>}
        <Field label="Empresa dona do catálogo">
          <select className="inp" value={catalogCompanyId} onChange={e => chooseCatalog(e.target.value)}>
            {!catalogs.length && <option value="">Nenhum catálogo disponível</option>}
            {catalogs.map(cat => <option key={cat.company_id} value={cat.company_id}>{cat.company_name}{cat.is_target ? ' · marca-alvo' : ''}</option>)}
          </select>
        </Field>
        <div className="sec mut">Produtos/serviços desta proposta</div>
        {(activeCatalog && activeCatalog.products || []).map(p => {
          const checked = offerRefs.some(ref => ref.source_company_id === catalogCompanyId && ref.product_id === p.id);
          return <OfferPick key={p.id} product={p} checked={checked} onToggle={toggleOffer} />;
        })}
        {activeCatalog && !activeCatalog.products.length && <EmptyState icon="layers" title="Nenhuma oferta cadastrada">Cadastre produtos nesta empresa para usá-los na proposta.</EmptyState>}
        {!activeCatalog && <EmptyState icon="layers" title="Sem catálogo">Cadastre produtos em uma empresa para usá-los na proposta.</EmptyState>}
        <div className="offer-count"><Icon name="link" />{selectedProducts.length} oferta(s) vinculada(s) a este conteúdo</div>
      </div>
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
  const hasOfferRefs = Object.prototype.hasOwnProperty.call(st, 'offer_refs');
  const offerRefs = Array.isArray(st.offer_refs) ? st.offer_refs : [];
  const offerPayload = hasOfferRefs ? { offer_refs: offerRefs } : {};   // projetos antigos seguem no modo legado
  const fmt = format || 'carrossel';
  const allTelas = st.telas || [];
  const telas = fmt === 'carrossel' ? allTelas : allTelas.slice(0, 1);   // post/story = 1 arte; carrossel = N telas
  const fmtName = { carrossel: 'Carrossel', post: 'Post fixo', story: 'Story (9:16)' }[fmt] || 'Carrossel';
  const fmtGer = { carrossel: 'carrossel', post: 'post fixo', story: 'story' }[fmt] || 'arte';   // rótulo do loading/mensagens
  const unTela = (nOrArr) => { const nn = Array.isArray(nOrArr) ? nOrArr.length : nOrArr; return nn === 1 ? 'arte' : 'telas'; };
  const [imgModels, setImgModels] = React.useState([]);
  const [versions, setVersions] = React.useState(st.carouselVersionsV2 || [{ model: '' }]);  // '' = 🎨 Estúdio IA (padrão do motor); chave V2 mata o default 'editorial' antigo persistido
  const [results, setResults] = React.useState(st.carouselResults || []);   // [{model, slides, cost, post_id}] — persistido
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [proc, setProc] = React.useState({ open: false });   // modal de loading fullscreen (igual teaser)
  const [influencers, setInfluencers] = React.useState([]);
  const [useInf, setUseInf] = React.useState(st.useInfluencer || false);   // opt-in: usar influencer na capa/CTA
  const [useStudio, setUseStudio] = React.useState(st.useStudio || false);   // ESTÚDIO IA: arte inteira por referências (logo+manual+refs+KB)
  const [infId, setInfId] = React.useState(st.influencerId || '');
  const [viewer, setViewer] = React.useState(null);   // {vi, si}
  const [editAsk, setEditAsk] = React.useState(null); // {rv, vi, si} — edição com IA (substitui window.prompt)
  const [editInst, setEditInst] = React.useState('');
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

  const [modelChoice, setModelChoice] = React.useState(true);   // admin decide: usuário escolhe modelo? (image.choice.enabled)
  const [refCur, setRefCur] = React.useState('');               // modelo FIXADO do Estúdio (mostra no rótulo da opção padrão)
  React.useEffect(() => { window.mpApi.aiModels().then(r => { setImgModels(r.image || []); setModelChoice((r && r.choice_enabled) !== false); setRefCur((r && r.image_ref_current) || ''); }).catch(() => {}); }, []);
  React.useEffect(() => { window.mpApi.listInfluencers(company.id).then(l => setInfluencers((l || []).filter(i => (i.photos || []).length))).catch(() => {}); }, [company.id]);
  React.useEffect(() => { ContState.set(company.id, { useInfluencer: useInf, influencerId: infId, useStudio }); }, [useInf, infId, useStudio]);
  React.useEffect(() => { ContState.set(company.id, { carouselVersionsV2: versions }); }, [versions]);  // salva a escolha do modelo (V2)
  React.useEffect(() => {   // SANEIA escolha morta: 'editorial' (removido) ou modelo de provedor escondido no
    if (!modelChoice) {                                   // admin desligou a escolha → TUDO usa o modelo FIXADO
      setVersions(vs => vs.some(v => v.model) ? vs.map(() => ({ model: '' })) : vs);
      return;
    }
    if (!imgModels.length) return;                        // admin → volta pro Estúdio (padrão). Era o "buga e fica
    const ok = new Set(imgModels.map(m => m.id));         // naquele grátis/editorial": valor salvo fora da lista.
    setVersions(vs => vs.map(v => (v.model && !ok.has(v.model)) ? { model: '' } : v));
  }, [imgModels, modelChoice]);
  const MODEL_OPTS = [{ id: '', name: '🎨 Estúdio IA — identidade do cadastro (padrão)' }, ...imgModels];
  const PROV_LABELS = { omniroute: 'OmniRoute (grátis · assinatura)', cometapi: 'CometAPI', piapi: 'PiAPI', openrouter: 'OpenRouter', kie: 'kie.ai (créditos)' };
  const MODEL_GROUPS = (() => {
    const g = {}; imgModels.forEach(m => { const p = m.provider || 'outros'; (g[p] = g[p] || []).push(m); });
    return Object.keys(g).map(p => ({ provider: p, label: PROV_LABELS[p] || p, models: g[p] }));
  })();
  const optLabel = (m) => m.name + (m.credits ? ' · ' + m.credits + ' cr/img' + (m.credits_learned ? '' : '~') : (m.price_brl ? ' · R$ ' + Number(m.price_brl).toFixed(2) + imgPriceKind(m) : (m.free ? ' · grátis' : '')));

  function setVerModel(i, m) { setVersions(vs => vs.map((v, k) => k === i ? { model: m } : v)); }
  function addVer() { setVersions(vs => vs.length < 4 ? [...vs, { model: '' }] : vs); }
  function delVer(i) { setVersions(vs => vs.length > 1 ? vs.filter((_, k) => k !== i) : vs); }
  const totalImgs = telas.length * versions.length;


  async function gerar() {
    setBusy(true); setResults([]); setMsg('');
    const out = new Array(versions.length);
    const aiVers = versions.filter(v => v.model && v.model !== 'editorial').length;
    const estMs = useStudio
      ? Math.max(180000, telas.length * Math.ceil(versions.length / 2) * 180000)
      : Math.max(6000, telas.length * versions.length * (aiVers ? 11000 : 1200));
    const t0 = Date.now();
    setProc({ open: true, pct: 1, detail: 'Preparando a geração…', phase: '', hideEta: useStudio });
    const tick = setInterval(() => {
      const pct = Math.min(95, ((Date.now() - t0) / estMs) * 100);
      setProc(p => (p.open && p.phase !== 'done' && p.phase !== 'error') ? { ...p, pct } : p);
    }, 400);
    try {
      let nextVersion = 0;
      const generationErrors = [];
      const workers = Array.from({ length: Math.min(2, versions.length) }, async () => {
        while (true) {
          const i = nextVersion++;
          if (i >= versions.length) return;
          setProc(p => ({ ...p, detail: versions.length > 1
            ? `Gerando até 2 versões em paralelo na Kie e validando o texto…`
            : `Gerando a arte na Kie e validando o texto…` }));
          setMsg(`Renderizando versão ${i + 1}/${versions.length}…`);
          try {
            const r = await window.mpApi.renderCarousel({ company_id: company.id, telas, model: versions[i].model, template_id: templateId, use_influencer: useInf, influencer_id: infId, format: fmt, event_id: st.eventId, render_mode: useStudio ? 'reference_full' : undefined, ...offerPayload });
            out[i] = { model: r.model, slides: r.slides || [], cost: r.cost || 0, warning: r.warning || '', post_id: r.post_id, base_urls: r.base_urls || [], offer_refs: r.offer_refs || offerRefs };
            const ready = out.filter(Boolean);
            setResults(ready); ContState.set(company.id, { carouselResults: ready });
          } catch (error) {
            generationErrors.push(error);
          }
        }
      });
      await Promise.all(workers);
      if (generationErrors.length) throw generationErrors[0];
      const cost = out.reduce((a, b) => a + (b.cost || 0), 0);
      const warns = out.filter(o => o.warning);
      clearInterval(tick);
      setProc({ open: true, pct: 100, phase: 'done', detail: `${out.length} versão(ões) × ${telas.length} ${unTela(telas)} pronta(s) · Custo: R$ ${cost.toFixed(2)}` });
      setMsg((warns.length ? '⚠ ' + warns[0].warning + ' ' : '')
        + `${out.length} versão(ões) × ${telas.length} ${unTela(telas)} = ${telas.length * out.length} ${telas.length * out.length === 1 ? 'imagem' : 'imagens'}. Custo: R$ ${cost.toFixed(2)}. Clique numa imagem pra ver a instrução + modo Instagram.`);
    } catch (e) { clearInterval(tick); setProc({ open: true, phase: 'error', detail: String(e.message || e) }); setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  // Re-render GRÁTIS (cache): reusa as fotos já geradas (base_urls) e só redesenha a arte
  // (texto/logo/rodapé) — não chama a IA, custo R$ 0. Útil pra iterar diagramação sem pagar.
  // Progresso animado p/ operações que chamam a IA (regenerar) — mesma tela de loading da geração.
  function _runWithProc(estMs, detail, fn) {
    const t0 = Date.now();
    setProc({ open: true, pct: 2, detail, phase: '' });
    const tick = setInterval(() => {
      const pct = Math.min(95, ((Date.now() - t0) / estMs) * 100);
      setProc(p => (p.open && p.phase !== 'done' && p.phase !== 'error') ? { ...p, pct } : p);
    }, 400);
    return fn()
      .then((okDetail) => { clearInterval(tick); setProc({ open: true, pct: 100, phase: 'done', detail: okDetail || 'Pronto.' }); })
      .catch((e) => { clearInterval(tick); setProc({ open: true, phase: 'error', detail: String((e && e.message) || e) }); throw e; });
  }

  async function regerarArte(rv, vi) {
    if (!(rv.base_urls || []).some(Boolean)) { setMsg('Esta versão não tem fotos salvas pra reusar (gere com um modelo de IA primeiro).'); return; }
    const aiSlow = /gpt-5\.4|chatgpt/i.test(rv.model || '');
    setBusy(true); setMsg('');
    try {
      await _runWithProc(aiSlow ? 300000 : 60000, `Regerando a arte da versão ${vi + 1}${(rv.base_urls || []).some(Boolean) && !useStudio ? ' (reusando as fotos)' : ''}…`, async () => {
        const r = await window.mpApi.renderCarousel({ company_id: company.id, telas, model: rv.model, template_id: templateId, base_urls: rv.base_urls, use_influencer: useInf, influencer_id: infId, format: fmt, event_id: st.eventId, render_mode: useStudio ? 'reference_full' : undefined, ...offerPayload });
        const nv = { model: r.model, slides: r.slides || [], cost: r.cost || 0, warning: r.warning || '', post_id: r.post_id, base_urls: r.base_urls || [], offer_refs: r.offer_refs || offerRefs };
        setResults(rs => { const c = rs.slice(); c[vi] = nv; ContState.set(company.id, { carouselResults: c }); return c; });
        setMsg(`Arte da versão ${vi + 1} regerada. Custo: R$ ${(r.cost || 0).toFixed(2)}.`);
        return `Arte pronta · Custo: R$ ${(r.cost || 0).toFixed(2)}`;
      });
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  async function regerarSlide(rv, vi, si) {
    const aiSlow = /gpt-5\.4|chatgpt/i.test(rv.model || '');
    setBusy(true); setMsg('');
    try {
      await _runWithProc(aiSlow ? 300000 : 60000, `Regerando ${fmt === 'carrossel' ? 'a tela ' + (si + 1) : 'a arte'} (paga só ela)…`, async () => {
        const bases = (rv.base_urls && rv.base_urls.length ? rv.base_urls.slice() : telas.map(() => null));
        bases[si] = null;   // zera SÓ esta → regenera (paga 1 slide); as outras reusam a foto salva (grátis)
        const r = await window.mpApi.renderCarousel({ company_id: company.id, telas, model: rv.model, template_id: templateId, use_influencer: useInf, influencer_id: infId, format: fmt, event_id: st.eventId, base_urls: bases, render_mode: useStudio ? 'reference_full' : undefined, ...offerPayload });
        const nv = { model: r.model, slides: r.slides || [], cost: r.cost || 0, warning: r.warning || '', post_id: r.post_id, base_urls: r.base_urls || [], offer_refs: r.offer_refs || offerRefs };
        setResults(rs => { const c = rs.slice(); c[vi] = nv; ContState.set(company.id, { carouselResults: c }); return c; });
        setMsg(`${fmt === 'carrossel' ? 'Tela ' + (si + 1) : 'Arte'} regenerada. Custo: R$ ${(r.cost || 0).toFixed(2)}.`);
        return `Pronto · Custo: R$ ${(r.cost || 0).toFixed(2)}`;
      });
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
        const np = await window.mpApi.createPost({
          company_id: company.id, title: st.assuntoTema || 'Carrossel',
          copy: (st.briefing || '').split('\n')[0] || (telas[0] && telas[0].title) || '',
          networks: ['instagram'], media_url: urls[0], intent: 'review',
          meta: { content_type: 'carousel', carousel_urls: urls, model: rv.model, telas_count: telas.length, ...(hasOfferRefs ? { offer_refs: offerRefs } : {}) },
        });
        if (np && np.id) addRunPosts(company.id, [np.id]);
      }
      setMsg(`Versão ${vi + 1} enviada para Aprovação (carrossel ${rv.slides.length} telas). Veja na aba Aprovação.`);
    } catch (e) { setMsg('Erro ao enviar: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  if (!telas.length) {
    return <div className="stack"><div className="hint" style={{ padding: 16 }}>
      Esse conteúdo é um <b>{fmtName}</b>, mas ainda não há {fmt === 'carrossel' ? 'plano de telas' : 'briefing'}.<br />
      Volte ao <b>Briefing</b>, escolha um <b>assunto</b> + formato <b>{fmtName}</b> e gere o {fmt === 'carrossel' ? 'plano de telas' : 'briefing'}. {fmt === 'carrossel' ? 'As telas aparecem' : 'A arte aparece'} aqui pra renderizar.
    </div></div>;
  }

  return <div className="stack">
    {proc.open && <ProcessModal open={proc.open} title={'Gerando ' + fmtGer} detail={proc.detail} pct={proc.pct} phase={proc.phase} hideEta={proc.hideEta} onClose={() => setProc({ open: false })} />}
    <div className="sec mut">{fmtName} · <b>{telas.length} {telas.length === 1 ? 'arte' : 'telas'}</b> {fmt === 'carrossel' ? 'do plano' : (fmt === 'story' ? '(vertical 9:16)' : '(4:5)')} (vindas do Briefing). {hasOfferRefs ? `${offerRefs.length} oferta(s) vinculada(s) por ID` : 'Projeto legado'} — escolha o modelo.</div>
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
          {(isClientUser() || !modelChoice)
            ? <span className="mut" style={{ flex: 1 }}>IA Caripost — modelo padrão da plataforma</span>
            : <select className="inp" value={v.model} onChange={e => setVerModel(i, e.target.value)} style={{ flex: 1 }}>
              <option value="">{'🎨 Estúdio IA — ' + (refCur ? refCur.replace(':', ' · ') : 'identidade do cadastro') + ' (padrão)'}</option>
              {!imgModels.length && <option disabled>carregando modelos…</option>}
              {MODEL_GROUPS.map(grp => <optgroup key={grp.provider} label={grp.label}>
                {grp.models.map(m => <option key={m.id} value={m.id}>{optLabel(m)}</option>)}
              </optgroup>)}
            </select>}
          {versions.length > 1 && <button className="btn sm ghost" onClick={() => delVer(i)}><Icon name="x" /></button>}
        </div>)}
        {versions.length < (isClientUser() ? clientMaxVer() : 4) && <button className="btn sm ghost" onClick={addVer}>{(isClientUser() || !modelChoice) ? '+ versão' : '+ versão (outro modelo)'}</button>}
      </div>
    </Field>
    {influencers.length > 0 && <Field label="Influencer (opcional — entra só na capa e no CTA)">
      <label className="row" style={{ gap: 8, alignItems: 'center', cursor: 'pointer' }}>
        <input type="checkbox" checked={useInf} onChange={e => setUseInf(e.target.checked)} />
        <span>Usar influencer — foto real composta na <b>capa</b> e no <b>CTA</b> (custa nano-banana). Desligue p/ não ficar repetitivo.</span>
      </label>
      <label className="row" style={{ gap: 8, alignItems: 'center', cursor: 'pointer' }}>
        <input type="checkbox" checked={useStudio} onChange={e => setUseStudio(e.target.checked)} />
        <span>🎨 <b>Estúdio IA</b> — a IA arquiteta a arte inteira seguindo as <b>referências do cliente</b> (versões da logo, artes de referência, manual de marca, base de conhecimento). Sua ideia é respeitada e enriquecida.</span>
      </label>
      {useInf && <select className="inp" value={infId} onChange={e => setInfId(e.target.value)} style={{ marginTop: 6 }}>
        <option value="">Automático (1º cadastrado)</option>
        {influencers.map(i => <option key={i.id} value={i.id}>{i.name}{i.handle ? ' · @' + i.handle : ''} ({(i.photos || []).length} fotos)</option>)}
      </select>}
    </Field>}
    <button className="btn pri" disabled={busy} onClick={gerar}>{busy ? 'Renderizando…' : (fmt === 'carrossel' ? `Gerar carrossel (${totalImgs} imagens)` : `Gerar ${fmtName.toLowerCase()} (${versions.length} ${versions.length === 1 ? 'versão' : 'versões'})`)}</button>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    {results.map((rv, vi) => <div key={vi} className="panel stack">
      <FlowHead icon="image" title={`Artes geradas · versão ${vi + 1}`}
        sub={`${rv.slides.length} ${rv.slides.length === 1 ? 'tela' : 'telas'}${isClientUser() ? '' : ' · ' + rv.model}${rv.cost ? ' · R$ ' + rv.cost.toFixed(2) : (isClientUser() ? '' : ' · grátis')}`}
        right={<div className="row" style={{ gap: 6 }}>
          {(rv.base_urls || []).some(Boolean) && <button className="btn sm ghost" disabled={busy} title="Reusa as fotos já geradas e só redesenha a arte — não paga IA" onClick={() => regerarArte(rv, vi)}><Icon name="refresh" />Regerar arte (grátis)</button>}
          <button className="btn sm pri" disabled={busy} onClick={() => enviarAprovacao(rv, vi)}>Enviar para Aprovação<Icon name="arrowR" /></button>
        </div>} />
      {rv.warning && <Callout kind="warn">{rv.warning}</Callout>}
      <div className="art-grid">
        {rv.slides.map((s, si) => <ArtCard key={si} src={s.url}
          label={si === 0 ? 'Capa' : `Tela ${si + 1}`}
          sub={s.image_ok ? 'foto IA' : 'editorial (sem foto)'}
          badges={[s.image_error
            ? <Pill key="e" kind="pri" dot>falhou</Pill>
            : <Pill key="ok" kind="good" dot>pronta</Pill>]}
          onOpen={() => setViewer({ vi, si })}
          actions={<>
            <button className="ov-btn" disabled={busy} title="Regerar SÓ esta tela (paga só ela; as outras reusam a foto)"
              onClick={e => { e.stopPropagation(); regerarSlide(rv, vi, si); }}><Icon name="refresh" /></button>
            <button className="ov-btn" disabled={busy} title="Editar com IA: descreva a mudança — o resto da arte é preservado"
              onClick={e => { e.stopPropagation(); setEditInst(''); setEditAsk({ url: s.url, vi, si }); }}><Icon name="pen" /></button>
            <button className="ov-btn" disabled={busy} title="Animar imagem: vira um clipe curto com movimento sutil" onClick={async e => {
              e.stopPropagation();
              setBusy(true); setMsg('Animando (1-2 min)…');
              try { const r = await window.mpApi.animateArt(company.id, s.url);
                if (r && r.url) { setMsg('✓ Animação pronta.'); window.open(r.url, '_blank'); }
                else setMsg('Erro: ' + ((r && r.detail) || 'falhou'));
              } catch (e2) { setMsg('Erro: ' + e2.message); } finally { setBusy(false); }
            }}><Icon name="teaser" /></button>
          </>} />)}
      </div>
    </div>)}
    {viewer && (() => {
      const rv = results[viewer.vi]; const sl = rv.slides; const si = viewer.si;
      const go = d => setViewer(v => ({ vi: v.vi, si: Math.max(0, Math.min(sl.length - 1, v.si + d)) }));
      const caption = `${si + 1} / ${sl.length} · versão ${viewer.vi + 1} (${rv.model}) · ${sl[si].image_ok ? 'foto IA' : 'editorial (sem foto)'}`;
      return <Lightbox src={sl[si].url} kind="image" name={caption} onClose={() => setViewer(null)}
        actions={<>
          <button className="btn sm ghost" disabled={si === 0} onClick={() => go(-1)}>Anterior</button>
          <button className="btn sm ghost" disabled={si === sl.length - 1} onClick={() => go(1)}>Próxima<Icon name="arrowR" /></button>
          {sl[si].prompt && <span style={{ flex: 1, minWidth: 0, fontSize: 11.5, lineHeight: 1.45, color: 'rgba(255,255,255,.72)', maxHeight: '5.4em', overflowY: 'auto' }}>
            <b style={{ color: '#fff' }}>Instrução enviada ao modelo:</b> {sl[si].prompt}{sl[si].image_error ? ' — ' + sl[si].image_error : ''}
          </span>}
        </>} />;
    })()}
    {editAsk && <Modal title="Editar arte com IA" icon="pen" size="sm" busy={busy} onClose={() => setEditAsk(null)}
      sub="Descreva só o que muda — o resto da arte é preservado."
      foot={<>
        <button className="btn ghost" disabled={busy} onClick={() => setEditAsk(null)}>Cancelar</button>
        <button className="btn pri" disabled={busy || !editInst.trim()} onClick={async () => {
          const { url, vi, si } = editAsk; const inst = editInst.trim();
          setEditAsk(null); setBusy(true); setMsg('Editando com IA…');
          try { const r = await window.mpApi.editArt(company.id, url, inst);
            if (r && r.url) { setResults(rs => rs.map((v, k) => k === vi ? { ...v, slides: v.slides.map((x, j) => j === si ? { ...x, url: r.url } : x) } : v)); setMsg('✓ Arte editada.'); }
            else setMsg('Erro: ' + ((r && r.detail) || 'falhou'));
          } catch (e) { setMsg('Erro: ' + e.message); } finally { setBusy(false); }
        }}><Icon name="sparkles" />Editar arte</button>
      </>}>
      <Field label="O que mudar nesta arte?">
        <textarea className="inp" rows={3} value={editInst} autoFocus onChange={e => setEditInst(e.target.value)}
          placeholder="Ex.: trocar o fundo por um ambiente de sala de estar, manter o texto e o logo" />
      </Field>
    </Modal>}
  </div>;
}

/* ── Passo 2: Criação ── */
function StepCriacao({ company }) {
  // A tela de Criação ADAPTA ao tipo escolhido no Briefing.
  const st = ContState.get(company.id);
  const f = st.formato || 'carrossel';
  const [videoMode, setVideoMode] = React.useState(st.videoMode || 'template');
  // carrossel/post/story usam o MESMO criador moderno (modelo, versões, influencer, card de vidro) — só muda a dimensão.
  if (f === 'carrossel' || f === 'post' || f === 'story') return <CarrosselCreator company={company} format={f} />;
  if (videoMode === 'generative') return <div className="stack">
    <div className="row" style={{ justifyContent: 'flex-end' }}>
      <button className="btn sm ghost" onClick={() => { ContState.set(company.id, { videoMode: 'template' }); setVideoMode('template'); }}>Voltar para video por template</button>
    </div>
    <VideoCreator company={company} />
  </div>;   // fluxo caro/IA continua disponível
  return <TemplateVideoCreator company={company} onUseGenerative={() => { ContState.set(company.id, { videoMode: 'generative' }); setVideoMode('generative'); }} />;
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
  const [costAsk, setCostAsk] = React.useState(null);   // {total, est} — confirmação de gasto (substitui window.confirm)
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
  const modelLabel = (id) => { const m = imgModels.find(x => x.id === id); return m ? (m.name + (m.price_brl ? ' R$ ' + Number(m.price_brl).toFixed(2) + imgPriceKind(m) : '')) : id; };

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

  function pedirGerar() {
    const chosen = allApps.filter(p => sel[p.id]);
    if (!chosen.length) { setMsg('Selecione ao menos um app (ou Institucional).'); return; }
    let total = 0, est = 0;
    chosen.forEach(p => { const c = qty[p.id] || 1; total += c; for (let k = 0; k < c; k++) { const pm = (imgModels.find(m => m.id === modelFor(p.id, k)) || {}).price_brl; est += pm || 0; } });
    if (est >= 1.5) { setCostAsk({ total, est }); return; }
    gerar();
  }

  async function gerar() {
    const chosen = allApps.filter(p => sel[p.id]);
    if (!chosen.length) { setMsg('Selecione ao menos um app (ou Institucional).'); return; }
    setCostAsk(null);
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
        <button className="btn pri" disabled={busy} onClick={pedirGerar}>{busy ? 'Gerando…' : 'Gerar'}</button>
      </div>
    </div>
    {costAsk && <CostConfirm kind="money"
      title={`Gerar ${costAsk.total} artes`}
      amount={`R$ ${costAsk.est.toFixed(2)}`} unit="estimado"
      confirmLabel={`Gerar ${costAsk.total} artes`}
      lines={[
        { k: 'Telas', v: String(costAsk.total) },
        { k: 'Custo médio por arte', v: `R$ ${(costAsk.est / costAsk.total).toFixed(2)}` },
      ]}
      onConfirm={gerar} onClose={() => setCostAsk(null)} />}
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <div className="grid2">
      {drafts.map(d => <div key={d.uid} className="panel stack">
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <div className="row" style={{ gap: 6 }}>
            <Pill kind="cy" dot>{d.network}</Pill>
            {(d.label || d.product) ? <Pill kind="good">{d.label || d.product}{d.variant ? ' · v' + d.variant : ''}</Pill> : null}
            <Pill kind={d.media_type === 'video' ? 'good' : ''}>sugerido: {d.media_type === 'video' ? 'vídeo' : 'imagem'}</Pill>
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
        {d.compose_warning && <Callout kind="warn">{d.compose_warning} <button className="btn sm ghost" disabled={busy} onClick={() => regenImage(d.uid)} style={{ marginLeft: 6 }}>Tentar de novo</button></Callout>}
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
  const [linkUrl, setLinkUrl] = React.useState(st.approvalUrl || '');
  const [sending, setSending] = React.useState(false);
  const [del_, setDel] = React.useState(null);   // post a excluir (substitui window.confirm)

  const load = React.useCallback(() => {
    window.mpApi.listPosts().then(r => setPosts((r.posts || []).filter(p => p.company_id === company.id))).catch(() => {});
  }, [company.id]);
  React.useEffect(() => { load(); }, [load]);

  async function sendToClient() {
    setSending(true); setMsg('Criando as peças e gerando o link…');
    try {
      // 1) transforma as peças geradas (rascunho local) em posts REVIEW (com a imagem)
      const drafts = (ContState.get(company.id).drafts) || [];
      const _nids = [];
      for (const d of drafts) {
        const np = await window.mpApi.createPost({ company_id: company.id, title: d.title, copy: d.copy, hashtags: d.hashtags, networks: [d.network], media_url: d.media_url || null, intent: 'review',
          meta: { product: d.product, visual_prompt: d.visual_prompt, headline: d.headline, subheadline: d.subheadline, benefits: d.benefits, cta: d.cta, model: d.model } });
        if (np && np.id) _nids.push(np.id);
      }
      addRunPosts(company.id, _nids);
      if (drafts.length) ContState.set(company.id, { drafts: [] });
      // 2) 1 link com as peças em revisão DESTE run (não arrasta histórico antigo pro cliente)
      const all = await window.mpApi.listPosts();
      const _rl = runIdSet();
      const reviewIds = (all.posts || []).filter(p => p.company_id === company.id && p.status === 'REVIEW' && _rl.has(p.id)).map(p => p.id);
      if (!reviewIds.length) { setMsg('Nenhuma peça gerada para enviar. Gere na Criação.'); setSending(false); return; }
      const r = await window.mpApi.createApprovalLink({ company_id: company.id, post_ids: reviewIds, stage: 'client' });
      const approvalUrl = r.url || '';
      setLinkUrl(approvalUrl);
      ContState.set(company.id, { approvalUrl });
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
      const _nids = [];
      for (const d of drafts) {
        const np = await window.mpApi.createPost({ company_id: company.id, title: d.title, copy: d.copy, hashtags: d.hashtags, networks: [d.network], media_url: d.media_url || null, intent: 'review' });
        if (np && np.id) _nids.push(np.id);
      }
      addRunPosts(company.id, _nids);
      ContState.set(company.id, { drafts: [] });
      setMsg('Enviado para aprovação.'); load();
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }
  async function transition(id, to) { try { await window.mpApi.transitionPost(id, to); load(); } catch (e) { setMsg('Erro: ' + e.message); } }
  async function del(id) { try { await window.mpApi.deletePost(id); setDel(null); load(); } catch (e) { setMsg('Erro: ' + e.message); } }

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
      const _nids = [];
      for (const d of drafts) {
        const np = await window.mpApi.createPost({ company_id: company.id, title: d.title, copy: d.copy, hashtags: d.hashtags, networks: [d.network], media_url: d.media_url || null, intent: 'review' });
        if (np && np.id) _nids.push(np.id);
      }
      addRunPosts(company.id, _nids);
      if (drafts.length) ContState.set(company.id, { drafts: [] });
      const r = await window.mpApi.listPosts();
      const _rl = runIdSet();
      const pend = (r.posts || []).filter(p => p.company_id === company.id && (p.status === 'REVIEW' || p.status === 'DRAFT') && _rl.has(p.id));
      for (const p of pend) {
        if (p.status === 'DRAFT') { try { await window.mpApi.transitionPost(p.id, 'REVIEW'); } catch (_) {} }
        try { await window.mpApi.transitionPost(p.id, 'APPROVED'); } catch (_) {}
      }
      setMsg(`${pend.length} peça(s) aprovada(s). Vá para Agendamento e publique.`); load();
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }

  // RUN ATUAL: mostra SÓ as peças produzidas neste projeto (artes geradas + rascunhos enviados nesta
  // sessão). Histórico antigo aprovado/reprovado não polui a tela — toggle mostra tudo se precisar.
  function runIdSet() {
    const st0 = ContState.get(company.id) || {};
    return new Set([...((st0.carouselResults || []).map(v => v.post_id)), ...((st0.runPostIds) || [])].filter(Boolean));
  }
  const [showAll, setShowAll] = React.useState(false);
  const _run = runIdSet();
  const _seen = new Set();
  const uniq = posts.filter(p => !_seen.has(p.id) && (_seen.add(p.id) || true));   // cada post aparece 1x
  const scoped = showAll ? uniq : uniq.filter(p => _run.has(p.id));
  const review = scoped.filter(p => p.status === 'REVIEW' || p.status === 'DRAFT');
  const approved = scoped.filter(p => p.status === 'APPROVED' || p.status === 'SCHEDULED');

  return <div className="stack">
    <FlowHead icon="shield" title="Fila de aprovação"
      sub={`${review.length} ${review.length === 1 ? 'peça aguardando decisão' : 'peças aguardando decisão'} · ${approved.length} aprovada(s)`}
      right={<Segmented value={showAll ? 'all' : 'run'} onChange={v => setShowAll(v === 'all')}
        options={[['run', 'Só esta produção'], ['all', 'Histórico completo']]} />} />
    <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <button className="btn pri" disabled={busy} onClick={enviarTodos}><Icon name="send" />Enviar peças p/ aprovação</button>
      <button className="btn" disabled={busy} onClick={aprovarTudo}><Icon name="check" />Aprovar tudo (teste)</button>
      <button className="btn sm ghost" onClick={load}><Icon name="refs" />Atualizar</button>
    </div>
    <div className="hint">{showAll ? 'Mostrando TODO o histórico da empresa.' : 'Mostrando só as peças desta produção (run atual).'} Modo teste: "Aprovar tudo" cria as peças e marca como aprovado direto, sem mandar pro cliente.</div>
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
        <button className="btn sm ghost" onClick={async () => { const ok = await copyContentText(linkUrl); setMsg(ok ? 'Link copiado.' : 'Não foi possível copiar o link.'); }}><Icon name="copy" />Copiar</button>
        <a className="btn sm ghost" href={linkUrl} target="_blank" rel="noopener noreferrer"><Icon name="globe" />Abrir</a>
      </div>}
      <div className="hint">Configure WhatsApp (Evolution) e SMTP no app <b>Notificações</b>.</div>
    </div>
    <div className="sec mut">Aguardando aprovação ({review.length})</div>
    {review.map(p => <ReviewCard key={p.id} post={p} busy={busy}
      onApprove={approveOne} onRegen={regenWithFeedback}
      onDelete={x => setDel(x)} onOpen={setPreview} />)}
    {!review.length && <EmptyState icon="check" title="Nada aguardando">Gere peças na Criação e envie para aprovação.</EmptyState>}
    <div className="sec mut">Aprovados ({approved.length})</div>
    {approved.map(p => <div key={p.id} className="litem" style={{ padding: 8, gap: 8, cursor: 'pointer' }} onClick={() => setPreview(p)}>
      {p.media_url && <img loading="lazy" decoding="async" src={p.media_url} style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 6 }} />}
      <div className="li-main"><b>{p.title || 'Post'}</b><small>{p.status === 'SCHEDULED' ? 'agendado' : (p.status === 'PUBLISHED' ? 'publicado' : 'aprovado')}{p.reviewed_at ? ' · cliente em ' + new Date(p.reviewed_at).toLocaleString('pt-BR') : ''}</small></div>
      <button className="btn sm ghost" onClick={e => { e.stopPropagation(); setDel(p); }}><Icon name="trash" /></button>
    </div>)}

    {del_ && <Confirm title="Excluir esta peça?"
      message="A peça sai desta produção. As já aprovadas continuam salvas."
      confirmLabel="Excluir"
      onConfirm={() => del(del_.id)} onClose={() => setDel(null)} />}

    {preview && <Modal title={preview.title || 'Post'} icon="eye" size="sm" onClose={() => setPreview(null)}>
      <div className="stack">
        {preview.media_url && <img loading="lazy" decoding="async" src={preview.media_url} style={{ width: '100%', borderRadius: 8, border: '1px solid var(--line)' }} />}
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <Pill kind={preview.status === 'APPROVED' ? 'good' : 'cy'} dot>{preview.status}</Pill>
          {preview.review_decision && <Pill kind={preview.review_decision === 'rejected' ? 'pri' : ''}>{preview.review_decision === 'approved' ? 'cliente: 100%' : preview.review_decision === 'changes' ? 'cliente: ressalvas' : 'cliente: reprovou'}</Pill>}
          {(preview.networks || []).map(n => <Pill key={n} kind="cy">{n}</Pill>)}
        </div>
        {preview.review_comment && <Callout kind="warn">Devolutiva do cliente: {preview.review_comment}</Callout>}
        <div className="hint" style={{ whiteSpace: 'pre-wrap' }}>{preview.copy}</div>
        {preview.hashtags && preview.hashtags.length ? <div className="hint" style={{ color: 'var(--pri2)' }}>{(preview.hashtags || []).join(' ')}</div> : null}
      </div>
    </Modal>}
  </div>;
}

/* ── Passo 4: Agendamento ── */
function StepAgenda({ company }) {
  const publishEnabled = !['prospect', 'lost'].includes(company.lifecycle_stage || 'managed');
  const deliveryState = ContState.get(company.id) || {};
  const [posts, setPosts] = React.useState([]);
  const [accounts, setAccounts] = React.useState([]);
  const [when, setWhen] = React.useState({});
  const [busy, setBusy] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [del_, setDel] = React.useState(null);        // post a excluir (substitui window.confirm)
  const [storyOn, setStoryOn] = React.useState({});   // por post: publicar a CAPA como Story junto do feed
  const [collabs, setCollabs] = React.useState({});   // por post: lista de @ colaboradores (collab) — editável
  const [collabIn, setCollabIn] = React.useState({});  // input de @ por post
  const [influencers, setInfluencers] = React.useState([]);   // cadastrados (pra adicionar rápido)
  const [orgs, setOrgs] = React.useState([]);                 // empresas de evento (pra marcar o @ do evento)
  const [infcos, setInfcos] = React.useState([]);             // empresas influencer (ex.: loucosdatelecom) — @ marcável
  React.useEffect(() => { if (publishEnabled) window.mpApi.listInfluencers(company.id).then(l => setInfluencers(l || [])).catch(() => {}); }, [company.id, publishEnabled]);
  React.useEffect(() => { if (publishEnabled) window.mpApi.listOrganizers(company.id).then(l => setOrgs(l || [])).catch(() => {}); }, [company.id, publishEnabled]);
  React.useEffect(() => { if (publishEnabled) window.mpApi.listInfCompanies(company.id).then(l => setInfcos(l || [])).catch(() => {}); }, [company.id, publishEnabled]);
  function curCollabs(p) { return collabs[p.id] || []; }   // VAZIO por padrão — collab é opção MANUAL por post (nunca automático)
  function addCollab(p, h) { h = (h || '').trim().replace(/^@/, ''); if (!h) return; const cur = curCollabs(p); if (cur.includes(h) || cur.length >= 3) return; setCollabs(s => ({ ...s, [p.id]: [...cur, h] })); setCollabIn(s => ({ ...s, [p.id]: '' })); }
  function rmCollab(p, h) { setCollabs(s => ({ ...s, [p.id]: curCollabs(p).filter(x => x !== h) })); }

  const load = React.useCallback(() => {
    window.mpApi.listPosts().then(r => setPosts((r.posts || []).filter(p => p.company_id === company.id && ['REVIEW', 'DRAFT', 'APPROVED', 'SCHEDULED'].includes(p.status)))).catch(() => {});
    if (publishEnabled) window.mpApi.socialAccounts(company.id).then(a => setAccounts(a || [])).catch(() => {});
  }, [company.id, publishEnabled]);
  React.useEffect(() => { load(); }, [load]);

  if (!publishEnabled) {
    const approvalUrl = deliveryState.approvalUrl || '';
    const runIds = new Set([
      ...((deliveryState.carouselResults || []).map(v => v && v.post_id)),
      ...(deliveryState.runPostIds || []),
    ].filter(Boolean));
    const scopedPosts = runIds.size ? posts.filter(p => runIds.has(p.id)) : posts;
    const pieces = [];
    const seenUrls = new Set();
    const addPiece = (url, label, id, part) => {
      if (!url || seenUrls.has(url)) return;
      seenUrls.add(url);
      pieces.push({ url, label: label || 'Peça', id: id || url, part: part || 0 });
    };
    scopedPosts.forEach(p => {
      const urls = (p.meta && Array.isArray(p.meta.carousel_urls) && p.meta.carousel_urls.length) ? p.meta.carousel_urls : [p.media_url];
      urls.forEach((url, index) => addPiece(url, p.title || 'Peça', p.id, urls.length > 1 ? index + 1 : 0));
    });
    (deliveryState.drafts || []).forEach(d => addPiece(d.media_url, d.title || d.label || d.product || 'Peça', d.uid));

    return <div className="stack">
      <FlowHead icon="calendar" title="Agendar publicação"
        sub={`${posts.length} ${posts.length === 1 ? 'peça aprovada pronta para publicar' : 'peças aprovadas prontas para publicar'}`} />
      <div className="panel stack" style={{ borderColor: 'var(--cyan)' }}>
        <div className="sec cy"><Icon name="send" />Proposta pronta para entrega</div>
        <div className="hint">Baixe as peças ou compartilhe o link de aprovação. Nenhuma rede social desta marca será conectada ou publicada.</div>
        {approvalUrl ? <div className="stack" style={{ gap: 8 }}>
          <b>Link de aprovação</b>
          <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input className="inp" readOnly value={approvalUrl} onFocus={e => e.target.select()} style={{ flex: 1, minWidth: 220 }} />
            <button className="btn sm ghost" onClick={async () => { const ok = await copyContentText(approvalUrl); setMsg(ok ? 'Link copiado.' : 'Não foi possível copiar o link.'); }}><Icon name="copy" />Copiar</button>
            <a className="btn sm pri" href={approvalUrl} target="_blank" rel="noopener noreferrer"><Icon name="globe" />Abrir</a>
          </div>
        </div> : <div className="hint">O link ainda não foi criado. Volte à etapa <b>Aprovação</b> e use “Gerar link + notificar”.</div>}
        {msg && <div className={msg.startsWith('Não') ? 'err' : 'ok'}>{msg}</div>}
      </div>

      <div className="sec mut">Peças para entrega ({pieces.length})</div>
      {pieces.map(piece => <div key={piece.id + ':' + piece.part + ':' + piece.url} className="litem" style={{ padding: 10, gap: 10 }}>
        <div className="li-main"><b>{piece.label}{piece.part ? ` · tela ${piece.part}` : ''}</b><small>Arquivo pronto para apresentação</small></div>
        <a className="btn sm ghost" href={piece.url} target="_blank" rel="noopener noreferrer"><Icon name="globe" />Abrir</a>
        <a className="btn sm" href={piece.url} download><Icon name="download" />Baixar</a>
      </div>)}
      {!pieces.length && <div className="hint">Nenhuma mídia pronta neste trabalho. Volte à Criação para gerar as peças.</div>}
      <button className="btn ghost" onClick={() => window.__mpOpen && window.__mpOpen('clientes')}><Icon name="building" />Abrir cadastro da marca</button>
    </div>;
  }

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

  async function del(id) { try { await window.mpApi.deletePost(id); setDel(null); load(); } catch (e) { setMsg('Erro: ' + e.message); } }

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
      const created = await window.mpApi.socialCreatePost({
        brandId: company.id, sourcePostId: p.id, channels,
        assetUrls,
        contentType: isCarousel ? 'carousel' : (meta.content_type === 'story' ? 'story' : contentType(p)), scheduledAt: scheduledAt || null,
        collaborators: curCollabs(p),               // COLLAB: lista editável (influencer + quem você adicionar)
      });
      // "Publicar agora" roda em segundo plano no servidor: espera o resultado REAL antes de marcar publicado.
      const sid = created && created.post && created.post.id;
      if (!scheduledAt && sid) {
        let sp = null;
        for (let i = 0; i < 60; i++) {   // até ~4 min
          await new Promise(r => setTimeout(r, 4000));
          try { sp = (await window.mpApi.socialPostStatus(sid)).post; } catch (_) { continue; }
          if (sp && ['published', 'failed', 'partial_failed', 'cancelled'].includes(sp.status)) break;
        }
        if (!sp || sp.status !== 'published') {
          const errs = ((sp && sp.channels) || []).filter(c => c.error_message).map(c => c.platform + ': ' + c.error_message);
          const expired = errs.some(m => /expired|expirad|revogad|access token/i.test(m));
          throw new Error((expired ? 'A conexão com a rede expirou — reconecte o Instagram/Facebook no cadastro do cliente. ' : 'O post NÃO foi publicado. ')
            + (errs.join(' · ') || ('status: ' + ((sp && sp.status) || 'sem resposta'))));
        }
      }
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
        <button className="btn sm ghost" disabled={busy === p.id} onClick={() => setDel(p)}><Icon name="trash" />Excluir</button>
      </div>
    </div>)}
    {!posts.length && <EmptyState icon="calendar" title="Nenhum post aprovado">Aprove as peças na etapa anterior para agendar aqui.</EmptyState>}
    {del_ && <Confirm title="Excluir esta peça?"
      message="A peça sai da agenda. As já publicadas continuam no histórico."
      confirmLabel="Excluir"
      onConfirm={() => del(del_.id)} onClose={() => setDel(null)} />}
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
    {sel && <Modal title={sel.title || 'Peça'} icon="image" size="sm" onClose={() => setSel(null)}>
      <div className="stack">
        <img loading="lazy" decoding="async" src={sel.media_url} style={{ width: '100%', borderRadius: 8, border: '1px solid var(--line)' }} />
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <Pill kind={tone(SL[sel.status])} dot>{SL[sel.status] || sel.status}</Pill>
          {(sel.networks || []).map(n => <Pill key={n} kind="cy">{n}</Pill>)}
          {cname(sel.company_id) && <Pill>{cname(sel.company_id)}</Pill>}
          {dt(sel) && <Pill>{dt(sel)}</Pill>}
        </div>
        <div className="hint" style={{ whiteSpace: 'pre-wrap' }}>{sel.copy}</div>
        {sel.hashtags && sel.hashtags.length ? <div className="hint" style={{ color: 'var(--pri2)' }}>{(sel.hashtags || []).join(' ')}</div> : null}
      </div>
    </Modal>}
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

Object.assign(window, { ConteudoApp, NotifConfigApp, PainelApp, AcervoApp, ContState, VideoApp });
