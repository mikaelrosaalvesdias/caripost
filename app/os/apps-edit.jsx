/* MetaPorn OS — Edição & Conteúdo: Legenda, Logo, Teaser, Thumbnail */

/* Barra "arquivo selecionado" comum aos apps de edição */
function CtxFileBar({ file, onPick }) {
  if (file) return <div className="litem" style={{ borderColor: 'var(--cyan)', background: 'var(--cyan-soft)' }}>
    <span className="li-ic" style={{ color: 'var(--cyan)' }}><Icon name="media" /></span>
    <div className="li-main"><b style={{ fontSize: 12.5 }}>{file.n}</b><small>arquivo selecionado em Arquivos</small></div>
    <button className="btn sm ghost" onClick={onPick}>Trocar</button>
  </div>;
  return <div className="litem" style={{ cursor: 'pointer' }} onClick={onPick}>
    <span className="li-ic"><Icon name="media" /></span>
    <div className="li-main"><b style={{ fontSize: 12.5 }}>Nenhum vídeo selecionado</b><small>clique para escolher do servidor</small></div>
    <button className="btn sm pri">Selecionar</button>
  </div>;
}

/* Seletor de arquivo inline (lista do servidor) */
function FilePicker({ onSelect, onClose, filterFn }) {
  const [files, setFiles] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [q, setQ] = React.useState('');
  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.listMedia().then(r => { setFiles(filterFn ? r.filter(filterFn) : r); setLoading(false); }).catch(() => setLoading(false));
  }, []);
  const visible = files.filter(f => !q || f.n.toLowerCase().includes(q.toLowerCase()));
  return <div className="panel stack" style={{ maxHeight: 320, overflow: 'hidden', display: 'flex' }}>
    <div className="rowx" style={{ justifyContent: 'space-between' }}>
      <input className="inp" style={{ flex: 1, height: 34, fontSize: 12 }} placeholder="Buscar…" value={q} onChange={e => setQ(e.target.value)} autoFocus />
      <button className="btn sm ghost" onClick={onClose}>✕</button>
    </div>
    <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
      {loading && <div className="hint">Carregando…</div>}
      {visible.slice(0, 40).map(f => <div key={f.object_key} className="litem" style={{ padding: '7px 10px', cursor: 'pointer' }} onClick={() => onSelect(f)}>
        <div className="li-main"><b style={{ fontSize: 12 }}>{f.n}</b><small>{f.s} · {f.size}</small></div>
        <Pill kind={f.tone} dot>{f.s}</Pill>
      </div>)}
    </div>
  </div>;
}

/* ── LEGENDA — transcrição, SRT e queima ── */
function LegendaApp() {
  const [tab, setTab] = React.useState('edit');
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [srt, setSrt] = React.useState('');
  const [runId, setRunId] = React.useState(null);
  const [phase, setPhase] = React.useState('idle');
  const [pct, setPct] = React.useState(0);
  const [statusMsg, setStatusMsg] = React.useState('');
  const [resultKey, setResultKey] = React.useState('');
  const [fontSize, setFontSize] = React.useState(22);
  const [fontColor, setFontColor] = React.useState('white');
  const pollRef = React.useRef(null);

  React.useEffect(() => {
    if (file && window.mpApi) {
      window.mpApi.findRunForKey(file.object_key).then(rid => {
        if (rid) { setRunId(rid); _loadSrt(rid); }
      }).catch(() => {});
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [file?.object_key]);

  async function _loadSrt(rid) {
    const s = await window.mpApi.getRunSrt(rid);
    setSrt(typeof s === 'string' ? s : (s.srt || ''));
  }

  async function doBurn(skipSubs) {
    if (!file) { alert('Selecione um vídeo primeiro.'); return; }
    setPhase('preparing'); setPct(5); setStatusMsg('Preparando…');
    try {
      const rid = runId || await window.mpApi.ensureRun(file, m => setStatusMsg(m));
      setRunId(rid);
      if (!skipSubs && !srt) await _loadSrt(rid);
      setPhase('burning'); setPct(10); setStatusMsg('Iniciando queima (FFmpeg)…');
      const r = await window.mpApi.burnSubtitles({
        run_id: rid,
        video_object_key: file.object_key,
        font_size: fontSize,
        font_color: fontColor,
        skip_subtitles: !!skipSubs,
      });
      const jobId = r.job_id;
      if (!jobId) throw new Error(r.error || 'sem job_id');
      pollRef.current = setInterval(async () => {
        try {
          const st = await window.mpApi.burnStatus(jobId);
          setPct(st.progress_pct || 50);
          setStatusMsg(st.detail || 'Processando…');
          if (st.status === 'done') {
            clearInterval(pollRef.current);
            setPhase('done'); setPct(100);
            setResultKey(st.output_object_key || st.burned_object_key || st.result_object_key || '');
          } else if (st.status === 'error') {
            clearInterval(pollRef.current);
            setPhase('error'); setStatusMsg(st.detail || st.error || 'Erro na queima');
          }
        } catch (_) {}
      }, 3500);
    } catch (e) {
      setPhase('error'); setStatusMsg(e.message);
    }
  }

  const srtBlocks = srt ? srt.split('\n\n').slice(0, 30) : [];

  return <div className="app">
    <AppHead icon="captions" title="Legenda & Queima" desc="Gera SRT (PT-BR), deixa você revisar, escolhe o estilo e queima a legenda no vídeo via FFmpeg."
      right={srt ? <Pill kind="good" dot>transcrição pronta</Pill> : <Pill kind="warn" dot>sem transcrição</Pill>} />
    <CtxFileBar file={file} onPick={() => setPicking(p => !p)} />
    {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); window.mpCtx.file = f; setPicking(false); setRunId(null); setSrt(''); setPhase('idle'); }} />}
    <div className="split">
      <div className="stack">
        <div className="sec cy"><Icon name="wave" />Prévia</div>
        {file ? <RealPlayer objectKey={file.object_key} /> : <div className="vstage" style={{ aspectRatio: '16/9' }}><div className="ph" /><div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--muted)', fontSize: 13 }}>Selecione um vídeo</div></div>}
        {runId
          ? <ProgressBar pct={100} tone="gd" label="Transcrição existente encontrada" eta={'run ' + runId.slice(0, 8)} />
          : file && <button className="btn" onClick={async () => {
              setPhase('preparing'); setStatusMsg('Analisando vídeo…');
              try { const rid = await window.mpApi.ensureRun(file, m => setStatusMsg(m)); setRunId(rid); await _loadSrt(rid); setPhase('idle'); }
              catch (e) { setPhase('error'); setStatusMsg(e.message); }
            }}><Icon name="mic" />Transcrever agora</button>}
      </div>
      <div className="stack">
        <div className="tabbar">
          <button className={'tabx' + (tab === 'edit' ? ' on' : '')} onClick={() => setTab('edit')}>Editor SRT</button>
          <button className={'tabx' + (tab === 'style' ? ' on' : '')} onClick={() => setTab('style')}>Estilo</button>
        </div>
        {tab === 'edit' ? <div className="panel flush" style={{ maxHeight: 240, overflowY: 'auto' }}>
          {srtBlocks.length ? srtBlocks.map((b, i) => {
            const lines = b.split('\n');
            return <div key={i} style={{ padding: '10px 15px', borderBottom: '1px solid var(--line)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--fm)', fontSize: 10.5, color: 'var(--muted)' }}><span>#{lines[0]}</span><span>{lines[1] || ''}</span></div>
              <div style={{ fontSize: 13, marginTop: 3 }}>{lines.slice(2).join(' ')}</div>
            </div>;
          }) : <div style={{ padding: '14px 15px', fontSize: 12.5, color: 'var(--muted)' }}>Sem SRT ainda — transcreva o vídeo primeiro.</div>}
        </div> : <div className="panel stack">
          <div className="grid2">
            <Field label="Tamanho da fonte"><select className="inp" value={fontSize} onChange={e => setFontSize(+e.target.value)}><option value="26">Grande (26)</option><option value="22">Médio (22)</option><option value="18">Pequeno (18)</option></select></Field>
            <Field label="Cor"><select className="inp" value={fontColor} onChange={e => setFontColor(e.target.value)}><option value="white">Branco</option><option value="yellow">Amarelo</option><option value="cyan">Ciano</option></select></Field>
          </div>
        </div>}
        {(phase === 'preparing' || phase === 'burning') && <div className="panel"><ProgressBar pct={pct} tone="cy" label={statusMsg} eta="" /></div>}
        {phase === 'error' && <div className="panel" style={{ borderColor: 'var(--pri-line)' }}><span style={{ color: 'var(--pri)', fontSize: 13 }}>✗ {statusMsg}</span></div>}
        {phase === 'done' && <div className="panel stack" style={{ borderColor: 'rgba(0,230,118,.3)' }}>
          <div className="pill good" style={{ alignSelf: 'flex-start' }}><Icon name="check" />Queima concluída</div>
          <div className="rowx">
            <button className="btn pri sm" onClick={async () => {
              const url = await window.mpApi.downloadUrl(resultKey, 'video_legendado');
              if (url) window.open(url, '_blank');
            }}><Icon name="download" />Baixar resultado</button>
            <button className="btn sm" onClick={() => { window.__mpOpen && window.__mpOpen('media'); }}><Icon name="media" />Ver em Arquivos</button>
          </div>
        </div>}
        <div className="rowx" style={{ justifyContent: 'flex-end' }}>
          <button className="btn" disabled={!srt} onClick={() => {
            const blob = new Blob([srt], { type: 'text/plain' });
            const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'legendas.srt'; a.click();
          }}><Icon name="download" />Baixar .srt</button>
          <button className="btn" disabled={!file || phase === 'burning'} onClick={() => doBurn(true)}><Icon name="logo" />Queimar só logo</button>
          <button className="btn pri" data-tour="leg-burn" disabled={!file || phase === 'burning'} onClick={() => doBurn(false)}><Icon name="burn" />{phase === 'burning' ? 'Queimando…' : 'Queimar legenda'}</button>
        </div>
      </div>
    </div>
  </div>;
}

/* ── LOGO — studio de marca d'água ── */
function LogoApp() {
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [profiles, setProfiles] = React.useState([]);
  const [selProfile, setSelProfile] = React.useState(null);
  const [pos, setPos] = React.useState('br');
  const [size, setSize] = React.useState(20);
  const [op, setOp] = React.useState(85);
  const [phase, setPhase] = React.useState('idle');
  const [pct, setPct] = React.useState(0);
  const [statusMsg, setStatusMsg] = React.useState('');
  const [resultKey, setResultKey] = React.useState('');
  const pollRef = React.useRef(null);
  const coords = { tl: [6, 8], tr: [78, 8], bl: [6, 74], br: [78, 74], c: [42, 42] };
  const posPct = { tl: [3, 3], tr: [97, 3], bl: [3, 97], br: [97, 97], c: [50, 50] };
  const lx = (coords[pos] || coords.br)[0], ly = (coords[pos] || coords.br)[1];

  React.useEffect(() => {
    if (window.mpApi) window.mpApi.logoProfiles().then(p => { setProfiles(p); if (p.length) setSelProfile(p[0]); }).catch(() => {});
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  async function doBurnLogo() {
    if (!file) { alert('Selecione um vídeo primeiro.'); return; }
    if (!selProfile) { alert('Nenhum perfil de logo cadastrado.'); return; }
    setPhase('burning'); setPct(5); setStatusMsg('Preparando…');
    try {
      const rid = await window.mpApi.ensureRun(file, m => setStatusMsg(m));
      const pp = posPct[pos] || posPct.br;
      const r = await window.mpApi.burnSubtitles({
        run_id: rid,
        video_object_key: file.object_key,
        skip_subtitles: true,
        logo_profile_id: selProfile.id || selProfile.profile_id || '',
        logo_x: pp[0], logo_y: pp[1],
        logo_scale_pct: size, logo_opacity: op,
      });
      if (!r.job_id) throw new Error(r.error || 'sem job_id');
      pollRef.current = setInterval(async () => {
        try {
          const st = await window.mpApi.burnStatus(r.job_id);
          setPct(st.progress_pct || 50); setStatusMsg(st.detail || 'Processando…');
          if (st.status === 'done') {
            clearInterval(pollRef.current); setPhase('done'); setPct(100);
            setResultKey(st.output_object_key || st.burned_object_key || '');
          } else if (st.status === 'error') {
            clearInterval(pollRef.current); setPhase('error'); setStatusMsg(st.detail || 'Erro');
          }
        } catch (_) {}
      }, 3500);
    } catch (e) { setPhase('error'); setStatusMsg(e.message); }
  }

  return <div className="app">
    <AppHead icon="logo" title="Studio de Logo" desc="Posicione a marca d'água, ajuste tamanho e opacidade, e queime no vídeo final."
      right={<Pill kind="cy" dot>{profiles.length} perfil(is)</Pill>} />
    <CtxFileBar file={file} onPick={() => setPicking(p => !p)} />
    {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); window.mpCtx.file = f; setPicking(false); setPhase('idle'); }} />}
    <div className="logo-studio">
      <div className="stack">
        <div className="sec cy"><Icon name="eye" />Palco — posição da logo</div>
        <div className="vstage" style={{ aspectRatio: '16/9', position: 'relative', overflow: 'hidden' }}>
          {file ? <div style={{ position: 'absolute', inset: 0 }}><RealThumb objectKey={file.object_key} /></div> : <div className="ph" />}
          <div className="logo-drag" style={{ left: lx + '%', top: ly + '%', width: size + '%', opacity: op / 100, zIndex: 2 }}>
            {selProfile?.logo_b64 ? <img src={selProfile.logo_b64} alt="logo" style={{ width: '100%', height: '100%', objectFit: 'contain' }} /> : 'LOGO'}
          </div>
        </div>
        <div className="hint" style={{ fontSize: 12, color: 'var(--cyan)', fontFamily: 'var(--fm)' }}>posição: {pos} · escala: {size}% · opacidade: {op}%</div>
      </div>
      <div className="stack">
        <Field label="Perfil de logo">
          <select className="inp" value={selProfile ? (selProfile.id || selProfile.profile_id || '') : ''} onChange={e => setSelProfile(profiles.find(p => (p.id || p.profile_id) === e.target.value) || null)}>
            {!profiles.length && <option value="">Nenhum perfil cadastrado</option>}
            {profiles.map(p => <option key={p.id || p.profile_id} value={p.id || p.profile_id}>{p.name || p.company_name || p.id}</option>)}
          </select>
        </Field>
        <Field label="Posição (cantos)">
          <div className="checks">{[['tl', '↖ Sup. esq.'], ['tr', '↗ Sup. dir.'], ['c', '◎ Centro'], ['bl', '↙ Inf. esq.'], ['br', '↘ Inf. dir.']].map(([k, l]) => <Check key={k} on={pos === k} onClick={() => setPos(k)}>{l}</Check>)}</div>
        </Field>
        <div>
          <label className="lbl">Tamanho · {size}%</label>
          <input type="range" min="5" max="45" value={size} onChange={e => setSize(+e.target.value)} style={{ width: '100%', accentColor: 'var(--cyan)' }} />
        </div>
        <div>
          <label className="lbl">Opacidade · {op}%</label>
          <input type="range" min="20" max="100" value={op} onChange={e => setOp(+e.target.value)} style={{ width: '100%', accentColor: 'var(--cyan)' }} />
        </div>
        {phase === 'burning' && <div className="panel"><ProgressBar pct={pct} tone="cy" label={statusMsg} /></div>}
        {phase === 'error' && <div className="panel" style={{ borderColor: 'var(--pri-line)' }}><span style={{ color: 'var(--pri)', fontSize: 13 }}>✗ {statusMsg}</span></div>}
        {phase === 'done' && <div className="panel stack" style={{ borderColor: 'rgba(0,230,118,.3)' }}>
          <div className="pill good" style={{ alignSelf: 'flex-start' }}><Icon name="check" />Logo aplicada</div>
          <button className="btn pri sm" onClick={async () => { const u = await window.mpApi.downloadUrl(resultKey, 'video_logo'); if (u) window.open(u, '_blank'); }}><Icon name="download" />Baixar resultado</button>
        </div>}
        <div className="rowx" style={{ justifyContent: 'flex-end' }}>
          <button className="btn pri" disabled={!file || phase === 'burning'} onClick={doBurnLogo}><Icon name="burn" />{phase === 'burning' ? 'Queimando…' : 'Queimar logo'}</button>
        </div>
      </div>
    </div>
  </div>;
}

/* ── TEASER — corte curto dos melhores momentos ── */
function TeaserApp() {
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [phase, setPhase] = React.useState('idle');
  const [pct, setPct] = React.useState(0);
  const [statusMsg, setStatusMsg] = React.useState('');
  const [resultKey, setResultKey] = React.useState('');
  const pollRef = React.useRef(null);

  React.useEffect(() => { return () => { if (pollRef.current) clearInterval(pollRef.current); }; }, []);

  async function doGenerate() {
    if (!file) { alert('Selecione um vídeo primeiro.'); return; }
    setPhase('running'); setPct(5); setStatusMsg('Preparando…');
    try {
      let rid = null;
      try { rid = await window.mpApi.findRunForKey(file.object_key); } catch (_) {}
      setStatusMsg('Gerando teaser…'); setPct(15);
      const r = await window.mpApi.teaserGenerate({
        run_id: rid || undefined,
        video_object_key: file.object_key,
      });
      const jobId = r.job_id;
      if (!jobId) {
        const k = r.teaser_object_key || r.output_object_key || '';
        if (k) { setPhase('done'); setPct(100); setResultKey(k); return; }
        throw new Error(r.error || 'sem job_id');
      }
      pollRef.current = setInterval(async () => {
        try {
          const st = await window.mpApi.teaserStatus(jobId);
          setPct(st.progress_pct || 50); setStatusMsg(st.detail || 'Renderizando…');
          if (st.status === 'done') {
            clearInterval(pollRef.current); setPhase('done'); setPct(100);
            setResultKey(st.teaser_object_key || st.output_object_key || st.result_object_key || '');
          } else if (st.status === 'error') {
            clearInterval(pollRef.current); setPhase('error'); setStatusMsg(st.detail || 'Erro');
          }
        } catch (_) {}
      }, 3500);
    } catch (e) { setPhase('error'); setStatusMsg(e.message); }
  }

  return <div className="app">
    <AppHead icon="scissors" title="Gerar Teaser" desc="Detecta os melhores momentos e monta um teaser curto, pronto pra divulgação."
      right={<Pill kind="cy" dot>auto-detecção de cenas</Pill>} />
    <CtxFileBar file={file} onPick={() => setPicking(p => !p)} />
    {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); window.mpCtx.file = f; setPicking(false); setPhase('idle'); }} />}
    <div className="split">
      <div className="stack">
        <div className="sec mut"><Icon name="wave" />Vídeo fonte</div>
        {file ? <RealPlayer objectKey={file.object_key} /> : <div className="vstage" style={{ aspectRatio: '16/9' }}><div className="ph" /><div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--muted)', fontSize: 13 }}>Selecione um vídeo</div></div>}
      </div>
      <div className="stack">
        <div className="hint" style={{ fontSize: 12.5 }}>O teaser usa a detecção automática de cenas do servidor. Se o vídeo já tiver análise (run), os melhores momentos do Vision são priorizados.</div>
        {phase === 'running' && <div className="panel stack">
          <ProgressBar pct={pct} tone="cy" label={statusMsg} />
        </div>}
        {phase === 'error' && <div className="panel" style={{ borderColor: 'var(--pri-line)' }}><span style={{ color: 'var(--pri)', fontSize: 13 }}>✗ {statusMsg}</span></div>}
        {phase === 'done' && <div className="panel stack" style={{ borderColor: 'rgba(0,230,118,.3)' }}>
          <div className="pill good" style={{ alignSelf: 'flex-start' }}><Icon name="check" />Teaser pronto</div>
          {resultKey && <RealPlayer objectKey={resultKey} style={{ maxHeight: 260 }} />}
          <div className="rowx">
            <button className="btn pri sm" onClick={async () => { const u = await window.mpApi.downloadUrl(resultKey, 'teaser'); if (u) window.open(u, '_blank'); }}><Icon name="download" />Baixar</button>
            <button className="btn sm" onClick={() => { window.mpCtx.file = { object_key: resultKey, n: 'teaser', s: 'teaser' }; window.__mpOpen && window.__mpOpen('telegram'); }}><Icon name="telegram" />Enviar ao Telegram</button>
          </div>
        </div>}
        <button className="btn pri block" disabled={!file || phase === 'running'} onClick={doGenerate}><Icon name="scissors" />{phase === 'running' ? 'Gerando…' : 'Gerar teaser'}</button>
      </div>
    </div>
  </div>;
}

/* ── THUMBNAIL — capa por IA ── */
function ThumbnailApp() {
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [frames, setFrames] = React.useState([]);
  const [sel, setSel] = React.useState(0);
  const [runId, setRunId] = React.useState(null);
  const [phase, setPhase] = React.useState('idle');
  const [statusMsg, setStatusMsg] = React.useState('');
  const [resultUrl, setResultUrl] = React.useState('');

  React.useEffect(() => {
    if (file && window.mpApi) {
      window.mpApi.findRunForKey(file.object_key).then(rid => {
        if (rid) { setRunId(rid); window.mpApi.getRunFrames(rid).then(f => setFrames(f || [])).catch(() => {}); }
      }).catch(() => {});
    }
  }, [file?.object_key]);

  async function doGenerate() {
    if (!file) { alert('Selecione um vídeo primeiro.'); return; }
    setPhase('running'); setStatusMsg('Preparando análise…');
    try {
      const rid = runId || await window.mpApi.ensureRun(file, m => setStatusMsg(m));
      setRunId(rid);
      setStatusMsg('Gerando thumbnail em alta resolução…');
      const r = await window.mpApi.thumbnailHighres({
        run_id: rid,
        object_key: file.object_key,
        frame_index: sel,
        frames_count: Math.max(2, frames.length || 10),
      });
      const url = r.url || r.image_url || r.thumbnail_url || (r.b64 ? 'data:image/jpeg;base64,' + r.b64 : '');
      if (!url) throw new Error(r.error || 'sem resultado');
      setResultUrl(url);
      setPhase('done');
    } catch (e) { setPhase('error'); setStatusMsg(e.message); }
  }

  const frameSrc = (f) => typeof f === 'string' ? f : (f.url || f.b64 || '');

  return <div className="app">
    <AppHead icon="thumbnail" title="Thumbnail IA" desc="Gera a capa ideal a partir dos frames-chave do vídeo, em alta resolução."
      right={<Pill kind="violet" icon="sparkles">Vision IA</Pill>} />
    <CtxFileBar file={file} onPick={() => setPicking(p => !p)} />
    {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); window.mpCtx.file = f; setPicking(false); setPhase('idle'); setFrames([]); setRunId(null); setResultUrl(''); }} />}
    <div className="split">
      <div className="stack">
        <div className="sec cy"><Icon name="image" />Frames candidatos {frames.length ? '(' + frames.length + ')' : ''}</div>
        {frames.length ? <div className="thumbs">{frames.slice(0, 12).map((f, i) =>
          <div key={i} className={'thumb' + (i === sel ? ' sel' : '')} onClick={() => setSel(i)}>
            <img src={frameSrc(f)} alt={'frame ' + i} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
          </div>)}
        </div> : <div className="panel">
          <div className="hint">{file ? 'Sem frames ainda. O vídeo precisa de análise — clique em Gerar que a análise roda automaticamente.' : 'Selecione um vídeo.'}</div>
        </div>}
        <div className="sec mut" style={{ marginTop: 6 }}>Prévia da capa</div>
        <div className="vstage" style={{ aspectRatio: '16/9', position: 'relative', overflow: 'hidden' }}>
          {resultUrl
            ? <img src={resultUrl} alt="thumbnail" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
            : frames[sel]
              ? <img src={frameSrc(frames[sel])} alt="frame" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
              : file ? <div style={{ position: 'absolute', inset: 0 }}><RealThumb objectKey={file.object_key} /></div> : <div className="ph" />}
        </div>
      </div>
      <div className="stack">
        {phase === 'running' && <div className="panel"><ProgressBar pct={70} tone="violet" label={statusMsg} /></div>}
        {phase === 'error' && <div className="panel" style={{ borderColor: 'var(--pri-line)' }}><span style={{ color: 'var(--pri)', fontSize: 13 }}>✗ {statusMsg}</span></div>}
        {phase === 'done' && <div className="panel stack" style={{ borderColor: 'rgba(0,230,118,.3)' }}>
          <div className="pill good" style={{ alignSelf: 'flex-start' }}><Icon name="check" />Capa gerada em alta resolução</div>
          <button className="btn pri sm" onClick={() => { const a = document.createElement('a'); a.href = resultUrl; a.download = 'thumbnail.jpg'; a.target = '_blank'; a.click(); }}><Icon name="download" />Baixar capa</button>
        </div>}
        <div className="hint" style={{ fontSize: 12.5 }}>Selecione o frame desejado à esquerda e gere a capa em alta resolução.</div>
        <div className="rowx" style={{ justifyContent: 'flex-end' }}>
          <button className="btn" onClick={() => { window.__mpOpen && window.__mpOpen('criacao'); }}><Icon name="post" />Editor completo</button>
          <button className="btn pri" disabled={!file || phase === 'running'} onClick={doGenerate}><Icon name="sparkles" />{phase === 'running' ? 'Gerando…' : 'Gerar com IA'}</button>
        </div>
      </div>
    </div>
  </div>;
}

Object.assign(window, { CtxFileBar, FilePicker, LegendaApp, LogoApp, TeaserApp, ThumbnailApp });
