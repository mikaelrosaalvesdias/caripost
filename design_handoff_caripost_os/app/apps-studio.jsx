/* MetaPorn OS — Estúdio: AutoEditor, Video Enhancer, Criação, Referência */

/* collapsible card section (mimics real <details class=cardSub>) */
function Acc({ title, open, children }) {
  const [o, setO] = React.useState(open);
  return <div className="acc">
    <button className="acc-h" onClick={() => setO(!o)}><Icon name="chevR" style={{ transform: o ? 'rotate(90deg)' : 'none', width: 13, height: 13 }} />{title}</button>
    {o && <div className="acc-b">{children}</div>}
  </div>;
}

/* ── AUTOEDITOR — cortes automáticos com IA (o núcleo) ── */
function AutoEditorApp() {
  const [trans, setTrans] = React.useState('smart');
  const [running, setRunning] = React.useState(false);
  const [audioNorm, setAudioNorm] = React.useState(true);
  const [audioDen, setAudioDen] = React.useState(true);
  const scenes = [
    { i: 1, src: 'v0', t: '00:12 → 00:38', d: '26s', rel: 0.91 },
    { i: 2, src: 'v1', t: '01:04 → 01:31', d: '27s', rel: 0.84 },
    { i: 3, src: 'v0', t: '02:20 → 02:51', d: '31s', rel: 0.88 },
    { i: 4, src: 'v2', t: '03:11 → 03:40', d: '29s', rel: 0.79 },
  ];
  return <div className="app">
    <AppHead icon="autoeditor" title="AutoEditor" desc="Multi-fonte → Grok Vision detecta as melhores cenas, corta, aplica transições e monta o vídeo final."
      right={<Pill kind="violet" icon="sparkles">Grok Vision</Pill>} />
    <div className="split">
      {/* CONFIG */}
      <div className="stack">
        <div className="sec">Configuração</div>
        <Acc title="Vídeo Fonte" open>
          <div className="rowx"><button className="btn sm"><Icon name="media" />Selecionar do servidor</button><span style={{ color: 'var(--muted)', fontSize: 12 }}>ou</span><button className="btn sm"><Icon name="upload" />Fazer upload</button></div>
          <div className="stack" style={{ marginTop: 10, gap: 6 }}>
            {['clipe_estudio_2406.mp4', 'sessao_premium_05.mp4', 'colab_estudioX.mp4'].map((v, i) => <div key={v} className="litem" style={{ padding: '9px 12px' }}>
              <span className="chip" style={{ fontFamily: 'var(--fm)', fontSize: 11 }}>v{i}</span>
              <div className="li-main"><b style={{ fontSize: 12.5 }}>{v}</b></div>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>{['1080p', '4K', '4K'][i]}</span>
            </div>)}
          </div>
          <div className="hint" style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>fontes: <b style={{ color: 'var(--text2)' }}>3 vídeos</b> · 39 min total</div>
        </Acc>
        <Acc title="Quantidade de Cenas" open>
          <Field label="Máx. cenas no corte"><input className="inp" type="number" defaultValue="60" /></Field>
          <div className="hint" style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>A IA seleciona automaticamente as melhores cenas por qualidade. Sem meta de duração.</div>
        </Acc>
        <Acc title="Transições" open>
          <Field label="Modo">
            <select className="inp" value={trans} onChange={e => setTrans(e.target.value)}>
              <option value="smart">Smart (detecta ponto natural)</option>
              <option value="always_crossfade">Sempre crossfade</option>
              <option value="none">Corte seco (sem transição)</option>
            </select>
          </Field>
          {trans !== 'none' && <div className="grid3" style={{ marginTop: 10 }}>
            <Field label="Crossfade vídeo (s)"><input className="inp" type="number" defaultValue="0.5" step="0.1" /></Field>
            <Field label="Crossfade áudio (s)"><input className="inp" type="number" defaultValue="0.3" step="0.1" /></Field>
            <Field label="Tipo visual"><select className="inp"><option>Fade</option><option>Dissolve</option><option>Wipe →</option><option>Slide →</option></select></Field>
          </div>}
          {trans === 'smart' && <Field label="Tolerância corte natural (s)"><input className="inp" type="number" defaultValue="1.5" step="0.5" /></Field>}
        </Acc>
        <Acc title="Qualidade de Saída">
          <div className="grid3">
            <Field label="CRF"><select className="inp"><option>Alta (18)</option><option selected>Média (23)</option><option>Baixa (28)</option></select></Field>
            <Field label="Resolução"><select className="inp"><option>4K</option><option selected>1080p</option><option>720p</option></select></Field>
            <Field label="FPS"><select className="inp"><option>60</option><option selected>30</option><option>24</option></select></Field>
          </div>
        </Acc>
        <Acc title="Áudio">
          <div className="rowx">
            <button className={'btn sm' + (audioNorm ? ' pri' : ' ghost')} onClick={() => setAudioNorm(!audioNorm)}>Normalizar volume</button>
            <button className={'btn sm' + (audioDen ? ' pri' : ' ghost')} onClick={() => setAudioDen(!audioDen)}>Remover ruído</button>
          </div>
        </Acc>
        <Acc title="Prompt do Grok ✎" open>
          <div className="hint" style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 8 }}>Instruções de seleção de cenas. Variáveis: <code style={{ color: 'var(--warn)' }}>{'{n_sources}'}</code> <code style={{ color: 'var(--warn)' }}>{'{n_sources_minus1}'}</code></div>
          <textarea className="inp" rows="5" style={{ fontFamily: 'var(--fm)', fontSize: 11.5 }} defaultValue={"Você é editor de conteúdo adulto. Selecione as melhores cenas entre {n_sources} vídeos (índices 0–{n_sources_minus1}). Priorize ação contínua, evite equipamento/bastidores. Garanta representação de todos os sources."} />
          <div className="rowx" style={{ marginTop: 8 }}><button className="btn sm pri"><Icon name="check" />Salvar prompt</button><button className="btn sm ghost"><Icon name="refresh" />Resetar padrão</button></div>
        </Acc>
        <Acc title="Criador (opcional)">
          <Field label="Criador"><select className="inp"><option>Nenhum (uso interno)</option><option>Raposinha</option><option>Ana Estúdio</option></select></Field>
          <Field label="Título (dica para a IA)"><input className="inp" placeholder="Ex: Raposinha Compilação Anal" /></Field>
          <div className="rowx" style={{ marginTop: 8 }}><button className="btn sm ghost">Excluir original após sucesso</button></div>
        </Acc>
        <div className="rowx" data-tour="ae-start">
          <button className="btn pri" onClick={() => setRunning(true)}><Icon name="autoeditor" />Iniciar AutoEditor</button>
          <button className="btn ghost"><Icon name="refresh" />Atualizar jobs</button>
        </div>
        {running && <div className="panel"><ProgressBar pct={31} tone="violet" label="Vision Analysis (Grok)" eta="etapa 2/14 · ≈ 1 h 40 min restantes (11 vídeos 4K)" /></div>}
      </div>

      {/* RESULTADO — BIG video */}
      <div className="stack">
        <div className="sec">Resultado</div>
        <VStage dur="06:12" time="02:18 / 06:12" pos={37} logo subtitle="" />
        <div className="hint" style={{ fontSize: 12.5, color: 'var(--text2)' }}>14 cenas · 1080p · 30fps · 06:12 · timelapse opener 10s · 2 crossfades</div>
        <div className="rowx">
          <button className="btn pri"><Icon name="download" />Download</button>
          <button className="btn"><Icon name="copy" />Copiar key</button>
          <button className="btn" data-tour="ae-recut"><Icon name="recut" />Re-cut</button>
        </div>
        <div className="sec mut" style={{ marginTop: 4 }}>Cenas selecionadas</div>
        <div className="stack" style={{ gap: 6 }}>
          {scenes.map(s => <div key={s.i} className="litem" style={{ padding: '10px 12px' }}>
            <span className="chip" style={{ fontFamily: 'var(--fm)', fontSize: 11 }}>#{s.i} · {s.src}</span>
            <div className="li-main"><b style={{ fontSize: 12.5, fontFamily: 'var(--fm)' }}>{s.t}</b><small>{s.d}</small></div>
            <Pill kind="violet" dot>rel {s.rel}</Pill>
          </div>)}
        </div>
      </div>
    </div>
  </div>;
}

/* ── VIDEO ENHANCER — upscale com IA ── */
function EnhancerApp() {
  const [running, setRunning] = React.useState(false);
  return <div className="app">
    <AppHead icon="enhance" title="Video Enhancer" desc="Upscale de qualidade com IA (Video2X · RealESRGAN). Melhora vídeos antigos ou de baixa resolução."
      right={<Pill kind="cy" icon="sparkles">RealESRGAN</Pill>} />
    <div className="split">
      <div className="stack">
        <div className="sec cy">Melhoria de Qualidade</div>
        <Acc title="Vídeo de Entrada" open>
          <div className="rowx"><button className="btn sm"><Icon name="media" />Selecionar do servidor</button><span style={{ color: 'var(--muted)', fontSize: 12 }}>ou</span><button className="btn sm"><Icon name="upload" />Fazer upload</button></div>
          <div className="litem" style={{ marginTop: 10 }}><span className="li-ic"><Icon name="media" /></span><div className="li-main"><b>bastidores_2019.mp4</b><small>480p · 06:30 · selecionado</small></div></div>
        </Acc>
        <Acc title="Resolução de Saída" open>
          <div className="checks">
            <Check on>720p — escala 2× (~2GB VRAM)</Check>
            <Check>1080p — escala 4× (~4GB VRAM)</Check>
          </div>
          <div className="hint" style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>Quanto maior a resolução, maior o tempo de processamento.</div>
        </Acc>
        {running && <div className="panel stack">
          <ProgressBar pct={46} tone="cy" label="Processando frames" eta="≈ 8 min restantes · frame 4.120 / 9.000" />
          <LogLines items={[{ s: 'done', t: 'Modelo RealESRGAN carregado' }, { s: 'done', t: 'Extraindo frames (480p)' }, { s: 'now', t: 'Upscaling 2× via Video2X…' }]} />
        </div>}
        <button className="btn pri block" onClick={() => setRunning(true)}><Icon name="enhance" />{running ? 'Melhorando…' : 'Melhorar Vídeo'}</button>
      </div>
      <div className="stack">
        <div className="sec mut">Antes / Depois</div>
        <div className="grid2" style={{ gap: 12 }}>
          <div><Media cap="480p original" play={false} /><div className="hint" style={{ textAlign: 'center', fontSize: 11.5, color: 'var(--muted)', marginTop: 6 }}>entrada</div></div>
          <div><Media cap="1080p · 4×" play={false} /><div className="hint" style={{ textAlign: 'center', fontSize: 11.5, color: 'var(--good)', marginTop: 6 }}>melhorado</div></div>
        </div>
        <div className="kv">
          <div className="row"><span className="k">Modelo</span><span className="v mono">RealESRGAN x4plus</span></div>
          <div className="row"><span className="k">Entrada</span><span className="v mono">854×480</span></div>
          <div className="row"><span className="k">Saída</span><span className="v mono">1920×1080</span></div>
        </div>
      </div>
    </div>
  </div>;
}

/* ── CRIAÇÃO — montagem de posts e teaser ── */
function CriacaoApp() {
  const [pos, setPos] = React.useState('br');
  return <div className="app" style={{ padding: 0 }}>
    <div style={{ padding: '22px 22px 0' }}>
      <AppHead icon="post" title="Criação de Posts" desc="Monta o post final: capa, título, descrição, tags, logo e teaser — pronto para publicar." />
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', borderTop: '1px solid var(--line)' }}>
      <div style={{ borderRight: '1px solid var(--line)', padding: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div className="sec mut" style={{ marginBottom: 2 }}>Runs</div>
        {[0, 1, 2].map(i => <button key={i} className="panel" style={{ padding: 8, textAlign: 'left', borderColor: i === 0 ? 'var(--pri-line)' : undefined }}>
          <div style={{ aspectRatio: '16/9', borderRadius: 7, background: 'linear-gradient(135deg,#16161f,#0c0c14)', marginBottom: 6 }} />
          <div style={{ fontFamily: 'var(--fm)', fontSize: 11, color: 'var(--muted)' }}>run_8f2a4{i}</div>
        </button>)}
      </div>
      <div className="split" style={{ padding: 20 }}>
        <div className="stack">
          <div className="sec cy">Prévia do post</div>
          <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
            <VStage dur="04:18" time="00:00 / 04:18" pos={0} logo>
              <span className="pill pri" style={{ position: 'absolute', top: 12, left: 12 }}>NOVO</span>
            </VStage>
            <div style={{ padding: 16 }}>
              <b style={{ fontFamily: 'var(--fh)', fontSize: 16 }}>Bastidores do estúdio — edição especial de junho</b>
              <p style={{ fontSize: 13, color: 'var(--text2)', margin: '8px 0 12px', lineHeight: 1.5 }}>Conteúdo exclusivo gravado essa semana. Qualidade premium com legenda e marca d'água.</p>
              <div className="rowx">{['estúdio', 'premium', 'junho', 'exclusivo'].map(t => <span key={t} className="chip tag">#{t}</span>)}</div>
            </div>
          </div>
        </div>
        <div className="stack">
          <Field label="Escolher capa"><div className="thumbs">{['00:12', '01:04', '02:20', '03:58'].map((t, i) => <Thumb key={t} label={t} sel={i === 1} />)}</div></Field>
          <Field label="Título"><input className="inp" defaultValue="Bastidores do estúdio — edição especial de junho" /></Field>
          <Field label="Descrição"><textarea className="inp" rows="3" defaultValue="Conteúdo exclusivo gravado essa semana. Qualidade premium com legenda e marca d'água." /></Field>
          <Field label="Logo / marca d'água — posição">
            <div className="checks">{[['tl', 'Sup. esq.'], ['tr', 'Sup. dir.'], ['bl', 'Inf. esq.'], ['br', 'Inf. dir.']].map(([k, l]) => <Check key={k} on={pos === k} onClick={() => setPos(k)}>{l}</Check>)}</div>
          </Field>
          <div className="rowx" style={{ justifyContent: 'flex-end' }}><button className="btn"><Icon name="scissors" />Gerar teaser</button><button className="btn pri"><Icon name="check" />Salvar post</button></div>
        </div>
      </div>
    </div>
  </div>;
}

/* ── REFERÊNCIA — pesquisa XVideos ── */
function ReferenciaApp() {
  const cards = [
    { t: 'Bastidores estúdio amador completo HD', v: '1.2M', l: '24k', d: '12:40', tags: 'amador · estúdio' },
    { t: 'Compilação premium junho 2026', v: '842k', l: '18k', d: '08:15', tags: 'compilação · premium' },
    { t: 'Casal brasileiro estúdio profissional', v: '2.1M', l: '41k', d: '15:22', tags: 'casal · brasil' },
    { t: 'Sessão exclusiva HD legendada', v: '634k', l: '12k', d: '06:48', tags: 'exclusivo · hd' },
    { t: 'Colab estúdios — edição especial', v: '1.8M', l: '33k', d: '19:05', tags: 'colab · estúdio' },
    { t: 'Top trending amador semana', v: '3.4M', l: '58k', d: '11:30', tags: 'trending · amador' },
  ];
  return <div className="app">
    <AppHead icon="refs" title="Referência XVideos" desc="Pesquisa e benchmarking — encontre conteúdos similares para calibrar título, tags e edição."
      right={<button className="btn pri sm"><Icon name="search" />Pesquisar</button>} />
    <div className="panel">
      <div className="grid3">
        <Field label="Busca / atriz"><input className="inp" placeholder="Mônica Matos, estúdio…" /></Field>
        <Field label="Categoria"><input className="inp" placeholder="Amateur, MILF…" /></Field>
        <Field label="Duração"><select className="inp"><option>Qualquer</option><option>Curto (1–3 min)</option><option>Médio (3–10 min)</option><option>Longo (10–20 min)</option></select></Field>
      </div>
      <div className="rowx" style={{ marginTop: 12 }}>
        <span className="hint" style={{ fontSize: 12, color: 'var(--muted)' }}>Sites:</span>
        <Check on>Xvideos</Check><Check>Pornhub</Check><Check>XNXX</Check>
      </div>
    </div>
    <div className="thumbs" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(240px,1fr))', gap: 14 }}>
      {cards.map((c, i) => <div key={i} className="panel" style={{ padding: 0, overflow: 'hidden' }}>
        <Media dur={c.d} cap={null} play />
        <div style={{ padding: 12 }}>
          <b style={{ fontSize: 12.5, display: 'block', lineHeight: 1.4, minHeight: 34 }}>{c.t}</b>
          <div className="rowx" style={{ justifyContent: 'space-between', marginTop: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}><Icon name="eye" style={{ width: 12, height: 12, verticalAlign: '-2px' }} /> {c.v} · ♥ {c.l}</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{c.tags}</div>
        </div>
      </div>)}
    </div>
  </div>;
}

Object.assign(window, { Acc, AutoEditorApp, EnhancerApp, CriacaoApp, ReferenciaApp });
