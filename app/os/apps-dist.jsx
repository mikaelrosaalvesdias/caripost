/* MetaPorn OS — Operação & Distribuição: Telegram, Publicar, Calendário */

/* ── TELEGRAM — fila, grupos e disparos ── */
function TelegramApp() {
  const groups = [
    { n: 'VIP Premium 🔥', members: '12.4k', on: true },
    { n: 'Prévia Grátis', members: '38.2k', on: true },
    { n: 'Estúdio Oficial', members: '8.1k', on: false },
  ];
  const queue = [
    { t: 'Bastidores do estúdio — junho', g: 'VIP Premium', s: 'enviado', tone: 'good', time: '14:20' },
    { t: 'Teaser vertical 0:15', g: 'Prévia Grátis', s: 'enviando', tone: 'cy', time: 'agora' },
    { t: 'Sessão premium 05', g: 'VIP Premium', s: 'na fila · 18:00', tone: 'warn', time: '18:00' },
  ];
  return <div className="app">
    <AppHead icon="telegram" title="Telegram" desc="Fila de disparos, grupos e canais — envie posts e teasers direto para seus assinantes."
      right={<Pill kind="cy" dot>bot conectado</Pill>} />
    <div className="grid3">
      <div className="stat"><div className="sv">3</div><div className="sl">Grupos ativos</div></div>
      <div className="stat"><div className="sv">58.7k</div><div className="sl">Alcance total</div></div>
      <div className="stat"><div className="sv">2</div><div className="sl">Na fila hoje</div></div>
    </div>
    <div className="split">
      <div className="stack">
        <div className="sec mut"><Icon name="users" />Grupos &amp; canais</div>
        {groups.map(g => <div key={g.n} className="litem">
          <span className="li-ic"><Icon name="telegram" /></span>
          <div className="li-main"><b>{g.n}</b><small>{g.members} membros</small></div>
          <Switch on={g.on} />
        </div>)}
        <button className="btn"><Icon name="plus" />Adicionar grupo</button>
      </div>
      <div className="stack">
        <div className="sec mut"><Icon name="send" />Fila de disparos</div>
        {queue.map((q, i) => <div key={i} className="litem">
          <div className="li-ic"><Icon name="post" /></div>
          <div className="li-main"><b>{q.t}</b><small>→ {q.g}</small></div>
          <Pill kind={q.tone} dot>{q.s}</Pill>
        </div>)}
        <div className="panel stack">
          <Field label="Disparo rápido"><select className="inp"><option>Bastidores do estúdio — junho</option><option>Teaser vertical 0:15</option></select></Field>
          <div className="rowx"><Check on>VIP Premium</Check><Check>Prévia Grátis</Check></div>
          <button className="btn pri block"><Icon name="send" />Enviar agora</button>
        </div>
      </div>
    </div>
  </div>;
}

/* ── PUBLICAR — distribuição nas plataformas ── */
function PublisherApp() {
  const plats = [
    { n: 'XVideos', on: true, st: 'conectado', tone: 'good' },
    { n: 'Pornhub', on: true, st: 'conectado', tone: 'good' },
    { n: 'XNXX', on: false, st: 'token expirado', tone: 'warn' },
    { n: 'xHamster', on: false, st: 'desconectado', tone: '' },
  ];
  return <div className="app">
    <AppHead icon="broadcast" title="Publicação Automática" desc="Distribui o vídeo final nas plataformas selecionadas, com título, tags e thumbnail." />
    <div className="split">
      <div className="stack">
        <div className="sec cy">Vídeo a publicar</div>
        <div className="panel" style={{ padding: 0, overflow: 'hidden' }}><VStage dur="06:12" time="00:00 / 06:12" pos={0} logo /></div>
        <Field label="Título"><input className="inp" defaultValue="Bastidores do estúdio — edição especial de junho" /></Field>
        <Field label="Tags"><div className="rowx">{['estúdio', 'premium', 'junho', 'amador', 'hd'].map(t => <span key={t} className="chip tag">#{t}</span>)}</div></Field>
      </div>
      <div className="stack">
        <div className="sec mut">Plataformas de destino</div>
        {plats.map(p => <div key={p.n} className="litem">
          <span className="li-ic"><Icon name="globe" /></span>
          <div className="li-main"><b>{p.n}</b><small>{p.st}</small></div>
          {p.tone ? <Pill kind={p.tone} dot>{p.st}</Pill> : null}
          <Switch on={p.on} />
        </div>)}
        <div className="panel stack">
          <div className="rowx" style={{ justifyContent: 'space-between' }}><span style={{ fontSize: 13 }}>Publicar agora</span><Check on /></div>
          <div className="rowx" style={{ justifyContent: 'space-between' }}><span style={{ fontSize: 13 }}>Ou agendar</span><Check /></div>
          <button className="btn pri block"><Icon name="broadcast" />Publicar em 2 plataformas</button>
        </div>
      </div>
    </div>
  </div>;
}

/* ── CALENDÁRIO EDITORIAL ── */
function CalendarApp() {
  const days = [];
  for (let i = -0; i < 35; i++) days.push(i + 1 - 0);
  const [entries, setEntries] = React.useState([
    { t: 'Bastidores do estúdio', d: 'Hoje · 18:00', c: 'Criador', plat: 'XVideos', tone: 'warn', s: 'agendado' },
  ]);
  React.useEffect(() => {
    if (!window.mpApi) return;
    window.mpApi.listCalendar().then(r => {
      if (r.length) setEntries(r.map(e => ({
        t: e.title || 'Publicação',
        d: e.publish_at ? new Date(e.publish_at).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—',
        c: e.creator_name || e.creator_id || '—',
        plat: Array.isArray(e.publish_platforms) ? e.publish_platforms.join(' · ') : (e.publish_platforms || '—'),
        tone: e.status === 'published' ? 'good' : 'warn',
        s: e.status || 'agendado',
      })));
    }).catch(() => {});
  }, []);
  const events = { 2: 'cy', 8: 'pri', 12: 'cy', 15: 'pri', 19: 'cy', 24: 'pri', 27: 'cy' };
  return <div className="app">
    <AppHead icon="calendar" title="Calendário Editorial" desc="Programe publicações por criador e plataforma, com auto-agendamento inteligente."
      right={<div className="rowx"><button className="btn sm"><Icon name="sparkles" />Auto-Agendar</button><button className="btn pri sm"><Icon name="plus" />Agendar</button></div>} />
    <div className="split">
      <div className="panel">
        <div className="rowx" style={{ justifyContent: 'space-between', marginBottom: 14 }}>
          <button className="wbtn"><Icon name="arrowL" /></button>
          <b style={{ fontFamily: 'var(--fh)', fontSize: 16 }}>Junho 2026</b>
          <button className="wbtn"><Icon name="arrowR" /></button>
        </div>
        <div className="cal">
          {['S', 'T', 'Q', 'Q', 'S', 'S', 'D'].map((d, i) => <div key={i} className="dow">{d}</div>)}
          {days.map((d, i) => {
            const valid = d >= 1 && d <= 30;
            return <div key={i} className={'cell' + (valid ? '' : ' out') + (d === 2 ? ' today' : '')}>
              {valid ? d : (d < 1 ? 31 + d : d - 30)}
              {events[d] && <span className={'ev ' + (events[d] === 'pri' ? 'pri' : '')} />}
            </div>;
          })}
        </div>
        <div className="rowx" style={{ marginTop: 12, fontSize: 11.5, color: 'var(--muted)' }}>
          <span className="rowx" style={{ gap: 5 }}><span style={{ width: 9, height: 9, borderRadius: 3, background: 'var(--pri)' }} />publicado</span>
          <span className="rowx" style={{ gap: 5 }}><span style={{ width: 9, height: 9, borderRadius: 3, background: 'var(--cyan)' }} />agendado</span>
        </div>
      </div>
      <div className="stack">
        <div className="sec mut"><Icon name="clock" />Próximas publicações</div>
        {entries.slice(0,6).map((e, i) => <div key={i} className="litem">
          <span className="li-ic"><Icon name="post" /></span>
          <div className="li-main"><b>{e.t}</b><small>{e.c} · {e.d} · {e.plat}</small></div>
          <Pill kind={e.tone} dot>{e.s}</Pill>
        </div>)}
        {!entries.length && <div className="hint">Nenhuma publicação agendada.</div>}
        <div className="panel stack">
          <div className="rowx" style={{ justifyContent: 'space-between' }}><span style={{ fontSize: 13 }}>Avisar no Telegram ao publicar</span><Switch on /></div>
          <div className="rowx" style={{ justifyContent: 'space-between' }}><span style={{ fontSize: 13 }}>Notificação no app</span><Switch on /></div>
        </div>
      </div>
    </div>
  </div>;
}

Object.assign(window, { TelegramApp, PublisherApp, CalendarApp });
