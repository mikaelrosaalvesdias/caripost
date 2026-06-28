/* Caripost OS — Gestão de Agência: Criadores, Tendências, Financeiro, DMCA, Settings */

const MP_OS_VERSION = 'v1.26.63';

/* ── CRIADORES ── */
function CreatorsApp() {
  const [creators, setCreators] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [selectedId, setSelectedId] = React.useState(null);
  const [creating, setCreating] = React.useState(false);

  const load = React.useCallback(() => {
    setLoading(true);
    window.mpApi.listCreators().then(r => { setCreators(r); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  React.useEffect(() => { if (window.mpApi) load(); }, [load]);

  return <div className="app">
    <AppHead icon="users" title="Gestão de Criadores" desc="Cadastro, perfis, contas e contratos dos criadores da agência."
      right={<button className="btn sm pri" onClick={() => { setCreating(c => !c); setSelectedId(null); }}><Icon name="plus" />Novo criador</button>} />
    <div className="grid3">
      <div className="stat"><div className="sv">{creators.length}</div><div className="sl">Criadores</div></div>
      <div className="stat"><div className="sv">{creators.filter(c => c.st === 'active' || c.st === 'ativo').length}</div><div className="sl">Ativos</div></div>
      <div className="stat"><div className="sv">{creators.filter(c => c.st === 'trial').length}</div><div className="sl">Em trial</div></div>
    </div>

    {creating && <CreatorForm onSaved={() => { setCreating(false); load(); }} onCancel={() => setCreating(false)} />}

    <div className="stack">
      {loading && <div className="hint">Carregando criadores…</div>}
      {!loading && !creators.length && <div className="hint">Nenhum criador cadastrado.</div>}
      {creators.map(c => <React.Fragment key={c.creator_id}>
        <div className="litem" style={{ padding: 14, cursor: 'pointer', borderColor: selectedId === c.creator_id ? 'var(--cyan)' : undefined }}
          onClick={() => { setSelectedId(id => id === c.creator_id ? null : c.creator_id); setCreating(false); }}>
          <div style={{ width: 48, height: 48, borderRadius: 14, background: 'linear-gradient(140deg,var(--pri),var(--pri2))', flex: 'none', display: 'grid', placeItems: 'center', fontFamily: 'var(--fh)', fontWeight: 700, fontSize: 18, color: '#fff' }}>{c.n[0]}</div>
          <div className="li-main"><b style={{ fontSize: 14 }}>{c.n}</b><small>{c.h}</small></div>
          <Pill kind={c.tone} dot>{c.st}</Pill>
        </div>
        {selectedId === c.creator_id && <CreatorDetail creatorId={c.creator_id} onSaved={load} onDeleted={() => { setSelectedId(null); load(); }} />}
      </React.Fragment>)}
    </div>
  </div>;
}

function CreatorForm({ onSaved, onCancel }) {
  const [name, setName] = React.useState('');
  const [email, setEmail] = React.useState('');
  const [phone, setPhone] = React.useState('');
  const [whatsapp, setWhatsapp] = React.useState('');
  const [status, setStatus] = React.useState('trial');
  const [commissionPct, setCommissionPct] = React.useState(25);
  const [notes, setNotes] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  async function save() {
    if (!name || !email) { setError('Nome e e-mail são obrigatórios.'); return; }
    setSaving(true); setError('');
    try {
      await window.mpApi.createCreator({
        name, email,
        phone: phone || null, whatsapp: whatsapp || null,
        status, commission_pct: Number(commissionPct) || 0,
        notes: notes || null,
      });
      onSaved();
    } catch (e) { setError(e.message || 'Erro ao criar criador.'); }
    finally { setSaving(false); }
  }

  return <div className="panel stack">
    <div className="sec cy"><Icon name="plus" />Novo criador</div>
    <div className="split">
      <div className="stack">
        <Field label="Nome"><input className="inp" value={name} onChange={e => setName(e.target.value)} /></Field>
        <Field label="E-mail"><input className="inp" type="email" value={email} onChange={e => setEmail(e.target.value)} /></Field>
        <Field label="Telefone"><input className="inp" value={phone} onChange={e => setPhone(e.target.value)} /></Field>
        <Field label="WhatsApp"><input className="inp" value={whatsapp} onChange={e => setWhatsapp(e.target.value)} /></Field>
      </div>
      <div className="stack">
        <Field label="Status">
          <select className="inp" value={status} onChange={e => setStatus(e.target.value)}>
            <option value="trial">Trial</option>
            <option value="active">Ativo</option>
            <option value="paused">Pausado</option>
            <option value="churned">Encerrado</option>
          </select>
        </Field>
        <Field label="Comissão da agência (%)"><input className="inp" type="number" min="0" max="100" value={commissionPct} onChange={e => setCommissionPct(e.target.value)} /></Field>
        <Field label="Notas"><textarea className="inp" rows="3" value={notes} onChange={e => setNotes(e.target.value)} /></Field>
      </div>
    </div>
    {error && <div className="hint" style={{ color: 'var(--pri)' }}>✗ {error}</div>}
    <div className="rowx" style={{ gap: 8 }}>
      <button className="btn pri" disabled={saving} onClick={save}><Icon name="check" />{saving ? 'Salvando…' : 'Criar criador'}</button>
      <button className="btn ghost" onClick={onCancel}>Cancelar</button>
    </div>
  </div>;
}

function PlatformAccountForm({ onSubmit, onSaved, onCancel }) {
  const [platforms, setPlatforms] = React.useState(['xvideos', 'pornhub', 'xnxx', 'xhamster']);
  const [platform, setPlatform] = React.useState('xvideos');
  const [username, setUsername] = React.useState('');
  const [profileUrl, setProfileUrl] = React.useState('');
  const [cookies, setCookies] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    window.mpApi.publisherPlatforms().then(p => { if (p && p.length) { setPlatforms(p); setPlatform(p[0]); } }).catch(() => {});
  }, []);

  async function save() {
    if (!username) { setError('Informe o usuário/handle.'); return; }
    setSaving(true); setError('');
    try {
      await onSubmit({ platform, username, profile_url: profileUrl || null, cookies_json: cookies || null });
      onSaved();
    } catch (e) { setError(e.message || 'Erro ao salvar conta.'); }
    finally { setSaving(false); }
  }

  return <div className="panel stack">
    <Field label="Plataforma">
      <select className="inp" value={platform} onChange={e => setPlatform(e.target.value)}>
        {platforms.map(p => <option key={p} value={p}>{p}</option>)}
      </select>
    </Field>
    <Field label="Usuário / handle"><input className="inp" value={username} onChange={e => setUsername(e.target.value)} /></Field>
    <Field label="URL do perfil (opcional)"><input className="inp" value={profileUrl} onChange={e => setProfileUrl(e.target.value)} /></Field>
    <Field label="Cookies (JSON, opcional — para publicação automática)">
      <textarea className="inp" rows="2" value={cookies} onChange={e => setCookies(e.target.value)} placeholder='[{"name":"...","value":"..."}]' />
    </Field>
    {error && <div className="hint" style={{ color: 'var(--pri)' }}>✗ {error}</div>}
    <div className="rowx" style={{ gap: 8 }}>
      <button className="btn pri sm" disabled={saving} onClick={save}><Icon name="check" />{saving ? 'Salvando…' : 'Adicionar'}</button>
      <button className="btn ghost sm" onClick={onCancel}>Cancelar</button>
    </div>
  </div>;
}

function CreatorDetail({ creatorId, onSaved, onDeleted }) {
  const [creator, setCreator] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [editing, setEditing] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [stats, setStats] = React.useState([]);
  const [scraping, setScraping] = React.useState(false);
  const [addingPlatform, setAddingPlatform] = React.useState(false);

  const [status, setStatus] = React.useState('trial');
  const [phone, setPhone] = React.useState('');
  const [whatsapp, setWhatsapp] = React.useState('');
  const [commissionPct, setCommissionPct] = React.useState(0);
  const [notes, setNotes] = React.useState('');

  function load() {
    setLoading(true);
    window.mpApi.getCreator(creatorId).then(c => {
      setCreator(c);
      setStatus(c.status); setPhone(c.phone || ''); setWhatsapp(c.whatsapp || '');
      setCommissionPct(c.commission_pct ?? 0); setNotes(c.notes || '');
      setLoading(false);
    }).catch(e => { setError(e.message); setLoading(false); });
  }

  React.useEffect(() => {
    load();
    window.mpApi.creatorStats(creatorId).then(r => setStats(r.stats || [])).catch(() => {});
  }, [creatorId]);

  async function save() {
    setSaving(true); setError('');
    try {
      await window.mpApi.updateCreator(creatorId, {
        status, phone: phone || null, whatsapp: whatsapp || null,
        commission_pct: Number(commissionPct) || 0, notes: notes || null,
      });
      setEditing(false); load(); onSaved && onSaved();
    } catch (e) { setError(e.message || 'Erro ao salvar.'); }
    finally { setSaving(false); }
  }

  async function remove() {
    if (!confirm(`Encerrar/remover o criador "${creator?.name}"?`)) return;
    try { await window.mpApi.deleteCreator(creatorId); onDeleted && onDeleted(); } catch (e) { alert('Erro: ' + e.message); }
  }

  async function scrapeStats() {
    setScraping(true); setMsg('');
    try { await window.mpApi.creatorScrapeStats(creatorId); setMsg('✓ Coleta de estatísticas iniciada em segundo plano.'); }
    catch (e) { setMsg('✗ ' + e.message); }
    finally { setScraping(false); }
  }

  async function removePlatform(platform) {
    if (!confirm(`Remover conta de ${platform}?`)) return;
    try { await window.mpApi.removeCreatorPlatform(creatorId, platform); load(); } catch (e) { alert('Erro: ' + e.message); }
  }

  async function checkLogin(platform) {
    setMsg('Verificando login…');
    try {
      const r = await window.mpApi.creatorLoginCheck(creatorId, platform);
      const st = (r.platforms && r.platforms[platform] && r.platforms[platform].status) || 'desconhecido';
      setMsg(`${platform}: ${st}`);
      load();
    } catch (e) { setMsg('✗ ' + e.message); }
  }

  if (loading) return <div className="panel"><div className="hint">Carregando criador…</div></div>;
  if (!creator) return null;

  return <div className="panel stack" style={{ marginLeft: 30, marginBottom: 8 }}>
    <div className="rowx" style={{ justifyContent: 'space-between' }}>
      <div className="sec cy">{creator.name} <span className="hint" style={{ marginLeft: 6 }}>{creator.email}</span></div>
      <div className="rowx" style={{ gap: 8 }}>
        <button className="btn sm ghost" onClick={() => setEditing(e => !e)}><Icon name="pen" />{editing ? 'Fechar edição' : 'Editar'}</button>
        <button className="btn sm ghost" style={{ color: 'var(--pri)' }} onClick={remove}><Icon name="trash" />Encerrar</button>
      </div>
    </div>

    {editing && <React.Fragment>
      <div className="split">
        <div className="stack">
          <Field label="Status">
            <select className="inp" value={status} onChange={e => setStatus(e.target.value)}>
              <option value="trial">Trial</option>
              <option value="active">Ativo</option>
              <option value="paused">Pausado</option>
              <option value="churned">Encerrado</option>
            </select>
          </Field>
          <Field label="Telefone"><input className="inp" value={phone} onChange={e => setPhone(e.target.value)} /></Field>
          <Field label="WhatsApp"><input className="inp" value={whatsapp} onChange={e => setWhatsapp(e.target.value)} /></Field>
        </div>
        <div className="stack">
          <Field label="Comissão da agência (%)"><input className="inp" type="number" min="0" max="100" value={commissionPct} onChange={e => setCommissionPct(e.target.value)} /></Field>
          <Field label="Notas"><textarea className="inp" rows="3" value={notes} onChange={e => setNotes(e.target.value)} /></Field>
        </div>
      </div>
      <div className="rowx" style={{ gap: 8 }}>
        <button className="btn pri sm" disabled={saving} onClick={save}><Icon name="check" />{saving ? 'Salvando…' : 'Salvar alterações'}</button>
      </div>
    </React.Fragment>}

    {error && <div className="hint" style={{ color: 'var(--pri)' }}>✗ {error}</div>}

    <div className="sec mut">Contas de plataforma</div>
    {(creator.platforms || []).map(p => <div key={p.platform} className="litem">
      <span className="li-ic"><Icon name="globe" /></span>
      <div className="li-main">
        <b style={{ textTransform: 'capitalize' }}>{p.platform}</b>
        <small>@{p.username} · {p.status}{p.last_login_check ? ' · checado ' + window.mpApi.fmtDate(p.last_login_check) : ''}</small>
      </div>
      <button className="btn sm ghost" onClick={() => checkLogin(p.platform)}><Icon name="shieldscan" />Checar login</button>
      <button className="btn sm ghost" style={{ color: 'var(--pri)' }} onClick={() => removePlatform(p.platform)}><Icon name="trash" /></button>
    </div>)}
    {!(creator.platforms || []).length && <div className="hint">Nenhuma conta de plataforma cadastrada.</div>}
    {!addingPlatform && <button className="btn sm" onClick={() => setAddingPlatform(true)}><Icon name="plus" />Adicionar conta de plataforma</button>}
    {addingPlatform && <PlatformAccountForm onSaved={() => { setAddingPlatform(false); load(); }} onCancel={() => setAddingPlatform(false)}
      onSubmit={payload => window.mpApi.addCreatorPlatform(creatorId, payload)} />}

    <div className="rowx" style={{ justifyContent: 'space-between' }}>
      <div className="sec mut">Estatísticas</div>
      <button className="btn sm" disabled={scraping} onClick={scrapeStats}><Icon name="refresh" />{scraping ? 'Coletando…' : 'Atualizar estatísticas'}</button>
    </div>
    {msg && <div className="hint">{msg}</div>}
    {stats.length ? stats.map((s, i) => <div key={i} className="row">
      <span className="k" style={{ textTransform: 'capitalize' }}>{s.platform}</span>
      <span className="v">{s.subscribers ?? '—'} inscritos · {s.total_views ?? '—'} views · R$ {s.earnings ?? '0'}</span>
    </div>) : <div className="hint">Sem estatísticas coletadas ainda.</div>}
  </div>;
}

/* ── TENDÊNCIAS ── */
function TrendsApp() {
  const [collecting, setCollecting] = React.useState(false);
  const [genBusy, setGenBusy] = React.useState(false);
  const [genAllBusy, setGenAllBusy] = React.useState(false);
  const [trends, setTrends] = React.useState([]);
  const [creators, setCreators] = React.useState([]);
  const [selCreator, setSelCreator] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [expanded, setExpanded] = React.useState(null);
  const [busyId, setBusyId] = React.useState('');

  // Company-based AI trends
  const [companies, setCompanies] = React.useState([]);
  const [selCompany, setSelCompany] = React.useState(null);
  const [report, setReport] = React.useState(null);
  const [aiEnabled, setAiEnabled] = React.useState(false);
  const [aiBusy, setAiBusy] = React.useState(false);

  function _load() {
    window.mpApi.listTrends().then(r => setTrends(r.map(b => ({
      t: b.market_summary ? String(b.market_summary).slice(0, 70) : 'Briefing',
      g: b.generated_at ? new Date(b.generated_at).toLocaleDateString('pt-BR') : '—',
      tone: b.sent_email || b.sent_whatsapp ? 'good' : 'warn',
      id: b.briefing_id,
      sent_email: b.sent_email, sent_whatsapp: b.sent_whatsapp,
      market_summary: b.market_summary, suggestions: b.suggestions || [], avoid: b.avoid || [],
    })))).catch(() => {});
  }

  React.useEffect(() => {
    if (!window.mpApi) return;
    _load();
    window.mpApi.listCreators().then(c => { setCreators(c); if (c.length) setSelCreator(c[0].creator_id); }).catch(() => {});
    // Load companies for AI trends
    window.mpApi.listCompanies().then(cs => { setCompanies(cs); if (cs.length) setSelCompany(cs[0].id); }).catch(() => {});
    window.mpApi.getAIStatus().then(s => setAiEnabled(s.ai_enabled)).catch(() => {});
  }, []);

  React.useEffect(() => {
    if (selCompany) window.mpApi.getTrendsReport(selCompany).then(r => setReport(r.report)).catch(() => setReport(null));
  }, [selCompany]);

  async function generateAITrends() {
    if (!selCompany) return;
    setAiBusy(true); setMsg('');
    try {
      await window.mpApi.generateTrendsReport(selCompany);
      const r = await window.mpApi.getTrendsReport(selCompany);
      setReport(r.report); setMsg('✓ Briefing gerado!');
    } catch (e) { setMsg('✗ ' + e.message); }
    finally { setAiBusy(false); }
  }

  async function approve(id) {
    setBusyId(id); setMsg('');
    try { await window.mpApi.approveBriefing(id, true); setMsg('✓ Briefing aprovado e notificação enviada.'); _load(); }
    catch (e) { setMsg('✗ ' + e.message); }
    finally { setBusyId(''); }
  }

  async function send(id) {
    setBusyId(id); setMsg('');
    try { await window.mpApi.sendBriefing(id, ['email']); setMsg('✓ Briefing enviado.'); _load(); }
    catch (e) { setMsg('✗ ' + e.message); }
    finally { setBusyId(''); }
  }

  const p = report?.payload || {};
  const themes = p.themes || [];
  const hashtags = p.hashtags || [];

  return <div className="app">
    <AppHead icon="trending" title="Tendências" desc="Briefing de temas em alta por empresa — vira pauta no gerador de conteúdo."
      right={<Pill kind="violet" icon="sparkles">IA briefing</Pill>} />

    {/* AI trends by company */}
    <div className="panel stack">
      <div className="sec"><Icon name="sparkles" />Briefing por Empresa</div>
      {!companies.length && <div className="hint">Cadastre uma empresa primeiro.</div>}
      {companies.length > 0 && <div className="rowx" style={{ flexWrap: 'wrap' }}>
        {companies.map(c => <button key={c.id} className={'btn sm' + (selCompany === c.id ? ' pri' : ' ghost')} onClick={() => setSelCompany(c.id)}>{c.name}</button>)}
      </div>}
      {!aiEnabled && <div className="hint">Configure a IA primeiro em Settings.</div>}
      {aiEnabled && <button className="btn sm pri" disabled={aiBusy} onClick={generateAITrends}><Icon name="sparkles" />{aiBusy ? 'Gerando…' : (report ? 'Atualizar tendências' : 'Gerar tendências')}</button>}
      {report && <div className="stack">
        <div className="hint">Briefing gerado em {new Date(report.created_at).toLocaleString('pt-BR')}</div>
        <div style={{ fontSize: 14, color: 'var(--text2)' }}>{p.summary}</div>
        {hashtags.length > 0 && <div style={{ color: 'var(--accent)', fontSize: 13 }}>{hashtags.join(' ')}</div>}
        <div className="grid2">
          {themes.map((t, i) => <div key={i} className="panel stack" style={{ padding: 14 }}>
            <div className="row" style={{ gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--pri)' }}>{i + 1}</span>
              <b>{t.title}</b>
            </div>
            <small style={{ color: 'var(--text2)' }}>{t.why}</small>
            {t.formats && t.formats.length > 0 && <div className="rowx" style={{ gap: 6 }}>{t.formats.map((f, j) => <Pill key={j} kind="cy">{f.toUpperCase()}</Pill>)}</div>}
            {t.example && <div style={{ padding: 12, border: '1px solid var(--line)', borderRadius: 8, fontSize: 13, color: 'var(--muted)' }}>{t.example}</div>}
          </div>)}
        </div>
      </div>}
    </div>

    {msg && <div className="hint" style={{ color: msg.startsWith('✓') ? 'var(--good)' : msg.startsWith('✗') ? 'var(--pri)' : 'var(--muted)' }}>{msg}</div>}

    {/* Creator briefings (legacy) */}
    <div className="sec mut"><Icon name="trending" />Briefings por Criador</div>
    <div className="split">
      <div className="stack">
        {!trends.length && <div className="hint">Nenhum briefing ainda.</div>}
        {trends.slice(0, 8).map((t, i) => <React.Fragment key={t.id || i}>
          <div className="litem" style={{ cursor: 'pointer' }} onClick={() => setExpanded(e => e === t.id ? null : t.id)}>
            <span className="li-ic"><Icon name="trending" /></span>
            <div className="li-main"><b style={{ fontSize: 12.5 }}>{t.t}</b><small>{t.g}</small></div>
            <Pill kind={t.tone} dot>{t.sent_email || t.sent_whatsapp ? 'enviado' : 'pendente'}</Pill>
          </div>
          {expanded === t.id && <div className="panel stack" style={{ marginLeft: 20 }}>
            <div style={{ fontSize: 13 }}>{t.market_summary}</div>
            {t.suggestions.map((s, j) => <div key={j} className="litem">
              <div className="li-main"><b style={{ fontSize: 12.5 }}>{s.title}</b><small>{s.concept} · {s.why_trending}</small></div>
              <Pill kind="cy">{s.view_potential}</Pill>
            </div>)}
            {!!t.avoid.length && <div className="hint">Evitar: {t.avoid.join(', ')}</div>}
            <div className="rowx" style={{ gap: 8 }}>
              <button className="btn sm pri" disabled={busyId === t.id} onClick={() => approve(t.id)}><Icon name="check" />Aprovar</button>
              <button className="btn sm ghost" disabled={busyId === t.id} onClick={() => send(t.id)}><Icon name="send" />Enviar</button>
            </div>
          </div>}
        </React.Fragment>)}
      </div>
      <div className="stack">
        <div className="panel stack">
          <div className="sec">Gerar briefing por criador</div>
          <Field label="Criador">
            <select className="inp" value={selCreator} onChange={e => setSelCreator(e.target.value)}>
              {creators.map(c => <option key={c.creator_id} value={c.creator_id}>{c.n}</option>)}
            </select>
          </Field>
          <button className="btn pri sm" disabled={genBusy || !selCreator} onClick={() => {
            setGenBusy(true); setMsg('Gerando briefing…');
            window.mpApi.generateBriefing(selCreator).then(() => { setMsg('✓ Briefing em geração — atualize em ~1 min.'); })
              .catch(e => setMsg('✗ ' + e.message)).finally(() => setGenBusy(false));
          }}><Icon name="sparkles" />{genBusy ? 'Gerando…' : 'Gerar Briefing'}</button>
        </div>
      </div>
    </div>
  </div>;
}

/* ── FINANCEIRO ── */
function FinancialApp() {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [creators, setCreators] = React.useState([]);
  const [platforms, setPlatforms] = React.useState(['xvideos', 'pornhub', 'xnxx', 'xhamster']);
  const [showEarning, setShowEarning] = React.useState(false);
  const [showReport, setShowReport] = React.useState(false);

  function load() {
    setLoading(true);
    window.mpApi.agencyOverview().then(d => { setData(d); setLoading(false); }).catch(() => setLoading(false));
  }
  React.useEffect(() => {
    if (!window.mpApi) return;
    load();
    window.mpApi.listCreators().then(setCreators).catch(() => {});
    window.mpApi.publisherPlatforms().then(p => { if (p && p.length) setPlatforms(p); }).catch(() => {});
  }, []);

  const fmt = v => v != null ? 'R$ ' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 }) : '—';
  const byPlat = data?.by_platform || data?.platforms || {};
  const platRows = Object.entries(byPlat).slice(0, 6);
  const maxV = Math.max(1, ...platRows.map(([, v]) => Number(v.gross || v.total || v) || 0));
  return <div className="app">
    <AppHead icon="dollar" title="Financeiro" desc="Receita, payout e visão da agência — por plataforma e por criador."
      right={<button className="btn sm" onClick={() => { setShowEarning(s => !s); setShowReport(false); }}><Icon name="plus" />Lançar receita</button>} />
    {loading && <div className="hint">Carregando dados financeiros…</div>}
    {showEarning && <EarningForm creators={creators} platforms={platforms} onSaved={() => { setShowEarning(false); load(); }} onCancel={() => setShowEarning(false)} />}
    <div className="grid3">
      <div className="stat"><div className="sv">{fmt(data?.gross_total ?? data?.total_gross ?? data?.gross)}</div><div className="sl">Receita bruta (mês)</div></div>
      <div className="stat"><div className="sv">{fmt(data?.net_total ?? data?.total_net ?? data?.net)}</div><div className="sl">Líquido pós-taxas</div></div>
      <div className="stat"><div className="sv">{fmt(data?.agency_commission ?? data?.commission)}</div><div className="sl">Comissão agência</div></div>
    </div>
    <div className="panel stack">
      <div className="sec mut"><Icon name="dollar" />Receita por plataforma</div>
      {!platRows.length && <div className="hint">Sem lançamentos no período. Registre receitas via API ou na UI de Financeiro.</div>}
      {platRows.map(([n, v]) => {
        const val = Number(v.gross || v.total || v) || 0;
        return <div key={n}>
          <div className="rowx" style={{ justifyContent: 'space-between', marginBottom: 5 }}><span style={{ fontSize: 13, textTransform: 'capitalize' }}>{n}</span><b style={{ fontFamily: 'var(--fh)', fontSize: 13 }}>{fmt(val)}</b></div>
          <div className="track gd"><i style={{ width: Math.round(val / maxV * 100) + '%' }} /></div>
        </div>;
      })}
    </div>
    {data?.period && <div className="hint">Período: {data.period.start || ''} → {data.period.end || ''}</div>}
    <div className="panel stack">
      <div className="rowx" style={{ justifyContent: 'space-between' }}>
        <div className="sec mut"><Icon name="doc" />Relatório mensal por criador</div>
        <button className="btn sm ghost" onClick={() => { setShowReport(s => !s); setShowEarning(false); }}>{showReport ? 'Fechar' : 'Gerar relatório'}</button>
      </div>
      {showReport && <ReportForm creators={creators} />}
    </div>
  </div>;
}

function EarningForm({ creators, platforms, onSaved, onCancel }) {
  const [creatorId, setCreatorId] = React.useState(creators[0]?.creator_id || '');
  const [platform, setPlatform] = React.useState(platforms[0] || 'xvideos');
  const [period, setPeriod] = React.useState(new Date().toISOString().slice(0, 7));
  const [grossRevenue, setGrossRevenue] = React.useState('');
  const [platformFeePct, setPlatformFeePct] = React.useState('');
  const [viewsInPeriod, setViewsInPeriod] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => { if (!creatorId && creators.length) setCreatorId(creators[0].creator_id); }, [creators]);

  async function save() {
    if (!creatorId) { setError('Selecione um criador.'); return; }
    setSaving(true); setError('');
    try {
      await window.mpApi.financialRecordEarning({
        creator_id: creatorId, platform, period,
        gross_revenue: Number(grossRevenue) || 0,
        platform_fee_pct: Number(platformFeePct) || 0,
        views_in_period: Number(viewsInPeriod) || 0,
        source: 'manual',
      });
      onSaved();
    } catch (e) { setError(e.message || 'Erro ao registrar receita.'); }
    finally { setSaving(false); }
  }

  return <div className="panel stack">
    <div className="sec cy"><Icon name="plus" />Lançar receita manual</div>
    <div className="split">
      <div className="stack">
        <Field label="Criador">
          <select className="inp" value={creatorId} onChange={e => setCreatorId(e.target.value)}>
            {creators.map(c => <option key={c.creator_id} value={c.creator_id}>{c.n}</option>)}
          </select>
        </Field>
        <Field label="Plataforma">
          <select className="inp" value={platform} onChange={e => setPlatform(e.target.value)}>
            {platforms.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </Field>
        <Field label="Período (mês)"><input className="inp" type="month" value={period} onChange={e => setPeriod(e.target.value)} /></Field>
      </div>
      <div className="stack">
        <Field label="Receita bruta (R$)"><input className="inp" type="number" min="0" step="0.01" value={grossRevenue} onChange={e => setGrossRevenue(e.target.value)} /></Field>
        <Field label="Taxa da plataforma (%)"><input className="inp" type="number" min="0" max="100" step="0.1" value={platformFeePct} onChange={e => setPlatformFeePct(e.target.value)} /></Field>
        <Field label="Views no período"><input className="inp" type="number" min="0" value={viewsInPeriod} onChange={e => setViewsInPeriod(e.target.value)} /></Field>
      </div>
    </div>
    {error && <div className="hint" style={{ color: 'var(--pri)' }}>✗ {error}</div>}
    <div className="rowx" style={{ gap: 8 }}>
      <button className="btn pri" disabled={saving} onClick={save}><Icon name="check" />{saving ? 'Salvando…' : 'Registrar receita'}</button>
      <button className="btn ghost" onClick={onCancel}>Cancelar</button>
    </div>
  </div>;
}

function ReportForm({ creators }) {
  const [creatorId, setCreatorId] = React.useState(creators[0]?.creator_id || '');
  const [month, setMonth] = React.useState(new Date().toISOString().slice(0, 7));
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');

  React.useEffect(() => { if (!creatorId && creators.length) setCreatorId(creators[0].creator_id); }, [creators]);

  async function generate() {
    if (!creatorId) { setMsg('✗ Selecione um criador.'); return; }
    setBusy(true); setMsg('Gerando e enviando relatório…');
    try {
      const r = await window.mpApi.financialGenerateReport(creatorId, month);
      const sent = r.sent?.email?.success;
      setMsg(sent ? '✓ Relatório gerado e enviado por e-mail.' : '✓ Relatório gerado (envio por e-mail não confirmado).');
    } catch (e) { setMsg('✗ ' + e.message); }
    finally { setBusy(false); }
  }

  return <div className="stack">
    <div className="rowx">
      <select className="inp" style={{ flex: 1 }} value={creatorId} onChange={e => setCreatorId(e.target.value)}>
        {creators.map(c => <option key={c.creator_id} value={c.creator_id}>{c.n}</option>)}
      </select>
      <input className="inp" type="month" value={month} onChange={e => setMonth(e.target.value)} style={{ flex: 'none', width: 140 }} />
      <button className="btn pri sm" disabled={busy} onClick={generate}><Icon name="send" />{busy ? 'Gerando…' : 'Gerar e enviar'}</button>
    </div>
    {msg && <div className="hint" style={{ color: msg.startsWith('✓') ? 'var(--good)' : 'var(--pri)' }}>{msg}</div>}
  </div>;
}

/* ── DMCA ── */
function DmcaApp() {
  const [scanning, setScanning] = React.useState(false);
  const [infr, setInfr] = React.useState([]);
  const [creators, setCreators] = React.useState([]);
  const [selCreator, setSelCreator] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [stats, setStats] = React.useState(null);
  const [selected, setSelected] = React.useState([]);
  const [bulkBusy, setBulkBusy] = React.useState(false);

  function _load() {
    window.mpApi.listDmca().then(setInfr).catch(() => {});
    window.mpApi.dmcaStats().then(setStats).catch(() => {});
  }
  React.useEffect(() => {
    if (!window.mpApi) return;
    _load();
    window.mpApi.listCreators().then(setCreators).catch(() => {});
  }, []);

  function toggleSel(id) {
    setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id]);
  }

  async function bulkTakedown() {
    if (!selected.length) return;
    setBulkBusy(true); setMsg('Enviando takedowns em massa…');
    try {
      const r = await window.mpApi.dmcaBulkTakedown(selected);
      setMsg(`✓ ${Object.keys(r.results || {}).length} takedown(s) processados.`);
      setSelected([]); _load();
    } catch (e) { setMsg('✗ ' + e.message); }
    finally { setBulkBusy(false); }
  }

  async function setStatus(id, status) {
    try { await window.mpApi.dmcaUpdateStatus(id, status); _load(); } catch (e) { alert('Erro: ' + e.message); }
  }

  return <div className="app">
    <AppHead icon="shield" title="Proteção DMCA" desc="Escaneia a web por pirataria do conteúdo dos criadores e dispara takedowns."
      right={<Pill kind="good" dot>monitorando</Pill>} />
    <div className="grid3">
      <div className="stat"><div className="sv">{stats?.total_detected ?? infr.length}</div><div className="sl">Infrações registradas</div></div>
      <div className="stat"><div className="sv">{stats?.pending_action ?? infr.filter(i => i.tone === 'pri').length}</div><div className="sl">Pendentes</div></div>
      <div className="stat"><div className="sv">{stats?.total_removed ?? infr.filter(i => i.tone === 'good').length}</div><div className="sl">Removidas</div></div>
    </div>
    <div className="panel stack">
      <div className="sec">Escanear por pirataria</div>
      <div className="rowx">
        <select className="inp" style={{ flex: 1 }} value={selCreator} onChange={e => setSelCreator(e.target.value)}>
          <option value="">Todos os criadores</option>
          {creators.map(c => <option key={c.creator_id} value={c.creator_id}>{c.n}</option>)}
        </select>
        <button className="btn pri" disabled={scanning} onClick={() => {
          setScanning(true); setMsg('Varredura iniciada…');
          window.mpApi.scanDmca(selCreator || null).then(() => { setMsg('✓ Scan em andamento — atualize em alguns minutos.'); })
            .catch(e => setMsg('✗ ' + e.message)).finally(() => setScanning(false));
        }}><Icon name="shieldscan" />{scanning ? 'Escaneando…' : 'Escanear Agora'}</button>
      </div>
      {msg && <div className="hint" style={{ color: msg.startsWith('✓') ? 'var(--good)' : 'var(--pri)' }}>{msg}</div>}
    </div>
    <div className="stack">
      <div className="rowx" style={{ justifyContent: 'space-between' }}>
        <div className="sec mut"><Icon name="warning" />Infrações <button className="btn sm ghost" style={{ marginLeft: 8 }} onClick={_load}><Icon name="refresh" /></button></div>
        {!!selected.length && <button className="btn sm pri" disabled={bulkBusy} onClick={bulkTakedown}><Icon name="shield" />{bulkBusy ? 'Enviando…' : `Takedown (${selected.length})`}</button>}
      </div>
      {!infr.length && <div className="hint">Nenhuma infração registrada.</div>}
      {infr.map((x, i) => <div key={i} className="litem">
        <input type="checkbox" checked={selected.includes(x.id)} onChange={() => toggleSel(x.id)} />
        <span className="li-ic" style={{ color: x.tone === 'pri' ? 'var(--pri)' : 'var(--good)' }}><Icon name="warning" /></span>
        <div className="li-main"><b style={{ fontFamily: 'var(--fm)', fontSize: 12 }}>{x.url}</b><small>{x.c} · {x.d}</small></div>
        <select className="inp" value={x.rawStatus} onChange={e => setStatus(x.id, e.target.value)} style={{ flex: 'none', width: 150 }}>
          <option value="detected">detectado</option>
          <option value="takedown_sent">takedown enviado</option>
          <option value="removed">removido</option>
          <option value="ignored">ignorado</option>
          <option value="failed">falhou</option>
        </select>
        {x.tone === 'pri' && <button className="btn sm pri" onClick={() => {
          window.mpApi.dmcaTakedown(x.id).then(() => _load()).catch(e => alert('Erro: ' + e.message));
        }}><Icon name="shield" />Takedown</button>}
      </div>)}
    </div>
  </div>;
}

/* ── SETTINGS — tokens reais, versão e sistema ── */
const IMG_PROVS = [
  { id: 'omniroute', label: 'OmniRoute (grátis · assinatura)', ph: 'token do gateway (opcional)' },
  { id: 'cometapi', label: 'CometAPI', ph: 'sk-...' },
  { id: 'piapi', label: 'PiAPI', ph: 'chave PiAPI' },
  { id: 'openrouter', label: 'OpenRouter', ph: 'sk-or-...' },
];
function ImageModelPicker() {
  const [models, setModels] = React.useState([]);
  const [current, setCurrent] = React.useState('');
  const [sel, setSel] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [keys, setKeys] = React.useState({});
  const [masks, setMasks] = React.useState({});
  const [savingP, setSavingP] = React.useState('');

  const load = React.useCallback(() => {
    setLoading(true);
    window.mpApi.aiModels().then(r => {
      const list = r.image || [];
      setModels(list); setCurrent(r.image_current || '');
      setSel(r.image_current || (list[0] && list[0].id) || '');
      setLoading(false);
    }).catch(() => setLoading(false));
    window.mpApi.getAISettings().then(s => setMasks((s && s.image && s.image.keyMasks) || {})).catch(() => {});
  }, []);
  React.useEffect(() => { if (window.mpApi) load(); }, [load]);

  async function saveKey(p) {
    const v = (keys[p] || '').trim(); if (!v) return;
    setSavingP(p);
    try {
      await window.mpApi.saveAISettings({ ['image.apiKey.' + p]: v });
      setMsg('✓ Chave salva: ' + p); setKeys(k => ({ ...k, [p]: '' }));
      const s = await window.mpApi.getAISettings(); setMasks((s && s.image && s.image.keyMasks) || {}); load();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setSavingP(''); }
  }
  async function save() {
    setMsg('Salvando…');
    try { const r = await window.mpApi.setAiModel({ image_model: sel }); setCurrent(r.image_current); setMsg('✓ Modelo padrão: ' + r.image_current); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }
  const price = m => m.price_brl ? ' · R$ ' + Number(m.price_brl).toFixed(2) : (m.free ? ' · grátis' : '');
  const PLAB = { omniroute: 'OmniRoute (grátis · assinatura)', cometapi: 'CometAPI', piapi: 'PiAPI', openrouter: 'OpenRouter' };
  const groups = (() => { const g = {}; models.forEach(m => { const p = m.provider || 'outros'; (g[p] = g[p] || []).push(m); }); return Object.keys(g).map(p => ({ provider: p, label: PLAB[p] || p, models: g[p] })); })();

  return <div className="panel stack">
    <div className="sec"><Icon name="image" />Provedor de IA (imagem)</div>
    <div className="hint">Conecte a chave de cada provedor. Na criação você escolhe provedor + modelo livremente (e compara preços).</div>
    {IMG_PROVS.map(pr => <div key={pr.id} className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <b style={{ minWidth: 210 }}>{pr.label}</b>
      <Pill kind={masks[pr.id] ? 'good' : 'warn'} dot>{masks[pr.id] ? 'configurado' : 'configurar'}</Pill>
      <input className="inp" type="password" value={keys[pr.id] || ''} onChange={e => setKeys(k => ({ ...k, [pr.id]: e.target.value }))} placeholder={pr.ph} style={{ flex: 1, minWidth: 160 }} />
      <button className="btn sm pri" disabled={savingP === pr.id} onClick={() => saveKey(pr.id)}>{savingP === pr.id ? '…' : 'Salvar'}</button>
    </div>)}
    {current && <div className="row"><span className="k">Modelo padrão</span><span className="v mono" style={{ color: 'var(--cyan)' }}>{current}</span></div>}
    <Field label="Modelo de imagem padrão (posts)">
      <div className="rowx" style={{ gap: 8 }}>
        <select className="inp" value={sel} onChange={e => setSel(e.target.value)}>
          {groups.length ? groups.map(grp => <optgroup key={grp.provider} label={grp.label}>
            {grp.models.map(m => <option key={m.id} value={m.id}>{(m.name || m.id) + price(m)}</option>)}
          </optgroup>) : <option value="">{loading ? 'Carregando…' : 'Sem modelos (configure uma chave acima)'}</option>}
        </select>
        <button className="btn sm ghost" onClick={load}><Icon name="refresh" />Recarregar</button>
      </div>
    </Field>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <button className="btn sm pri" onClick={save}>Definir como padrão</button>
  </div>;
}

function SettingsApp() {
  const [tab, setTab] = React.useState('tokens');
  const [tokens, setTokens] = React.useState([]);
  const [health, setHealth] = React.useState(null);
  const [savingFor, setSavingFor] = React.useState('');
  const PROVIDERS = [
    'openai', 'grok', 'gemini', 'deepseek', 'openrouter', 'groq', 'deepgram', 'assemblyai', 'fal',
    'composio', 'composio_auth_config_instagram', 'composio_auth_config_facebook', 'composio_auth_config_tiktok', 'composio_auth_config_youtube',
  ];
  const TOKEN_LABELS = {
    composio: 'Composio API',
    composio_auth_config_instagram: 'Instagram Auth Config',
    composio_auth_config_facebook: 'Facebook Auth Config',
    composio_auth_config_tiktok: 'TikTok Auth Config',
    composio_auth_config_youtube: 'YouTube Auth Config',
  };

  // AI settings state
  const [aiSettings, setAiSettings] = React.useState(null);
  const [aiProvider, setAiProvider] = React.useState('anthropic');
  const [aiModel, setAiModel] = React.useState('');
  const [aiKey, setAiKey] = React.useState('');
  const [aiKeyMask, setAiKeyMask] = React.useState('');
  const [aiModels, setAiModels] = React.useState([]);
  const [aiMsg, setAiMsg] = React.useState('');
  const [aiSaving, setAiSaving] = React.useState(false);
  const [aiTesting, setAiTesting] = React.useState(false);
  const [aiTestResult, setAiTestResult] = React.useState('');

  function _load() {
    window.mpApi.getTokens().then(setTokens).catch(() => {});
  }
  React.useEffect(() => {
    if (!window.mpApi) return;
    _load();
    window.mpApi.fetch('/health').then(setHealth).catch(() => setHealth({ ok: false }));
    // Load AI settings
    window.mpApi.getAISettings().then(s => {
      setAiSettings(s);
      if (s.ai) { setAiProvider(s.ai.provider || 'anthropic'); setAiModel(s.ai.model || ''); setAiKeyMask(s.ai.keyMasks?.[s.ai.provider] || ''); }
    }).catch(() => {});
  }, []);

  function _tokenFor(p) {
    return tokens.find(t => (t.key || '').replace('token:', '') === p);
  }

  async function saveToken(p) {
    const label = TOKEN_LABELS[p] || p;
    const v = prompt('Cole o valor de ' + label + ':');
    if (!v) return;
    setSavingFor(p);
    try { await window.mpApi.saveToken(p, v.trim()); _load(); }
    catch (e) { alert('Erro: ' + e.message); }
    finally { setSavingFor(''); }
  }

  async function loadAIModels() {
    try {
      const models = await window.mpApi.loadAIModels('ai', aiProvider, aiKey || null);
      setAiModels(models);
      if (models.length && !aiModel) setAiModel(models[0]);
    } catch (e) { setAiMsg('Erro ao carregar modelos: ' + e.message); }
  }

  async function saveAISettings() {
    setAiSaving(true); setAiMsg('');
    const body = { 'ai.provider': aiProvider };
    if (aiModel) body['ai.model'] = aiModel;
    if (aiKey) body['ai.apiKey.' + aiProvider] = aiKey;
    try {
      await window.mpApi.saveAISettings(body);
      setAiMsg('✓ Configurações salvas');
      setAiKey('');
      const s = await window.mpApi.getAISettings();
      setAiSettings(s);
      if (s.ai) setAiKeyMask(s.ai.keyMasks?.[aiProvider] || '');
    } catch (e) { setAiMsg('✗ ' + e.message); }
    finally { setAiSaving(false); }
  }

  async function testAI() {
    setAiTesting(true); setAiTestResult('');
    try {
      const r = await window.mpApi.testAI();
      setAiTestResult(r.test_result === 'ok' ? '✓ Conexão ok — IA pronta.' : '✗ ' + (r.message || 'Erro'));
    } catch (e) { setAiTestResult('✗ ' + e.message); }
    finally { setAiTesting(false); }
  }

  return <div className="app">
    <AppHead icon="settings" title="Settings" desc="Tokens de IA, sistema e informações da plataforma."
      right={<Pill kind="cy" dot>{MP_OS_VERSION}</Pill>} />
    <div className="tabbar">
      {[['tokens', 'Tokens & IA'], ['ai', 'IA Caripost'], ['sys', 'Sistema']].map(([k, l]) =>
        <button key={k} className={'tabx' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}
    </div>
    {tab === 'tokens' && <div className="stack">
      {PROVIDERS.map(p => {
        const t = _tokenFor(p);
        return <div key={p} className="litem">
          <span className="li-ic"><Icon name="key" /></span>
          <div className="li-main"><b style={{ textTransform: 'capitalize' }}>{TOKEN_LABELS[p] || p}</b><small style={{ fontFamily: 'var(--fm)' }}>{t ? 'configurado · ' + (t.updated_at || '').slice(0, 10) : 'não configurado'}</small></div>
          <Pill kind={t ? 'good' : 'warn'} dot>{t ? 'conectado' : 'configurar'}</Pill>
          <button className="btn sm ghost" disabled={savingFor === p} onClick={() => saveToken(p)}><Icon name="pen" />{savingFor === p ? '…' : ''}</button>
        </div>;
      })}
    </div>}
    {tab === 'ai' && <div className="stack">
      <div className="panel stack">
        <div className="sec"><Icon name="sparkles" />IA de texto</div>
        <div className="hint">Copy de posts, planos editoriais e briefings de tendência.</div>
        <Field label="Provedor">
          <select className="inp" value={aiProvider} onChange={e => { setAiProvider(e.target.value); setAiModel(''); setAiModels([]); setAiKeyMask(aiSettings?.ai?.keyMasks?.[e.target.value] || ''); }}>
            <option value="cometapi">CometAPI (Claude/GPT/Gemini · preserva acentos)</option>
            <option value="anthropic">Anthropic (Claude)</option>
            <option value="openai">OpenAI</option>
            <option value="openrouter">OpenRouter</option>
          </select>
        </Field>
        <Field label="Modelo">
          <div className="rowx" style={{ gap: 8 }}>
            <select className="inp" value={aiModel} onChange={e => setAiModel(e.target.value)}>
              {aiModels.length ? aiModels.map(m => <option key={m} value={m}>{m}</option>) : <option value="">{aiModel || 'Carregar modelos'}</option>}
            </select>
            <button className="btn sm ghost" onClick={loadAIModels}><Icon name="refresh" />Carregar</button>
          </div>
        </Field>
        <Field label="API Key">
          <input className="inp" type="password" value={aiKey} onChange={e => setAiKey(e.target.value)} placeholder="sk-ant-... / sk-... / sk-or-..." />
          {aiKeyMask && <small style={{ color: 'var(--muted)', fontSize: 11 }}>Chave salva: {aiKeyMask}. Em branco mantém.</small>}
        </Field>
        {aiMsg && <div className={aiMsg.startsWith('✓') ? 'ok' : 'err'}>{aiMsg}</div>}
        <button className="btn sm pri" disabled={aiSaving} onClick={saveAISettings}>{aiSaving ? 'Salvando…' : 'Salvar configurações'}</button>
      </div>
      <ImageModelPicker />
      <div className="panel stack">
        <div className="sec">Testar IA</div>
        <button className="btn sm" disabled={aiTesting} onClick={testAI}>{aiTesting ? 'Testando…' : 'Testar conexão'}</button>
        {aiTestResult && <div className={aiTestResult.startsWith('✓') ? 'ok' : 'err'}>{aiTestResult}</div>}
      </div>
    </div>}
    {tab === 'sys' && <div className="stack">
      <div className="panel stack">
        <div className="sec">Plataforma</div>
        <div className="kv">
          <div className="row"><span className="k">Versão do Caripost OS</span><span className="v mono" style={{ color: 'var(--cyan)', fontWeight: 700 }}>{MP_OS_VERSION}</span></div>
          <div className="row"><span className="k">API</span><span className="v" style={{ color: health?.ok ? 'var(--good)' : 'var(--pri)' }}>{health?.ok ? 'online' : 'offline'}</span></div>
          <div className="row"><span className="k">UI antiga (referência)</span><span className="v"><a href="/ui/" target="_blank" rel="noreferrer" style={{ color: 'var(--cyan)' }}>/ui/ ↗</a></span></div>
          <div className="row"><span className="k">Docs da API</span><span className="v"><a href="/docs" target="_blank" rel="noreferrer" style={{ color: 'var(--cyan)' }}>/docs ↗</a></span></div>
        </div>
      </div>
      <div className="panel stack">
        <div className="sec mut">Sessão</div>
        <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={() => window.mpApi.logout()}><Icon name="x" />Encerrar sessão</button>
      </div>
    </div>}
  </div>;
}

Object.assign(window, { CreatorsApp, TrendsApp, FinancialApp, DmcaApp, SettingsApp, MP_OS_VERSION });
