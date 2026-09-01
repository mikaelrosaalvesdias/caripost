/* Caripost OS — Inteligência & Mídia: Analyze, Compare, Runs, Arquivos */

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
  if (url) return <img loading="lazy" decoding="async" src={url} alt={alt || ''} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', ...style }} />;
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

/* Converte frame (base64 puro, data-uri, url ou objeto) em src de <img> válido.
   ATENÇÃO: base64 de JPEG começa com "/9j/" e de PNG com "iVBOR" — NÃO confundir
   com caminho de URL que começa com "/". Só caminhos /api ou /local são URLs. */
function frameSrc(f) {
  if (!f) return '';
  let s = typeof f === 'string' ? f : (f.b64 || f.url || f.image || f.src || '');
  if (!s) return '';
  if (s.startsWith('data:') || s.startsWith('http')) return s;
  if (s.startsWith('/api') || s.startsWith('/local') || s.startsWith('/uploads')) return s;
  return 'data:image/jpeg;base64,' + s;
}


/* ── ANALYZE — referências, Vision e JSON ── */
const SOCIAL_PLATFORMS = [
  ['youtube', 'YouTube'], ['instagram', 'Instagram'], ['tiktok', 'TikTok'], ['facebook', 'Facebook'],
  ['kwai', 'Kwai'], ['x', 'X/Twitter'], ['pinterest', 'Pinterest'], ['linkedin', 'LinkedIn'],
];

function AnalyzeApp() {
  const [tab, setTab] = React.useState('prompt');
  const [busy, setBusy] = React.useState(false);
  const [busyLabel, setBusyLabel] = React.useState('');
  const [analyzeModal, setAnalyzeModal] = React.useState({ open: false, pct: 0, detail: '', fileName: '', phase: 'running' });
  const [uploadPct, setUploadPct] = React.useState(0);
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [result, setResult] = React.useState(null);
  const [srt, setSrt] = React.useState('');
  const [frames, setFrames] = React.useState([]);
  const [picking, setPicking] = React.useState(false);
  const fileInputRef = React.useRef(null);
  const [creators, setCreators] = React.useState([]);
  const [creatorId, setCreatorId] = React.useState('');
  const [creatorRefs, setCreatorRefs] = React.useState(null); // null=desconhecido, []=sem refs
  const [refDraft, setRefDraft] = React.useState('');
  const [savingRefs, setSavingRefs] = React.useState(false);
  const [platforms, setPlatforms] = React.useState(['youtube', 'instagram']);

  React.useEffect(() => {
    if (window.mpApi) window.mpApi.listCreators().then(setCreators).catch(() => {});
  }, []);

  React.useEffect(() => {
    if (!creatorId || !window.mpApi) { setCreatorRefs(null); return; }
    window.mpApi.getCreator(creatorId)
      .then(c => setCreatorRefs(c.reference_channels || []))
      .catch(() => setCreatorRefs([]));
  }, [creatorId]);

  function togglePlatform(p) {
    setPlatforms(ps => ps.includes(p) ? ps.filter(x => x !== p) : [...ps, p]);
  }

  async function saveRefs() {
    const links = refDraft.split('\n').map(s => s.trim()).filter(Boolean);
    if (!links.length || !creatorId) return;
    setSavingRefs(true);
    try {
      await window.mpApi.updateCreator(creatorId, { reference_channels: links });
      setCreatorRefs(links); setRefDraft('');
    } catch (e) { mpAlert('Erro ao salvar referências: ' + e.message); }
    finally { setSavingRefs(false); }
  }

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
      mpAlert('Upload falhou: ' + e.message);
    }
  }

  async function doAnalyze() {
    if (!file?.object_key) { mpAlert('Selecione ou envie um vídeo primeiro.'); return; }
    if (!creatorId) { mpAlert('Escolha a empresa/criador primeiro.'); return; }
    const payload = {
      video_object_key: file.object_key,
      original_filename: file.n || '',
      creator_id: creatorId,
      platforms,
      stt_provider: 'none',
      limit: 20,
    };
    setBusy(true);
    setBusyLabel('Preparando análise...');
    setAnalyzeModal({ open: true, pct: 3, detail: 'Preparando análise...', fileName: file.n || file.object_key, phase: 'running' });
    try {
      const r = await runAnalyzeJob(payload);
      setResult(r);
      if (r.run_id) {
        window.mpApi.getRunFrames(r.run_id).then(f => setFrames(f || [])).catch(() => {});
      }
      setAnalyzeModal(m => ({ ...m, open: true, pct: 100, detail: 'Análise concluída.', phase: 'done' }));
      await new Promise(resolve => setTimeout(resolve, 650));
    } catch (e) {
      setAnalyzeModal(m => ({ ...m, open: true, detail: 'Erro: ' + e.message, phase: 'error' }));
      await new Promise(resolve => setTimeout(resolve, 1600));
      mpAlert('Análise falhou: ' + e.message);
    } finally {
      setBusy(false);
      setAnalyzeModal(m => ({ ...m, open: false }));
    }
  }

  async function runAnalyzeJob(payload) {
    if (!window.mpApi.analyzeStart || !window.mpApi.analyzeStatus) {
      setAnalyzeModal(m => ({ ...m, pct: 70, detail: 'Analisando referência, JSON e Vision...' }));
      return window.mpApi.analyze(payload);
    }
    const start = await window.mpApi.analyzeStart(payload);
    if (!start?.job_id) throw new Error(start?.error || 'Não foi possível iniciar análise.');
    return new Promise((resolve, reject) => {
      let stopped = false;
      let pollTimer = null;
      let transientErrors = 0;
      const finish = (fn, value) => {
        if (stopped) return;
        stopped = true;
        if (pollTimer) clearTimeout(pollTimer);
        fn(value);
      };
      const poll = async () => {
        try {
          const job = await window.mpApi.analyzeStatus(start.job_id);
          transientErrors = 0;
          const pct = Math.max(0, Math.min(100, Math.round(Number(job.progress_pct) || 0)));
          const detail = job.detail || 'Analisando referência, JSON e Vision...';
          setBusyLabel(detail);
          setAnalyzeModal(m => ({ ...m, pct, detail, phase: job.status === 'error' ? 'error' : 'running' }));
          if (job.status === 'done') {
            finish(resolve, job.result || {});
            return;
          }
          if (job.status === 'error') {
            finish(reject, new Error(job.detail || job.error || 'Análise falhou'));
            return;
          }
        } catch (err) {
          transientErrors += 1;
          if (transientErrors >= 6) {
            finish(reject, err);
            return;
          }
          setAnalyzeModal(m => ({ ...m, detail: 'Reconectando ao status da análise...' }));
        }
        pollTimer = setTimeout(poll, 2000);
      };
      poll();
    });
  }

  const sug = result?.suggested || {};
  const grok = result?.grok || {};
  const vision = result?.vision || {};
  const promptText = grok.markdown_prompt_ptbr_keep_original || grok.prompt || grok.title_prompt || sug.description_template ||
    (result ? JSON.stringify(sug, null, 2) : '');

  return <div className="app">
    <AnalyzeLoadingModal open={analyzeModal.open} pct={analyzeModal.pct} detail={analyzeModal.detail} fileName={analyzeModal.fileName} phase={analyzeModal.phase} />
    <AppHead icon="analyze" title="Analyze" desc="Referências, Vision IA e JSON do vídeo — sem transcrição nesta etapa."
      right={<Pill kind="good" dot>storage online</Pill>} />
    <div className="split">
      {/* ENTRADA */}
      <div className="stack">
        <div className="panel stack">
          <div className="rowx" style={{ justifyContent: 'space-between' }}>
            <div className="sec"><Icon name="upload" />Vídeo (upload ou do servidor)</div>
            <button className="btn sm" onClick={() => setPicking(p => !p)}><Icon name="media" />Escolher do servidor</button>
          </div>
          {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); window.mpCtx.file = f; setPicking(false); }} />}
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

        <div className="panel stack">
          <Field label="Empresa / criador">
            <select className="inp" value={creatorId} onChange={e => setCreatorId(e.target.value)}>
              <option value="">— selecione —</option>
              {creators.map(c => <option key={c.creator_id} value={c.creator_id}>{c.n}</option>)}
            </select>
          </Field>
          <div>
            <label className="lbl">Plataformas-alvo</label>
            <div className="rowx" style={{ flexWrap: 'wrap' }}>
              {SOCIAL_PLATFORMS.map(([k, l]) => <button key={k} className={'btn sm' + (platforms.includes(k) ? ' pri' : '')} onClick={() => togglePlatform(k)}>{l}</button>)}
            </div>
          </div>
          {creatorId && Array.isArray(creatorRefs) && creatorRefs.length > 0 &&
            <div className="hint">Usando {creatorRefs.length} referência(s) cadastrada(s) deste criador como contexto.</div>}
          {creatorId && Array.isArray(creatorRefs) && creatorRefs.length === 0 && <div className="stack">
            <div className="hint" style={{ color: 'var(--pri)' }}>Este criador não tem referências cadastradas. Cole os links (1 por linha):</div>
            <textarea className="inp" rows="3" value={refDraft} onChange={e => setRefDraft(e.target.value)}
              placeholder={'https://youtube.com/@canal\nhttps://instagram.com/perfil'} />
            <button className="btn sm pri" disabled={savingRefs || !refDraft.trim()} onClick={saveRefs}><Icon name="check" />{savingRefs ? 'Salvando…' : 'Salvar referências'}</button>
          </div>}
        </div>

        <div className="rowx" data-tour="an-go">
          <button className="btn pri" disabled={busy} onClick={doAnalyze}><Icon name="sparkles" />{busy ? 'Analisando…' : 'Analisar'}</button>
          <button className="btn ghost" onClick={() => { setFile(null); setResult(null); setSrt(''); setFrames([]); window.mpCtx.file = null; }}>Limpar</button>
        </div>
        {busy && <div className="panel"><ProgressBar pct={70} tone="cy" label={busyLabel} eta="referência + Vision em andamento" /></div>}
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
          {[['prompt', 'Referência'], ['vision', 'Vision'], ['json', 'JSON']].map(([k, l]) =>
            <button key={k} className={'tabx' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}
        </div>
        {tab === 'prompt' && <div className="panel stack" style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.6, maxHeight: 420, overflow: 'auto' }}>
          {!result && <span className="hint">Analise um vídeo para ver o resultado aqui.</span>}
          {result && (() => {
            const g = grok.generated || {};
            const titles = g.titles || (grok.title ? [grok.title] : []);
            const hashtags = g.hashtags || [];
            const desc = g.description || grok.description;
            return <React.Fragment>
              {titles.length > 0 && <div><b style={{ color: 'var(--cyan)' }}>Títulos</b>{titles.map((t, i) => <div key={i} className="row"><span className="k">{String.fromCharCode(65 + i)}</span><span className="v" style={{ textAlign: 'left' }}>{t}</span></div>)}</div>}
              {desc && <div><b style={{ color: 'var(--cyan)' }}>Descrição</b><div style={{ whiteSpace: 'pre-wrap' }}>{desc}</div></div>}
              {hashtags.length > 0 && <div><b style={{ color: 'var(--cyan)' }}>Hashtags</b><div>{hashtags.map(h => String(h).startsWith('#') ? h : '#' + h).join(' ')}</div></div>}
              {g.thumbnail_concept && <div><b style={{ color: 'var(--cyan)' }}>Thumbnail</b><div>{g.thumbnail_concept}</div></div>}
              {g.recommendations && <div><b style={{ color: 'var(--cyan)' }}>Recomendações</b><div style={{ whiteSpace: 'pre-wrap' }}>{g.recommendations}</div></div>}
              {sug.tags?.length > 0 && <div><b style={{ color: 'var(--cyan)' }}>Tags</b><div>{sug.tags.join(', ')}</div></div>}
              {titles.length === 0 && !desc && <span className="hint">Sem geração de texto (configure um token de IA em Settings). Prompt disponível em "Copiar prompt".</span>}
            </React.Fragment>;
          })()}
        </div>}
        {tab === 'vision' && <div className="stack">
          {frames.length > 0 && <div className="thumbs">{frames.slice(0, 6).map((f, i) =>
            <div key={i} className="thumb"><img loading="lazy" decoding="async" src={frameSrc(f)} alt={'frame ' + i} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} /></div>)}
          </div>}
          <div className="panel" style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.6, maxHeight: 300, overflow: 'auto' }}>
            <b style={{ color: 'var(--cyan)' }}>Visão IA:</b> {(vision.analysis && typeof vision.analysis === 'object' ? vision.analysis.description : vision.analysis) || 'Sem análise de visão disponível.'}
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
      mpAlert('Compare falhou: ' + e.message);
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
              <div key={i} className="thumb"><img loading="lazy" decoding="async" src={frameSrc(f)} alt={'frame'} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} /></div>)}
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
              if (!txt) { mpAlert('SRT indisponível para este run.'); return; }
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
              catch (e) { mpAlert('Erro: ' + e.message); }
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
  { app: 'teaser', icon: 'scissors', label: 'Teaser', desc: 'Resumo curto pra divulgação', tone: 'cy' },
  { app: 'cortes', icon: 'cortes', label: 'Cortes', desc: 'Vertical p/ Shorts/Reels', tone: 'cy' },
  { app: 'thumbnail', icon: 'thumbnail', label: 'Thumbnail', desc: 'Capa por IA', tone: 'violet' },
  { app: 'enhancer', icon: 'enhance', label: 'Melhorar', desc: 'Upscale de qualidade', tone: 'cy' },
  { app: 'criacao', icon: 'post', label: 'Criar Post', desc: 'Montar publicação', tone: 'pri' },
  { app: 'publisher', icon: 'broadcast', label: 'Publicar', desc: 'Enviar às plataformas', tone: 'pri' },
  { app: 'telegram', icon: 'telegram', label: 'Telegram', desc: 'Disparar ao grupo', tone: 'cy' },
];
const FILTERS = [['all', 'Todos'], ['original', 'Originais'], ['burn', 'Queimados'], ['teaser', 'Teasers'], ['cortes', 'Cortes'], ['autoeditor', 'AutoEditor']];

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
  const [dateFilter, setDateFilter] = React.useState('all'); // all | today | 7d | 30d
  const [sortBy, setSortBy] = React.useState('recent');       // recent | old | name | size
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
      const keys = items.map(i => i.object_key);
      window.mpApi.metaBatch(keys).then(m => setMetaMap(m)).catch(() => {});
    } catch (_) {} finally { setLoading(false); }
  }

  const now = Date.now();
  const DAY = 86400000;
  function _inDateRange(m) {
    if (dateFilter === 'all') return true;
    const t = m.ts ? new Date(m.ts).getTime() : 0;
    if (!t) return false;
    if (dateFilter === 'today') { const d = new Date(); d.setHours(0,0,0,0); return t >= d.getTime(); }
    if (dateFilter === '7d') return now - t <= 7 * DAY;
    if (dateFilter === '30d') return now - t <= 30 * DAY;
    return true;
  }
  const items = allItems
    .filter(m => filter === 'all' || m.s === filter || (filter === 'original' && m.s === '4K original'))
    .filter(m => !search || m.n.toLowerCase().includes(search.toLowerCase()) || (m.object_key || '').toLowerCase().includes(search.toLowerCase()))
    .filter(_inDateRange)
    .sort((a, b) => {
      if (sortBy === 'name') return a.n.localeCompare(b.n);
      if (sortBy === 'size') return (b.size_bytes || 0) - (a.size_bytes || 0);
      const ta = a.ts ? new Date(a.ts).getTime() : 0, tb = b.ts ? new Date(b.ts).getTime() : 0;
      return sortBy === 'old' ? ta - tb : tb - ta;
    });
  const DATE_FILTERS = [['all', 'Qualquer data'], ['today', 'Hoje'], ['7d', '7 dias'], ['30d', '30 dias']];
  const SORTS = [['recent', 'Mais recentes'], ['old', 'Mais antigos'], ['name', 'Nome (A-Z)'], ['size', 'Maiores']];

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
    } catch (e) { mpAlert('Erro no download: ' + e.message); }
    finally { setBusyOp(''); }
  }
  async function doRename(f) {
    const newName = await mpPrompt('Novo nome do arquivo:', f.n);
    if (!newName || newName === f.n) return;
    setBusyOp('rename');
    try {
      await window.mpApi.renameMedia(f.object_key, newName);
      await _reload();
      setSel(null);
    } catch (e) { mpAlert('Erro ao renomear: ' + e.message); }
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
    } catch (e) { mpAlert('Erro ao excluir: ' + e.message); }
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
    <div className="rowx" style={{ gap: 8, flexWrap: 'wrap' }}>
      <div className="rowx" style={{ gap: 4 }}>
        <span className="lbl" style={{ alignSelf: 'center', margin: 0 }}>Data:</span>
        {DATE_FILTERS.map(([k, l]) => <button key={k} className={'btn sm' + (dateFilter === k ? ' pri' : ' ghost')} onClick={() => setDateFilter(k)}>{l}</button>)}
      </div>
      <div className="rowx" style={{ gap: 6, marginLeft: 'auto' }}>
        <span className="lbl" style={{ alignSelf: 'center', margin: 0 }}>Ordenar:</span>
        <select className="inp" style={{ height: 34, fontSize: 12.5, width: 160 }} value={sortBy} onChange={e => setSortBy(e.target.value)}>
          {SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>
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
          <div style={{ fontSize: 10, color: 'var(--faint)', marginTop: 3 }}><Icon name="clock" style={{ width: 10, height: 10, verticalAlign: '-1px' }} /> {m.date}</div>
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

Object.assign(window, { AppHead, RealThumb, RealPlayer, frameSrc, AnalyzeApp, CompareApp, RunsApp, MediaApp });
