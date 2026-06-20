/* Caripost OS — Clientes, Central de Aprovação, Concorrentes */

/* ── CLIENTES ── */
function ClientesApp() {
  const [companies, setCompanies] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [creating, setCreating] = React.useState(false);
  const [selectedId, setSelectedId] = React.useState(null);

  const load = React.useCallback(() => {
    setLoading(true);
    window.mpApi.listCompanies().then(r => { setCompanies(r); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  React.useEffect(() => { if (window.mpApi) load(); }, [load]);

  return <div className="app">
    <AppHead icon="building" title="Clientes" desc="Empresas com comunicação padronizada e pronta para escala."
      right={<button className="btn sm pri" onClick={() => { setCreating(c => !c); setSelectedId(null); }}><Icon name="plus" />Novo cliente</button>} />
    <div className="grid3">
      <div className="stat"><div className="sv">{companies.length}</div><div className="sl">Empresas</div></div>
      <div className="stat"><div className="sv">{companies.filter(c => c.active).length}</div><div className="sl">Ativas</div></div>
      <div className="stat"><div className="sv">{companies.reduce((s, c) => s + (c.post_count || 0), 0)}</div><div className="sl">Posts</div></div>
    </div>

    {creating && <CompanyForm onSaved={() => { setCreating(false); load(); }} onCancel={() => setCreating(false)} />}

    <div className="stack">
      {loading && <div className="hint">Carregando empresas…</div>}
      {!loading && !companies.length && <div className="hint">Nenhuma empresa cadastrada.</div>}
      {companies.map(c => <React.Fragment key={c.id}>
        <div className="litem" style={{ padding: 14, cursor: 'pointer', borderColor: selectedId === c.id ? 'var(--cyan)' : undefined }}
          onClick={() => { setSelectedId(id => id === c.id ? null : c.id); setCreating(false); }}>
          <div style={{ width: 48, height: 48, borderRadius: 14, background: 'linear-gradient(140deg,var(--pri),var(--pri2))', flex: 'none', display: 'grid', placeItems: 'center', fontFamily: 'var(--fh)', fontWeight: 700, fontSize: 18, color: '#fff' }}>{(c.name || '?')[0]}</div>
          <div className="li-main"><b style={{ fontSize: 14 }}>{c.name}</b><small>{c.segment || 'Sem segmento'} · {c.post_count || 0} posts</small></div>
          <Pill kind={c.active ? 'good' : 'warn'} dot>{c.active ? 'Ativo' : 'Inativo'}</Pill>
        </div>
        {selectedId === c.id && <CompanyDetail companyId={c.id} onSaved={load} onDeleted={() => { setSelectedId(null); load(); }} />}
      </React.Fragment>)}
    </div>
  </div>;
}

function CompanyForm({ onSaved, onCancel }) {
  const [name, setName] = React.useState('');
  const [segment, setSegment] = React.useState('');
  const [website, setWebsite] = React.useState('');
  const [city, setCity] = React.useState('');
  const [state, setState] = React.useState('');
  const [phone, setPhone] = React.useState('');
  const [email, setEmail] = React.useState('');
  const [competitors, setCompetitors] = React.useState([{ name: '', instagram: '', website: '' }]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  async function save() {
    if (!name) { setError('Nome é obrigatório.'); return; }
    setSaving(true); setError('');
    try {
      const comps = competitors.filter(c => c.name).map(c => ({ name: c.name, instagram: c.instagram || null, website: c.website || null }));
      await window.mpApi.createCompany({
        name, segment: segment || null, website: website || null,
        city: city || null, state: state || null, phone: phone || null, email: email || null,
        competitors: comps,
      });
      onSaved();
    } catch (e) { setError(e.message || 'Erro ao criar empresa.'); }
    finally { setSaving(false); }
  }

  return <div className="panel stack">
    <div className="sec cy"><Icon name="plus" />Novo cliente</div>
    <div className="split">
      <div className="stack">
        <Field label="Nome *"><input className="inp" value={name} onChange={e => setName(e.target.value)} placeholder="Ex: IBIUNET" /></Field>
        <Field label="Segmento"><input className="inp" value={segment} onChange={e => setSegment(e.target.value)} placeholder="Ex: Telecom" /></Field>
        <Field label="Website"><input className="inp" value={website} onChange={e => setWebsite(e.target.value)} placeholder="https://" /></Field>
        <Field label="Cidade"><input className="inp" value={city} onChange={e => setCity(e.target.value)} /></Field>
      </div>
      <div className="stack">
        <Field label="Estado"><input className="inp" value={state} onChange={e => setState(e.target.value)} placeholder="SP" /></Field>
        <Field label="Telefone"><input className="inp" value={phone} onChange={e => setPhone(e.target.value)} placeholder="(11) 99999-9999" /></Field>
        <Field label="Email"><input className="inp" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="contato@empresa.com" /></Field>
      </div>
    </div>
    <div className="sec mut">Concorrentes (opcional)</div>
    {competitors.map((c, i) => <div key={i} className="split" style={{ gap: 8 }}>
      <input className="inp" placeholder="Nome" value={c.name} onChange={e => { const a = [...competitors]; a[i].name = e.target.value; setCompetitors(a); }} />
      <input className="inp" placeholder="@instagram" value={c.instagram} onChange={e => { const a = [...competitors]; a[i].instagram = e.target.value; setCompetitors(a); }} />
      <input className="inp" placeholder="https://" value={c.website} onChange={e => { const a = [...competitors]; a[i].website = e.target.value; setCompetitors(a); }} />
      <button className="btn sm ghost" onClick={() => setCompetitors(competitors.filter((_, j) => j !== i))}><Icon name="x" /></button>
    </div>)}
    <button className="btn sm ghost" onClick={() => setCompetitors([...competitors, { name: '', instagram: '', website: '' }])}><Icon name="plus" />Adicionar concorrente</button>
    {error && <div className="err">{error}</div>}
    <div className="row" style={{ gap: 8 }}>
      <button className="btn sm pri" disabled={saving} onClick={save}>{saving ? 'Salvando…' : 'Cadastrar empresa'}</button>
      <button className="btn sm ghost" onClick={onCancel}>Cancelar</button>
    </div>
  </div>;
}

function CompanyDetail({ companyId, onSaved, onDeleted }) {
  const [company, setCompany] = React.useState(null);
  const [tab, setTab] = React.useState('fluxo');
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(() => {
    setLoading(true);
    window.mpApi.getCompany(companyId).then(c => { setCompany(c); setLoading(false); }).catch(() => setLoading(false));
  }, [companyId]);

  React.useEffect(() => { load(); }, [load]);

  if (loading) return <div className="panel"><div className="hint">Carregando…</div></div>;
  if (!company) return null;

  const tabs = [['fluxo', 'Fluxo'], ['geral', 'Dados Gerais'], ['visual', 'Identidade Visual'], ['voz', 'Voz & Persona'], ['concorrentes', 'Concorrentes'], ['gerar', 'Gerar Conteúdo']];

  return <div className="panel stack">
    <div className="tabbar">
      {tabs.map(([k, l]) => <button key={k} className={'tabx' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}
    </div>
    {tab === 'fluxo' && <CompanyFluxo company={company} onSaved={load} />}
    {tab === 'geral' && <CompanyGeral company={company} onSaved={load} />}
    {tab === 'visual' && <CompanyVisual company={company} onSaved={load} />}
    {tab === 'voz' && <CompanyVoz company={company} onSaved={load} />}
    {tab === 'concorrentes' && <CompanyConcorrentes company={company} onSaved={load} />}
    {tab === 'gerar' && <CompanyGerar company={company} />}
  </div>;
}

function CompanyFluxo({ company, onSaved }) {
  const [workspace, setWorkspace] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [instagram, setInstagram] = React.useState((company.socials || {}).instagram || '');
  const [compName, setCompName] = React.useState('');
  const [compIg, setCompIg] = React.useState('');

  const load = React.useCallback(() => {
    setLoading(true);
    window.mpApi.socialWorkspace(company.id)
      .then(r => { setWorkspace(r); setLoading(false); })
      .catch(e => { setMsg('Erro: ' + e.message); setLoading(false); });
  }, [company.id]);

  React.useEffect(() => { if (window.mpApi) load(); }, [load]);

  const accounts = workspace?.accounts || [];
  const competitors = workspace?.competitors || company.competitors || [];
  const report = workspace?.strategy || null;
  const strategy = report?.payload?.strategy || null;
  const ideas = strategy?.post_ideas || [];
  const identity = strategy?.brand_identity || {};

  async function saveInstagram() {
    setBusy(true); setMsg('');
    try {
      await window.mpApi.updateCompany(company.id, { socials: { ...(company.socials || {}), instagram } });
      setMsg('Instagram da empresa salvo.');
      onSaved();
      load();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }

  async function connect(platform) {
    setBusy(true); setMsg('Abrindo conexão ' + platform + '...');
    try {
      const callbackUrl = window.location.origin + '/api/social/callback';
      const r = await window.mpApi.socialConnect({ brandId: company.id, platform, callbackUrl });
      if (r.redirect_url) window.open(r.redirect_url, '_blank', 'noopener,noreferrer');
      setMsg(r.redirect_url ? 'Autorize na aba aberta e depois clique em Atualizar.' : 'Conexão registrada.');
      setTimeout(load, 1200);
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }

  async function addCompetitor() {
    if (!compName.trim()) { setMsg('Informe o nome do concorrente.'); return; }
    setBusy(true); setMsg('');
    try {
      await window.mpApi.socialAddCompetitor({ brandId: company.id, name: compName.trim(), instagram: compIg.trim() });
      setCompName(''); setCompIg('');
      setMsg('Concorrente adicionado.');
      onSaved();
      load();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }

  async function analyze() {
    setBusy(true); setMsg('Analisando Instagram, concorrentes e referências...');
    try {
      await window.mpApi.socialAnalyzeBrand(company.id, { instagram, applyBrandKit: true });
      setMsg('Análise pronta. Identidade, ideias e prompts foram atualizados.');
      onSaved();
      load();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }

  async function generateDrafts() {
    setBusy(true); setMsg('Criando posts para aprovação...');
    try {
      const r = await window.mpApi.socialGenerateDrafts(company.id, { count: 4 });
      setMsg(`${(r.created || []).length} posts enviados para aprovação.`);
      load();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }

  return <div className="stack">
    <div className="grid3">
      <div className="stat"><div className="sv">{instagram ? '1' : '0'}</div><div className="sl">Instagram da empresa</div></div>
      <div className="stat"><div className="sv">{accounts.filter(a => a.status === 'connected' || a.status === 'active').length}</div><div className="sl">Canais conectados</div></div>
      <div className="stat"><div className="sv">{competitors.length}</div><div className="sl">Concorrentes</div></div>
    </div>

    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    {loading && <div className="hint">Carregando fluxo...</div>}

    <div className="split">
      <div className="panel stack">
        <div className="sec cy"><Icon name="building" />1. Perfil social da empresa</div>
        <Field label="Instagram oficial">
          <input className="inp" value={instagram} onChange={e => setInstagram(e.target.value)} placeholder="@empresa ou URL do Instagram" />
        </Field>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <button className="btn sm pri" disabled={busy} onClick={saveInstagram}>Salvar Instagram</button>
          <button className="btn sm" disabled={busy} onClick={() => connect('instagram')}><Icon name="link" />Conectar Instagram</button>
          <button className="btn sm ghost" disabled={busy} onClick={load}>Atualizar</button>
        </div>
        {accounts.length ? accounts.map(acc => <div key={acc.id} className="litem" style={{ padding: 10 }}>
          <span className="li-ic"><Icon name="broadcast" /></span>
          <div className="li-main"><b style={{ textTransform: 'capitalize' }}>{acc.platform}</b><small>{acc.external_account_name || acc.external_account_id || 'Composio'}</small></div>
          <Pill kind={acc.status === 'connected' || acc.status === 'active' ? 'good' : 'warn'} dot>{acc.status}</Pill>
        </div>) : <div className="hint">Conecte o Instagram pela autorização oficial do Composio. Não é token manual.</div>}
      </div>

      <div className="panel stack">
        <div className="sec mut"><Icon name="radar" />2. Concorrentes e referências</div>
        <div className="split" style={{ gap: 8 }}>
          <input className="inp" value={compName} onChange={e => setCompName(e.target.value)} placeholder="Nome do concorrente" />
          <input className="inp" value={compIg} onChange={e => setCompIg(e.target.value)} placeholder="@instagram ou URL" />
        </div>
        <button className="btn sm" disabled={busy} onClick={addCompetitor}><Icon name="plus" />Adicionar concorrente</button>
        {competitors.slice(0, 6).map(c => {
          const h = c.handles || {};
          return <div key={c.id} className="litem" style={{ padding: 10 }}>
            <div className="li-main"><b>{c.name}</b><small>{h.instagram || h.website || 'sem perfil social'}</small></div>
          </div>;
        })}
      </div>
    </div>

    <div className="panel stack">
      <div className="row" style={{ justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
        <div>
          <div className="sec pri" style={{ margin: 0 }}><Icon name="sparkles" />3. Análise automática</div>
          <div className="hint" style={{ marginTop: 6 }}>A IA cruza perfil da empresa, concorrentes, referências e gera identidade, pilares, ideias e prompts de arte.</div>
        </div>
        <button className="btn pri" disabled={busy} onClick={analyze}>{busy ? 'Rodando...' : 'Analisar e gerar estratégia'}</button>
      </div>

      {strategy && <div className="split">
        <div className="stack">
          <div className="sec mut">Identidade sugerida</div>
          <div className="hint">{strategy.summary}</div>
          {identity.positioning && <div className="row"><span className="k">Posicionamento</span><span className="v">{identity.positioning}</span></div>}
          {identity.voice && <div className="row"><span className="k">Voz</span><span className="v">{identity.voice}</span></div>}
          {identity.visual_prompt_base && <div className="panel" style={{ fontSize: 12 }}>{identity.visual_prompt_base}</div>}
        </div>
        <div className="stack">
          <div className="sec mut">Pilares</div>
          {(strategy.content_pillars || []).slice(0, 5).map((p, i) => <div key={i} className="litem" style={{ padding: 10 }}>
            <div className="li-main"><b>{p.name}</b><small>{p.angle}</small></div>
          </div>)}
        </div>
      </div>}
    </div>

    {ideas.length > 0 && <div className="panel stack">
      <div className="row" style={{ justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
        <div className="sec cy" style={{ margin: 0 }}><Icon name="image" />4. Ideias e prompts de arte</div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn sm pri" disabled={busy} onClick={generateDrafts}>Criar 4 posts para aprovação</button>
          <button className="btn sm" onClick={() => window.__mpOpen && window.__mpOpen('aprovacao')}>Abrir aprovação</button>
        </div>
      </div>
      <div className="grid2">
        {ideas.slice(0, 8).map((idea, i) => <div key={i} className="litem" style={{ alignItems: 'flex-start' }}>
          <span className="li-ic"><Icon name="sparkles" /></span>
          <div className="li-main">
            <b>{idea.title || 'Ideia de post'}</b>
            <small>{idea.format || 'post'} · {idea.network || 'instagram'} · {idea.why || ''}</small>
            {idea.visual_prompt && <div className="hint" style={{ marginTop: 8 }}>{idea.visual_prompt}</div>}
          </div>
        </div>)}
      </div>
    </div>}

    <div className="panel stack">
      <div className="sec mut"><Icon name="calendar" />5. Aprovar, produzir e agendar</div>
      <div className="grid3">
        <button className="btn" onClick={() => window.__mpOpen && window.__mpOpen('aprovacao')}><Icon name="shield" />Aprovar posts</button>
        <button className="btn" onClick={() => window.__mpOpen && window.__mpOpen('criacao')}><Icon name="image" />Criar arte/mídia</button>
        <button className="btn" onClick={() => window.__mpOpen && window.__mpOpen('publisher')}><Icon name="broadcast" />Publicar/agendar</button>
      </div>
    </div>
  </div>;
}

function CompanyGeral({ company, onSaved }) {
  const [name, setName] = React.useState(company.name || '');
  const [segment, setSegment] = React.useState(company.segment || '');
  const [website, setWebsite] = React.useState(company.website || '');
  const [email, setEmail] = React.useState(company.email || '');
  const [city, setCity] = React.useState(company.city || '');
  const [state, setState] = React.useState(company.state || '');
  const [phone, setPhone] = React.useState(company.phone || '');
  const socials = company.socials || {};
  const [ig, setIg] = React.useState(socials.instagram || '');
  const [fb, setFb] = React.useState(socials.facebook || '');
  const [tt, setTt] = React.useState(socials.tiktok || '');
  const [msg, setMsg] = React.useState('');
  const [saving, setSaving] = React.useState(false);

  async function save() {
    setSaving(true); setMsg('');
    try {
      await window.mpApi.updateCompany(company.id, {
        name, segment: segment || null, website: website || null, email: email || null,
        city: city || null, state: state || null, phone: phone || null,
        social_instagram: ig, social_facebook: fb, social_tiktok: tt,
      });
      setMsg('Salvo!'); onSaved();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setSaving(false); }
  }

  return <div className="stack">
    <div className="split">
      <Field label="Nome"><input className="inp" value={name} onChange={e => setName(e.target.value)} /></Field>
      <Field label="Segmento"><input className="inp" value={segment} onChange={e => setSegment(e.target.value)} placeholder="Ex: Saúde, Educação" /></Field>
    </div>
    <div className="split">
      <Field label="Website"><input className="inp" value={website} onChange={e => setWebsite(e.target.value)} /></Field>
      <Field label="Email"><input className="inp" value={email} onChange={e => setEmail(e.target.value)} /></Field>
    </div>
    <div className="split">
      <Field label="Cidade"><input className="inp" value={city} onChange={e => setCity(e.target.value)} /></Field>
      <Field label="Estado"><input className="inp" value={state} onChange={e => setState(e.target.value)} placeholder="SP" /></Field>
    </div>
    <Field label="Telefone"><input className="inp" value={phone} onChange={e => setPhone(e.target.value)} placeholder="(11) 99999-9999" /></Field>
    <div className="sec mut">Redes sociais</div>
    <div className="split">
      <Field label="Instagram"><input className="inp" value={ig} onChange={e => setIg(e.target.value)} placeholder="@usuario" /></Field>
      <Field label="Facebook"><input className="inp" value={fb} onChange={e => setFb(e.target.value)} /></Field>
    </div>
    <Field label="TikTok"><input className="inp" value={tt} onChange={e => setTt(e.target.value)} /></Field>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <button className="btn sm pri" disabled={saving} onClick={save}>{saving ? 'Salvando…' : 'Salvar'}</button>
  </div>;
}

function CompanyVisual({ company, onSaved }) {
  const bk = company.brand_kit || {};
  const colors = bk.colors || {};
  const [primary, setPrimary] = React.useState(colors.primary || '#123d8f');
  const [secondary, setSecondary] = React.useState(colors.secondary || '#fe6601');
  const [accent, setAccent] = React.useState(colors.accent || '#14b7f0');
  const [msg, setMsg] = React.useState('');
  const refs = company.references || [];

  async function saveColors() {
    setMsg('');
    try {
      await window.mpApi.saveBrandKit(company.id, { primaryColor: primary, secondaryColor: secondary, accentColor: accent });
      setMsg('Cores salvas!'); onSaved();
    } catch (e) { setMsg('Erro: ' + e.message); }
  }

  async function doUploadLogo(file) {
    try { await window.mpApi.uploadLogo(company.id, file); onSaved(); } catch (e) { setMsg('Erro: ' + e.message); }
  }

  async function doUploadRef(file) {
    try { await window.mpApi.uploadReference(company.id, file); onSaved(); } catch (e) { setMsg('Erro: ' + e.message); }
  }

  async function doDeleteRef(assetId) {
    try { await window.mpApi.deleteReference(company.id, assetId); onSaved(); } catch (e) { setMsg('Erro: ' + e.message); }
  }

  return <div className="stack">
    <div className="sec">Logo da marca</div>
    <div className="row" style={{ gap: 16, alignItems: 'center' }}>
      {bk.logo_url ? <img src={bk.logo_url} style={{ maxHeight: 80, maxWidth: 200, borderRadius: 8, border: '1px solid var(--line)' }} /> : <div className="hint">Sem logo</div>}
      <input type="file" accept="image/*" onChange={e => e.target.files[0] && doUploadLogo(e.target.files[0])} />
    </div>
    <div className="sec">Paleta de cores</div>
    <div className="split">
      <Field label="Primária"><div className="row" style={{ gap: 8, alignItems: 'center' }}><input type="color" value={primary} onChange={e => setPrimary(e.target.value)} style={{ width: 50, height: 40, border: 'none', background: 'none', cursor: 'pointer' }} /><span className="mono" style={{ fontSize: 12 }}>{primary}</span></div></Field>
      <Field label="Secundária"><div className="row" style={{ gap: 8, alignItems: 'center' }}><input type="color" value={secondary} onChange={e => setSecondary(e.target.value)} style={{ width: 50, height: 40, border: 'none', background: 'none', cursor: 'pointer' }} /><span className="mono" style={{ fontSize: 12 }}>{secondary}</span></div></Field>
    </div>
    <Field label="Destaque"><div className="row" style={{ gap: 8, alignItems: 'center' }}><input type="color" value={accent} onChange={e => setAccent(e.target.value)} style={{ width: 50, height: 40, border: 'none', background: 'none', cursor: 'pointer' }} /><span className="mono" style={{ fontSize: 12 }}>{accent}</span></div></Field>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <button className="btn sm pri" onClick={saveColors}>Salvar cores</button>
    <div className="sec">Mood board</div>
    <input type="file" accept="image/*" onChange={e => e.target.files[0] && doUploadRef(e.target.files[0])} />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: 12 }}>
      {refs.map(r => <div key={r.id} style={{ position: 'relative' }}>
        <img src={r.url} style={{ width: '100%', height: 100, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--line)' }} />
        <button onClick={() => doDeleteRef(r.id)} style={{ position: 'absolute', top: 4, right: 4, background: 'rgba(0,0,0,.7)', color: '#fff', border: 'none', borderRadius: 4, padding: '2px 6px', cursor: 'pointer', fontSize: 12 }}>✕</button>
      </div>)}
    </div>
  </div>;
}

function CompanyVoz({ company, onSaved }) {
  const bk = company.brand_kit || {};
  const [voice, setVoice] = React.useState(bk.voice || '');
  const [persona, setPersona] = React.useState(bk.persona || '');
  const [visual, setVisual] = React.useState(bk.visual_prompt_base || '');
  const [msg, setMsg] = React.useState('');
  const [saving, setSaving] = React.useState(false);

  async function save() {
    setSaving(true); setMsg('');
    try {
      await window.mpApi.saveBrandKit(company.id, { voice, persona, visual_prompt_base: visual });
      setMsg('Salvo!'); onSaved();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setSaving(false); }
  }

  return <div className="stack">
    <Field label="Tom de voz"><input className="inp" value={voice} onChange={e => setVoice(e.target.value)} placeholder="Ex: próximo, confiante, sem jargão técnico" /></Field>
    <Field label="Persona da marca"><textarea className="inp" rows={4} value={persona} onChange={e => setPersona(e.target.value)} placeholder="Descreva a persona..." style={{ resize: 'vertical' }} /></Field>
    <Field label="Base para prompt visual"><textarea className="inp" rows={3} value={visual} onChange={e => setVisual(e.target.value)} placeholder="Ex: fundo branco, produto em destaque" style={{ resize: 'vertical' }} /></Field>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <button className="btn sm pri" disabled={saving} onClick={save}>{saving ? 'Salvando…' : 'Salvar'}</button>
  </div>;
}

function CompanyConcorrentes({ company, onSaved }) {
  const comps = company.competitors || [];
  const [name, setName] = React.useState('');
  const [ig, setIg] = React.useState('');
  const [site, setSite] = React.useState('');
  const [msg, setMsg] = React.useState('');

  async function add() {
    if (!name) { setMsg('Nome é obrigatório'); return; }
    setMsg('');
    try {
      await window.mpApi.addCompetitor(company.id, { name, instagram: ig || null, website: site || null });
      setName(''); setIg(''); setSite(''); onSaved();
    } catch (e) { setMsg('Erro: ' + e.message); }
  }

  async function remove(id) {
    try { await window.mpApi.removeCompetitor(company.id, id); onSaved(); } catch (e) { setMsg('Erro: ' + e.message); }
  }

  return <div className="stack">
    {comps.map(c => {
      const h = c.handles || {};
      return <div key={c.id} className="litem" style={{ padding: 12 }}>
        <div className="li-main"><b>{c.name}</b><small>{h.instagram || ''} {h.website || ''}</small></div>
        <button className="btn sm ghost" onClick={() => remove(c.id)}><Icon name="x" /></button>
      </div>;
    })}
    {!comps.length && <div className="hint">Nenhum concorrente cadastrado.</div>}
    <div className="sec mut">Adicionar concorrente</div>
    <div className="split" style={{ gap: 8 }}>
      <input className="inp" placeholder="Nome *" value={name} onChange={e => setName(e.target.value)} />
      <input className="inp" placeholder="@instagram" value={ig} onChange={e => setIg(e.target.value)} />
      <input className="inp" placeholder="https://" value={site} onChange={e => setSite(e.target.value)} />
    </div>
    {msg && <div className="err">{msg}</div>}
    <button className="btn sm pri" onClick={add}>Adicionar</button>
  </div>;
}

function CompanyGerar({ company }) {
  const [briefing, setBriefing] = React.useState('');
  const [title, setTitle] = React.useState('');
  const [copy, setCopy] = React.useState('');
  const [hashtags, setHashtags] = React.useState('');
  const [networks, setNetworks] = React.useState(['instagram']);
  const [scheduledAt, setScheduledAt] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [aiMsg, setAiMsg] = React.useState('');
  const [generating, setGenerating] = React.useState(false);
  const [saving, setSaving] = React.useState(false);

  const NETS = ['instagram', 'facebook', 'tiktok', 'youtube', 'linkedin', 'x'];

  async function generateAI() {
    if (!briefing) { setAiMsg('Digite um briefing'); return; }
    setGenerating(true); setAiMsg('Gerando…');
    try {
      const g = await window.mpApi.generatePostAI({ company_id: company.id, briefing, networks });
      setTitle(g.title || ''); setCopy(g.copy || ''); setHashtags(g.hashtags || '');
      setAiMsg('Copy gerada!');
    } catch (e) { setAiMsg('Erro: ' + e.message); }
    finally { setGenerating(false); }
  }

  async function createPost(intent) {
    if (!copy) { setMsg('Copy é obrigatória'); return; }
    setSaving(true); setMsg('');
    try {
      await window.mpApi.createPost({
        company_id: company.id, title, copy, hashtags,
        networks, scheduled_at: scheduledAt || null, intent,
      });
      setMsg(intent === 'review' ? 'Enviado para aprovação!' : 'Rascunho salvo!');
      setTitle(''); setCopy(''); setHashtags('');
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setSaving(false); }
  }

  return <div className="stack">
    <div className="panel stack" style={{ borderColor: 'var(--pri)' }}>
      <div className="sec pri"><Icon name="sparkles" />Gerar com IA</div>
      <textarea className="inp" rows={3} value={briefing} onChange={e => setBriefing(e.target.value)} placeholder="Briefing: o que esse post precisa comunicar?" style={{ resize: 'vertical' }} />
      {aiMsg && <div className={aiMsg.startsWith('Erro') ? 'err' : 'ok'}>{aiMsg}</div>}
      <button className="btn sm pri" disabled={generating} onClick={generateAI}>{generating ? 'Gerando…' : 'Gerar copy com IA'}</button>
    </div>
    <div className="panel stack">
      <div className="sec">Post manual</div>
      <Field label="Título interno"><input className="inp" value={title} onChange={e => setTitle(e.target.value)} /></Field>
      <Field label="Copy"><textarea className="inp" rows={6} value={copy} onChange={e => setCopy(e.target.value)} style={{ resize: 'vertical', minHeight: 120 }} /></Field>
      <Field label="Hashtags"><input className="inp" value={hashtags} onChange={e => setHashtags(e.target.value)} placeholder="#exemplo #marca" /></Field>
      <Field label="Redes">
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          {NETS.map(n => <button key={n} className={'btn sm' + (networks.includes(n) ? ' pri' : ' ghost')} onClick={() => setNetworks(ns => ns.includes(n) ? ns.filter(x => x !== n) : [...ns, n])}>{n}</button>)}
        </div>
      </Field>
      <Field label="Agendar para (opcional)"><input className="inp" type="datetime-local" value={scheduledAt} onChange={e => setScheduledAt(e.target.value)} /></Field>
      {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
      <div className="row" style={{ gap: 8 }}>
        <button className="btn sm pri" disabled={saving} onClick={() => createPost('review')}>{saving ? 'Salvando…' : 'Enviar para aprovação'}</button>
        <button className="btn sm" disabled={saving} onClick={() => createPost('draft')}>Salvar rascunho</button>
      </div>
    </div>
  </div>;
}

/* ── APROVAÇÃO ── */
function AprovacaoApp() {
  const [posts, setPosts] = React.useState([]);
  const [labels, setLabels] = React.useState({});
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(() => {
    setLoading(true);
    window.mpApi.listPosts('DRAFT,REVIEW,APPROVED,SCHEDULED').then(r => { setPosts(r.posts || []); setLabels(r.labels || {}); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  React.useEffect(() => { if (window.mpApi) load(); }, [load]);

  const review = posts.filter(p => p.status === 'REVIEW');
  const draft = posts.filter(p => p.status === 'DRAFT');
  const approved = posts.filter(p => p.status === 'APPROVED' || p.status === 'SCHEDULED');

  async function transition(id, to) { try { await window.mpApi.transitionPost(id, to); load(); } catch (e) { alert(e.message); } }
  async function del(id) { if (!confirm('Excluir?')) return; try { await window.mpApi.deletePost(id); load(); } catch (e) { alert(e.message); } }

  function renderSection(items, title) {
    if (!items.length) return null;
    return <React.Fragment>
      <div className="sec">{title}</div>
      {items.map(p => <PostCard key={p.id} post={p} label={labels[p.status] || p.status} onTransition={transition} onDelete={del} />)}
    </React.Fragment>;
  }

  return <div className="app">
    <AppHead icon="shield" title="Central de Aprovação" desc="Revise, aprove ou devolva os conteúdos antes de irem para as redes." />
    {loading && <div className="hint">Carregando…</div>}
    {!loading && !posts.length && <div className="hint">Nenhum conteúdo na fila.</div>}
    <div className="stack">
      {renderSection(review, 'Aguardando aprovação')}
      {renderSection(draft, 'Rascunhos')}
      {renderSection(approved, 'Aprovados e agendados')}
    </div>
  </div>;
}

function PostCard({ post, label, onTransition, onDelete }) {
  const nets = (post.networks || []).join(', ');
  const sched = post.scheduled_at ? ' · agendado ' + new Date(post.scheduled_at).toLocaleString('pt-BR') : '';
  return <div className="panel stack" style={{ padding: 16 }}>
    <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
      <div className="li-main"><b>{post.title || 'Sem título'}</b><small>{post.company_name}{sched} · {nets}</small></div>
      <Pill kind={post.status === 'REVIEW' ? 'warn' : post.status === 'SCHEDULED' ? 'good' : 'cy'} dot>{label}</Pill>
    </div>
    <div style={{ whiteSpace: 'pre-wrap', fontSize: 14, color: 'var(--text2)' }}>{post.copy}</div>
    {post.hashtags && post.hashtags.length > 0 && <div style={{ color: 'var(--accent)', fontSize: 13 }}>{post.hashtags.join(' ')}</div>}
    <div className="row" style={{ gap: 8 }}>
      {post.status === 'DRAFT' && <button className="btn sm" onClick={() => onTransition(post.id, 'REVIEW')}>Enviar p/ revisão</button>}
      {post.status === 'REVIEW' && <button className="btn sm pri" onClick={() => onTransition(post.id, 'APPROVED')}>Aprovar</button>}
      {post.status === 'REVIEW' && <button className="btn sm ghost" onClick={() => onTransition(post.id, 'DRAFT')}>Devolver</button>}
      {post.status === 'APPROVED' && post.scheduled_at && <button className="btn sm pri" onClick={() => onTransition(post.id, 'SCHEDULED')}>Agendar</button>}
      <button className="btn sm ghost" style={{ color: 'var(--bad)' }} onClick={() => onDelete(post.id)}><Icon name="x" /></button>
    </div>
  </div>;
}

/* ── CONCORRENTES ── */
function ConcorrentesApp() {
  const [comps, setComps] = React.useState([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (window.mpApi) window.mpApi.listAllCompetitors().then(r => { setComps(r); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  return <div className="app">
    <AppHead icon="radar" title="Inteligência de Concorrentes" desc="Benchmark dos concorrentes de cada empresa: o que postam, frequência e engajamento." />
    {loading && <div className="hint">Carregando…</div>}
    {!loading && !comps.length && <div className="hint">Nenhum concorrente mapeado ainda. O mapeamento automático faz parte do módulo de Pesquisa de Marketing (em construção).</div>}
    <div className="grid2">
      {comps.map(c => {
        const h = c.handles || {};
        return <div key={c.id} className="panel stack" style={{ padding: 16 }}>
          <b style={{ fontSize: 15 }}>{c.name}</b>
          <small style={{ color: 'var(--muted)' }}>Concorrente de {c.company_name}</small>
          {h.instagram && <div style={{ color: 'var(--accent)', fontSize: 13 }}>{h.instagram}</div>}
          {h.website && <div style={{ color: 'var(--muted)', fontSize: 13 }}>{h.website}</div>}
        </div>;
      })}
    </div>
  </div>;
}

Object.assign(window, { ClientesApp, AprovacaoApp, ConcorrentesApp });
