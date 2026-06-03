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

/* ── ANALYZE — transcrição, análise e prompt ── */
function AnalyzeApp() {
  const [tab, setTab] = React.useState('prompt');
  const [stt, setStt] = React.useState('premium');
  const [transcribing, setTranscribing] = React.useState(false);
  const [uploadPct, setUploadPct] = React.useState(0);
  const [uploadedKey, setUploadedKey] = React.useState('');
  const [uploadedName, setUploadedName] = React.useState('');
  const [runResult, setRunResult] = React.useState(null);
  const fileInputRef = React.useRef(null);
  const providers = [
    ['auto', '⚡ Auto estrito'], ['assemblyai', 'AssemblyAI'], ['groq', 'OpenRouter STT'],
    ['openai', 'OpenAI'], ['local', '🖥 Local'], ['premium', '⭐ Premium'],
  ];
  async function handleFiles(files) {
    if (!files || !files.length) return;
    if (!window.mpApi) return;
    const arr = Array.from(files);
    setUploadedName(arr.map(f => f.name).join(', '));
    try {
      setUploadPct(1);
      let done = 0;
      const keys = await Promise.all(arr.map(f =>
        window.mpApi.uploadFile(f, p => {
          setUploadPct(Math.round((done * 100 + p) / arr.length));
        }).then(k => { done++; return k; })
      ));
      setUploadedKey(keys[0]);
      setUploadPct(100);
    } catch (e) {
      setUploadPct(0);
      alert('Upload falhou: ' + e.message);
    }
  }
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
            <b>{uploadedName || 'Arraste vídeos aqui ou clique para selecionar'}</b>
            <small>MP4 / MOV / MKV · upload direto para storage</small>
          </div>
          {uploadPct > 0 && uploadPct < 100 && <ProgressBar pct={uploadPct} tone="cy" label="Enviando para storage…" />}
          <div className="kv" style={{ fontSize: 12 }}>
            <div className="row"><span className="k">object_key</span><span className="v mono">{uploadedKey || 'nenhum selecionado'}</span></div>
            <div className="row"><span className="k">status</span><span className="v" style={{ color: uploadedKey ? 'var(--good)' : 'var(--muted)' }}>{uploadedKey ? 'enviado · pronto' : 'aguardando upload'}</span></div>
          </div>
        </div>

        <div>
          <label className="lbl">Transcrição (texto original)</label>
          <textarea className="inp" rows="5" defaultValue="Fala galera, bem-vindos ao canal. Hoje a gente preparou um conteúdo bem especial pra vocês…" />
        </div>
        <div className="grid2">
          <Field label="Idioma"><select className="inp"><option>pt-BR</option><option>en</option><option>es</option><option>auto</option></select></Field>
          <Field label="Limit"><input className="inp" type="number" defaultValue="20" /></Field>
        </div>

        <div>
          <label className="lbl">Motor de transcrição (STT)</label>
          <div className="rowx" data-tour="an-stt">
            {providers.map(([k, l]) => <button key={k} className={'btn sm' + (stt === k ? ' pri' : '')} onClick={() => setStt(k)}>{l}</button>)}
          </div>
          <div className="rowx" style={{ marginTop: 10 }}>
            <Check>Gemidos claros</Check><Check>Realçar fala baixa</Check>
          </div>
        </div>

        <details className="panel" style={{ padding: 0 }}>
          <summary style={{ padding: '14px 16px', cursor: 'pointer', fontSize: 13, fontWeight: 600, color: 'var(--text2)' }}>▸ Referências &amp; filtros avançados</summary>
          <div className="stack" style={{ padding: '0 16px 16px' }}>
            <Field label="Sites de referência"><div className="rowx"><Check on>Xvideos</Check><Check>Pornhub</Check><Check>XNXX</Check><Check>OnlyFans</Check></div></Field>
            <div className="grid2">
              <Field label="Atriz / Ator"><input className="inp" placeholder="Ex: Mônica Matos…" /></Field>
              <Field label="Qtd atores"><select className="inp"><option>Qualquer</option><option>Solo (1)</option><option>Casal (2)</option><option>Trio (3)</option><option>Gangbang (5+)</option></select></Field>
            </div>
            <div className="grid2">
              <Field label="País"><input className="inp" placeholder="Brasil, Japão, EUA…" /></Field>
              <Field label="Categoria / tag"><input className="inp" placeholder="Teen, MILF, Amateur…" /></Field>
            </div>
            <Field label="Duração"><select className="inp"><option>Qualquer duração</option><option>Curto (1–3 min)</option><option>Médio (3–10 min)</option><option>Longo (10–20 min)</option></select></Field>
          </div>
        </details>

        <div className="rowx" data-tour="an-go">
          <button className="btn pri" onClick={() => {
            setTranscribing(true);
            if (window.mpApi && uploadedKey) {
              window.mpApi.fetch('/analyze', {
                method: 'POST',
                body: JSON.stringify({ video_object_key: uploadedKey, original_filename: uploadedName, stt_provider: stt, limit: 20 }),
              }).then(r => {
                setRunResult(r);
                setTranscribing(false);
              }).catch(() => setTranscribing(false));
            } else {
              setTimeout(() => setTranscribing(false), 2400);
            }
          }}><Icon name="sparkles" />Analisar</button>
          <button className="btn ghost" onClick={() => { setUploadedKey(''); setUploadedName(''); setUploadPct(0); setRunResult(null); }}>Limpar</button>
        </div>
        {transcribing && <div className="panel"><ProgressBar pct={uploadedKey ? 80 : 64} tone="cy" label="Transcrevendo + analisando" eta="≈ 40 s restantes · large-v3" /></div>}
      </div>

      {/* RESULTADO */}
      <div className="stack">
        <div className="rowx" style={{ justifyContent: 'space-between' }}>
          <span className="hint" style={{ fontSize: 12, color: 'var(--muted)' }}>run_id: <b style={{ fontFamily: 'var(--fm)', color: 'var(--text2)' }}>{runResult?.run_id || 'run_8f2a41'}</b></span>
          <div className="rowx"><button className="btn sm"><Icon name="copy" />Copiar prompt</button><button className="btn sm">→ Compare</button></div>
        </div>
        <div className="tabbar">
          {[['prompt', 'Prompt'], ['srt', 'SRT'], ['vision', 'Visão IA'], ['json', 'JSON']].map(([k, l]) =>
            <button key={k} className={'tabx' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}
        </div>
        {tab === 'prompt' && <div className="panel" style={{ fontFamily: 'var(--fm)', fontSize: 12.5, lineHeight: 1.7, color: 'var(--text2)', whiteSpace: 'pre-wrap' }}>
          {`Gere título, descrição e tags para este vídeo adulto.\nIdioma: PT-BR. Tom: chamativo, direto.\n\nCONTEXTO (transcrição):\n"Fala galera, bem-vindos ao canal…"\n\nCATEGORIA detectada: Amador · Estúdio\nPERFORMERS: 2 (casal)\n\nRetorne JSON: { titulo, descricao, tags[] }`}
        </div>}
        {tab === 'srt' && <div className="stack">
          <button className="btn sm" style={{ alignSelf: 'flex-start' }}><Icon name="download" />Baixar .SRT</button>
          <div className="panel" style={{ fontFamily: 'var(--fm)', fontSize: 12, lineHeight: 1.7, color: 'var(--text2)' }}>
            {`1\n00:00:00,000 → 00:00:03,200\nFala galera, bem-vindos ao canal\n\n2\n00:00:03,200 → 00:00:07,000\nHoje a gente preparou um conteúdo especial`}
          </div>
        </div>}
        {tab === 'vision' && <div className="stack">
          <div className="thumbs">{['00:12', '01:04', '02:20', '03:11', '03:58', '04:10'].map(t => <Thumb key={t} label={t} />)}</div>
          <div className="panel" style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.6 }}>
            <b style={{ color: 'var(--cyan)' }}>Grok Vision:</b> Cena interna de estúdio com iluminação suave. Casal, plano médio. Sem equipamento visível no enquadramento principal.
          </div>
        </div>}
        {tab === 'json' && <div className="panel" style={{ fontFamily: 'var(--fm)', fontSize: 12, lineHeight: 1.7, color: 'var(--text2)', whiteSpace: 'pre-wrap' }}>
          {`{\n  "titulo": "Bastidores do estúdio — junho",\n  "categoria": "amador/estudio",\n  "performers": 2,\n  "tags": ["estúdio","premium","exclusivo"],\n  "confidence": 0.92\n}`}
        </div>}
      </div>
    </div>
  </div>;
}

/* ── COMPARE — comparação entre modelos ── */
function CompareApp() {
  const models = [
    { n: 'Grok-2', t: '1.8s', c: '$0.012', tok: '842', best: true, txt: 'Bastidores do estúdio — edição especial de junho', tone: 'pri' },
    { n: 'GPT-4o', t: '2.1s', c: '$0.014', tok: '910', txt: 'Conteúdo premium de junho gravado em estúdio', tone: 'cy' },
    { n: 'Claude Sonnet', t: '2.4s', c: '$0.009', tok: '788', txt: 'Edição exclusiva de estúdio — junho 2026', tone: 'violet' },
    { n: 'Gemini Flash', t: '0.9s', c: '$0.004', tok: '654', txt: 'Estúdio HD — bastidores de junho', tone: '' },
  ];
  return <div className="app">
    <AppHead icon="compare" title="Compare" desc="Roda o mesmo prompt em vários modelos e mostra custo, tempo, tokens e resultado lado a lado."
      right={<button className="btn pri sm"><Icon name="bolt" />Rodar 4 modelos</button>} />
    <Field label="Prompt"><textarea className="inp" rows="2" defaultValue="Gere um título chamativo (máx 60 caracteres) a partir da transcrição." /></Field>
    <div className="grid2">
      {models.map(m => <div key={m.n} className="panel stack" style={{ borderColor: m.best ? 'var(--pri-line)' : undefined, position: 'relative' }}>
        {m.best && <span className="pill pri" style={{ position: 'absolute', top: -11, right: 14 }}><Icon name="star" />vencedor</span>}
        <div className="rowx" style={{ justifyContent: 'space-between' }}>
          <b style={{ fontFamily: 'var(--fh)', fontSize: 16 }}>{m.n}</b>
          <Pill kind={m.tone} dot>{m.t}</Pill>
        </div>
        <div style={{ fontSize: 14, color: 'var(--text)', lineHeight: 1.5, minHeight: 44 }}>"{m.txt}"</div>
        <div className="rowx" style={{ gap: 8 }}>
          <span className="chip"><Icon name="clock" />{m.t}</span>
          <span className="chip"><Icon name="dollar" />{m.c}</span>
          <span className="chip"><Icon name="sparkles" />{m.tok} tok</span>
        </div>
        <button className={'btn block ' + (m.best ? 'pri' : '')}><Icon name="check" />Usar este</button>
      </div>)}
    </div>
  </div>;
}

/* ── RUNS — histórico técnico e resultados ── */
function RunsApp() {
  const [sel, setSel] = React.useState(0);
  const [runs, setRuns] = React.useState([
    { id: 'run_8f2a41', date: 'hoje 14:36', snip: 'Bastidores do estúdio — junho', ok: true },
    { id: 'run_8f1c02', date: 'hoje 13:10', snip: 'Sessão premium 05 — análise vision', ok: true },
    { id: 'run_8e9b77', date: 'ontem 19:42', snip: 'Colab estúdio X — transcrição', ok: true },
    { id: 'run_8e7a10', date: 'ontem 16:03', snip: 'Falha: áudio inaudível', ok: false },
  ]);
  React.useEffect(() => {
    if (window.mpApi) window.mpApi.listRuns(40).then(r => { if (r.length) { setRuns(r); setSel(0); } }).catch(() => {});
  }, []);
  return <div className="app" style={{ padding: 0 }}>
    <div style={{ padding: '22px 22px 0' }}>
      <AppHead icon="runs" title="Runs" desc="Histórico técnico de todas as análises — prompt, SRT, frames e JSON de cada execução." />
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 0, borderTop: '1px solid var(--line)' }}>
      <div style={{ borderRight: '1px solid var(--line)', padding: 14, display: 'flex', flexDirection: 'column', gap: 6 }}>
        {runs.map((r, i) => <button key={r.id} className="litem" style={{ textAlign: 'left', borderColor: i === sel ? 'var(--pri-line)' : undefined, background: i === sel ? 'var(--pri-soft)' : undefined }} onClick={() => setSel(i)}>
          <div className="li-main">
            <b style={{ fontFamily: 'var(--fm)', fontSize: 12, color: 'var(--muted)' }}>{r.id}</b>
            <small style={{ display: 'block', color: 'var(--text2)', fontSize: 12.5, margin: '2px 0' }}>{r.snip}</small>
            <span style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', color: r.ok ? 'var(--good)' : 'var(--pri)' }}>{r.ok ? 'OK' : 'ERRO'} · {r.date}</span>
          </div>
        </button>)}
      </div>
      <div className="stack" style={{ padding: 20 }}>
        <div className="rowx" style={{ justifyContent: 'space-between' }}>
          <b style={{ fontFamily: 'var(--fm)', fontSize: 14 }}>{runs[sel].id}</b>
          <Pill kind={runs[sel].ok ? 'good' : 'pri'} dot>{runs[sel].ok ? 'concluído' : 'erro'}</Pill>
        </div>
        <div className="sec mut"><Icon name="layers" />Frames-chave</div>
        <div className="thumbs">{['00:12', '01:04', '02:20', '03:11', '03:58'].map(t => <Thumb key={t} label={t} />)}</div>
        <div className="sec mut"><Icon name="doc" />Metadados</div>
        <div className="kv">
          <div className="row"><span className="k">Título gerado</span><span className="v">{runs[sel].snip}</span></div>
          <div className="row"><span className="k">Modelo</span><span className="v mono">grok-2-vision</span></div>
          <div className="row"><span className="k">Duração análise</span><span className="v mono">2 min 18 s</span></div>
          <div className="row"><span className="k">Tags</span><span className="v">estúdio · premium · junho</span></div>
        </div>
        <div className="rowx"><button className="btn sm"><Icon name="copy" />Copiar prompt</button><button className="btn sm"><Icon name="download" />Baixar SRT</button><button className="btn sm">→ Compare</button></div>
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
const FILE_OPS = [
  { op: 'download', icon: 'download', label: 'Baixar' },
  { op: 'rename', icon: 'pen', label: 'Renomear' },
  { op: 'copy', icon: 'copy', label: 'Copiar key' },
  { op: 'delete', icon: 'trash', label: 'Excluir', danger: true },
];
const MEDIA_ITEMS = [
  { n: 'clipe_estudio_2406.mp4', s: 'original', tone: '', tech: '1080p · 04:18', dur: '04:18', size: '500 MB', date: 'hoje 14:30' },
  { n: 'clipe_2406_BURN.mp4', s: 'burn', tone: 'good', tech: '1080p · legenda+logo', dur: '04:18', size: '512 MB', date: 'hoje 14:42' },
  { n: 'teaser_2406_vertical.mp4', s: 'teaser', tone: 'cy', tech: '9:16 · 0:15', dur: '0:15', size: '38 MB', date: 'hoje 14:45' },
  { n: 'sessao_premium_05.mp4', s: 'processando', tone: 'warn', tech: '4K · 12:40', dur: '12:40', size: '3.2 GB', date: 'hoje 13:10' },
  { n: 'autoeditor_compil_03.mp4', s: 'autoeditor', tone: 'violet', tech: '1080p · 08:22', dur: '08:22', size: '1.1 GB', date: 'hoje 12:02' },
  { n: 'colab_estudioX.mp4', s: '4K original', tone: '', tech: '4K · 22:10', dur: '22:10', size: '6.4 GB', date: 'ontem 19:40' },
];
const FILTERS = [['all', 'Todos'], ['original', 'Originais'], ['burn', 'Queimados'], ['teaser', 'Teasers'], ['autoeditor', 'AutoEditor']];

function FileActionGrid({ file, onOpen }) {
  return <div className="fa-grid">
    {FILE_ACTIONS.map(a => <button key={a.app} className="fa-tile" onClick={() => onOpen(a.app)}>
      <span className={'fa-ic ' + a.tone}><Icon name={a.icon} /></span>
      <b>{a.label}</b><small>{a.desc}</small>
    </button>)}
  </div>;
}

function MediaApp() {
  const [view, setView] = React.useState('icons');
  const [filter, setFilter] = React.useState('all');
  const [sel, setSel] = React.useState(null);      // selected file → detail view
  const [ctx, setCtx] = React.useState(null);      // {x,y,file} → context menu
  const [allItems, setAllItems] = React.useState(MEDIA_ITEMS);
  const [loading, setLoading] = React.useState(false);
  React.useEffect(() => {
    if (!window.mpApi) return;
    setLoading(true);
    window.mpApi.listMedia().then(r => { if (r.length) setAllItems(r); }).catch(() => {}).finally(() => setLoading(false));
  }, []);
  const items = allItems.filter(m => filter === 'all' || m.s.includes(filter) || (filter === 'original' && m.s.includes('original')));
  const openApp = (app) => { setCtx(null); if (window.__mpOpen) window.__mpOpen(app); };

  // DETAIL VIEW — what to do with this video
  if (sel) {
    return <div className="app" style={{ padding: 0 }}>
      <div className="file-detail-bar">
        <button className="btn sm ghost" onClick={() => setSel(null)}><Icon name="arrowL" />Arquivos</button>
        <b style={{ fontFamily: 'var(--fm)', fontSize: 13 }}>{sel.n}</b>
        <Pill kind={sel.tone} dot>{sel.s}</Pill>
      </div>
      <div className="file-detail">
        <div className="stack">
          <VStage dur={sel.dur} time={'00:00 / ' + sel.dur} pos={0} logo={sel.s === 'burn'} subtitle={sel.s === 'burn' ? 'legenda aplicada' : ''} />
          <div className="kv">
            <div className="row"><span className="k">Arquivo</span><span className="v mono">{sel.n}</span></div>
            <div className="row"><span className="k">Formato</span><span className="v">{sel.tech}</span></div>
            <div className="row"><span className="k">Tamanho</span><span className="v mono">{sel.size}</span></div>
            <div className="row"><span className="k">Criado</span><span className="v">{sel.date}</span></div>
            <div className="row"><span className="k">Status</span><span className="v" style={{ textTransform: 'capitalize' }}>{sel.s}</span></div>
          </div>
          <div className="rowx">{FILE_OPS.map(o => <button key={o.op} className={'btn sm' + (o.danger ? ' ghost' : '')} style={o.danger ? { color: 'var(--pri)', borderColor: 'var(--pri-line)' } : {}}><Icon name={o.icon} />{o.label}</button>)}</div>
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
        <span className="tb-search" style={{ height: 38, width: 180, position: 'static' }}><Icon name="search" />Buscar mídia…</span>
        <div className="rowx" style={{ gap: 4, border: '1px solid var(--line2)', borderRadius: 10, padding: 3 }}>
          {[['icons', 'grid'], ['list', 'list']].map(([k, ic]) => <button key={k} className={'btn sm ghost' + (view === k ? ' pri' : '')} style={{ padding: 7 }} onClick={() => setView(k)}><Icon name={ic} /></button>)}
        </div>
      </div>} />
    <div className="tabbar">
      {FILTERS.map(([k, l]) => <button key={k} className={'tabx' + (filter === k ? ' on' : '')} onClick={() => setFilter(k)}>{l}</button>)}
    </div>

    {view === 'icons' ? <div className="thumbs" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 14 }}>
      {items.map(m => <div key={m.n} className="file-card" onClick={() => setSel(m)}
        onContextMenu={e => { e.preventDefault(); setCtx({ x: e.clientX, y: e.clientY, file: m }); }}>
        <Media cap={null} dur={m.dur} play>
          <span className="pill" style={{ position: 'absolute', top: 8, left: 8, fontSize: 10, padding: '3px 9px' }}>{m.s}</span>
          <span className="file-hover"><span className="fh-btn"><Icon name="bolt" />Ver ações</span></span>
        </Media>
        <div style={{ padding: '10px 4px 4px' }}>
          <b style={{ fontSize: 12.5, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.n}</b>
          <div className="rowx" style={{ justifyContent: 'space-between', marginTop: 5 }}>
            <span style={{ fontSize: 10.5, color: 'var(--muted)' }}>{m.tech} · {m.size}</span>
            <Pill kind={m.tone} dot>{m.s}</Pill>
          </div>
        </div>
      </div>)}
    </div> : <div className="stack">
      {items.map(m => <div key={m.n} className="litem" style={{ cursor: 'pointer' }} onClick={() => setSel(m)}
        onContextMenu={e => { e.preventDefault(); setCtx({ x: e.clientX, y: e.clientY, file: m }); }}>
        <div style={{ width: 72, height: 41, borderRadius: 8, background: 'linear-gradient(135deg,#16161f,#0c0c14)', border: '1px solid var(--line)', flex: 'none', position: 'relative' }}>
          <span style={{ position: 'absolute', right: 4, bottom: 3, fontSize: 9, fontFamily: 'var(--fm)', color: 'var(--muted)' }}>{m.dur}</span>
        </div>
        <div className="li-main"><b>{m.n}</b><small>{m.tech} · {m.size} · {m.date}</small></div>
        <Pill kind={m.tone} dot>{m.s}</Pill>
        <button className="btn sm pri" onClick={e => { e.stopPropagation(); setSel(m); }}><Icon name="bolt" />Ações</button>
      </div>)}
    </div>}

    {ctx && <div className="ctxmenu" style={{ left: Math.min(ctx.x, window.innerWidth - 230), top: Math.min(ctx.y, window.innerHeight - 380) }} onClick={e => e.stopPropagation()}>
      <div className="ctx-head">{ctx.file.n}</div>
      <button className="ctx-item strong" onClick={() => { setSel(ctx.file); setCtx(null); }}><Icon name="eye" />Abrir / ver ações</button>
      <div className="ctx-sep" />
      {FILE_ACTIONS.slice(0, 6).map(a => <button key={a.app} className="ctx-item" onClick={() => openApp(a.app)}><Icon name={a.icon} />{a.label}</button>)}
      <div className="ctx-sep" />
      {FILE_OPS.map(o => <button key={o.op} className={'ctx-item' + (o.danger ? ' danger' : '')} onClick={() => setCtx(null)}><Icon name={o.icon} />{o.label}</button>)}
    </div>}
  </div>;
}

Object.assign(window, { AppHead, AnalyzeApp, CompareApp, RunsApp, MediaApp });
