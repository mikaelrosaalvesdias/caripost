/* MetaPorn OS — Edição & Conteúdo: Legenda, Logo, Teaser, Thumbnail */

/* ── LEGENDA — transcrição, SRT e queima ── */
function LegendaApp() {
  const [tab, setTab] = React.useState('edit');
  const [burning, setBurning] = React.useState(false);
  const srt = [
    { i: 1, t: '00:00,0 → 00:03,2', x: 'Fala galera, bem-vindos ao canal' },
    { i: 2, t: '00:03,2 → 00:07,0', x: 'Hoje a gente preparou um conteúdo especial' },
    { i: 3, t: '00:07,0 → 00:11,4', x: 'Fica até o final que vale muito a pena' },
  ];
  return <div className="app">
    <AppHead icon="captions" title="Legenda & Queima" desc="Gera SRT (PT-BR), deixa você revisar, escolhe o estilo e queima a legenda no vídeo via FFmpeg."
      right={<Pill kind="good" dot>PT-BR detectado</Pill>} />
    <div className="split">
      <div className="stack">
        <div className="sec cy"><Icon name="wave" />Prévia · 142 segmentos</div>
        <VStage dur="04:18" time="00:07 / 04:18" pos={3} subtitle="Hoje a gente preparou um conteúdo especial" />
        <div className="prog"><ProgressBar pct={100} tone="gd" label="Transcrição (large-v3)" eta="✓ concluída em 2 min 18 s" /></div>
        <div className="rowx">
          <span className="chip"><Icon name="mic" />Premium · large-v3</span>
          <Check on>Gemidos claros</Check><Check>Realçar fala baixa</Check>
        </div>
      </div>
      <div className="stack">
        <div className="tabbar">
          <button className={'tabx' + (tab === 'edit' ? ' on' : '')} onClick={() => setTab('edit')}>Editor SRT</button>
          <button className={'tabx' + (tab === 'style' ? ' on' : '')} onClick={() => setTab('style')}>Estilo</button>
        </div>
        {tab === 'edit' ? <div className="panel flush">
          {srt.map(s => <div key={s.i} style={{ padding: '12px 15px', borderBottom: '1px solid var(--line)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--fm)', fontSize: 11, color: 'var(--muted)' }}><span>#{s.i}</span><span>{s.t}</span></div>
            <div style={{ fontSize: 13.5, marginTop: 4 }}>{s.x}</div>
          </div>)}
          <div style={{ padding: '11px 15px', fontSize: 12, color: 'var(--muted)' }}>+ 139 segmentos…</div>
        </div> : <div className="panel stack">
          <Field label="Fonte"><select className="inp"><option>Inter Bold</option><option>Space Grotesk</option><option>Montserrat</option></select></Field>
          <div className="grid2">
            <Field label="Tamanho"><select className="inp"><option>Grande</option><option>Médio</option><option>Pequeno</option></select></Field>
            <Field label="Posição"><select className="inp"><option>Inferior central</option><option>Superior</option></select></Field>
          </div>
          <Field label="Cor / contorno"><div className="rowx"><span className="chip"><span style={{ width: 14, height: 14, borderRadius: 4, background: '#fff' }} />Branco</span><span className="chip"><span style={{ width: 14, height: 14, borderRadius: 4, background: '#000', border: '1px solid var(--line2)' }} />Contorno preto</span><span className="chip"><span style={{ width: 14, height: 14, borderRadius: 4, background: 'var(--pri)' }} />Vermelho</span></div></Field>
        </div>}
        {burning && <div className="panel"><ProgressBar pct={42} tone="cy" label="Queimando legenda (FFmpeg)" eta="≈ 50 s · render 02:31 / 04:18" /></div>}
        <div className="rowx" style={{ justifyContent: 'flex-end' }}>
          <button className="btn"><Icon name="download" />Baixar .srt</button>
          <button className="btn"><Icon name="globe" />Traduzir</button>
          <button className="btn pri" data-tour="leg-burn" onClick={() => setBurning(true)}><Icon name="burn" />Queimar legenda</button>
        </div>
      </div>
    </div>
  </div>;
}

/* ── LOGO — studio de marca d'água arrastável ── */
function LogoApp() {
  const [pos, setPos] = React.useState('br');
  const [size, setSize] = React.useState(20);
  const [op, setOp] = React.useState(85);
  const coords = { tl: [6, 8], tr: [78, 8], bl: [6, 74], br: [78, 74], c: [42, 42] };
  const [lx, ly] = coords[pos] || coords.br;
  return <div className="app">
    <AppHead icon="logo" title="Studio de Logo" desc="Arraste a marca d'água na prévia, ajuste tamanho e opacidade, e queime no vídeo final."
      right={<Pill kind="cy" dot>arraste para posicionar</Pill>} />
    <div className="logo-studio">
      <div className="stack">
        <div className="sec cy"><Icon name="eye" />Palco — arraste a logo</div>
        <div className="vstage" style={{ aspectRatio: '16/9' }}>
          <div className="ph" />
          <span className="dur">04:18</span>
          <div className="logo-drag" style={{ left: lx + '%', top: ly + '%', width: size + '%', opacity: op / 100 }}>LOGO</div>
          <div className="vcontrols"><span className="pbtn"><Icon name="play" /></span><div className="vbar"><i style={{ width: '0%' }} /></div><span className="vtime">00:00 / 04:18</span></div>
        </div>
        <div className="hint" style={{ fontSize: 12, color: 'var(--cyan)', fontFamily: 'var(--fm)' }}>x: {lx}%  ·  y: {ly}%  ·  escala: {size}%</div>
      </div>
      <div className="stack">
        <Field label="Logo / marca">
          <div className="litem"><span className="li-ic"><Icon name="image" /></span><div className="li-main"><b>marca_estudio.png</b><small>PNG transparente · 512×512</small></div><button className="btn sm ghost"><Icon name="upload" /></button></div>
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
        <div className="rowx" style={{ justifyContent: 'flex-end' }}>
          <button className="btn"><Icon name="eye" />Pré-visualizar</button>
          <button className="btn pri"><Icon name="burn" />Queimar logo</button>
        </div>
      </div>
    </div>
  </div>;
}

/* ── TEASER — corte curto dos melhores momentos ── */
function TeaserApp() {
  const [running, setRunning] = React.useState(false);
  return <div className="app">
    <AppHead icon="scissors" title="Gerar Teaser" desc="Detecta os melhores momentos e monta um teaser curto e vertical, pronto pra divulgação."
      right={<Pill kind="cy" dot>auto-detecção de cenas</Pill>} />
    <div className="split">
      <div className="stack">
        <div className="sec mut"><Icon name="wave" />Linha do tempo · momentos sugeridos</div>
        <div className="panel" style={{ padding: 14 }}>
          <div style={{ position: 'relative', height: 60, borderRadius: 9, background: 'linear-gradient(90deg,#16161f,#0c0c14)', overflow: 'hidden', border: '1px solid var(--line)' }}>
            {[[8, 12], [34, 10], [58, 14], [80, 9]].map(([l, w], i) => <div key={i} style={{ position: 'absolute', top: 0, bottom: 0, left: l + '%', width: w + '%', background: 'var(--pri-soft)', borderLeft: '2px solid var(--pri)', borderRight: '2px solid var(--pri)' }} />)}
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', padding: '0 10px', gap: 3 }}>
              {Array.from({ length: 52 }).map((_, i) => <span key={i} style={{ flex: 1, height: (10 + (i * 7 % 32)) + 'px', background: 'rgba(255,255,255,.1)', borderRadius: 2 }} />)}
            </div>
          </div>
          <div className="rowx" style={{ marginTop: 10, gap: 8 }}>{['00:12', '01:04', '02:20', '03:48'].map(t => <span key={t} className="chip"><Icon name="clock" />{t}</span>)}</div>
        </div>
        <VStage ratio="9/16" dur="0:15" time="0:06 / 0:15" pos={40} subtitle="prévia exclusiva" logo />
      </div>
      <div className="stack">
        <Field label="Duração do teaser"><select className="inp"><option>15 segundos</option><option>30 segundos</option><option>60 segundos</option></select></Field>
        <Field label="Formato"><div className="checks"><Check on>9:16 vertical</Check><Check>1:1 quadrado</Check><Check>16:9 wide</Check></div></Field>
        <Field label="Incluir"><div className="rowx"><Check on>legenda</Check><Check on>logo</Check><Check on>fade in/out</Check></div></Field>
        {running && <div className="panel stack">
          <ProgressBar pct={42} tone="cy" label="Renderizando teaser" eta="≈ 50 s restantes" />
          <LogLines items={[{ s: 'done', t: '4 cenas selecionadas' }, { s: 'now', t: 'Cortando e montando…' }]} />
        </div>}
        <button className="btn pri block" onClick={() => setRunning(true)}><Icon name="scissors" />{running ? 'Gerando…' : 'Gerar teaser'}</button>
      </div>
    </div>
  </div>;
}

/* ── THUMBNAIL — capa por IA ── */
function ThumbnailApp() {
  const [sel, setSel] = React.useState(2);
  const [gen, setGen] = React.useState(false);
  return <div className="app">
    <AppHead icon="thumbnail" title="Thumbnail IA" desc="Gera a capa ideal a partir dos frames-chave + descrição dos performers, com título sobreposto."
      right={<Pill kind="violet" icon="sparkles">Vision IA</Pill>} />
    <div className="split">
      <div className="stack">
        <div className="sec cy"><Icon name="image" />Frames candidatos</div>
        <div className="thumbs">{['00:12', '01:04', '02:20', '03:11', '03:58', '04:10'].map((t, i) => <Thumb key={t} label={t} sel={i === sel} onClick={() => setSel(i)} />)}</div>
        <div className="sec mut" style={{ marginTop: 6 }}>Prévia da capa</div>
        <div className="vstage" style={{ aspectRatio: '16/9' }}>
          <div className="ph" />
          <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, top: 0, display: 'grid', placeItems: 'center', padding: 24 }}>
            <b style={{ fontFamily: 'var(--fh)', fontSize: 26, color: '#fff', textAlign: 'center', textShadow: '0 3px 12px #000, 0 0 4px #000', lineHeight: 1.1 }}>BASTIDORES DO ESTÚDIO</b>
          </div>
          <span className="pill pri" style={{ position: 'absolute', top: 12, left: 12 }}>HD</span>
        </div>
      </div>
      <div className="stack">
        <Field label="Título na capa"><input className="inp" defaultValue="Bastidores do estúdio — junho" /></Field>
        <Field label="Descrição dos performers (para IA)"><input className="inp" placeholder="Ex: morena 25 anos, corpo atlético, tatuagem no braço" /></Field>
        <Field label="Estilo da capa"><div className="checks"><Check on>Título grande</Check><Check>Selo "NOVO"</Check><Check on>Vinheta escura</Check><Check>Borda neon</Check></div></Field>
        <Field label="Posição do texto"><select className="inp"><option>Centro</option><option>Inferior</option><option>Superior</option></select></Field>
        {gen && <div className="panel"><ProgressBar pct={70} tone="violet" label="Gerando thumbnail (Vision)" eta="≈ 12 s restantes" /></div>}
        <div className="rowx" style={{ justifyContent: 'flex-end' }}>
          <button className="btn"><Icon name="download" />Baixar capa</button>
          <button className="btn pri" onClick={() => setGen(true)}><Icon name="sparkles" />Gerar com IA</button>
        </div>
      </div>
    </div>
  </div>;
}

Object.assign(window, { LegendaApp, LogoApp, TeaserApp, ThumbnailApp });
