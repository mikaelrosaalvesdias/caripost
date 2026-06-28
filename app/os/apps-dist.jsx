/* Caripost OS — Operação & Distribuição: Telegram, Publicar, Calendário */

/* ── TELEGRAM — grupos reais e disparo real ── */
function TelegramApp() {
  const [groups, setGroups] = React.useState([]);
  const [connected, setConnected] = React.useState(false);
  const [selGroup, setSelGroup] = React.useState('');
  const [caption, setCaption] = React.useState('');
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [sending, setSending] = React.useState(false);
  const [sentMsg, setSentMsg] = React.useState('');

  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.telegramSettings().then(s => {
      const gs = s.groups || [];
      setGroups(gs);
      setConnected(!!(s.n8n_webhook_url || s.webhook_url || gs.length));
      if (gs.length) setSelGroup(gs[0].chat_id || gs[0].id || '');
    }).catch(() => {});
  }, []);

  async function sendNow() {
    if (!file) { alert('Selecione um teaser/vídeo primeiro.'); return; }
    if (!selGroup) { alert('Selecione um grupo.'); return; }
    setSending(true); setSentMsg('');
    try {
      const r = await window.mpApi.telegramSendNow({
        chat_id: selGroup,
        teaser_object_key: file.object_key,
        caption: caption || file.n,
      });
      if (r.ok) setSentMsg('✓ Enviado com sucesso!');
      else setSentMsg('✗ ' + (r.error || 'Falha no envio'));
    } catch (e) { setSentMsg('✗ ' + e.message); }
    finally { setSending(false); }
  }

  return <div className="app">
    <AppHead icon="telegram" title="Telegram" desc="Dispare teasers e posts direto para seus grupos e canais de assinantes."
      right={<Pill kind={connected ? 'cy' : 'warn'} dot>{connected ? 'bot conectado' : 'não configurado'}</Pill>} />
    <div className="grid3">
      <div className="stat"><div className="sv">{groups.length}</div><div className="sl">Grupos cadastrados</div></div>
      <div className="stat"><div className="sv">{connected ? 'ON' : 'OFF'}</div><div className="sl">Webhook</div></div>
      <div className="stat"><div className="sv">{file ? '1' : '0'}</div><div className="sl">Mídia selecionada</div></div>
    </div>
    <div className="split">
      <div className="stack">
        <div className="sec mut"><Icon name="users" />Grupos &amp; canais</div>
        {!groups.length && <div className="hint">Nenhum grupo cadastrado. Configure o webhook e os grupos em Settings → Telegram.</div>}
        {groups.map(g => <div key={g.chat_id || g.id} className="litem" style={{ cursor: 'pointer', borderColor: selGroup === (g.chat_id || g.id) ? 'var(--cyan)' : undefined }} onClick={() => setSelGroup(g.chat_id || g.id)}>
          <span className="li-ic"><Icon name="telegram" /></span>
          <div className="li-main"><b>{g.name || g.title || g.chat_id}</b><small>{g.chat_id || g.id}</small></div>
          {selGroup === (g.chat_id || g.id) && <Pill kind="cy" dot>selecionado</Pill>}
        </div>)}
      </div>
      <div className="stack">
        <div className="sec mut"><Icon name="send" />Disparo</div>
        <CtxFileBar file={file} onPick={() => setPicking(p => !p)} />
        {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); window.mpCtx.file = f; setPicking(false); }} />}
        <Field label="Legenda do post"><textarea className="inp" rows="3" placeholder="Texto que acompanha o vídeo…" value={caption} onChange={e => setCaption(e.target.value)} /></Field>
        {sentMsg && <div className="panel" style={{ borderColor: sentMsg.startsWith('✓') ? 'rgba(0,230,118,.3)' : 'var(--pri-line)' }}>
          <span style={{ color: sentMsg.startsWith('✓') ? 'var(--good)' : 'var(--pri)', fontSize: 13 }}>{sentMsg}</span>
        </div>}
        <button className="btn pri block" disabled={sending || !file || !selGroup} onClick={sendNow}><Icon name="send" />{sending ? 'Enviando…' : 'Enviar agora'}</button>
      </div>
    </div>
  </div>;
}

const SOCIAL_PLATFORMS = ['instagram', 'facebook', 'youtube', 'tiktok'];

/* ── PUBLICAR — distribuição real nas plataformas ── */
function PublisherApp() {
  const [platforms, setPlatforms] = React.useState([]);
  const [selPlats, setSelPlats] = React.useState([]);
  const [creators, setCreators] = React.useState([]);
  const [companies, setCompanies] = React.useState([]);
  const [selCreator, setSelCreator] = React.useState('');
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [title, setTitle] = React.useState('');
  const [phase, setPhase] = React.useState('idle');
  const [statusMsg, setStatusMsg] = React.useState('');
  const [socialConfig, setSocialConfig] = React.useState({ platforms: SOCIAL_PLATFORMS });
  const [socialBrand, setSocialBrand] = React.useState('');
  const [socialAccounts, setSocialAccounts] = React.useState([]);
  const [socialSelected, setSocialSelected] = React.useState([]);
  const [socialTitle, setSocialTitle] = React.useState('');
  const [socialCaption, setSocialCaption] = React.useState('');
  const [socialAssetUrl, setSocialAssetUrl] = React.useState('');
  const [socialContentType, setSocialContentType] = React.useState('image');
  const [socialScheduleAt, setSocialScheduleAt] = React.useState('');
  const [socialApproved, setSocialApproved] = React.useState(false);
  const [socialMsg, setSocialMsg] = React.useState('');
  const [socialBusy, setSocialBusy] = React.useState(false);
  const [competitors, setCompetitors] = React.useState([]);
  const [competitorName, setCompetitorName] = React.useState('');
  const [competitorHandle, setCompetitorHandle] = React.useState('');
  const [references, setReferences] = React.useState([]);
  const [referenceUrl, setReferenceUrl] = React.useState('');
  const pollRef = React.useRef(null);
  const socialPollRef = React.useRef(null);

  const brandOptions = React.useMemo(() => [
    ...companies.map(c => ({ id: c.id, name: c.name, kind: 'cliente' })),
  ], [companies]);

  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.publisherPlatforms().then(p => {
      const list = Array.isArray(p) ? p : Object.keys(p || {});
      const social = list.filter(x => SOCIAL_PLATFORMS.includes(x));
      setPlatforms(social.length ? social : SOCIAL_PLATFORMS);   // só redes sociais, sem plataformas adultas
    }).catch(() => setPlatforms(SOCIAL_PLATFORMS));
    window.mpApi.listCreators().then(c => {
      setCreators(c);
      if (c.length) setSelCreator(c[0].creator_id);
    }).catch(() => {});
    window.mpApi.listCompanies().then(c => setCompanies(c || [])).catch(() => {});
    window.mpApi.socialConfig().then(setSocialConfig).catch(() => {});
    // Pré-carrega título do run se houver
    const ctx = window.mpCtx?.file;
    if (ctx?.run_id && window.mpApi) {
      window.mpApi.getRun(ctx.run_id).then(d => {
        const t = d.result?.grok?.title;
        if (t) { setTitle(t); setSocialTitle(t); }
      }).catch(() => {});
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (socialPollRef.current) clearInterval(socialPollRef.current);
    };
  }, []);

  React.useEffect(() => {
    if (!socialBrand && brandOptions.length) setSocialBrand(brandOptions[0].id);
  }, [socialBrand, brandOptions]);

  const loadSocial = React.useCallback(() => {
    if (!window.mpApi || !socialBrand) return;
    window.mpApi.socialAccounts(socialBrand).then(a => {
      setSocialAccounts(a || []);
      setSocialSelected(prev => prev.filter(id => (a || []).some(acc => acc.id === id)));
    }).catch(() => {});
    window.mpApi.socialCompetitors(socialBrand).then(setCompetitors).catch(() => setCompetitors([]));
    window.mpApi.socialReferences(socialBrand).then(setReferences).catch(() => setReferences([]));
  }, [socialBrand]);

  React.useEffect(() => { loadSocial(); }, [loadSocial]);

  async function connectSocial(platform) {
    if (!socialBrand) { alert('Selecione uma marca/cliente.'); return; }
    setSocialBusy(true); setSocialMsg('Abrindo conexão ' + platform + '…');
    try {
      const callbackUrl = window.location.origin + '/api/social/callback';
      const r = await window.mpApi.socialConnect({ brandId: socialBrand, platform, callbackUrl });
      if (r.redirect_url) window.open(r.redirect_url, '_blank', 'noopener,noreferrer');
      setSocialMsg(r.redirect_url ? 'Conexão aberta em nova aba. Depois de autorizar, atualize os canais.' : 'Conexão registrada.');
      setTimeout(loadSocial, 1200);
    } catch (e) { setSocialMsg('Erro: ' + e.message); }
    finally { setSocialBusy(false); }
  }

  async function disconnectSocial(id) {
    if (!confirm('Desconectar este canal?')) return;
    setSocialBusy(true);
    try { await window.mpApi.socialDisconnect(id); setSocialMsg('Canal desconectado.'); loadSocial(); }
    catch (e) { setSocialMsg('Erro: ' + e.message); }
    finally { setSocialBusy(false); }
  }

  function toggleSocialChannel(id) {
    setSocialSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  async function submitSocial(publishNow) {
    if (!socialBrand) { alert('Selecione uma marca/cliente.'); return; }
    if (!socialSelected.length) { alert('Selecione ao menos um canal conectado.'); return; }
    if (!socialApproved) { alert('A publicação precisa estar aprovada.'); return; }
    const channels = socialAccounts.filter(a => socialSelected.includes(a.id)).map(a => ({
      socialConnectionId: a.id,
      platform: a.platform,
    }));
    setSocialBusy(true); setSocialMsg(publishNow ? 'Enviando para publicação…' : 'Agendando publicação…');
    try {
      const payload = {
        brandId: socialBrand,
        title: socialTitle,
        caption: socialCaption,
        contentType: socialContentType,
        assetUrls: socialAssetUrl.trim() ? [socialAssetUrl.trim()] : [],
        channels,
        scheduledAt: publishNow ? null : (socialScheduleAt ? new Date(socialScheduleAt).toISOString() : null),
        approved: true,
      };
      const r = await window.mpApi.socialCreatePost(payload);
      const id = r.post?.id;
      setSocialMsg(id ? `Post social ${id.slice(0, 8)} criado.` : 'Post social criado.');
      if (id && publishNow) pollSocialPost(id);
    } catch (e) { setSocialMsg('Erro: ' + e.message); }
    finally { setSocialBusy(false); }
  }

  function pollSocialPost(postId) {
    if (socialPollRef.current) clearInterval(socialPollRef.current);
    socialPollRef.current = setInterval(async () => {
      try {
        const r = await window.mpApi.socialPostStatus(postId);
        const st = r.post?.status || '';
        setSocialMsg('Status social: ' + st);
        if (['published', 'failed', 'partial_failed', 'cancelled'].includes(st)) {
          clearInterval(socialPollRef.current);
          socialPollRef.current = null;
        }
      } catch (_) {}
    }, 3500);
  }

  async function addCompetitor() {
    if (!competitorName.trim()) return;
    setSocialBusy(true);
    try {
      await window.mpApi.socialAddCompetitor({ brandId: socialBrand, name: competitorName.trim(), instagram: competitorHandle.trim() });
      setCompetitorName(''); setCompetitorHandle(''); loadSocial();
    } catch (e) { setSocialMsg('Erro: ' + e.message); }
    finally { setSocialBusy(false); }
  }

  async function analyzeCompetitor(id) {
    setSocialBusy(true); setSocialMsg('Analisando concorrente…');
    try { await window.mpApi.socialAnalyzeCompetitor(id); setSocialMsg('Análise registrada.'); loadSocial(); }
    catch (e) { setSocialMsg('Erro: ' + e.message); }
    finally { setSocialBusy(false); }
  }

  async function addReference() {
    if (!referenceUrl.trim()) return;
    setSocialBusy(true);
    try {
      await window.mpApi.socialAddReference({ brandId: socialBrand, url: referenceUrl.trim(), platform: 'social' });
      setReferenceUrl(''); loadSocial();
    } catch (e) { setSocialMsg('Erro: ' + e.message); }
    finally { setSocialBusy(false); }
  }

  async function publish() {
    if (!file) { alert('Selecione um vídeo.'); return; }
    if (!selCreator) { alert('Selecione um criador.'); return; }
    if (!selPlats.length) { alert('Selecione ao menos uma plataforma.'); return; }
    setPhase('running'); setStatusMsg('Iniciando publicação…');
    try {
      const r = await window.mpApi.publish({
        creator_id: selCreator,
        video_object_key: file.object_key,
        platforms: selPlats,
        title: title || file.n,
      });
      const jobId = r.job_id;
      if (!jobId) { setPhase(r.ok ? 'done' : 'error'); setStatusMsg(r.ok ? 'Publicado!' : (r.detail || r.error || 'Erro')); return; }
      pollRef.current = setInterval(async () => {
        try {
          const st = await window.mpApi.publishStatus(jobId);
          setStatusMsg(st.detail || st.status || 'Publicando…');
          if (st.status === 'done') { clearInterval(pollRef.current); setPhase('done'); setStatusMsg('✓ Publicado nas plataformas!'); }
          else if (st.status === 'error') { clearInterval(pollRef.current); setPhase('error'); setStatusMsg(st.detail || 'Erro'); }
        } catch (_) {}
      }, 4000);
    } catch (e) { setPhase('error'); setStatusMsg(e.message); }
  }

  return <div className="app">
    <AppHead icon="broadcast" title="Publicação" desc="Canais sociais, referências, concorrentes e distribuição oficial via provider." />

    <div className="split">
      <div className="stack">
        <div className="sec cy"><Icon name="link" />Canais conectados</div>
        <Field label="Marca / cliente">
          <select className="inp" value={socialBrand} onChange={e => setSocialBrand(e.target.value)}>
            {!brandOptions.length && <option value="">Nenhuma marca</option>}
            {brandOptions.map(b => <option key={b.kind + b.id} value={b.id}>{b.name} · {b.kind}</option>)}
          </select>
        </Field>
        <div className="grid2">
          {(socialConfig.platforms || SOCIAL_PLATFORMS).map(platform => (
            <button key={platform} className="btn" disabled={socialBusy || !socialBrand} onClick={() => connectSocial(platform)}>
              <Icon name="plus" />{platform}
            </button>
          ))}
        </div>
        {!socialAccounts.length && <div className="hint">Nenhum canal conectado para esta marca.</div>}
        {socialAccounts.map(acc => {
          const on = socialSelected.includes(acc.id);
          return <div key={acc.id} className="litem" style={{ cursor: 'pointer', borderColor: on ? 'var(--cyan)' : undefined }} onClick={() => toggleSocialChannel(acc.id)}>
            <span className="li-ic"><Icon name="broadcast" /></span>
            <div className="li-main"><b style={{ textTransform: 'capitalize' }}>{acc.platform}</b><small>{acc.external_account_name || acc.external_account_id || acc.status}</small></div>
            <Pill kind={acc.status === 'connected' || acc.status === 'active' ? 'good' : 'warn'} dot>{acc.status}</Pill>
            <button className="btn sm" onClick={e => { e.stopPropagation(); disconnectSocial(acc.id); }}>Desconectar</button>
          </div>;
        })}
      </div>

      <div className="stack">
        <div className="sec mut"><Icon name="send" />Agendamento / publicação social</div>
        <Field label="Título"><input className="inp" value={socialTitle} onChange={e => setSocialTitle(e.target.value)} /></Field>
        <Field label="Legenda"><textarea className="inp" rows="3" value={socialCaption} onChange={e => setSocialCaption(e.target.value)} /></Field>
        <Field label="URL pública da mídia ou referência">
          <input className="inp" value={socialAssetUrl} onChange={e => setSocialAssetUrl(e.target.value)} placeholder="https://..." />
        </Field>
        <div className="grid2">
          <Field label="Tipo">
            <select className="inp" value={socialContentType} onChange={e => setSocialContentType(e.target.value)}>
              <option value="image">Imagem</option><option value="video">Vídeo</option><option value="carousel">Carrossel</option><option value="text">Texto</option>
            </select>
          </Field>
          <Field label="Agendar">
            <input className="inp" type="datetime-local" value={socialScheduleAt} onChange={e => setSocialScheduleAt(e.target.value)} />
          </Field>
        </div>
        <label className="litem" style={{ cursor: 'pointer' }}>
          <Check on={socialApproved} onClick={() => setSocialApproved(v => !v)} />
          <div className="li-main"><b>Conteúdo aprovado</b><small>Obrigatório para publicar ou agendar.</small></div>
        </label>
        {socialMsg && <div className="panel"><span style={{ fontSize: 13 }}>{socialMsg}</span></div>}
        <div className="rowx" style={{ gap: 8 }}>
          <button className="btn pri" disabled={socialBusy} onClick={() => submitSocial(true)}><Icon name="broadcast" />Publicar agora</button>
          <button className="btn" disabled={socialBusy || !socialScheduleAt} onClick={() => submitSocial(false)}><Icon name="clock" />Agendar</button>
        </div>
      </div>
    </div>

    <div className="split" style={{ marginTop: 14 }}>
      <div className="stack">
        <div className="sec mut"><Icon name="sparkles" />Concorrentes</div>
        <div className="grid2">
          <input className="inp" value={competitorName} onChange={e => setCompetitorName(e.target.value)} placeholder="Nome" />
          <input className="inp" value={competitorHandle} onChange={e => setCompetitorHandle(e.target.value)} placeholder="@instagram ou URL" />
        </div>
        <button className="btn" disabled={socialBusy || !socialBrand} onClick={addCompetitor}><Icon name="plus" />Adicionar concorrente</button>
        {competitors.slice(0, 8).map(c => <div key={c.id} className="litem">
          <span className="li-ic"><Icon name="users" /></span>
          <div className="li-main"><b>{c.name}</b><small>{Object.values(c.handles || {}).filter(Boolean).join(' · ') || 'sem handle'}</small></div>
          <button className="btn sm" disabled={socialBusy} onClick={() => analyzeCompetitor(c.id)}>Analisar</button>
        </div>)}
      </div>
      <div className="stack">
        <div className="sec mut"><Icon name="image" />Referências</div>
        <div className="rowx" style={{ gap: 8 }}>
          <input className="inp" value={referenceUrl} onChange={e => setReferenceUrl(e.target.value)} placeholder="Link de referência" />
          <button className="btn" disabled={socialBusy || !socialBrand} onClick={addReference}><Icon name="plus" />Salvar</button>
        </div>
        {references.slice(0, 8).map(r => <div key={r.id} className="litem">
          <span className="li-ic"><Icon name="link" /></span>
          <div className="li-main"><b>{r.meta?.title || r.kind || 'Referência'}</b><small>{r.url}</small></div>
        </div>)}
      </div>
    </div>

    <div className="sec mut" style={{ marginTop: 18 }}>Publicação legada</div>
    <div className="split">
      <div className="stack">
        <div className="sec cy">Vídeo a publicar</div>
        <CtxFileBar file={file} onPick={() => setPicking(p => !p)} />
        {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); window.mpCtx.file = f; setPicking(false); }} />}
        {file && <RealPlayer objectKey={file.object_key} style={{ maxHeight: 280 }} />}
        <Field label="Título"><input className="inp" value={title} onChange={e => setTitle(e.target.value)} placeholder="Título da publicação" /></Field>
        <Field label="Criador">
          <select className="inp" value={selCreator} onChange={e => setSelCreator(e.target.value)}>
            {!creators.length && <option value="">Nenhum criador</option>}
            {creators.map(c => <option key={c.creator_id} value={c.creator_id}>{c.n}</option>)}
          </select>
        </Field>
      </div>
      <div className="stack">
        <div className="sec mut">Plataformas de destino</div>
        {!platforms.length && <div className="hint">Carregando plataformas…</div>}
        {platforms.map(p => {
          const name = typeof p === 'string' ? p : (p.name || p.id);
          const on = selPlats.includes(name);
          return <div key={name} className="litem" style={{ cursor: 'pointer', borderColor: on ? 'var(--cyan)' : undefined }}
            onClick={() => setSelPlats(prev => on ? prev.filter(x => x !== name) : [...prev, name])}>
            <span className="li-ic"><Icon name="globe" /></span>
            <div className="li-main"><b style={{ textTransform: 'capitalize' }}>{name}</b></div>
            <Check on={on} onClick={e => { e && e.stopPropagation && e.stopPropagation(); }} />
          </div>;
        })}
        {phase === 'running' && <div className="panel"><ProgressBar pct={60} tone="cy" label={statusMsg} /></div>}
        {phase === 'error' && <div className="panel" style={{ borderColor: 'var(--pri-line)' }}><span style={{ color: 'var(--pri)', fontSize: 13 }}>✗ {statusMsg}</span></div>}
        {phase === 'done' && <div className="panel" style={{ borderColor: 'rgba(0,230,118,.3)' }}><span style={{ color: 'var(--good)', fontSize: 13 }}>{statusMsg}</span></div>}
        <button className="btn pri block" disabled={phase === 'running'} onClick={publish}><Icon name="broadcast" />{phase === 'running' ? 'Publicando…' : `Publicar em ${selPlats.length || 0} plataforma(s)`}</button>
      </div>
    </div>
  </div>;
}

/* ── CALENDÁRIO EDITORIAL ── */
function CalendarApp() {
  const [posts, setPosts] = React.useState([]);
  const [companies, setCompanies] = React.useState([]);
  const [companyId, setCompanyId] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [sel, setSel] = React.useState(null);
  const [ref, setRef] = React.useState(new Date());

  const load = React.useCallback(() => {
    if (!window.mpApi) return;
    setLoading(true);
    window.mpApi.listPosts().then(r => { setPosts((r.posts || []).filter(p => ['SCHEDULED', 'PUBLISHED'].includes(p.status))); setLoading(false); }).catch(() => setLoading(false));
    window.mpApi.listCompanies().then(c => setCompanies(c || [])).catch(() => {});
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const dateOf = (p) => p.scheduled_at || p.published_at;
  const fmt = (p) => { const d = dateOf(p); return d ? new Date(d).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'; };
  const fil = posts.filter(p => !companyId || p.company_id === companyId);
  const year = ref.getFullYear(), month = ref.getMonth();
  const startDow = (new Date(year, month, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const byDay = {};
  fil.forEach(p => { const d = dateOf(p); if (d) { const dt = new Date(d); if (dt.getFullYear() === year && dt.getMonth() === month) (byDay[dt.getDate()] = byDay[dt.getDate()] || []).push(p); } });
  const td = new Date();
  const isToday = (d) => td.getFullYear() === year && td.getMonth() === month && td.getDate() === d;
  const monthLabel = ref.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
  const cells = [];
  for (let i = 0; i < startDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  return <div className="app">
    <AppHead icon="calendar" title="Agenda" desc="Posts agendados e publicados, por dia." right={
      <select className="inp" value={companyId} onChange={e => setCompanyId(e.target.value)} style={{ maxWidth: 200 }}>
        <option value="">Todos os clientes</option>
        {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>} />
    <div className="split">
      <div className="panel">
        <div className="rowx" style={{ justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <button className="btn sm ghost" onClick={() => setRef(new Date(year, month - 1, 1))}>‹</button>
          <b style={{ textTransform: 'capitalize' }}>{monthLabel}</b>
          <button className="btn sm ghost" onClick={() => setRef(new Date(year, month + 1, 1))}>›</button>
        </div>
        <div className="cal">
          {['S', 'T', 'Q', 'Q', 'S', 'S', 'D'].map((d, i) => <div key={i} className="dow">{d}</div>)}
          {cells.map((d, i) => <div key={i} className={'cell' + (!d ? ' out' : '') + (d && isToday(d) ? ' today' : '')} onClick={() => d && byDay[d] && setSel(byDay[d][0])} style={{ cursor: d && byDay[d] ? 'pointer' : 'default' }}>
            {d || ''}
            {d && byDay[d] && <span className={'ev ' + (byDay[d].some(p => p.status === 'PUBLISHED') ? 'pri' : '')} />}
          </div>)}
        </div>
        <div className="rowx" style={{ marginTop: 12, fontSize: 11.5, color: 'var(--muted)', gap: 12 }}>
          <span className="rowx" style={{ gap: 5 }}><span style={{ width: 9, height: 9, borderRadius: 3, background: 'var(--pri)' }} />publicado</span>
          <span className="rowx" style={{ gap: 5 }}><span style={{ width: 9, height: 9, borderRadius: 3, background: 'var(--cyan)' }} />agendado</span>
        </div>
      </div>
      <div className="stack">
        <div className="sec mut"><Icon name="clock" />Posts ({fil.length})</div>
        {loading && <div className="hint">Carregando…</div>}
        {!loading && !fil.length && <div className="hint">Nenhum post agendado ou publicado ainda. Agende/publique em Conteúdo → Agendamento.</div>}
        {fil.slice().sort((a, b) => (dateOf(b) || '').localeCompare(dateOf(a) || '')).map(p => <div key={p.id} className="litem" style={{ cursor: 'pointer', gap: 8 }} onClick={() => setSel(p)}>
          {p.media_url ? <img loading="lazy" decoding="async" src={p.media_url} style={{ width: 44, height: 44, objectFit: 'cover', borderRadius: 6 }} /> : <span className="li-ic"><Icon name="post" /></span>}
          <div className="li-main"><b>{p.title || 'Post'}</b><small>{fmt(p)} · {(p.networks || []).join(', ')}</small></div>
          <Pill kind={p.status === 'PUBLISHED' ? 'good' : 'cy'} dot>{p.status === 'PUBLISHED' ? 'publicado' : 'agendado'}</Pill>
        </div>)}
      </div>
    </div>
    {sel && <div onClick={() => setSel(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'grid', placeItems: 'center', zIndex: 9999, padding: 16 }}>
      <div onClick={e => e.stopPropagation()} className="panel stack" style={{ maxWidth: 420, maxHeight: '90vh', overflow: 'auto' }}>
        <div className="rowx" style={{ justifyContent: 'space-between' }}><b>{sel.title || 'Post'}</b><button className="btn sm ghost" onClick={() => setSel(null)}><Icon name="x" /></button></div>
        {sel.media_url && <img loading="lazy" decoding="async" src={sel.media_url} style={{ width: '100%', borderRadius: 8 }} />}
        <Pill kind={sel.status === 'PUBLISHED' ? 'good' : 'cy'} dot>{sel.status === 'PUBLISHED' ? 'publicado' : 'agendado'} · {fmt(sel)}</Pill>
        <div className="hint" style={{ whiteSpace: 'pre-wrap' }}>{sel.copy}</div>
        <div className="hint">Redes: {(sel.networks || []).join(', ') || '—'}</div>
      </div>
    </div>}
  </div>;
}

/* Linha de publicação agendada — remarcar / excluir */
function CalendarEntryRow({ entry, onDelete, onReschedule }) {
  const [editing, setEditing] = React.useState(false);
  const [val, setVal] = React.useState(entry.publish_at ? entry.publish_at.slice(0, 16) : '');
  return <div className="litem" style={{ flexWrap: 'wrap', gap: 8 }}>
    <span className="li-ic"><Icon name="post" /></span>
    <div className="li-main"><b>{entry.t}</b><small>{entry.c} · {entry.d} · {entry.plat}</small></div>
    <Pill kind={entry.tone} dot>{entry.s}</Pill>
    {editing ? <>
      <input className="inp" type="datetime-local" style={{ height: 32, fontSize: 12, width: 175 }} value={val} onChange={e => setVal(e.target.value)} />
      <button className="btn sm pri" onClick={() => { onReschedule(new Date(val).toISOString()); setEditing(false); }}>Salvar</button>
      <button className="btn sm ghost" onClick={() => setEditing(false)}>Cancelar</button>
    </> : <>
      <button className="btn sm ghost" onClick={() => setEditing(true)}><Icon name="clock" />Remarcar</button>
      <button className="btn sm ghost" style={{ color: 'var(--pri)' }} onClick={onDelete}><Icon name="trash" />Excluir</button>
    </>}
  </div>;
}

/* Formulário: nova publicação agendada (manual) */
function CalendarNewForm({ creators, platforms, onDone, onCancel }) {
  const [creatorId, setCreatorId] = React.useState('');
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [selPlats, setSelPlats] = React.useState([]);
  const [publishAt, setPublishAt] = React.useState('');
  const [crossPromote, setCrossPromote] = React.useState(true);
  const [crossAt, setCrossAt] = React.useState('');
  const [title, setTitle] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [tags, setTags] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => { if (!creatorId && creators.length) setCreatorId(creators[0].creator_id); }, [creators]);

  async function save() {
    if (!creatorId) { setError('Selecione um criador.'); return; }
    if (!file) { setError('Selecione um vídeo.'); return; }
    if (!publishAt) { setError('Defina a data de publicação.'); return; }
    setSaving(true); setError('');
    try {
      await window.mpApi.calendarCreate({
        creator_id: creatorId,
        video_object_key: file.object_key,
        run_id: file.run_id || null,
        publish_platforms: selPlats,
        publish_at: new Date(publishAt).toISOString(),
        cross_promote: crossPromote,
        cross_promote_at: crossPromote && crossAt ? new Date(crossAt).toISOString() : null,
        title, description,
        tags: tags.split(',').map(s => s.trim()).filter(Boolean),
      });
      onDone();
    } catch (e) { setError(e.message || 'Erro ao agendar.'); }
    finally { setSaving(false); }
  }

  return <div className="panel stack">
    <div className="sec cy"><Icon name="plus" />Nova publicação agendada</div>
    <div className="split">
      <div className="stack">
        <Field label="Criador">
          <select className="inp" value={creatorId} onChange={e => setCreatorId(e.target.value)}>
            {!creators.length && <option value="">Nenhum criador</option>}
            {creators.map(c => <option key={c.creator_id} value={c.creator_id}>{c.n}</option>)}
          </select>
        </Field>
        <CtxFileBar file={file} onPick={() => setPicking(p => !p)} />
        {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); setPicking(false); }} />}
        <Field label="Título"><input className="inp" value={title} onChange={e => setTitle(e.target.value)} placeholder="Título da publicação" /></Field>
        <Field label="Descrição"><textarea className="inp" rows="2" value={description} onChange={e => setDescription(e.target.value)} /></Field>
        <Field label="Tags (separadas por vírgula)"><input className="inp" value={tags} onChange={e => setTags(e.target.value)} placeholder="tag1, tag2" /></Field>
      </div>
      <div className="stack">
        <div className="sec mut">Plataformas</div>
        {!platforms.length && <div className="hint">Carregando plataformas…</div>}
        {platforms.map(p => {
          const name = typeof p === 'string' ? p : (p.name || p.id);
          const on = selPlats.includes(name);
          return <div key={name} className="litem" style={{ cursor: 'pointer', borderColor: on ? 'var(--cyan)' : undefined }}
            onClick={() => setSelPlats(prev => on ? prev.filter(x => x !== name) : [...prev, name])}>
            <span className="li-ic"><Icon name="globe" /></span>
            <div className="li-main"><b style={{ textTransform: 'capitalize' }}>{name}</b></div>
            <Check on={on} onClick={e => { e && e.stopPropagation && e.stopPropagation(); }} />
          </div>;
        })}
        <Field label="Publicar em"><input className="inp" type="datetime-local" value={publishAt} onChange={e => setPublishAt(e.target.value)} /></Field>
        <div className="litem" style={{ cursor: 'pointer' }} onClick={() => setCrossPromote(p => !p)}>
          <span className="li-ic"><Icon name="send" /></span>
          <div className="li-main"><b>Cross-promotion</b><small>Disparar também em canais auxiliares (Telegram, etc.)</small></div>
          <Check on={crossPromote} onClick={e => { e && e.stopPropagation && e.stopPropagation(); }} />
        </div>
        {crossPromote && <Field label="Cross-promo em"><input className="inp" type="datetime-local" value={crossAt} onChange={e => setCrossAt(e.target.value)} /></Field>}
      </div>
    </div>
    {error && <div className="panel" style={{ borderColor: 'var(--pri-line)' }}><span style={{ color: 'var(--pri)', fontSize: 13 }}>✗ {error}</span></div>}
    <div className="rowx" style={{ gap: 8 }}>
      <button className="btn pri" disabled={saving} onClick={save}><Icon name="check" />{saving ? 'Salvando…' : 'Agendar'}</button>
      <button className="btn ghost" onClick={onCancel}>Cancelar</button>
    </div>
  </div>;
}

/* Formulário: agendamento automático (calendar_scheduler.auto_schedule) */
function CalendarAutoForm({ creators, platforms, onDone, onCancel }) {
  const [creatorId, setCreatorId] = React.useState('');
  const [videos, setVideos] = React.useState([]);
  const [picking, setPicking] = React.useState(false);
  const [selPlats, setSelPlats] = React.useState([]);
  const [periodDays, setPeriodDays] = React.useState(7);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');
  const [result, setResult] = React.useState(null);

  React.useEffect(() => { if (!creatorId && creators.length) setCreatorId(creators[0].creator_id); }, [creators]);

  async function run() {
    if (!creatorId) { setError('Selecione um criador.'); return; }
    if (!videos.length) { setError('Selecione ao menos um vídeo.'); return; }
    if (!selPlats.length) { setError('Selecione ao menos uma plataforma.'); return; }
    setSaving(true); setError(''); setResult(null);
    try {
      const r = await window.mpApi.calendarAutoSchedule({
        creator_id: creatorId,
        video_object_keys: videos.map(v => v.object_key),
        platforms: selPlats,
        period_days: Number(periodDays) || 7,
      });
      if (r.error) throw new Error(r.error);
      setResult(r);
    } catch (e) { setError(e.message || 'Erro no agendamento automático.'); }
    finally { setSaving(false); }
  }

  return <div className="panel stack">
    <div className="sec cy"><Icon name="sparkles" />Agendamento automático</div>
    <Field label="Criador">
      <select className="inp" value={creatorId} onChange={e => setCreatorId(e.target.value)}>
        {!creators.length && <option value="">Nenhum criador</option>}
        {creators.map(c => <option key={c.creator_id} value={c.creator_id}>{c.n}</option>)}
      </select>
    </Field>
    <div className="sec mut">Vídeos a agendar</div>
    {videos.map(v => <div key={v.object_key} className="litem">
      <span className="li-ic"><Icon name="media" /></span>
      <div className="li-main"><b style={{ fontSize: 12.5 }}>{v.n}</b></div>
      <button className="btn sm ghost" onClick={() => setVideos(prev => prev.filter(x => x.object_key !== v.object_key))}><Icon name="trash" /></button>
    </div>)}
    <button className="btn sm" onClick={() => setPicking(p => !p)}><Icon name="plus" />Adicionar vídeo</button>
    {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setVideos(prev => prev.find(x => x.object_key === f.object_key) ? prev : [...prev, f]); setPicking(false); }} />}
    <div className="sec mut">Plataformas</div>
    {platforms.map(p => {
      const name = typeof p === 'string' ? p : (p.name || p.id);
      const on = selPlats.includes(name);
      return <div key={name} className="litem" style={{ cursor: 'pointer', borderColor: on ? 'var(--cyan)' : undefined }}
        onClick={() => setSelPlats(prev => on ? prev.filter(x => x !== name) : [...prev, name])}>
        <span className="li-ic"><Icon name="globe" /></span>
        <div className="li-main"><b style={{ textTransform: 'capitalize' }}>{name}</b></div>
        <Check on={on} onClick={e => { e && e.stopPropagation && e.stopPropagation(); }} />
      </div>;
    })}
    <Field label="Período (dias)"><input className="inp" type="number" min="1" max="60" value={periodDays} onChange={e => setPeriodDays(e.target.value)} /></Field>
    {error && <div className="panel" style={{ borderColor: 'var(--pri-line)' }}><span style={{ color: 'var(--pri)', fontSize: 13 }}>✗ {error}</span></div>}
    {result && <div className="panel" style={{ borderColor: 'rgba(0,230,118,.3)' }}><span style={{ color: 'var(--good)', fontSize: 13 }}>✓ {result.created ?? (result.entry_ids || []).length} publicação(ões) agendada(s)</span></div>}
    <div className="rowx" style={{ gap: 8 }}>
      <button className="btn pri" disabled={saving} onClick={run}><Icon name="sparkles" />{saving ? 'Agendando…' : 'Gerar agenda'}</button>
      {result ? <button className="btn" onClick={onDone}>Concluir</button> : <button className="btn ghost" onClick={onCancel}>Cancelar</button>}
    </div>
  </div>;
}

Object.assign(window, { TelegramApp, PublisherApp, CalendarApp });
