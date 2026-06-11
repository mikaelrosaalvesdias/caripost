/* MetaPorn OS — Operação & Distribuição: Telegram, Publicar, Calendário */

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

/* ── PUBLICAR — distribuição real nas plataformas ── */
function PublisherApp() {
  const [platforms, setPlatforms] = React.useState([]);
  const [selPlats, setSelPlats] = React.useState([]);
  const [creators, setCreators] = React.useState([]);
  const [selCreator, setSelCreator] = React.useState('');
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [title, setTitle] = React.useState('');
  const [phase, setPhase] = React.useState('idle');
  const [statusMsg, setStatusMsg] = React.useState('');
  const pollRef = React.useRef(null);

  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.publisherPlatforms().then(p => {
      const list = Array.isArray(p) ? p : Object.keys(p || {});
      setPlatforms(list);
    }).catch(() => {});
    window.mpApi.listCreators().then(c => {
      setCreators(c);
      if (c.length) setSelCreator(c[0].creator_id);
    }).catch(() => {});
    // Pré-carrega título do run se houver
    const ctx = window.mpCtx?.file;
    if (ctx?.run_id && window.mpApi) {
      window.mpApi.getRun(ctx.run_id).then(d => {
        const t = d.result?.grok?.title;
        if (t) setTitle(t);
      }).catch(() => {});
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

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
    <AppHead icon="broadcast" title="Publicação" desc="Distribui o vídeo final nas plataformas selecionadas, com título e thumbnail." />
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
  const days = [];
  for (let i = 0; i < 35; i++) days.push(i + 1);
  const [entries, setEntries] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.listCalendar().then(r => {
      setEntries(r.map(e => ({
        t: e.title || 'Publicação',
        d: e.publish_at ? new Date(e.publish_at).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—',
        c: e.creator_name || e.creator_id || '—',
        plat: Array.isArray(e.publish_platforms) ? e.publish_platforms.join(' · ') : (e.publish_platforms || '—'),
        tone: e.status === 'published' ? 'good' : 'warn',
        s: e.status || 'agendado',
        day: e.publish_at ? new Date(e.publish_at).getDate() : null,
      })));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const today = new Date().getDate();
  const eventDays = {};
  entries.forEach(e => { if (e.day) eventDays[e.day] = e.tone === 'good' ? 'pri' : 'cy'; });
  const monthLabel = new Date().toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });

  return <div className="app">
    <AppHead icon="calendar" title="Calendário Editorial" desc="Publicações agendadas por criador e plataforma." />
    <div className="split">
      <div className="panel">
        <div className="rowx" style={{ justifyContent: 'center', marginBottom: 14 }}>
          <b style={{ fontFamily: 'var(--fh)', fontSize: 16, textTransform: 'capitalize' }}>{monthLabel}</b>
        </div>
        <div className="cal">
          {['S', 'T', 'Q', 'Q', 'S', 'S', 'D'].map((d, i) => <div key={i} className="dow">{d}</div>)}
          {days.map((d, i) => {
            const valid = d >= 1 && d <= 31;
            return <div key={i} className={'cell' + (valid ? '' : ' out') + (d === today ? ' today' : '')}>
              {valid ? d : ''}
              {eventDays[d] && <span className={'ev ' + (eventDays[d] === 'pri' ? 'pri' : '')} />}
            </div>;
          })}
        </div>
        <div className="rowx" style={{ marginTop: 12, fontSize: 11.5, color: 'var(--muted)' }}>
          <span className="rowx" style={{ gap: 5 }}><span style={{ width: 9, height: 9, borderRadius: 3, background: 'var(--pri)' }} />publicado</span>
          <span className="rowx" style={{ gap: 5 }}><span style={{ width: 9, height: 9, borderRadius: 3, background: 'var(--cyan)' }} />agendado</span>
        </div>
      </div>
      <div className="stack">
        <div className="sec mut"><Icon name="clock" />Próximas publicações</div>
        {loading && <div className="hint">Carregando…</div>}
        {!loading && !entries.length && <div className="hint">Nenhuma publicação agendada.</div>}
        {entries.slice(0, 8).map((e, i) => <div key={i} className="litem">
          <span className="li-ic"><Icon name="post" /></span>
          <div className="li-main"><b>{e.t}</b><small>{e.c} · {e.d} · {e.plat}</small></div>
          <Pill kind={e.tone} dot>{e.s}</Pill>
        </div>)}
      </div>
    </div>
  </div>;
}

Object.assign(window, { TelegramApp, PublisherApp, CalendarApp });
