/* ═══════════════════════════════════════════════════════════════
   Caripost OS — PATCH v2 · componentes do Cadastro e do app Criação
   Carregar DEPOIS de ui-modals.jsx e ANTES de apps-clientes.jsx.

   Nada aqui altera comportamento, rota de API ou nome de campo —
   é só apresentação. Reutiliza o kit do v1 (Modal, Callout, Pill…).
   ═══════════════════════════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════════════════
   A. SEÇÕES DO CADASTRO — as 13 abas viram 5 grupos nomeados
   Mesmas chaves de `tab` já usadas em CompanyDetail: nada de
   renomear estado nem componente.
   ═══════════════════════════════════════════════════════════════ */
const CLI_SECTIONS = [
  ['Essencial para a IA', [
    ['geral', 'Dados Gerais', 'doc', true],
    ['visual', 'Identidade Visual', 'image', true],
    ['voz', 'Voz & Persona', 'mic', true],
  ]],
  ['Oferta', [
    ['produtos', 'Produtos & Serviços', 'layers', true],
    ['concorrentes', 'Concorrentes', 'radar', false],
  ]],
  ['Produção', [
    ['criacao', 'Criação & Prompts', 'sparkles', false],
    ['video', 'Vídeo', 'teaser', false],
    ['gerar', 'Gerar Conteúdo', 'bolt', false],
  ]],
  ['Relacionamento', [
    ['fluxo', 'Fluxo', 'flow', false],
    ['influencers', 'Influencers', 'star', false],
    ['events', 'Eventos', 'calendar', false],
  ]],
  ['Operação', [
    ['conexoes', 'Conexões', 'link', false],
    ['acesso', 'Acesso & Funções', 'key', false],
  ]],
];

/* monta os grupos conforme o estágio, mantendo a MESMA lista de
   abas que CompanyDetail já calcula (prospecto = 8 seções) */
function cliSectionsFor(allowedKeys, labelOverrides) {
  const allowed = new Set(allowedKeys);
  const over = labelOverrides || {};
  return CLI_SECTIONS
    .map(([group, items]) => [group, items.filter(([k]) => allowed.has(k)).map(it =>
      over[it[0]] ? [it[0], over[it[0]], it[2], it[3]] : it)])
    .filter(([, items]) => items.length);
}

/* ═══════════════════════════════════════════════════════════════
   B. COMPLETUDE DA MARCA — o que falta para gerar conteúdo
   Só LÊ os campos que já existem (brand_kit, references, products).
   ═══════════════════════════════════════════════════════════════ */
function computeBrandReadiness(company, products, opts) {
  const c = company || {};
  const bk = c.brand_kit || {};
  const extras = bk.extras || {};
  const colors = bk.colors || {};
  const refs = c.references || [];
  const list = products || [];
  const o = opts || {};
  const logos = o.logos || bk.logos || [];
  const approvedRefs = refs.filter(r => {
    const st = (r.meta || {}).review_status;
    return st === 'approved' || (!st && r.source === 'UPLOADED');
  });

  const items = [
    { key: 'logo', label: 'Logo', section: 'visual', required: true,
      ok: !!(bk.logo_url || logos.length || extras.logo_url),
      hint: 'Sem logo a arte sai sem marca.' },
    { key: 'colors', label: 'Cores', section: 'visual', required: true,
      ok: Object.keys(colors).length > 0,
      hint: 'A paleta define o visual das peças.' },
    { key: 'voice', label: 'Tom de voz', section: 'voz', required: true,
      ok: !!(bk.tone_of_voice || bk.persona || bk.audience),
      hint: 'Sem tom de voz a copy sai genérica.' },
    { key: 'product', label: 'Produto', section: 'produtos', required: true,
      ok: list.length > 0 || (c.catalog_links_count || 0) > 0,
      hint: 'É o que a peça vai anunciar.' },
    { key: 'visualbase', label: 'Direção visual', section: 'visual', required: false,
      ok: !!bk.visual_prompt_base || approvedRefs.length > 0,
      hint: 'Referências aprovadas guiam a imagem.' },
    { key: 'contact', label: 'Site ou rede', section: 'geral', required: false,
      ok: !!(c.website || c.site_url || (c.socials || {}).instagram || (c.socials || {}).facebook),
      hint: 'Usado para importar identidade e no CTA.' },
  ];

  const req = items.filter(i => i.required);
  const reqOk = req.filter(i => i.ok).length;
  const allOk = items.filter(i => i.ok).length;
  const pct = Math.round((allOk / items.length) * 100);
  return { items, pct, ready: reqOk === req.length, reqOk, reqTotal: req.length, missing: items.filter(i => !i.ok) };
}

/* estado por seção, para os pontinhos da navegação.
   Prefixo is-* de propósito: 'ok' cru colidiria com a classe
   utilitária global .ok do os.css (mensagem de status). */
function cliSectionStatus(readiness) {
  const st = {};
  (readiness.items || []).forEach(i => {
    const cur = st[i.section];
    const val = i.ok ? 'is-ok' : (i.required ? 'is-req' : 'is-miss');
    // prioridade: is-req > is-miss > is-ok
    if (cur === 'is-req') return;
    if (val === 'is-req' || !cur || (cur === 'is-ok' && val === 'is-miss')) st[i.section] = val;
  });
  return st;
}

function BrandReadiness({ readiness, onGo }) {
  const r = readiness || { items: [], pct: 0 };
  const title = r.ready
    ? 'Pronta para gerar conteúdo'
    : `Faltam ${r.reqTotal - r.reqOk} item(ns) para gerar conteúdo`;
  return <div className="rd">
    <div className={'rd-ring' + (r.ready ? ' is-ready' : '')} style={{ '--pct': r.pct }}>
      <b>{r.pct}%</b>
    </div>
    <div className="rd-txt">
      <div className="rd-t">{title}</div>
      <div className="hint" style={{ marginTop: 3 }}>
        {r.ready
          ? 'Identidade, voz e oferta preenchidas. Refine a direção visual para melhorar as artes.'
          : 'Clique no que falta para ir direto à seção.'}
      </div>
      <div className="rd-chips">
        {r.items.map(i => i.ok
          ? <span className="rd-chip is-ok" key={i.key}><Icon name="check" />{i.label}</span>
          : <button className={'rd-chip' + (i.required ? ' is-miss' : '')} key={i.key}
              title={i.hint} onClick={() => onGo && onGo(i.section)}>
              <Icon name={i.required ? 'warning' : 'plus'} />{i.label}
            </button>)}
      </div>
    </div>
  </div>;
}

/* ═══════════════════════════════════════════════════════════════
   C. SHELL DO CADASTRO — hero, navegação lateral, painel
   ═══════════════════════════════════════════════════════════════ */
function ClientHero({ company, stage, onBack, right, children }) {
  const c = company || {};
  const bk = c.brand_kit || {};
  const site = c.website || c.site_url || '';
  return <div className="stack">
    {onBack && <div className="row">
      <button className="cli-back" onClick={onBack}><Icon name="arrowL" />Todas as empresas</button>
    </div>}
    <div className="cli-hero">
      <div className="ch-av">
        {bk.logo_url ? <img src={bk.logo_url} alt="" /> : (c.name || '?')[0]}
      </div>
      <div className="ch-txt">
        <h3>{c.name || 'Cliente'}</h3>
        <div className="ch-meta">
          {stage && <Pill kind={stage.kind || 'cy'} dot>{stage.label}</Pill>}
          {c.segment && <span className="hint">{c.segment}</span>}
          {site && <a href={site} target="_blank" rel="noreferrer">{String(site).replace(/^https?:\/\//, '')}</a>}
        </div>
      </div>
      {right && <div className="ch-side">{right}</div>}
    </div>
    {children}
  </div>;
}

function SectionNav({ groups, value, onChange, status }) {
  const st = status || {};
  return <div className="cli-nav">
    {groups.map(([group, items]) => <React.Fragment key={group}>
      <div className="cli-nav-g">{group}</div>
      {items.map(([key, label, icon]) => <button key={key}
        className={'cli-nav-i' + (value === key ? ' on' : '')} onClick={() => onChange(key)}>
        <Icon name={icon} />
        <span>{label}</span>
        {st[key] && <i className={'dot ' + (st[key] === 'is-req' ? 'is-miss is-req' : st[key])} />}
      </button>)}
    </React.Fragment>)}
  </div>;
}

/* cabeçalho padrão de cada seção */
function ClientSection({ icon, title, sub, side, children }) {
  return <div className="cli-sec">
    <div className="cli-sec-h">
      <div className="cs-ic"><Icon name={icon || 'doc'} /></div>
      <div className="cs-txt">
        <h4>{title}</h4>
        {sub && <div className="cs-sub">{sub}</div>}
      </div>
      {side && <div className="cs-side">{side}</div>}
    </div>
    {children}
  </div>;
}

/* campos opcionais recolhidos */
function OptionalFields({ title = 'Campos opcionais', children }) {
  return <details className="cli-more">
    <summary>{title}</summary>
    <div className="cli-more-b">{children}</div>
  </details>;
}

/* barra de salvar grudada no fim do painel */
function SaveBar({ busy, msg, label = 'Salvar', onSave, children }) {
  return <div className="cli-save">
    <span className="sp">
      {msg ? <span className={msg.startsWith('Erro') ? 'err' : 'ok'} style={{ padding: '5px 10px' }}>{msg}</span> : null}
    </span>
    {children}
    <button className="btn pri" disabled={busy} onClick={onSave}>
      <Icon name="check" />{busy ? 'Salvando…' : label}
    </button>
  </div>;
}

/* barra de topo das seções densas */
function DenseBar({ title, count, children }) {
  return <div className="cli-dense-bar">
    <span className="db-t">{title}</span>
    {count != null && <Pill kind="cy">{count}</Pill>}
    <span className="db-sp" />
    {children}
  </div>;
}

/* ── ativos (logos, referências) ── */
function AssetTile({ src, tag, dark, on, onClick }) {
  return <div className={'cli-asset' + (dark ? ' dark' : '') + (on ? ' on' : '')} onClick={onClick}>
    {src ? <img src={src} alt="" /> : <Icon name="image" style={{ width: 22, height: 22, color: 'var(--muted)' }} />}
    {tag && <span className="as-tag">{tag}</span>}
  </div>;
}
function AssetAdd({ label = 'Enviar', onClick }) {
  return <div className="cli-asset add" onClick={onClick}>
    <Icon name="upload" /><span>{label}</span>
  </div>;
}
function PaletteRow({ colors }) {
  const entries = Object.entries(colors || {});
  if (!entries.length) return null;
  const labels = { primary: 'Principal', secondary: 'Secundária', accent: 'Destaque' };
  return <div className="cli-pal">
    {entries.map(([k, hex]) => <div className="cli-sw" key={k}>
      <div className="sw-c" style={{ background: hex }} />
      <span className="sw-l">{labels[k] || k}</span>
      <span className="sw-h">{String(hex || '').toUpperCase()}</span>
    </div>)}
  </div>;
}

/* ── árvore do catálogo ── */
function CatalogNode({ icon = 'layers', title, sub, count, open, side, children }) {
  return <details className="cli-node" open={open}>
    <summary>
      <span className="nd-ic"><Icon name={icon} /></span>
      <span className="nd-main">
        <b>{title}</b>
        {sub && <span className="hint sm" style={{ display: 'block', marginTop: 2 }}>{sub}</span>}
      </span>
      {count != null && <Pill kind={count ? 'cy' : ''}>{count}</Pill>}
      {side}
    </summary>
    <div className="nd-b">{children}</div>
  </details>;
}
function CatalogLeaf({ name, sub, plans, side }) {
  return <div className="cli-leaf">
    <span className="li-ic" style={{ width: 30, height: 30 }}><Icon name="doc" /></span>
    <span className="lf-main">
      <b>{name}</b>
      {sub && <small>{sub}</small>}
      {!!(plans || []).length && <span className="cli-plans" style={{ marginTop: 6 }}>
        {plans.map(p => <span className="chip" key={p} style={{ fontSize: 11, padding: '3px 9px' }}>{p}</span>)}
      </span>}
    </span>
    {side}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════
   D. APP CRIAÇÃO
   ═══════════════════════════════════════════════════════════════ */

/* linha de run legível */
function RunRow({ run, on, thumb, onClick }) {
  const r = run || {};
  const dur = r.duration_str || (r.duration_seconds != null ? mpFmtSec(r.duration_seconds) : null);
  const when = r.created_str || r.created_at_str || '';
  const state = r.frames_count === 0 ? 'partial' : (r.result || r.has_result ? 'ready' : '');
  return <button className={'cri-run' + (on ? ' on' : '')} onClick={onClick}>
    <span className="rn-th">
      {thumb ? <img loading="lazy" decoding="async" src={thumb} alt="" /> : <Icon name="teaser" />}
      {dur && <span className="rn-d">{dur}</span>}
    </span>
    <span className="rn-main">
      <b>{r.snip || r.name || 'Sem nome'}</b>
      <span className="rn-meta">
        <span className="rn-id">{String(r.id || '').slice(0, 8)}</span>
        {when && <>· {when}</>}
      </span>
    </span>
    <span className={'rn-st ' + state} title={state === 'ready' ? 'analisado' : state === 'partial' ? 'sem frames' : ''} />
  </button>;
}

/* seletor de capa com seleção evidente */
function CoverPicker({ frames, value = 0, onChange, srcOf, max = 12 }) {
  const list = (frames || []).slice(0, max);
  if (!list.length) return null;
  const src = srcOf || (window.frameSrc) || (f => f);
  return <div className="cri-covers">
    {list.map((f, i) => <div key={i} className={'cri-cover' + (i === value ? ' on' : '')}
      onClick={() => onChange && onChange(i)} title={'Frame ' + (i + 1)}>
      <img loading="lazy" decoding="async" src={src(f)} alt={'frame ' + (i + 1)} />
      <span className="cv-mk"><Icon name="check" /></span>
      <span className="cv-t">{i + 1}</span>
    </div>)}
  </div>;
}

/* contador de caracteres com limite por rede */
function CharCount({ value = '', max = 2200 }) {
  const n = String(value || '').length;
  const pct = Math.min(100, (n / max) * 100);
  const cls = n > max ? ' over' : (n > max * 0.85 ? ' warn' : '');
  return <div className={'cri-count' + cls}>
    <span className="cc-bar"><i style={{ width: pct + '%' }} /></span>
    <span>{n}/{max}</span>
  </div>;
}

/* prévia do post, com a rede-alvo visível */
function PostPreview({ net = 'Instagram', netIcon = 'broadcast', cover, title, desc, tags, empty }) {
  return <div className="cri-prev">
    <div className="cri-prev-net">
      <span className="pn-ic"><Icon name={netIcon} /></span>
      <b>{net}</b>
      <span className="hint sm" style={{ marginLeft: 'auto' }}>prévia</span>
    </div>
    <div className="cri-prev-media">
      {cover ? <img loading="lazy" decoding="async" src={cover} alt="capa" /> : null}
      {!cover && <div className="pv-empty">{empty || 'Sem capa selecionada'}</div>}
    </div>
    <div className="cri-prev-b">
      <div className="pv-t">{title || 'Sem título'}</div>
      <div className="pv-d">{desc || 'Sem descrição gerada.'}</div>
      {!!(tags || []).length && <div className="row" style={{ gap: 5 }}>
        {tags.slice(0, 8).map(t => <span className="chip tag" key={t}>#{t}</span>)}
      </div>}
    </div>
  </div>;
}

/* estado publicado */
function PublishDone({ net = 'Instagram', when, onOpen, onNew }) {
  return <div className="cri-done">
    <span className="cd-ic"><Icon name="check" /></span>
    <span style={{ flex: 1, minWidth: 0 }}>
      <b>Post publicado em {net}</b>
      {when && <small>{when}</small>}
    </span>
    {onOpen && <button className="btn sm" onClick={onOpen}><Icon name="eye" />Ver</button>}
    {onNew && <button className="btn sm ghost" onClick={onNew}>Novo post</button>}
  </div>;
}

Object.assign(window, {
  CLI_SECTIONS, cliSectionsFor, computeBrandReadiness, cliSectionStatus,
  BrandReadiness, ClientHero, SectionNav, ClientSection, OptionalFields, SaveBar,
  DenseBar, AssetTile, AssetAdd, PaletteRow, CatalogNode, CatalogLeaf,
  RunRow, CoverPicker, CharCount, PostPreview, PublishDone,
});
