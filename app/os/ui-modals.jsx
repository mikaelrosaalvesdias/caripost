/* ═══════════════════════════════════════════════════════════════
   Caripost OS — PATCH v1 · componentes canônicos de modal/loading
   Carregar DEPOIS de icons.jsx e ANTES de apps-*.jsx.

   Substitui, com a MESMA assinatura de props:
     • ProcessModal        (era escuro rgba(8,6,12,.86) + <style> injetado)
     • AnalyzeLoadingModal (era um 2º anel duplicado + <style> injetado)
   → agora ambos usam o anel claro canônico do os-patch.css.

   Adiciona, para trocar os modais ad-hoc de fundo preto:
     • Modal    — janela padrão (head/body/foot)
     • Confirm  — confirmação curta
     • Lightbox — visualizador de mídia (escuro: é vídeo/imagem)
   ═══════════════════════════════════════════════════════════════ */

/* ── util de tempo ── */
function mpFmtSec(s) {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60), ss = s % 60;
  return (m > 0 ? m + 'm ' : '') + String(ss).padStart(m > 0 ? 2 : 1, '0') + 's';
}
function mpFmtEta(ms) {
  const sec = Math.max(0, Math.ceil((ms || 0) / 1000));
  if (sec <= 0) return 'menos de 1s restante';
  if (sec < 60) return `${sec}s restantes`;
  const min = Math.floor(sec / 60), rest = sec % 60;
  if (min < 60) return rest ? `${min}min ${rest}s restantes` : `${min}min restantes`;
  const h = Math.floor(min / 60), m = min % 60;
  return m ? `${h}h ${m}min restantes` : `${h}h restantes`;
}
/* trava o scroll do body enquanto há overlay */
function mpUseLock(active) {
  React.useEffect(() => {
    if (!active) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [active]);
}
/* fecha no ESC */
function mpUseEsc(active, onClose) {
  React.useEffect(() => {
    if (!active || !onClose) return;
    const h = e => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', h);
    return () => document.removeEventListener('keydown', h);
  }, [active, onClose]);
}

/* ─────────────────────────────────────────────────────────────
   RingLoader — o anel canônico (usado por todos os loaders)
   ───────────────────────────────────────────────────────────── */
function RingLoader({ pct, phase, indeterminate }) {
  const p = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
  const isErr = phase === 'error', isDone = phase === 'done';
  if (isDone) {
    return <div className="mp-ring" style={{ '--pct': 100 }}>
      <div className="pct"><Icon name="check" style={{ width: 52, height: 52 }} /></div>
    </div>;
  }
  return <div className={'mp-ring' + (indeterminate && !isErr ? ' spin' : '')} style={{ '--pct': indeterminate ? 25 : p }}>
    <div className="pct">{isErr ? '!' : p + '%'}</div>
  </div>;
}

/* ─────────────────────────────────────────────────────────────
   ProcessModal — MESMA API de antes, agora no tema claro
   props: open, title, detail, pct, phase, onClose, onCancel, hideEta
   ───────────────────────────────────────────────────────────── */
function ProcessModal({ open, title, detail, pct, phase, onClose, onCancel, hideEta }) {
  const [elapsed, setElapsed] = React.useState(0);
  const startRef = React.useRef(null);
  React.useEffect(() => {
    if (!open) { startRef.current = null; setElapsed(0); return; }
    startRef.current = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 500);
    return () => clearInterval(id);
  }, [open]);
  mpUseLock(open);
  if (!open) return null;

  const p = Math.round(Math.max(0, Math.min(100, pct || 0)));
  const isErr = phase === 'error', isDone = phase === 'done';
  const eta = p >= 10 && p < 100 ? (elapsed / p) * (100 - p) : null;
  const cls = 'mp-load' + (isDone ? ' is-done' : '') + (isErr ? ' is-error' : '');

  return <div className={cls} role="status" aria-live="polite">
    <div className="mp-load-wrap">
      <RingLoader pct={p} phase={phase} indeterminate={!isDone && !isErr && p < 1} />
      <div className="mp-load-title">{isErr ? 'Falhou' : isDone ? 'Concluído' : (title || 'Processando…')}</div>
      <div className="mp-load-detail">{detail || ''}</div>
      {!isDone && !isErr && <>
        <div className="mp-load-track"><i style={{ width: p + '%' }} /></div>
        <div className="mp-load-times">
          <div className="t"><b>{mpFmtSec(elapsed)}</b><span>decorrido</span></div>
          {!hideEta && <div className="t"><b>{eta != null ? '~' + mpFmtSec(eta) : '—'}</b><span>restante</span></div>}
        </div>
      </>}
      <div className="mp-load-actions">
        {(isDone || isErr)
          ? <button className="btn pri" onClick={onClose}>Fechar</button>
          : onCancel && <button className="btn ghost" onClick={onCancel}>Cancelar</button>}
      </div>
    </div>
  </div>;
}

/* ─────────────────────────────────────────────────────────────
   AnalyzeLoadingModal — MESMA API de antes, agora canônico
   props: open, pct, detail, fileName, phase
   ───────────────────────────────────────────────────────────── */
function AnalyzeLoadingModal({ open, pct, detail, fileName, phase }) {
  const [elapsed, setElapsed] = React.useState(0);
  const startRef = React.useRef(0);
  React.useEffect(() => {
    if (!open) { startRef.current = 0; setElapsed(0); return; }
    startRef.current = Date.now();
    setElapsed(0);
    const id = setInterval(() => setElapsed(Date.now() - startRef.current), 500);
    return () => clearInterval(id);
  }, [open]);
  mpUseLock(open);
  if (!open) return null;

  const p = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
  const eta = p <= 1 ? 'calculando tempo restante'
    : p >= 99 ? 'finalizando…'
    : mpFmtEta(elapsed * (100 - p) / p);
  const cls = 'mp-load' + (phase === 'done' ? ' is-done' : '') + (phase === 'error' ? ' is-error' : '');

  return <div className={cls} role="status" aria-live="polite">
    <div className="mp-load-wrap">
      <RingLoader pct={p} phase={phase} indeterminate={p < 1 && phase !== 'error'} />
      <div className="mp-load-title">
        {phase === 'done' ? 'Análise concluída' : phase === 'error' ? 'Análise falhou' : 'Analisando vídeo'}
      </div>
      <div className="mp-load-detail">{detail || 'Preparando análise…'}</div>
      <div className="mp-load-eta">
        {phase === 'done' ? 'finalizado' : phase === 'error' ? 'verifique o erro e tente novamente' : eta}
      </div>
      <div className="mp-load-file">{fileName || 'video'}</div>
    </div>
  </div>;
}

/* ─────────────────────────────────────────────────────────────
   Modal — janela padrão do app (substitui os scrims preto inline)
   props: open, title, sub, icon, size ('sm'|''|'lg'|'xl'),
          onClose, foot, busy, children
   ───────────────────────────────────────────────────────────── */
function Modal({ open = true, title, sub, icon, size = '', onClose, foot, busy, children }) {
  mpUseLock(open);
  mpUseEsc(open && !busy, onClose);
  if (!open) return null;
  return <div className="mp-modal" onMouseDown={e => { if (e.target === e.currentTarget && !busy && onClose) onClose(); }}>
    <div className={'mp-modal-card' + (size ? ' ' + size : '')} role="dialog" aria-modal="true" aria-label={title || 'Janela'}>
      {(title || onClose) && <div className="mp-modal-head">
        {icon && <div className="mh-ic"><Icon name={icon} /></div>}
        <div className="mh-txt">
          {title && <h3>{title}</h3>}
          {sub && <div className="mh-sub">{sub}</div>}
        </div>
        {onClose && <button className="mp-modal-close" disabled={busy} onClick={onClose} aria-label="Fechar">
          <Icon name="x" />
        </button>}
      </div>}
      <div className="mp-modal-body">{children}</div>
      {foot && <div className="mp-modal-foot">{foot}</div>}
    </div>
  </div>;
}

/* ── Confirm — confirmação curta ── */
function Confirm({ open = true, title, message, confirmLabel = 'Confirmar', cancelLabel = 'Cancelar', busy, onConfirm, onClose }) {
  return <Modal open={open} size="sm" title={title} icon="help" onClose={onClose} busy={busy}
    foot={<>
      <button className="btn ghost" disabled={busy} onClick={onClose}>{cancelLabel}</button>
      <button className="btn pri" disabled={busy} onClick={onConfirm}>{busy ? 'Aguarde…' : confirmLabel}</button>
    </>}>
    <div className="hint" style={{ fontSize: 13.5 }}>{message}</div>
  </Modal>;
}

/* ─────────────────────────────────────────────────────────────
   Lightbox — visualizador de mídia (escuro de propósito)
   props: open, src, kind ('image'|'video'), name, onClose, actions
   ───────────────────────────────────────────────────────────── */
function Lightbox({ open = true, src, kind = 'image', name, onClose, actions }) {
  mpUseLock(open);
  mpUseEsc(open, onClose);
  if (!open) return null;
  return <div className="mp-lightbox" onMouseDown={e => { if (e.target === e.currentTarget && onClose) onClose(); }}>
    <div className="mp-lightbox-inner">
      {onClose && <button className="mp-lightbox-close" onClick={onClose} aria-label="Fechar"><Icon name="x" /></button>}
      {kind === 'video'
        ? <video src={src} controls autoPlay playsInline />
        : <img src={src} alt={name || ''} />}
      <div className="mp-lightbox-bar">
        <span className="lb-name">{name || ''}</span>
        {actions}
      </div>
    </div>
  </div>;
}

/* ── EmptyState / SkeletonRows — para trocar "Carregando…" cru ── */
function EmptyState({ icon = 'layers', title, children, action }) {
  return <div className="empty">
    <div className="em-ic"><Icon name={icon} /></div>
    {title && <b>{title}</b>}
    {children && <div className="hint">{children}</div>}
    {action}
  </div>;
}
function SkeletonRows({ rows = 3 }) {
  return <div className="stack" aria-hidden="true">
    {Array.from({ length: rows }).map((_, i) => <div className="sk-row" key={i}>
      <div className="sk-av" />
      <div className="sk-main">
        <div className="sk-line" style={{ width: '46%' }} />
        <div className="sk-line" style={{ width: '72%', height: 9 }} />
      </div>
    </div>)}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════
   FLUXO DE CRIAÇÃO — componentes canônicos
   ═══════════════════════════════════════════════════════════════ */

/* ── Callout — substitui os blocos #3a2f10/#ffd479 do tema escuro ── */
function Callout({ kind = '', icon, children }) {
  const ic = icon || (kind === 'danger' ? 'x' : kind === 'good' ? 'check' : kind === 'warn' ? 'warning' : 'help');
  return <div className={'callout' + (kind ? ' ' + kind : '')}>
    <span className="co-ic"><Icon name={ic} /></span>
    <div>{children}</div>
  </div>;
}

/* ── Segmented — substitui toggles com ◉ / ○ ── */
function Segmented({ value, onChange, options }) {
  return <div className="segmented" role="tablist">
    {options.map(([v, label]) =>
      <button key={v} role="tab" aria-selected={value === v}
        className={value === v ? 'on' : ''} onClick={() => onChange(v)}>{label}</button>)}
  </div>;
}

/* ─────────────────────────────────────────────────────────────
   CostConfirm — confirmação de GASTO REAL
   Substitui window.confirm() em: geração de vídeo e de imagens.
   props: open, title, kind ('money'|'credits'), amount, unit,
          lines[{k,v}], note, confirmLabel, onConfirm, onClose, busy
   ───────────────────────────────────────────────────────────── */
function CostConfirm({ open = true, title = 'Confirmar geração', kind = 'money', amount, unit,
                       lines = [], note, confirmLabel, onConfirm, onClose, busy }) {
  const isCredits = kind === 'credits';
  return <Modal open={open} size="sm" onClose={onClose} busy={busy}
    foot={<>
      <button className="btn ghost" disabled={busy} onClick={onClose}>Cancelar</button>
      <button className="btn pri" disabled={busy} onClick={onConfirm}>
        <Icon name="bolt" />{busy ? 'Gerando…' : (confirmLabel || 'Confirmar e gerar')}
      </button>
    </>}>
    <div className="cost">
      <div className="cost-top">
        <div className="c-ic"><Icon name={isCredits ? 'sparkles' : 'dollar'} /></div>
        <div className="c-txt">
          <b>{title}</b>
          <small>{isCredits ? 'consome créditos da sua conta' : 'consome saldo real'}</small>
        </div>
        <div className="c-val">
          <b>{amount}</b>
          <span>{unit || (isCredits ? 'créditos' : 'estimado')}</span>
        </div>
      </div>
      <div className="cost-body">
        {!!lines.length && <div className="cost-lines">
          {lines.map((l, i) => <div className="cl" key={i}>
            <span className="k">{l.k}</span><span className="v">{l.v}</span>
          </div>)}
        </div>}
        <Callout kind="warn" icon="warning">
          Esta ação <b>gasta {isCredits ? 'créditos' : 'dinheiro'} de verdade</b> e não pode ser desfeita.
          {note ? <> {note}</> : null}
        </Callout>
      </div>
    </div>
  </Modal>;
}

/* ── OfferPick — seleção de produto/oferta do catálogo (Briefing) ── */
function OfferPick({ product, checked, onToggle }) {
  const caps = [
    ['logo', 'logo', product.has_logo],
    ['image', 'foto real', product.has_photo],
    ['doc', 'base', product.has_knowledge],
  ];
  return <label className={'offer' + (checked ? ' on' : '')}>
    <input type="checkbox" checked={!!checked} onChange={e => onToggle(product, e.target.checked)} />
    <div className="of-main">
      <b>{product.name}</b>
      <div className="of-caps">
        <span className="of-cap">{product.category || 'oferta'}</span>
        {caps.map(([ic, label, has]) => has
          ? <span className="of-cap has" key={label}><Icon name={ic} />{label}</span>
          : null)}
      </div>
    </div>
  </label>;
}

/* ─────────────────────────────────────────────────────────────
   ReviewCard — card da fila de aprovação
   props: post, onApprove, onReject, onRegen, onDelete, onOpen, busy
   ───────────────────────────────────────────────────────────── */
function ReviewCard({ post, onApprove, onRegen, onDelete, onOpen, busy }) {
  const d = post.review_decision;
  const state = d === 'rejected' ? 'rejected' : d === 'changes' ? 'changes'
    : (post.status === 'APPROVED' || post.status === 'SCHEDULED') ? 'approved' : 'pending';
  const stateLabel = { pending: 'aguardando', changes: 'com ressalvas', rejected: 'reprovado', approved: 'aprovado' }[state];
  const stateKind = { pending: 'warn', changes: 'cy', rejected: 'pri', approved: 'good' }[state];
  return <div className={'rev ' + state}>
    <div className="rev-rail" />
    <div className="rev-in">
      {post.media_url && <div className="rev-thumb" onClick={() => onOpen && onOpen(post)}>
        <img loading="lazy" decoding="async" src={post.media_url} alt="" />
        <div className="zoom"><Icon name="eye" /></div>
      </div>}
      <div className="rev-body">
        <div className="rev-head">
          <b>{post.title || 'Post'}</b>
          <Pill kind={stateKind} dot>{stateLabel}</Pill>
          {(post.networks || []).map(n => <span className="chip" key={n}>{n}</span>)}
        </div>
        {d === 'changes' && <Callout kind="warn" icon="warning">
          Cliente aprovou <b>com ressalvas</b>: {post.review_comment}
        </Callout>}
        {d === 'rejected' && <Callout kind="danger" icon="x">
          Cliente <b>reprovou</b>: {post.review_comment}
        </Callout>}
        {post.copy && <div className="rev-copy clip">{post.copy}</div>}
        <div className="rev-acts">
          {(d === 'changes' || d === 'rejected') && onRegen &&
            <button className="btn sm pri" disabled={busy} onClick={() => onRegen(post)}>
              <Icon name="bolt" />Regenerar com o feedback</button>}
          {state !== 'approved' && onApprove &&
            <button className="btn sm" disabled={busy} onClick={() => onApprove(post)}>
              <Icon name="check" />Aprovar</button>}
          {onOpen && <button className="btn sm ghost" onClick={() => onOpen(post)}><Icon name="eye" />Ver</button>}
          {onDelete && <button className="btn sm ghost" disabled={busy} onClick={() => onDelete(post)}>
            <Icon name="trash" /></button>}
        </div>
      </div>
    </div>
  </div>;
}

/* ── ArtCard — arte gerada na Criação ── */
function ArtCard({ src, label, sub, badges, selected, onOpen, actions }) {
  return <div className={'art' + (selected ? ' sel' : '')}>
    <div className="art-img" onClick={onOpen}>
      {src ? <img loading="lazy" decoding="async" src={src} alt={label || ''} /> : null}
      {actions && <div className="ov-btns">{actions}</div>}
    </div>
    <div className="art-meta">
      <b>{label}</b>
      {sub && <div className="hint sm" style={{ marginTop: 2 }}>{sub}</div>}
      {!!(badges || []).length && <div className="row">{badges}</div>}
    </div>
  </div>;
}

/* ── FlowHead — cabeçalho de cada passo do fluxo ── */
function FlowHead({ icon, title, sub, right }) {
  return <div className="flow-head">
    <div className="fh-ic"><Icon name={icon} /></div>
    <div className="fh-txt">
      <h3>{title}</h3>
      {sub && <div className="fh-sub">{sub}</div>}
    </div>
    {right}
  </div>;
}

/* ─────────────────────────────────────────────────────────────
   IdeaInput — campo onde o operador escreve A IDEIA em texto livre
   e a IA transforma em briefing estruturado.
   props: value, onChange, onGenerate, busy, seeds[], max, label, sub
   ───────────────────────────────────────────────────────────── */
function IdeaInput({ value = '', onChange, onGenerate, busy, seeds = [], max = 600,
                     label = 'Qual é a ideia?', sub = 'Escreva com suas palavras — a IA transforma em briefing.' }) {
  const ref = React.useRef(null);
  function seed(t) {
    const next = value ? value.replace(/\s*$/, '') + ' ' + t : t;
    onChange && onChange(next.slice(0, max));
    if (ref.current) ref.current.focus();
  }
  return <div className="idea">
    <div className="idea-top">
      <div className="i-ic"><Icon name="sparkles" /></div>
      <div className="i-txt"><b>{label}</b><small>{sub}</small></div>
    </div>
    <div className="idea-body">
      <textarea ref={ref} className="inp" maxLength={max} value={value} disabled={busy}
        onChange={e => onChange && onChange(e.target.value)}
        placeholder="Ex.: quero uma campanha mostrando que o Zapping Full sai de graça no plano de 700 MB. Tom leve, focado em família. Fechar com CTA de assinar pelo site." />
      {!!seeds.length && !value && <div className="idea-seeds">
        {seeds.map(s => <button type="button" key={s} className="idea-seed" onClick={() => seed(s)}>+ {s}</button>)}
      </div>}
      <div className="idea-foot">
        <button className="btn pri" disabled={busy || !value.trim()} onClick={onGenerate}>
          <Icon name="sparkles" />{busy ? 'Escrevendo…' : 'Transformar em briefing'}
        </button>
        {value && <button className="btn ghost sm" disabled={busy} onClick={() => onChange && onChange('')}>Limpar</button>}
        <span className="cnt">{value.length}/{max}</span>
      </div>
    </div>
  </div>;
}

Object.assign(window, {
  RingLoader, ProcessModal, AnalyzeLoadingModal,
  Modal, Confirm, Lightbox, EmptyState, SkeletonRows,
  Callout, Segmented, CostConfirm, OfferPick, ReviewCard, ArtCard, FlowHead, IdeaInput,
  mpFmtSec, mpFmtEta,
});

/* ═══════════════════════════════════════════════════════════════
   DIÁLOGOS IMPERATIVOS — substituem alert() / confirm() / prompt()
   nativos nos pontos que ainda chamavam o navegador.
   Mesma cara do <Modal>/<Confirm>; devolvem Promise.
   ═══════════════════════════════════════════════════════════════ */

function _mpDialogHost() {
  let el = document.getElementById('mp-dialog-root');
  if (!el) { el = document.createElement('div'); el.id = 'mp-dialog-root'; document.body.appendChild(el); }
  return el;
}

/* monta um modal avulso e resolve a Promise quando ele fecha */
function _mpOpenDialog(render) {
  return new Promise(resolve => {
    const host = document.createElement('div');
    _mpDialogHost().appendChild(host);
    const root = ReactDOM.createRoot(host);
    let done = false;
    const close = value => {
      if (done) return;
      done = true;
      resolve(value);
      setTimeout(() => { try { root.unmount(); } catch (e) {} host.remove(); }, 0);
    };
    root.render(render(close));
  });
}

/* aviso simples — no lugar de alert() */
function mpAlert(message, opts) {
  const o = opts || {};
  const kind = o.kind || (/^(erro|falha|falhou)/i.test(String(message)) ? 'danger' : '');
  const title = o.title || (kind === 'danger' ? 'Não deu certo' : 'Aviso');
  return _mpOpenDialog(close => React.createElement(Modal, {
    size: 'sm', title, icon: kind === 'danger' ? 'warning' : 'help', onClose: () => close(undefined),
    foot: React.createElement('button', { className: 'btn pri', onClick: () => close(undefined) }, 'Entendi'),
  }, React.createElement(Callout, { kind: kind || 'info' }, String(message))));
}

/* confirmação — no lugar de window.confirm(); resolve true/false */
function mpConfirm(message, opts) {
  const o = opts || {};
  return _mpOpenDialog(close => React.createElement(Confirm, {
    title: o.title || 'Confirmar',
    message: String(message),
    confirmLabel: o.confirmLabel || 'Confirmar',
    cancelLabel: o.cancelLabel || 'Cancelar',
    onConfirm: () => close(true),
    onClose: () => close(false),
  }));
}

/* campo de texto — no lugar de prompt(); resolve string ou null */
function MpPromptBody({ label, initial, placeholder, type, onDone }) {
  const [v, setV] = React.useState(initial || '');
  return React.createElement(Modal, {
    size: 'sm', title: label || 'Informe o valor', icon: 'pen', onClose: () => onDone(null),
    foot: React.createElement(React.Fragment, null,
      React.createElement('button', { className: 'btn ghost', onClick: () => onDone(null) }, 'Cancelar'),
      React.createElement('button', { className: 'btn pri', disabled: !v.trim(), onClick: () => onDone(v) }, 'Confirmar')),
  }, React.createElement(Field, { label: label || 'Valor' },
    React.createElement('input', {
      className: 'inp', autoFocus: true, type: type || 'text', value: v, placeholder: placeholder || '',
      onChange: e => setV(e.target.value),
      onKeyDown: e => { if (e.key === 'Enter' && v.trim()) onDone(v); },
    })));
}

function mpPrompt(label, initial, opts) {
  const o = opts || {};
  return _mpOpenDialog(close => React.createElement(MpPromptBody, {
    label, initial, placeholder: o.placeholder, type: o.type, onDone: close,
  }));
}

Object.assign(window, { mpAlert, mpConfirm, mpPrompt });
