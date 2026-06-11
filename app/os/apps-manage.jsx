/* MetaPorn OS — Gestão de Agência: Criadores, Tendências, Financeiro, DMCA, Settings */

const MP_OS_VERSION = 'v1.20.0';

/* ── CRIADORES ── */
function CreatorsApp() {
  const [creators, setCreators] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  React.useEffect(() => {
    if (window.mpApi) window.mpApi.listCreators().then(r => { setCreators(r); setLoading(false); }).catch(() => setLoading(false));
  }, []);
  return <div className="app">
    <AppHead icon="users" title="Gestão de Criadores" desc="Cadastro, perfis, contas e contratos dos criadores da agência." />
    <div className="grid3">
      <div className="stat"><div className="sv">{creators.length}</div><div className="sl">Criadores</div></div>
      <div className="stat"><div className="sv">{creators.filter(c => c.st === 'active' || c.st === 'ativo').length}</div><div className="sl">Ativos</div></div>
      <div className="stat"><div className="sv">{creators.filter(c => c.st === 'trial').length}</div><div className="sl">Em trial</div></div>
    </div>
    <div className="stack">
      {loading && <div className="hint">Carregando criadores…</div>}
      {!loading && !creators.length && <div className="hint">Nenhum criador cadastrado.</div>}
      {creators.map(c => <div key={c.h} className="litem" style={{ padding: 14 }}>
        <div style={{ width: 48, height: 48, borderRadius: 14, background: 'linear-gradient(140deg,var(--pri),var(--pri2))', flex: 'none', display: 'grid', placeItems: 'center', fontFamily: 'var(--fh)', fontWeight: 700, fontSize: 18, color: '#fff' }}>{c.n[0]}</div>
        <div className="li-main"><b style={{ fontSize: 14 }}>{c.n}</b><small>{c.h}</small></div>
        <Pill kind={c.tone} dot>{c.st}</Pill>
      </div>)}
    </div>
  </div>;
}

/* ── TENDÊNCIAS ── */
function TrendsApp() {
  const [collecting, setCollecting] = React.useState(false);
  const [genBusy, setGenBusy] = React.useState(false);
  const [trends, setTrends] = React.useState([]);
  const [creators, setCreators] = React.useState([]);
  const [selCreator, setSelCreator] = React.useState('');
  const [msg, setMsg] = React.useState('');

  function _load() {
    window.mpApi.listTrends().then(r => setTrends(r.map(b => ({
      t: b.summary || b.trend_keyword || b.title || 'Briefing',
      g: b.created_at ? new Date(b.created_at).toLocaleDateString('pt-BR') : '—',
      tone: 'good',
      id: b.briefing_id || b.id,
      body: b.briefing_text || b.content || '',
    })))).catch(() => {});
  }

  React.useEffect(() => {
    if (!window.mpApi) return;
    _load();
    window.mpApi.listCreators().then(c => { setCreators(c); if (c.length) setSelCreator(c[0].creator_id); }).catch(() => {});
  }, []);

  return <div className="app">
    <AppHead icon="trending" title="Radar de Tendências" desc="Coleta tendências globais (XVideos/Pornhub) e gera briefings por criador com o Grok."
      right={<Pill kind="violet" icon="sparkles">Grok briefing</Pill>} />
    <div className="rowx">
      <button className="btn pri" disabled={collecting} onClick={() => {
        setCollecting(true); setMsg('Coletando tendências globais…');
        window.mpApi.collectTrends().then(() => { setMsg('✓ Coleta iniciada — atualize em alguns minutos.'); _load(); })
          .catch(e => setMsg('✗ ' + e.message)).finally(() => setCollecting(false));
      }}><Icon name="refresh" />{collecting ? 'Coletando…' : 'Coletar Tendências Globais'}</button>
      <button className="btn ghost" onClick={_load}><Icon name="list" />Atualizar Lista</button>
    </div>
    {msg && <div className="hint" style={{ color: msg.startsWith('✓') ? 'var(--good)' : msg.startsWith('✗') ? 'var(--pri)' : 'var(--muted)' }}>{msg}</div>}
    <div className="split">
      <div className="stack">
        <div className="sec mut"><Icon name="trending" />Briefings recentes</div>
        {!trends.length && <div className="hint">Nenhum briefing ainda. Colete tendências e gere um briefing.</div>}
        {trends.slice(0, 8).map((t, i) => <div key={i} className="litem">
          <span className="li-ic"><Icon name="trending" /></span>
          <div className="li-main"><b style={{ fontSize: 12.5 }}>{String(t.t).slice(0, 60)}</b><small>{t.g}</small></div>
          <Pill kind={t.tone} dot>ok</Pill>
        </div>)}
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
            setGenBusy(true); setMsg('Gerando briefing com Grok…');
            window.mpApi.generateBriefing(selCreator).then(() => { setMsg('✓ Briefing em geração — atualize a lista em ~1 min.'); })
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
  React.useEffect(() => {
    if (window.mpApi) window.mpApi.agencyOverview().then(d => { setData(d); setLoading(false); }).catch(() => setLoading(false));
  }, []);
  const fmt = v => v != null ? 'R$ ' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 }) : '—';
  const byPlat = data?.by_platform || data?.platforms || {};
  const platRows = Object.entries(byPlat).slice(0, 6);
  const maxV = Math.max(1, ...platRows.map(([, v]) => Number(v.gross || v.total || v) || 0));
  return <div className="app">
    <AppHead icon="dollar" title="Financeiro" desc="Receita, payout e visão da agência — por plataforma e por criador." />
    {loading && <div className="hint">Carregando dados financeiros…</div>}
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
  </div>;
}

/* ── DMCA ── */
function DmcaApp() {
  const [scanning, setScanning] = React.useState(false);
  const [infr, setInfr] = React.useState([]);
  const [creators, setCreators] = React.useState([]);
  const [selCreator, setSelCreator] = React.useState('');
  const [msg, setMsg] = React.useState('');

  function _load() {
    window.mpApi.listDmca().then(setInfr).catch(() => {});
  }
  React.useEffect(() => {
    if (!window.mpApi) return;
    _load();
    window.mpApi.listCreators().then(setCreators).catch(() => {});
  }, []);

  return <div className="app">
    <AppHead icon="shield" title="Proteção DMCA" desc="Escaneia a web por pirataria do conteúdo dos criadores e dispara takedowns."
      right={<Pill kind="good" dot>monitorando</Pill>} />
    <div className="grid3">
      <div className="stat"><div className="sv">{infr.length}</div><div className="sl">Infrações registradas</div></div>
      <div className="stat"><div className="sv">{infr.filter(i => i.tone === 'pri').length}</div><div className="sl">Ativas</div></div>
      <div className="stat"><div className="sv">{infr.filter(i => i.tone === 'good').length}</div><div className="sl">Resolvidas</div></div>
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
      <div className="sec mut"><Icon name="warning" />Infrações <button className="btn sm ghost" style={{ marginLeft: 8 }} onClick={_load}><Icon name="refresh" /></button></div>
      {!infr.length && <div className="hint">Nenhuma infração registrada.</div>}
      {infr.map((x, i) => <div key={i} className="litem">
        <span className="li-ic" style={{ color: x.tone === 'pri' ? 'var(--pri)' : 'var(--good)' }}><Icon name="warning" /></span>
        <div className="li-main"><b style={{ fontFamily: 'var(--fm)', fontSize: 12 }}>{x.url}</b><small>{x.c} · {x.d}</small></div>
        <Pill kind={x.tone} dot>{x.s}</Pill>
        {x.tone === 'pri' && <button className="btn sm pri" onClick={() => {
          window.mpApi.dmcaTakedown(x.id).then(() => _load()).catch(e => alert('Erro: ' + e.message));
        }}><Icon name="shield" />Takedown</button>}
      </div>)}
    </div>
  </div>;
}

/* ── SETTINGS — tokens reais, versão e sistema ── */
function SettingsApp() {
  const [tab, setTab] = React.useState('tokens');
  const [tokens, setTokens] = React.useState([]);
  const [health, setHealth] = React.useState(null);
  const [savingFor, setSavingFor] = React.useState('');
  const PROVIDERS = ['openai', 'grok', 'gemini', 'deepseek', 'openrouter', 'groq', 'deepgram', 'assemblyai', 'fal'];

  function _load() {
    window.mpApi.getTokens().then(setTokens).catch(() => {});
  }
  React.useEffect(() => {
    if (!window.mpApi) return;
    _load();
    window.mpApi.fetch('/health').then(setHealth).catch(() => setHealth({ ok: false }));
  }, []);

  function _tokenFor(p) {
    return tokens.find(t => (t.key || '').replace('token:', '') === p);
  }

  async function saveToken(p) {
    const v = prompt('Cole a API key de ' + p + ':');
    if (!v) return;
    setSavingFor(p);
    try { await window.mpApi.saveToken(p, v.trim()); _load(); }
    catch (e) { alert('Erro: ' + e.message); }
    finally { setSavingFor(''); }
  }

  return <div className="app">
    <AppHead icon="settings" title="Settings" desc="Tokens de IA, sistema e informações da plataforma."
      right={<Pill kind="cy" dot>{MP_OS_VERSION}</Pill>} />
    <div className="tabbar">
      {[['tokens', 'Tokens & IA'], ['sys', 'Sistema']].map(([k, l]) =>
        <button key={k} className={'tabx' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}
    </div>
    {tab === 'tokens' && <div className="stack">
      {PROVIDERS.map(p => {
        const t = _tokenFor(p);
        return <div key={p} className="litem">
          <span className="li-ic"><Icon name="key" /></span>
          <div className="li-main"><b style={{ textTransform: 'capitalize' }}>{p}</b><small style={{ fontFamily: 'var(--fm)' }}>{t ? 'configurado · ' + (t.updated_at || '').slice(0, 10) : 'não configurado'}</small></div>
          <Pill kind={t ? 'good' : 'warn'} dot>{t ? 'conectado' : 'configurar'}</Pill>
          <button className="btn sm ghost" disabled={savingFor === p} onClick={() => saveToken(p)}><Icon name="pen" />{savingFor === p ? '…' : ''}</button>
        </div>;
      })}
    </div>}
    {tab === 'sys' && <div className="stack">
      <div className="panel stack">
        <div className="sec">Plataforma</div>
        <div className="kv">
          <div className="row"><span className="k">Versão do MetaPorn OS</span><span className="v mono" style={{ color: 'var(--cyan)', fontWeight: 700 }}>{MP_OS_VERSION}</span></div>
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
