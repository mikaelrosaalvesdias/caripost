/* Caripost OS — Clientes, Central de Aprovação, Concorrentes */

/* ── CLIENTES ── */
function ClientesApp() {
  const [companies, setCompanies] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [creating, setCreating] = React.useState(false);
  const [selectedId, setSelectedId] = React.useState(null);
  const [loadError, setLoadError] = React.useState('');

  const load = React.useCallback(() => {
    setLoading(true);
    return window.mpApi.listCompanies()
      .then(r => { setCompanies(r); setLoadError(''); setLoading(false); return r; })
      .catch(e => { setLoadError(e.message || 'Não foi possível atualizar a lista.'); setLoading(false); return null; });
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

    {creating && <CompanyForm onSaved={company => {
      setCreating(false);
      setSelectedId(company?.id || null);
      if (company) setCompanies(current => [company, ...current.filter(item => item.id !== company.id)]);
      load();
    }} onCancel={() => setCreating(false)} />}

    <div className="stack">
      {loading && <div className="hint">Carregando empresas…</div>}
      {loadError && <div className="err">Não foi possível atualizar a lista: {loadError} <button className="btn sm ghost" onClick={load}>Tentar novamente</button></div>}
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
  const [website, setWebsite] = React.useState('');
  const [instagram, setInstagram] = React.useState('');
  const [facebook, setFacebook] = React.useState('');
  const [segment, setSegment] = React.useState('');
  const [city, setCity] = React.useState('');
  const [state, setState] = React.useState('');
  const [phone, setPhone] = React.useState('');
  const [email, setEmail] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  async function save() {
    if (!name.trim()) { setError('Nome é obrigatório.'); return; }
    setSaving(true); setError('');
    try {
      const company = await window.mpApi.createCompany({
        name: name.trim(), segment: segment || null, website: website.trim() || null,
        social_instagram: instagram.trim() || null, social_facebook: facebook.trim() || null,
        city: city || null, state: state || null, phone: phone || null, email: email || null,
      });
      onSaved(company);
    } catch (e) { setError(e.message || 'Erro ao criar empresa.'); }
    finally { setSaving(false); }
  }

  return <div className="panel stack">
    <div className="sec cy"><Icon name="plus" />Cadastrar empresa</div>
    <div className="hint">Informe a empresa e suas fontes oficiais. O Caripost cria o cadastro, localiza logos, extrai a paleta e abre o resultado para revisão.</div>
    <div className="split">
      <div className="stack">
        <Field label="Nome *"><input className="inp" value={name} onChange={e => setName(e.target.value)} placeholder="Ex: Rio Cable" /></Field>
        <Field label="Website oficial"><input className="inp" value={website} onChange={e => setWebsite(e.target.value)} placeholder="https://empresa.com.br" /></Field>
      </div>
      <div className="stack">
        <Field label="Instagram oficial"><input className="inp" value={instagram} onChange={e => setInstagram(e.target.value)} placeholder="@empresa ou URL" /></Field>
        <Field label="Facebook oficial"><input className="inp" value={facebook} onChange={e => setFacebook(e.target.value)} placeholder="URL da página (opcional)" /></Field>
      </div>
    </div>
    <details>
      <summary className="hint" style={{ cursor: 'pointer', fontWeight: 700 }}>Dados opcionais de contato e localização</summary>
      <div className="split" style={{ marginTop: 10 }}>
        <Field label="Segmento"><input className="inp" value={segment} onChange={e => setSegment(e.target.value)} placeholder="Ex: Telecom" /></Field>
        <Field label="E-mail"><input className="inp" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="contato@empresa.com" /></Field>
      </div>
      <div className="grid3" style={{ marginTop: 8 }}>
        <Field label="Cidade"><input className="inp" value={city} onChange={e => setCity(e.target.value)} /></Field>
        <Field label="Estado"><input className="inp" value={state} onChange={e => setState(e.target.value)} placeholder="SP" /></Field>
        <Field label="Telefone"><input className="inp" value={phone} onChange={e => setPhone(e.target.value)} placeholder="(11) 99999-9999" /></Field>
      </div>
    </details>
    {error && <div className="err">{error}</div>}
    <div className="row" style={{ gap: 8 }}>
      <button className="btn sm pri" disabled={saving} onClick={save}>
        <Icon name="sparkles" />{saving ? 'Cadastrando…' : ((website.trim() || instagram.trim() || facebook.trim()) ? 'Cadastrar e puxar identidade' : 'Cadastrar empresa')}
      </button>
      <button className="btn sm ghost" disabled={saving} onClick={onCancel}>Cancelar</button>
    </div>
  </div>;
}

function CompanyEnrichmentPanel({ company, onRefresh, onReview }) {
  const status = company?.brand_kit?.extras?.enrichment || {};
  const [starting, setStarting] = React.useState(false);
  const [applyingPalette, setApplyingPalette] = React.useState(false);
  const [error, setError] = React.useState('');
  const socials = company.socials || {};
  const hasSources = !!(company.website || socials.instagram || socials.facebook);
  const running = status.state === 'queued' || status.state === 'running';
  const stages = [
    ['profile', 'Site e posicionamento'],
    ['logos', 'Logos institucionais'],
    ['products', 'Produtos e serviços'],
    ['palette', 'Paleta principal'],
    ['done', 'Pronto para revisar'],
  ];
  const stageIndex = stages.findIndex(([key]) => key === status.stage);
  const detectedColors = company?.brand_kit?.extras?.detected_colors || {};
  const currentColors = company?.brand_kit?.colors || {};
  const detectedEntries = Object.entries(detectedColors);
  const detectedPaletteApplied = detectedEntries.length > 0
    && Object.keys(currentColors).length === detectedEntries.length
    && detectedEntries.every(([name, hex]) => String(currentColors[name] || '').toUpperCase() === String(hex || '').toUpperCase());

  async function start() {
    if (!hasSources) { setError('Cadastre o site, Instagram ou Facebook em Dados Gerais primeiro.'); return; }
    setStarting(true); setError('');
    try {
      await window.mpApi.startCompanyEnrichment(company.id, {});
      await onRefresh(true);
    } catch (e) { setError(e.message || 'Não foi possível iniciar a importação.'); }
    finally { setStarting(false); }
  }

  async function useDetectedPalette() {
    if (!Object.keys(detectedColors).length) return;
    if (!window.confirm('Substituir a paleta atual pelas cores detectadas nas logos?')) return;
    setApplyingPalette(true); setError('');
    try {
      await window.mpApi.saveBrandKit(company.id, { colors: detectedColors });
      await onRefresh(true);
    } catch (e) { setError(e.message || 'Não foi possível aplicar a paleta detectada.'); }
    finally { setApplyingPalette(false); }
  }

  return <div className="panel stack" style={{ borderColor: running ? 'var(--cyan)' : undefined }}>
    <div className="row" style={{ justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
      <div>
        <div className="sec cy" style={{ margin: 0 }}><Icon name="sparkles" />Importação da identidade</div>
        <div className="hint" style={{ marginTop: 5 }}>
          {running ? (status.message || 'Importando identidade…') :
            status.state === 'done' ? 'Identidade importada. Confira as logos e a paleta antes de criar conteúdo.' :
              status.state === 'failed' ? 'A última importação não terminou.' :
                hasSources ? 'Use uma única importação para site, redes, logos, cores e produtos.' : 'Adicione uma fonte oficial em Dados Gerais.'}
        </div>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {status.state === 'done' && <button className="btn sm" onClick={onReview}><Icon name="image" />Revisar logos e cores</button>}
        {status.palette_preserved && detectedEntries.length > 0 && !detectedPaletteApplied && <button className="btn sm" disabled={applyingPalette} onClick={useDetectedPalette}>{applyingPalette ? 'Aplicando…' : 'Usar paleta detectada'}</button>}
        <button className="btn sm pri" disabled={running || starting || !hasSources} onClick={start}>
          <Icon name="refs" />{running || starting ? 'Importando…' : (status.state ? 'Puxar novamente' : 'Puxar identidade')}
        </button>
      </div>
    </div>
    {running && <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
      {stages.map(([key, label], index) => <Pill key={key} kind={stageIndex >= 0 && index < stageIndex ? 'good' : (index === stageIndex ? 'cy' : '')} dot={stageIndex >= 0 && index <= stageIndex}>{label}</Pill>)}
    </div>}
    {status.state === 'done' && <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
      <span className="hint"><b>{status.logos_total || 0}</b> logo(s)</span>
      <span className="hint"><b>{status.colors_found || 0}</b> cor(es)</span>
      <span className="hint"><b>{status.products_added || 0}</b> produto(s) novo(s)</span>
      {status.palette_preserved && (detectedPaletteApplied
        ? <Pill kind="good">Paleta detectada aplicada</Pill>
        : <Pill kind="warn">Paleta manual preservada</Pill>)}
    </div>}
    {!!(status.warnings || []).length && <details>
      <summary className="hint" style={{ cursor: 'pointer' }}>{status.warnings.length} aviso(s) da importação</summary>
      <div className="stack" style={{ gap: 4, marginTop: 6 }}>{status.warnings.map((warning, i) => <div key={i} className="hint">• {warning}</div>)}</div>
    </details>}
    {(error || status.error) && <div className="err">{error || status.error}</div>}
  </div>;
}

function CompanyDetail({ companyId, onSaved, onDeleted }) {
  const [company, setCompany] = React.useState(null);
  const [tab, setTab] = React.useState('fluxo');
  const [loading, setLoading] = React.useState(true);
  const [refreshError, setRefreshError] = React.useState('');

  const load = React.useCallback((quiet = false) => {
    if (!quiet) setLoading(true);
    return window.mpApi.getCompany(companyId)
      .then(c => { setCompany(c); setRefreshError(''); setLoading(false); return c; })
      .catch(e => { setRefreshError(e.message || 'Não foi possível atualizar a empresa.'); setLoading(false); return null; });
  }, [companyId]);

  React.useEffect(() => { load(); }, [load]);

  const enrichmentState = company?.brand_kit?.extras?.enrichment?.state || '';
  React.useEffect(() => {
    if (enrichmentState !== 'queued' && enrichmentState !== 'running') return undefined;
    let cancelled = false;
    let timer = null;
    async function poll() {
      try {
        const status = await window.mpApi.companyEnrichmentStatus(companyId);
        if (cancelled) return;
        setRefreshError('');
        setCompany(current => current ? {
          ...current,
          brand_kit: {
            ...(current.brand_kit || {}),
            extras: { ...((current.brand_kit || {}).extras || {}), enrichment: status },
          },
        } : current);
        if (status.state === 'done' || status.state === 'failed') {
          await load(true);
          return;
        }
        timer = setTimeout(poll, 2200);
      } catch (e) {
        if (cancelled) return;
        setRefreshError('Falha ao consultar o progresso: ' + (e.message || e));
        timer = setTimeout(poll, 4000);
      }
    }
    timer = setTimeout(poll, 1000);
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [companyId, enrichmentState, load]);

  async function delCompany() {
    if (!window.confirm('Excluir a empresa "' + (company && company.name) + '" e todos os seus dados (produtos, posts, conexões)?')) return;
    try { await window.mpApi.deleteCompany(companyId); if (onDeleted) onDeleted(); }
    catch (e) { window.alert('Erro: ' + e.message); }
  }

  if (loading) return <div className="panel"><div className="hint">Carregando…</div></div>;
  if (!company) return <div className="panel stack">
    <div className="err">{refreshError || 'Não foi possível carregar a empresa.'}</div>
    <button className="btn sm pri" onClick={() => load()}><Icon name="refresh" />Tentar novamente</button>
  </div>;

  const tabs = [['fluxo', 'Fluxo'], ['geral', 'Dados Gerais'], ['visual', 'Identidade Visual'], ['produtos', 'Produtos & Serviços'], ['influencers', 'Influencers'], ['events', 'Eventos'], ['voz', 'Voz & Persona'], ['video', 'Vídeo'], ['criacao', 'Criação & Prompts'], ['conexoes', 'Conexões'], ['concorrentes', 'Concorrentes'], ['gerar', 'Gerar Conteúdo'], ['acesso', 'Acesso & Funções']];

  return <div className="panel stack">
    <CompanyEnrichmentPanel company={company} onRefresh={load} onReview={() => setTab('visual')} />
    {refreshError && <div className="err">{refreshError}</div>}
    <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
      <div className="tabbar" style={{ flex: 1 }}>
        {tabs.map(([k, l]) => <button key={k} className={'tabx' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      <button className="btn sm ghost" onClick={delCompany} title="Excluir empresa"><Icon name="trash" />Excluir empresa</button>
    </div>
    {tab === 'fluxo' && <CompanyFluxo company={company} onSaved={load} />}
    {tab === 'acesso' && <CompanyAcesso company={company} onSaved={load} />}
    {tab === 'geral' && <CompanyGeral company={company} onSaved={load} />}
    {tab === 'visual' && <CompanyVisual company={company} onSaved={load} />}
    {tab === 'produtos' && <CompanyProdutos company={company} />}
    {tab === 'influencers' && <CompanyInfluencers company={company} />}
    {tab === 'events' && <CompanyEvents company={company} />}
    {tab === 'voz' && <CompanyVoz company={company} onSaved={load} />}
    {tab === 'video' && <CompanyVideo company={company} />}
    {tab === 'criacao' && <CompanyCriacao company={company} />}
    {tab === 'conexoes' && <CompanyConexoes company={company} />}
    {tab === 'concorrentes' && <CompanyConcorrentes company={company} onSaved={load} />}
    {tab === 'gerar' && <CompanyGerar company={company} />}
  </div>;
}

function CompanyProdutos({ company }) {
  const [products, setProducts] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [newName, setNewName] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [copyOpen, setCopyOpen] = React.useState(false);

  const load = React.useCallback(() => {
    if (!window.mpApi) return;
    setLoading(true);
    window.mpApi.listProducts(company.id)
      .then(p => { setProducts(p || []); setLoading(false); })
      .catch(e => { setMsg('Erro: ' + e.message); setLoading(false); });
  }, [company.id]);

  React.useEffect(() => { load(); }, [load]);

  async function addProduct() {
    if (!newName.trim()) { setMsg('Informe o nome do produto.'); return; }
    try { await window.mpApi.createProduct(company.id, { name: newName.trim() }); setNewName(''); setMsg(''); load(); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }

  return <div className="stack">
    <div className="hint">Produtos, serviços e procedimentos são <b>fonte de conteúdo</b> para o briefing. Não são selecionados na geração — a IA busca aqui as infos do que você cadastrar.</div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
      <input className="inp" value={newName} onChange={e => setNewName(e.target.value)} placeholder="Nome do produto (ex.: Look Diesel)" onKeyDown={e => e.key === 'Enter' && addProduct()} />
      <button className="btn pri" onClick={addProduct}><Icon name="plus" />Adicionar produto</button>
      <button className="btn" onClick={() => setCopyOpen(true)}><Icon name="copy" />Copiar de outro cliente</button>
    </div>
    {copyOpen && <CopyProductsModal company={company} onClose={() => setCopyOpen(false)} onDone={(n) => { setCopyOpen(false); setMsg(n ? `${n} produto(s) copiado(s).` : 'Nada copiado.'); load(); }} />}
    {loading && <div className="hint">Carregando produtos…</div>}
    {!loading && !products.length && <div className="hint">Nenhum produto ainda. Adicione os produtos que a empresa trabalha.</div>}
    {products.map(p => <ProductCard key={p.id} company={company} product={p} onChanged={load} />)}
  </div>;
}

function CopyProductsModal({ company, onClose, onDone }) {
  const [sources, setSources] = React.useState(null);
  const [srcId, setSrcId] = React.useState('');
  const [picked, setPicked] = React.useState({});   // product_id -> bool
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');

  React.useEffect(() => {
    window.mpApi.productCopySources(company.id)
      .then(s => { setSources(s || []); if ((s || []).length) setSrcId(s[0].company_id); })
      .catch(e => setMsg('Erro: ' + e.message));
  }, [company.id]);

  const src = (sources || []).find(s => s.company_id === srcId);
  const prods = (src && src.products) || [];
  const chosen = prods.filter(p => picked[p.id]).map(p => p.id);
  function toggle(id) { setPicked(m => ({ ...m, [id]: !m[id] })); }
  function allNone() { const all = prods.every(p => picked[p.id]); const nx = {}; if (!all) prods.forEach(p => { nx[p.id] = true; }); setPicked(nx); }

  async function copy() {
    setBusy(true); setMsg('');
    try {
      const r = await window.mpApi.copyProducts(company.id, { source_company_id: srcId, product_ids: chosen });
      onDone((r && r.count) || 0);
    } catch (e) { setMsg('Erro: ' + e.message); setBusy(false); }
  }

  return <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 9000, background: 'rgba(0,0,0,.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
    <div className="panel stack" style={{ maxWidth: 560, width: '100%', maxHeight: '85vh', overflowY: 'auto', background: 'var(--bg2)' }} onClick={e => e.stopPropagation()}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <b>Copiar produtos de outro cliente</b>
        <button className="btn sm ghost" onClick={onClose}><Icon name="x" /></button>
      </div>
      <div className="hint" style={{ marginTop: 6 }}>As cópias ficam independentes — editar aqui não muda o cliente de origem. Não traz logos/fotos (só o texto e a base de conhecimento que alimentam o briefing).</div>
      {msg && <div className="err">{msg}</div>}
      {sources === null && <div className="hint">Carregando clientes…</div>}
      {sources !== null && !sources.length && <div className="hint">Nenhum outro cliente com produtos cadastrados.</div>}
      {sources !== null && !!sources.length && <div className="stack" style={{ marginTop: 10 }}>
        <Field label="Cliente de origem">
          <select className="inp" value={srcId} onChange={e => { setSrcId(e.target.value); setPicked({}); }}>
            {sources.map(s => <option key={s.company_id} value={s.company_id}>{s.company_name} ({s.products.length})</option>)}
          </select>
        </Field>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <span className="sec mut">Produtos</span>
          <button className="btn sm ghost" onClick={allNone}>{prods.every(p => picked[p.id]) && prods.length ? 'Desmarcar todos' : 'Marcar todos'}</button>
        </div>
        <div className="stack" style={{ maxHeight: 260, overflowY: 'auto', gap: 4 }}>
          {prods.map(p => <label key={p.id} className="litem" style={{ padding: 8, cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'center' }}>
            <input type="checkbox" checked={!!picked[p.id]} onChange={() => toggle(p.id)} />
            <div className="li-main"><b>{p.name}</b>{p.category && <small>{p.category}</small>}</div>
          </label>)}
        </div>
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
          <button className="btn ghost" onClick={onClose} disabled={busy}>Cancelar</button>
          <button className="btn pri" onClick={copy} disabled={busy || !chosen.length}>{busy ? 'Copiando…' : `Copiar ${chosen.length || ''} produto(s)`}</button>
        </div>
      </div>}
    </div>
  </div>;
}

function CompanyInfluencers({ company }) {
  const [companies, setCompanies] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [name, setName] = React.useState('');
  const [handle, setHandle] = React.useState('');
  const [kind, setKind] = React.useState('external');
  const [msg, setMsg] = React.useState('');
  const [orphans, setOrphans] = React.useState([]);   // influenciadores cadastrados ANTES (sem empresa) → mostrar p/ mover
  const load = React.useCallback(() => {
    if (!window.mpApi) return;
    setLoading(true);
    window.mpApi.listInfCompanies(company.id).then(l => { setCompanies(l || []); setLoading(false); }).catch(e => { setMsg('Erro: ' + e.message); setLoading(false); });
    window.mpApi.listInfluencers(company.id).then(l => setOrphans((l || []).filter(i => !i.infcompany_id))).catch(() => {});
  }, [company.id]);
  React.useEffect(() => { load(); }, [load]);
  async function mover(infId, infcoId) { if (!infcoId) return; try { await window.mpApi.updateInfluencer(company.id, infId, { infcompany_id: infcoId }); load(); } catch (e) { setMsg('Erro: ' + e.message); } }
  async function add() {
    if (!name.trim()) { setMsg('Informe a empresa influencer.'); return; }
    try { await window.mpApi.createInfCompany(company.id, { name: name.trim(), handle: handle.trim(), kind }); setName(''); setHandle(''); setMsg(''); load(); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }
  return <div className="stack">
    <div className="hint">Cadastre a <b>empresa influencer</b> (ex.: loucosdatelecom) — <b>interna</b> (da própria empresa) ou <b>terceirizada</b> — com @ e logo. Embaixo dela ficam os <b>influenciadores</b> (foto + @). Dá pra usar a empresa <b>sozinha</b> (post com o @ dela, sem influenciador) ou compor a foto de um influenciador na arte.</div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <div className="stack" style={{ gap: 6, padding: 10, border: '1px solid var(--line)', borderRadius: 10 }}>
      <b style={{ fontSize: 13 }}>+ Nova empresa influencer</b>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <input className="inp" value={name} onChange={e => setName(e.target.value)} placeholder="Empresa (ex.: loucosdatelecom)" />
        <input className="inp" value={handle} onChange={e => setHandle(e.target.value)} placeholder="@instagram" style={{ maxWidth: 165 }} />
        <select className="inp" value={kind} onChange={e => setKind(e.target.value)} style={{ maxWidth: 155 }}>
          <option value="external">Terceirizada</option>
          <option value="internal">Interna (própria)</option>
        </select>
        <button className="btn pri" onClick={add}><Icon name="plus" />Adicionar</button>
      </div>
    </div>
    {loading && <div className="hint">Carregando…</div>}
    {!loading && !companies.length && <div className="hint">Nenhuma empresa influencer ainda.</div>}
    {companies.map(c => <InfCompanyCard key={c.id} company={company} infco={c} onChanged={load} />)}
    {orphans.length > 0 && <div className="stack" style={{ marginTop: 10 }}>
      <div className="sec mut">Influenciadores sem empresa (cadastrados antes) — mova pra uma empresa (mantém as fotos)</div>
      {orphans.map(i => <div key={i.id} className="card" style={{ padding: 10 }}>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <div><b>{i.name}</b>{i.handle ? <span className="mut"> · @{i.handle}</span> : null} <span className="mut">· {(i.photos || []).length} foto(s)</span></div>
          {companies.length > 0 && <select className="inp" style={{ maxWidth: 220 }} value="" onChange={e => mover(i.id, e.target.value)}>
            <option value="">Mover pra empresa…</option>
            {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>}
        </div>
      </div>)}
    </div>}
  </div>;
}

function InfCompanyCard({ company, infco, onChanged }) {
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [iname, setIname] = React.useState('');
  const [ihandle, setIhandle] = React.useState('');
  const logos = infco.logos || [];
  const influencers = infco.influencers || [];
  async function uploadLogo(files) {
    const list = Array.from(files || []); if (!list.length) return;
    setBusy(true); setMsg('Enviando logo…');
    try { for (const f of list) await window.mpApi.uploadInfCompanyLogo(company.id, infco.id, f); setMsg(''); onChanged && onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); } finally { setBusy(false); }
  }
  async function delLogo(aid) { try { await window.mpApi.deleteInfCompanyLogo(company.id, infco.id, aid); onChanged && onChanged(); } catch (e) { setMsg('Erro: ' + e.message); } }
  async function delCo() { if (!confirm('Excluir esta empresa influencer e TODOS os influenciadores dela?')) return; try { await window.mpApi.deleteInfCompany(company.id, infco.id); onChanged && onChanged(); } catch (e) { setMsg('Erro: ' + e.message); } }
  async function addInf() {
    if (!iname.trim()) { setMsg('Informe o nome do influenciador.'); return; }
    try { await window.mpApi.createInfluencer(company.id, { infcompany_id: infco.id, name: iname.trim(), handle: ihandle.trim() }); setIname(''); setIhandle(''); setMsg(''); onChanged && onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }
  return <div className="card" style={{ padding: 12 }}>
    <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
      <div><b>🏢 {infco.name}</b>{infco.handle ? <span className="mut"> · @{infco.handle}</span> : null} <Pill kind={infco.kind === 'internal' ? 'good' : 'cy'}>{infco.kind === 'internal' ? 'interna' : 'terceirizada'}</Pill></div>
      <button className="btn sm ghost" onClick={delCo}>Excluir</button>
    </div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'} style={{ fontSize: 12 }}>{msg}</div>}
    <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 8, alignItems: 'center' }}>
      <span className="mut" style={{ fontSize: 12 }}>Logo da empresa:</span>
      {logos.map(p => <div key={p.id} style={{ position: 'relative' }}>
        <img loading="lazy" decoding="async" src={p.url} style={{ width: 64, height: 64, objectFit: 'contain', borderRadius: 8, background: '#fff' }} />
        <button onClick={() => delLogo(p.id)} style={{ position: 'absolute', top: -6, right: -6, background: '#fb2f68', color: '#fff', border: 'none', borderRadius: 999, width: 20, height: 20, cursor: 'pointer', fontSize: 12 }}>×</button>
      </div>)}
      <label className="btn sm" style={{ cursor: 'pointer' }}>{busy ? '…' : '+ logo'}<input type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={e => { if (e.target.files.length) uploadLogo(e.target.files); e.target.value = ''; }} /></label>
    </div>
    <div className="sec mut" style={{ marginTop: 10 }}>Influenciadores desta empresa</div>
    {influencers.map(i => <InfluencerCard key={i.id} company={company} inf={i} onChanged={onChanged} />)}
    <div className="stack" style={{ gap: 6, marginTop: 8, padding: 8, border: '1px dashed var(--line)', borderRadius: 8 }}>
      <b style={{ fontSize: 12 }}>+ Novo influenciador desta empresa</b>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <input className="inp" value={iname} onChange={e => setIname(e.target.value)} placeholder="Nome (ex.: Júnior Lorenzi)" onKeyDown={e => e.key === 'Enter' && addInf()} />
        <input className="inp" value={ihandle} onChange={e => setIhandle(e.target.value)} placeholder="@instagram" style={{ maxWidth: 175 }} onKeyDown={e => e.key === 'Enter' && addInf()} />
        <button className="btn sm pri" onClick={addInf}><Icon name="plus" />Adicionar</button>
      </div>
    </div>
  </div>;
}

function InfluencerCard({ company, inf, onChanged }) {
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const photos = inf.photos || [];
  async function upload(files) {
    const list = Array.from(files || []);
    if (!list.length) return;
    setBusy(true); setMsg(`Enviando ${list.length} foto(s)…`);
    try { for (const f of list) await window.mpApi.uploadInfluencerPhoto(company.id, inf.id, f); setMsg(''); onChanged && onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); } finally { setBusy(false); }
  }
  async function delPhoto(aid) { try { await window.mpApi.deleteInfluencerPhoto(company.id, inf.id, aid); onChanged && onChanged(); } catch (e) { setMsg('Erro: ' + e.message); } }
  async function delInf() { if (!confirm('Excluir este influencer e as fotos?')) return; try { await window.mpApi.deleteInfluencer(company.id, inf.id); onChanged && onChanged(); } catch (e) { setMsg('Erro: ' + e.message); } }
  return <div className="card" style={{ padding: 12 }}>
    <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
      <div><b>{inf.name}</b>{inf.handle ? <span className="mut"> · @{inf.handle}</span> : null}</div>
      <button className="btn sm ghost" onClick={delInf}>Excluir</button>
    </div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'} style={{ fontSize: 12 }}>{msg}</div>}
    <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
      {photos.map(p => <div key={p.id} style={{ position: 'relative', display: 'inline-block' }}>
        <img loading="lazy" decoding="async" src={p.url} style={{ width: 84, height: 84, objectFit: 'cover', borderRadius: 8 }} />
        <button onClick={() => delPhoto(p.id)} title="Remover" style={{ position: 'absolute', top: -6, right: -6, background: '#fb2f68', color: '#fff', border: 'none', borderRadius: 999, width: 20, height: 20, cursor: 'pointer', fontSize: 12, lineHeight: '20px' }}>×</button>
      </div>)}
    </div>
    <label className="btn sm" style={{ marginTop: 8, display: 'inline-block', cursor: 'pointer' }}>
      {busy ? 'Enviando…' : '+ Fotos do influencer'}
      <input type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={e => { if (e.target.files && e.target.files.length) upload(e.target.files); e.target.value = ''; }} />
    </label>
  </div>;
}

function CompanyEvents({ company }) {
  const [orgs, setOrgs] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [name, setName] = React.useState('');
  const [ig, setIg] = React.useState('');
  const [site, setSite] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const load = React.useCallback(() => {
    if (!window.mpApi) return;
    setLoading(true);
    window.mpApi.listOrganizers(company.id).then(l => { setOrgs(l || []); setLoading(false); }).catch(e => { setMsg('Erro: ' + e.message); setLoading(false); });
  }, [company.id]);
  React.useEffect(() => { load(); }, [load]);
  async function add() {
    if (!name.trim()) { setMsg('Informe a empresa do evento.'); return; }
    try { await window.mpApi.createOrganizer(company.id, { name: name.trim(), instagram: ig.trim(), website: site.trim() }); setName(''); setIg(''); setSite(''); setMsg(''); load(); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }
  return <div className="stack">
    <div className="hint">Cadastre a <b>empresa do evento</b> (ex.: ExPSP) com Instagram, site e <b>logo</b>. Embaixo dela ficam os <b>eventos</b> que você vai participar — com <b>data início/fim</b>, cidade, descrição, <b>logos e imagens de divulgação</b>. A IA usa tudo pra produzir a divulgação.</div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <div className="stack" style={{ gap: 6, padding: 10, border: '1px solid var(--line)', borderRadius: 10 }}>
      <b style={{ fontSize: 13 }}>+ Nova empresa do evento</b>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <input className="inp" value={name} onChange={e => setName(e.target.value)} placeholder="Empresa do evento (ex.: ExPSP)" />
        <input className="inp" value={ig} onChange={e => setIg(e.target.value)} placeholder="@instagram" style={{ maxWidth: 175 }} />
        <input className="inp" value={site} onChange={e => setSite(e.target.value)} placeholder="site.com.br" style={{ maxWidth: 190 }} />
        <button className="btn pri" onClick={add}><Icon name="plus" />Adicionar</button>
      </div>
    </div>
    {loading && <div className="hint">Carregando…</div>}
    {!loading && !orgs.length && <div className="hint">Nenhuma empresa de evento ainda.</div>}
    {orgs.map(o => <OrganizerCard key={o.id} company={company} org={o} onChanged={load} />)}
  </div>;
}

function OrganizerCard({ company, org, onChanged }) {
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [evName, setEvName] = React.useState('');
  const [ds, setDs] = React.useState('');
  const [de, setDe] = React.useState('');
  const [loc, setLoc] = React.useState('');
  const [stand, setStand] = React.useState('');
  const [desc, setDesc] = React.useState('');
  const logos = org.logos || [];
  const events = org.events || [];
  async function uploadLogo(files) {
    const list = Array.from(files || []); if (!list.length) return;
    setBusy(true); setMsg('Enviando logo…');
    try { for (const f of list) await window.mpApi.uploadOrganizerLogo(company.id, org.id, f); setMsg(''); onChanged && onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); } finally { setBusy(false); }
  }
  async function delLogo(aid) { try { await window.mpApi.deleteOrganizerLogo(company.id, org.id, aid); onChanged && onChanged(); } catch (e) { setMsg('Erro: ' + e.message); } }
  async function delOrg() { if (!confirm('Excluir esta empresa do evento e TODOS os eventos dela?')) return; try { await window.mpApi.deleteOrganizer(company.id, org.id); onChanged && onChanged(); } catch (e) { setMsg('Erro: ' + e.message); } }
  async function addEvent() {
    if (!evName.trim()) { setMsg('Informe o nome do evento.'); return; }
    try { await window.mpApi.createEvent(company.id, { organizer_id: org.id, name: evName.trim(), date_start: ds, date_end: de, location: loc.trim(), description: desc.trim(), meta: { stand: stand.trim() } }); setEvName(''); setDs(''); setDe(''); setLoc(''); setStand(''); setDesc(''); setMsg(''); onChanged && onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }
  return <div className="card" style={{ padding: 12 }}>
    <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
      <div><b>🏢 {org.name}</b>{org.instagram ? <span className="mut"> · @{org.instagram}</span> : null}{org.website ? <span className="mut"> · {org.website}</span> : null}</div>
      <button className="btn sm ghost" onClick={delOrg}>Excluir</button>
    </div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'} style={{ fontSize: 12 }}>{msg}</div>}
    <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 8, alignItems: 'center' }}>
      <span className="mut" style={{ fontSize: 12 }}>Logo da empresa:</span>
      {logos.map(p => <div key={p.id} style={{ position: 'relative' }}>
        <img loading="lazy" decoding="async" src={p.url} style={{ width: 64, height: 64, objectFit: 'contain', borderRadius: 8, background: '#fff' }} />
        <button onClick={() => delLogo(p.id)} style={{ position: 'absolute', top: -6, right: -6, background: '#fb2f68', color: '#fff', border: 'none', borderRadius: 999, width: 20, height: 20, cursor: 'pointer', fontSize: 12 }}>×</button>
      </div>)}
      <label className="btn sm" style={{ cursor: 'pointer' }}>{busy ? '…' : '+ logo'}<input type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={e => { if (e.target.files.length) uploadLogo(e.target.files); e.target.value = ''; }} /></label>
    </div>
    <div className="sec mut" style={{ marginTop: 10 }}>Eventos desta empresa</div>
    {events.map(ev => <EventCard key={ev.id} company={company} ev={ev} onChanged={onChanged} />)}
    <div className="stack" style={{ gap: 6, marginTop: 8, padding: 8, border: '1px dashed var(--line)', borderRadius: 8 }}>
      <b style={{ fontSize: 12 }}>+ Novo evento desta empresa</b>
      <input className="inp" value={evName} onChange={e => setEvName(e.target.value)} placeholder="Nome do evento (ex.: ExPSP 2026)" />
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <label className="mut" style={{ fontSize: 12 }}>Início <input className="inp" type="date" value={ds} onChange={e => setDs(e.target.value)} /></label>
        <label className="mut" style={{ fontSize: 12 }}>Fim <input className="inp" type="date" value={de} onChange={e => setDe(e.target.value)} /></label>
        <input className="inp" value={loc} onChange={e => setLoc(e.target.value)} placeholder="Cidade" style={{ maxWidth: 150 }} />
        <input className="inp" value={stand} onChange={e => setStand(e.target.value)} placeholder="Stand (ex.: 45)" style={{ maxWidth: 120 }} />
      </div>
      <textarea className="inp" rows="2" value={desc} onChange={e => setDesc(e.target.value)} placeholder="Descrição do evento" />
      <button className="btn sm pri" onClick={addEvent} style={{ alignSelf: 'flex-start' }}><Icon name="plus" />Adicionar evento</button>
    </div>
  </div>;
}

function EventCard({ company, ev, onChanged }) {
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const logos = ev.logos || [];
  const images = ev.images || [];
  async function upl(files, isImg) {
    const list = Array.from(files || []); if (!list.length) return;
    setBusy(true); setMsg('Enviando…');
    try { for (const f of list) await (isImg ? window.mpApi.uploadEventImage(company.id, ev.id, f) : window.mpApi.uploadEventLogo(company.id, ev.id, f)); setMsg(''); onChanged && onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); } finally { setBusy(false); }
  }
  async function del(aid, isImg) { try { await (isImg ? window.mpApi.deleteEventImage(company.id, ev.id, aid) : window.mpApi.deleteEventLogo(company.id, ev.id, aid)); onChanged && onChanged(); } catch (e) { setMsg('Erro: ' + e.message); } }
  async function delEv() { if (!confirm('Excluir este evento?')) return; try { await window.mpApi.deleteEvent(company.id, ev.id); onChanged && onChanged(); } catch (e) { setMsg('Erro: ' + e.message); } }
  const f = d => d ? new Date(d + 'T00:00:00').toLocaleDateString() : '';
  const periodo = ev.date_start ? (f(ev.date_start) + (ev.date_end && ev.date_end !== ev.date_start ? ' a ' + f(ev.date_end) : '')) : f(ev.event_date);
  return <div className="card" style={{ padding: 10, marginTop: 6 }}>
    <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
      <div><b>{ev.name}</b>{periodo ? <span className="mut"> · 📅 {periodo}</span> : null}{ev.location ? <span className="mut"> · 📍 {ev.location}</span> : null}</div>
      <button className="btn sm ghost" onClick={delEv}>Excluir</button>
    </div>
    {ev.description ? <div className="mut" style={{ fontSize: 13, marginTop: 4 }}>{ev.description}</div> : null}
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'} style={{ fontSize: 12 }}>{msg}</div>}
    <div className="row" style={{ gap: 16, flexWrap: 'wrap', marginTop: 8 }}>
      <div className="stack" style={{ gap: 4 }}>
        <span className="mut" style={{ fontSize: 11 }}>Logos de divulgação</span>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          {logos.map(p => <div key={p.id} style={{ position: 'relative' }}><img loading="lazy" decoding="async" src={p.url} style={{ width: 58, height: 58, objectFit: 'contain', borderRadius: 6, background: '#fff' }} /><button onClick={() => del(p.id, false)} style={{ position: 'absolute', top: -6, right: -6, background: '#fb2f68', color: '#fff', border: 'none', borderRadius: 999, width: 18, height: 18, fontSize: 11, cursor: 'pointer' }}>×</button></div>)}
          <label className="btn sm" style={{ cursor: 'pointer' }}>+ logo<input type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={e => { if (e.target.files.length) upl(e.target.files, false); e.target.value = ''; }} /></label>
        </div>
      </div>
      <div className="stack" style={{ gap: 4 }}>
        <span className="mut" style={{ fontSize: 11 }}>Imagens de divulgação</span>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          {images.map(p => <div key={p.id} style={{ position: 'relative' }}><img loading="lazy" decoding="async" src={p.url} style={{ width: 58, height: 58, objectFit: 'cover', borderRadius: 6 }} /><button onClick={() => del(p.id, true)} style={{ position: 'absolute', top: -6, right: -6, background: '#fb2f68', color: '#fff', border: 'none', borderRadius: 999, width: 18, height: 18, fontSize: 11, cursor: 'pointer' }}>×</button></div>)}
          <label className="btn sm" style={{ cursor: 'pointer' }}>{busy ? '…' : '+ imagem'}<input type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={e => { if (e.target.files.length) upl(e.target.files, true); e.target.value = ''; }} /></label>
        </div>
      </div>
    </div>
  </div>;
}

function ProductCard({ company, product, onChanged }) {
  const [name, setName] = React.useState(product.name || '');
  const [description, setDescription] = React.useState(product.description || '');
  const [website, setWebsite] = React.useState(product.website || '');
  const [instagram, setInstagram] = React.useState((product.socials || {}).instagram || '');
  const [objective, setObjective] = React.useState(product.objective || '');
  const [functions, setFunctions] = React.useState((product.functions || []).join('\n'));
  const [solName, setSolName] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const solutions = product.solutions || [];
  const logos = product.logos || [];
  const photos = product.photos || [];
  const [photoBusy, setPhotoBusy] = React.useState(false);
  const [photoMsg, setPhotoMsg] = React.useState('');
  const [kbChars, setKbChars] = React.useState((product.knowledge || '').length);
  const [kbBusy, setKbBusy] = React.useState(false);
  const [kbMsg, setKbMsg] = React.useState('');
  React.useEffect(() => {
    window.mpApi.getProductKb(company.id, product.id).then(r => setKbChars((r && r.chars) || 0)).catch(() => {});
  }, [product.id]);
  async function uploadKb(file) {
    if (!file) return;
    setKbBusy(true); setKbMsg('Lendo e indexando ' + file.name + '…');
    try {
      const r = await window.mpApi.uploadProductKb(company.id, product.id, file);
      if (r && r.detail) { setKbMsg('Erro: ' + r.detail); }
      else {
        setKbChars((r && r.total_chars) || 0);
        const f = (r && r.filled) || {};
        if (f.description) setDescription(f.description);
        if (f.objective) setObjective(f.objective);
        if (Array.isArray(f.functions) && f.functions.length) setFunctions(f.functions.join('\n'));
        const auto = Object.keys(f).length ? ' Preenchi automaticamente: ' + Object.keys(f).map(k => ({ description: 'descrição', objective: 'objetivo', functions: 'funções' }[k] || k)).join(', ') + ' (confira e salve).' : '';
        setKbMsg('✓ ' + ((r && r.file) || file.name) + ' adicionado (' + ((r && r.chars) || 0) + ' caracteres).' + auto);
        onChanged();
      }
    } catch (e) { setKbMsg('Erro: ' + e.message); }
    finally { setKbBusy(false); }
  }
  async function clearKb() {
    if (!window.confirm('Limpar TODA a base de conhecimento de "' + product.name + '"?')) return;
    setKbBusy(true);
    try { await window.mpApi.clearProductKb(company.id, product.id); setKbChars(0); setKbMsg('Base limpa.'); onChanged(); }
    catch (e) { setKbMsg('Erro: ' + e.message); }
    finally { setKbBusy(false); }
  }

  async function save() {
    setBusy(true); setMsg('');
    try {
      await window.mpApi.updateProduct(company.id, product.id, {
        name, description, website, objective,
        functions: functions.split('\n').map(s => s.trim()).filter(Boolean),
        socials: { ...(product.socials || {}), instagram },
      });
      setMsg('Salvo.'); onChanged();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }
  async function enrich() {
    if (!website && !instagram) { setMsg('Informe o site ou o Instagram primeiro.'); return; }
    setBusy(true); setMsg('Lendo site/Instagram e preenchendo o perfil…');
    try {
      const r = await window.mpApi.enrichProduct(company.id, product.id, { website, instagram });
      const d = r.extracted || {};
      if (d.description) setDescription(d.description);
      if (d.objective) setObjective(d.objective);
      if (d.functions && d.functions.length) setFunctions(d.functions.join('\n'));
      const cols = (d.colors && Object.values(d.colors).filter(Boolean).length) ? ' + cores do logo' : '';
      const note = d.site_text_used ? '' : ' (site não acessível — inferido do nome/IG)';
      setMsg('✓ Perfil preenchido' + cols + note + '. Revise, tire o que não quiser e salve.');
      onChanged();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!window.confirm('Excluir o produto "' + product.name + '"?')) return;
    try { await window.mpApi.deleteProduct(company.id, product.id); onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }
  async function addSolution() {
    if (!solName.trim()) return;
    try { await window.mpApi.createSolution(company.id, product.id, { name: solName.trim() }); setSolName(''); onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }
  async function removeSolution(id) {
    try { await window.mpApi.deleteSolution(company.id, id); onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }
  async function uploadLogo(files) {
    const list = Array.from(files || []).filter(Boolean);
    if (!list.length) return;
    if (list.length > 1) setMsg(`Enviando ${list.length} logos…`);
    let ok = 0, fail = 0;
    for (const f of list) {
      try { await window.mpApi.uploadProductLogo(company.id, product.id, f); ok++; }
      catch (e) { fail++; setMsg('Erro em ' + (f.name || 'arquivo') + ': ' + e.message); }
    }
    onChanged();
    if (list.length > 1) setMsg(`${ok} logo(s) enviada(s)` + (fail ? `, ${fail} falhou(aram)` : '') + '.');
  }
  async function removeLogo(id) {
    if (!window.confirm('Excluir esta logo?')) return;
    try { await window.mpApi.deleteLogo(company.id, id); onChanged(); }
    catch (e) { setMsg('Erro: ' + e.message); }
  }
  async function uploadPhoto(file) {
    if (!file) return;
    setPhotoBusy(true); setPhotoMsg('Enviando e analisando ' + file.name + '…');
    try {
      const r = await window.mpApi.uploadProductPhoto(company.id, product.id, file);
      if (r && r.detail) setPhotoMsg('Erro: ' + r.detail);
      else { setPhotoMsg((r && r.facts) ? ('✓ Foto analisada — fatos somados ao briefing: ' + r.facts) : '✓ Foto enviada (visão não extraiu fatos).'); onChanged(); }
    } catch (e) { setPhotoMsg('Erro: ' + e.message); }
    finally { setPhotoBusy(false); }
  }
  async function removePhoto(id) {
    if (!window.confirm('Excluir esta foto?')) return;
    try { await window.mpApi.deleteProductPhoto(company.id, product.id, id); onChanged(); }
    catch (e) { setPhotoMsg('Erro: ' + e.message); }
  }

  return <div className="panel stack">
    <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
      <div className="row" style={{ gap: 8, alignItems: 'center' }}><span className="li-ic"><Icon name="layers" /></span><b>{product.name}</b></div>
      <button className="btn sm" onClick={remove}><Icon name="trash" />Excluir</button>
    </div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <div className="split">
      <Field label="Nome"><input className="inp" value={name} onChange={e => setName(e.target.value)} /></Field>
      <Field label="Site"><input className="inp" value={website} onChange={e => setWebsite(e.target.value)} placeholder="https://" /></Field>
    </div>
    <Field label="Instagram"><input className="inp" value={instagram} onChange={e => setInstagram(e.target.value)} placeholder="@produto" /></Field>
    <div className="row">
      <button className="btn sm" disabled={busy} onClick={enrich}><Icon name="sparkles" />{busy ? 'Puxando…' : 'Puxar do site/Instagram'}</button>
      <small className="hint" style={{ alignSelf: 'center' }}>Preenche descrição, objetivo, funções, cores e à la carte — sem preços.</small>
    </div>
    <Field label="Descrição (fonte do briefing)"><textarea className="inp" rows={3} value={description} onChange={e => setDescription(e.target.value)} placeholder="O que é, diferenciais, público, claims…" style={{ resize: 'vertical' }} /></Field>
    <Field label="Objetivo / posicionamento (como a IA deve vender esta oferta)"><textarea className="inp" rows={2} value={objective} onChange={e => setObjective(e.target.value)} placeholder="Ex.: procedimento premium com resultado natural; público que busca autoestima e confiança." style={{ resize: 'vertical' }} /></Field>
    <Field label="Funções / benefícios / o que inclui (uma por linha — alimenta a IA, sem preços)"><textarea className="inp" rows={3} value={functions} onChange={e => setFunctions(e.target.value)} placeholder="Catálogo de músicas offline&#10;Sem anúncios&#10;Letras sincronizadas" style={{ resize: 'vertical' }} /></Field>
    <Field label="Base de conhecimento (PDF/TXT: manual, FAQ, lista de funções — deixa o briefing PROFUNDO)">
      <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <input type="file" accept=".pdf,.docx,.doc,.txt,.md,.csv,.jpg,.jpeg,.png,.webp" disabled={kbBusy} onChange={e => { const f = e.target.files[0]; e.target.value = ''; uploadKb(f); }} />
        {kbChars > 0 && <Pill kind="good" dot>{kbChars.toLocaleString('pt-BR')} caracteres indexados</Pill>}
        {kbChars > 0 && <button className="btn sm ghost" disabled={kbBusy} onClick={clearKb}>Limpar base</button>}
      </div>
      {kbMsg && <div className="hint">{kbMsg}</div>}
      <div className="hint">Pode subir vários arquivos (vão se somando). A IA usa isto + o site + a internet pra montar o conteúdo.</div>
    </Field>

    <div className="sec mut" style={{ marginTop: 4 }}>Logos do produto</div>
    <div className="row" style={{ gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
      {logos.map(l => <div key={l.id} style={{ position: 'relative', display: 'inline-block' }}>
        <img loading="lazy" decoding="async" src={l.url} style={{ maxHeight: 48, maxWidth: 120, borderRadius: 6, border: '1px solid var(--line)', display: 'block' }} />
        <button className="btn sm" title="Excluir logo" onClick={() => removeLogo(l.id)}
          style={{ position: 'absolute', top: -8, right: -8, padding: '1px 6px', lineHeight: 1.2, borderRadius: 999 }}><Icon name="x" /></button>
      </div>)}
      <label className="hint" style={{ display: 'block', marginTop: 4 }}>Selecione um ou vários arquivos de logo:</label>
      <input type="file" accept="image/*" multiple onChange={e => { if (e.target.files && e.target.files.length) uploadLogo(e.target.files); e.target.value = ''; }} />
    </div>

    <div className="sec mut" style={{ marginTop: 4 }}>Foto do produto <span className="hint">— a IA analisa por visão e ancora o vídeo no item REAL</span></div>
    <div className="row" style={{ gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
      {photos.map(p => <div key={p.id} style={{ position: 'relative', display: 'inline-block' }}>
        <img loading="lazy" decoding="async" src={p.url} style={{ maxHeight: 64, maxWidth: 96, borderRadius: 6, border: '1px solid var(--line)', display: 'block' }} />
        <button className="btn sm" title="Excluir foto" onClick={() => removePhoto(p.id)}
          style={{ position: 'absolute', top: -8, right: -8, padding: '1px 6px', lineHeight: 1.2, borderRadius: 999 }}><Icon name="x" /></button>
      </div>)}
      <input type="file" accept="image/*" disabled={photoBusy} onChange={e => { const f = e.target.files[0]; e.target.value = ''; uploadPhoto(f); }} />
    </div>
    {photoMsg && <div className="hint">{photoMsg}</div>}

    {product.colors && ['primary', 'secondary', 'accent'].some(k => product.colors[k]) && <>
      <div className="sec mut" style={{ marginTop: 4 }}>Cores (do logo)</div>
      <div className="row" style={{ gap: 12 }}>
        {['primary', 'secondary', 'accent'].map(k => product.colors[k] ? <div key={k} className="row" style={{ gap: 6, alignItems: 'center' }}>
          <span style={{ width: 20, height: 20, borderRadius: 5, background: product.colors[k], border: '1px solid var(--line)', display: 'inline-block' }} />
          <small className="mono">{product.colors[k]}</small>
        </div> : null)}
      </div>
    </>}

    <div className="sec mut" style={{ marginTop: 4 }}>À la carte (entregue junto neste app)</div>
    <div className="hint">Itens que vêm dentro do app — ex.: Zap → Telecine, Premiere, Canais Adultos; Aya Books → eBooks, Mini Books, Audiobooks.</div>
    {solutions.map(s => <div key={s.id} className="litem" style={{ padding: 8 }}>
      <div className="li-main"><b>{s.name}</b>{s.description && <small>{s.description}</small>}</div>
      <button className="btn sm ghost" onClick={() => removeSolution(s.id)}><Icon name="x" /></button>
    </div>)}
    <div className="row" style={{ gap: 8 }}>
      <input className="inp" value={solName} onChange={e => setSolName(e.target.value)} placeholder="Novo item à la carte" onKeyDown={e => e.key === 'Enter' && addSolution()} />
      <button className="btn sm" onClick={addSolution}><Icon name="plus" />Adicionar</button>
    </div>

    <div className="row"><button className="btn pri" disabled={busy} onClick={save}>{busy ? 'Salvando…' : 'Salvar produto'}</button></div>
  </div>;
}

function CompanyConexoes({ company }) {
  const [accounts, setAccounts] = React.useState([]);
  const [config, setConfig] = React.useState(null);
  const [busy, setBusy] = React.useState('');
  const [msg, setMsg] = React.useState('');

  const PLATFORMS = [
    ['instagram', 'Instagram', 'broadcast'],
    ['facebook', 'Facebook', 'globe'],
  ];

  const load = React.useCallback(() => {
    if (!window.mpApi) return;
    window.mpApi.socialAccounts(company.id).then(a => setAccounts(a || [])).catch(() => {});
    window.mpApi.socialConfig().then(setConfig).catch(() => {});
  }, [company.id]);

  React.useEffect(() => { load(); }, [load]);

  const accountFor = (p) => accounts.find(a => a.platform === p);
  const isOk = (a) => a && (a.status === 'connected' || a.status === 'active');

  async function connect(platform) {
    setBusy(platform); setMsg('Abrindo autorização ' + platform + '…');
    try {
      const callbackUrl = window.location.origin + '/api/social/callback';
      const r = await window.mpApi.socialConnect({ brandId: company.id, platform, callbackUrl });
      if (r.redirect_url) window.open(r.redirect_url, '_blank', 'noopener,noreferrer');
      setMsg(r.redirect_url ? 'Autorize na aba aberta e depois clique em Testar.' : 'Conexão registrada.');
      setTimeout(load, 1500);
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(''); }
  }

  async function disconnect(id) {
    setBusy(id); setMsg('');
    try { await window.mpApi.socialDisconnect(id); setMsg('Desconectado.'); load(); }
    catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(''); }
  }

  return <div className="stack">
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    {config && config.composio_configured === false && <div className="err">
      Composio não configurado. Adicione a API key do Composio em Settings para conectar as redes.
    </div>}
    <div className="hint">Conecte cada rede pela autorização oficial do Composio. Sem token manual — o auth config é criado automaticamente com a API key.</div>
    <div className="grid2">
      {PLATFORMS.map(([p, label, ic]) => {
        const acc = accountFor(p);
        const ok = isOk(acc);
        const expires = acc && (acc.expires_at || (acc.metadata || {}).expires_at);
        return <div key={p} className="panel stack">
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <div className="row" style={{ gap: 8, alignItems: 'center' }}>
              <span className="li-ic"><Icon name={ic} /></span>
              <b>{label}</b>
            </div>
            <Pill kind={ok ? 'good' : acc ? 'warn' : ''} dot>{acc ? acc.status : 'não conectado'}</Pill>
          </div>
          {acc && <small className="hint">{acc.external_account_name || acc.external_account_id || 'Composio'}</small>}
          {expires && <small className="hint">Expira: {new Date(expires).toLocaleString('pt-BR')}</small>}
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button className="btn sm pri" disabled={busy === p} onClick={() => connect(p)}>
              <Icon name="link" />{acc ? 'Reconectar' : 'Conectar'}
            </button>
            <button className="btn sm ghost" disabled={!!busy} onClick={load}><Icon name="refs" />Testar</button>
            {acc && <button className="btn sm" disabled={busy === acc.id} onClick={() => disconnect(acc.id)}><Icon name="trash" />Desconectar</button>}
          </div>
        </div>;
      })}
    </div>
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

  async function shareConnectLink() {
    setBusy(true); setMsg('Criando link seguro...');
    try {
      const r = await window.mpApi.socialConnectInvite({ brandId: company.id, platform: 'instagram' });
      await navigator.clipboard.writeText(r.url);
      setMsg('Link copiado. Envie ao cliente; ele vale por 7 dias e conecta somente esta empresa.');
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
      await window.mpApi.socialAnalyzeBrand(company.id, { instagram, applyBrandKit: false });
      setMsg('Análise pronta. Ideias e estratégia foram atualizadas sem alterar a identidade revisada.');
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
          <button className="btn sm ghost" disabled={busy} onClick={shareConnectLink}><Icon name="copy" />Copiar link para o cliente</button>
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
        <button className="btn" onClick={() => window.__mpOpen && window.__mpOpen('conteudo')}><Icon name="broadcast" />Publicar/agendar</button>
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

function CompanyLogos({ company, onSaved }) {
  const [logos, setLogos] = React.useState([]);
  const [msg, setMsg] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const refreshKey = company?.brand_kit?.updated_at || company?.brand_kit?.extras?.enrichment?.finished_at || '';

  const load = React.useCallback(() => {
    if (!window.mpApi) return;
    window.mpApi.listLogos(company.id)
      .then(l => { setLogos(l || []); setMsg(current => current.startsWith('Erro') ? '' : current); })
      .catch(e => setMsg('Erro: ' + e.message));
  }, [company.id, refreshKey]);

  React.useEffect(() => { load(); }, [load]);

  async function upload(files) {
    const selected = Array.from(files || []);
    if (!selected.length) return;
    setBusy(true); setMsg('');
    try {
      let uploaded = 0;
      for (const file of selected) {
        await window.mpApi.uploadLogoVariant(company.id, file, 'logo', logos.length === 0 && uploaded === 0);
        uploaded += 1;
        setMsg(`Enviando logos… ${uploaded}/${selected.length}`);
      }
      setMsg(`${uploaded} logo(s) salva(s).`); load(); onSaved && onSaved(true);
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }
  async function makePrimary(id) {
    setBusy(true); setMsg('');
    try { await window.mpApi.setPrimaryLogo(company.id, id); setMsg('Logo principal atualizada.'); load(); onSaved && onSaved(true); }
    catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }
  async function remove(id) {
    if (!window.confirm('Excluir esta logo?')) return;
    setBusy(true); setMsg('');
    try { await window.mpApi.deleteLogo(company.id, id); load(); onSaved && onSaved(true); }
    catch (e) { setMsg('Erro: ' + e.message); }
    finally { setBusy(false); }
  }

  return <div className="stack">
    <div className="sec">Logos da empresa <Pill kind="cy">{logos.length}</Pill></div>
    <div className="hint">Todas as variantes encontradas ficam aqui. Escolha qual é a principal; as demais continuam disponíveis para fundos claros e escuros. Upload: PNG, JPEG ou WebP, até 10 MB.</div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 12 }}>
      {logos.map(l => {
        const meta = l.meta || {};
        return <div key={l.id} className="panel" style={{ position: 'relative', padding: 8, borderColor: meta.is_primary ? 'var(--green)' : undefined }}>
        <div style={{ height: 92, padding: 10, borderRadius: 8, display: 'grid', placeItems: 'center', background: 'linear-gradient(135deg,#1f2937 0 50%,#f8fafc 50%)' }}>
          <img loading="lazy" decoding="async" src={l.url} style={{ maxWidth: '100%', width: '100%', height: 72, objectFit: 'contain' }} />
        </div>
        <div className="row" style={{ justifyContent: 'space-between', marginTop: 7, gap: 6 }}>
          <div className="hint" style={{ fontSize: 10 }}>{meta.variant || (l.source === 'WEB' ? 'site' : 'manual')}</div>
          {meta.is_primary ? <Pill kind="good">★ Principal</Pill> : <button className="btn sm ghost" disabled={busy} onClick={() => makePrimary(l.id)}>☆ Usar</button>}
          <button className="btn sm ghost" disabled={busy} title="Excluir logo" onClick={() => remove(l.id)}><Icon name="trash" /></button>
        </div>
      </div>;})}
      {!logos.length && <div className="hint">Sem logos ainda.</div>}
    </div>
    <label className="btn sm pri" style={{ alignSelf: 'flex-start', cursor: 'pointer' }}>
      <Icon name="plus" />{busy ? 'Enviando…' : 'Adicionar uma ou várias logos'}
      <input type="file" accept="image/png,image/jpeg,image/webp" multiple style={{ display: 'none' }} onChange={e => { upload(e.target.files); e.target.value = ''; }} />
    </label>
  </div>;
}

function CompanyVisual({ company, onSaved }) {
  const bk = company.brand_kit || {};
  const colors = bk.colors || {};
  const colorsKey = JSON.stringify(colors);
  const paletteFrom = value => Object.entries(value || {}).map(([name, hex]) => ({ name, hex }));
  const [pal, setPal] = React.useState(() => paletteFrom(colors));
  const [msg, setMsg] = React.useState('');
  const [igHandle, setIgHandle] = React.useState('');
  const [igBusy, setIgBusy] = React.useState(false);
  const identityRunning = ['queued', 'running'].includes(bk.extras?.enrichment?.state);
  React.useEffect(() => { setPal(paletteFrom(colors)); }, [company.id, colorsKey]);
  async function importIg() {
    setIgBusy(true); setMsg('');
    try {
      const r = await window.mpApi.importInstagram(company.id, { handle: igHandle, kind: 'reference', count: 4 });
      setMsg(`✓ Importado de @${r.handle}: ${r.refs} referência(s).`); onSaved();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setIgBusy(false); }
  }
  const refs = company.references || [];
  const setPalAt = (i, patch) => setPal(p => p.map((c, j) => j === i ? { ...c, ...patch } : c));

  async function saveColors() {
    setMsg('');
    try {
      const dict = {};
      for (const color of pal) {
        const name = (color.name || '').trim();
        const hex = (color.hex || '').trim().toUpperCase();
        if (!name && !hex) continue;
        if (!name) throw new Error('Dê um nome para todas as cores.');
        if (!/^#[0-9A-F]{6}$/.test(hex)) throw new Error(`Cor inválida em "${name}".`);
        if (Object.prototype.hasOwnProperty.call(dict, name)) throw new Error(`Nome de cor repetido: "${name}".`);
        dict[name] = hex;
      }
      await window.mpApi.saveBrandKit(company.id, { colors: dict });
      setMsg(`${Object.keys(dict).length} cor(es) salva(s).`); onSaved(true);
    } catch (e) { setMsg('Erro: ' + e.message); }
  }

  async function doUploadRef(file) {
    try {
      await window.mpApi.uploadReference(company.id, file);
      setMsg('✓ Referência enviada. Analisando composição, paleta auxiliar e posição da assinatura…');
      onSaved();
      setTimeout(onSaved, 12000);
    } catch (e) { setMsg('Erro: ' + e.message); }
  }

  async function doDeleteRef(assetId) {
    try { await window.mpApi.deleteReference(company.id, assetId); onSaved(); } catch (e) { setMsg('Erro: ' + e.message); }
  }

  return <div className="stack">
    <CompanyLogos company={company} onSaved={onSaved} />
    <div className="sec">Paleta de cores <Pill kind="cy">{pal.length}</Pill></div>
    <div className="hint">A importação agrupa tons parecidos e mantém apenas cores realmente distintas, sem limite fixo de três. Você pode corrigir, remover ou adicionar qualquer cor.</div>
    {identityRunning && <div className="hint">Aguarde a importação terminar antes de salvar a revisão da paleta.</div>}
    <div className="stack" style={{ gap: 8 }}>
      {!pal.length && <div className="hint">Nenhuma cor detectada. Puxe a identidade novamente ou adicione manualmente.</div>}
      {pal.map((c, i) => <div key={i} className="row" style={{ gap: 8, alignItems: 'center' }}>
        <input type="color" value={/^#[0-9a-fA-F]{6}$/.test(c.hex) ? c.hex : '#000000'} onChange={e => setPalAt(i, { hex: e.target.value })} style={{ width: 46, height: 38, border: 'none', background: 'none', cursor: 'pointer' }} />
        <input className="inp" value={c.name} onChange={e => setPalAt(i, { name: e.target.value })} placeholder="nome (ex.: primary, rosa, dourado)" style={{ maxWidth: 220 }} />
        <span className="mono" style={{ fontSize: 12, minWidth: 70 }}>{c.hex}</span>
        <button className="btn sm ghost" onClick={() => setPal(p => p.filter((_, j) => j !== i))}>✕</button>
      </div>)}
      <button className="btn sm ghost" onClick={() => setPal(p => [...p, { name: 'cor' + (p.length + 1), hex: '#888888' }])}>+ Adicionar cor</button>
    </div>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <button className="btn sm pri" disabled={identityRunning} onClick={saveColors}>Salvar cores</button>
    <div className="sec">Artes de referência (o Estúdio IA segue este estilo)</div>
    <div className="hint">Suba artes que representem o estilo desejado (suas, do manual, ou de um perfil que o cliente admira). O motor usa as mais recentes como <b>família visual</b> em toda geração.</div>
    {bk.extras && bk.extras.reference_profile && <div className="card" style={{ padding: 12 }}>
      <div style={{ fontWeight: 700 }}>Perfil extraído das referências</div>
      <div className="hint">
        {bk.extras.reference_profile.status === 'analyzing' ? 'Analisando as artes…' :
          `Logo institucional: ${bk.extras.reference_profile.logo_position || 'não identificada'} · ` +
          `${bk.extras.reference_profile.layout_direction || 'direção visual registrada'}`}
      </div>
      {!!(bk.extras.reference_profile.palette || []).length && <div className="row" style={{ gap: 5, marginTop: 8 }}>
        {bk.extras.reference_profile.palette.map((c, i) =>
          <span key={i} title={c} style={{ width: 24, height: 24, borderRadius: 6, background: c, border: '1px solid var(--line)' }} />)}
      </div>}
    </div>}
    <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <input className="inp" style={{ maxWidth: 240 }} placeholder="@perfil de referência" value={igHandle} onChange={e => setIgHandle(e.target.value)} />
      <span className="hint">Somente inspiração visual; o Instagram oficial da empresa entra na importação única.</span>
      <button className="btn sm pri" disabled={igBusy || !igHandle.trim()} onClick={importIg}>{igBusy ? 'Importando…' : 'Importar referências'}</button>
    </div>
    <input type="file" accept="image/*" onChange={e => e.target.files[0] && doUploadRef(e.target.files[0])} />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: 12 }}>
      {refs.map(r => <div key={r.id} style={{ position: 'relative' }}>
        <img loading="lazy" decoding="async" src={r.url} style={{ width: '100%', height: 100, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--line)' }} />
        <button onClick={() => doDeleteRef(r.id)} style={{ position: 'absolute', top: 4, right: 4, background: 'rgba(0,0,0,.7)', color: '#fff', border: 'none', borderRadius: 4, padding: '2px 6px', cursor: 'pointer', fontSize: 12 }}>✕</button>
      </div>)}
    </div>
  </div>;
}

function CompanyCriacao({ company }) {
  const [defaults, setDefaults] = React.useState(null);
  const [baseOv, setBaseOv] = React.useState({});   // override salvo
  const [edits, setEdits] = React.useState({});      // "g.k" -> string (campos tocados)
  const [msg, setMsg] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    window.mpApi.getCreativeConfig(company.id)
      .then(r => { setDefaults(r.defaults || {}); setBaseOv(r.override || {}); })
      .catch(e => setMsg('Erro: ' + (e.message || e)));
  }, [company.id]);

  if (!defaults) return <div className="hint">Carregando configuração criativa…</div>;

  const GROUPS = { briefing: 'Briefing / roteiro (carrossel e post)', image: 'Imagem — system prompt e cena', layout_policy: 'Layout (liberdade controlada)', brand_logo: 'Logo da marca', text_fit: 'Ajuste de texto', quality_guard: 'Controle de qualidade', design: 'Design do slide (avançado)' };
  const GROUP_HINTS = {
    briefing: 'Controla o plano/roteiro de carrossel e post. As configurações de VÍDEO ficam na aba "Vídeo".',
    image: 'Controla o prompt da imagem. O padrão abaixo preserva a qualidade atual; mude só para este cliente.',
  };
  const asStr = v => (v && typeof v === 'object') ? JSON.stringify(v, null, 2) : (v == null ? '' : String(v));
  const isObjKey = (g, k) => { const dv = (defaults[g] || {})[k]; return dv && typeof dv === 'object'; };
  function curStr(g, k) {
    const ek = g + '|' + k;
    if (edits[ek] !== undefined) return edits[ek];
    const ov = (baseOv[g] || {})[k];
    return asStr(ov !== undefined ? ov : (defaults[g] || {})[k]);
  }
  const overridden = (g, k) => (edits[g + '|' + k] !== undefined) || ((baseOv[g] || {})[k] !== undefined);
  const setStr = (g, k, v) => setEdits(s => ({ ...s, [g + '|' + k]: v }));
  function resetKey(g, k) {
    setEdits(s => { const n = { ...s }; delete n[g + '|' + k]; return n; });
    setBaseOv(s => { const gg = { ...(s[g] || {}) }; delete gg[k]; const n = { ...s, [g]: gg }; if (!Object.keys(gg).length) delete n[g]; return n; });
  }
  function buildOverride() {
    const out = JSON.parse(JSON.stringify(baseOv));
    for (const ek of Object.keys(edits)) {
      const i = ek.indexOf('|'); const g = ek.slice(0, i); const k = ek.slice(i + 1);
      let v = edits[ek];
      if (isObjKey(g, k)) { try { v = JSON.parse(edits[ek]); } catch (_) { throw new Error('JSON inválido em ' + g + ' › ' + k); } }
      out[g] = { ...(out[g] || {}), [k]: v };
    }
    return out;
  }
  async function save() {
    setBusy(true); setMsg('');
    try { const ov = buildOverride(); await window.mpApi.saveCreativeConfig(company.id, ov); setBaseOv(ov); setEdits({}); setMsg('Salvo! As próximas gerações deste cliente usam sua configuração.'); }
    catch (e) { setMsg('Erro: ' + (e.message || e)); } finally { setBusy(false); }
  }
  async function resetAll() {
    if (!window.confirm('Restaurar TODAS as configurações criativas deste cliente para o padrão?')) return;
    setBusy(true); setMsg('');
    try { await window.mpApi.saveCreativeConfig(company.id, {}); setBaseOv({}); setEdits({}); setMsg('Restaurado para o padrão.'); }
    catch (e) { setMsg('Erro: ' + (e.message || e)); } finally { setBusy(false); }
  }

  return <div className="stack">
    <div className="sec mut">Tudo que a IA usa pra criar (texto, imagem, vídeo, design) — <b>editável por cliente</b>. Mexa pra melhorar; em branco/“padrão” usa o default. Nada fica travado.</div>
    {Object.keys(GROUPS).map(g => {
      const keys = Object.keys(defaults[g] || {});
      if (!keys.length) return null;
      return <div key={g} className="panel stack">
        <b>{GROUPS[g]}</b>
        {GROUP_HINTS[g] && <div className="hint">{GROUP_HINTS[g]}</div>}
        {keys.map(k => <Field key={k} label={k + (overridden(g, k) ? '  ·  personalizado' : '  ·  padrão')}>
          <textarea className="inp" rows={isObjKey(g, k) ? 6 : 3} value={curStr(g, k)}
            onChange={e => setStr(g, k, e.target.value)}
            style={{ resize: 'vertical', fontFamily: isObjKey(g, k) ? 'monospace' : 'inherit', fontSize: 12 }} />
          {overridden(g, k) && <button className="btn sm ghost" onClick={() => resetKey(g, k)}>↺ voltar ao padrão</button>}
        </Field>)}
      </div>;
    })}
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <div className="row" style={{ gap: 8 }}>
      <button className="btn pri" disabled={busy} onClick={save}>{busy ? 'Salvando…' : 'Salvar configuração'}</button>
      <button className="btn ghost" disabled={busy} onClick={resetAll}>Restaurar tudo p/ padrão</button>
    </div>
  </div>;
}

function CompanyVideo({ company }) {
  // ÚNICA config de vídeo: o System Prompt — a estrutura que o briefing LÊ pra montar a instrução do vídeo.
  const [defaults, setDefaults] = React.useState(null);
  const [ov, setOv] = React.useState({});
  const [sys, setSys] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    window.mpApi.getCreativeConfig(company.id).then(r => {
      const d = r.defaults || {}, o = r.override || {};
      setDefaults(d); setOv(o);
      const ovv = o.video || {};
      setSys('system_prompt' in ovv ? (ovv.system_prompt || '') : ((d.video || {}).system_prompt || ''));
    }).catch(e => setMsg('Erro: ' + (e.message || e)));
  }, [company.id]);
  if (!defaults) return <div className="hint">Carregando configuração de vídeo…</div>;
  const dSys = (defaults.video || {}).system_prompt || '';
  async function save() {
    setBusy(true); setMsg('');
    try {
      const out = JSON.parse(JSON.stringify(ov));
      out.video = { ...(out.video || {}) };
      if (sys.trim() === dSys.trim()) delete out.video.system_prompt; else out.video.system_prompt = sys;
      if (!Object.keys(out.video).length) delete out.video;
      await window.mpApi.saveCreativeConfig(company.id, out);
      setOv(out); setMsg('Salvo! As próximas gerações de vídeo deste cliente usam este System Prompt.');
    } catch (e) { setMsg('Erro: ' + (e.message || e)); }
    finally { setBusy(false); }
  }
  return <div className="stack">
    <div className="sec mut">Configuração de <b>VÍDEO</b> — <b>só o System Prompt</b>. É a estrutura que o briefing LÊ pra montar a instrução que a IA usa pra fazer o vídeo. Nenhuma outra regra escondida.</div>
    <Field label={'System Prompt do vídeo' + (sys.trim() !== dSys.trim() ? '  ·  personalizado' : '  ·  padrão')}>
      <textarea className="inp" rows={14} value={sys} onChange={e => setSys(e.target.value)} style={{ resize: 'vertical', fontSize: 12 }} placeholder="A estrutura/instrução que o briefing usa pra montar o prompt do vídeo." />
      {sys.trim() !== dSys.trim() && <button className="btn sm ghost" onClick={() => setSys(dSys)}>↺ voltar ao padrão</button>}
    </Field>
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
    <button className="btn pri" disabled={busy} onClick={save}>{busy ? 'Salvando…' : 'Salvar System Prompt do vídeo'}</button>
  </div>;
}

function CompanyVoz({ company, onSaved }) {
  const bk = company.brand_kit || {};
  const [voice, setVoice] = React.useState(bk.voice || '');
  const [persona, setPersona] = React.useState(bk.persona || '');
  const [visual, setVisual] = React.useState(bk.visual_prompt_base || '');
  const [audience, setAudience] = React.useState(bk.audience || '');
  const [assuntos, setAssuntos] = React.useState(bk.assuntos || '');
  const [msg, setMsg] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [dirty, setDirty] = React.useState(false);
  const brandUpdatedAt = bk.updated_at || '';

  React.useEffect(() => {
    if (dirty) return;
    setVoice(bk.voice || '');
    setPersona(bk.persona || '');
    setVisual(bk.visual_prompt_base || '');
    setAudience(bk.audience || '');
    setAssuntos(bk.assuntos || '');
  }, [company.id, brandUpdatedAt, dirty]);

  async function save() {
    setSaving(true); setMsg('');
    try {
      await window.mpApi.saveBrandKit(company.id, { voice, persona, visual_prompt_base: visual, audience, assuntos });
      setDirty(false); setMsg('Salvo!'); onSaved();
    } catch (e) { setMsg('Erro: ' + e.message); }
    finally { setSaving(false); }
  }
  return <div className="stack">
    <div className="hint">A importação única no topo preenche estes campos. Aqui você apenas revisa e ajusta o texto final.</div>
    <Field label="Público & modelo de negócio (a IA segue isto à risca em todo conteúdo)"><textarea className="inp" rows={3} value={audience} onChange={e => { setAudience(e.target.value); setDirty(true); }} placeholder="Ex.: A Cariap vende SVAs para PROVEDORES de internet (ISPs), que revendem/agregam os apps ao plano dos assinantes. O conteúdo fala COM o provedor, posicionando os apps como valor agregado para reter e monetizar a base." style={{ resize: 'vertical' }} /></Field>
    <Field label="Tom de voz"><input className="inp" value={voice} onChange={e => { setVoice(e.target.value); setDirty(true); }} placeholder="Ex: próximo, confiante, sem jargão técnico" /></Field>
    <Field label="Persona da marca"><textarea className="inp" rows={4} value={persona} onChange={e => { setPersona(e.target.value); setDirty(true); }} placeholder="Descreva a persona..." style={{ resize: 'vertical' }} /></Field>
    <Field label="Base para prompt visual"><textarea className="inp" rows={3} value={visual} onChange={e => { setVisual(e.target.value); setDirty(true); }} placeholder="Ex: fundo branco, produto em destaque" style={{ resize: 'vertical' }} /></Field>
    <Field label="Assuntos / Pautas (um por linha — aparecem como sugestão na Criação)"><textarea className="inp" rows={5} value={assuntos} onChange={e => { setAssuntos(e.target.value); setDirty(true); }} placeholder={"Ex.:\nsegurança digital para a família\ncomo reter assinantes com apps\nentretenimento ilimitado no plano"} style={{ resize: 'vertical' }} /></Field>
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
  const [loading, setLoading] = React.useState(true);
  const [sel, setSel] = React.useState(null);

  const load = React.useCallback(() => {
    setLoading(true);
    window.mpApi.listPosts('DRAFT,REVIEW,APPROVED,SCHEDULED,PUBLISHED').then(r => { setPosts(r.posts || []); setLoading(false); }).catch(() => setLoading(false));
  }, []);
  React.useEffect(() => { if (window.mpApi) load(); }, [load]);

  async function transition(id, to) { try { await window.mpApi.transitionPost(id, to); load(); } catch (e) { alert(e.message); } }
  async function del(id) { if (!confirm('Excluir?')) return; try { await window.mpApi.deletePost(id); load(); } catch (e) { alert(e.message); } }

  const SL = { REVIEW: 'em revisão', DRAFT: 'rascunho', APPROVED: 'aprovado', SCHEDULED: 'agendado', PUBLISHED: 'publicado' };
  const order = { REVIEW: 0, DRAFT: 1, APPROVED: 2, SCHEDULED: 3, PUBLISHED: 4 };
  const byClient = {};
  posts.slice().sort((a, b) => (order[a.status] || 9) - (order[b.status] || 9)).forEach(p => { const k = p.company_name || '—'; (byClient[k] = byClient[k] || []).push(p); });
  const dt = (v) => v ? new Date(v).toLocaleString('pt-BR') : '';

  return <div className="app">
    <AppHead icon="shield" title="Central de Aprovação" desc="Revise, aprove ou devolva — separado por cliente. Clique para ver o post completo." right={<button className="btn sm ghost" onClick={load}><Icon name="refs" />Atualizar</button>} />
    {loading && <div className="hint">Carregando…</div>}
    {!loading && !posts.length && <div className="hint">Nenhum conteúdo na fila. Gere e envie peças em Conteúdo.</div>}
    {Object.entries(byClient).map(([client, items]) => <div key={client} className="stack" style={{ marginBottom: 8 }}>
      <div className="sec"><Icon name="building" />{client} ({items.length})</div>
      <div className="grid2">
        {items.map(p => <PostCard key={p.id} post={p} label={SL[p.status] || p.status} onTransition={transition} onDelete={del} onExpand={() => setSel(p)} />)}
      </div>
    </div>)}
    {sel && <div onClick={() => setSel(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'grid', placeItems: 'center', zIndex: 9999, padding: 16 }}>
      <div onClick={e => e.stopPropagation()} className="panel stack" style={{ maxWidth: 440, maxHeight: '92vh', overflow: 'auto' }}>
        <div className="row" style={{ justifyContent: 'space-between' }}><b>{sel.title || 'Post'}</b><button className="btn sm ghost" onClick={() => setSel(null)}><Icon name="x" /></button></div>
        {sel.media_url && <img loading="lazy" decoding="async" src={sel.media_url} style={{ width: '100%', borderRadius: 8, border: '1px solid var(--line)' }} />}
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <Pill kind={sel.status === 'PUBLISHED' || sel.status === 'APPROVED' ? 'good' : sel.status === 'REVIEW' ? 'warn' : 'cy'} dot>{SL[sel.status] || sel.status}</Pill>
          <Pill>{sel.company_name}</Pill>
          {(sel.networks || []).map(n => <Pill key={n} kind="cy">{n}</Pill>)}
        </div>
        {sel.review_decision && <div className="hint">Cliente: <b>{sel.review_decision === 'approved' ? 'aprovou 100%' : sel.review_decision === 'changes' ? 'ressalvas' : 'reprovou'}</b>{sel.reviewed_at ? ' em ' + dt(sel.reviewed_at) : ''}{sel.review_comment ? ' — ' + sel.review_comment : ''}</div>}
        {sel.published_at && <div className="hint">Publicado em {dt(sel.published_at)}</div>}
        {sel.scheduled_at && <div className="hint">Agendado para {dt(sel.scheduled_at)}</div>}
        <div style={{ whiteSpace: 'pre-wrap', fontSize: 14, color: 'var(--text2)' }}>{sel.copy}</div>
        {sel.hashtags && sel.hashtags.length > 0 && <div style={{ color: 'var(--accent)', fontSize: 13 }}>{sel.hashtags.join(' ')}</div>}
      </div>
    </div>}
  </div>;
}

function PostCard({ post, label, onTransition, onDelete, onExpand }) {
  const nets = (post.networks || []).join(', ');
  return <div className="panel stack" style={{ padding: 12 }}>
    {post.media_url && <img loading="lazy" decoding="async" src={post.media_url} onClick={onExpand} title="Clique para expandir" style={{ width: '100%', borderRadius: 8, cursor: 'zoom-in', border: '1px solid var(--line)' }} />}
    <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
      <div className="li-main"><b>{post.title || 'Sem título'}</b><small>{nets || '—'}</small></div>
      <Pill kind={post.status === 'PUBLISHED' || post.status === 'APPROVED' ? 'good' : post.status === 'REVIEW' ? 'warn' : 'cy'} dot>{label}</Pill>
    </div>
    {post.review_decision === 'changes' && <div style={{ background: '#3a2f10', color: '#ffd479', borderRadius: 8, padding: '8px 12px', fontSize: 13 }}>⚠ Cliente: ressalvas — {post.review_comment}</div>}
    {post.review_decision === 'rejected' && <div className="err">✕ Cliente reprovou — {post.review_comment}</div>}
    {post.review_decision === 'approved' && <div className="ok">✓ Cliente aprovou 100%</div>}
    <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, color: 'var(--text2)', maxHeight: 72, overflow: 'auto' }}>{post.copy}</div>
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
      <button className="btn sm ghost" onClick={onExpand}>Ver completo</button>
      {post.status === 'DRAFT' && <button className="btn sm" onClick={() => onTransition(post.id, 'REVIEW')}>Revisão</button>}
      {post.status === 'REVIEW' && <button className="btn sm pri" onClick={() => onTransition(post.id, 'APPROVED')}>Aprovar</button>}
      {post.status === 'REVIEW' && <button className="btn sm ghost" onClick={() => onTransition(post.id, 'DRAFT')}>Devolver</button>}
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

/* ── ACESSO & FUNÇÕES (SaaS): admin libera/bloqueia funções por cliente + cria os acessos ── */
function CompanyAcesso({ company, onSaved }) {
  // ESPELHA os grupos/apps do OS — o admin liga/desliga QUALQUER app por cliente.
  const APP_GROUPS = [
    ['Inteligência e Mídia', [['analyze', 'Analyze'], ['compare', 'Compare'], ['runs', 'Runs'], ['media', 'Arquivos'], ['referencia', 'Referência'], ['enhancer', 'Video Enhancer']]],
    ['Edição & Conteúdo', [['legenda', 'Legenda'], ['logo', 'Logo'], ['teaser', 'Teaser'], ['cortes', 'Cortes'], ['thumbnail', 'Thumbnail']]],
    ['Operação e Distribuição', [['conteudo', 'Conteúdo'], ['criacao', 'Criação'], ['publisher', 'Publicar'], ['calendar', 'Agenda']]],
    ['Gestão de Agência', [['painel', 'Painel'], ['clientes', 'Clientes'], ['acervo', 'Acervo'], ['trends', 'Tendências'], ['aprovacao', 'Aprovação'], ['concorrentes', 'Concorrentes'], ['financial', 'Financeiro'], ['notificacoes', 'Notificações'], ['settings', 'Settings']]],
    ['Fluxo rápido', [['auto', 'Modo rápido'], ['autoeditor', 'AutoEditor'], ['wizard', 'Assistente']]],
  ];
  const IA_CAPS = [['video', 'Criar vídeo'], ['animar', 'Animar imagem'], ['editar_arte', 'Editar com IA'], ['estudio', 'Estúdio IA (referências)']];
  const CLIENT_DEFAULT = ['conteudo', 'criacao', 'publisher', 'calendar', 'clientes', 'acervo', 'aprovacao', 'notificacoes', 'wizard', 'video', 'animar', 'editar_arte', 'estudio'];
  const isOn = (f, k) => f[k] === true || (f[k] === undefined && CLIENT_DEFAULT.includes(k));
  const initF = (() => { try { return typeof company.features === 'string' ? JSON.parse(company.features || '{}') : (company.features || {}); } catch (e) { return {}; } })();
  const [feats, setFeats] = React.useState(initF);
  const [maxVer, setMaxVer] = React.useState(initF.versoes_max || 2);
  const [msg, setMsg] = React.useState('');
  const [users, setUsers] = React.useState([]);
  const [nu, setNu] = React.useState({ username: '', password: '', tipo: 'owner' });
  const loadUsers = React.useCallback(() => {
    window.mpApi.listAuthUsers().then(r => {
      const all = (r && r.users) || [];
      setUsers(all.filter(u => u.company_id === company.id || (u.role === 'agency' && company.owner_user_id === u.user_id)));
    }).catch(() => {});
  }, [company.id]);
  React.useEffect(() => { loadUsers(); }, [loadUsers]);
  async function saveFeats() {
    setMsg('');
    try {
      const full = { ...feats };
      APP_GROUPS.forEach(([, apps]) => apps.forEach(([k]) => { full[k] = isOn(feats, k); }));
      IA_CAPS.forEach(([k]) => { full[k] = isOn(feats, k); });
      full.versoes_max = Number(maxVer) || 2;
      await window.mpApi.setCompanyFeatures(company.id, full);
      setMsg('✓ Funções salvas. O cliente vê as bloqueadas apagadinhas com aviso de plano.');
      onSaved && onSaved();
    } catch (e) { setMsg('Erro: ' + e.message); }
  }
  async function criarAcesso() {
    setMsg('');
    if (!nu.username || !nu.password) { setMsg('Informe e-mail/usuário e senha.'); return; }
    try {
      const payload = { username: nu.username.trim(), password: nu.password, role: nu.tipo };
      if (nu.tipo === 'owner') payload.company_id = company.id;
      const r = await window.mpApi.createAuthUser(payload);
      if (r && r.error) { setMsg('Erro: ' + r.error); return; }
      if (nu.tipo === 'agency' && r && r.user) {
        try { await window.mpApi.updateCompany(company.id, { owner_user_id: r.user.user_id }); } catch (e) {}
      }
      setNu({ username: '', password: '', tipo: 'owner' }); setMsg('✓ Acesso criado.'); loadUsers();
    } catch (e) { setMsg('Erro: ' + e.message); }
  }
  return <div className="stack">
    <div className="sec"><Icon name="shield" />Funções liberadas para este cliente</div>
    <div className="hint">Desmarcadas ficam <b>apagadinhas</b> pro cliente, com o aviso: "Função não liberada no seu plano. Chame o seu consultor de vendas."</div>
    {APP_GROUPS.map(([gname, apps]) => <div key={gname} className="panel stack" style={{ gap: 6 }}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <b style={{ fontSize: 13 }}>{gname}</b>
        <span className="row" style={{ gap: 6 }}>
          <button className="btn sm ghost" onClick={() => setFeats(f => { const n = { ...f }; apps.forEach(([k]) => n[k] = true); return n; })}>liberar tudo</button>
          <button className="btn sm ghost" onClick={() => setFeats(f => { const n = { ...f }; apps.forEach(([k]) => n[k] = false); return n; })}>bloquear tudo</button>
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 6 }}>
        {apps.map(([k, l]) => <label key={k} className="row" style={{ gap: 8, alignItems: 'center', cursor: 'pointer' }}>
          <input type="checkbox" checked={isOn(feats, k)} onChange={e => setFeats(f => ({ ...f, [k]: e.target.checked }))} />
          <span>{l}</span>
        </label>)}
      </div>
    </div>)}
    <div className="panel stack" style={{ gap: 6 }}>
      <b style={{ fontSize: 13 }}>Capacidades de IA</b>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: 6 }}>
        {IA_CAPS.map(([k, l]) => <label key={k} className="row" style={{ gap: 8, alignItems: 'center', cursor: 'pointer' }}>
          <input type="checkbox" checked={isOn(feats, k)} onChange={e => setFeats(f => ({ ...f, [k]: e.target.checked }))} />
          <span>{l}</span>
        </label>)}
      </div>
    </div>
    <Field label="Máximo de versões por geração (menos é mais pro cliente)">
      <select className="inp" style={{ maxWidth: 120 }} value={maxVer} onChange={e => setMaxVer(e.target.value)}>
        {[1, 2, 3, 4].map(n => <option key={n} value={n}>{n}</option>)}
      </select>
    </Field>
    <button className="btn sm pri" onClick={saveFeats}>Salvar funções</button>
    <div className="sec" style={{ marginTop: 14 }}><Icon name="users" />Acessos deste cliente</div>
    <div className="hint"><b>Cliente final</b> = usa a plataforma só para esta empresa. <b>Agência</b> = compra o software e cadastra os próprios clientes (esta empresa vira o 1º cliente dela).</div>
    <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <select className="inp" style={{ maxWidth: 230 }} value={nu.tipo} onChange={e => setNu(v => ({ ...v, tipo: e.target.value }))}>
        <option value="owner">Cliente final (só esta empresa)</option>
        <option value="agency">Agência (cadastra clientes próprios)</option>
      </select>
      <input className="inp" style={{ maxWidth: 240 }} placeholder="e-mail / usuário" value={nu.username} onChange={e => setNu(v => ({ ...v, username: e.target.value }))} />
      <input className="inp" style={{ maxWidth: 180 }} type="password" placeholder="senha" value={nu.password} onChange={e => setNu(v => ({ ...v, password: e.target.value }))} />
      <button className="btn sm pri" onClick={criarAcesso}>Criar acesso</button>
    </div>
    {users.length > 0 && <div className="stack" style={{ gap: 6 }}>
      {users.map(u => <div key={u.user_id} className="litem" style={{ padding: 10 }}>
        <div className="li-main"><b>{u.username}</b><small>{u.role === 'agency' ? 'Agência' : 'Cliente final'} · {u.active ? 'ativo' : 'inativo'}</small></div>
        <button className="btn sm ghost" onClick={async () => { const p = prompt('Nova senha para ' + u.username + ':'); if (p) { await window.mpApi.resetAuthPassword(u.user_id, p); setMsg('✓ Senha redefinida.'); } }}>Redefinir senha</button>
      </div>)}
    </div>}
    {msg && <div className={msg.startsWith('Erro') ? 'err' : 'ok'}>{msg}</div>}
  </div>;
}
