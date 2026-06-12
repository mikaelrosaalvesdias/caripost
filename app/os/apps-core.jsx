/* MetaPorn OS — Inteligência & Mídia: Analyze, Compare, Runs, Arquivos */

function AppHead({ icon, title, desc, right }) {
  return <div className="app-head">
    <div className="tb-ic" style={{ width: 42, height: 42, borderRadius: 12 }}><Icon name={icon} style={{ width: 21, height: 21 }} /></div>
    <div className="lead">
      <div className="app-title">{title}</div>
      <div className="app-desc">{desc}</div>
    </div>
    {right}
  </div>;
}

/* Thumb real com fallback — usado em vários apps */
function RealThumb({ objectKey, alt, style }) {
  const [url, setUrl] = React.useState(null);
  const [err, setErr] = React.useState(false);
  React.useEffect(() => {
    let alive = true;
    if (window.mpApi && objectKey) {
      window.mpApi.thumbUrl(objectKey).then(u => { if (alive) setUrl(u); }).catch(() => { if (alive) setErr(true); });
    }
    return () => { alive = false; };
  }, [objectKey]);
  if (url) return <img src={url} alt={alt || ''} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', ...style }} />;
  return <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'rgba(255,255,255,.18)', fontSize: 26, background: 'linear-gradient(135deg,#16161f,#0c0c14)', ...style }}>{err ? '◼' : '▶'}</div>;
}

/* Player real — busca stream URL e toca */
function RealPlayer({ objectKey, style }) {
  const [src, setSrc] = React.useState('');
  React.useEffect(() => {
    let alive = true;
    if (window.mpApi && objectKey) {
      window.mpApi.streamUrl(objectKey).then(u => { if (alive) setSrc(u); }).catch(() => {});
    }
    return () => { alive = false; };
  }, [objectKey]);
  if (!src) return <div className="vstage" style={{ aspectRatio: '16/9', ...style }}><div className="ph" /><div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--muted)', fontSize: 13 }}>Carregando vídeo…</div></div>;
  return <video src={src} controls preload="metadata" playsInline style={{ width: '100%', maxHeight: 420, background: '#000', borderRadius: 14, border: '1px solid var(--line2)', display: 'block', ...style }} />;
}

/* Converte frame (base64 puro, data-uri, url ou objeto) em src de <img> válido */
function frameSrc(f) {
  if (!f) return '';
  let s = typeof f === 'string' ? f : (f.b64 || f.url || f.image || f.src || '');
  if (!s) return '';
  if (s.startsWith('data:') || s.startsWith('http') || s.startsWith('/')) return s;
  return 'data:image/jpeg;base64,' + s;
}

/* ── ProcessModal — overlay fullscreen com círculo girando, tempo decorrido e ETA ── */
function ProcessModal({ open, title, detail, pct, phase, onClose, onCancel }) {
  const [elapsed, setElapsed] = React.useState(0);
  const startRef = React.useRef(null);
  React.useEffect(() => {
    if (!open) { startRef.current = null; setElapsed(0); return; }
    startRef.current = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 500);
    return () => clearInterval(id);
  }, [open]);
  if (!open) return null;
  const fmt = s => {
    s = Math.max(0, Math.round(s));
    const m = Math.floor(s / 60), ss = s % 60;
    return (m > 0 ? m + 'm ' : '') + String(ss).padStart(m > 0 ? 2 : 1, '0') + 's';
  };
  const p = Math.max(0, Math.min(100, pct || 0));
  // ETA estimado pela taxa de progresso
  const eta = p > 3 && p < 100 ? (elapsed / p) * (100 - p) : null;
  const isErr = phase === 'error';
  const isDone = phase === 'done';
  return <div className={'proc-modal' + (isErr ? ' err' : '')}>
    <div className="proc-ring-wrap">
      {isDone
        ? <div style={{ width: 150, height: 150, borderRadius: '50%', display: 'grid', placeItems: 'center', background: 'var(--good)', boxShadow: '0 0 30px rgba(0,230,118,.4)' }}><Icon name="check" style={{ width: 54, height: 54, color: '#fff' }} /></div>
        : <>
            <div className="proc-ring" />
            <div className="proc-pct">{isErr ? '!' : p + '%'}</div>
          </>}
    </div>
    <div className="proc-title">{isErr ? 'Falhou' : isDone ? 'Concluído!' : (title || 'Processando…')}</div>
    <div className="proc-detail">{detail || ''}</div>
    {!isDone && !isErr && <>
      <div className="proc-track"><i style={{ width: p + '%' }} /></div>
      <div className="proc-times">
        <div className="proc-time-b"><b>{fmt(elapsed)}</b><span>decorrido</span></div>
        <div className="proc-time-b"><b>{eta != null ? '~' + fmt(eta) : '—'}</b><span>restante</span></div>
      </div>
    </>}
    <div className="proc-actions">
      {(isDone || isErr)
        ? <button className="btn pri" onClick={onClose}>Fechar</button>
        : onCancel && <button className="btn ghost" onClick={onCancel}>Cancelar</button>}
    </div>
  </div>;
}

/* ── ANALYZE — transcrição, análise e prompt ── */
function AnalyzeApp() {
  const [tab, setTab] = React.useState('prompt');
  const [stt, setStt] = React.useState('premium');
  const [busy, setBusy] = React.useState(false);
  const [busyLabel, setBusyLabel] = React.useState('');
  const [uploadPct, setUploadPct] = React.useState(0);
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [result, setResult] = React.useState(null);
  const [srt, setSrt] = React.useState('');
  const [frames, setFrames] = React.useState([]);
  const fileInputRef = React.useRef(null);
  const providers = [
    ['auto', '⚡ Auto estrito'], ['assemblyai', 'AssemblyAI'], ['groq', 'OpenRouter STT'],
    ['openai', 'OpenAI'], ['local', '🖥 Local'], ['premium', '⭐ Premium'],
  ];

  // Se veio do Arquivos com run existente, carrega o resultado
  React.useEffect(() => {
    const ctx = window.mpCtx?.file;
    if (ctx && window.mpApi) {
      setFile(ctx);
      window.mpApi.findRunForKey(ctx.object_key).then(rid => {
        if (rid) _loadRun(rid);
      }).catch(() => {});
    }
  }, []);

  async function _loadRun(runId) {
    try {
      const run = await window.mpApi.getRun(runId);
      setResult({ run_id: runId, ...run.result });
      window.mpApi.getRunSrt(runId).then(s => setSrt(typeof s === 'string' ? s : (s.srt || ''))).catch(() => {});
      window.mpApi.getRunFrames(runId).then(f => setFrames(f || [])).catch(() => {});
    } catch (_) {}
  }

  async function handleFiles(files) {
    if (!files || !files.length || !window.mpApi) return;
    const arr = Array.from(files);
    try {
      setUploadPct(1);
      let done = 0;
      const keys = await Promise.all(arr.map(f =>
        window.mpApi.uploadFile(f, p => setUploadPct(Math.round((done * 100 + p) / arr.length)))
          .then(k => { done++; return k; })
      ));
      setUploadPct(100);
      setFile({ object_key: keys[0], n: arr[0].name });
      setTimeout(() => setUploadPct(0), 1200);
    } catch (e) {
      setUploadPct(0);
      alert('Upload falhou: ' + e.message);
    }
  }

  async function doAnalyze() {
    if (!file?.object_key) { alert('Selecione ou envie um vídeo primeiro.'); return; }
    setBusy(true); setBusyLabel('Transcrevendo + analisando… (pode levar minutos)');
    try {
      const r = await window.mpApi.analyze({
        video_object_key: file.object_key,
        original_filename: file.n || '',
        limit: 20,
      });
      setResult(r);
      if (r.run_id) {
        window.mpApi.getRunSrt(r.run_id).then(s => setSrt(typeof s === 'string' ? s : (s.srt || ''))).catch(() => {});
        window.mpApi.getRunFrames(r.run_id).then(f => setFrames(f || [])).catch(() => {});
      }
    } catch (e) {
      alert('Análise falhou: ' + e.message);
    } finally { setBusy(false); }
  }

  const sug = result?.suggested || {};
  const grok = result?.grok || {};
  const vision = result?.vision || {};
  const promptText = grok.prompt || grok.title_prompt || sug.description_template ||
    (result ? JSON.stringify(sug, null, 2) : '');

  return <div className="app">
    <AppHead icon="analyze" title="Analyze" desc="Transcrição PT-BR, análise por IA e geração de prompt — tudo em um."
      right={<Pill kind="good" dot>storage online</Pill>} />
    <div className="split">
      {/* ENTRADA */}
      <div className="stack">
        <div className="panel stack">
          <div className="sec"><Icon name="upload" />Upload de vídeo (direto para storage)</div>
          <div className="dropzone" data-tour="an-drop" style={{ padding: '26px 20px', cursor: 'pointer' }}
            onClick={() => fileInputRef.current && fileInputRef.current.click()}
            onDragOver={e => { e.preventDefault(); e.currentTarget.classList.add('drag'); }}
            onDragLeave={e => e.currentTarget.classList.remove('drag')}
            onDrop={e => { e.preventDefault(); e.currentTarget.classList.remove('drag'); handleFiles(e.dataTransfer.files); }}>
            <input ref={fileInputRef} type="file" accept="video/*" multiple style={{ display: 'none' }} onChange={e => handleFiles(e.target.files)} />
            <div className="dz-ic"><Icon name="upload" /></div>
            <b>{file?.n || 'Arraste vídeos aqui ou clique para selecionar'}</b>
            <small>MP4 / MOV / MKV · upload direto para storage</small>
          </div>
          {uploadPct > 0 && uploadPct < 100 && <ProgressBar pct={uploadPct} tone="cy" label="Enviando para storage…" />}
          <div className="kv" style={{ fontSize: 12 }}>
            <div className="row"><span className="k">object_key</span><span className="v mono" style={{ fontSize: 10.5, wordBreak: 'break-all', textAlign: 'right' }}>{file?.object_key || 'nenhum selecionado'}</span></div>
            <div className="row"><span className="k">status</span><span className="v" style={{ color: file ? 'var(--good)' : 'var(--muted)' }}>{file ? 'pronto para análise' : 'aguardando vídeo'}</span></div>
          </div>
        </div>

        <div>
          <label className="lbl">Motor de transcrição (STT)</label>
          <div className="rowx" data-tour="an-stt">
            {providers.map(([k, l]) => <button key={k} className={'btn sm' + (stt === k ? ' pri' : '')} onClick={() => setStt(k)}>{l}</button>)}
          </div>
        </div>

        <div className="rowx" data-tour="an-go">
          <button className="btn pri" disabled={busy} onClick={doAnalyze}><Icon name="sparkles" />{busy ? 'Analisando…' : 'Analisar'}</button>
          <button className="btn ghost" onClick={() => { setFile(null); setResult(null); setSrt(''); setFrames([]); window.mpCtx.file = null; }}>Limpar</button>
        </div>
        {busy && <div className="panel"><ProgressBar pct={70} tone="cy" label={busyLabel} eta="transcrição + Grok Vision em andamento" /></div>}
      </div>

      {/* RESULTADO */}
      <div className="stack">
        <div className="rowx" style={{ justifyContent: 'space-between' }}>
          <span className="hint" style={{ fontSize: 12, color: 'var(--muted)' }}>run_id: <b style={{ fontFamily: 'var(--fm)', color: 'var(--text2)' }}>{result?.run_id ? result.run_id.slice(0, 12) : '—'}</b></span>
          <div className="rowx">
            <button className="btn sm" onClick={() => { if (promptText) navigator.clipboard.writeText(promptText); }}><Icon name="copy" />Copiar prompt</button>
            <button className="btn sm" onClick={() => window.__mpOpen && window.__mpOpen('compare')}>→ Compare</button>
          </div>
        </div>
        <div className="tabbar">
          {[['prompt', 'Resultado'], ['srt', 'SRT'], ['vision', 'Visão IA'], ['json', 'JSON']].map(([k, l]) =>
            <button key={k} className={'tabx' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}
        </div>
        {tab === 'prompt' && <div className="panel" style={{ fontFamily: 'var(--fm)', fontSize: 12.5, lineHeight: 1.7, color: 'var(--text2)', whiteSpace: 'pre-wrap', maxHeight: 380, overflow: 'auto' }}>
          {result
            ? [
                sug.tags?.length ? 'TAGS: ' + sug.tags.join(', ') : '',
                sug.description_template ? '\nDESCRIÇÃO:\n' + sug.description_template : '',
                grok.title ? '\nTÍTULO: ' + grok.title : '',
                grok.description ? '\nDESC GROK:\n' + grok.description : '',
              ].filter(Boolean).join('\n') || JSON.stringify(result.suggested || result.grok || {}, null, 2)
            : 'Analise um vídeo para ver o resultado aqui.'}
        </div>}
        {tab === 'srt' && <div className="stack">
          <button className="btn sm" style={{ alignSelf: 'flex-start' }} disabled={!srt} onClick={() => {
            const blob = new Blob([srt], { type: 'text/plain' });
            const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'legendas.srt'; a.click();
          }}><Icon name="download" />Baixar .SRT</button>
          <div className="panel" style={{ fontFamily: 'var(--fm)', fontSize: 12, lineHeight: 1.7, color: 'var(--text2)', whiteSpace: 'pre-wrap', maxHeight: 340, overflow: 'auto' }}>
            {srt || 'SRT indisponível — analise um vídeo com transcrição.'}
          </div>
        </div>}
        {tab === 'vision' && <div className="stack">
          {frames.length > 0 && <div className="thumbs">{frames.slice(0, 6).map((f, i) =>
            <div key={i} className="thumb"><img src={frameSrc(f)} alt={'frame ' + i} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} /></div>)}
          </div>}
          <div className="panel" style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.6, maxHeight: 300, overflow: 'auto' }}>
            <b style={{ color: 'var(--cyan)' }}>Grok Vision:</b> {vision.analysis || vision.description || 'Sem análise de visão disponível.'}
          </div>
        </div>}
        {tab === 'json' && <div className="panel" style={{ fontFamily: 'var(--fm)', fontSize: 11.5, lineHeight: 1.6, color: 'var(--text2)', whiteSpace: 'pre-wrap', maxHeight: 380, overflow: 'auto' }}>
          {result ? JSON.stringify(result, null, 2) : '{ }'}
        </div>}
      </div>
    </div>
  </div>;
}

/* ── COMPARE — comparação entre modelos ── */
function CompareApp() {
  const [prompt, setPrompt] = React.useState('Gere um título chamativo (máx 60 caracteres) para um vídeo adulto amador brasileiro.');
  const [busy, setBusy] = React.useState(false);
  const [results, setResults] = React.useState(null);
  const MODELS = [
    { provider: 'grok', label: 'Grok', tone: 'pri' },
    { provider: 'openai', label: 'OpenAI', tone: 'cy' },
    { provider: 'deepseek', label: 'DeepSeek', tone: 'violet' },
    { provider: 'gemini', label: 'Gemini', tone: '' },
  ];

  async function run() {
    if (!window.mpApi) return;
    setBusy(true); setResults(null);
    try {
      const r = await window.mpApi.compare({
        prompt,
        providers: MODELS.map(m => ({ name: m.provider })),
      });
      setResults(r.results || r.responses || r);
    } catch (e) {
      alert('Compare falhou: ' + e.message);
    } finally { setBusy(false); }
  }

  function _resFor(provider) {
    if (!results) return null;
    if (Array.isArray(results)) return results.find(r => (r.provider || r.name) === provider);
    return results[provider];
  }

  return <div className="app">
    <AppHead icon="compare" title="Compare" desc="Roda o mesmo prompt em vários modelos e mostra custo, tempo, tokens e resultado lado a lado."
      right={<button className="btn pri sm" disabled={busy} onClick={run}><Icon name="bolt" />{busy ? 'Rodando…' : 'Rodar modelos'}</button>} />
    <Field label="Prompt"><textarea className="inp" rows="2" value={prompt} onChange={e => setPrompt(e.target.value)} /></Field>
    {busy && <div className="panel"><ProgressBar pct={60} tone="cy" label="Consultando modelos em paralelo…" /></div>}
    <div className="grid2">
      {MODELS.map(m => {
        const r = _resFor(m.provider);
        const txt = r ? (r.text || r.output || r.response || r.error || JSON.stringify(r).slice(0, 200)) : '';
        return <div key={m.provider} className="panel stack" style={{ position: 'relative' }}>
          <div className="rowx" style={{ justifyContent: 'space-between' }}>
            <b style={{ fontFamily: 'var(--fh)', fontSize: 16 }}>{m.label}</b>
            {r?.elapsed_ms != null && <Pill kind={m.tone} dot>{(r.elapsed_ms / 1000).toFixed(1)}s</Pill>}
          </div>
          <div style={{ fontSize: 13.5, color: 'var(--text)', lineHeight: 1.5, minHeight: 44, whiteSpace: 'pre-wrap', maxHeight: 140, overflow: 'auto' }}>
            {txt ? '"' + txt + '"' : (busy ? '…' : 'aguardando execução')}
          </div>
          {r?.tokens != null && <div className="rowx" style={{ gap: 8 }}>
            <span className="chip"><Icon name="sparkles" />{r.tokens} tok</span>
          </div>}
          <button className="btn block" disabled={!txt} onClick={() => navigator.clipboard.writeText(txt)}><Icon name="copy" />Copiar</button>
        </div>;
      })}
    </div>
  </div>;
}

/* ── RUNS — histórico técnico e resultados ── */
function RunsApp() {
  const [sel, setSel] = React.useState(0);
  const [runs, setRuns] = React.useState([]);
  const [detail, setDetail] = React.useState(null);
  const [frames, setFrames] = React.useState([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.listRuns(60).then(r => { setRuns(r); setLoading(false); if (r.length) _select(r[0], 0); })
      .catch(() => setLoading(false));
  }, []);

  async function _select(run, idx) {
    setSel(idx);
    setDetail(null); setFrames([]);
    try {
      const d = await window.mpApi.getRun(run.id);
      setDetail(d);
      window.mpApi.getRunFrames(run.id).then(f => setFrames(f || [])).catch(() => {});
    } catch (_) {}
  }

  const cur = runs[sel];
  const res = detail?.result || {};
  const sug = res.suggested || {};
  const grok = res.grok || {};

  return <div className="app" style={{ padding: 0 }}>
    <div style={{ padding: '22px 22px 0' }}>
      <AppHead icon="runs" title="Runs" desc="Histórico técnico de todas as análises — prompt, SRT, frames e JSON de cada execução." />
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 0, borderTop: '1px solid var(--line)', minHeight: 0, flex: 1 }}>
      <div style={{ borderRight: '1px solid var(--line)', padding: 14, display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto', maxHeight: 520 }}>
        {loading && <div className="hint">Carregando runs…</div>}
        {!loading && !runs.length && <div className="hint">Nenhum run ainda. Use o Analyze.</div>}
        {runs.map((r, i) => <button key={r.id} className="litem" style={{ textAlign: 'left', borderColor: i === sel ? 'var(--pri-line)' : undefined, background: i === sel ? 'var(--pri-soft)' : undefined }} onClick={() => _select(r, i)}>
          <div className="li-main">
            <b style={{ fontFamily: 'var(--fm)', fontSize: 11, color: 'var(--muted)' }}>{r.id.slice(0, 8)}</b>
            <small style={{ display: 'block', color: 'var(--text2)', fontSize: 12, margin: '2px 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.snip}</small>
            <span style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', color: r.ok ? 'var(--good)' : 'var(--pri)' }}>{r.ok ? 'OK' : 'ERRO'} · {r.date}</span>
          </div>
        </button>)}
      </div>
      <div className="stack" style={{ padding: 20, overflowY: 'auto', maxHeight: 520 }}>
        {!cur && <div className="hint">Selecione um run.</div>}
        {cur && <>
          <div className="rowx" style={{ justifyContent: 'space-between' }}>
            <b style={{ fontFamily: 'var(--fm)', fontSize: 13 }}>{cur.id}</b>
            <Pill kind={cur.ok ? 'good' : 'pri'} dot>{cur.ok ? 'concluído' : 'erro'}</Pill>
          </div>
          {frames.length > 0 && <>
            <div className="sec mut"><Icon name="layers" />Frames-chave</div>
            <div className="thumbs">{frames.slice(0, 6).map((f, i) =>
              <div key={i} className="thumb"><img src={frameSrc(f)} alt={'frame'} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} /></div>)}
            </div>
          </>}
          <div className="sec mut"><Icon name="doc" />Metadados</div>
          <div className="kv">
            <div className="row"><span className="k">Arquivo</span><span className="v" style={{ fontSize: 12 }}>{cur.snip}</span></div>
            <div className="row"><span className="k">Título sugerido</span><span className="v" style={{ fontSize: 12 }}>{grok.title || '—'}</span></div>
            <div className="row"><span className="k">Tags</span><span className="v" style={{ fontSize: 12 }}>{(sug.tags || []).slice(0, 6).join(' · ') || '—'}</span></div>
            <div className="row"><span className="k">object_key</span><span className="v mono" style={{ fontSize: 10, wordBreak: 'break-all' }}>{cur.video_object_key || '—'}</span></div>
          </div>
          <div className="rowx">
            <button className="btn sm" onClick={async () => {
              const s = await window.mpApi.getRunSrt(cur.id);
              const txt = typeof s === 'string' ? s : (s.srt || '');
              if (!txt) { alert('SRT indisponível para este run.'); return; }
              const blob = new Blob([txt], { type: 'text/plain' });
              const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'legendas.srt'; a.click();
            }}><Icon name="download" />Baixar SRT</button>
            <button className="btn sm" onClick={() => {
              window.mpCtx.file = { object_key: cur.video_object_key, n: cur.snip, run_id: cur.id };
              window.__mpOpen && window.__mpOpen('criacao');
            }}>→ Criar Post</button>
            <button className="btn sm ghost" style={{ color: 'var(--pri)' }} onClick={async () => {
              if (!confirm('Excluir este run?')) return;
              try { await window.mpApi.fetch('/runs/' + cur.id, { method: 'DELETE' }); setRuns(rs => rs.filter(r => r.id !== cur.id)); setSel(0); }
              catch (e) { alert('Erro: ' + e.message); }
            }}><Icon name="trash" />Excluir</button>
          </div>
        </>}
      </div>
    </div>
  </div>;
}

/* ── ARQUIVOS — file manager: clique no vídeo abre ações ── */
const FILE_ACTIONS = [
  { app: 'autoeditor', icon: 'autoeditor', label: 'AutoEditor', desc: 'Cortar / re-cut com IA', tone: 'violet' },
  { app: 'legenda', icon: 'captions', label: 'Legenda', desc: 'Transcrever e queimar', tone: 'cy' },
  { app: 'logo', icon: 'logo', label: 'Logo', desc: "Marca d'água", tone: 'cy' },
  { app: 'teaser', icon: 'scissors', label: 'Teaser', desc: 'Corte curto vertical', tone: 'cy' },
  { app: 'thumbnail', icon: 'thumbnail', label: 'Thumbnail', desc: 'Capa por IA', tone: 'violet' },
  { app: 'enhancer', icon: 'enhance', label: 'Melhorar', desc: 'Upscale de qualidade', tone: 'cy' },
  { app: 'criacao', icon: 'post', label: 'Criar Post', desc: 'Montar publicação', tone: 'pri' },
  { app: 'publisher', icon: 'broadcast', label: 'Publicar', desc: 'Enviar às plataformas', tone: 'pri' },
  { app: 'telegram', icon: 'telegram', label: 'Telegram', desc: 'Disparar ao grupo', tone: 'cy' },
];
const FILTERS = [['all', 'Todos'], ['original', 'Originais'], ['burn', 'Queimados'], ['teaser', 'Teasers'], ['autoeditor', 'AutoEditor']];

function FileActionGrid({ file, onOpen }) {
  return <div className="fa-grid">
    {FILE_ACTIONS.map(a => <button key={a.app} className="fa-tile" onClick={() => onOpen(a.app, file)}>
      <span className={'fa-ic ' + a.tone}><Icon name={a.icon} /></span>
      <b>{a.label}</b><small>{a.desc}</small>
    </button>)}
  </div>;
}

function MediaApp() {
  const [view, setView] = React.useState('icons');
  const [filter, setFilter] = React.useState('all');
  const [search, setSearch] = React.useState('');
  const [sel, setSel] = React.useState(null);
  const [ctx, setCtx] = React.useState(null);
  const [allItems, setAllItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [metaMap, setMetaMap] = React.useState({});
  const [busyOp, setBusyOp] = React.useState('');

  React.useEffect(() => { _reload(); }, []);

  async function _reload() {
    if (!window.mpApi) return;
    setLoading(true);
    try {
      const items = await window.mpApi.listMedia();
      setAllItems(items);
      // metadados em lote (rápido) para duração/resolução
      const keys = items.map(i => i.object_key);
      window.mpApi.metaBatch(keys).then(m => setMetaMap(m)).catch(() => {});
    } catch (_) {} finally { setLoading(false); }
  }

  const items = allItems
    .filter(m => filter === 'all' || m.s === filter || (filter === 'original' && m.s === '4K original'))
    .filter(m => !search || m.n.toLowerCase().includes(search.toLowerCase()));

  function _techFor(m) {
    const meta = metaMap[m.object_key];
    if (!meta) return m.tech || '';
    const parts = [];
    if (meta.height) parts.push(meta.height + 'p');
    if (meta.duration_seconds) parts.push(window.__mpFmtTime(meta.duration_seconds));
    return parts.join(' · ') || m.tech;
  }
  function _durFor(m) {
    const meta = metaMap[m.object_key];
    return meta?.duration_seconds ? window.__mpFmtTime(meta.duration_seconds) : '';
  }

  /* Abre app de função COM o arquivo no contexto global */
  const openApp = (app, file) => {
    setCtx(null);
    window.mpCtx.file = { object_key: file.object_key, n: file.n, s: file.s, run_id: null };
    if (window.__mpOpen) window.__mpOpen(app);
  };

  /* Operações de arquivo reais */
  async function doDownload(f) {
    setBusyOp('download');
    try {
      const url = await window.mpApi.downloadUrl(f.object_key, f.n.replace(/\.[^.]+$/, ''));
      if (url) window.open(url, '_blank');
    } catch (e) { alert('Erro no download: ' + e.message); }
    finally { setBusyOp(''); }
  }
  async function doRename(f) {
    const newName = prompt('Novo nome do arquivo:', f.n);
    if (!newName || newName === f.n) return;
    setBusyOp('rename');
    try {
      await window.mpApi.renameMedia(f.object_key, newName);
      await _reload();
      setSel(null);
    } catch (e) { alert('Erro ao renomear: ' + e.message); }
    finally { setBusyOp(''); }
  }
  function doCopy(f) {
    navigator.clipboard.writeText(f.object_key);
  }
  async function doDelete(f) {
    if (!confirm('Excluir "' + f.n + '" do servidor? Esta ação não pode ser desfeita.')) return;
    setBusyOp('delete');
    try {
      await window.mpApi.deleteMedia(f.object_key);
      setSel(null);
      await _reload();
    } catch (e) { alert('Erro ao excluir: ' + e.message); }
    finally { setBusyOp(''); }
  }
  const FILE_OPS_REAL = [
    { op: 'download', icon: 'download', label: 'Baixar', fn: doDownload },
    { op: 'rename', icon: 'pen', label: 'Renomear', fn: doRename },
    { op: 'copy', icon: 'copy', label: 'Copiar key', fn: doCopy },
    { op: 'delete', icon: 'trash', label: 'Excluir', danger: true, fn: doDelete },
  ];

  // DETAIL VIEW — o que fazer com este vídeo
  if (sel) {
    return <div className="app" style={{ padding: 0 }}>
      <div className="file-detail-bar">
        <button className="btn sm ghost" onClick={() => setSel(null)}><Icon name="arrowL" />Arquivos</button>
        <b style={{ fontFamily: 'var(--fm)', fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 380 }}>{sel.n}</b>
        <Pill kind={sel.tone} dot>{sel.s}</Pill>
      </div>
      <div className="file-detail">
        <div className="stack">
          <RealPlayer objectKey={sel.object_key} />
          <div className="kv">
            <div className="row"><span className="k">Arquivo</span><span className="v mono" style={{ fontSize: 11, wordBreak: 'break-all' }}>{sel.n}</span></div>
            <div className="row"><span className="k">Formato</span><span className="v">{_techFor(sel)}</span></div>
            <div className="row"><span className="k">Tamanho</span><span className="v mono">{sel.size}</span></div>
            <div className="row"><span className="k">Criado</span><span className="v">{sel.date}</span></div>
            <div className="row"><span className="k">Status</span><span className="v" style={{ textTransform: 'capitalize' }}>{sel.s}</span></div>
          </div>
          <div className="rowx">{FILE_OPS_REAL.map(o => <button key={o.op} className={'btn sm' + (o.danger ? ' ghost' : '')} disabled={busyOp === o.op}
            style={o.danger ? { color: 'var(--pri)', borderColor: 'var(--pri-line)' } : {}}
            onClick={() => o.fn(sel)}><Icon name={o.icon} />{busyOp === o.op ? '…' : o.label}</button>)}</div>
        </div>
        <div className="stack">
          <div className="sec">O que deseja fazer com este vídeo?</div>
          <FileActionGrid file={sel} onOpen={openApp} />
        </div>
      </div>
    </div>;
  }

  return <div className="app" onClick={() => setCtx(null)}>
    <AppHead icon="media" title="Arquivos" desc="Clique em um vídeo para ver tudo que você pode fazer com ele. Botão direito = menu rápido."
      right={<div className="rowx">
        <input className="inp" style={{ height: 38, width: 180, fontSize: 12.5 }} placeholder="Buscar mídia…" value={search} onChange={e => setSearch(e.target.value)} />
        <button className="btn sm ghost" onClick={_reload} title="Recarregar"><Icon name="refresh" /></button>
        <div className="rowx" style={{ gap: 4, border: '1px solid var(--line2)', borderRadius: 10, padding: 3 }}>
          {[['icons', 'grid'], ['list', 'list']].map(([k, ic]) => <button key={k} className={'btn sm ghost' + (view === k ? ' pri' : '')} style={{ padding: 7 }} onClick={() => setView(k)}><Icon name={ic} /></button>)}
        </div>
      </div>} />
    <div className="tabbar">
      {FILTERS.map(([k, l]) => <button key={k} className={'tabx' + (filter === k ? ' on' : '')} onClick={() => setFilter(k)}>{l}</button>)}
      <span className="hint" style={{ marginLeft: 'auto', alignSelf: 'center', fontSize: 11.5 }}>{loading ? 'carregando…' : items.length + ' arquivo(s)'}</span>
    </div>

    {loading && !allItems.length && <div className="hint" style={{ textAlign: 'center', padding: 50 }}>Carregando biblioteca…</div>}

    {view === 'icons' ? <div className="thumbs" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(220px,1fr))', gap: 14 }}>
      {items.map(m => <div key={m.object_key} className="file-card" onClick={() => setSel(m)}
        onContextMenu={e => { e.preventDefault(); e.stopPropagation(); setCtx({ x: e.clientX, y: e.clientY, file: m }); }}>
        <div className="media" style={{ aspectRatio: '16/9', position: 'relative' }}>
          <RealThumb objectKey={m.object_key} alt={m.n} />
          <span className="pill" style={{ position: 'absolute', top: 8, left: 8, fontSize: 10, padding: '3px 9px', zIndex: 2 }}>{m.s}</span>
          {_durFor(m) && <span className="dur" style={{ zIndex: 2 }}>{_durFor(m)}</span>}
          <span className="file-hover"><span className="fh-btn"><Icon name="bolt" />Ver ações</span></span>
        </div>
        <div style={{ padding: '10px 4px 4px' }}>
          <b style={{ fontSize: 12.5, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.n}</b>
          <div className="rowx" style={{ justifyContent: 'space-between', marginTop: 5 }}>
            <span style={{ fontSize: 10.5, color: 'var(--muted)' }}>{_techFor(m)} · {m.size}</span>
            <Pill kind={m.tone} dot>{m.s}</Pill>
          </div>
        </div>
      </div>)}
    </div> : <div className="stack">
      {items.map(m => <div key={m.object_key} className="litem" style={{ cursor: 'pointer' }} onClick={() => setSel(m)}
        onContextMenu={e => { e.preventDefault(); e.stopPropagation(); setCtx({ x: e.clientX, y: e.clientY, file: m }); }}>
        <div style={{ width: 72, height: 41, borderRadius: 8, overflow: 'hidden', border: '1px solid var(--line)', flex: 'none', position: 'relative', background: 'linear-gradient(135deg,#16161f,#0c0c14)' }}>
          <RealThumb objectKey={m.object_key} alt="" />
        </div>
        <div className="li-main"><b style={{ fontSize: 12.5 }}>{m.n}</b><small>{_techFor(m)} · {m.size} · {m.date}</small></div>
        <Pill kind={m.tone} dot>{m.s}</Pill>
        <button className="btn sm pri" onClick={e => { e.stopPropagation(); setSel(m); }}><Icon name="bolt" />Ações</button>
      </div>)}
    </div>}

    {ctx && <div className="ctxmenu" style={{ left: Math.min(ctx.x, window.innerWidth - 230), top: Math.min(ctx.y, window.innerHeight - 380) }} onClick={e => e.stopPropagation()}>
      <div className="ctx-head">{ctx.file.n}</div>
      <button className="ctx-item strong" onClick={() => { setSel(ctx.file); setCtx(null); }}><Icon name="eye" />Abrir / ver ações</button>
      <div className="ctx-sep" />
      {FILE_ACTIONS.slice(0, 6).map(a => <button key={a.app} className="ctx-item" onClick={() => openApp(a.app, ctx.file)}><Icon name={a.icon} />{a.label}</button>)}
      <div className="ctx-sep" />
      <button className="ctx-item" onClick={() => { doDownload(ctx.file); setCtx(null); }}><Icon name="download" />Baixar</button>
      <button className="ctx-item" onClick={() => { doRename(ctx.file); setCtx(null); }}><Icon name="pen" />Renomear</button>
      <button className="ctx-item" onClick={() => { doCopy(ctx.file); setCtx(null); }}><Icon name="copy" />Copiar key</button>
      <button className="ctx-item danger" onClick={() => { doDelete(ctx.file); setCtx(null); }}><Icon name="trash" />Excluir</button>
    </div>}
  </div>;
}

Object.assign(window, { AppHead, RealThumb, RealPlayer, frameSrc, ProcessModal, AnalyzeApp, CompareApp, RunsApp, MediaApp });
