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
            setResultKey(st.object_key || st.output_object_key || st.burned_object_key || st.result_object_key || '');
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
        {resultKey && phase !== 'preparing' && phase !== 'burning' && <div className="panel stack" style={{ borderColor: 'rgba(0,230,118,.3)' }}>
          <div className="pill good" style={{ alignSelf: 'flex-start' }}><Icon name="check" />Queima concluída</div>
          {resultKey && <RealPlayer objectKey={resultKey} style={{ maxHeight: 220 }} />}
          <div className="rowx">
            <button className="btn pri sm" onClick={() => window.mpApi.download(resultKey, 'video_legendado.mp4')}><Icon name="download" />Baixar resultado</button>
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
    <ProcessModal open={phase === 'preparing' || phase === 'burning' || phase === 'error'}
      title="Queimando legenda" detail={statusMsg} pct={pct} phase={phase === 'error' ? 'error' : 'running'}
      onClose={() => setPhase('idle')} />
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
            setResultKey(st.object_key || st.output_object_key || st.burned_object_key || '');
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
        {resultKey && phase !== 'burning' && <div className="panel stack" style={{ borderColor: 'rgba(0,230,118,.3)' }}>
          <div className="pill good" style={{ alignSelf: 'flex-start' }}><Icon name="check" />Logo aplicada</div>
          {resultKey && <RealPlayer objectKey={resultKey} style={{ maxHeight: 220 }} />}
          <button className="btn pri sm" onClick={() => window.mpApi.download(resultKey, 'video_logo.mp4')}><Icon name="download" />Baixar resultado</button>
        </div>}
        <div className="rowx" style={{ justifyContent: 'flex-end' }}>
          <button className="btn pri" disabled={!file || phase === 'burning'} onClick={doBurnLogo}><Icon name="burn" />{phase === 'burning' ? 'Queimando…' : 'Queimar logo'}</button>
        </div>
      </div>
    </div>
    <ProcessModal open={phase === 'burning' || phase === 'error'}
      title="Queimando logo" detail={statusMsg} pct={pct} phase={phase === 'error' ? 'error' : 'running'}
      onClose={() => setPhase('idle')} />
  </div>;
}

/* ── LogoBurnModal — ajustes completos de logo sobre o teaser (modal) ── */
function LogoBurnModal({ teaserKey, runId, profiles, onClose, onDone }) {
  const [selProfile, setSelProfile] = React.useState(profiles[0] || null);
  const [pos, setPos] = React.useState('br');
  const [size, setSize] = React.useState(20);
  const [op, setOp] = React.useState(85);
  const [proc, setProc] = React.useState({ open: false, pct: 0, detail: '', phase: 'running' });
  const pollRef = React.useRef(null);
  const posPct = { tl: [3, 3], tr: [97, 3], bl: [3, 97], br: [97, 97], c: [50, 50] };
  const coords = { tl: [6, 8], tr: [78, 8], bl: [6, 74], br: [78, 74], c: [42, 42] };
  const lx = (coords[pos] || coords.br)[0], ly = (coords[pos] || coords.br)[1];

  React.useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  async function burn() {
    if (!selProfile) { alert('Selecione um perfil de logo.'); return; }
    if (!runId) { alert('Sem run associado ao teaser — não é possível queimar a logo.'); return; }
    setProc({ open: true, pct: 5, detail: 'Iniciando queima da logo…', phase: 'running' });
    try {
      const pp = posPct[pos] || posPct.br;
      const r = await window.mpApi.fetch('/api/teaser/burn-logo', {
        method: 'POST',
        body: JSON.stringify({
          run_id: runId,
          teaser_object_key: teaserKey,
          logo_profile_id: selProfile.id || selProfile.profile_id || '',
          logo_profile_layout_linked: false,
          logo_x: pp[0], logo_y: pp[1],
          logo_scale_pct: size, logo_opacity: op,
        }),
      });
      if (!r.job_id) throw new Error(r.error || r.detail || 'sem job_id');
      pollRef.current = setInterval(async () => {
        try {
          const st = await window.mpApi.burnStatus(r.job_id);
          setProc(p => ({ ...p, pct: st.progress_pct || p.pct, detail: st.detail || 'Queimando logo…' }));
          if (st.status === 'done') {
            clearInterval(pollRef.current);
            const out = st.object_key || st.output_object_key || st.burned_object_key || st.result_object_key || teaserKey;
            setProc(p => ({ ...p, pct: 100, phase: 'done', detail: 'Logo aplicada!', resultKey: out }));
          } else if (st.status === 'error') {
            clearInterval(pollRef.current);
            setProc(p => ({ ...p, phase: 'error', detail: st.detail || 'Erro na queima' }));
          }
        } catch (_) {}
      }, 3000);
    } catch (e) { setProc({ open: true, pct: 0, detail: e.message, phase: 'error' }); }
  }

  return <>
    <div className="lbm-veil" onClick={onClose} />
    <div className="lbm-card">
      <div className="lbm-head">
        <div className="tb-ic" style={{ width: 36, height: 36, borderRadius: 10 }}><Icon name="logo" /></div>
        <div><b style={{ fontFamily: 'var(--fh)', fontSize: 16 }}>Queimar logo no teaser</b><div style={{ fontSize: 12, color: 'var(--muted)' }}>posicione, ajuste tamanho e opacidade — igual à função Logo</div></div>
        <button className="wbtn close" style={{ marginLeft: 'auto' }} onClick={onClose}><Icon name="x" /></button>
      </div>
      <div className="lbm-body">
        <div className="stack">
          <div className="sec cy"><Icon name="eye" />Prévia</div>
          <div className="vstage" style={{ aspectRatio: '16/9', position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', inset: 0 }}><RealThumb objectKey={teaserKey} /></div>
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
              {profiles.map(p => <option key={p.id || p.profile_id} value={p.id || p.profile_id}>{p.company_name || p.logo_name || p.id}</option>)}
            </select>
          </Field>
          <Field label="Posição (cantos)">
            <div className="checks">{[['tl', '↖ Sup. esq.'], ['tr', '↗ Sup. dir.'], ['c', '◎ Centro'], ['bl', '↙ Inf. esq.'], ['br', '↘ Inf. dir.']].map(([k, l]) => <Check key={k} on={pos === k} onClick={() => setPos(k)}>{l}</Check>)}</div>
          </Field>
          <div><label className="lbl">Tamanho · {size}%</label><input type="range" min="5" max="45" value={size} onChange={e => setSize(+e.target.value)} style={{ width: '100%', accentColor: 'var(--cyan)' }} /></div>
          <div><label className="lbl">Opacidade · {op}%</label><input type="range" min="20" max="100" value={op} onChange={e => setOp(+e.target.value)} style={{ width: '100%', accentColor: 'var(--cyan)' }} /></div>
        </div>
      </div>
      <div className="lbm-foot">
        <button className="btn ghost" onClick={onClose}>Cancelar</button>
        <button className="btn pri" onClick={burn}><Icon name="burn" />Queimar logo</button>
      </div>
    </div>
    <ProcessModal open={proc.open} title="Queimando logo" detail={proc.detail} pct={proc.pct} phase={proc.phase}
      onClose={() => {
        const done = proc.phase === 'done';
        setProc({ open: false, pct: 0, detail: '', phase: 'running' });
        if (done) { onDone && onDone(proc.resultKey); onClose(); }
      }} />
  </>;
}

/* ── TEASER — corte curto dos melhores momentos ── */
function TeaserApp() {
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [runId, setRunId] = React.useState(null);
  const [frames, setFrames] = React.useState([]);
  const [frameTimes, setFrameTimes] = React.useState([]);
  const [selFrames, setSelFrames] = React.useState([]);
  const [loadingFrames, setLoadingFrames] = React.useState(false);
  // avançado
  const [showAdv, setShowAdv] = React.useState(false);
  const [numClips, setNumClips] = React.useState(8);
  const [clipDur, setClipDur] = React.useState(6);
  const [autoDist, setAutoDist] = React.useState(false);
  const [totalMin, setTotalMin] = React.useState(2);
  const [firstMin, setFirstMin] = React.useState(0.5);
  const [lastMin, setLastMin] = React.useState(0.5);
  const [crf, setCrf] = React.useState(26);
  const [fmt, setFmt] = React.useState('web'); // web | mobile | both
  const [profiles, setProfiles] = React.useState([]);
  const [opener, setOpener] = React.useState(null);
  const [openerPos, setOpenerPos] = React.useState('start');
  const [openerPick, setOpenerPick] = React.useState(false);
  const [openerUpPct, setOpenerUpPct] = React.useState(0);
  const openerInputRef = React.useRef(null);
  // execução
  const [jobs, setJobs] = React.useState([]);
  const [genActive, setGenActive] = React.useState(false);
  const [logoModal, setLogoModal] = React.useState(null); // {teaserKey, idx}
  const pollRefs = React.useRef({});

  const isBurned = file && (file.s === 'burn' || (file.object_key || '').includes('burns/'));

  React.useEffect(() => {
    if (window.mpApi) window.mpApi.logoProfiles().then(setProfiles).catch(() => {});
    return () => { Object.values(pollRefs.current).forEach(t => clearInterval(t)); };
  }, []);

  React.useEffect(() => {
    if (!file || !window.mpApi) return;
    setLoadingFrames(true); setFrames([]); setFrameTimes([]); setSelFrames([]); setRunId(null);
    window.mpApi.findRunForKey(file.object_key).then(async rid => {
      if (!rid) { setLoadingFrames(false); return; }
      setRunId(rid);
      const [fr, run] = await Promise.all([
        window.mpApi.getRunFrames(rid).catch(() => []),
        window.mpApi.getRun(rid).catch(() => null),
      ]);
      setFrames(fr || []);
      const ts = run?.result?.vision?.frame_timestamps;
      setFrameTimes(Array.isArray(ts) ? ts : []);
      setLoadingFrames(false);
    }).catch(() => setLoadingFrames(false));
  }, [file?.object_key]);

  const _frameSrc = window.frameSrc;
  function _tsFor(i) { const t = frameTimes[i]; return t == null ? '' : window.__mpFmtTime(t); }

  async function transcribeNow() {
    if (!file) return;
    setLoadingFrames(true);
    try {
      const rid = await window.mpApi.ensureRun(file, () => {});
      setRunId(rid);
      const fr = await window.mpApi.getRunFrames(rid).catch(() => []);
      setFrames(fr || []);
      const run = await window.mpApi.getRun(rid).catch(() => null);
      const ts = run?.result?.vision?.frame_timestamps;
      setFrameTimes(Array.isArray(ts) ? ts : []);
    } catch (e) { alert('Análise falhou: ' + e.message); }
    finally { setLoadingFrames(false); }
  }

  async function handleOpenerUpload(files) {
    if (!files?.length || !window.mpApi) return;
    const f = files[0];
    try {
      setOpenerUpPct(1);
      const key = await window.mpApi.uploadFile(f, p => setOpenerUpPct(p));
      setOpener({ object_key: key, n: f.name });
      setOpenerUpPct(0);
    } catch (e) { setOpenerUpPct(0); alert('Upload falhou: ' + e.message); }
  }

  function _buildPlan(n, totMin, fMin, lMin) {
    const tot = totMin * 60, first = fMin * 60, last = lMin * 60;
    if (n < 2) return { ok: false, detail: 'Mínimo 2 cenas.' };
    if (first + last >= tot) return { ok: false, detail: 'Primeira + última cena excedem a duração total.' };
    const midCount = n - 2;
    const midDur = midCount > 0 ? (tot - first - last) / midCount : 0;
    if (midCount > 0 && midDur < 2) return { ok: false, detail: 'Cenas do meio ficariam com menos de 2s — reduza o nº de cenas ou aumente a duração total.' };
    return { ok: true, durations: [first, ...Array(midCount).fill(midDur), last] };
  }

  async function generate() {
    if (!file) { alert('Selecione um vídeo primeiro.'); return; }
    Object.values(pollRefs.current).forEach(t => clearInterval(t));
    pollRefs.current = {};

    let nClips = Math.max(2, Math.min(numClips, 20));
    let cDur = Math.max(2, Math.min(clipDur, 720));
    const sortedSel = selFrames.slice().sort((a, b) => a - b);
    const perScene = {};
    let ordered = [];
    if (autoDist) {
      const planN = sortedSel.length >= 2 ? Math.min(sortedSel.length, 20) : nClips;
      const plan = _buildPlan(planN, totalMin, firstMin, lastMin);
      if (!plan.ok) { alert(plan.detail); return; }
      nClips = planN; ordered = plan.durations;
      cDur = Math.max(2, Math.min(Math.round(ordered.reduce((a, b) => a + b, 0) / ordered.length), 720));
      if (sortedSel.length) sortedSel.slice(0, nClips).forEach((idx, pos) => { perScene[idx] = ordered[pos]; });
    } else if (sortedSel.length) {
      sortedSel.forEach(idx => { perScene[idx] = cDur; });
    }
    const totalSec = ordered.length ? ordered.reduce((a, b) => a + b, 0) : nClips * cDur;
    if (totalSec > 1800) { alert('Teaser muito longo (' + Math.round(totalSec / 60) + ' min). Limite: 30 min.'); return; }

    const variants = fmt === 'both'
      ? [{ label: 'Web 1080p', h: 1080 }, { label: 'Celular 720p', h: 720 }]
      : fmt === 'mobile' ? [{ label: 'Celular 720p', h: 720 }] : [{ label: 'Web 1080p', h: 1080 }];

    const basePayload = {
      run_id: runId || undefined,
      num_clips: nClips, clip_duration: cDur, output_crf: crf, output_max_fps: 30,
      source_type: isBurned ? 'burned' : 'original',
      video_object_key: file.object_key,
      selected_frame_indexes: sortedSel,
      scene_durations_by_frame: perScene,
      ordered_scene_durations: ordered,
      frames_count: frames.length,
      force_logo_overlay: false,
      opener: { object_key: opener?.object_key || null, position: openerPos },
    };

    setGenActive(true);
    setJobs(variants.map(v => ({ label: v.label, jobId: null, pct: 5, msg: 'Iniciando…', status: 'running', resultKey: '' })));

    variants.forEach((v, vi) => {
      window.mpApi.teaserGenerate({ ...basePayload, output_max_height: v.h }).then(r => {
        if (!r.job_id) { setJobs(js => js.map((j, i) => i === vi ? { ...j, status: 'error', msg: r.error || r.detail || 'sem job_id' } : j)); return; }
        setJobs(js => js.map((j, i) => i === vi ? { ...j, jobId: r.job_id } : j));
        pollRefs.current[vi] = setInterval(async () => {
          try {
            const st = await window.mpApi.teaserStatus(r.job_id);
            setJobs(js => js.map((j, i) => i === vi ? {
              ...j, pct: st.progress_pct || j.pct, msg: st.detail || 'Renderizando…',
              status: st.status === 'done' ? 'done' : st.status === 'error' ? 'error' : 'running',
              resultKey: st.object_key || st.teaser_object_key || j.resultKey,
            } : j));
            if (st.status === 'done' || st.status === 'error') clearInterval(pollRefs.current[vi]);
          } catch (_) {}
        }, 3500);
      }).catch(e => { setJobs(js => js.map((j, i) => i === vi ? { ...j, status: 'error', msg: e.message } : j)); });
    });
  }

  async function renameResult(j, idx) {
    const cur = (j.resultKey || '').split('/').pop();
    const name = prompt('Novo nome do teaser:', cur);
    if (!name || name === cur) return;
    try { await window.mpApi.renameMedia(j.resultKey, name); setJobs(js => js.map((x, i) => i === idx ? { ...x, msg: '✓ renomeado para ' + name } : x)); }
    catch (e) { alert('Erro ao renomear: ' + e.message); }
  }

  const running = jobs.some(j => j.status === 'running');
  // estado agregado p/ ProcessModal de geração
  const avgPct = jobs.length ? Math.round(jobs.reduce((a, j) => a + (j.pct || 0), 0) / jobs.length) : 0;
  const anyErr = jobs.some(j => j.status === 'error');
  const allDone = jobs.length > 0 && jobs.every(j => j.status === 'done');
  const genPhase = anyErr ? 'error' : allDone ? 'done' : 'running';
  const genDetail = anyErr ? (jobs.find(j => j.status === 'error')?.msg || 'Erro')
    : allDone ? 'Teaser pronto!' : (jobs.find(j => j.status === 'running')?.msg || 'Renderizando…') + (jobs.length > 1 ? ` · ${jobs.filter(j => j.status === 'done').length}/${jobs.length} formatos` : '');

  return <div className="app">
    <AppHead icon="scissors" title="Gerar Teaser" desc="Usa as cenas detectadas pela IA para montar um teaser curto, pronto pra divulgação."
      right={<Pill kind="cy" dot>{frames.length ? frames.length + ' cenas da IA' : 'auto-detecção'}</Pill>} />
    <CtxFileBar file={file} onPick={() => setPicking(p => !p)} />
    {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); window.mpCtx.file = f; setPicking(false); setJobs([]); }} />}

    {file && isBurned && <div className="hint" style={{ color: 'var(--good)', fontSize: 12 }}>✓ Vídeo já queimado (logo aplicada) — o teaser herda a marca.</div>}

    <div className="split">
      <div className="stack">
        <div className="sec cy"><Icon name="image" />Cenas detectadas pela IA {selFrames.length ? `· ${selFrames.length} selecionada(s)` : ''}</div>
        {loadingFrames && <div className="panel"><ProgressBar pct={60} tone="cy" label="Carregando cenas do analisador…" /></div>}
        {!loadingFrames && !frames.length && file && <div className="panel stack">
          <div className="hint">Este vídeo ainda não foi analisado pela IA — sem cenas detectadas. Analise agora para escolher as cenas, ou gere sem seleção (o servidor detecta automaticamente).</div>
          <button className="btn sm" style={{ alignSelf: 'flex-start' }} onClick={transcribeNow}><Icon name="sparkles" />Analisar agora</button>
        </div>}
        {frames.length > 0 && <>
          <div className="thumbs" style={{ maxHeight: 240, overflowY: 'auto' }}>
            {frames.map((f, i) => {
              const on = selFrames.includes(i);
              return <div key={i} className={'thumb' + (on ? ' sel' : '')} onClick={() => setSelFrames(p => on ? p.filter(x => x !== i) : [...p, i])} style={{ position: 'relative' }}>
                <img src={_frameSrc(f)} alt={'cena ' + i} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
                {on && <span style={{ position: 'absolute', top: 4, right: 4, width: 18, height: 18, borderRadius: 5, background: 'var(--pri)', display: 'grid', placeItems: 'center', fontSize: 11, color: '#fff', zIndex: 2 }}>✓</span>}
                {_tsFor(i) && <span className="t">{_tsFor(i)}</span>}
              </div>;
            })}
          </div>
          <div className="rowx">
            <button className="btn sm ghost" onClick={() => setSelFrames(frames.map((_, i) => i))}>Selecionar todas</button>
            <button className="btn sm ghost" onClick={() => setSelFrames([])}>Limpar</button>
            <span className="hint" style={{ fontSize: 11.5 }}>{selFrames.length ? 'cenas escolhidas manualmente' : 'sem seleção → IA escolhe as melhores'}</span>
          </div>
        </>}
        {file && <RealPlayer objectKey={file.object_key} style={{ maxHeight: 240 }} />}
      </div>

      <div className="stack">
        {/* AVANÇADO */}
        <button className="acc-h" style={{ border: '1px solid var(--line)', borderRadius: 12, background: 'var(--glass2)' }} onClick={() => setShowAdv(a => !a)}>
          <Icon name="chevR" style={{ transform: showAdv ? 'rotate(90deg)' : 'none', width: 13, height: 13 }} />Avançado
          <span className="hint" style={{ marginLeft: 'auto', fontSize: 11 }}>{numClips} cenas · {autoDist ? totalMin + ' min total' : clipDur + 's/cena'} · {fmt === 'both' ? '2 formatos' : fmt === 'mobile' ? 'celular' : 'web'}</span>
        </button>
        {showAdv && <div className="panel stack">
          <div className="grid2">
            <Field label="Nº de cenas (máx 20)"><input className="inp" type="number" min="2" max="20" value={numClips} onChange={e => setNumClips(+e.target.value || 8)} /></Field>
            <Field label="Duração por cena (s)"><input className="inp" type="number" min="2" max="720" value={clipDur} disabled={autoDist} onChange={e => setClipDur(+e.target.value || 6)} /></Field>
          </div>
          <div className="rowx" style={{ justifyContent: 'space-between' }}>
            <span style={{ fontSize: 13 }}>Auto-distribuir duração total</span>
            <Check on={autoDist} onClick={() => setAutoDist(a => !a)} />
          </div>
          {autoDist && <div className="grid3">
            <Field label="Total (min)"><input className="inp" type="number" min="0.5" step="0.5" value={totalMin} onChange={e => setTotalMin(+e.target.value || 2)} /></Field>
            <Field label="1ª cena (min)"><input className="inp" type="number" min="0.1" step="0.1" value={firstMin} onChange={e => setFirstMin(+e.target.value || 0.5)} /></Field>
            <Field label="Última (min)"><input className="inp" type="number" min="0.1" step="0.1" value={lastMin} onChange={e => setLastMin(+e.target.value || 0.5)} /></Field>
          </div>}
          <Field label="Qualidade">
            <select className="inp" value={crf} onChange={e => setCrf(+e.target.value)}>
              <option value="24">Alta (CRF 24)</option>
              <option value="26">Média (CRF 26)</option>
              <option value="28">Econômica (CRF 28)</option>
            </select>
          </Field>
          <Field label="Formato de saída">
            <div className="checks">
              <Check on={fmt === 'web'} onClick={() => setFmt('web')}>Web · 1080p</Check>
              <Check on={fmt === 'mobile'} onClick={() => setFmt('mobile')}>Celular · 720p</Check>
              <Check on={fmt === 'both'} onClick={() => setFmt('both')}>Os 2 (gera 2)</Check>
            </div>
          </Field>
          <div className="sec mut" style={{ marginTop: 4 }}>Vídeo de abertura (opener)</div>
          {opener
            ? <div className="litem" style={{ padding: '8px 12px' }}>
                <span className="li-ic"><Icon name="play" /></span>
                <div className="li-main"><b style={{ fontSize: 12 }}>{opener.n}</b><small>posição: {openerPos === 'start' ? 'início' : 'fim'}</small></div>
                <button className="btn sm ghost" style={{ color: 'var(--pri)' }} onClick={() => setOpener(null)}>✕</button>
              </div>
            : <div className="rowx">
                <input ref={openerInputRef} type="file" accept="video/*" style={{ display: 'none' }} onChange={e => handleOpenerUpload(e.target.files)} />
                <button className="btn sm" onClick={() => openerInputRef.current && openerInputRef.current.click()}><Icon name="upload" />Subir da máquina</button>
                <button className="btn sm" onClick={() => setOpenerPick(p => !p)}><Icon name="media" />Do servidor</button>
              </div>}
          {openerUpPct > 0 && openerUpPct < 100 && <ProgressBar pct={openerUpPct} tone="cy" label="Enviando abertura…" />}
          {openerPick && <FilePicker onClose={() => setOpenerPick(false)} onSelect={f => { setOpener({ object_key: f.object_key, n: f.n }); setOpenerPick(false); }} />}
          {opener && <Field label="Posição da abertura">
            <div className="checks">
              <Check on={openerPos === 'start'} onClick={() => setOpenerPos('start')}>Início</Check>
              <Check on={openerPos === 'end'} onClick={() => setOpenerPos('end')}>Fim</Check>
            </div>
          </Field>}
        </div>}

        {/* RESULTADOS — logo SÓ aparece aqui, depois de gerar */}
        {jobs.filter(j => j.status === 'done').map((j, i) => <div key={i} className="panel stack" style={{ borderColor: 'rgba(0,230,118,.3)' }}>
          <div className="rowx" style={{ justifyContent: 'space-between' }}>
            <b style={{ fontSize: 13, fontFamily: 'var(--fh)' }}>{j.label}</b>
            <Pill kind="good" dot>pronto</Pill>
          </div>
          {j.resultKey && <RealPlayer objectKey={j.resultKey} style={{ maxHeight: 220 }} />}
          <div className="rowx" style={{ flexWrap: 'wrap' }}>
            <button className="btn pri sm" onClick={() => window.mpApi.download(j.resultKey, 'teaser.mp4')}><Icon name="download" />Baixar</button>
            <button className="btn sm" onClick={() => renameResult(j, jobs.indexOf(j))}><Icon name="pen" />Renomear</button>
            {!isBurned && !j.logoApplied && <button className="btn sm" onClick={() => setLogoModal({ teaserKey: j.resultKey, idx: jobs.indexOf(j) })}><Icon name="logo" />Queimar logo</button>}
            {j.logoApplied && <span className="pill good" style={{ fontSize: 11 }}><Icon name="check" />logo aplicada</span>}
            <button className="btn sm" onClick={() => { window.mpCtx.file = { object_key: j.resultKey, n: 'teaser', s: 'teaser' }; window.__mpOpen && window.__mpOpen('media'); }}><Icon name="media" />Ver em Arquivos</button>
            <button className="btn sm" onClick={() => { window.mpCtx.file = { object_key: j.resultKey, n: 'teaser', s: 'teaser' }; window.__mpOpen && window.__mpOpen('telegram'); }}><Icon name="telegram" />Telegram</button>
          </div>
        </div>)}

        <button className="btn pri block" disabled={!file || running} onClick={generate}>
          <Icon name="scissors" />{running ? 'Gerando…' : fmt === 'both' ? 'Gerar 2 teasers (web + celular)' : 'Gerar teaser'}
        </button>
      </div>
    </div>

    {/* MODAL fullscreen de geração */}
    <ProcessModal open={genActive} title={jobs.length > 1 ? 'Gerando teasers' : 'Gerando teaser'} detail={genDetail} pct={avgPct} phase={genPhase}
      onClose={() => setGenActive(false)} onCancel={() => { Object.values(pollRefs.current).forEach(t => clearInterval(t)); setGenActive(false); setJobs([]); }} />

    {/* MODAL de queima de logo */}
    {logoModal && <LogoBurnModal teaserKey={logoModal.teaserKey} runId={runId} profiles={profiles}
      onClose={() => setLogoModal(null)}
      onDone={(newKey) => { if (newKey) setJobs(js => js.map((x, i) => i === logoModal.idx ? { ...x, resultKey: newKey, logoApplied: true } : x)); }} />}
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

  const frameSrc = window.frameSrc;

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
