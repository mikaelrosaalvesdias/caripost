/* Caripost OS — Agência automática: calendário editorial do mês (etapa 1: ideias + legendas) */

const AG_FMT = { post: ['Post', 'cy'], carrossel: ['Carrossel', 'violet'], reels: ['Reels', 'warn'] };
const AG_STAGE = {
  idea: ['Ideia para aprovar', 'warn'], idea_ok: ['Ideia aprovada', 'good'], idea_rejected: ['Reprovada', ''],
};
const AG_WD = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
const AG_MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];

function agMonthLabel(m) {
  if (!m) return '';
  const [y, mm] = m.split('-').map(Number);
  return AG_MESES[mm - 1] + ' de ' + y;
}
function agSlotLabel(s) {
  const d = new Date(s.slice(0, 10) + 'T12:00:00');
  return AG_WD[d.getDay()] + ', ' + s.slice(8, 10) + '/' + s.slice(5, 7) + ' · ' + s.slice(11, 16);
}

function AgenciaApp() {
  const [companies, setCompanies] = React.useState([]);
  const [cid, setCid] = React.useState('');
  const [plans, setPlans] = React.useState([]);
  const [nextMonth, setNextMonth] = React.useState('');
  const [planId, setPlanId] = React.useState('');
  const [plan, setPlan] = React.useState(null);
  const [month, setMonth] = React.useState('');
  const [busy, setBusy] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [filter, setFilter] = React.useState('all');
  const [open, setOpen] = React.useState({});
  const [ask, setAsk] = React.useState(null);
  const pollRef = React.useRef(null);

  React.useEffect(() => {
    window.mpApi.listCompanies().then(cs => {
      setCompanies(cs);
      const c = cs.find(x => /cariap/i.test(x.name)) || cs[0];
      if (c) setCid(c.id);
    }).catch(e => setMsg('Erro: ' + e.message));
    return () => clearInterval(pollRef.current);
  }, []);

  function loadPlans(selectId) {
    if (!cid) return;
    window.mpApi.agencyPlans(cid).then(r => {
      setPlans(r.plans || []); setNextMonth(r.next_month || '');
      if (!month) setMonth(r.next_month || '');
      const pick = selectId || ((r.plans || [])[0] || {}).id || '';
      setPlanId(pick);
    }).catch(e => setMsg('Erro: ' + e.message));
  }
  React.useEffect(() => { setPlan(null); setPlanId(''); loadPlans(); }, [cid]);

  function loadPlan(id) {
    if (!id) { setPlan(null); return; }
    window.mpApi.agencyPlan(id).then(r => {
      setPlan(r.plan);
      clearInterval(pollRef.current);
      if (r.plan && r.plan.status === 'generating') {
        pollRef.current = setInterval(() => window.mpApi.agencyPlan(id).then(x => {
          setPlan(x.plan);
          if (x.plan.status !== 'generating') { clearInterval(pollRef.current); setMsg(''); loadPlans(id); }
        }).catch(() => {}), 4000);
      }
    }).catch(e => setMsg('Erro: ' + e.message));
  }
  React.useEffect(() => { loadPlan(planId); }, [planId]);

  async function gerar() {
    const existing = plans.find(p => p.month === month);
    if (existing && !(await mpConfirm('Já existe um calendário de ' + agMonthLabel(month) + '. Gerar outro mesmo assim?', { confirmLabel: 'Gerar outro' }))) return;
    setBusy('gen'); setMsg('');
    try {
      const r = await window.mpApi.agencyCreatePlan(cid, { month });
      setMsg('Montando ' + r.slots + ' peças de ' + agMonthLabel(month) + '… leva alguns minutos; pode deixar aberto.');
      loadPlans(r.plan.id);
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(''); }
  }

  function patchLocal(item) {
    setPlan(p => p ? { ...p, items: p.items.map(i => i.id === item.id ? item : i) } : p);
  }
  async function setStage(it, stage, comment) {
    setBusy(it.id);
    try { const r = await window.mpApi.agencyUpdateItem(it.id, { stage, ...(comment != null ? { review_comment: comment } : {}) }); patchLocal(r.item); }
    catch (e) { mpToast('Erro: ' + e.message, 'err'); }
    finally { setBusy(''); }
  }
  function reprovar(it) { setAsk({ it, kind: 'reject', text: it.review_comment || '' }); }
  function refazer(it) { setAsk({ it, kind: 'regen', text: it.review_comment || '' }); }
  async function confirmAsk() {
    const { it, kind, text } = ask;
    setAsk(null);
    if (kind === 'reject') return setStage(it, 'idea_rejected', text.trim());
    setBusy(it.id);
    try { const r = await window.mpApi.agencyRegenerate(it.id, text.trim()); patchLocal(r.item); mpToast('Ideia refeita.'); }
    catch (e) { mpToast('Erro: ' + e.message, 'err'); }
    finally { setBusy(''); }
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
  async function excluirPlano() {
    if (!(await mpConfirm('Excluir o calendário de ' + agMonthLabel(plan.month) + ' e todas as ideias dele?', { confirmLabel: 'Excluir' }))) return;
    try { await window.mpApi.agencyDeletePlan(plan.id); setPlan(null); loadPlans(); }
    catch (e) { mpToast('Erro: ' + e.message, 'err'); }
  }

  const items = (plan && plan.items) || [];
  const count = k => items.filter(i => i.stage === k).length;
  const fmtCount = f => items.filter(i => i.format === f).length;
  const shown = items.filter(i => filter === 'all' || i.stage === filter || i.format === filter);

  return <div className="app">
    <AppHead icon="calendar" title="Agência" desc="Calendário editorial automático do mês: a IA planeja as peças e escreve as legendas; você aprova."
      right={<Pill kind="violet" icon="sparkles">Etapa 1 · ideias</Pill>} />

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

    {plan && plan.status !== 'generating' && <div className="panel stack">
      <div className="rowx" style={{ flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <b style={{ fontSize: 16 }}>{agMonthLabel(plan.month)}</b>
        <Pill kind="cy">{fmtCount('post')} posts</Pill>
        <Pill kind="violet">{fmtCount('carrossel')} carrosséis</Pill>
        <Pill kind="warn">{fmtCount('reels')} reels</Pill>
        <span style={{ flex: 1 }} />
        <Pill kind="warn" dot>{count('idea')} para aprovar</Pill>
        <Pill kind="good" dot>{count('idea_ok')} aprovadas</Pill>
        <Pill dot>{count('idea_rejected')} reprovadas</Pill>
        <button className="btn sm pri" disabled={!count('idea') || busy === 'all'} onClick={aprovarTodas}><Icon name="check" />Aprovar todas</button>
        <button className="btn sm ghost" onClick={excluirPlano}><Icon name="trash" />Excluir</button>
      </div>
      {(plan.dates || []).length > 0 && <div className="hint">Datas do mês: {plan.dates.map(d => d.date.slice(8, 10) + '/' + d.date.slice(5, 7) + ' ' + d.nome).join(' · ')}</div>}
      <Segmented value={filter} onChange={setFilter} options={[['all', 'Todas'], ['idea', 'Para aprovar'], ['idea_ok', 'Aprovadas'], ['idea_rejected', 'Reprovadas'], ['post', 'Posts'], ['carrossel', 'Carrosséis'], ['reels', 'Reels']]} />
    </div>}

    {plan && plan.status !== 'generating' && <div className="stack">
      {!shown.length && <EmptyState icon="calendar" title="Nada aqui">Troque o filtro.</EmptyState>}
      {shown.map(it => {
        const [fl, fk] = AG_FMT[it.format] || [it.format, ''];
        const [sl, sk] = AG_STAGE[it.stage] || [it.stage, ''];
        const isOpen = !!open[it.id];
        return <div key={it.id} className="panel stack" style={{ opacity: it.stage === 'idea_rejected' ? 0.6 : 1 }}>
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
              <Icon name="eye" />{isOpen ? 'Fechar' : 'Ver legenda e arte'}
            </button>
            <span style={{ flex: 1 }} />
            <button className="btn sm ghost" disabled={busy === it.id} onClick={() => refazer(it)}><Icon name="refresh" />{busy === it.id ? 'Refazendo…' : 'Refazer'}</button>
            {it.stage !== 'idea_rejected' && <button className="btn sm ghost" disabled={busy === it.id} onClick={() => reprovar(it)}><Icon name="x" />Reprovar</button>}
            {it.stage !== 'idea_ok' && it.title && <button className="btn sm pri" disabled={busy === it.id} onClick={() => setStage(it, 'idea_ok')}><Icon name="check" />Aprovar ideia</button>}
            {it.stage === 'idea_ok' && <button className="btn sm ghost" disabled={busy === it.id} onClick={() => setStage(it, 'idea')}>Desfazer aprovação</button>}
          </div>
        </div>;
      })}
    </div>}

    {ask && <Modal size="sm" icon={ask.kind === 'reject' ? 'x' : 'refresh'} onClose={() => setAsk(null)}
      title={ask.kind === 'reject' ? 'Reprovar ideia' : 'Refazer ideia'}
      sub={ask.kind === 'reject' ? 'Diga o que não ficou bom (opcional). Vira instrução se você mandar refazer depois.' : 'Diga como quer a nova versão (opcional).'}
      foot={<><button className="btn ghost" onClick={() => setAsk(null)}>Cancelar</button>
        <button className="btn pri" onClick={confirmAsk}>{ask.kind === 'reject' ? 'Reprovar' : 'Refazer'}</button></>}>
      <textarea className="inp" rows={4} autoFocus value={ask.text} onChange={e => setAsk({ ...ask, text: e.target.value })}
        placeholder={ask.kind === 'reject' ? 'Ex.: tema repetido, prefiro falar de ExitLag' : 'Ex.: foque em reforma tributária, tom mais direto'} />
    </Modal>}

    {!plan && cid && <EmptyState icon="calendar" title="Nenhum calendário ainda">
      Escolha o mês e clique em "Gerar calendário". A IA monta cerca de 22 peças (posts, carrosséis e reels) com legenda pronta, usando o catálogo, as datas comemorativas e os eventos da empresa.
    </EmptyState>}
  </div>;
}

Object.assign(window, { AgenciaApp });
