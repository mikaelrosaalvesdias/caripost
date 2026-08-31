/* Caripost OS — Modo Automático (fullscreen) + Assistente (wizard) */

const PIPE = [
  { k: 'upload',  ic: 'upload',     label: 'Upload' },
  { k: 'vision',  ic: 'analyze',    label: 'Vision IA' },
  { k: 'scenes',  ic: 'autoeditor', label: 'Detecção' },
  { k: 'select',  ic: 'sparkles',   label: 'Seleção Grok' },
  { k: 'cut',     ic: 'scissors',   label: 'Corte' },
  { k: 'legenda', ic: 'captions',   label: 'Legenda' },
  { k: 'logo',    ic: 'logo',       label: 'Logo' },
  { k: 'render',  ic: 'enhance',    label: 'Render' },
  { k: 'publish', ic: 'broadcast',  label: 'Publicar' },
];

function _detailToStage(detail) {
  const d = (detail || '').toLowerCase();
  if (d.includes('baixando') || d.includes('download')) return 0;
  if (d.includes('vision') || d.includes('analiz') || d.includes('frame')) return 1;
  if (d.includes('detect') || d.includes('cenas') || d.includes('candid')) return 2;
  if (d.includes('selecion') || d.includes('grok') || d.includes('escolh')) return 3;
  if (d.includes('cort') || d.includes('transi') || d.includes('cut')) return 4;
  if (d.includes('legenda') || d.includes('srt')) return 5;
  if (d.includes('logo') || d.includes('marca')) return 6;
  if (d.includes('render') || d.includes('export') || d.includes('finaliz')) return 7;
  if (d.includes('public')) return 8;
  return -1;
}

function AutoMode({ onExit, onClose }) {
  const [phase, setPhase] = React.useState('setup');
  const [allFiles, setAllFiles] = React.useState([]);
  const [catFilter, setCatFilter] = React.useState('original');
  const [selectedKeys, setSelectedKeys] = React.useState([]);
  const [thumbs, setThumbs] = React.useState({});       // object_key → thumb url
  const [uploading, setUploading] = React.useState(false);
  const [uploadPct, setUploadPct] = React.useState(0);
  const uploadRef = React.useRef(null);
  const [jobId, setJobId] = React.useState(null);
  const [active, setActive] = React.useState(0);
  const [pct, setPct] = React.useState(0);
  const [detail, setDetail] = React.useState('Aguardando inicio...');
  const [logs, setLogs] = React.useState([]);
  const [resultKey, setResultKey] = React.useState('');
  const pollRef = React.useRef(null);

  React.useEffect(() => {
    if (window.mpApi) {
      window.mpApi.listMedia().then(r => { setAllFiles(r); _loadThumbs(r); }).catch(() => {});
      window.mpApi.listAeJobs(1).then(jobs => {
        const running = (jobs || []).find(j => j.status === 'running' || j.status === 'pending');
        if (running) { setJobId(running.job_id); setPhase('running'); _startPoll(running.job_id); }
      }).catch(() => {});
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  function _loadThumbs(files) {
    files.slice(0, 40).forEach(f => {
      const key = f.object_key;
      if (!key) return;
      window.mpApi.fetch('/api/media-manager/thumbnail-url?object_key=' + encodeURIComponent(key))
        .then(r => { if (r.url) setThumbs(prev => ({ ...prev, [key]: r.url })); })
        .catch(() => {});
    });
  }

  async function handleUpload(files) {
    if (!files || !files.length || !window.mpApi) return;
    setUploading(true); setUploadPct(1);
    const arr = Array.from(files);
    try {
      let done = 0;
      const keys = await Promise.all(arr.map(f =>
        window.mpApi.uploadFile(f, p => setUploadPct(Math.round((done * 100 + p) / arr.length)))
          .then(k => { done++; return k; })
      ));
      setUploadPct(100);
      // Reload files and select newly uploaded
      window.mpApi.listMedia().then(r => { setAllFiles(r); _loadThumbs(r); }).catch(() => {});
      setSelectedKeys(prev => [...new Set([...prev, ...keys])]);
      setCatFilter('original');
    } catch (e) {
      alert('Upload falhou: ' + e.message);
    } finally {
      setUploading(false); setUploadPct(0);
    }
  }

  function _startPoll(id) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      if (!window.mpApi) return;
      window.mpApi.aeStatus(id).then(r => {
        const p = r.progress_pct || 0;
        const d = r.detail || '';
        const si = _detailToStage(d);
        if (si >= 0) setActive(si);
        setPct(p);
        setDetail(d || 'Processando...');
        setLogs(prev => {
          if (prev.length && prev[prev.length - 1].t === d) return prev;
          return [...prev.slice(-4).map(x => ({ ...x, s: 'done' })), { s: 'now', t: d }];
        });
        if (r.status === 'done') {
          clearInterval(pollRef.current);
          setActive(PIPE.length - 1); setPct(100); setPhase('done');
          setResultKey(r.result_video_object_key || '');
        } else if (r.status === 'error') {
          clearInterval(pollRef.current); setPhase('error');
          setDetail(r.detail || 'Erro no processamento');
        }
      }).catch(() => {});
    }, 4000);
  }

  async function startJob() {
    if (!selectedKeys.length) { alert('Selecione ao menos um video fonte.'); return; }
    if (!window.mpApi) return;
    try {
      setPhase('running'); setActive(0); setPct(5); setDetail('Iniciando...');
      setLogs([{ s: 'now', t: 'Job iniciado' }]);
      const r = await window.mpApi.startAutoEditor({
        video_object_key: selectedKeys[0],
        video_object_keys: selectedKeys,
        max_scenes: 60, transition_mode: 'smart',
        audio_normalize: true, audio_denoise: true,
      });
      setJobId(r.job_id); _startPoll(r.job_id);
    } catch (e) {
      setPhase('error'); setDetail('Erro ao iniciar: ' + e.message);
    }
  }

  const overall = phase === 'done' ? 100
    : Math.min(Math.round((active / PIPE.length) * 100 + pct / PIPE.length), 99);
  const etaMin = Math.max(1, Math.round((100 - overall) / 8));

  const CAT_FILTERS = [
    ['original', 'Originais'],
    ['burn', 'Queimados'],
    ['teaser', 'Teasers'],
    ['autoeditor', 'AutoEditor'],
  ];
  const visibleFiles = catFilter === 'all'
    ? allFiles
    : allFiles.filter(f => f.s === catFilter || (catFilter === 'original' && f.s === '4K original'));

  // === SETUP ===
  if (phase === 'setup') return (
    <div className="auto-screen">
      <div className="auto-top">
        <div className="kic"><Icon name="bolt" /></div>
        <div>
          <h2>Modo Automatico</h2>
          <div className="sub">Selecione os videos fonte para iniciar o pipeline completo</div>
        </div>
        <button className="btn exit" onClick={onExit} style={{ marginLeft: 'auto' }}><Icon name="restore" />Minimizar</button>
        <button className="wbtn close" onClick={onClose} style={{ width: 40, height: 40, borderRadius: 10 }}><Icon name="x" /></button>
      </div>

      <div style={{ padding: '14px 28px 0', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {CAT_FILTERS.map(([k, l]) => (
          <button key={k} className={'btn sm' + (catFilter === k ? ' pri' : '')} onClick={() => setCatFilter(k)}>{l}</button>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {uploading && <span className="hint" style={{ color: 'var(--cyan)' }}>Enviando… {uploadPct}%</span>}
          <input ref={uploadRef} type="file" accept="video/*" multiple style={{ display: 'none' }} onChange={e => handleUpload(e.target.files)} />
          <button className="btn sm cy" onClick={() => uploadRef.current && uploadRef.current.click()} disabled={uploading}>
            <Icon name="upload" />Upload da maquina
          </button>
        </div>
        {selectedKeys.length > 0 && (
          <span className="pill cy" style={{ fontSize: 11 }}>{selectedKeys.length} selecionado(s)</span>
        )}
      </div>

      <div style={{ padding: '12px 28px', flex: 1, overflow: 'auto' }}>
        {!allFiles.length && <div className="hint" style={{ textAlign: 'center', padding: 40 }}>Carregando arquivos do servidor...</div>}
        {allFiles.length > 0 && !visibleFiles.length && (
          <div className="hint" style={{ textAlign: 'center', padding: 40 }}>Nenhum arquivo nesta categoria.</div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12 }}>
          {visibleFiles.map(f => {
            const sel = selectedKeys.includes(f.object_key);
            const thumb = thumbs[f.object_key];
            return (
              <div key={f.object_key}
                style={{
                  borderRadius: 14, overflow: 'hidden', cursor: 'pointer',
                  border: '2px solid ' + (sel ? 'var(--pri)' : 'rgba(255,255,255,.08)'),
                  background: sel ? 'var(--pri-soft)' : 'rgba(255,255,255,.03)',
                  boxShadow: sel ? '0 0 0 1px var(--pri-line)' : 'none',
                  transition: 'border-color .15s, box-shadow .15s',
                  position: 'relative',
                }}
                onClick={() => setSelectedKeys(p => sel ? p.filter(k => k !== f.object_key) : [...p, f.object_key])}>
                {/* Thumbnail */}
                <div style={{ aspectRatio: '16/9', position: 'relative', background: 'linear-gradient(135deg,#16161f,#0c0c14)', overflow: 'hidden' }}>
                  {thumb
                    ? <img loading="lazy" decoding="async" src={thumb} alt={f.n} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                    : <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'rgba(255,255,255,.2)', fontSize: 28 }}>▶</div>
                  }
                  {/* Check badge */}
                  {sel && (
                    <div style={{ position: 'absolute', top: 7, right: 7, width: 22, height: 22, borderRadius: 6, background: 'var(--pri)', display: 'grid', placeItems: 'center', fontSize: 13, color: '#fff', boxShadow: '0 2px 8px rgba(255,23,68,.4)' }}>✓</div>
                  )}
                  {/* Duration if available */}
                  {f.dur && <span style={{ position: 'absolute', bottom: 6, right: 7, background: 'rgba(0,0,0,.75)', color: '#fff', fontSize: 10, fontFamily: 'var(--fm)', padding: '2px 7px', borderRadius: 5 }}>{f.dur}</span>}
                </div>
                {/* Label */}
                <div style={{ padding: '8px 10px 10px' }}>
                  <div style={{ fontSize: 11.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: sel ? 'var(--text)' : 'var(--text2)' }}>{f.n}</div>
                  <div style={{ fontSize: 10.5, color: 'var(--muted)', marginTop: 3 }}>{f.tech || f.size || ''}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="auto-foot">
        <button className="btn pri" onClick={startJob} disabled={!selectedKeys.length} style={{ fontSize: 14, padding: '11px 26px' }}>
          <Icon name="bolt" />Iniciar ({selectedKeys.length || 0} {selectedKeys.length === 1 ? 'video' : 'videos'})
        </button>
        <button className="btn ghost" onClick={onClose}>Cancelar</button>
      </div>
    </div>
  );

  // === RUNNING / DONE / ERROR ===
  const curPipe = PIPE[Math.min(active, PIPE.length - 1)];
  return (
    <div className="auto-screen">
      <div className="auto-top">
        <div className="kic"><Icon name="bolt" /></div>
        <div>
          <h2>Modo Automatico</h2>
          <div className="sub">{selectedKeys.length || 1} fonte(s) · AutoEditor + Grok Vision{jobId ? ' · ' + jobId.slice(0, 8) : ''}</div>
        </div>
        <div className="big">
          <b>{overall + '%'}</b>
          <span>{phase === 'done' ? 'concluido!' : phase === 'error' ? 'erro' : '~' + etaMin + ' min restantes'}</span>
        </div>
        <button className="btn exit" onClick={onExit}><Icon name="restore" />Minimizar</button>
        <button className="wbtn close" onClick={onClose} style={{ width: 40, height: 40, borderRadius: 10 }}><Icon name="x" /></button>
      </div>

      <div className="pipe">
        {PIPE.map((n, i) => {
          const st = phase === 'done' ? 'done' : i < active ? 'done' : i === active ? 'run' : 'queue';
          return (
            <React.Fragment key={n.k}>
              <div className={'pnode ' + st}>
                <div className="ball">{st === 'done' ? <Icon name="check" /> : <Icon name={n.ic} />}</div>
                <b>{n.label}</b>
                <small>{st === 'done' ? 'ok' : st === 'run' ? 'rodando' : 'na fila'}</small>
              </div>
              {i < PIPE.length - 1 && <div className={'pconn ' + (i < active || phase === 'done' ? 'done' : i === active ? 'run' : '')} />}
            </React.Fragment>
          );
        })}
      </div>

      <div className="auto-mid">
        <div className="auto-card">
          <h4>
            <Icon name={curPipe.ic} style={{ width: 18, height: 18, color: 'var(--cyan)' }} />
            Etapa atual — {phase === 'done' ? 'Concluido' : phase === 'error' ? 'Erro' : curPipe.label}
            {phase === 'running' && <span className="spin" />}
          </h4>
          <LogLines items={logs.length ? logs : [{ s: 'now', t: detail }]} />
          <ProgressBar pct={pct} tone={phase === 'error' ? 'pri' : 'cy'} label={detail} eta={phase === 'done' ? 'concluido' : ''} />
          <div style={{ marginTop: 'auto' }}>
            <ProgressBar pct={overall} label="Progresso total do fluxo" eta={active + ' de ' + PIPE.length + ' etapas concluidas'} />
          </div>
        </div>
        <div className="auto-card">
          <h4><Icon name="eye" style={{ width: 18, height: 18 }} />Resultado</h4>
          <div className="auto-prev">
            {phase === 'done' && resultKey
              ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div className="pill good" style={{ alignSelf: 'flex-start' }}><Icon name="check" />AutoEditor concluido</div>
                  <div className="kv" style={{ fontSize: 12 }}>
                    <div className="row"><span className="k">Arquivo</span><span className="v mono" style={{ wordBreak: 'break-all', fontSize: 11 }}>{resultKey.split('/').pop()}</span></div>
                  </div>
                  <div className="rowx">
                    <button className="btn pri" onClick={() => {
                      if (window.mpApi) window.mpApi.fetch('/api/video-download-url?object_key=' + encodeURIComponent(resultKey))
                        .then(r => { if (r.url) window.open(r.url, '_blank'); }).catch(() => {});
                    }}><Icon name="download" />Download</button>
                    <button className="btn" onClick={() => { if (window.__mpOpen) window.__mpOpen('criacao'); onExit(); }}><Icon name="post" />Criar Post</button>
                  </div>
                </div>
              )
              : <VStage dur="--:--" time={'-- / --'} pos={pct} logo={false} subtitle={detail} />
            }
          </div>
        </div>
      </div>

      <div className="auto-foot">
        {phase === 'running' && (
          <button className="btn" onClick={() => { if (window.__mpOpen) window.__mpOpen('autoeditor'); onExit(); }}>
            <Icon name="pen" />Ver no AutoEditor
          </button>
        )}
        {phase === 'done' && (
          <button className="btn pri" onClick={() => { if (window.__mpOpen) window.__mpOpen('media'); onExit(); }}>
            <Icon name="media" />Ver em Arquivos
          </button>
        )}
        {phase === 'error' && (
          <button className="btn" onClick={() => { setPhase('setup'); setSelectedKeys([]); setLogs([]); }}>
            <Icon name="refresh" />Tentar novamente
          </button>
        )}
        <span className="pill cy" style={{ marginLeft: 'auto' }}><Icon name="bell" />Avisar no Telegram quando concluir</span>
      </div>
    </div>
  );
}

const WIZ = [
  { t: 'Origem',      d: 'Escolha o video bruto',         ic: 'upload' },
  { t: 'Transcricao', d: 'Gere e revise as legendas',     ic: 'captions' },
  { t: 'Marca',       d: 'Aplique logo e estilo',         ic: 'logo' },
  { t: 'Conteudo',    d: 'Titulo, descricao e capa',      ic: 'sparkles' },
  { t: 'Publicar',    d: 'Agende ou poste',               ic: 'send' },
];

function WizardApp() {
  const [i, setI] = React.useState(1);
  return <div className="app">
    <div className="app-head">
      <div className="tb-ic" style={{ width: 40, height: 40, borderRadius: 12 }}><Icon name="flow" style={{ width: 20, height: 20 }} /></div>
      <div className="lead">
        <div className="app-title">Assistente de Fluxo</div>
        <div className="app-desc">Conduz voce do upload a publicacao, um passo de cada vez.</div>
      </div>
      <Pill kind="cy" dot>passo {i + 1} de {WIZ.length}</Pill>
    </div>

    <div className="wiz-steps">
      {WIZ.map((s, idx) => <React.Fragment key={idx}>
        <button className={'wstep' + (idx < i ? ' done' : idx === i ? ' on' : '')} onClick={() => setI(idx)}>
          <span className="wd">{idx < i ? <Icon name="checkSm" style={{ width: 12, height: 12 }} /> : idx + 1}</span>{s.t}
        </button>
        {idx < WIZ.length - 1 && <span className={'wsep' + (idx < i ? ' done' : '')} />}
      </React.Fragment>)}
    </div>

    <div className="panel stack" style={{ minHeight: 220 }}>
      <div className="rowx" style={{ gap: 12 }}>
        <div className="tb-ic" style={{ width: 36, height: 36, borderRadius: 11 }}><Icon name={WIZ[i].ic} style={{ width: 18, height: 18 }} /></div>
        <div><b style={{ fontFamily: 'var(--fh)', fontSize: 17 }}>{WIZ[i].t}</b><div style={{ fontSize: 13, color: 'var(--muted)' }}>{WIZ[i].d}</div></div>
      </div>
      {i === 0 && <div className="dropzone"><div className="dz-ic"><Icon name="upload" /></div><b>Arraste o video</b><small>MP4 / MOV ate 8 GB</small></div>}
      {i === 1 && <div className="split"><Media cap="previa" subtitle="conteudo especial" /><div className="stack"><ProgressBar pct={100} tone="gd" label="Transcricao" eta="concluida" /><Field label="Revisar"><textarea className="inp" defaultValue="Fala galera, bem-vindos ao canal..." /></Field></div></div>}
      {i === 2 && <div className="split"><Media cap="previa" logo play={false} /><div className="stack"><Field label="Logo"><div className="litem"><span className="li-ic"><Icon name="star" /></span><div className="li-main"><b>marca_estudio.png</b></div></div></Field><Field label="Posicao"><div className="checks"><Check>Sup. esq.</Check><Check on>Inf. dir.</Check></div></Field></div></div>}
      {i === 3 && <div className="stack"><Field label="Titulo"><input className="inp" defaultValue="Bastidores do estudio" /></Field><Field label="Capa"><div className="thumbs">{['00:12', '01:04', '02:20'].map((t, k) => <Thumb key={t} label={t} sel={k === 1} />)}</div></Field></div>}
      {i === 4 && <div className="grid2"><div className="panel" style={{ padding: 0, overflow: 'hidden' }}><Media cap="post pronto" logo play /></div><div className="stack"><Field label="Plataformas"><div className="checks"><Check on>Portal</Check><Check on>Telegram</Check></div></Field><Field label="Quando"><div className="checks"><Check on>Agora</Check><Check>Agendar</Check></div></Field><button className="btn pri block"><Icon name="send" />Publicar</button></div></div>}
    </div>

    <div className="rowx" style={{ justifyContent: 'space-between' }}>
      <button className="btn ghost" disabled={i === 0} onClick={() => setI(Math.max(0, i - 1))}><Icon name="arrowL" />Voltar</button>
      <div className="rowx"><button className="btn ghost">Pular</button>
        <button className="btn pri" onClick={() => setI(Math.min(WIZ.length - 1, i + 1))}>{i === WIZ.length - 1 ? 'Concluir' : 'Proximo'}<Icon name="arrowR" /></button></div>
    </div>
  </div>;
}

Object.assign(window, { AutoMode, WizardApp, PIPE, WIZ });
