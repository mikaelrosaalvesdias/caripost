/* Caripost OS — Estúdio: AutoEditor, Video Enhancer, Criação, Referência */

/* collapsible card section */
function Acc({ title, open, children }) {
  const [o, setO] = React.useState(open);
  return <div className="acc">
    <button className="acc-h" onClick={() => setO(!o)}><Icon name="chevR" style={{ transform: o ? 'rotate(90deg)' : 'none', width: 13, height: 13 }} />{title}</button>
    {o && <div className="acc-b">{children}</div>}
  </div>;
}

/* ── AUTOEDITOR — cortes automáticos com IA ── */
function AutoEditorApp() {
  const [trans, setTrans] = React.useState('smart');
  const [running, setRunning] = React.useState(false);
  const [audioNorm, setAudioNorm] = React.useState(true);
  const [audioDen, setAudioDen] = React.useState(true);
  const [maxScenes, setMaxScenes] = React.useState(60);
  const [scenes, setScenes] = React.useState([]);
  const [resultKey, setResultKey] = React.useState('');
  const [resultMeta, setResultMeta] = React.useState('');
  const [jobPct, setJobPct] = React.useState(0);
  const [jobLabel, setJobLabel] = React.useState('');
  const [selectedKeys, setSelectedKeys] = React.useState(() => {
    const ctx = window.mpCtx?.file;
    return ctx ? [ctx.object_key] : [];
  });
  const [showPicker, setShowPicker] = React.useState(false);
  const [recentJobs, setRecentJobs] = React.useState([]);
  const pollRef = React.useRef(null);

  function _fmt(sec) {
    if (sec == null) return '—';
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  }

  function _applyJob(j) {
    if (!j) return;
    if (j.selected_scenes?.length) {
      setScenes(j.selected_scenes.slice(0, 12).map((s, idx) => ({
        i: idx + 1, src: s.source_label || 'v0',
        t: _fmt(s.start != null ? s.start : s.source_start) + ' → ' + _fmt(s.end != null ? s.end : s.source_end),
        d: ((s.duration || 0).toFixed(1)) + 's',
        rel: parseFloat((s.score || s.vision_relevance || 0).toFixed(2)),
      })));
    }
    if (j.result_video_object_key) setResultKey(j.result_video_object_key);
    const out = j.output_probe || {};
    if (out.duration_seconds) setResultMeta(`${(j.selected_scenes || []).length} cenas · ${out.width || '?'}x${out.height || '?'} · ${_fmt(out.duration_seconds)}`);
  }

  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.listAeJobs(8).then(jobs => {
      setRecentJobs(jobs || []);
      const running0 = (jobs || []).find(j => j.status === 'running' || j.status === 'pending');
      if (running0) { setRunning(true); _poll(running0.job_id); return; }
      const done = (jobs || []).find(j => j.status === 'done');
      if (done) _applyJob(done);
    }).catch(() => {});
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  function _poll(jobId) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const r = await window.mpApi.aeStatus(jobId);
        setJobPct(r.progress_pct || 0);
        setJobLabel(r.detail || 'Processando…');
        if (r.status === 'done') {
          clearInterval(pollRef.current); setRunning(false); _applyJob(r);
          window.mpApi.listAeJobs(8).then(setRecentJobs).catch(() => {});
        } else if (r.status === 'error') {
          clearInterval(pollRef.current); setRunning(false);
          setJobLabel('✗ ' + (r.detail || 'Erro'));
        }
      } catch (_) {}
    }, 4000);
  }

  function start() {
    if (!selectedKeys.length) { mpAlert('Selecione ao menos um vídeo fonte.'); return; }
    setRunning(true); setJobPct(5); setJobLabel('Iniciando…');
    window.mpApi.startAutoEditor({
      video_object_key: selectedKeys[0],
      video_object_keys: selectedKeys,
      max_scenes: maxScenes,
      transition_mode: trans,
      audio_normalize: audioNorm,
      audio_denoise: audioDen,
    }).then(r => { if (r.job_id) _poll(r.job_id); else { setRunning(false); mpAlert(r.error || 'Falha ao iniciar'); } })
      .catch(e => { setRunning(false); mpAlert('Erro: ' + e.message); });
  }

  return <div className="app">
    <AppHead icon="autoeditor" title="AutoEditor" desc="Multi-fonte → Grok Vision detecta as melhores cenas, corta, aplica transições e monta o vídeo final."
      right={<Pill kind="violet" icon="sparkles">Grok Vision</Pill>} />
    <div className="split">
      {/* CONFIG */}
      <div className="stack">
        <div className="sec">Configuração</div>
        <Acc title="Vídeo Fonte" open>
          <div className="rowx"><button className="btn sm" onClick={() => setShowPicker(p => !p)}><Icon name="media" />Selecionar do servidor</button></div>
          {showPicker && <div style={{ marginTop: 8 }}>
            <FilePicker onClose={() => setShowPicker(false)} onSelect={f => {
              setSelectedKeys(p => p.includes(f.object_key) ? p : [...p, f.object_key]);
            }} />
          </div>}
          {selectedKeys.length > 0 && <div className="stack" style={{ marginTop: 10, gap: 6 }}>
            {selectedKeys.map((k, i) => <div key={k} className="litem" style={{ padding: '9px 12px' }}>
              <span className="chip" style={{ fontFamily: 'var(--fm)', fontSize: 11 }}>v{i}</span>
              <div className="li-main"><b style={{ fontSize: 12 }}>{k.split('/').pop()}</b></div>
              <button className="btn sm ghost" style={{ color: 'var(--pri)' }} onClick={() => setSelectedKeys(p => p.filter(x => x !== k))}><Icon name="x" /></button>
            </div>)}
          </div>}
          <div className="hint" style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>fontes: <b style={{ color: 'var(--text2)' }}>{selectedKeys.length} vídeo(s)</b></div>
        </Acc>
        <Acc title="Quantidade de Cenas" open>
          <Field label="Máx. cenas no corte"><input className="inp" type="number" value={maxScenes} onChange={e => setMaxScenes(+e.target.value || 60)} /></Field>
          <div className="hint" style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>A IA seleciona automaticamente as melhores cenas por qualidade.</div>
        </Acc>
        <Acc title="Transições" open>
          <Field label="Modo">
            <select className="inp" value={trans} onChange={e => setTrans(e.target.value)}>
              <option value="smart">Smart (detecta ponto natural)</option>
              <option value="always_crossfade">Sempre crossfade</option>
              <option value="none">Corte seco (sem transição)</option>
            </select>
          </Field>
        </Acc>
        <Acc title="Áudio">
          <div className="rowx">
            <button className={'btn sm' + (audioNorm ? ' pri' : ' ghost')} onClick={() => setAudioNorm(!audioNorm)}>Normalizar volume</button>
            <button className={'btn sm' + (audioDen ? ' pri' : ' ghost')} onClick={() => setAudioDen(!audioDen)}>Remover ruído</button>
          </div>
        </Acc>
        <div className="rowx" data-tour="ae-start">
          <button className="btn pri" disabled={running} onClick={start}><Icon name="autoeditor" />{running ? 'Processando…' : 'Iniciar AutoEditor'}</button>
          <button className="btn ghost" onClick={() => window.mpApi.listAeJobs(8).then(j => { setRecentJobs(j); const d = j.find(x => x.status === 'done'); if (d) _applyJob(d); }).catch(() => {})}><Icon name="refresh" />Atualizar jobs</button>
        </div>
        {running && <div className="panel"><ProgressBar pct={jobPct} tone="violet" label={jobLabel} /></div>}
      </div>

      {/* RESULTADO */}
      <div className="stack">
        <div className="sec">Resultado</div>
        {resultKey ? <RealPlayer objectKey={resultKey} /> : <div className="vstage" style={{ aspectRatio: '16/9' }}><div className="ph" /><div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--muted)', fontSize: 13 }}>Nenhum resultado ainda</div></div>}
        {resultMeta && <div className="hint" style={{ fontSize: 12.5, color: 'var(--text2)' }}>{resultMeta}</div>}
        <div className="rowx">
          <button className="btn pri" disabled={!resultKey} onClick={async () => { const u = await window.mpApi.downloadUrl(resultKey, 'autoeditor_final'); if (u) window.open(u, '_blank'); }}><Icon name="download" />Download</button>
          <button className="btn" disabled={!resultKey} onClick={() => navigator.clipboard.writeText(resultKey)}><Icon name="copy" />Copiar key</button>
          <button className="btn" data-tour="ae-recut" disabled={!resultKey} onClick={() => { window.mpCtx.file = { object_key: resultKey, n: resultKey.split('/').pop(), s: 'autoeditor' }; window.__mpOpen && window.__mpOpen('criacao'); }}><Icon name="post" />Criar Post</button>
        </div>
        {scenes.length > 0 && <>
          <div className="sec mut" style={{ marginTop: 4 }}>Cenas selecionadas</div>
          <div className="stack" style={{ gap: 6, maxHeight: 240, overflowY: 'auto' }}>
            {scenes.map(s => <div key={s.i} className="litem" style={{ padding: '10px 12px' }}>
              <span className="chip" style={{ fontFamily: 'var(--fm)', fontSize: 11 }}>#{s.i} · {s.src}</span>
              <div className="li-main"><b style={{ fontSize: 12.5, fontFamily: 'var(--fm)' }}>{s.t}</b><small>{s.d}</small></div>
              <Pill kind="violet" dot>rel {s.rel}</Pill>
            </div>)}
          </div>
        </>}
        {recentJobs.length > 0 && <>
          <div className="sec mut" style={{ marginTop: 4 }}>Jobs recentes</div>
          <div className="stack" style={{ gap: 4, maxHeight: 160, overflowY: 'auto' }}>
            {recentJobs.slice(0, 6).map(j => <div key={j.job_id} className="litem" style={{ padding: '7px 11px', cursor: 'pointer' }} onClick={() => _applyJob(j)}>
              <div className="li-main"><b style={{ fontSize: 11.5, fontFamily: 'var(--fm)' }}>{(j.job_id || '').slice(0, 8)}</b><small>{j.detail ? j.detail.slice(0, 50) : j.status}</small></div>
              <Pill kind={j.status === 'done' ? 'good' : j.status === 'error' ? 'pri' : 'cy'} dot>{j.status}</Pill>
            </div>)}
          </div>
        </>}
      </div>
    </div>
  </div>;
}

/* ── VIDEO ENHANCER — upscale com IA ── */
function EnhancerApp() {
  const [file, setFile] = React.useState(window.mpCtx?.file || null);
  const [picking, setPicking] = React.useState(false);
  const [resolution, setResolution] = React.useState('720p');
  const [phase, setPhase] = React.useState('idle');
  const [pct, setPct] = React.useState(0);
  const [statusMsg, setStatusMsg] = React.useState('');
  const [resultKey, setResultKey] = React.useState('');
  const pollRef = React.useRef(null);

  React.useEffect(() => { return () => { if (pollRef.current) clearInterval(pollRef.current); }; }, []);

  async function start() {
    if (!file) { mpAlert('Selecione um vídeo primeiro.'); return; }
    setPhase('running'); setPct(5); setStatusMsg('Iniciando…');
    try {
      const r = await window.mpApi.enhancerStart({
        video_object_key: file.object_key,
        object_key: file.object_key,
        resolution,
      });
      if (!r.job_id) throw new Error(r.error || r.detail || 'sem job_id');
      pollRef.current = setInterval(async () => {
        try {
          const st = await window.mpApi.enhancerStatus(r.job_id);
          setPct(st.progress_pct || 50); setStatusMsg(st.detail || 'Processando frames…');
          if (st.status === 'done') {
            clearInterval(pollRef.current); setPhase('done'); setPct(100);
            setResultKey(st.output_object_key || st.result_object_key || '');
          } else if (st.status === 'error') {
            clearInterval(pollRef.current); setPhase('error'); setStatusMsg(st.detail || 'Erro');
          }
        } catch (_) {}
      }, 4000);
    } catch (e) { setPhase('error'); setStatusMsg(e.message); }
  }

  return <div className="app">
    <AppHead icon="enhance" title="Video Enhancer" desc="Upscale de qualidade com IA (Video2X · RealESRGAN). Melhora vídeos antigos ou de baixa resolução."
      right={<Pill kind="cy" icon="sparkles">RealESRGAN</Pill>} />
    <CtxFileBar file={file} onPick={() => setPicking(p => !p)} />
    {picking && <FilePicker onClose={() => setPicking(false)} onSelect={f => { setFile(f); window.mpCtx.file = f; setPicking(false); setPhase('idle'); }} />}
    <div className="split">
      <div className="stack">
        <div className="sec cy">Melhoria de Qualidade</div>
        <Acc title="Resolução de Saída" open>
          <div className="checks">
            <Check on={resolution === '720p'} onClick={() => setResolution('720p')}>720p — escala 2× (~2GB VRAM)</Check>
            <Check on={resolution === '1080p'} onClick={() => setResolution('1080p')}>1080p — escala 4× (~4GB VRAM)</Check>
          </div>
        </Acc>
        {phase === 'running' && <div className="panel stack">
          <ProgressBar pct={pct} tone="cy" label={statusMsg} />
        </div>}
        {phase === 'error' && <div className="panel" style={{ borderColor: 'var(--pri-line)' }}><span style={{ color: 'var(--pri)', fontSize: 13 }}>✗ {statusMsg}</span></div>}
        {phase === 'done' && <div className="panel stack" style={{ borderColor: 'rgba(0,230,118,.3)' }}>
          <div className="pill good" style={{ alignSelf: 'flex-start' }}><Icon name="check" />Vídeo melhorado</div>
          <button className="btn pri sm" onClick={async () => { const u = await window.mpApi.downloadUrl(resultKey, 'enhanced'); if (u) window.open(u, '_blank'); }}><Icon name="download" />Baixar</button>
        </div>}
        <button className="btn pri block" disabled={!file || phase === 'running'} onClick={start}><Icon name="enhance" />{phase === 'running' ? 'Melhorando…' : 'Melhorar Vídeo'}</button>
      </div>
      <div className="stack">
        <div className="sec mut">Vídeo de entrada</div>
        {file ? <RealPlayer objectKey={file.object_key} /> : <div className="vstage" style={{ aspectRatio: '16/9' }}><div className="ph" /></div>}
      </div>
    </div>
  </div>;
}

/* ── CRIAÇÃO — montagem de posts ── */
function CriacaoApp() {
  const [runs, setRuns] = React.useState([]);
  const [sel, setSel] = React.useState(null);
  const [detail, setDetail] = React.useState(null);
  const [frames, setFrames] = React.useState([]);
  const [frameSel, setFrameSel] = React.useState(0);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.listRuns(40).then(async r => {
      setRuns(r); setLoading(false);
      // Se veio do Arquivos com run, seleciona
      const ctx = window.mpCtx?.file;
      if (ctx?.run_id) {
        const found = r.find(x => x.id === ctx.run_id);
        if (found) { _select(found); return; }
      }
      if (ctx?.object_key) {
        const found = r.find(x => x.video_object_key === ctx.object_key);
        if (found) { _select(found); return; }
      }
      if (r.length) _select(r[0]);
    }).catch(() => setLoading(false));
  }, []);

  async function _select(run) {
    setSel(run); setDetail(null); setFrames([]); setFrameSel(0);
    try {
      const d = await window.mpApi.getRun(run.id);
      setDetail(d);
      window.mpApi.getRunFrames(run.id).then(f => setFrames(f || [])).catch(() => {});
    } catch (_) {}
  }

  const res = detail?.result || {};
  const sug = res.suggested || {};
  const grok = res.grok || {};
  const frameSrc = window.frameSrc;

  return <div className="app" style={{ padding: 0 }}>
    <div style={{ padding: '22px 22px 0' }}>
      <FlowHead icon="post" title="Criação de Posts"
        sub="Monta o post final: capa, título, descrição e tags — a partir de um run analisado."
        right={sel ? <Pill kind="cy" dot>{(sel.snip || sel.id || '').slice(0, 28)}</Pill> : null} />
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '250px 1fr', borderTop: '1px solid var(--line)', flex: 1, minHeight: 0 }}>
      <div style={{ borderRight: '1px solid var(--line)', padding: 14, display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto', maxHeight: 540 }}>
        <div className="sec mut" style={{ marginBottom: 2 }}>Runs</div>
        {loading && <SkeletonRows rows={4} />}
        {!loading && !runs.length && <EmptyState icon="layers" title="Nenhum run ainda">Analise um vídeo no app Analisar para ele aparecer aqui.</EmptyState>}
        {runs.map(r => <button key={r.id} className="panel" style={{ padding: 8, textAlign: 'left', borderColor: sel?.id === r.id ? 'var(--pri-line)' : undefined, cursor: 'pointer' }} onClick={() => _select(r)}>
          <div style={{ fontFamily: 'var(--fm)', fontSize: 10.5, color: 'var(--muted)' }}>{r.id.slice(0, 8)}</div>
          <div style={{ fontSize: 11.5, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.snip}</div>
        </button>)}
      </div>
      <div className="split" style={{ padding: 20, overflowY: 'auto', maxHeight: 540 }}>
        <div className="stack">
          <div className="sec cy">Prévia do post</div>
          <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ aspectRatio: '16/9', position: 'relative', background: '#000' }}>
              {frames[frameSel]
                ? <img loading="lazy" decoding="async" src={frameSrc(frames[frameSel])} alt="capa" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
                : sel?.video_object_key ? <RealThumb objectKey={sel.video_object_key} /> : null}
            </div>
            <div style={{ padding: 16 }}>
              <b style={{ fontFamily: 'var(--fh)', fontSize: 15 }}>{grok.title || sel?.snip || 'Sem título'}</b>
              <p style={{ fontSize: 12.5, color: 'var(--text2)', margin: '8px 0 12px', lineHeight: 1.5, maxHeight: 80, overflow: 'auto' }}>{grok.description || sug.description_template || 'Sem descrição gerada.'}</p>
              <div className="rowx" style={{ flexWrap: 'wrap' }}>{(sug.tags || []).slice(0, 8).map(t => <span key={t} className="chip tag">#{t}</span>)}</div>
            </div>
          </div>
        </div>
        <div className="stack">
          {frames.length > 0 && <Field label="Escolher capa"><div className="thumbs">{frames.slice(0, 8).map((f, i) =>
            <div key={i} className={'thumb' + (i === frameSel ? ' sel' : '')} onClick={() => setFrameSel(i)}>
              <img loading="lazy" decoding="async" src={frameSrc(f)} alt={'f' + i} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
            </div>)}</div></Field>}
          <Field label="Título"><input className="inp" defaultValue={grok.title || ''} key={sel?.id + '_t'} /></Field>
          <Field label="Descrição"><textarea className="inp" rows="3" defaultValue={grok.description || sug.description_template || ''} key={sel?.id + '_d'} /></Field>
          <div className="rowx" style={{ justifyContent: 'flex-end' }}>
            <button className="btn" disabled={!sel} onClick={() => { window.mpCtx.file = { object_key: sel.video_object_key, n: sel.snip, run_id: sel.id }; window.__mpOpen && window.__mpOpen('teaser'); }}><Icon name="scissors" />Gerar teaser</button>
            <button className="btn" disabled={!sel} onClick={() => { window.mpCtx.file = { object_key: sel.video_object_key, n: sel.snip, run_id: sel.id }; window.__mpOpen && window.__mpOpen('legenda'); }}><Icon name="captions" />Queimar legenda</button>
            <button className="btn pri" disabled={!sel} onClick={() => { window.mpCtx.file = { object_key: sel.video_object_key, n: sel.snip, run_id: sel.id }; window.__mpOpen && window.__mpOpen('publisher'); }}><Icon name="broadcast" />Publicar</button>
          </div>
        </div>
      </div>
    </div>
  </div>;
}

/* ── REFERÊNCIA — pesquisa XVideos ── */
function ReferenciaApp() {
  const [type, setType] = React.useState('search');
  const [query, setQuery] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [cards, setCards] = React.useState([]);
  const [err, setErr] = React.useState('');

  async function doSearch() {
    if (!query.trim()) return;
    setBusy(true); setErr('');
    try {
      const r = await window.mpApi.xvSearch(type, query.trim(), 24, 'views');
      const vids = r.videos || r.results || r.items || [];
      setCards(vids.map(v => ({
        t: v.title || '—',
        v: v.views || v.views_str || '—',
        d: v.duration || '—',
        url: v.url || v.link || '',
        thumb: v.thumb || v.thumbnail || v.image || '',
        tags: (v.tags || []).slice(0, 3).join(' · '),
      })));
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return <div className="app">
    <AppHead icon="refs" title="Referência XVideos" desc="Pesquisa e benchmarking — encontre conteúdos similares para calibrar título, tags e edição."
      right={<button className="btn pri sm" disabled={busy} onClick={doSearch}><Icon name="search" />{busy ? 'Buscando…' : 'Pesquisar'}</button>} />
    <div className="panel">
      <div className="grid3">
        <Field label="Tipo">
          <select className="inp" value={type} onChange={e => setType(e.target.value)}>
            <option value="search">Busca geral</option>
            <option value="pornstar">Atriz / Pornstar</option>
            <option value="channel">Canal / Studio</option>
          </select>
        </Field>
        <Field label="Busca"><input className="inp" placeholder="brasileira, Monica Matos…" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()} /></Field>
        <Field label="&nbsp;"><button className="btn pri block" disabled={busy} onClick={doSearch}><Icon name="search" />Buscar</button></Field>
      </div>
    </div>
    {err && <div className="panel" style={{ borderColor: 'var(--pri-line)' }}><span style={{ color: 'var(--pri)', fontSize: 13 }}>✗ {err}</span></div>}
    {busy && <div className="panel"><ProgressBar pct={60} tone="cy" label="Buscando referências…" /></div>}
    <div className="thumbs" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 14 }}>
      {cards.map((c, i) => <a key={i} className="panel" style={{ padding: 0, overflow: 'hidden', cursor: 'pointer', textDecoration: 'none', color: 'inherit' }} href={c.url || '#'} target="_blank" rel="noreferrer">
        <div style={{ aspectRatio: '16/9', position: 'relative', background: '#0c0c14' }}>
          {c.thumb && <img loading="lazy" decoding="async" src={c.thumb} alt="" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />}
          {c.d !== '—' && <span className="dur" style={{ position: 'absolute', right: 8, bottom: 8, background: 'rgba(0,0,0,.75)', color: '#fff', fontSize: 10, fontFamily: 'var(--fm)', padding: '2px 7px', borderRadius: 5 }}>{c.d}</span>}
        </div>
        <div style={{ padding: 12 }}>
          <b style={{ fontSize: 12, display: 'block', lineHeight: 1.4, minHeight: 32, overflow: 'hidden' }}>{c.t}</b>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}><Icon name="eye" style={{ width: 12, height: 12, verticalAlign: '-2px' }} /> {c.v}{c.tags ? ' · ' + c.tags : ''}</div>
        </div>
      </a>)}
    </div>
    {!cards.length && !busy && <div className="hint" style={{ textAlign: 'center', padding: 30 }}>Faça uma busca para ver referências reais do XVideos.</div>}
  </div>;
}

Object.assign(window, { Acc, AutoEditorApp, EnhancerApp, CriacaoApp, ReferenciaApp });
