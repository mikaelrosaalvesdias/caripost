/* MetaPorn OS — shell: boot, desktop, window manager, taskbar, start, tour */

const APPS = {
  // Inteligência e Mídia
  analyze:    { title: 'Analyze',         icon: 'analyze',    C: 'AnalyzeApp',    w: 1060, h: 740, grp: 'int' },
  compare:    { title: 'Compare',         icon: 'compare',    C: 'CompareApp',    w: 980,  h: 680, grp: 'int' },
  runs:       { title: 'Runs',            icon: 'runs',       C: 'RunsApp',       w: 1000, h: 680, grp: 'int' },
  media:      { title: 'Arquivos',        icon: 'media',      C: 'MediaApp',      w: 1080, h: 720, grp: 'int' },
  referencia: { title: 'Referência',      icon: 'refs',       C: 'ReferenciaApp', w: 1040, h: 720, grp: 'int' },
  autoeditor: { title: 'AutoEditor',      icon: 'autoeditor', C: 'AutoEditorApp', w: 1100, h: 770, grp: 'int' },
  enhancer:   { title: 'Video Enhancer',  icon: 'enhance',    C: 'EnhancerApp',   w: 1020, h: 700, grp: 'int' },
  // Edição & Conteúdo
  legenda:    { title: 'Legenda',         icon: 'captions',   C: 'LegendaApp',    w: 1040, h: 730, grp: 'edit' },
  logo:       { title: 'Logo',            icon: 'logo',       C: 'LogoApp',       w: 1020, h: 700, grp: 'edit' },
  teaser:     { title: 'Teaser',          icon: 'scissors',   C: 'TeaserApp',     w: 1020, h: 730, grp: 'edit' },
  thumbnail:  { title: 'Thumbnail',       icon: 'thumbnail',  C: 'ThumbnailApp',  w: 1020, h: 710, grp: 'edit' },
  // Operação e Distribuição
  criacao:    { title: 'Criação',         icon: 'post',       C: 'CriacaoApp',    w: 1060, h: 730, grp: 'op' },
  telegram:   { title: 'Telegram',        icon: 'telegram',   C: 'TelegramApp',   w: 980,  h: 680, grp: 'op' },
  publisher:  { title: 'Publicar',        icon: 'broadcast',  C: 'PublisherApp',  w: 980,  h: 690, grp: 'op' },
  calendar:   { title: 'Agenda',          icon: 'calendar',   C: 'CalendarApp',   w: 1000, h: 680, grp: 'op' },
  // Gestão de Agência
  creators:   { title: 'Criadores',       icon: 'users',      C: 'CreatorsApp',   w: 920,  h: 680, grp: 'ges' },
  trends:     { title: 'Tendências',      icon: 'trending',   C: 'TrendsApp',     w: 980,  h: 680, grp: 'ges' },
  financial:  { title: 'Financeiro',      icon: 'dollar',     C: 'FinancialApp',  w: 960,  h: 680, grp: 'ges' },
  dmca:       { title: 'DMCA',            icon: 'shield',     C: 'DmcaApp',       w: 940,  h: 680, grp: 'ges' },
  settings:   { title: 'Settings',        icon: 'settings',   C: 'SettingsApp',   w: 840,  h: 660, grp: 'ges' },
  wizard:     { title: 'Assistente',      icon: 'flow',       C: 'WizardApp',     w: 960,  h: 720, grp: null },
};
const GROUPS = [
  ['int', 'Inteligência e Mídia'],
  ['edit', 'Edição & Conteúdo'],
  ['op', 'Operação e Distribuição'],
  ['ges', 'Gestão de Agência'],
];
const PINNED = ['autoeditor', 'analyze', 'legenda', 'logo', 'criacao', 'media', 'telegram'];

const TOURS = {
  autoeditor: [
    { sel: '[data-tour="ae-start"]', title: 'Inicie o AutoEditor', body: 'Selecione as fontes, ajuste cenas e transições e clique aqui. O Grok Vision analisa e monta o corte sozinho.' },
    { sel: '[data-tour="ae-recut"]', title: 'Re-cut rápido', body: 'Gostou do vídeo mas quer outra seleção? O Re-cut reaproveita a análise Vision e refaz em 20–40 min.' },
  ],
  analyze: [
    { sel: '[data-tour="an-drop"]', title: 'Comece pelo vídeo', body: 'Arraste um ou vários vídeos. Eles sobem em fila paralela direto para o storage.' },
    { sel: '[data-tour="an-go"]', title: 'Analise', body: 'Gera transcrição, prompt, visão IA e JSON — tudo nas abas do resultado ao lado.' },
  ],
};

function App() {
  const [booting, setBooting] = React.useState(true);
  const [bootPct, setBootPct] = React.useState(0);
  const [bootMsg, setBootMsg] = React.useState('Iniciando MetaPorn OS…');
  const [wins, setWins] = React.useState([]);
  const [zTop, setZTop] = React.useState(10);
  const [start, setStart] = React.useState(false);
  const [tasks, setTasks] = React.useState(false);
  const [notif, setNotif] = React.useState(false);
  const [auto, setAuto] = React.useState(false);
  const [tour, setTour] = React.useState(null);
  const [now, setNow] = React.useState(new Date());

  const skipBoot = React.useCallback(() => { setBooting(false); }, []);

  // Auth check — mostra login só se a API exigir
  React.useEffect(() => {
    if (window.__mpCheckAuth) window.__mpCheckAuth();
  }, []);

  React.useEffect(() => {
    const msgs = ['Iniciando MetaPorn OS…', 'Carregando módulos de IA…', 'Conectando storage…', 'Verificando tokens…', 'Pronto.'];
    const DUR = 2200, t0 = Date.now();
    let raf, done = false;
    const tick = () => {
      const p = Math.min(100, Math.round(((Date.now() - t0) / DUR) * 100));
      setBootPct(p);
      setBootMsg(msgs[Math.min(msgs.length - 1, Math.floor(p / 22))]);
      if (p >= 100) { if (!done) { done = true; setTimeout(() => setBooting(false), 450); } return; }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const clk = setInterval(() => setNow(new Date()), 30000);
    return () => { cancelAnimationFrame(raf); clearInterval(clk); };
  }, []);

  function focus(id) { setZTop(z => { setWins(ws => ws.map(w => w.id === id ? { ...w, z: z + 1, min: false } : w)); return z + 1; }); }

  function open(appId) {
    setStart(false);
    if (appId === 'auto') { setAuto(true); return; }
    const existing = wins.find(w => w.appId === appId);
    if (existing) {
      // Re-monta o app para ele reler o contexto (mpCtx.file)
      focus(existing.id);
      setWins(ws => ws.map(w => w.id === existing.id ? { ...w, nonce: (w.nonce || 0) + 1 } : w));
      return;
    }
    const a = APPS[appId];
    if (!a) return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const w = Math.min(a.w, vw - 40), h = Math.min(a.h, vh - 110);
    const offset = wins.length * 28 % 120;
    const x = Math.max(20, (vw - w) / 2 - 60 + offset);
    const y = Math.max(20, (vh - h - 56) / 2 - 30 + offset);
    const id = 'w' + Date.now();
    setZTop(z => z + 1);
    setWins(ws => [...ws, { id, appId, x, y, w, h, z: zTop + 1, min: false, max: vw < 760, nonce: 0 }]);
    if (TOURS[appId]) setTimeout(() => startTour(appId), 360);
  }
  function close(id) {
    setWins(ws => ws.map(w => w.id === id ? { ...w, closing: true } : w));
    setTimeout(() => setWins(ws => ws.filter(w => w.id !== id)), 150);
  }
  function toggleMin(id) { setWins(ws => ws.map(w => w.id === id ? { ...w, min: !w.min } : w)); }
  function toggleMax(id) { setWins(ws => ws.map(w => w.id === id ? { ...w, max: !w.max } : w)); focus(id); }

  function startTour(appId) { const steps = TOURS[appId]; if (steps) setTour({ steps, idx: 0 }); }

  const running = [...new Set(wins.map(w => w.appId))];
  window.__mpOpen = open;
  const t = now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  const d = now.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });

  return <div className="os" onMouseDown={() => { setStart(false); setTasks(false); setNotif(false); }}>
    {booting && <Boot pct={bootPct} msg={bootMsg} onSkip={skipBoot} />}

    <div className="wallpaper">
      <div className="aurora a1" /><div className="aurora a2" /><div className="aurora a3" />
      <div className="wall-logo">META<em>P</em></div>
    </div>

    {/* desktop — grouped grid, ALL apps visible */}
    <div className="desk">
      <div className="desk-col">
        <div className="desk-col-label">Fluxo Rápido</div>
        <div className="desk-col-grid">
          <div className="dicon feat" onClick={() => open('auto')}><div className="ig"><Icon name="bolt" /></div><span>Modo Automático</span></div>
          <div className="dicon feat vi" onClick={() => open('autoeditor')}><div className="ig"><Icon name="autoeditor" /></div><span>AutoEditor</span></div>
          <div className="dicon" onClick={() => open('wizard')}><div className="ig" style={{ background: 'linear-gradient(150deg,#20d5ff,#1380a3)', color: '#fff', borderColor: 'transparent' }}><Icon name="flow" /></div><span>Assistente</span></div>
        </div>
      </div>
      {GROUPS.map(([g, label]) => <div className="desk-col" key={g}>
        <div className="desk-col-label">{label}</div>
        <div className="desk-col-grid">
          {Object.keys(APPS).filter(id => APPS[id].grp === g && id !== 'autoeditor').map(id =>
            <div key={id} className="dicon" onClick={() => open(id)}><div className="ig"><Icon name={APPS[id].icon} /></div><span>{APPS[id].title}</span></div>)}
        </div>
      </div>)}
    </div>

    {/* windows */}
    {wins.map(w => <Window key={w.id} w={w} onFocus={() => focus(w.id)} onClose={() => close(w.id)}
      onMin={() => toggleMin(w.id)} onMax={() => toggleMax(w.id)} onHelp={() => startTour(w.appId)}
      onMove={(x, y) => setWins(ws => ws.map(i => i.id === w.id ? { ...i, x, y } : i))} topZ={zTop} />)}

    {/* modo automático fullscreen */}
    {auto && <AutoMode onExit={() => setAuto(false)} onClose={() => setAuto(false)} />}

    {/* start menu */}
    {start && <StartMenu onOpen={open} onClick={e => e.stopPropagation()} />}

    {/* flyouts */}
    {tasks && <TaskCenter onClick={e => e.stopPropagation()} />}
    {notif && <NotifCenter onClick={e => e.stopPropagation()} />}

    {/* taskbar */}
    <div className="taskbar" onMouseDown={e => e.stopPropagation()}>
      <button className="tb-start" onClick={() => { setStart(s => !s); setTasks(false); setNotif(false); }}>
        <span className="m">M</span>Iniciar</button>
      <button className="tb-search" onClick={() => { setStart(true); setTasks(false); setNotif(false); }}><Icon name="search" />Buscar app ou ação<kbd>Ctrl + Espaço</kbd></button>
      <div className="tb-apps">
        {PINNED.map(id => {
          const isRun = running.includes(id);
          return <button key={id} className={'tb-app' + (isRun ? ' run' : '')} onClick={() => open(id)} title={APPS[id].title}>
            <Icon name={APPS[id].icon} />
          </button>;
        })}
      </div>
      <div className="tb-tray">
        <button className="tray-btn" onClick={() => { setTasks(s => !s); setNotif(false); setStart(false); }}>
          <Icon name="tasks" /></button>
        <button className="tray-btn" onClick={() => { setNotif(s => !s); setTasks(false); setStart(false); }}>
          <Icon name="bell" /></button>
        <div className="tb-clock"><b>{t}</b><span>{d}</span></div>
      </div>
    </div>

    {tour && <Tour tour={tour} setTour={setTour} />}
  </div>;
}

function Boot({ pct, msg, onSkip }) {
  return <div className={'boot' + (pct >= 100 ? ' fade' : '')} onClick={onSkip} title="clique para entrar">
    <div className="boot-mark">M</div>
    <div className="boot-logo">Meta<em>Porn</em><span style={{ fontSize: 20, color: 'var(--muted)', fontWeight: 400, marginLeft: 8 }}>OS</span></div>
    <div className="boot-bar"><i style={{ width: pct + '%' }} /></div>
    <div className="boot-status">{msg} {pct < 100 && pct + '%'}</div>
    <div className="boot-ver">v1.20.2 · admin platform</div>
  </div>;
}

function Window({ w, onFocus, onClose, onMin, onMax, onHelp, onMove, topZ }) {
  const a = APPS[w.appId];
  const Comp = window[a.C];
  const drag = React.useRef(null);
  function down(e) {
    if (w.max) return;
    onFocus();
    drag.current = { sx: e.clientX, sy: e.clientY, ox: w.x, oy: w.y };
    const mv = ev => { if (!drag.current) return; onMove(drag.current.ox + ev.clientX - drag.current.sx, Math.max(0, drag.current.oy + ev.clientY - drag.current.sy)); };
    const up = () => { drag.current = null; document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); };
    document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
  }
  const style = w.max
    ? { inset: 0, width: '100%', height: 'calc(100vh - 56px)', zIndex: w.z }
    : { left: w.x, top: w.y, width: w.w, height: w.h, zIndex: w.z };
  return <div className={'win' + (w.max ? ' max' : '') + (w.min ? ' min' : '') + (w.closing ? ' closing' : '') + (w.z === topZ ? ' focused' : '')}
    style={style} onMouseDown={e => { e.stopPropagation(); onFocus(); }}>
    <div className="titlebar" onMouseDown={down} onDoubleClick={onMax}>
      <div className="tb-ic"><Icon name={a.icon} /></div>
      <span className="tb-name">{a.title}</span>
      <div className="win-actions">
        <button className="wbtn help" onClick={onHelp} title="Tutorial"><Icon name="help" /></button>
        <button className="wbtn" onClick={onMin}><Icon name="min" /></button>
        <button className="wbtn" onClick={onMax}><Icon name={w.max ? 'restore' : 'max'} /></button>
        <button className="wbtn close" onClick={onClose}><Icon name="x" /></button>
      </div>
    </div>
    <div className="win-body">{Comp ? <Comp key={w.nonce || 0} /> : <div className="app">App não encontrado</div>}</div>
  </div>;
}

function StartMenu({ onOpen, onClick }) {
  return <div className="startmenu" onMouseDown={onClick}>
    <div className="sm-search"><Icon name="search" />Buscar apps, ações e mídias…</div>
    <div className="sm-label">Fluxo rápido</div>
    <div className="sm-feat">
      <div className="sm-feat-card" onClick={() => onOpen('auto')}>
        <div className="fi"><Icon name="bolt" /></div>
        <div><b>Modo Automático</b><small>fonte → publicado sozinho</small></div>
      </div>
      <div className="sm-feat-card" onClick={() => onOpen('autoeditor')}>
        <div className="fi vi"><Icon name="autoeditor" /></div>
        <div><b>AutoEditor</b><small>cortes com Grok Vision</small></div>
      </div>
      <div className="sm-feat-card" onClick={() => onOpen('wizard')}>
        <div className="fi cy"><Icon name="flow" /></div>
        <div><b>Assistente</b><small>passo a passo</small></div>
      </div>
    </div>
    {GROUPS.map(([g, label]) => <React.Fragment key={g}>
      <div className="sm-label">{label}</div>
      <div className="sm-grid">
        {Object.keys(APPS).filter(id => APPS[id].grp === g && id !== 'autoeditor').map(id => <div key={id} className="sm-app" onClick={() => onOpen(id)}>
          <div className="si"><Icon name={APPS[id].icon} /></div><span>{APPS[id].title}</span>
        </div>)}
      </div>
    </React.Fragment>)}
  </div>;
}

/* Central de Tarefas — jobs reais (AutoEditor + Enhancer + Burn) */
function TaskCenter({ onClick }) {
  const [items, setItems] = React.useState([]);
  const [loaded, setLoaded] = React.useState(false);
  React.useEffect(() => {
    if (!window.mpApi) return;
    Promise.allSettled([
      window.mpApi.listAeJobs(6),
      window.mpApi.enhancerJobs(),
    ]).then(([ae, ve]) => {
      const out = [];
      (ae.status === 'fulfilled' ? ae.value : []).forEach(j => out.push({
        ic: 'autoeditor',
        title: 'AutoEditor · ' + (j.job_id || '').slice(0, 8),
        status: j.status, pct: j.progress_pct || (j.status === 'done' ? 100 : 0),
        detail: j.detail || '',
      }));
      (ve.status === 'fulfilled' ? ve.value : []).slice(0, 4).forEach(j => out.push({
        ic: 'enhance',
        title: 'Enhancer · ' + (j.job_id || '').slice(0, 8),
        status: j.status, pct: j.progress_pct || (j.status === 'done' ? 100 : 0),
        detail: j.detail || '',
      }));
      setItems(out.slice(0, 8));
      setLoaded(true);
    });
  }, []);
  const active = items.filter(i => i.status === 'running' || i.status === 'pending').length;
  return <div className="flyout" onMouseDown={onClick}>
    <div className="flyout-head"><h3>Central de Tarefas</h3><span className="pill cy" style={{ fontSize: 11 }}>{active} ativas</span></div>
    <div className="flyout-body">
      {!loaded && <div className="hint" style={{ padding: 12 }}>Carregando jobs…</div>}
      {loaded && !items.length && <div className="hint" style={{ padding: 12 }}>Nenhum job recente.</div>}
      {items.map((it, i) => {
        const cls = it.status === 'done' ? 'done' : (it.status === 'running' || it.status === 'pending') ? 'run' : 'queue';
        return <div key={i} className="task">
          <div className={'tk-ic ' + cls}><Icon name={it.status === 'done' ? 'check' : it.ic} /></div>
          <div className="tk-main"><b>{it.title}</b>
            {it.status !== 'done' && <div className="track cy"><i style={{ width: (it.pct || 0) + '%' }} /></div>}
          </div>
          <div className={'tk-rt' + (it.status === 'done' ? ' gd' : '')}>{it.status === 'done' ? 'concluído' : (it.pct || 0) + '%'}</div>
        </div>;
      })}
    </div>
  </div>;
}

/* Notificações — jobs concluídos recentes */
function NotifCenter({ onClick }) {
  const [items, setItems] = React.useState([]);
  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.listAeJobs(5).then(jobs => {
      setItems((jobs || []).filter(j => j.status === 'done').slice(0, 5).map(j => ({
        ic: 'check',
        t: 'AutoEditor concluído',
        d: (j.result_video_object_key || '').split('/').pop() || (j.job_id || '').slice(0, 8),
      })));
    }).catch(() => {});
  }, []);
  return <div className="flyout" onMouseDown={onClick}>
    <div className="flyout-head"><h3>Notificações</h3></div>
    <div className="flyout-body">
      {!items.length && <div className="hint" style={{ padding: 12 }}>Sem notificações.</div>}
      {items.map((n, i) => <div key={i} className="task">
        <div className="tk-ic done"><Icon name={n.ic} /></div>
        <div className="tk-main"><b>{n.t}</b><small style={{ color: 'var(--muted)', fontSize: 11.5 }}>{n.d}</small></div>
      </div>)}
    </div>
  </div>;
}

function Tour({ tour, setTour }) {
  const { steps, idx } = tour;
  const step = steps[idx];
  const [rect, setRect] = React.useState(null);
  React.useLayoutEffect(() => {
    const el = document.querySelector(step.sel);
    if (el) { const r = el.getBoundingClientRect(); setRect({ top: r.top - 6, left: r.left - 6, width: r.width + 12, height: r.height + 12 }); }
    else setRect(null);
  }, [idx]);
  const coachStyle = rect
    ? { top: Math.min(window.innerHeight - 220, rect.top + rect.height + 14), left: Math.min(window.innerWidth - 340, Math.max(14, rect.left)) }
    : { top: '40%', left: '50%', transform: 'translate(-50%,-50%)' };
  return <>
    <div className="tour-veil" onClick={() => setTour(null)} />
    {rect && <div className="spot-ring" style={rect} />}
    <div className="coach" style={coachStyle}>
      <div className="step">Tutorial · passo {idx + 1} de {steps.length}</div>
      <h4>{step.title}</h4>
      <p>{step.body}</p>
      <div className="coach-nav">
        <button className="btn sm ghost" onClick={() => setTour(null)}>Pular</button>
        <div className="coach-dots">{steps.map((_, i) => <i key={i} className={i === idx ? 'on' : ''} />)}</div>
        {idx > 0 && <button className="btn sm" onClick={() => setTour({ steps, idx: idx - 1 })}>Voltar</button>}
        <button className="btn sm pri" onClick={() => idx === steps.length - 1 ? setTour(null) : setTour({ steps, idx: idx + 1 })}>
          {idx === steps.length - 1 ? 'Entendi' : 'Próximo'}</button>
      </div>
    </div>
  </>;
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
