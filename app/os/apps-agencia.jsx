/* Caripost OS — Agência automática multi-cliente: calendário do mês → ideias → artes → agendamento (piloto automático) */

const AG_FMT = { post: ['Post', 'cy'], carrossel: ['Carrossel', 'violet'], reels: ['Reels', 'warn'] };
const AG_STAGE = {
  idea: ['Ideia para aprovar', 'warn'], idea_ok: ['Ideia aprovada', 'good'], idea_rejected: ['Ideia reprovada', ''],
  art_queued: ['Na fila da arte', 'cy'], producing: ['Gerando arte…', 'cy'], art: ['Arte para aprovar', 'warn'],
  art_rejected: ['Arte reprovada', ''], art_ok: ['Arte aprovada', 'good'], scheduled: ['Agendada', 'good'],
  published: ['Publicada', 'good'], failed: ['Falhou ao publicar', 'danger'], skipped: ['Pulada (sem aprovação)', ''],
};
const AG_WD = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
const AG_MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
const AG_WORKING = ['art_queued', 'producing'];

function agMonthLabel(m) {
  if (!m) return '';
  const [y, mm] = m.split('-').map(Number);
  return AG_MESES[mm - 1] + ' de ' + y;
}
function agSlotLabel(s) {
  const d = new Date(s.slice(0, 10) + 'T12:00:00');
  return AG_WD[d.getDay()] + ', ' + s.slice(8, 10) + '/' + s.slice(5, 7) + ' · ' + s.slice(11, 16);
}

/* ── Visão de mês (Marco C) ── */
function AgMonthGrid({ month, items, dates, onPick }) {
  const [y, m] = month.split('-').map(Number);
  const first = new Date(y, m - 1, 1).getDay();
  const ndays = new Date(y, m, 0).getDate();
  const cells = [];
  for (let i = 0; i < first; i++) cells.push(null);
  for (let d = 1; d <= ndays; d++) cells.push(d);
  while (cells.length % 7) cells.push(null);
  const key = d => month + '-' + String(d).padStart(2, '0');
  const byDay = {};
  items.forEach(it => { (byDay[it.slot_at.slice(0, 10)] = byDay[it.slot_at.slice(0, 10)] || []).push(it); });
  const dateNames = {};
  (dates || []).forEach(d => { (dateNames[d.date] = dateNames[d.date] || []).push(d.nome); });
  return <div className="panel" style={{ padding: 10 }}>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))', gap: 6 }}>
      {AG_WD.map(w => <div key={w} className="sec mut" style={{ textAlign: 'center', margin: 0 }}>{w}</div>)}
      {cells.map((d, i) => {
        if (!d) return <div key={'e' + i} />;
        const its = byDay[key(d)] || [];
        const dn = dateNames[key(d)];
        return <div key={d} style={{ minHeight: 96, border: '1px solid var(--line, rgba(0,0,0,.08))', borderRadius: 10, padding: 6, background: dn ? 'rgba(124,58,237,.05)' : 'transparent' }}>
          <div style={{ fontSize: 12, fontWeight: 700, opacity: .7 }}>{d}</div>
          {dn && <div style={{ fontSize: 10.5, color: 'var(--violet, #7c3aed)', lineHeight: 1.2, marginBottom: 3 }}>{dn.join(' · ')}</div>}
          {its.map(it => {
            const [fl, fk] = AG_FMT[it.format] || [it.format, ''];
            const [sl] = AG_STAGE[it.stage] || [it.stage];
            const thumb = ((it.meta || {}).slides || [])[0];
            return <button key={it.id} onClick={() => onPick(it)} title={sl + ' — ' + (it.title || '')}
              style={{ display: 'flex', gap: 5, alignItems: 'center', width: '100%', textAlign: 'left', border: 0, background: 'rgba(0,0,0,.035)', borderRadius: 7, padding: '3px 5px', marginTop: 3, cursor: 'pointer', opacity: ['idea_rejected', 'skipped'].includes(it.stage) ? .45 : 1 }}>
              {thumb ? <img src={thumb} alt="" style={{ width: 22, height: 28, objectFit: 'cover', borderRadius: 3, flex: 'none' }} />
                : <span style={{ width: 7, height: 7, borderRadius: 7, flex: 'none', background: fk === 'violet' ? '#7c3aed' : fk === 'warn' ? '#f59e0b' : '#06b6d4' }} />}
              <span style={{ fontSize: 10.5, lineHeight: 1.2, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                <b>{fl}</b> · {it.title || '—'}
              </span>
            </button>;
          })}
        </div>;
      })}
    </div>
  </div>;
}

/* ── Configuração da agência por cliente (Marco D + multi-cliente) ── */
function AgConfigModal({ cid, name, onClose }) {
  const [cfg, setCfg] = React.useState(null);
  const [ov, setOv] = React.useState({});
  const [busy, setBusy] = React.useState('');
  const [dna, setDna] = React.useState(null);
  const [dnaText, setDnaText] = React.useState('');
  React.useEffect(() => { window.mpApi.agencyConfig(cid).then(r => { setCfg(r.config); setOv(r.override || {}); }).catch(e => mpToast('Erro: ' + e.message, 'err')); }, [cid]);
  React.useEffect(() => { window.mpApi.visualDna(cid).then(r => { setDna(r); setDnaText((r.dna || {}).text || ''); }).catch(() => {}); }, [cid]);
  async function analisarDna() {
    setBusy('dna');
    try { const r = await window.mpApi.visualDnaAnalyze(cid); setDna(d => ({ ...(d || {}), dna: r.dna })); setDnaText(r.dna.text || ''); mpToast('DNA visual atualizado.'); }
    catch (e) { mpToast('Erro: ' + e.message, 'err'); }
    finally { setBusy(''); }
  }
  const set = (k, v) => setCfg(c => ({ ...c, [k]: v }));
  const mix = (cfg && cfg.mix) || {};
  const pills = (cfg && cfg.pillars) || [];
  const setPill = (i, k, v) => set('pillars', pills.map((p, j) => j === i ? { ...p, [k]: k === 'weight' ? Number(v) || 0 : v } : p));
  const wd = new Set((cfg && cfg.weekdays) || [0, 1, 2, 3, 4, 5]);
  async function sugerir() {
    setBusy('sug');
    try {
      const r = await window.mpApi.agencySuggestConfig(cid);
      setCfg(c => ({ ...c, ...r.suggestion }));
      mpToast('Sugestão aplicada — revise e salve.');
    } catch (e) { mpToast('Erro: ' + e.message, 'err'); }
    finally { setBusy(''); }
  }
  async function salvar() {
    setBusy('save');
    try {
      const keys = ['enabled', 'generate_day', 'notify_whatsapp', 'mix', 'time', 'weekdays', 'pillars', 'cta', 'whatsapp', 'hashtags_base', 'style', 'art_mode'];
      const next = { ...ov };
      keys.forEach(k => { next[k] = cfg[k]; });
      next.enabled = !!cfg.enabled; next.generate_day = Number(cfg.generate_day) || 20;
      await window.mpApi.agencySaveConfig(cid, next);
      if (dna && dnaText !== ((dna.dna || {}).text || '')) await window.mpApi.visualDnaSave(cid, dnaText);
      mpToast('Configuração salva.'); onClose(true);
    } catch (e) { mpToast('Erro: ' + e.message, 'err'); }
    finally { setBusy(''); }
  }
  const total = pills.reduce((a, p) => a + (Number(p.weight) || 0), 0);
  return <Modal icon="settings" title={'Agência — ' + (name || 'cliente')} onClose={() => onClose(false)} busy={!!busy}
    sub="Linha editorial, volume e piloto automático deste cliente. Nada é publicado sem aprovação."
    foot={<><button className="btn ghost" disabled={busy === 'sug' || !cfg} onClick={sugerir}><Icon name="sparkles" />{busy === 'sug' ? 'Pensando…' : 'Sugerir com IA'}</button>
      <span style={{ flex: 1 }} /><button className="btn ghost" onClick={() => onClose(false)}>Cancelar</button>
      <button className="btn pri" disabled={!cfg || !!busy} onClick={salvar}>Salvar</button></>}>
    {!cfg ? <SkeletonRows rows={5} /> : <div className="stack">
      <div className="sec">Piloto automático</div>
      <div className="rowx" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <Segmented value={cfg.enabled ? 'on' : 'off'} onChange={v => set('enabled', v === 'on')} options={[['on', 'Ligado'], ['off', 'Desligado']]} />
        <Field label="Gera o mês seguinte no dia"><input className="inp" type="number" min="1" max="28" style={{ width: 90 }} value={cfg.generate_day || 20} onChange={e => set('generate_day', e.target.value)} /></Field>
        <Field label="WhatsApp para avisos"><input className="inp" placeholder="5511999998888" value={cfg.notify_whatsapp || ''} onChange={e => set('notify_whatsapp', e.target.value)} /></Field>
      </div>
      <div className="sec">DNA visual do cliente</div>
      <div className="hint">A personalidade das artes que o cliente já publica (tipografia, posicionamento, elementos, fotografia). O Estúdio IA segue isto para a peça parecer feita pelo designer dele, não por IA.
        {dna ? ' ' + (dna.n_refs || 0) + ' arte(s) de referência no cadastro.' : ''} {dna && !dna.n_refs ? 'Suba artes do Instagram dele em Clientes → Referências para um DNA fiel.' : ''}</div>
      <textarea className="inp" rows={5} value={dnaText} onChange={e => setDnaText(e.target.value)} placeholder="Ainda sem DNA — clique em Analisar artes de referência." />
      <button className="btn sm ghost" style={{ alignSelf: 'flex-start' }} disabled={busy === 'dna'} onClick={analisarDna}><Icon name="sparkles" />{busy === 'dna' ? 'Analisando… (~1 min)' : 'Analisar artes de referência'}</button>
      <div className="sec">Estilo das artes</div>
      <Segmented value={cfg.art_mode || 'equilibrado'} onChange={v => set('art_mode', v)} options={[['impacto', 'IA pura'], ['equilibrado', 'Equilibrado'], ['limpo', 'Limpo'], ['layered', 'Camadas (Canva)']]} />
      <div className="sec">Volume e horário</div>
      <div className="rowx" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        {[['post', 'Posts'], ['carrossel', 'Carrosséis'], ['reels', 'Reels']].map(([k, l]) =>
          <Field key={k} label={l + '/mês'}><input className="inp" type="number" min="0" max="40" style={{ width: 90 }} value={mix[k] ?? 0} onChange={e => set('mix', { ...mix, [k]: Number(e.target.value) || 0 })} /></Field>)}
        <Field label="Horário"><input className="inp" type="time" value={cfg.time || '18:00'} onChange={e => set('time', e.target.value)} /></Field>
      </div>
      <div className="rowx" style={{ gap: 6, flexWrap: 'wrap' }}>
        {['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'].map((d, i) =>
          <button key={d} className={'btn sm ' + (wd.has(i) ? 'pri' : 'ghost')} onClick={() => { const n = new Set(wd); n.has(i) ? n.delete(i) : n.add(i); set('weekdays', [...n].sort()); }}>{d}</button>)}
      </div>
      <div className="sec">Pilares de conteúdo <span className="mut">(soma {total}%)</span></div>
      {pills.map((p, i) => <div key={i} className="rowx" style={{ gap: 6, alignItems: 'flex-start' }}>
        <input className="inp" style={{ width: 190 }} value={p.name || ''} onChange={e => setPill(i, 'name', e.target.value)} placeholder="Pilar" />
        <input className="inp" type="number" style={{ width: 70 }} value={p.weight || 0} onChange={e => setPill(i, 'weight', e.target.value)} />
        <textarea className="inp" rows={2} style={{ flex: 1 }} value={p.desc || ''} onChange={e => setPill(i, 'desc', e.target.value)} placeholder="O que entra neste pilar" />
        <button className="btn sm ghost" onClick={() => set('pillars', pills.filter((_, j) => j !== i))}><Icon name="x" /></button>
      </div>)}
      <button className="btn sm ghost" style={{ alignSelf: 'flex-start' }} onClick={() => set('pillars', [...pills, { name: '', weight: 10, desc: '' }])}><Icon name="plus" />Pilar</button>
      <div className="sec">Voz das legendas</div>
      <div className="rowx" style={{ gap: 10, flexWrap: 'wrap' }}>
        <Field label="CTA padrão"><input className="inp" style={{ minWidth: 280 }} value={cfg.cta || ''} onChange={e => set('cta', e.target.value)} /></Field>
        <Field label="WhatsApp comercial (vai na legenda)"><input className="inp" value={cfg.whatsapp || ''} onChange={e => set('whatsapp', e.target.value)} /></Field>
      </div>
      <Field label="Hashtags-base"><input className="inp" value={(cfg.hashtags_base || []).join(' ')} onChange={e => set('hashtags_base', e.target.value.split(/\s+/).filter(Boolean))} /></Field>
      <Field label="Estilo / guia de legenda"><textarea className="inp" rows={4} value={cfg.style || ''} onChange={e => set('style', e.target.value)} /></Field>
    </div>}
  </Modal>;
}

/* ── Painel de todos os clientes ── */
function AgOverview({ clients, cid, onPick }) {
  if (!clients.length) return null;
  const n = (c, ks) => ks.reduce((a, k) => a + ((c.counts || {})[k] || 0), 0);
  return <div className="panel stack">
    <div className="sec" style={{ margin: 0 }}><Icon name="building" />Clientes da agência</div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))', gap: 8 }}>
      {clients.map(c => <button key={c.company_id} onClick={() => onPick(c.company_id)} className="btn ghost"
        style={{ display: 'block', textAlign: 'left', padding: 10, height: 'auto', border: c.company_id === cid ? '2px solid var(--pri)' : undefined }}>
        <div style={{ fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.name}</div>
        <div className="mut" style={{ fontSize: 11.5, marginTop: 2 }}>
          {c.plan ? agMonthLabel(c.plan.month) + ' · ' + (c.plan.status === 'generating' ? 'gerando' : c.plan.n_items + ' peças') : 'sem calendário'}
          {c.enabled ? ' · piloto ligado' : ''}
        </div>
        {c.plan && <div style={{ fontSize: 11.5, marginTop: 4 }}>
          {n(c, ['idea']) > 0 && <span style={{ color: '#d97706' }}>{n(c, ['idea'])} ideias · </span>}
          {n(c, ['art']) > 0 && <span style={{ color: '#d97706' }}>{n(c, ['art'])} artes · </span>}
          <span style={{ color: '#059669' }}>{n(c, ['scheduled', 'art_ok', 'published'])} agendadas/publicadas</span>
        </div>}
      </button>)}
    </div>
  </div>;
}

function AgenciaApp() {
  const [companies, setCompanies] = React.useState([]);
  const [cid, setCid] = React.useState('');
  const [plans, setPlans] = React.useState([]);
  const [planId, setPlanId] = React.useState('');
  const [plan, setPlan] = React.useState(null);
  const [month, setMonth] = React.useState('');
  const [busy, setBusy] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [filter, setFilter] = React.useState('all');
  const [view, setView] = React.useState('list');
  const [open, setOpen] = React.useState({});
  const [ask, setAsk] = React.useState(null);
  const [cfgOpen, setCfgOpen] = React.useState(false);
  const [clients, setClients] = React.useState([]);
  const [viewer, setViewer] = React.useState(null);
  const pollRef = React.useRef(null);

  React.useEffect(() => {
    window.mpApi.listCompanies().then(cs => {
      cs = [...cs].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
      setCompanies(cs);
      let last = ''; try { last = localStorage.getItem('mp.agencia.cid') || ''; } catch (_) {}
      const c = cs.find(x => x.id === last) || cs[0];
      if (c) setCid(c.id);
    }).catch(e => setMsg('Erro: ' + e.message));
    loadOverview();
    return () => clearInterval(pollRef.current);
  }, []);

  function loadPlans(selectId) {
    if (!cid) return;
    window.mpApi.agencyPlans(cid).then(r => {
      setPlans(r.plans || []);
      if (!month) setMonth(r.next_month || '');
      setPlanId(selectId || ((r.plans || [])[0] || {}).id || '');
    }).catch(e => setMsg('Erro: ' + e.message));
  }
  function loadOverview() { window.mpApi.agencyOverview().then(r => setClients(r.clients || [])).catch(() => {}); }
  React.useEffect(() => {
    setPlan(null); setPlanId(''); loadPlans();
    try { if (cid) localStorage.setItem('mp.agencia.cid', cid); } catch (_) {}
  }, [cid]);

  const needsPoll = p => p && (p.status === 'generating' || (p.items || []).some(i => AG_WORKING.includes(i.stage)));
  function loadPlan(id) {
    clearInterval(pollRef.current);
    if (!id) { setPlan(null); return; }
    window.mpApi.agencyPlan(id).then(r => {
      setPlan(r.plan);
      if (needsPoll(r.plan)) {
        pollRef.current = setInterval(() => window.mpApi.agencyPlan(id).then(x => {
          setPlan(x.plan);
          if (!needsPoll(x.plan)) { clearInterval(pollRef.current); setMsg(''); loadOverview(); if (x.plan.status !== 'generating') loadPlans(id); }
        }).catch(() => {}), 6000);
      }
    }).catch(e => setMsg('Erro: ' + e.message));
  }
  React.useEffect(() => { loadPlan(planId); }, [planId]);

  async function gerar() {
    if (plans.find(p => p.month === month) && !(await mpConfirm('Já existe um calendário de ' + agMonthLabel(month) + '. Gerar outro mesmo assim?', { confirmLabel: 'Gerar outro' }))) return;
    setBusy('gen'); setMsg('');
    try {
      const r = await window.mpApi.agencyCreatePlan(cid, { month });
      setMsg('Montando ' + r.slots + ' peças de ' + agMonthLabel(month) + '… leva alguns minutos; pode deixar aberto.');
      loadPlans(r.plan.id);
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(''); }
  }

  function patchLocal(item) { setPlan(p => p ? { ...p, items: p.items.map(i => i.id === item.id ? item : i) } : p); }
  async function act(it, fn, ok) {
    setBusy(it.id);
    try { const r = await fn(); if (r && r.item) patchLocal(r.item); if (ok) mpToast(ok); }
    catch (e) { mpToast('Erro: ' + e.message, 'err'); }
    finally { setBusy(''); }
  }
  const setStage = (it, stage, comment) => act(it, () => window.mpApi.agencyUpdateItem(it.id, { stage, ...(comment != null ? { review_comment: comment } : {}) }));
  async function confirmAsk() {
    const { it, kind, text } = ask;
    setAsk(null);
    const c = text.trim();
    if (kind === 'reject') return setStage(it, 'idea_rejected', c);
    if (kind === 'regen') return act(it, () => window.mpApi.agencyRegenerate(it.id, c), 'Ideia refeita.');
    if (kind === 'rejectArt') return act(it, () => window.mpApi.agencyRejectArt(it.id, c));
    if (kind === 'regenArt') { await act(it, () => window.mpApi.agencyProduceItem(it.id, c), 'Arte na fila.'); return loadPlan(plan.id); }
  }
  async function salvarCampo(it, field, value) {
    if ((it[field] || '') === value) return;
    try { const r = await window.mpApi.agencyUpdateItem(it.id, { [field]: value }); patchLocal(r.item); mpToast('Salvo.'); }
    catch (e) { mpToast('Erro: ' + e.message, 'err'); }
  }
  async function aprovarTodas() {
    if (!(await mpConfirm('Aprovar todas as ideias que ainda estão pendentes?', { confirmLabel: 'Aprovar todas' }))) return;
    setBusy('all');
    try { const r = await window.mpApi.agencyApproveIdeas(plan.id); setPlan(r.plan); mpToast(r.approved + ' ideia(s) aprovada(s).'); }
    catch (e) { mpToast('Erro: ' + e.message, 'err'); }
    finally { setBusy(''); }
  }
  async function produzir() {
    const n = count('idea_ok') + count('art_rejected');
    if (!(await mpConfirm('Gerar a arte de ' + n + ' peça(s) aprovada(s)? Usa o Estúdio IA (assinatura, sem custo; se ela falhar, usa créditos kie). Leva ~2–4 min por peça e roda em segundo plano — pode fechar o app.', { confirmLabel: 'Gerar artes' }))) return;
    setBusy('prod');
    try { const r = await window.mpApi.agencyProduce(plan.id); setPlan(r.plan); mpToast(r.queued + ' arte(s) na fila.'); loadPlan(plan.id); }
    catch (e) { mpToast('Erro: ' + e.message, 'err'); }
    finally { setBusy(''); }
  }
  async function aprovarArte(it) {
    await act(it, () => window.mpApi.agencyApproveArt(it.id));
  }
  async function excluirPlano() {
    if (!(await mpConfirm('Excluir o calendário de ' + agMonthLabel(plan.month) + ' e todas as peças dele? (artes já geradas continuam em Arquivos)', { confirmLabel: 'Excluir' }))) return;
    try { await window.mpApi.agencyDeletePlan(plan.id); setPlan(null); loadPlans(); }
    catch (e) { mpToast('Erro: ' + e.message, 'err'); }
  }
  function pick(it) {
    setView('list'); setFilter('all'); setOpen(o => ({ ...o, [it.id]: true }));
    setTimeout(() => { const el = document.getElementById('ag-' + it.id); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 80);
  }

  const items = (plan && plan.items) || [];
  const count = k => items.filter(i => i.stage === k).length;
  const fmtCount = f => items.filter(i => i.format === f).length;
  const working = items.filter(i => AG_WORKING.includes(i.stage)).length;
  const shown = items.filter(i => filter === 'all' || i.stage === filter || i.format === filter
    || (filter === 'arte' && ['art', 'art_queued', 'producing', 'art_rejected'].includes(i.stage))
    || (filter === 'agenda' && ['art_ok', 'scheduled', 'published', 'failed'].includes(i.stage)));

  return <div className="app">
    <AppHead icon="calendar" title="Agência" desc="Calendário editorial automático: a IA planeja, escreve e cria as artes; você aprova; o sistema agenda e publica."
      right={<button className="btn sm ghost" disabled={!cid} onClick={() => setCfgOpen(true)}><Icon name="settings" />Configurar agência do cliente</button>} />

    <AgOverview clients={clients} cid={cid} onPick={setCid} />

    <div className="panel stack">
      <div className="rowx" style={{ flexWrap: 'wrap', gap: 10, alignItems: 'flex-end' }}>
        <Field label="Empresa">
          <select className="inp" value={cid} onChange={e => setCid(e.target.value)}>
            {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Calendário">
          <select className="inp" value={planId} onChange={e => setPlanId(e.target.value)}>
            {!plans.length && <option value="">— nenhum ainda —</option>}
            {plans.map(p => <option key={p.id} value={p.id}>{agMonthLabel(p.month)} · {p.n_items} peças{p.status === 'generating' ? ' (gerando)' : p.status === 'error' ? ' (erro)' : ''}</option>)}
          </select>
        </Field>
        <Field label="Gerar mês">
          <input className="inp" type="month" value={month} onChange={e => setMonth(e.target.value)} />
        </Field>
        <button className="btn pri" disabled={!cid || !month || busy === 'gen'} onClick={gerar}>
          <Icon name="sparkles" />{busy === 'gen' ? 'Iniciando…' : 'Gerar calendário'}
        </button>
      </div>
      {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    </div>

    {plan && plan.status === 'generating' && <Callout icon="sparkles">
      Montando o calendário de {agMonthLabel(plan.month)} — {plan.error || 'começando'}… as peças aparecem abaixo quando terminar.
    </Callout>}
    {plan && plan.status === 'ideas' && plan.error && <Callout kind="warn">{plan.error}</Callout>}
    {plan && plan.status === 'error' && <Callout kind="danger">Falhou: {plan.error}. Exclua e gere de novo.</Callout>}
    {working > 0 && <Callout icon="image">Gerando {working} arte(s) em segundo plano (~2–4 min cada). Pode fechar o app — elas aparecem aqui quando prontas.</Callout>}

    {plan && plan.status !== 'generating' && <div className="panel stack">
      <div className="rowx" style={{ flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <b style={{ fontSize: 16 }}>{agMonthLabel(plan.month)}</b>
        <Pill kind="cy">{fmtCount('post')} posts</Pill>
        <Pill kind="violet">{fmtCount('carrossel')} carrosséis</Pill>
        <Pill kind="warn">{fmtCount('reels')} reels</Pill>
        <span style={{ flex: 1 }} />
        <button className="btn sm ghost" onClick={excluirPlano}><Icon name="trash" />Excluir</button>
      </div>
      <div className="rowx" style={{ flexWrap: 'wrap', gap: 6 }}>
        <Pill kind="warn" dot>{count('idea')} ideias p/ aprovar</Pill>
        <Pill kind="good" dot>{count('idea_ok')} ideias aprovadas</Pill>
        <Pill kind="warn" dot>{count('art')} artes p/ aprovar</Pill>
        <Pill kind="good" dot>{count('scheduled') + count('art_ok')} agendadas</Pill>
        <Pill kind="good" dot>{count('published')} publicadas</Pill>
        {count('failed') > 0 && <Pill kind="danger" dot>{count('failed')} falharam</Pill>}
        <span style={{ flex: 1 }} />
        <button className="btn sm ghost" disabled={!count('idea') || busy === 'all'} onClick={aprovarTodas}><Icon name="check" />Aprovar todas as ideias</button>
        <button className="btn sm pri" disabled={!(count('idea_ok') + count('art_rejected')) || busy === 'prod'} onClick={produzir}><Icon name="image" />Gerar artes ({count('idea_ok') + count('art_rejected')})</button>
      </div>
      {(plan.dates || []).length > 0 && <div className="hint">Datas do mês: {plan.dates.map(d => d.date.slice(8, 10) + '/' + d.date.slice(5, 7) + ' ' + d.nome).join(' · ')}</div>}
      <div className="rowx" style={{ flexWrap: 'wrap', gap: 8 }}>
        <Segmented value={view} onChange={setView} options={[['list', 'Lista'], ['month', 'Mês']]} />
        {view === 'list' && <Segmented value={filter} onChange={setFilter} options={[['all', 'Todas'], ['idea', 'Ideias p/ aprovar'], ['idea_ok', 'Ideias aprovadas'], ['arte', 'Artes'], ['agenda', 'Agendadas'], ['post', 'Posts'], ['carrossel', 'Carrosséis'], ['reels', 'Reels']]} />}
      </div>
    </div>}

    {plan && plan.status !== 'generating' && view === 'month' && <AgMonthGrid month={plan.month} items={items} dates={plan.dates} onPick={pick} />}

    {plan && plan.status !== 'generating' && view === 'list' && <div className="stack">
      {!shown.length && <EmptyState icon="calendar" title="Nada aqui">Troque o filtro.</EmptyState>}
      {shown.map(it => {
        const [fl, fk] = AG_FMT[it.format] || [it.format, ''];
        const [sl, sk] = AG_STAGE[it.stage] || [it.stage, ''];
        const isOpen = !!open[it.id];
        const meta = it.meta || {};
        const slides = meta.slides || [];
        const ideaStage = ['idea', 'idea_ok', 'idea_rejected'].includes(it.stage);
        return <div key={it.id} id={'ag-' + it.id} className="panel stack" style={{ opacity: ['idea_rejected', 'skipped'].includes(it.stage) ? 0.6 : 1 }}>
          <div className="rowx" style={{ flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
            <b>{agSlotLabel(it.slot_at)}</b>
            <Pill kind={fk}>{fl}</Pill>
            {it.pillar && <Pill>{it.pillar}</Pill>}
            {it.product && <Pill kind="cy" icon="layers">{it.product}</Pill>}
            {it.date_hint && <Pill kind="violet" icon="calendar">{it.date_hint}</Pill>}
            <span style={{ flex: 1 }} />
            <Pill kind={sk} dot>{sl}</Pill>
          </div>
          <div style={{ fontSize: 17, fontWeight: 700 }}>{it.title || <span className="mut">(sem ideia — clique em Refazer)</span>}</div>
          {it.angle && <div className="mut">{it.angle}</div>}
          {it.review_comment && <div className="hint">Comentário: {it.review_comment}</div>}
          {it.error && <div className={['art_ok'].includes(it.stage) ? 'hint' : 'err'}>{it.error}</div>}
          {meta.art_warning && it.stage === 'art' && <div className="hint">Conferência de texto: {meta.art_warning}</div>}
          {slides.length > 0 && <div className="rowx" style={{ gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
            {slides.map((u, k) => <img key={u} src={u} alt={'tela ' + (k + 1)} onClick={() => setViewer({ slides, k })}
              style={{ height: 210, borderRadius: 10, cursor: 'zoom-in', flex: 'none', boxShadow: '0 2px 10px rgba(0,0,0,.12)' }} />)}
          </div>}
          {isOpen && <div className="stack">
            <Field label="Legenda">
              <textarea className="inp" rows={9} defaultValue={it.copy || ''} onBlur={e => salvarCampo(it, 'copy', e.target.value)} />
            </Field>
            <Field label="Hashtags">
              <input className="inp" defaultValue={it.hashtags || ''} onBlur={e => salvarCampo(it, 'hashtags', e.target.value)} />
            </Field>
            <Field label={it.format === 'reels' ? 'Roteiro do reels' : 'Direção de arte'}>
              <textarea className="inp" rows={4} defaultValue={it.art_brief || ''} onBlur={e => salvarCampo(it, 'art_brief', e.target.value)} />
            </Field>
          </div>}
          <div className="rowx" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button className="btn sm ghost" onClick={() => setOpen(o => ({ ...o, [it.id]: !isOpen }))}>
              <Icon name="eye" />{isOpen ? 'Fechar' : 'Ver legenda'}
            </button>
            <span style={{ flex: 1 }} />
            {ideaStage && <>
              <button className="btn sm ghost" disabled={busy === it.id} onClick={() => setAsk({ it, kind: 'regen', text: it.review_comment || '' })}><Icon name="refresh" />{busy === it.id ? 'Refazendo…' : 'Refazer ideia'}</button>
              {it.stage !== 'idea_rejected' && <button className="btn sm ghost" disabled={busy === it.id} onClick={() => setAsk({ it, kind: 'reject', text: it.review_comment || '' })}><Icon name="x" />Reprovar</button>}
              {it.stage !== 'idea_ok' && it.title && <button className="btn sm pri" disabled={busy === it.id} onClick={() => setStage(it, 'idea_ok')}><Icon name="check" />Aprovar ideia</button>}
              {it.stage === 'idea_ok' && <button className="btn sm ghost" disabled={busy === it.id} onClick={() => setStage(it, 'idea')}>Desfazer aprovação</button>}
              {it.stage === 'idea_ok' && <button className="btn sm" disabled={busy === it.id} onClick={() => act(it, () => window.mpApi.agencyProduceItem(it.id, ''), 'Arte na fila.').then(() => loadPlan(plan.id))}><Icon name="image" />Gerar arte</button>}
            </>}
            {it.post_id && slides.length > 0 && ['art', 'art_ok'].includes(it.stage) && <>
              <button className="btn sm ghost" disabled={busy === it.id} title="Abre como design editável no Canva" onClick={() => act(it, async () => {
                const r = await window.mpApi.canvaOpenOrConnect(it.post_id); if (r.canva && r.canva.edit_url) window.open(r.canva.edit_url, '_blank'); return null;
              }, 'Aberto no Canva — edite e depois clique em "Trazer do Canva".')}><Icon name="pen" />Editar no Canva</button>
              <button className="btn sm ghost" disabled={busy === it.id} title="Traz a versão editada no Canva" onClick={() => act(it, async () => {
                await window.mpApi.canvaPull(it.post_id); return window.mpApi.agencyRefreshArt(it.id);
              }, 'Versão do Canva trazida.')}><Icon name="download" />Trazer do Canva</button>
            </>}
            {['art', 'art_rejected'].includes(it.stage) && <>
              <button className="btn sm ghost" disabled={busy === it.id} onClick={() => setAsk({ it, kind: 'regenArt', text: '' })}><Icon name="refresh" />Refazer arte</button>
              {it.stage === 'art' && <button className="btn sm ghost" disabled={busy === it.id} onClick={() => setAsk({ it, kind: 'rejectArt', text: '' })}><Icon name="x" />Reprovar arte</button>}
              {it.stage === 'art' && <button className="btn sm pri" disabled={busy === it.id} onClick={() => aprovarArte(it)}><Icon name="check" />Aprovar e agendar</button>}
            </>}
          </div>
        </div>;
      })}
    </div>}

    {viewer && <Lightbox src={viewer.slides[viewer.k]} kind="image" name={(viewer.k + 1) + ' / ' + viewer.slides.length} onClose={() => setViewer(null)}
      actions={<>
        <a className="btn sm" href={viewer.slides[viewer.k]} download={'arte-' + (viewer.k + 1) + '.png'}><Icon name="download" />Baixar</a>
        <button className="btn sm ghost" disabled={viewer.k === 0} onClick={() => setViewer(v => ({ ...v, k: v.k - 1 }))}>Anterior</button>
        <button className="btn sm ghost" disabled={viewer.k === viewer.slides.length - 1} onClick={() => setViewer(v => ({ ...v, k: v.k + 1 }))}>Próxima</button>
      </>} />}

    {ask && <Modal size="sm" icon={['reject', 'rejectArt'].includes(ask.kind) ? 'x' : 'refresh'} onClose={() => setAsk(null)}
      title={{ reject: 'Reprovar ideia', regen: 'Refazer ideia', rejectArt: 'Reprovar arte', regenArt: 'Refazer arte' }[ask.kind]}
      sub={['reject', 'rejectArt'].includes(ask.kind) ? 'Diga o que não ficou bom (opcional). Vira instrução quando mandar refazer.' : 'Diga como quer a nova versão (opcional).'}
      foot={<><button className="btn ghost" onClick={() => setAsk(null)}>Cancelar</button>
        <button className="btn pri" onClick={confirmAsk}>{['reject', 'rejectArt'].includes(ask.kind) ? 'Reprovar' : 'Refazer'}</button></>}>
      <textarea className="inp" rows={4} autoFocus value={ask.text} onChange={e => setAsk({ ...ask, text: e.target.value })}
        placeholder={ask.kind.includes('Art') ? 'Ex.: logo maior, fundo mais claro, sem pessoas' : 'Ex.: foque em reforma tributária, tom mais direto'} />
    </Modal>}

    {cfgOpen && <AgConfigModal cid={cid} name={(companies.find(c => c.id === cid) || {}).name} onClose={saved => { setCfgOpen(false); if (saved) loadOverview(); }} />}

    {!plan && cid && <EmptyState icon="calendar" title="Nenhum calendário ainda">
      Escolha o mês e clique em "Gerar calendário". Na primeira vez, a IA monta a linha editorial sob medida deste cliente (pilares, tom, hashtags) a partir do cadastro — dá para ajustar em "Configurar agência do cliente". Depois planeja as peças do mês com legenda pronta, usando o catálogo, as datas comemorativas e os eventos.
    </EmptyState>}
  </div>;
}

Object.assign(window, { AgenciaApp });
