/* MetaPorn OS — Gestão de Agência: Criadores, Tendências, Financeiro, DMCA, Settings */

/* ── CRIADORES — cadastro, perfis e contas ── */
function CreatorsApp() {
  const [creators, setCreators] = React.useState([
    { n: 'Ana Estúdio', h: '@anaestudio', subs: '—', rev: '—', tone: 'good', st: 'ativo' },
    { n: 'Raposinha', h: '@raposinha', subs: '—', rev: '—', tone: 'good', st: 'ativo' },
  ]);
  React.useEffect(() => {
    if (window.mpApi) window.mpApi.listCreators().then(r => { if (r.length) setCreators(r); }).catch(() => {});
  }, []);
  return <div className="app">
    <AppHead icon="users" title="Gestão de Criadores" desc="Cadastro, perfis, contas e contratos dos criadores da agência."
      right={<button className="btn pri sm"><Icon name="plus" />Novo criador</button>} />
    <div className="grid3">
      <div className="stat"><div className="sv">4</div><div className="sl">Criadores ativos</div></div>
      <div className="stat"><div className="sv">72.2k</div><div className="sl">Assinantes totais</div></div>
      <div className="stat"><div className="sv">R$ 45.3k</div><div className="sl">Receita do mês</div><div className="sd">+18%</div></div>
    </div>
    <div className="stack">
      {creators.map(c => <div key={c.h} className="litem" style={{ padding: 14 }}>
        <div style={{ width: 48, height: 48, borderRadius: 14, background: 'linear-gradient(140deg,var(--pri),var(--pri2))', flex: 'none', display: 'grid', placeItems: 'center', fontFamily: 'var(--fh)', fontWeight: 700, fontSize: 18, color: '#fff' }}>{c.n[0]}</div>
        <div className="li-main"><b style={{ fontSize: 14 }}>{c.n}</b><small>{c.h} · {c.subs} assinantes</small></div>
        <div style={{ textAlign: 'right', marginRight: 8 }}><div style={{ fontFamily: 'var(--fh)', fontSize: 15, color: 'var(--good)' }}>{c.rev}</div><div style={{ fontSize: 11, color: 'var(--muted)' }}>mês</div></div>
        <Pill kind={c.tone} dot>{c.st}</Pill>
        <button className="btn sm ghost"><Icon name="chevR" /></button>
      </div>)}
    </div>
  </div>;
}

/* ── TENDÊNCIAS — radar e briefings ── */
function TrendsApp() {
  const [job, setJob] = React.useState(false);
  const [collecting, setCollecting] = React.useState(false);
  const [trends, setTrends] = React.useState([
    { t: 'Carregando tendências…', g: '—', tone: '' },
  ]);
  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.listTrends().then(r => {
      if (r.length) setTrends(r.map(b => ({
        t: b.summary || b.trend_keyword || 'Tendência',
        g: b.growth || '+—',
        tone: 'good',
        id: b.briefing_id || b.id,
      })));
      else setTrends([{ t: 'Nenhuma tendência coletada ainda', g: '—', tone: '' }]);
    }).catch(() => setTrends([{ t: 'Erro ao carregar', g: '—', tone: '' }]));
  }, []);
  return <div className="app">
    <AppHead icon="trending" title="Radar de Tendências" desc="Coleta tendências globais (XVideos/Pornhub) e gera briefings por criador com o Grok."
      right={<Pill kind="violet" icon="sparkles">Grok briefing</Pill>} />
    <div className="rowx">
      <button className="btn pri" onClick={() => {
        setCollecting(true);
        if (window.mpApi) window.mpApi.collectTrends()
          .then(() => window.mpApi.listTrends().then(r => { if (r.length) setTrends(r.map(b => ({ t: b.summary || b.trend_keyword || 'Tendência', g: b.growth || '+—', tone: 'good', id: b.briefing_id }))); }))
          .catch(() => {}).finally(() => setCollecting(false));
      }}><Icon name="refresh" />{collecting ? 'Coletando…' : 'Coletar Tendências Globais'}</button>
      <button className="btn ghost" onClick={() => {
        if (window.mpApi) window.mpApi.listTrends().then(r => { if (r.length) setTrends(r.map(b => ({ t: b.summary || b.trend_keyword || 'Tendência', g: b.growth || '+—', tone: 'good', id: b.briefing_id }))); });
      }}><Icon name="list" />Atualizar Lista</button>
    </div>
    <div className="split">
      <div className="stack">
        <div className="sec mut"><Icon name="trending" />Em alta esta semana</div>
        {trends.map((t, i) => <div key={i} className="litem">
          <span className="li-ic"><Icon name="trending" /></span>
          <div className="li-main"><b>{t.t}</b></div>
          <Pill kind={t.tone} dot>{t.g}</Pill>
        </div>)}
      </div>
      <div className="stack">
        <div className="panel stack">
          <div className="sec">Gerar briefing por criador</div>
          <Field label="Criador"><select className="inp"><option>Ana Estúdio</option><option>Raposinha</option><option>Estúdio X</option></select></Field>
          <div className="rowx"><button className="btn sm"><Icon name="broadcast" />Coletar Canais</button><button className="btn pri sm" onClick={() => setJob(true)}><Icon name="sparkles" />Gerar Briefing</button></div>
        </div>
        {job && <div className="panel stack">
          <LogLines items={[
            { s: 'done', t: 'Canais do criador coletados (XVideos + Pornhub)' },
            { s: 'done', t: 'Categoria dominante: anal / amador' },
            { s: 'now', t: 'Grok gerando sugestões de conteúdo…' },
          ]} />
          <div className="rowx"><button className="btn pri sm" style={{ background: 'var(--good)', borderColor: 'var(--good)' }}><Icon name="check" />Aprovar e Notificar</button><button className="btn sm ghost"><Icon name="eye" />Aprovar sem notificar</button></div>
        </div>}
      </div>
    </div>
  </div>;
}

/* ── FINANCEIRO ── */
function FinancialApp() {
  const [tab, setTab] = React.useState('agency');
  return <div className="app">
    <AppHead icon="dollar" title="Financeiro" desc="Receita, payout e visão da agência — por plataforma e por criador." />
    <div className="tabbar">
      {[['agency', '🏢 Visão da Agência'], ['creator', '📊 Por Criador'], ['add', '+ Lançar Receita']].map(([k, l]) =>
        <button key={k} className={'tabx' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}
    </div>
    {tab === 'agency' && <div className="stack">
      <div className="grid3">
        <div className="stat"><div className="sv">R$ 45.3k</div><div className="sl">Receita bruta (mês)</div><div className="sd">+18% vs maio</div></div>
        <div className="stat"><div className="sv">R$ 31.7k</div><div className="sl">Líquido pós-taxas</div></div>
        <div className="stat"><div className="sv">R$ 13.6k</div><div className="sl">Comissão agência</div></div>
      </div>
      <div className="panel stack">
        <div className="sec mut"><Icon name="dollar" />Receita por plataforma</div>
        {[['XVideos', 72, 'R$ 22.4k'], ['Pornhub', 48, 'R$ 14.9k'], ['Telegram VIP', 26, 'R$ 6.1k'], ['OnlyFans', 8, 'R$ 1.9k']].map(([n, w, v]) => <div key={n}>
          <div className="rowx" style={{ justifyContent: 'space-between', marginBottom: 5 }}><span style={{ fontSize: 13 }}>{n}</span><b style={{ fontFamily: 'var(--fh)', fontSize: 13 }}>{v}</b></div>
          <div className="track gd"><i style={{ width: w + '%' }} /></div>
        </div>)}
      </div>
    </div>}
    {tab === 'creator' && <div className="stack">
      <div className="rowx"><select className="inp" style={{ flex: 1 }}><option>Raposinha</option><option>Ana Estúdio</option></select><input className="inp" type="month" style={{ width: 160 }} defaultValue="2026-06" /><button className="btn pri">Ver</button></div>
      <div className="grid3">
        <div className="stat"><div className="sv">R$ 21.6k</div><div className="sl">Receita bruta</div></div>
        <div className="stat"><div className="sv">R$ 15.1k</div><div className="sl">Payout criador</div></div>
        <div className="stat"><div className="sv">2.4M</div><div className="sl">Views no período</div></div>
      </div>
      <div className="panel"><div className="sec mut" style={{ marginBottom: 10 }}>Receita · 6 meses</div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, height: 120 }}>
          {[55, 62, 70, 58, 82, 95].map((h, i) => <div key={i} style={{ flex: 1, height: h + '%', borderRadius: '6px 6px 0 0', background: i === 5 ? 'var(--good)' : 'rgba(255,255,255,.1)' }} />)}
        </div>
      </div>
    </div>}
    {tab === 'add' && <div className="panel stack">
      <div className="grid2">
        <Field label="Criador"><select className="inp"><option>Ana Estúdio</option><option>Raposinha</option></select></Field>
        <Field label="Plataforma"><input className="inp" defaultValue="xvideos" /></Field>
        <Field label="Período"><input className="inp" type="month" defaultValue="2026-06" /></Field>
        <Field label="Receita bruta (R$)"><input className="inp" type="number" defaultValue="0" /></Field>
        <Field label="Taxa da plataforma (%)"><input className="inp" type="number" defaultValue="20" /></Field>
        <Field label="Views no período"><input className="inp" type="number" defaultValue="0" /></Field>
      </div>
      <button className="btn pri" style={{ alignSelf: 'flex-start' }}><Icon name="check" />Salvar lançamento</button>
    </div>}
  </div>;
}

/* ── DMCA — monitoramento e proteção ── */
function DmcaApp() {
  const [scanning, setScanning] = React.useState(false);
  const [infr, setInfr] = React.useState([
    { url: 'pirata-tube.xyz/v/8f2a', c: 'Ana Estúdio', s: 'takedown enviado', tone: 'good', d: 'há 2 d' },
    { url: 'leak-site.net/clip/2241', c: 'Raposinha', s: 'detectado', tone: 'pri', d: 'hoje' },
  ]);
  React.useEffect(() => {
    if (window.mpApi) window.mpApi.listDmca().then(r => { if (r.length) setInfr(r); }).catch(() => {});
  }, []);
  return <div className="app">
    <AppHead icon="shield" title="Proteção DMCA" desc="Escaneia a web por pirataria do conteúdo dos criadores e dispara takedowns."
      right={<Pill kind="good" dot>monitorando</Pill>} />
    <div className="grid3">
      <div className="stat"><div className="sv">142</div><div className="sl">URLs monitoradas</div></div>
      <div className="stat"><div className="sv">8</div><div className="sl">Infrações ativas</div><div className="sd" style={{ color: 'var(--pri)' }}>2 novas hoje</div></div>
      <div className="stat"><div className="sv">96%</div><div className="sl">Taxa de remoção</div></div>
    </div>
    <div className="panel stack">
      <div className="sec">Escanear por pirataria</div>
      <div className="rowx"><select className="inp" style={{ flex: 1 }}><option>Todos os criadores</option><option>Ana Estúdio</option><option>Raposinha</option></select>
        <button className="btn pri" onClick={() => { setScanning(true); setTimeout(() => setScanning(false), 2600); }}><Icon name="shieldscan" />Escanear Agora</button></div>
      {scanning && <ProgressBar pct={58} tone="cy" label="Varrendo a web" eta="≈ 30 s · 84 / 142 fontes" />}
    </div>
    <div className="stack">
      <div className="sec mut"><Icon name="warning" />Infrações</div>
      {infr.map((x, i) => <div key={i} className="litem">
        <span className="li-ic" style={{ color: x.tone === 'pri' ? 'var(--pri)' : 'var(--good)' }}><Icon name="warning" /></span>
        <div className="li-main"><b style={{ fontFamily: 'var(--fm)', fontSize: 12.5 }}>{x.url}</b><small>{x.c} · {x.d}</small></div>
        <Pill kind={x.tone} dot>{x.s}</Pill>
        {x.tone === 'pri' && <button className="btn sm pri"><Icon name="shield" />Takedown</button>}
      </div>)}
    </div>
  </div>;
}

/* ── SETTINGS — tokens, usuários e sistema ── */
function SettingsApp() {
  const [tab, setTab] = React.useState('tokens');
  return <div className="app">
    <AppHead icon="settings" title="Settings" desc="Tokens de IA, integrações, usuários e preferências do sistema." />
    <div className="tabbar">
      {[['tokens', 'Tokens & IA'], ['integr', 'Integrações'], ['users', 'Usuários'], ['prefs', 'Preferências']].map(([k, l]) =>
        <button key={k} className={'tabx' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}
    </div>
    {tab === 'tokens' && <div className="stack">
      {[
        { n: 'xAI / Grok', k: 'xai-••••••••4f2a', ok: true }, { n: 'OpenAI', k: 'sk-••••••••e91c', ok: true },
        { n: 'Anthropic', k: 'sk-ant-••••2b7d', ok: true }, { n: 'AssemblyAI', k: '••••••••91ac', ok: true },
        { n: 'Google Gemini', k: 'não configurado', ok: false }, { n: 'OpenRouter', k: 'or-••••••5c3e', ok: true },
      ].map((t, i) => <div key={i} className="litem">
        <span className="li-ic"><Icon name="key" /></span>
        <div className="li-main"><b>{t.n}</b><small style={{ fontFamily: 'var(--fm)' }}>{t.k}</small></div>
        <Pill kind={t.ok ? 'good' : 'warn'} dot>{t.ok ? 'conectado' : 'configurar'}</Pill>
        <button className="btn sm ghost"><Icon name="pen" /></button>
      </div>)}
      <button className="btn"><Icon name="plus" />Adicionar provedor</button>
    </div>}
    {tab === 'integr' && <div className="stack">
      {[['Telegram Bot', 'telegram', true], ['MinIO / S3', 'layers', true], ['XVideos (referências)', 'globe', true], ['FFmpeg', 'autoeditor', true], ['Webhook DMCA', 'shield', false]].map(([n, ic, ok], i) =>
        <div key={i} className="litem"><span className="li-ic"><Icon name={ic} /></span><div className="li-main"><b>{n}</b><small>{ok ? 'ativa' : 'desativado'}</small></div><Switch on={ok} /></div>)}
    </div>}
    {tab === 'users' && <div className="stack">
      {[['mikael (admin)', 'Admin', 'good'], ['operador1', 'Operador', ''], ['editora_ana', 'Editor', '']].map(([n, r, t], i) =>
        <div key={i} className="litem"><span className="li-ic"><Icon name="portal" /></span><div className="li-main"><b>{n}</b><small>{r}</small></div><Pill kind={t} dot>{r}</Pill></div>)}
      <button className="btn"><Icon name="plus" />Convidar usuário</button>
    </div>}
    {tab === 'prefs' && <div className="stack">
      {[['Tema escuro', true], ['Notificações desktop', true], ['Tour ao abrir apps novos', true], ['Som ao concluir tarefa', false], ['Excluir original após AutoEditor', false]].map(([n, on], i) =>
        <div key={i} className="litem"><div className="li-main"><b>{n}</b></div><Switch on={on} /></div>)}
      <Field label="Idioma"><select className="inp"><option>Português (BR)</option><option>English</option></select></Field>
    </div>}
  </div>;
}

Object.assign(window, { CreatorsApp, TrendsApp, FinancialApp, DmcaApp, SettingsApp });
