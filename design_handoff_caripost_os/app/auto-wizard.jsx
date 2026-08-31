/* MetaPorn OS — Modo Automático (fullscreen) + Assistente (wizard) */

const PIPE = [
  { k: 'upload', ic: 'upload', label: 'Upload' },
  { k: 'vision', ic: 'analyze', label: 'Vision IA' },
  { k: 'scenes', ic: 'autoeditor', label: 'Detecção' },
  { k: 'select', ic: 'sparkles', label: 'Seleção Grok' },
  { k: 'cut', ic: 'scissors', label: 'Corte' },
  { k: 'legenda', ic: 'captions', label: 'Legenda' },
  { k: 'logo', ic: 'logo', label: 'Logo' },
  { k: 'render', ic: 'enhance', label: 'Render' },
  { k: 'publish', ic: 'broadcast', label: 'Publicar' },
];

function AutoMode({ onExit, onClose }) {
  const [active, setActive] = React.useState(4);   // index running
  const [step, setStep] = React.useState(58);      // current-step %
  const [paused, setPaused] = React.useState(false);

  React.useEffect(() => {
    if (paused) return;
    const id = setInterval(() => {
      setStep(s => {
        let ns = s + 2;
        if (ns >= 100) {
          ns = 0;
          setActive(a => Math.min(a + 1, PIPE.length - 1));
        }
        return ns;
      });
    }, 380);
    return () => clearInterval(id);
  }, [paused]);

  const overall = Math.min(Math.round((active / PIPE.length) * 100 + step / PIPE.length), 99);

  return <div className="auto-screen">
    <div className="auto-top">
      <div className="kic"><Icon name="bolt" /></div>
      <div>
        <h2>Modo Automático</h2>
        <div className="sub">3 fontes · 39 min · AutoEditor + Grok Vision · iniciado 14:32</div>
      </div>
      <div className="big">
        <b>{overall + '%'}</b>
        <span>{'≈\u00A0' + Math.max(1, Math.round((100 - overall) / 14)) + '\u00A0min\u00A0restantes'}</span>
      </div>
      <button className="btn exit" onClick={onExit}><Icon name="restore" />Minimizar</button>
      <button className="wbtn close" onClick={onClose} style={{ width: 40, height: 40, borderRadius: 10 }}><Icon name="x" /></button>
    </div>

    <div className="pipe">
      {PIPE.map((n, i) => {
        const state = i < active ? 'done' : i === active ? 'run' : 'queue';
        return <React.Fragment key={n.k}>
          <div className={'pnode ' + state}>
            <div className="ball">{state === 'done' ? <Icon name="check" /> : <Icon name={n.ic} />}</div>
            <b>{n.label}</b>
            <small>{state === 'done' ? 'ok' : state === 'run' ? 'rodando' : 'na fila'}</small>
          </div>
          {i < PIPE.length - 1 && <div className={'pconn ' + (i < active ? 'done' : i === active ? 'run' : '')} />}
        </React.Fragment>;
      })}
    </div>

    <div className="auto-mid">
      <div className="auto-card">
        <h4><Icon name={PIPE[active].ic} style={{ width: 18, height: 18, color: 'var(--cyan)' }} />Etapa atual — {PIPE[active].label}<span className="spin" /></h4>
        <LogLines items={[
          { s: 'done', t: '3 fontes preparadas · HDR→SDR aplicado', time: '14:33' },
          { s: 'done', t: 'Grok Vision analisou 142 frames', time: '14:51' },
          { s: 'done', t: '38 candidatos de cena detectados', time: '14:53' },
          { s: 'done', t: 'Grok selecionou 14 cenas', time: '14:54' },
          { s: 'now', t: `${PIPE[active].label}… ${Math.round(step)}%` },
        ]} />
        <ProgressBar pct={Math.round(step)} tone="cy" label="Progresso desta etapa" eta={`≈ ${Math.max(5, Math.round((100 - step) * 0.6))} s restantes nesta etapa`} />
        <div style={{ marginTop: 'auto' }}>
          <ProgressBar pct={overall} label="Progresso total do fluxo" eta={`${active} de ${PIPE.length} etapas concluídas`} />
        </div>
      </div>
      <div className="auto-card">
        <h4><Icon name="eye" style={{ width: 18, height: 18 }} />Prévia ao vivo</h4>
        <div className="auto-prev"><VStage dur="06:12" time={`0${Math.floor(step/20)}:${String(Math.round(step*0.5)).padStart(2,'0')} / 06:12`} pos={step} logo subtitle="conteúdo especial de junho" /></div>
      </div>
    </div>

    <div className="auto-foot">
      <button className="btn" onClick={() => setPaused(p => !p)}><Icon name={paused ? 'play' : 'pause'} />{paused ? 'Retomar' : 'Pausar'}</button>
      <button className="btn"><Icon name="pen" />Intervir nesta etapa</button>
      <button className="btn ghost" onClick={() => { setStep(0); setActive(a => Math.min(a + 1, PIPE.length - 1)); }}>Pular etapa<Icon name="chevR" /></button>
      <span className="pill cy" style={{ marginLeft: 'auto' }}><Icon name="bell" />Avisar no Telegram quando concluir</span>
    </div>
  </div>;
}

const WIZ = [
  { t: 'Origem', d: 'Escolha o vídeo bruto', ic: 'upload' },
  { t: 'Transcrição', d: 'Gere e revise as legendas', ic: 'captions' },
  { t: 'Marca', d: 'Aplique logo e estilo', ic: 'logo' },
  { t: 'Conteúdo', d: 'Título, descrição e capa', ic: 'sparkles' },
  { t: 'Publicar', d: 'Agende ou poste', ic: 'send' },
];

function WizardApp() {
  const [i, setI] = React.useState(1);
  return <div className="app">
    <div className="app-head">
      <div className="tb-ic" style={{ width: 40, height: 40, borderRadius: 12 }}><Icon name="flow" style={{ width: 20, height: 20 }} /></div>
      <div className="lead">
        <div className="app-title">Assistente de Fluxo</div>
        <div className="app-desc">Conduz você do upload à publicação, um passo de cada vez.</div>
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
      {i === 0 && <div className="dropzone"><div className="dz-ic"><Icon name="upload" /></div><b>Arraste o vídeo</b><small>MP4 / MOV até 8 GB</small></div>}
      {i === 1 && <div className="split"><Media cap="prévia" subtitle="conteúdo especial de junho" /><div className="stack"><ProgressBar pct={100} tone="gd" label="Transcrição" eta="✓ 142 segmentos" /><Field label="Revisar"><textarea className="inp" defaultValue="Fala galera, bem-vindos ao canal…" /></Field></div></div>}
      {i === 2 && <div className="split"><Media cap="prévia" logo play={false} /><div className="stack"><Field label="Logo"><div className="litem"><span className="li-ic"><Icon name="star" /></span><div className="li-main"><b>marca_estudio.png</b></div></div></Field><Field label="Posição"><div className="checks"><Check>Sup. esq.</Check><Check on>Inf. dir.</Check></div></Field></div></div>}
      {i === 3 && <div className="stack"><Field label="Título"><input className="inp" defaultValue="Bastidores do estúdio — edição especial de junho" /></Field><Field label="Capa"><div className="thumbs">{['00:12', '01:04', '02:20'].map((t, k) => <Thumb key={t} label={t} sel={k === 1} />)}</div></Field></div>}
      {i === 4 && <div className="grid2"><div className="panel" style={{ padding: 0, overflow: 'hidden' }}><Media cap="post pronto" logo play /></div><div className="stack"><Field label="Plataformas"><div className="checks"><Check on>Portal</Check><Check on>Telegram</Check></div></Field><Field label="Quando"><div className="checks"><Check on>Agora</Check><Check>Agendar</Check></div></Field><button className="btn pri block"><Icon name="send" />Publicar</button></div></div>}
    </div>

    <div className="rowx" style={{ justifyContent: 'space-between' }}>
      <button className="btn ghost" disabled={i === 0} onClick={() => setI(Math.max(0, i - 1))}><Icon name="arrowL" />Voltar</button>
      <div className="rowx"><button className="btn ghost">Pular</button>
        <button className="btn pri" onClick={() => setI(Math.min(WIZ.length - 1, i + 1))}>{i === WIZ.length - 1 ? 'Concluir' : 'Próximo'}<Icon name="arrowR" /></button></div>
    </div>
  </div>;
}

Object.assign(window, { AutoMode, WizardApp, PIPE, WIZ });
