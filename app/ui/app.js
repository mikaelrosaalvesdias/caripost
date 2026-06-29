/* Minimal admin UI (no build step) */

function qs(id) { return document.getElementById(id) }

const IS_EMBED_MODE = new URLSearchParams(location.search).get('embed') === '1';
if (IS_EMBED_MODE) document.body.classList.add('ui-embed');

// ── Loader de inicialização da página ─────────────────────────────────────
const _pageLoader = (() => {
  const STEPS = [
    { pct: 5,  label: 'Carregando configurações locais…',  ms: 80   },
    { pct: 20, label: 'Carregando perfis de logo…',        ms: 400  },
    { pct: 40, label: 'Verificando autenticação…',         ms: 600  },
    { pct: 60, label: 'Iniciando interface…',              ms: 150  },
    { pct: 78, label: 'Verificando conexão com servidor…', ms: 500  },
    { pct: 92, label: 'Carregando dados iniciais…',        ms: 300  },
    { pct: 100, label: 'Pronto!',                          ms: 200  },
  ];
  const totalMs = STEPS.reduce((s, st) => s + st.ms, 0);
  let _startTime = Date.now();
  let _curPct = 0;
  let _stepIdx = 0;
  let _closed = false;

  function _el(id) { return document.getElementById(id); }

  function _update(pct, label) {
    if (_closed) return;
    _curPct = pct;
    const fill = _el('plFill');
    const det  = _el('plDetail');
    const pctEl = _el('plPct');
    const etaEl = _el('plEta');
    if (fill) fill.style.width = pct + '%';
    if (det)  det.textContent = label;
    if (pctEl) pctEl.textContent = pct + '%';
    if (etaEl && pct < 100) {
      const elapsed = Date.now() - _startTime;
      const rate = pct > 0 ? elapsed / pct : 0;
      const remainMs = Math.max(0, rate * (100 - pct));
      etaEl.textContent = remainMs > 1200
        ? `~${Math.ceil(remainMs / 1000)}s restantes`
        : 'quase pronto…';
    } else if (etaEl) {
      etaEl.textContent = '';
    }
  }

  function step(idx) {
    if (idx >= STEPS.length) return;
    const s = STEPS[idx];
    _stepIdx = idx;
    _update(s.pct, s.label);
  }

  function close() {
    if (_closed) return;
    _closed = true;
    _update(100, 'Pronto!');
    const modal = _el('pageLoadModal');
    if (!modal) return;
    setTimeout(() => {
      modal.style.opacity = '0';
      setTimeout(() => modal.remove(), 420);
    }, 280);
  }

  // Fallback: fecha após 8s se algo travar
  setTimeout(() => { if (!_closed) close(); }, 8000);

  return { step, close, STEPS };
})();

// ── Barra de progresso animada para operações longas ───────────────────────
class AnimatedProgress {
  constructor(wrapId, fillId, labelId) {
    this._wrap  = qs(wrapId);
    this._fill  = qs(fillId);
    this._label = qs(labelId);
    this._pct   = 0;
    this._timer = null;
    this._steps = [];
    this._stepIdx = 0;
    this._stepStart = 0;
    this._history = null;
    this._lastHistoryText = '';
    this._title = this._titleForWrap(wrapId);
    this._ensureCard();
  }

  _titleForWrap(id) {
    const titles = {
      anTranscribeProgressWrap: 'Transcrever',
      anAnalyzeProgressWrap: 'Analisar',
      aeProgressWrap: 'AutoEditor',
    };
    return titles[id] || 'Processando';
  }

  _ensureCard() {
    if (!this._wrap || !this._fill || !this._label) return;
    if (this._wrap.dataset.progressCard === '1') return;

    const previousDisplay = this._wrap.style.display || '';
    this._wrap.dataset.progressCard = '1';
    this._wrap.classList.add('upload-progress-card', 'op-progress-card');

    const ring = document.createElement('div');
    ring.className = 'upload-progress-ring';
    ring.style.setProperty('--upload-pct', '0');
    ring.innerHTML = `
      <div class="upload-progress-inner">
        <div class="upload-progress-percent">0%</div>
        <div class="upload-progress-state">pronto</div>
      </div>
    `;

    const copy = document.createElement('div');
    copy.className = 'upload-progress-copy';

    const title = document.createElement('div');
    title.className = 'upload-progress-title';
    title.textContent = this._title;

    this._label.classList.add('upload-progress-detail');
    this._label.textContent = this._label.textContent || 'Aguardando início.';

    const track = document.createElement('div');
    track.className = 'upload-progress-track';
    track.appendChild(this._fill);

    const history = document.createElement('div');
    history.className = 'op-progress-history';

    copy.appendChild(title);
    copy.appendChild(this._label);
    copy.appendChild(track);
    copy.appendChild(history);

    this._wrap.innerHTML = '';
    this._wrap.appendChild(ring);
    this._wrap.appendChild(copy);
    this._ring = ring;
    this._pctText = ring.querySelector('.upload-progress-percent');
    this._stateText = ring.querySelector('.upload-progress-state');
    this._titleEl = title;
    this._history = history;
    this._wrap.style.display = previousDisplay || 'none';
  }

  _stateTextFor(kind) {
    if (kind === 'good') return 'ok';
    if (kind === 'bad') return 'erro';
    if (kind === 'waiting') return 'confirme';
    return this._pct > 2 ? 'rodando' : 'aguarde';
  }

  _paint(pct, label, kind = 'active') {
    if (!this._wrap || !this._fill || !this._label) return;
    this._ensureCard();
    const safePct = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
    this._wrap.classList.toggle('is-good', kind === 'good');
    this._wrap.classList.toggle('is-bad', kind === 'bad');
    this._wrap.style.setProperty('--upload-pct', safePct.toFixed(1));
    if (this._ring) this._ring.style.setProperty('--upload-pct', safePct.toFixed(1));
    if (this._pctText) this._pctText.textContent = `${Math.round(safePct)}%`;
    if (this._stateText) this._stateText.textContent = this._stateTextFor(kind);
    if (this._titleEl) this._titleEl.textContent = this._title;
    this._fill.style.width = `${safePct.toFixed(1)}%`;
    if (label) this._label.textContent = label;
  }

  _pushHistory(text, kind = 'active') {
    if (!this._history || !text) return;
    const clean = String(text).replace(/^[✓✗⏳🎬🔍🤖✂️🔊🎞️📥]+\s*/u, '').trim();
    if (!clean || clean === this._lastHistoryText) return;
    this._lastHistoryText = clean;
    const item = document.createElement('div');
    item.className = `op-progress-history-item ${kind}`;
    item.textContent = `${kind === 'good' ? '✓' : kind === 'bad' ? '!' : '•'} ${clean}`;
    this._history.prepend(item);
    while (this._history.children.length > 6) this._history.lastElementChild?.remove();
  }

  // steps = [{pct: 30, label: 'texto…', minMs: 2000}, …]
  start(steps) {
    this._steps    = steps;
    this._stepIdx  = 0;
    this._pct      = 0;
    this._lastHistoryText = '';
    if (this._history) this._history.innerHTML = '';
    this._fill.style.background  = '';
    this._wrap.style.display     = 'grid';
    this._paint(0, steps[0]?.label || 'Iniciando…');
    this._pushHistory(steps[0]?.label || 'Iniciando…');
    this._stepStart = Date.now();
    clearInterval(this._timer);
    this._timer = setInterval(() => this._tick(), 250);
  }
  _tick() {
    const step = this._steps[this._stepIdx];
    if (!step) return;
    const target  = step.pct;
    const elapsed = Date.now() - this._stepStart;
    if (this._pct < target - 0.4)
      this._pct += (target - this._pct) * 0.12;
    this._paint(this._pct, step.label || '');
    const next = this._steps[this._stepIdx + 1];
    if (next && elapsed >= (step.minMs || 1500) && this._pct >= target - 1.5) {
      this._stepIdx++;
      this._stepStart = Date.now();
      this._paint(this._pct, next.label || '');
      this._pushHistory(next.label || '');
    }
  }
  _updatePct(pct, label) {
    if (pct <= this._pct && !label) return;
    this._pct = Math.max(this._pct, pct);
    this._paint(this._pct, label || this._label?.textContent || '');
    if (label) this._pushHistory(label);
    // Advance fake-animation step so it doesn't run ahead of real progress
    while (this._stepIdx < this._steps.length - 1 && this._pct >= this._steps[this._stepIdx].pct) {
      this._stepIdx++;
      this._stepStart = Date.now();
    }
  }
  complete(label) {
    clearInterval(this._timer);
    this._pct = 100;
    this._wrap.style.display = 'grid';
    this._paint(100, label || '✓ Concluído', 'good');
    this._pushHistory(label || 'Concluído', 'good');
  }
  error(label) {
    clearInterval(this._timer);
    this._pct = 100;
    this._wrap.style.display = 'grid';
    this._paint(100, label || '✗ Falhou', 'bad');
    this._pushHistory(label || 'Falhou', 'bad');
  }
  hide() {
    clearInterval(this._timer);
    this._wrap.style.display = 'none';
    this._pct = 0;
    this._paint(0, 'Aguardando início.');
  }
}

const transcribeProgress = new AnimatedProgress(
  'anTranscribeProgressWrap', 'anTranscribeProgressFill', 'anTranscribeProgressLabel'
);
const analyzeProgress = new AnimatedProgress(
  'anAnalyzeProgressWrap', 'anAnalyzeProgressFill', 'anAnalyzeProgressLabel'
);

const state = {
  apiKey: null,
  lastAnalyze: null,
  lastRunDetail: null,
  runDetailRequestId: 0,
  runDetailAbort: null,
  runDetailFramesLoadingFor: null,
  criacaoRequestId: 0,
  criacaoAbort: null,
  runFramesCache: new Map(),
  selectedRunId: null,
  selectedCriacaoRunId: null,
};

function _safeStorageGet(key, fallback = '') {
  try {
    return window.localStorage?.getItem(key) ?? fallback;
  } catch (_) {
    return fallback;
  }
}

function _safeStorageSet(key, value) {
  try {
    window.localStorage?.setItem(key, String(value));
  } catch (_) {}
}

const mediaManagerState = {
  category: 'all',
  search: '',
  maxKeys: 80,
  items: [],
  driveConfig: null,
  driveJobs: {},
  driveIntakeCreatorId: '',
  driveIntakeConfig: null,
  driveIntakeItems: [],
  driveIntakeJobs: {},
  driveIntakeSelectedIds: [],
  previewObjectKey: '',
  previewLabel: '',
  loaded: false,
  selectedKeys: [],
  viewMode: _safeStorageGet('mediaManagerViewMode', 'icons') === 'list' ? 'list' : 'icons',
  tileSize: Math.max(140, Math.min(parseInt(_safeStorageGet('mediaManagerTileSize', '190'), 10) || 190, 340)),
  tileShape: ['16x9', '4x3', '1x1', 'poster'].includes(_safeStorageGet('mediaManagerTileShape', '16x9'))
    ? _safeStorageGet('mediaManagerTileShape', '16x9')
    : '16x9',
  previewObserver: null,
  thumbQueue: [],
  thumbActive: 0,
  metadataCache: {},
  metadataPending: new Set(),
};

let _burnQueueRefreshInFlight = null;
let _burnQueueLastRefreshAt = 0;

function toast(msg, kind = "good") {
  const el = qs('toast');
  el.textContent = msg;
  el.classList.remove('hidden', 'good', 'bad');
  el.classList.add(kind === 'bad' ? 'bad' : 'good');
  setTimeout(() => { el.classList.add('hidden') }, 2500);
}

function loadApiKey() {
  const v = sessionStorage.getItem('adult_meta_api_key');
  if (v) {
    state.apiKey = v;
    qs('apiKey').value = v;
  }
}

function saveApiKey() {
  const v = qs('apiKey').value.trim();
  state.apiKey = v || null;
  if (state.apiKey) sessionStorage.setItem('adult_meta_api_key', state.apiKey);
  else sessionStorage.removeItem('adult_meta_api_key');
  toast('API key salva na sessão');
}

async function apiFetch(path, opts = {}) {
  const headers = Object.assign({
    'content-type': 'application/json',
  }, (opts.headers || {}));

  if (state.apiKey) headers['X-API-Key'] = state.apiKey;

  const res = await fetch(path, Object.assign({}, opts, { headers }));
  const ct = res.headers.get('content-type') || '';
  let data = null;
  if (ct.includes('application/json')) data = await res.json();
  else data = await res.text();

  if (!res.ok) {
    const msg = typeof data === 'string' ? data : (data?.detail || JSON.stringify(data));
    throw new Error(`${res.status} ${res.statusText}: ${msg}`);
  }
  return data;
}

function routeTo(name) {
  // nav highlight
  document.querySelectorAll('.nav a[data-route]').forEach(a => {
    a.classList.toggle('active', a.dataset.route === name);
  });
  // show page
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const page = qs(`page-${name}`);
  if (page) page.classList.add('active');
  updateTopbarContext(name);
  if (window.innerWidth <= 900) toggleSidebar(false);
  // show/hide media action footer based on active page
  const footer = qs('mediaActionFooter');
  if (footer) {
    if (name === 'media') {
      _updateMediaActionFooter(_mediaSelectedSet());
    } else {
      footer.classList.remove('visible');
    }
  }
  // lazy loaders
  if (name === 'settings') { reloadTokens(); renderChangelog(); aiLoadSettings(); }
  if (name === 'runs') reloadRuns();
  if (name === 'media') loadMediaManagerPage();
  if (name === 'criacao') { loadCriacaoRuns(); loadScheduledPosts(); }
  if (name === 'telegram') renderTelegramPage();
  if (name === 'referencia') updateRefSearchType();
  // Agency modules
  if (name === 'autoeditor') autoeditorLoad();
  if (name === 'creators') creatorsLoad();
  if (name === 'publisher') publisherLoad();
  if (name === 'trends') trendsLoad();
  if (name === 'calendar') calendarLoad();
  if (name === 'financial') financialLoad();
  if (name === 'dmca') dmcaLoad();
  if (name === 'videoenhancer') veLoad();
  // Company modules
  if (name === 'clientes') clientesLoad();
  if (name === 'aprovacao') aprovacaoLoad();
  if (name === 'concorrentes') concorrentesLoad();
}

function initRouting() {
  function onHash() {
    const rawHash = (location.hash || '').replace('#', '').trim();
    if (!rawHash) {
      routeTo('analyze');
      osShowDesktopHome();
      return;
    }
    const h = rawHash;
    routeTo(h);
  }
  window.addEventListener('hashchange', onHash);
  onHash();
}

async function healthTick() {
  try {
    const r = await fetch('/health');
    const ok = r.ok;
    qs('healthBadge').textContent = ok ? 'API: online' : 'API: offline';
    qs('healthBadge').style.color = ok ? 'var(--good)' : 'var(--bad)';
  } catch (e) {
    qs('healthBadge').textContent = 'API: offline';
    qs('healthBadge').style.color = 'var(--bad)';
  }
}

// SETTINGS
const tokenProviders = ['openai', 'groq', 'grok', 'gemini', 'deepseek', 'openrouter', 'deepgram', 'fal'];

function renderTokenRows(tokens) {
  const configured = new Map();
  (tokens || []).forEach(t => configured.set(t.key, t.updated_at));

  const wrap = qs('tokensTable');
  wrap.innerHTML = '';

  tokenProviders.forEach(p => {
    const key = `token:${p}`;
    const updatedAt = configured.get(key);

    const row = document.createElement('div');
    row.className = 'tokenRow';

    const left = document.createElement('div');
    left.innerHTML = `<div class="badge">${p}</div>`;

    const input = document.createElement('input');
    input.type = 'password';
    input.placeholder = 'cole o token e clique em salvar';
    input.autocomplete = 'off';

    const btn = document.createElement('button');
    btn.className = 'btn primary';
    btn.textContent = 'Salvar';
    btn.onclick = async () => {
      const v = input.value.trim();
      if (!v) return toast('Cole um token antes de salvar', 'bad');
      try {
        await apiFetch('/settings/tokens', { method: 'POST', body: JSON.stringify({ provider: p, api_key: v }) });
        input.value = '';
        toast('Token salvo');
        await reloadTokens();
      } catch (e) {
        toast(e.message, 'bad');
      }
    };

    const status = document.createElement('div');
    status.className = 'badge ' + (updatedAt ? 'good' : 'bad');
    status.textContent = updatedAt ? `Configurado em ${updatedAt}` : 'Não configurado';

    row.appendChild(left);
    row.appendChild(input);
    row.appendChild(btn);
    row.appendChild(status);
    wrap.appendChild(row);
  });
}

async function reloadTokens() {
  try {
    const r = await apiFetch('/settings/tokens');
    renderTokenRows(r.tokens);
  } catch (e) {
    toast(e.message, 'bad');
  }
}

// VISION DIAGNOSTIC
async function runVisionDiagnostic() {
  const btn = qs('btnVisionDiag');
  const resultDiv = qs('visionDiagResult');
  const statusEl = qs('visionDiagStatus');
  const jsonEl = qs('visionDiagJson');
  const copiedEl = qs('visionDiagCopied');

  btn.disabled = true;
  btn.textContent = '⏳ Testando...';
  resultDiv.style.display = 'none';
  copiedEl.style.display = 'none';

  try {
    const r = await apiFetch('/api/vision-diagnostic');
    const ok = r.any_success;
    statusEl.style.color = ok ? 'var(--ok)' : 'var(--err)';
    statusEl.textContent = `Status: ${r.status} — ${r.recommendation}`;
    jsonEl.textContent = JSON.stringify(r, null, 2);
    resultDiv.style.display = 'block';
  } catch (e) {
    statusEl.style.color = 'var(--err)';
    statusEl.textContent = `Erro ao executar: ${e.message}`;
    jsonEl.textContent = '';
    resultDiv.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = '🔬 Executar Diagnóstico';
  }
}

function copyVisionDiag() {
  const jsonEl = qs('visionDiagJson');
  const copiedEl = qs('visionDiagCopied');
  navigator.clipboard.writeText(jsonEl.textContent).then(() => {
    copiedEl.style.display = 'inline';
    setTimeout(() => { copiedEl.style.display = 'none'; }, 2000);
  });
}

// CHANGELOG
const TEASER_MAX_NUM_CLIPS = 20;
const TEASER_MAX_SCENE_DURATION_SEC = 720;
const TEASER_MAX_TOTAL_DURATION_SEC = 1800;

const CHANGELOG = [
  {
    version: 'v1.27.2', date: '2026-06-29',
    items: [
      { type: 'fix', text: 'Vídeo: modal de geração agora usa progresso do provedor dentro da cena e não fica preso em 5% em vídeos de uma cena.' },
      { type: 'fix', text: 'Vídeo: ETA volta a aparecer em jobs longos porque a barra avança mesmo enquanto a cena ainda está sendo gerada.' },
      { type: 'fix', text: 'Vídeo: custo estimado por catálogo não é mais rotulado como custo real e usa a mesma conversão BRL do preflight.' },
    ],
  },
  {
    version: 'v1.27.1', date: '2026-06-29',
    items: [
      { type: 'fix', text: 'Vídeo: CometAPI entregue sem usage.cost agora registra custo pelo catálogo/preflight, em vez de finalizar como R$ 0.' },
      { type: 'fix', text: 'Vídeo: download final usa a configuração congelada do job, sem depender do modelo global durante jobs longos.' },
    ],
  },
  {
    version: 'v1.27.0', date: '2026-06-29',
    items: [
      { type: 'fix', text: 'Vídeo: jobs agora congelam o provedor usado na criação, então trocar modelo durante a geração não quebra polling/download.' },
      { type: 'fix', text: 'Vídeo: status mostra provider_job_id, status e progresso do provedor; CometAPI ganha janela maior de polling.' },
      { type: 'fix', text: 'Vídeo: UI aguarda jobs longos sem declarar timeout antes do backend.' },
    ],
  },
  {
    version: 'v1.26.99', date: '2026-06-29',
    items: [
      { type: 'fix', text: 'Vídeo: preços do seletor e do preflight agora vêm dos catálogos OpenRouter/CometAPI quando disponíveis.' },
      { type: 'fix', text: 'Vídeo: duração travada respeita os segundos escolhidos quando o modelo permite, evitando cobrar/gerar clipe maior que o pedido.' },
    ],
  },
  {
    version: 'v1.26.98', date: '2026-06-29',
    items: [
      { type: 'fix', text: 'Vídeo: OpenRouter agora usa duration e frame_images no schema oficial, evitando erro Zod em first frame.' },
      { type: 'fix', text: 'Vídeo: CometAPI usa POST /v1/videos multipart + polling/download documentados; modelos Comet com rotas próprias saíram do seletor para evitar cobrança em endpoint errado.' },
      { type: 'fix', text: 'Vídeo: geração branded usa segundos por cena do preflight e endpoints legados passam prompt string, não objeto de storyboard.' },
    ],
  },
  {
    version: 'v1.26.61', date: '2026-06-28',
    items: [
      { type: 'fix', text: 'Conteúdo: rollback do motor de proteção/recorte que deixou post fixo com cara de template e reduziu criatividade.' },
      { type: 'fix', text: 'Post fixo: geração com IA volta ao modo criativo antigo por padrão; compositor com caixa fica apenas opt-in por render_mode.' },
    ],
  },
  {
    version: 'v1.23.4', date: '2026-06-22',
    items: [
      { type: 'fix', text: 'Instagram: re-host de imagem corrigido — URLs completas HTTPS agora são resolvidas para o caminho local no disco antes do upload ao tmpfiles.org.' },
      { type: 'fix', text: 'Logo: cutout refeito com alpha gradiente suave (sem flood-fill) — fundo sólido é removido sem pixelar bordas nem cortar letras.' },
    ],
  },
  {
    version: 'v1.23.3', date: '2026-06-22',
    items: [
      { type: 'fix', text: 'Composio/Instagram: publicação funcionando end-to-end. Imagem re-hosteada em tmpfiles.org (sem auth), ig_user_id no passo de publish, formato arguments corrigido.' },
      { type: 'fix', text: 'Logo: removido o flood-fill cutout que destruía o logo na imagem gerada — aplicado intacto, preservando alpha original.' },
      { type: 'fix', text: 'Social: erros da task fire-and-forget de publicação agora são capturados e logados.' },
    ],
  },
  {
    version: 'v1.22.3', date: '2026-06-20',
    items: [
      { type: 'fix', text: 'Composio: Settings agora aceita token Composio e Auth Configs sociais para conectar Instagram sem depender apenas de env no Docker.' },
      { type: 'fix', text: 'Social: provider Composio lê token salvo no banco e mostra configuração correta em /api/social/config.' },
    ],
  },
  {
    version: 'v1.22.2', date: '2026-06-20',
    items: [
      { type: 'feat', text: 'Clientes: nova aba Fluxo guia o caminho completo da empresa, do Instagram e concorrentes até estratégia, ideias, aprovação e publicação.' },
      { type: 'feat', text: 'Social Strategy: análise por empresa cruza perfil, concorrentes e referências via Composio/IA e gera identidade, pilares, ideias e prompts de arte.' },
      { type: 'feat', text: 'Geração de rascunhos: ideias da estratégia podem virar posts em revisão sem preencher dados duplicados.' },
    ],
  },
  {
    version: 'v1.22.1', date: '2026-06-20',
    items: [
      { type: 'feat', text: 'Social Integration Layer: conexões, posts, agendamento, status e métricas via Composio/provider isolado.' },
      { type: 'feat', text: 'Publicar OS: canais conectados, post social aprovado, concorrentes e referências sem tocar em upload ou processamento de vídeo.' },
      { type: 'chore', text: 'Worker social agendado com logs por canal, retry controlado e bloqueio para conteúdo não aprovado.' },
    ],
  },
  {
    version: 'v1.22.0', date: '2026-06-20',
    items: [
      { type: 'feat', text: 'Módulo de Clientes: CRUD de empresas, brand kit (logo, cores, voz, persona), mood board e concorrentes.' },
      { type: 'feat', text: 'Central de Aprovação: workflow DRAFT → REVIEW → APPROVED → SCHEDULED com transições validadas.' },
      { type: 'feat', text: 'Inteligência de Concorrentes: benchmark cross-empresa com visão consolidada.' },
      { type: 'feat', text: 'IA de texto (Anthropic/OpenAI/OpenRouter) integrada: geração de copy de posts e briefings de tendências.' },
      { type: 'feat', text: 'Tendências atualizadas: briefing por empresa via IA, sem dependência de scraping de plataformas adultas.' },
      { type: 'feat', text: 'Configurações de IA na página de Settings: provedor, modelo, API key e teste de conexão.' },
      { type: 'chore', text: 'Limpeza de referências de plataformas adultas na view de Tendências.' },
    ],
  },
  {
    version: 'v1.21.3', date: '2026-06-16',
    items: [
      { type: 'fix', text: 'Cortes diferencia Vision IA real de fallback automático quando os tokens de IA não estão configurados.' },
    ],
  },
  {
    version: 'v1.21.2', date: '2026-06-16',
    items: [
      { type: 'fix', text: 'Cortes IA agora informa timestamps por frame à Vision, usa cache persistente por hash do vídeo e atualiza progresso durante a extração paralela.' },
    ],
  },
  {
    version: 'v1.21.1', date: '2026-06-15',
    items: [
      { type: 'feat', text: 'Cortes com IA: Vision analisa frames e seleciona os melhores momentos automaticamente — sem sliders de minutagem.' },
      { type: 'feat', text: 'Extração paralela de clips com semáforo: até 3 ffmpeg simultâneos, speedup de 3x.' },
      { type: 'feat', text: 'Cache de análise por vídeo: mesma mídia não reanalisada pela IA.' },
      { type: 'design', text: 'UI redesenhadada do Cortes: limpa, sem inputs de quantidade/duração, foco em 1 clique.' },
      { type: 'feat', text: 'Fallback automático para detecção clássica de cenas quando IA está indisponível.' },
    ],
  },
  {
    version: 'v1.20.27', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'Analyze passa a pular transcrição por padrão e roda somente referências, Vision e JSON para evitar travas longas em vídeos grandes.' },
    ],
  },
  {
    version: 'v1.20.24', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'Upload em partes agora tem timeout por request e retry tambem para partes que ficam penduradas sem erro do navegador.' },
    ],
  },
  {
    version: 'v1.20.23', date: '2026-06-15',
    items: [
      { type: 'feat', text: 'Uploads agora exibem modal de tela inteira com circulo de progresso, percentual, tempo restante e etapa atual do envio.' },
    ],
  },
  {
    version: 'v1.20.22', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'Uploads pequenos via local-stream tambem passam a repetir automaticamente em falhas transitorias de rede.' },
    ],
  },
  {
    version: 'v1.20.21', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'Complete idempotente do upload em partes deixa de falhar se o registro auxiliar nao puder ser salvo, preservando a resposta de sucesso do upload.' },
    ],
  },
  {
    version: 'v1.20.20', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'Finalizacao do upload em partes passa a usar XHR, igual ao envio das partes, evitando falhas de fetch no navegador apos uploads grandes.' },
    ],
  },
  {
    version: 'v1.20.19', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'Finalizacao de upload em partes ganhou lock por upload, evitando corrida entre retries de complete e abort durante a montagem do arquivo grande.' },
    ],
  },
  {
    version: 'v1.20.18', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'Upload em partes agora repete tambem a inicializacao e finalizacao, e o backend devolve o mesmo resultado se a resposta do complete se perder na rede.' },
    ],
  },
  {
    version: 'v1.20.17', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'Uploads grandes passam a usar envio local em partes, com montagem e validação no backend antes de salvar o arquivo final.' },
    ],
  },
  {
    version: 'v1.20.16', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'Alinha as versoes publicas do Caripost OS e do painel ao backend em producao, removendo indicadores antigos e forçando novo cache bust dos assets.' },
    ],
  },
  {
    version: 'v1.19.13', date: '2026-06-15',
    items: [
      { type: 'fix', text: 'MetaPorn OS: o tour automatico deixa de bloquear cliques nas areas de upload, permitindo selecionar videos no Analyzer e nos fluxos com upload mesmo com o tutorial visivel.' },
    ],
  },
  {
    version: 'v1.19.12', date: '2026-06-14',
    items: [
      { type: 'fix', text: 'MetaPorn OS: routers modulares agora aceitam o mesmo X-Session-Token do login, liberando AutoEditor, Enhancer, Publicar, Criadores, DMCA, Agenda, Tendencias e Financeiro apos autenticar.' },
    ],
  },
  {
    version: 'v1.19.11', date: '2026-06-14',
    items: [
      { type: 'fix', text: 'MetaPorn OS: upload agora aguarda o login no overlay e retoma o mesmo arquivo selecionado, com uma nova tentativa quando a sessao expira.' },
    ],
  },
  {
    version: 'v1.19.10', date: '2026-06-13',
    items: [
      { type: 'fix', text: 'MetaPorn OS: a checagem inicial de auth preserva a abertura visual anterior e deixa o login aparecer somente quando uma ação protegida exigir credencial.' },
    ],
  },
  {
    version: 'v1.19.9', date: '2026-06-13',
    items: [
      { type: 'fix', text: 'MetaPorn OS: checagem de autenticacao agora reconhece `missing_or_invalid_api_key` mesmo quando o backend responde HTTP 200, forçando login antes do upload.' },
    ],
  },
  {
    version: 'v1.19.8', date: '2026-06-13',
    items: [
      { type: 'fix', text: 'MetaPorn OS: upload via `/uploads/local-stream` agora tambem envia a `X-API-Key` salva pela UI antiga, evitando `missing_or_invalid_api_key` em ambientes com API key obrigatoria.' },
    ],
  },
  {
    version: 'v1.19.7', date: '2026-06-13',
    items: [
      { type: 'fix', text: 'MetaPorn OS: upload de video passa a usar `/uploads/local-stream`, evitando falha de CORS/domínio no PUT direto do storage apos a migracao para CariPost.' },
    ],
  },
  {
    version: 'v1.19.6', date: '2026-06-10',
    items: [
      { type: 'fix', text: 'Arquivos: primeiras capas da grade agora sao carregadas imediatamente no render, mesmo quando a lista fica abaixo da dobra dentro da janela do MetaPorn OS.' },
    ],
  },
  {
    version: 'v1.19.5', date: '2026-06-10',
    items: [
      { type: 'fix', text: 'MetaPorn OS: login do desktop agora respeita /auth/check; quando a autenticação está ativa, o login acontece no OS e a sessão é compartilhada com os módulos antigos embutidos.' },
    ],
  },
  {
    version: 'v1.19.4', date: '2026-06-10',
    items: [
      { type: 'fix', text: 'MetaPorn OS: janelas do desktop passam a abrir os módulos reais antigos em /ui/?embed=1, restaurando uploads, runs, criação, burn, teaser, settings e demais handlers sem trocar o visual do desktop.' },
      { type: 'fix', text: 'Visual: ícones do desktop aumentados e distribuição centralizada no topo da tela.' },
    ],
  },
  {
    version: 'v1.19.0', date: '2026-06-02',
    items: [
      { type: 'feat', text: 'Redesign visual completo baseado no pacote Claude Designer: botões Run (cyan) vs Create (verde) em todos os módulos, pipeline visual de etapas no AutoEditor, footer de ações ao selecionar vídeo em Arquivos, portal do criador reformulado com novo sistema de design dark luxury.' },
    ],
  },
  {
    version: 'v1.18.21', date: '2026-06-02',
    items: [
      { type: 'fix', text: 'Visual: corrigida a tela inicial para seguir o desktop do pacote Claude Designer, com boot/login MetaPorn OS, grupos de apps completos e janela oculta por padrão quando não há rota direta.' },
    ],
  },
  {
    version: 'v1.18.20', date: '2026-06-02',
    items: [
      { type: 'fix', text: 'Visual: corrigida a entrega do redesign do Claude Designer com login em MetaPorn OS, desktop de apps agrupados, start menu real, taskbar e janela principal sem alterar rotas, endpoints ou loaders existentes.' },
    ],
  },
  {
    version: 'v1.18.19', date: '2026-06-02',
    items: [
      { type: 'feat', text: 'Visual: aplicado o shell MetaPorn OS desenhado no pacote do Claude Designer, com launcher em blocos, janela principal em vidro escuro e barra inferior de atalhos, preservando rotas e funções existentes.' },
    ],
  },
  {
    version: 'v1.18.18', date: '2026-05-25',
    items: [
      { type: 'fix', text: 'Logo: burn corrigido para calcular a altura pela proporção real da imagem no FFmpeg 7, evitando marca achatada em vídeos legendados.' },
    ],
  },
  {
    version: 'v1.18.17', date: '2026-05-23',
    items: [
      { type: 'fix', text: 'Runs/Criação: botões fixos de exclusão agora aparecem na lateral e ficam habilitados ao selecionar um run, sem depender apenas dos botões pequenos dentro da lista.' },
      { type: 'fix', text: 'Criação: adicionadas ações visíveis para limpar somente a criação selecionada ou excluir tudo do run selecionado.' },
    ],
  },
  {
    version: 'v1.18.16', date: '2026-05-23',
    items: [
      { type: 'feat', text: 'Runs: adicionadas ações para excluir run completo ou limpar somente a criação, removendo registros, jobs e mídias derivadas sem afetar arquivos usados por outros runs.' },
      { type: 'fix', text: 'Criação: limpeza preserva o run original e bloqueia exclusão quando há processamento ativo, evitando apagar estado durante burn/teaser em andamento.' },
      { type: 'chore', text: 'Versionamento sincronizado no backend, badges da UI e cache-busting do app.js para o deploy.' },
    ],
  },
  {
    version: 'v1.18.15', date: '2026-05-21',
    items: [
      { type: 'fix', text: 'Transcrição: fallback OpenRouter do pós-processamento agora usa `x-ai/grok-4.3`, evitando falha por modelo Grok depreciado.' },
    ],
  },
  {
    version: 'v1.18.14', date: '2026-05-21',
    items: [
      { type: 'fix', text: 'Transcrição: pós-processamento adulto não tenta mais `grok-2-latest`; usa Grok atual e cai para OpenRouter quando xAI rejeita o modelo.' },
    ],
  },
  {
    version: 'v1.18.13', date: '2026-05-21',
    items: [
      { type: 'fix', text: 'Transcrição local: modo adulto sem idioma explícito agora força PT-BR e tenta strict, relaxed e no-VAD antes de retornar vazio.' },
      { type: 'fix', text: 'Transcrição Auto: se o local vier vazio, tenta Whisper Sync e OpenRouter em sequência em vez de encerrar com empty_transcript.' },
      { type: 'feat', text: 'Teaser: queima de logo ganhou card circular de progresso com porcentagem, estado e histórico, igual ao upload.' },
    ],
  },
  {
    version: 'v1.18.12', date: '2026-05-20',
    items: [
      { type: 'fix', text: 'Logo: escala agora preserva o aspecto real da imagem no burn sem legenda, burn com legenda, preview e teaser.' },
      { type: 'fix', text: 'Logo: queima sem legenda, teaser direto e queima de logo no teaser voltam a carregar a imagem salva da empresa mesmo quando o layout foi desvinculado.' },
      { type: 'fix', text: 'Teaser: endpoint de queimar logo agora aceita `logos[]` como a queima principal, preservando a configuração da aba de logo do teaser.' },
      { type: 'fix', text: 'Logo: logs de burn/teaser agora mostram `logo_present` e `logo_count`, evitando job silencioso sem overlay.' },
    ],
  },
  {
    version: 'v1.18.5', date: '2026-05-19',
    items: [
      { type: 'feat', text: 'Arquivos: seleção múltipla redesenhada com cards/linhas marcados, seleção por categoria filtrada e botão de seleção total do Drive.' },
      { type: 'feat', text: 'Arquivos: duração, resolução, FPS e áudio agora carregam por ffprobe em lote e aparecem nos cards e na lista.' },
      { type: 'perf', text: 'Arquivos: capas agora usam thumbnails JPEG cacheadas no servidor em vez de carregar um vídeo por card, acelerando muito a grade.' },
    ],
  },
  {
    version: 'v1.18.4', date: '2026-05-19',
    items: [
      { type: 'fix', text: 'Queima: endpoint e visão de fila agora expõem `progress_pct` explicitamente para a porcentagem aparecer mesmo fora do card principal do job.' },
    ],
  },
  {
    version: 'v1.18.3', date: '2026-05-19',
    items: [
      { type: 'fix', text: 'Whisper Sync agora reconstrói o SRT pelos word_timestamps para evitar blocos gigantes de vários minutos.' },
    ]
  },
  {
    version: 'v1.18.2', date: '2026-05-19',
    items: [
      { type: 'feat', text: 'Transcrição ganhou Whisper Sync: faster-whisper premium com timestamps por palavra, sem LLM, para legenda queimável em áudio adulto difícil.' },
      { type: 'fix', text: 'Deepgram passa a usar nova-3 com keyterms adultos por padrão, em vez de nova-2/keywords.' },
    ]
  },
  {
    version: 'v1.18.1', date: '2026-05-19',
    items: [
      { type: 'feat', text: 'Transcrição ganhou provider Deepgram Sync com timestamps por palavra para gerar SRT queimável com sincronia real.' },
      { type: 'fix', text: 'Deepgram preserva texto bruto sem pós-processamento LLM, evitando reescrita/alucinação em diálogos.' },
    ]
  },
  {
    version: 'v1.18.0', date: '2026-05-19',
    items: [
      { type: 'fix', text: 'Queima de legenda ganhou diagnóstico de SRT antes do burn, mostrando buracos grandes de sincronia/cobertura no próprio run.' },
      { type: 'feat', text: 'Aba Criação agora gera prévia rápida de 60s em baixa resolução no minuto escolhido, com a mesma logo, fonte e SRT da queima completa.' },
      { type: 'fix', text: 'OpenRouter STT usa prompt PT-BR adulto e chunks menores por padrão para reduzir perda de trechos e alucinação em diálogos.' },
    ]
  },
  {
    version: 'v1.17.9', date: '2026-05-18',
    items: [
      { type: 'fix', text: 'OpenRouter continua liberado para legenda: quando vier sem timestamps reais, o backend reespalha os blocos no tempo do vídeo antes da queima.' },
      { type: 'fix', text: 'SRT antigo com blocos de 5 minutos agora é reparado automaticamente na queima, em vez de obrigar Premium/local.' },
    ]
  },
  {
    version: 'v1.17.8', date: '2026-05-18',
    items: [
      { type: 'fix', text: 'Queima bloqueia SRT com timestamps sintéticos/por blocos de 5 minutos para evitar legenda travada ou fora de sincronia.' },
      { type: 'fix', text: 'OpenRouter STT agora retorna timing_quality/burn_safe para a interface não tratar texto sem timestamps reais como legenda pronta para queima.' },
      { type: 'fix', text: 'Watermarks em canvas 16:9 completo (ex: 3840x2160) deixam de ser recortados automaticamente, evitando logo subir para o centro ao queimar com legenda.' },
      { type: 'fix', text: 'Antes de queimar, linhas longas do SRT são quebradas em até duas linhas para não criar faixa gigante no rodapé.' },
    ]
  },
  {
    version: 'v1.17.7', date: '2026-05-16',
    items: [
      { type: 'fix', text: 'Tradução OpenRouter: remove modelos reasoning (DeepSeek R1) que contaminavam delimitador |||SEG||| com blocos de pensamento; adiciona limpeza de resposta (tags think, code fences, trailing delimiter) e fallback para Google Translate.' },
      { type: 'feat', text: 'Queima: tamanho da legenda agora aceita de 6 a 72 (antes mínimo 10), com reserva de espaço da logo ajustada proporcionalmente.' },
      { type: 'fix', text: 'Queima: backend gerava timestamps falsos (~5s) quando SRT não era encontrado no run (fallback que chunkava texto puro). Agora frontend envia SRT do editor diretamente no body, e backend usa ele primeiro — fim de timposts artificiais e logo deslocada.' },
    ]
  },
  {
    version: 'v1.17.4', date: '2026-05-15',
    items: [
      { type: 'fix', text: 'Transcrição premium: prompt adulto PT-BR reforçado, VAD com threshold 0.35-0.40 e whitelist ampliada.' },
      { type: 'fix', text: 'Grok pós-processamento: payload agora leva adult_mode/porn_context e registra removidos/alterados nos logs.' },
      { type: 'fix', text: 'Tradução de legenda: prompt preserva tom adulto explícito, palavrões, gemidos e dirty talk.' },
    ]
  },
  {
    version: 'v1.17.3', date: '2026-05-15',
    items: [
      { type: 'fix', text: 'Premium PT-BR: faster-whisper large-v3-turbo/large-v3 em CPU int8 com prompt adulto, VAD dedicado e word timestamps.' },
      { type: 'fix', text: 'Transcrição pornô BR: scoring anti-alucinação, whitelist forte de dirty talk/gemidos e fallback sem traduzir nem remover repetições reais.' },
      { type: 'fix', text: 'Pós-processamento Grok-3 opcional via token:grok agora é conservador: só remove alucinação clara e preserva timestamps.' },
    ]
  },
  {
    version: 'v1.17.2', date: '2026-05-15',
    items: [
      { type: 'fix', text: 'Transcrição PT-BR: filtro anti-alucinação remove blocos clássicos de ASR em inglês/spam sem cortar repetições reais.' },
      { type: 'fix', text: 'AssemblyAI: keyterms adultos agora respeitam o idioma escolhido; em pt-BR não empurra termos em inglês.' },
      { type: 'fix', text: 'Premium: resgate sem VAD deixou de rodar por padrão para não inventar fala em gemidos/silêncio.' },
    ]
  },
  {
    version: 'v1.17.1', date: '2026-05-15',
    items: [
      { type: 'fix', text: 'Transcrição: opção Groq agora usa OpenRouter STT com token:openrouter, sem exigir token:groq.' },
      { type: 'fix', text: 'Premium large-v3: filtros relaxados e fallback sem VAD para não retornar vazio em fala baixa.' },
      { type: 'fix', text: 'AssemblyAI: não descarta palavras por confiança baixa e preserva mais fala repetida/baixa.' },
    ]
  },
  {
    version: 'v1.17.0', date: '2026-05-15',
    items: [
      { type: 'fix', text: 'Transcrição: repetições de palavras/frases/segmentos não são mais removidas, pois em vídeo adulto isso faz parte do conteúdo real.' },
      { type: 'fix', text: 'Transcrição: limpeza agora remove apenas scripts inesperados, spam conhecido e vazamento de prompt, preservando fala repetida.' },
    ]
  },
  {
    version: 'v1.16.9', date: '2026-05-15',
    items: [
      { type: 'fix', text: 'AssemblyAI: reduzido speech_threshold para não abortar vídeos com fala baixa; o filtro anti-ruído fica na confiança das palavras.' },
    ]
  },
  {
    version: 'v1.16.8', date: '2026-05-15',
    items: [
      { type: 'fix', text: 'Analyze: selecionar ou subir vídeo não inicia mais transcrição automática; a etapa original agora exige escolha manual do provider.' },
      { type: 'feat', text: 'Analyze: adicionados botões Auto estrito, AssemblyAI, Groq, OpenAI e Local para transcrever o vídeo selecionado sob demanda.' },
    ]
  },
  {
    version: 'v1.16.7', date: '2026-05-15',
    items: [
      { type: 'fix', text: 'AssemblyAI: corrigido upload HTTP assíncrono do áudio extraído para o endpoint /v2/upload.' },
    ]
  },
  {
    version: 'v1.16.6', date: '2026-05-15',
    items: [
      { type: 'feat', text: 'Transcrição: adicionada opção AssemblyAI Universal-3 Pro/Universal-2 como alternativa ao Whisper local/Groq/OpenAI, sem substituir o modo local estrito.' },
      { type: 'fix', text: 'Transcrição Auto agora é conservadora/local para reduzir alucinação: trecho sem fala clara deve voltar vazio em vez de inventar legenda.' },
    ]
  },
  {
    version: 'v1.16.5', date: '2026-05-14',
    items: [
      { type: 'feat', text: 'Upload: seleção múltipla de vídeos no Analyze, envio em fila paralela sem formulário/modal de metadados e com progresso consolidado.' },
    ]
  },
  {
    version: 'v1.16.4', date: '2026-05-14',
    items: [
      { type: 'fix', text: 'Transcrição: removido envio de prompt/instruções para Whisper/OpenAI, que causava vazamento literal de instruções dentro da legenda.' },
    ]
  },
  {
    version: 'v1.16.3', date: '2026-05-14',
    items: [
      { type: 'fix', text: 'Transcrição: spam conhecido do Whisper agora é removido mesmo em frase curta, não só em blocos longos.' },
    ]
  },
  {
    version: 'v1.16.2', date: '2026-05-14',
    items: [
      { type: 'fix', text: 'Transcrição: filtro anti-alucinação agora remove também spam clássico do Whisper em PT/ES tipo “se inscreva no canal”, comum em trechos adultos sem fala clara.' },
    ]
  },
  {
    version: 'v1.16.1', date: '2026-05-14',
    items: [
      { type: 'fix', text: 'Transcrição adulto: prompt sem censura para fala explícita, captura de voz baixa/vocalizações claras e pré-processamento de áudio para levantar diálogo em cenas com gemidos/ruído.' },
    ]
  },
  {
    version: 'v1.16.0', date: '2026-05-14',
    items: [
      { type: 'fix', text: 'Transcrição: idioma falado separado de tradução, padrão em português e filtro anti-alucinação para bloquear scripts/idiomas estranhos antes de salvar o SRT.' },
      { type: 'ui', text: 'Legenda: novo preview visual de fonte, tamanho, cor e delay na tela de queima, atualizando em tempo real como o preview de logo.' },
    ]
  },
  {
    version: 'v1.15.9', date: '2026-05-13',
    items: [
      { type: 'fix', text: 'Logo: removida qualquer correção que esticava a arte; a queima agora preserva a proporção real da imagem e, com legenda, reserva uma faixa inferior para impedir logo e legenda de se atropelarem.' },
    ]
  },
  {
    version: 'v1.15.8', date: '2026-05-13',
    items: [
      { type: 'fix', text: 'Logo: sondagem do SAR real do vídeo com ffprobe, pois no scale2ref do FFmpeg 5.1 as variáveis sar/main_sar apontam para o SAR do logo (sempre 1), não do vídeo — corrige logo achatada de vez.' },
      { type: 'fix', text: 'Progresso da queima: throttle reduzido de 5% para 3% e mensagem "Salvando vídeo queimado…" forçada após o ffmpeg, evitando UI travada em 96%.' },
    ]
  },
  {
    version: 'v1.15.7', date: '2026-05-13',
    items: [
      { type: 'fix', text: 'Logo: corrigido cálculo de altura no scale2ref — usava proporção do vídeo (ih/iw) em vez da proporção real do logo (main_h/main_w), e faltava compensação de SAR não quadrado, causando logo achatada em vídeos anamórficos.' },
    ]
  },
  {
    version: 'v1.15.6', date: '2026-05-13',
    items: [
      { type: 'fix', text: 'Logo: logos ultra-horizontais mantêm a largura configurada e recebem correção de altura visual, evitando marca gigante e achatada na queima.' },
    ]
  },
  {
    version: 'v1.15.5', date: '2026-05-13',
    items: [
      { type: 'fix', text: 'Logo: logos horizontais transparentes agora são aparadas e recebem escala wide inteligente, evitando aparência achatada na queima.' },
    ]
  },
  {
    version: 'v1.15.4', date: '2026-05-13',
    items: [
      { type: 'fix', text: 'Logo: preview HQ, queima e teaser agora preservam a proporção real da imagem ao escalar, evitando logo achatada no vídeo final.' },
    ]
  },
  {
    version: 'v1.15.3', date: '2026-05-12',
    items: [
      { type: 'feat', text: 'Arquivos: visualização por capas no estilo explorador de arquivos, com player ao clicar, ações rápidas, ajuste de tamanho e formatos 16:9, 4:3, quadrado e poster.' },
      { type: 'perf', text: 'Arquivos: capas carregam sob demanda ao rolar a página, evitando abrir preview de todos os vídeos de uma vez.' },
    ]
  },
  {
    version: 'v1.15.2', date: '2026-05-12',
    items: [
      { type: 'feat', text: 'Progresso: Transcrever, Analisar, Compare, Burn/Logo/Legenda e Teaser agora usam o mesmo quadro circular azul com porcentagem e histórico dos passos.' },
      { type: 'fix', text: 'Compare: progresso em stream não reentra mais no próprio handler, evitando loop de eventos enquanto conta tokens.' },
    ]
  },
  {
    version: 'v1.15.1', date: '2026-05-12',
    items: [
      { type: 'fix', text: 'Upload: estado inicial agora deixa explícito que o envio só começa após clicar em Confirmar Upload no modal, com feedback imediato ao confirmar.' },
    ]
  },
  {
    version: 'v1.15.0', date: '2026-05-12',
    items: [
      { type: 'feat', text: 'Upload: progresso agora usa loader circular azul com porcentagem no centro e detalhes do envio logo abaixo.' },
    ]
  },
  {
    version: 'v1.14.9', date: '2026-05-12',
    items: [
      { type: 'fix', text: 'Upload: seleção de arquivo agora mostra estado "aguardando confirmação" antes do modal e barra real de progresso durante envio para `/uploads/local-stream`.' },
      { type: 'fix', text: 'Upload: interface passa a exibir MB enviados, tamanho total e percentual, deixando claro quando o arquivo ainda não começou a chegar ao servidor.' },
    ]
  },
  {
    version: 'v1.14.5', date: '2026-05-07',
    items: [
      { type: 'fix', text: 'Upload/Burn: validação detecta MP4 truncado pelo tamanho real vs duração/bitrate declarado antes de iniciar processamento longo.' },
      { type: 'fix', text: 'Burn: validação rápida agora testa também pontos iniciais/intermediários e captura "Packet corrupt", "missing picture" e "nothing was encoded".' },
      { type: 'fix', text: 'Burn: status de erro preserva run_id/logo_count para facilitar diagnóstico de arquivos problemáticos.' },
      { type: 'fix', text: 'Criação: botão de queima bloqueia duplo clique enquanto um job já está iniciando ou rodando.' },
    ]
  },
  {
    version: 'v1.14.1', date: '2026-05-03',
    items: [
      { type: 'feat', text: 'Upload: modal de metadados ao enviar arquivo — permite definir nome do arquivo e empresa antes do upload.' },
      { type: 'fix',  text: 'Arquivos: nome exibido agora usa o display_name definido no modal (não mais UUID/código S3).' },
      { type: 'fix',  text: 'Runs: lista exibe o nome original do arquivo ou chave S3 legível em vez do UUID do run.' },
      { type: 'fix',  text: 'Compare: resultado (texto, títulos, tags) agora persiste ao navegar entre abas e volta ao reabrir Criação.' },
      { type: 'fix',  text: 'Compare: providers A e B fixados em OpenRouter — removidas opções de xAI, OpenAI, Gemini, DeepSeek e Ollama.' },
      { type: 'fix',  text: 'Logo: controles de posição (presets, sliders X/Y, nudge) sempre habilitados — não dependem mais de logo ativa carregada.' },
      { type: 'fix',  text: 'Vision: scan de cenas em modo rápido (quick=True) usa seek individual por frame em vez de scan sequencial do vídeo inteiro.' },
      { type: 'fix',  text: 'Vision: modelo OpenRouter tenta próximo fallback quando "No endpoints found" (era ignorado silenciosamente).' },
      { type: 'fix',  text: 'Analyze: progresso real do servidor (5%→100%) exibido via polling a cada 2s — barra não trava mais em fake-animation.' },
      { type: 'fix',  text: 'Vision: usa OpenRouter como primeira escolha; xAI direto como fallback.' },
    ]
  },
  {
    version: 'v1.13.14', date: '2026-05-05',
    items: [
      { type: 'feat', text: 'Criação: painel de posicionamento de logo redesenhado como editor visual, com preview central, grade de posições, ajuste fino e campos numéricos.' },
      { type: 'fix', text: 'Criação: controles de X/Y/tamanho/opacidade agora sincronizam sliders, números e arraste da logo ativa em tempo real.' },
    ]
  },
  {
    version: 'v1.13.13', date: '2026-05-05',
    items: [
      { type: 'fix', text: 'Criação: editor de posicionamento da logo agora usa sempre frame limpo no Passo 1; a logo editável fica sempre separada do vídeo para não travar invisível.' },
      { type: 'fix', text: 'Criação: botões de preset/nudge de logo não são mais sobrescritos pelos valores antigos dos sliders.' },
    ]
  },
  {
    version: 'v1.13.12', date: '2026-05-05',
    items: [
      { type: 'fix', text: 'Criação: corrigido caso em que a logo não se movia visualmente após carregar preview HQ com logo compositada; o overlay editável agora volta a aparecer assim que o ajuste começa.' },
    ]
  },
  {
    version: 'v1.13.11', date: '2026-05-05',
    items: [
      { type: 'fix', text: 'Criação: posicionamento da logo ficou responsivo; sliders e drag agora atualizam localmente em tempo real e salvam/HQ apenas ao finalizar o ajuste.' },
      { type: 'fix', text: 'Preview de logos usa atualização coalescida por animation frame e transform GPU, reduzindo travadas ao arrastar múltiplas logos.' },
    ]
  },
  {
    version: 'v1.13.10', date: '2026-05-05',
    items: [
      { type: 'feat', text: 'Criação: Passo 1 agora suporta até 6 logos no burn principal, com quantidade configurável, upload uma a uma, seleção da logo ativa, preview simultâneo e posicionamento individual.' },
      { type: 'feat', text: 'Biblioteca de empresas passa a salvar conjuntos de logos com posição, escala e opacidade por logo, mantendo compatibilidade com empresas antigas de uma logo.' },
      { type: 'feat', text: 'Burn principal e preview HQ aceitam payload `logos[]` e queimam overlays sequenciais no FFmpeg; o campo legado `logo_b64` continua funcionando como fallback.' },
      { type: 'fix', text: 'Corrigida normalização de escala do multi-logo no teaser, evitando `NaN`/tamanho incorreto nos controles e payload.' },
    ]
  },
  {
    version: 'v1.13.0', date: '2026-04-25',
    items: [
      { type: 'feat', text: 'Video Enhancer: nova aba na sidebar com UI completa — selecionar vídeo do servidor ou fazer upload, escolher resolução 720p/1080p, iniciar job e acompanhar progresso em tempo real.' },
      { type: 'feat', text: 'Video Enhancer: barra de progresso com polling automático a cada 3s, exibe status, % e path do arquivo gerado ao concluir.' },
      { type: 'feat', text: 'Video Enhancer: lista de jobs recentes com status, resolução, tamanho e timestamps.' },
      { type: 'feat', text: 'Video Enhancer: botão "Verificar Video2X" checa instalação e exibe aviso se não encontrado.' },
    ]
  },
  {
    version: 'v1.12.9', date: '2026-04-25',
    items: [
      { type: 'feat', text: 'Novo módulo Video Enhancer: endpoint POST /api/video-enhancer/enhance recebe vídeo (upload multipart ou video_object_key local:) e executa Video2X para upscale de qualidade.' },
      { type: 'feat', text: 'Video Enhancer: suporte a resolução 720p (escala 2×) e 1080p (escala 4×) configurável por parâmetro ou variável VIDEO_OUTPUT_RESOLUTION.' },
      { type: 'feat', text: 'Video Enhancer: detecção automática de versão do Video2X (v5 flags vs v6 subcommands); fallback amigável com instrução de instalação se binário não encontrado.' },
      { type: 'feat', text: 'Video Enhancer: validações de entrada — extensão (mp4/mov/webm), tamanho máximo (VIDEO_ENHANCER_MAX_SIZE_MB), arquivo existente; pastas original/processed/temp criadas automaticamente.' },
      { type: 'feat', text: 'Video Enhancer: job assíncrono com acompanhamento via GET /api/video-enhancer/status/{job_id}; logs de início, comando executado, sucesso e erro no console.' },
      { type: 'feat', text: 'Video Enhancer: GET /api/video-enhancer/check verifica instalação do Video2X; GET /jobs lista histórico. README completo em video-enhancer/README.md.' },
    ]
  },
  {
    version: 'v1.12.8', date: '2026-04-17',
    items: [
      { type: 'fix', text: 'AutoEditor: concat com >30 clips agora usa reencode direto em vez de xfade chain — cadeia de 100+ filtros xfade encadeados estourava limites internos do ffmpeg causando EINVAL -22.' },
    ]
  },
  {
    version: 'v1.12.7', date: '2026-04-17',
    items: [
      { type: 'fix', text: 'AutoEditor: adicionada validação de clips por ffprobe antes do concat — clips com 0 frames são descartados; timelapse clips agora tratam fontes sem áudio (anullsrc) e são validados individualmente.' },
      { type: 'fix', text: 'AutoEditor: erro "Concat falhou" agora mostra erros de copy E reencode separadamente para melhor diagnóstico.' },
    ]
  },
  {
    version: 'v1.12.6', date: '2026-04-17',
    items: [
      { type: 'fix', text: 'AutoEditor: corrigido erro "Concat falhou coder before EOF -22 Invalid argument" — timelapse clips agora forçam -pix_fmt yuv420p; reencode concat normaliza format=yuv420p por stream antes do filter concat.' },
    ]
  },
  {
    version: 'v1.12.5', date: '2026-04-17',
    items: [
      { type: 'fix', text: 'Transcrição: corrigido erro 500 causado por função settings_get duplicada em db.py que sobrescrevia a original e retornava string em vez de dict para tokens de API.' },
    ]
  },
  {
    version: 'v1.12.4', date: '2026-04-17',
    items: [
      { type: 'perf', text: 'AutoEditor: _HARD_MIN elevado de 5s → 12s — segmentos curtos são descartados antes de chegar ao Grok, reduzindo micro-cortes.' },
      { type: 'perf', text: 'AutoEditor: scene_threshold reduzido de 0.32 → 0.25 — ffmpeg detecta menos cortes, gerando candidatos naturalmente mais longos.' },
      { type: 'perf', text: 'AutoEditor: peso do duration_score no ranking aumentado de 0.55 → 0.70 — cenas longas sobem no ranking antes da seleção pelo Grok.' },
    ]
  },
  {
    version: 'v1.12.3', date: '2026-04-17',
    items: [
      { type: 'feat', text: 'AutoEditor: prompt do Grok agora é editável diretamente na UI — seção "Prompt do Grok ✎" dentro de Configuração, sem necessidade de redeploy.' },
      { type: 'feat', text: 'AutoEditor: prompt salvo no SQLite (settings → ae_narrative_rules), com botão Salvar e Resetar padrão.' },
      { type: 'fix',  text: 'AutoEditor: campos Scene threshold / Cena mín / Cena máx / Pular transcrição removidos da UI — eram limites artificiais contra a filosofia do projeto.' },
      { type: 'feat', text: 'API: GET/PUT/DELETE /api/auto-editor/config para gerenciar prompt do Grok.' },
    ]
  },
  {
    version: 'v1.12.2', date: '2026-04-17',
    items: [
      { type: 'fix',  text: 'AutoEditor: HDR tone-mapping agora aplicado corretamente no recut — fontes sempre re-probadas para garantir color_transfer/pix_fmt atualizados.' },
      { type: 'feat', text: 'AutoEditor: _summarize_input_probe agora armazena color_primaries/color_transfer/color_space/pix_fmt nas sources para jobs futuros.' },
      { type: 'feat', text: 'AutoEditor: filtro pós-seleção _filter_equipment_scenes remove deterministicamente cenas com câmera/tripé visível.' },
      { type: 'feat', text: 'AutoEditor: timelapse opener — top-8 cenas por vision_relevance extraídas a 2× velocidade (~10s) colocadas no início do vídeo.' },
      { type: 'fix',  text: 'AutoEditor: prompt do Grok simplificado — removidas regras de porcentagem fixa (30% prelim / 70% sex) que conflitavam com conteúdo real.' },
    ]
  },
  {
    version: 'v1.12.1', date: '2026-04-17',
    items: [
      { type: 'fix', text: 'AutoEditor: cenas não são mais infladas para min_scene_duration — o LLM recebe cortes naturais (3s, 8s, 45s) em vez de blocos artificiais de 15-27s.' },
      { type: 'fix', text: 'AutoEditor: min_scene_duration default 15s → 3s; clips respeitam a duração real detectada pelo ffmpeg.' },
      { type: 'fix', text: 'AutoEditor: cobertura garantida — se Grok ignorar algum source_index (ex: C0696-98), o sistema injeta os melhores candidatos heurísticos desses vídeos automaticamente.' },
    ],
  },
  {
    version: 'v1.12.0', date: '2026-04-16',
    items: [
      { type: 'feat', text: 'AutoEditor: vídeos Sony XAVC e qualquer fonte HDR 10-bit (HLG, PQ/HDR10, S-Log) agora saem com cor correta — tone-mapping automático BT.2020→BT.709 via zscale/tonemap.' },
      { type: 'feat', text: 'AutoEditor: Grok Vision agora recebe frames com cores reais de câmeras HDR/Sony, melhorando a qualidade da análise de cenas.' },
      { type: 'perf', text: 'AutoEditor: detecção de cenas (scene detection) agora roda em 360p em vez de 4K — ~5-8× mais rápido por vídeo.' },
      { type: 'perf', text: 'AutoEditor: eliminada segunda passagem de detecção de cenas por vídeo — cut points da Vision são reutilizados diretamente.' },
      { type: 'perf', text: 'AutoEditor: extração de clips agora é paralela (até 3 ffmpeg simultâneos com semáforo) em vez de sequencial.' },
      { type: 'perf', text: 'AutoEditor: preset de encode dos clips intermediários alterado de medium → fast (~40% mais rápido por clip sem perda visual perceptível).' },
      { type: 'perf', text: 'AutoEditor: extração de keyframes para Vision unificada em único call ffmpeg batched em vez de N subprocessos separados.' },
      { type: 'perf', text: 'AutoEditor: job de 11 vídeos 4K que levava 3-5h deve cair para ~40-60min com todas as otimizações combinadas.' },
    ],
  },
  {
    version: 'v1.11.13', date: '2026-04-16',
    items: [
      { type: 'feat', text: 'AutoEditor: estrutura narrativa obrigatória no prompt do Grok — timelapse→intro→ação→preliminar (30%)→sexo (70%)→gozada, com regras detalhadas por tipo de cena.' },
      { type: 'feat', text: 'AutoEditor: perfil do canal do criador detectado automaticamente (anal/oral/threesome/solo/lesbian/squirt) via scraping dos próprios canais do criador no Xvideos.' },
      { type: 'feat', text: 'AutoEditor: regras de edição por categoria passadas ao Grok — comportamento diferente para criadores dominantemente anal, oral, etc.' },
      { type: 'feat', text: 'AutoEditor: max_scenes default 24→60, min_scene_duration 25s→15s, cap 80→120, floor mínimo de 1 cena por 3min de conteúdo.' },
      { type: 'fix', text: 'Transcrição: filtros anti-alucinação do Whisper (vad_filter, no_speech_threshold=0.55, log_prob_threshold=-1.0, compression_ratio_threshold=2.4).' },
      { type: 'fix', text: 'XVideos: socket.setdefaulttimeout(25) em todas as funções de scraping — elimina hang que matava o processo.' },
      { type: 'feat', text: 'Portal: FileRow exibe job.detail + % durante processamento do AutoEditor.' },
      { type: 'feat', text: 'Publicação: pipeline emite progress_pct e detail em cada etapa, admin auto-poll após iniciar.' },
    ],
  },
  {
    version: 'v1.11.13-base', date: '2026-04-15',
    items: [
      { type: 'feat', text: 'AutoEditor: cada vídeo selecionado agora passa por Analyze / Vision individualmente antes da curadoria final.' },
      { type: 'feat', text: 'AutoEditor: a seleção multi-fonte agora consolida candidatos por vídeo, mas extrai cada cena direto do arquivo original da sua origem.' },
      { type: 'fix', text: 'AutoEditor: cortes Smart mantêm sincronizados os tempos locais de cada cena, evitando extrair trechos errados após ajuste fino.' },
      { type: 'fix', text: 'AutoEditor: a tela de resultado passou a mostrar claramente de qual vídeo veio cada cena escolhida.' },
    ],
  },
  {
    version: 'v1.11.12', date: '2026-04-14',
    items: [
      { type: 'feat', text: 'AutoEditor: agora aceita múltiplos vídeos no mesmo job, preservando a ordem escolhida para montar a fonte final de edição.' },
      { type: 'feat', text: 'AutoEditor: Analyze / Vision roda automaticamente ao iniciar o job, sem depender da aba Analyze como etapa manual separada.' },
      { type: 'feat', text: 'AutoEditor: a seleção de cenas usa Vision para enriquecer o score e também envia esse contexto visual para o Grok.' },
      { type: 'fix', text: 'AutoEditor: a UI saiu do fluxo de vídeo único e passou a mostrar lista ordenada de fontes, resumo da Vision e status de áudio da entrada/saída.' },
    ],
  },
  {
    version: 'v1.11.8', date: '2026-04-14',
    items: [
      { type: 'fix', text: 'Versionamento do admin sincronizado: main.py, badges do HTML e cache-busting do app.js agora apontam para a mesma versão real do deploy.' },
      { type: 'fix', text: 'Deploys do painel não ficam mais com estado híbrido visual onde o container sobe código novo, mas a interface continua exibindo número antigo.' },
    ],
  },
  {
    version: 'v1.11.8', date: '2026-04-14',
    items: [
      { type: 'feat', text: 'Tendências: painel de progresso em tempo real com etapas detalhadas para "Coletar Canais" e "Gerar Briefing" — polling a cada 2.5s.' },
      { type: 'feat', text: 'Tendências: após geração, briefing fica "aguardando aprovação" com botões "✅ Aprovar e Notificar Criador", "👁 Aprovar sem notificar" e "🗑 Descartar".' },
      { type: 'feat', text: 'Tendências: barra de progresso por canal coletado (canal X/N, total de vídeos encontrados).' },
      { type: 'fix', text: 'Portal login: settings_get retornava dict inteiro — agora extrai corretamente o .value do hash, resolvendo o 401 com senha correta.' },
      { type: 'feat', text: 'Criadores: campo "Canais de Referência" e "Senha do Portal" no formulário de criação/edição.' },
    ],
  },
  {
    version: 'v1.11.7', date: '2026-04-14',
    items: [
      { type: 'feat', text: 'Criadores: campo "Canais de Referência" (URL por linha) adicionado ao formulário — salvo no criador e usado pelo Trend Radar para scraping de vídeos reais.' },
      { type: 'feat', text: 'Criadores: campo "Senha do Portal" no formulário — ao salvar, configura automaticamente o acesso do criador em criador.caripost.n8nmikael.com.br via /api/portal/set-password.' },
      { type: 'fix', text: 'Criadores: ao criar um novo criador, o creator_id retornado é usado imediatamente para definir a senha do portal, sem necessidade de etapa manual.' },
    ],
  },
  {
    version: 'v1.11.6', date: '2026-04-14',
    items: [
      { type: 'fix', text: 'Cache-busting: script tag do app.js agora usa versão atualizada (?v=1116), forçando browsers a baixar o código mais recente sem precisar de Ctrl+Shift+R.' },
      { type: 'fix', text: 'Changelog: adicionadas entradas faltantes de v1.11.3 a v1.11.6 que estavam deployadas mas não apareciam no log de versões.' },
    ],
  },
  {
    version: 'v1.11.5', date: '2026-04-14',
    items: [
      { type: 'feat', text: 'Portal do Criador - Tendências: cada sugestão do briefing agora exibe seção "🖼 Prompt thumbnail IA" com botão de cópia para colar direto no nano-banana.' },
      { type: 'feat', text: 'Portal API: endpoint /api/portal/my-trends passa suggestions completas incluindo image_prompt, top_channel_insights e campos de referência.' },
    ],
  },
  {
    version: 'v1.11.4', date: '2026-04-14',
    items: [
      { type: 'feat', text: 'Admin - Tendências: lista de briefings mostra nome do criador, contagem de sugestões e badge "🖼 prompts IA" quando o briefing contém image_prompts.' },
      { type: 'feat', text: 'Admin - Tendências: trendsShowBriefing() exibe painel de insights dos canais de referência com formato, tags e oportunidades por canal.' },
      { type: 'feat', text: 'Admin - Tendências: cada sugestão no briefing tem botão "📋 Copiar" para o image_prompt, pronto para colar no gerador de imagens.' },
    ],
  },
  {
    version: 'v1.11.3', date: '2026-04-13',
    items: [
      { type: 'feat', text: 'Trend Radar (backend): Grok agora é o provider exclusivo para briefings — somente token:grok ou token:openrouter (grok-3-fast) são tentados, sem fallback para OpenAI/DeepSeek.' },
      { type: 'feat', text: 'Trend Radar (backend): TREND_BRIEFING_PROMPT completamente reescrito com persona de diretor de conteúdo adulto explícita, sem filtros, instruindo o Grok a analisar views acima de 500K.' },
      { type: 'feat', text: 'Trend Radar (backend): cada sugestão do briefing agora inclui campo image_prompt — prompt detalhado em inglês para geração de thumbnail via IA de imagem.' },
      { type: 'feat', text: 'Admin - Tendências: novo botão "📡 Coletar Canais" para scraping dos canais de referência do criador (XVideos/Pornhub) antes de gerar briefings.' },
    ],
  },
  {
    version: 'v1.11.2', date: '2026-04-13',
    items: [
      { type: 'feat', text: 'Trend Radar: briefings agora gerados exclusivamente via Grok (xAI) com prompt adulto explícito e sem filtros de conteúdo.' },
      { type: 'feat', text: 'Briefings: cada sugestão inclui image_prompt detalhado para geração de thumbnail via IA de imagem (nano-banana/Gemini).' },
      { type: 'feat', text: 'Admin - Tendências: novo botão "Coletar Canais" para scraping dos canais de referência (XVideos/Pornhub) antes de gerar briefings.' },
      { type: 'feat', text: 'Admin - Tendências: briefings exibem insights por canal, prompts de thumbnail copiáveis e filtro por criador.' },
      { type: 'feat', text: 'Portal - Tendências: prompt de thumbnail IA exibido com botão de cópia em cada sugestão do briefing.' },
    ],
  },
  {
    version: 'v1.11.1', date: '2026-04-13',
    items: [
      { type: 'feat', text: 'AutoEditor: nova aba com pipeline assíncrono de corte automático, seleção de cenas, melhora de áudio e exportação do vídeo final.' },
      { type: 'feat', text: 'Swagger/OpenAPI: módulos de agência agora usam bodies tipados com Pydantic nos endpoints principais.' },
      { type: 'fix', text: 'Financeiro: schema voltou a expor platform_fee_pct, alinhando a documentação com o payload real da UI.' },
    ],
  },
  {
    version: 'v1.11.0', date: '2026-04-13',
    items: [
      { type: 'feat', text: 'Plataforma de agência: 7 novos módulos — Criadores, AutoPublisher, Portal do Criador, Trend Radar, DMCA, Agenda Editorial e Financeiro.' },
      { type: 'feat', text: 'Creator Management: CRUD completo de criadores com contas em múltiplas plataformas (XVideos, Pornhub, XNXX, xHamster) e criptografia Fernet para cookies/credenciais.' },
      { type: 'feat', text: 'AutoPublisher: upload automatizado via Playwright/Chromium com selector maps editáveis por plataforma sem alterar código.' },
      { type: 'feat', text: 'Trend Radar: coleta diária de tendências + briefings personalizados gerados por IA (Grok) para cada criador, com envio automático por email toda segunda.' },
      { type: 'feat', text: 'DMCA Protection: scan automático de pirataria via hash de imagem (pHash) e envio de notificações de takedown.' },
      { type: 'feat', text: 'Agenda Editorial: agendamento cross-platform com auto-schedule por IA e verificação a cada 5 minutos.' },
      { type: 'feat', text: 'Financeiro: registro de receitas, cálculo automático de comissão da agência/repasse ao criador e relatórios mensais por email.' },
      { type: 'feat', text: 'APScheduler: 8 jobs automáticos (coleta de tendências, briefings, scrape de stats, DMCA scan, publicação agendada, cross-promotion, login check, relatório mensal).' },
      { type: 'fix', text: 'Corrigida chamada incorreta a run_providers_to_completion em trend_briefing e calendar_scheduler (argumentos posicionais em função keyword-only + resultado tratado como string).' },
    ],
  },
  {
    version: 'v1.10.65', date: '2026-04-05',
    items: [
      { type: 'feat', text: 'Telegram via n8n: integração revisada para usar webhook n8n (bot token já configurado lá) — app gera URL assinada do teaser e dispara o webhook.' },
      { type: 'feat', text: 'Scheduler backend: verifica posts agendados a cada 30s e dispara automaticamente via webhook n8n.' },
      { type: 'feat', text: 'Logo: escala máxima aumentada de 60% para 100% — permite usar imagens pré-compostas (duas logos em frame completo) como overlay de tela cheia.' },
      { type: 'fix', text: 'Teaser: seleção de "Vídeo original" agora é respeitada sem conversão silenciosa para burned.' },
      { type: 'fix', text: 'Teaser burn-logo: não sobrescreve scale/posição customizada do usuário com valores do perfil.' },
    ],
  },
  {
    version: 'v1.10.60', date: '2026-04-03',
    items: [
      { type: 'feat', text: 'Arquivos: seleção múltipla adicionada com ações em lote para excluir e iniciar envio de vários arquivos ao Google Drive.' },
      { type: 'feat', text: 'Arquivos: barra de seleção mostra quantidade marcada e respeita o filtro atual para selecionar tudo de uma vez.' },
    ],
  },
  {
    version: 'v1.10.59', date: '2026-04-03',
    items: [
      { type: 'feat', text: 'Arquivos: nova página de gerenciamento para originais, queimados e teasers com player inline, download, renomear e exclusão.' },
      { type: 'feat', text: 'Arquivos: integração com Google Drive adicionada na própria UI, com pasta configurável e envio direto do storage para o Drive.' },
      { type: 'fix', text: 'Rename de mídia agora atualiza referências do run quando a chave muda, evitando quebrar runs por renomeação manual.' },
    ],
  },
  {
    version: 'v1.10.58', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Admin: `doctor.sh` agora funciona mesmo em servidor sem `rg`, usando fallback automático para `grep` na leitura de erros recentes.' },
      { type: 'fix', text: 'Admin: validação de storage separa melhor objetos ausentes do storage, vídeos inválidos e arquivos que nem são vídeo; o scan deixa de cuspir erro genérico para tudo.' },
    ],
  },
  {
    version: 'v1.10.57', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Blindagem extra de runtime: todo restart agora limpa temporários órfãos de burns/teasers no `/media/_tmp`, evitando sobras gigantes após falha, crash ou deploy interrompido.' },
      { type: 'fix', text: 'Deploy só faz limpeza total do `_tmp` quando não há jobs ativos; com isso a manutenção libera espaço sem apagar processamento em andamento por engano.' },
      { type: 'feat', text: 'Diagnóstico operacional: novo `scripts/doctor.sh` resume disco, Docker, saúde HTTP, fila de burn, jobs do banco, uso de mídia e erros recentes em um único comando.' },
    ],
  },
  {
    version: 'v1.10.56', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Blindagem operacional: SQLite agora usa WAL, busy_timeout e retry curto para reduzir falhas “database is locked” durante polling da fila e jobs simultâneos.' },
      { type: 'fix', text: 'Todos os temporários pesados passaram a preferir `/media/_tmp`, evitando que uploads, preview, análise, transcrição e validações encham o disco raiz do container.' },
      { type: 'fix', text: 'Deploy ficou mais seguro: limpa artefatos velhos quando falta espaço, não força `--no-cache` por padrão, espera healthcheck real e evita restart no meio de jobs sem override explícito.' },
    ],
  },
  {
    version: 'v1.10.55', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Teaser: ao gerar um teaser novo, o app limpa automaticamente resultados antigos de “teaser com logo” para não misturar o teaser perfeito com um burn velho gigante.' },
      { type: 'fix', text: 'Teaser com logo ganhou exclusão própria; ao apagar esse derivado, o wizard_state também é limpo e ele não volta após refresh.' },
    ],
  },
  {
    version: 'v1.10.54', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Teaser: fonte queimada agora trava o fluxo em cima do vídeo queimado real, sem religar logo automática ao abrir o Passo 3 e sem reaplicar marca por cima do arquivo já queimado.' },
      { type: 'fix', text: 'Burn concluído: se o teaser ainda apontava para o original padrão do run, a fonte muda automaticamente para o vídeo queimado recém-gerado.' },
    ],
  },
  {
    version: 'v1.10.53', date: '2026-04-02',
    items: [
      { type: 'feat', text: 'Teaser: toggle "Aplicar logo no teaser" agora usa visual de switch ON/OFF (toggle deslizante) para ficar óbvio e clicável.' },
    ],
  },
  {
    version: 'v1.10.52', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Teaser: logo não é mais aplicada quando "Aplicar logo no teaser" está desmarcado — backend agora gatea carregamento do perfil em force_logo_overlay; frontend remove logos sync_main quando logo do Passo 1 é removida e reseta estado ao remover última logo da lista.' },
    ],
  },
  {
    version: 'v1.10.51', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Teaser: controles da logo agora podem ser vinculados ao Passo 1, mantendo posição/escala/opacidade idênticas com sincronização imediata.' },
    ],
  },
  {
    version: 'v1.10.50', date: '2026-04-02',
    items: [
      { type: 'feat', text: 'Teaser: novo fluxo para gerar o teaser primeiro e depois queimar só a logo no teaser, com preview e download separados.' },
      { type: 'fix', text: 'Teaser sem logo: backend agora ignora o perfil da empresa quando `forçar logo` está desligado, evitando logo gigante aparecer mesmo após apagar a logo no passo.' },
    ],
  },
  {
    version: 'v1.10.48', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Burn e teaser agora desligam automaticamente o vínculo com o layout salvo da empresa se os sliders atuais estiverem diferentes, evitando logo gigante por override silencioso.' },
    ],
  },
  {
    version: 'v1.10.47', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Teaser agora preserva o áudio do vídeo fonte por padrão e o fallback de concatenação lida com vídeos sem áudio, evitando teaser silencioso.' },
      { type: 'fix', text: 'Logo: backend só reaplica o layout salvo da empresa quando o layout segue vinculado; ajustes manuais no wizard agora são respeitados no burn e teaser.' },
      { type: 'fix', text: 'Excluir teaser ficou mais robusto: UI envia o object_key e o backend aceita deletar mesmo se o wizard_state estiver desatualizado.' },
    ],
  },
  {
    version: 'v1.10.46', date: '2026-04-02',
    items: [
      { type: 'fix', text: 'Player do teaser agora prefere stream completo (qualidade e áudio originais), com fallback para preview adaptativo apenas se o stream falhar.' },
      { type: 'fix', text: 'Backend do burn/teaser passa a persistir `logo_profile_layout_linked` e sincroniza o layout salvo da empresa no wizard_state quando o perfil está vinculado.' },
    ],
  },
  {
    version: 'v1.10.45', date: '2026-04-01',
    items: [
      { type: 'fix', text: 'Teaser com logo estática agora mantém a imagem em loop durante cada cena e valida cada clip antes da concatenação, evitando MP4 com 1 frame, tela preta ou travamento.' },
      { type: 'fix', text: 'Burn e teaser passaram a reaplicar no backend o layout salvo da empresa quando o run continua vinculado ao perfil, blindando runs antigos contra logo gigante por configuração stale.' },
    ],
  },
  {
    version: 'v1.10.44', date: '2026-04-01',
    items: [
      { type: 'fix', text: 'Empresa salva volta a ser a fonte da verdade do layout da logo ao reabrir o run; quando o layout segue vinculado ao perfil, posição/escala/opacidade salvas são reaplicadas automaticamente.' },
      { type: 'fix', text: 'Ao mexer manualmente na logo depois de escolher uma empresa, o run se desliga do layout salvo da empresa em vez de misturar silenciosamente valores antigos e atuais.' },
      { type: 'fix', text: 'Teaser passou a manter áudio consistente por clip e a concatenação de recuperação reconstrói a timeline com filtro `concat`, reduzindo MP4 preto/travado por timeline quebrada.' },
    ],
  },
  {
    version: 'v1.10.43', date: '2026-04-01',
    items: [
      { type: 'fix', text: 'Teaser manual passa a usar os timestamps reais dos frames do run em vez de mapear a seleção linearmente para o vídeo inteiro, evitando começo preto e cenas erradas.' },
      { type: 'fix', text: 'Logo herdada do Passo 1 volta a sincronizar com posição/escala atuais no teaser, e a normalização final rejeita teaser com vídeo mais curto que o planejado.' },
    ],
  },
  {
    version: 'v1.10.41', date: '2026-04-01',
    items: [
      { type: 'fix', text: 'Burn, teaser, concat e uploads grandes deixaram de usar `/tmp` do container como scratch principal e passaram a preferir `/media/_tmp`, evitando falha por falta de espaço durante renders longos.' },
      { type: 'fix', text: 'Queimas de logo em vídeos grandes agora não morrem mais no final com `No space left on device` seguido de `unable to open database file` por estouro do disco temporário do container.' },
    ],
  },
  {
    version: 'v1.10.40', date: '2026-04-01',
    items: [
      { type: 'fix', text: 'Editor da logo agora reage em tempo real ao arrastar e mexer nos sliders, sem deixar a marca invisível até o próximo refresh do preview HQ.' },
      { type: 'fix', text: 'Refresh automático do preview HQ ficou silencioso e passou a acontecer em segundo plano, reduzindo pisca-pisca e mantendo o ajuste visual contínuo.' },
    ],
  },
  {
    version: 'v1.10.39', date: '2026-04-01',
    items: [
      { type: 'fix', text: 'Preview da logo não reaproveita mais frame HQ antigo já compositado ao trocar logo, posição, escala ou opacidade, evitando o efeito de logo duplicada.' },
      { type: 'fix', text: 'Deploy local passou a atualizar o serviço com `--no-resolve-image`, evitando task presa em digest antigo e reduzindo risco do projeto parecer offline após publicação.' },
    ],
  },
  {
    version: 'v1.10.38', date: '2026-04-01',
    items: [
      { type: 'feat', text: 'Biblioteca de logos por empresa: agora dá para subir uma logo, salvar nome da empresa com posição/escala/opacidade ideais e depois só escolher a empresa no passo de Criação.' },
      { type: 'feat', text: 'Perfis de logo ficam persistidos no backend com arquivo salvo no storage local do servidor, sem depender da aba atual ou de reenviar a mesma imagem toda vez.' },
      { type: 'fix', text: 'Ao selecionar uma empresa salva, o wizard reaplica automaticamente a logo armazenada e a geometria ideal antes do burn, teaser e thumbnail.' },
    ],
  },
  {
    version: 'v1.10.37', date: '2026-04-01',
    items: [
      { type: 'feat', text: 'Uploads novos, burns, teasers, combinados e previews passaram a aceitar storage local gerenciado no servidor com refs `local:...`, sem depender do limite de put único do S3.' },
      { type: 'fix', text: 'Upload principal e uploads auxiliares migraram para stream binário direto em `/uploads/local-stream`, removendo o caminho de FormData no frontend e reduzindo erro ao subir arquivos.' },
      { type: 'feat', text: 'Listagem, validação, stream, download e exclusão agora funcionam em storage híbrido: legado S3 continua abrindo, mas o app também administra mídia local com URLs assinadas.' },
    ],
  },
  {
    version: 'v1.10.36', date: '2026-03-31',
    items: [
      { type: 'fix', text: 'Rotas legadas de upload particionado foram desligadas no backend; clientes antigos agora recebem erro claro pedindo migração para `/uploads/proxy`, sem qualquer caminho escondido de chunking.' },
      { type: 'feat', text: 'Servidor ganhou `scripts/storage_admin.sh` para listar, validar e excluir uploads com falha direto no host, inclusive em lote.' },
      { type: 'fix', text: 'Fluxo de blindagem do storage foi consolidado: upload principal segue single-part validado, UI já deixa limpar objetos ruins e o shell ganhou o mesmo poder.' },
    ],
  },
  {
    version: 'v1.10.35', date: '2026-03-31',
    items: [
      { type: 'fix', text: 'Upload principal deixou de usar particionamento manual no app; agora sobe o arquivo em uma única requisição para o backend, que faz put_object single-part e valida o vídeo antes de aceitá-lo.' },
      { type: 'fix', text: 'Storage ganhou validação e exclusão manual de uploads na lista do servidor, facilitando limpar arquivos quebrados sem sair da interface.' },
      { type: 'feat', text: 'Teaser ganhou planejador por minutos: você define duração total, tempo da primeira parte e da parte final, e o restante é distribuído automaticamente pelas cenas.' },
      { type: 'fix', text: 'Worker de teaser agora falha rápido quando o vídeo-fonte já está corrompido, em vez de avançar para um processamento longo e ruim.' },
    ],
  },
  {
    version: 'v1.10.34', date: '2026-03-31',
    items: [
      { type: 'fix', text: 'Uploads grandes via multipart deixaram de consolidar estado de partes num único JSON concorrente no SQLite; cada parte agora é persistida atomicamente, evitando perda silenciosa de chunks.' },
      { type: 'fix', text: 'Finalização do upload agora valida quantidade esperada de partes e o tamanho final do objeto no MinIO antes de aceitar o vídeo, bloqueando MP4 incompleto antes que ele só exploda no burn.' },
      { type: 'fix', text: 'Frontend do upload passou a informar tamanho total e número esperado de partes ao backend para validação forte do arquivo armazenado.' },
    ],
  },
  {
    version: 'v1.10.33', date: '2026-03-31',
    items: [
      { type: 'fix', text: 'Criação: removido loop de re-render no wizard causado pelo auto-refresh do preview HQ da logo, que roubava foco dos inputs e impedia digitação.' },
      { type: 'fix', text: 'Sincronização visual da logo no pós-render agora atualiza sliders/labels sem reagendar persistência, redraw e refresh HQ a cada render.' },
    ],
  },
  {
    version: 'v1.10.32', date: '2026-03-31',
    items: [
      { type: 'fix', text: 'Passo da logo agora tenta carregar automaticamente o preview HQ fiel ao burn ao abrir o editor, reduzindo dependência do botão manual `HQ` para posicionar/escala corretos.' },
      { type: 'fix', text: 'Troca de resolução do burn agora força recarga do preview HQ da logo, evitando comparar um preview velho com uma saída em outra resolução.' },
      { type: 'fix', text: 'Preview visual da logo passou a usar encaixe mais honesto do frame no box, reduzindo distorção por `cover` quando o vídeo não é exatamente 16:9.' },
    ],
  },
  {
    version: 'v1.10.31', date: '2026-03-26',
    items: [
      { type: 'fix', text: 'Concatenação do teaser agora valida a timeline do MP4 copiado e recodifica automaticamente quando o vídeo sai com poucos frames/timestamps ruins, evitando teaser preto ou congelado.' },
      { type: 'fix', text: 'Concat com abertura herdou a mesma validação de timeline, reduzindo risco de MP4 final com áudio normal e vídeo praticamente parado.' },
    ],
  },
  {
    version: 'v1.10.30', date: '2026-03-25',
    items: [
      { type: 'feat', text: 'Teaser automático agora aceita cenas longas, com duração por cena de até 720 segundos, destravando teasers de 11-12 minutos sem hacks.' },
      { type: 'fix', text: 'Frontend e backend do teaser passaram a usar os mesmos limites e validações, evitando cortar silenciosamente duração configurada na UI.' },
      { type: 'fix', text: 'Jobs de teaser ganharam proteção por duração total estimada e timeouts mais realistas para cenas longas, reduzindo travamentos e processamentos absurdos.' },
    ],
  },
  {
    version: 'v1.10.29', date: '2026-03-25',
    items: [
      { type: 'fix', text: 'Preview HQ da logo agora pode ser renderizado pelo backend com o mesmo `ffmpeg` do burn, usando posição/escala/opacidade reais da queima em vez de só uma aproximação CSS.' },
      { type: 'fix', text: 'Burn passou a sincronizar explicitamente os sliders da logo antes de enviar o job, evitando uso de valores antigos quando o estado da tela e o estado interno se desalinham.' },
      { type: 'fix', text: 'Ao mexer na logo com HQ carregado, o preview compositado é invalidado e reatualizado, reduzindo divergência entre editor e vídeo final.' },
    ],
  },
  {
    version: 'v1.10.28', date: '2026-03-24',
    items: [
      { type: 'fix', text: 'Burn com resolução `Original` (`0`) volta a respeitar a resolução real do vídeo no backend, evitando saída 1080p por engano e logo desproporcional no arquivo final.' },
      { type: 'fix', text: 'Player do resultado queimado passa a usar `contain` e a proporção real do vídeo, alinhando melhor o que você vê com o preview da etapa de logo.' },
      { type: 'fix', text: 'Frontend normaliza URLs antigas/presigned para `object_key` curta antes de chamar stream/download, evitando `414 Request-URI Too Long` e `404` derivados de estado velho do wizard.' },
    ],
  },
  {
    version: 'v1.10.27', date: '2026-03-24',
    items: [
      { type: 'fix', text: 'Configuração da logo do wizard volta a ser salva por run mesmo quando o app está aberto sem `API_KEY`, então reabrir a criação não reseta posição/escala para o preset padrão.' },
      { type: 'fix', text: 'Burn agora grava no backend os parâmetros atuais de logo e preset assim que o processamento começa, reduzindo divergência entre preview, estado salvo e vídeo final.' },
      { type: 'fix', text: 'Antes do burn pesado, o backend faz uma checagem rápida do arquivo original para detectar truncamento/corrupção mais cedo e entrar em modo rápido de contingência quando necessário.' },
      { type: 'fix', text: 'Modo de recuperação do burn agora explica que a falha veio do arquivo original e usa preset mais rápido para não ficar preso por tanto tempo.' },
    ],
  },
  {
    version: 'v1.10.26', date: '2026-03-18',
    items: [
      { type: 'fix', text: 'Burn em modo recuperação agora corta e preenche o resultado final para fechar na duração esperada, sem estourar minutos extras.' },
      { type: 'fix', text: 'A fila de burn deixou de ser consultada automaticamente em background; ela só abre quando você pede, eliminando timeouts ruidosos no console.' },
    ],
  },
  {
    version: 'v1.10.25', date: '2026-03-18',
    items: [
      { type: 'fix', text: 'Burn: quando o MP4 truncar depois da metade, o sistema tenta concluir o vídeo congelando o último frame bom até a duração esperada, em vez de só falhar.' },
      { type: 'fix', text: 'Burn concluído em modo recuperação agora aparece como sucesso com aviso claro no resultado final.' },
      { type: 'fix', text: 'Polling da fila de burn foi desacelerado e deixou de bloquear o loop principal de status, reduzindo ruído como `ERR_TIMED_OUT` em `/api/burn-subtitles/queue`.' },
    ],
  },
  {
    version: 'v1.10.24', date: '2026-03-17',
    items: [
      { type: 'fix', text: 'Burn: ffmpeg do vídeo final agora tolera melhor quadros/pacotes corrompidos no MP4 original (`-err_detect ignore_err` + `+discardcorrupt`).' },
      { type: 'fix', text: 'Burn: quando o arquivo original estiver truncado/corrompido, a UI passa a receber erro explícito (`source_media_corrupt`) com duração alcançada, em vez de só `Conversion failed!`.' },
      { type: 'fix', text: 'Burn: saídas quase completas deixam de ser descartadas só porque o ffmpeg retornou código não-zero por erro menor no input.' },
    ],
  },
  {
    version: 'v1.10.23', date: '2026-03-17',
    items: [
      { type: 'fix', text: 'Jobs de burn e teaser agora persistem em SQLite, então o polling não perde o job ao cair em outro worker do Uvicorn.' },
      { type: 'fix', text: 'Ao reiniciar o serviço, jobs interrompidos passam a voltar com erro claro (`service_restarted`) em vez de sumirem com `404 job_not_found`.' },
      { type: 'fix', text: 'Burn com logo sem legenda: overlay agora usa `shortest=1`, impedindo o `ffmpeg` de ficar infinito por causa da imagem em loop.' },
      { type: 'fix', text: 'Produção voltou a rodar com múltiplos workers do Uvicorn, reduzindo indisponibilidade do app sob carga durante burn/teaser.' },
    ],
  },
  {
    version: 'v1.10.22', date: '2026-03-19',
    items: [
      { type: 'fix', text: 'Bug crítico 414: `_framePreviewSrc` tinha `\\/` na regex e tratava base64 de JPEG (começa com `/9j/…`) como URL, causando tela preta no preview e 414 no servidor.' },
    ],
  },
  {
    version: 'v1.10.21', date: '2026-03-17',
    items: [
      { type: 'fix', text: 'Jobs de burn e teaser no servidor agora rodam em worker único do app, eliminando `404 job_not_found` intermitente no polling após iniciar processamento.' },
      { type: 'fix', text: 'Preview HQ da logo: usa timestamps reais/reconstruídos dos screenshots em vez de mapear frame 0 para t=0 — elimina frame preto ao clicar em HQ.' },
      { type: 'fix', text: 'Preview HQ da logo agora troca a imagem só depois de carregar e usa `blob:` URL curta no DOM, evitando sumiço/tela preta em frames grandes.' },
      { type: 'fix', text: 'Logo: escala do burn e do teaser alinhada ao preview usando % da largura do vídeo final (não mais % do arquivo da logo) — o tamanho queimado agora bate com o editor visual.' },
      { type: 'fix', text: 'Preview da logo agora respeita a proporção real do vídeo quando há frame HQ/probe disponível, reduzindo distorção visual de posição e tamanho.' },
    ],
  },
  {
    version: 'v1.10.21', date: '2026-03-18',
    items: [
      { type: 'fix', text: 'Burn: botão "🗑 Deletar" agora aparece mesmo quando URL do vídeo expirou (só object_key salvo) — garante que sempre é possível deletar.' },
    ],
  },
  {
    version: 'v1.10.20', date: '2026-03-18',
    items: [
      { type: 'feat', text: 'Burn: botão "🗑 Deletar" no resultado do burn e no preview final — deleta o vídeo queimado do servidor e limpa o estado.' },
    ],
  },
  {
    version: 'v1.10.19', date: '2026-03-18',
    items: [
      { type: 'fix', text: 'Preview da logo: frame HQ agora extraído na mesma resolução do burn (1080p por padrão) — posicionamento e tamanho da logo batem com o vídeo queimado.' },
      { type: 'feat', text: 'Resolução: adicionada opção 4K (2160p) no seletor; ao trocar a resolução o frame HQ é recarregado automaticamente.' },
    ],
  },
  {
    version: 'v1.10.18', date: '2026-03-17',
    items: [
      { type: 'fix', text: 'Preview da logo: reescrito sem nested template literals — frame do vídeo aparece direto ao selecionar o run.' },
      { type: 'fix', text: 'Botão "Sem legenda": substituído checkbox feio por botão toggle integrado ao botão de burn.' },
    ],
  },
  {
    version: 'v1.10.17', date: '2026-03-17',
    items: [
      { type: 'feat', text: 'Tradução: substituído Google Translate por cadeia LLM (Grok → DeepSeek/OpenRouter → OpenAI) — tradução de qualidade adulta sem censura.' },
      { type: 'feat', text: 'Burn: nova opção "Queimar sem legenda (só logo)" — queima apenas a logo no vídeo sem precisar de transcrição.' },
      { type: 'feat', text: 'Preview da logo (Passo 1): botão "HQ" extrai frame em resolução real do vídeo para posicionamento fiel antes do burn.' },
    ],
  },
  {
    version: 'v1.10.16', date: '2026-03-17',
    items: [
      { type: 'fix',  text: 'Transcrição: ffmpeg agora tolera AAC corrompido/não-padrão (Reserved bit set, Number of bands exceeds limit) — vídeos gravados por câmeras/softwares com encoder não-conforme não falham mais.' },
    ],
  },
  {
    version: 'v1.10.15', date: '2026-03-17',
    items: [
      { type: 'feat', text: 'Transcrição: fallback chain automático — Auto tenta Groq Whisper → OpenAI Whisper → Local, igual ao padrão da Vision. Botão ⚡ Auto é o padrão.' },
      { type: 'fix',  text: 'Transcrição local: áudio extraído como WAV PCM (sem codec delay) em vez de AAC — elimina ~130ms de atraso nos timestamps do SRT.' },
      { type: 'fix',  text: 'Transcrição API: AAC extraído a 32kbps (era ~128kbps) — vídeos de até ~100 min ficam abaixo do limite de 25MB da OpenAI/Groq.' },
      { type: 'fix',  text: 'Whisper local: vad_filter desabilitado + condition_on_previous_text=False — timestamps mais estáveis, sem drift de centenas de ms.' },
      { type: 'fix',  text: 'Erros de transcrição agora mostram o detalhe real do ffmpeg/API na tela, em vez de só "ffmpeg_failed".' },
    ],
  },
  {
    version: 'v1.10.14', date: '2026-03-17',
    items: [
      { type: 'feat', text: 'UX: barra de progresso animada durante transcrição (Baixando → Extraindo áudio → Whisper) e análise (Baixando → Frames → Vision AI → LLM) — elimina sensação de erro em operações longas.' },
    ],
  },
  {
    version: 'v1.10.13', date: '2026-03-17',
    items: [
      { type: 'feat', text: 'Ollama local: modelos uncensored dolphin-mixtral:8x7b, dolphin3:8b, dolphin-mistral:7b-v2.8 e llava-llama3:8b disponíveis no provider Ollama.' },
    ],
  },
  {
    version: 'v1.10.12', date: '2026-03-16',
    items: [
      { type: 'fix', text: 'Uvicorn: substituído --limit-concurrency por --workers 2 — healthcheck não compete mais com uploads pesados, eliminando ciclo de restart/502.' },
      { type: 'fix', text: 'Healthcheck Docker: intervalo 10s→15s, timeout 5s→8s, start-period 15s→30s, retries 3→5 — container não é mais morto como "unhealthy" durante uploads simultâneos.' },
    ],
  },
  {
    version: 'v1.10.11', date: '2026-03-04',
    items: [
      { type: 'perf', text: 'Teaser player agora usa preview adaptativo (`/api/video-preview-url`) com cache em `previews/`, reduzindo travamentos em teasers antigos 4K/alto FPS.' },
      { type: 'fix', text: 'Geração de teaser passou a limitar saída por padrão para perfil web fluido (max 1080p/30fps, keyframes e bitrate controlados), mantendo qualidade visual e melhorando reprodução.' },
    ],
  },
  {
    version: 'v1.10.10', date: '2026-03-04',
    items: [
      { type: 'fix', text: 'Player do teaser/legendado/combinado agora usa sempre URL de stream inline por `object_key` (sem `attachment`), eliminando travamentos causados por URL de download no `<video>`.' },
      { type: 'fix', text: 'Reidratação do Wizard passou a substituir automaticamente URLs antigas com `response-content-disposition=attachment` por URL de stream para playback estável.' },
      { type: 'fix', text: 'Botões de download de teaser/combinado migrados para `/api/video-download-url`, separando fluxo de download e fluxo de reprodução.' },
    ],
  },
  {
    version: 'v1.10.9', date: '2026-03-04',
    items: [
      { type: 'fix', text: 'Player de preview (legendado/teaser/combinado): vídeos agora usam `preload=metadata` e `playsinline` para reduzir travamentos na visualização dentro da UI.' },
      { type: 'fix', text: 'Pipeline ffmpeg: outputs de burn, teaser, mix e concat passaram a usar `-movflags +faststart`, melhorando início de reprodução e seek no navegador.' },
    ],
  },
  {
    version: 'v1.10.8', date: '2026-03-04',
    items: [
      { type: 'perf', text: 'Runs: troca de run agora carrega primeiro `/runs/{id}/light` e busca screenshots em segundo plano (`/runs/{id}/frames`), reduzindo tempo de resposta percebido na UI.' },
      { type: 'perf', text: 'Criação: seleção de run migrada para endpoint mínimo `/runs/{id}/wizard-data`, carregando só o necessário no início e puxando frames depois, sem bloquear a tela.' },
      { type: 'perf', text: 'Criação: hidratação de URLs de mídia paralelizada + cache de presigned URL no frontend para evitar chamadas repetidas e reduzir latência ao alternar runs.' },
    ],
  },
  {
    version: 'v1.10.7', date: '2026-03-04',
    items: [
      { type: 'fix', text: 'Teaser: escolha de logo destravada (upload sempre habilitado), preview da logo visível sem bloquear edição e auto-import da logo do Passo 1 na primeira entrada do passo.' },
      { type: 'fix', text: 'Teaser: seleção de fonte original corrigida com fallback robusto para `video_object_key`; quando não há vídeo queimado, o passo passa a priorizar o vídeo original automaticamente.' },
      { type: 'feat', text: 'Teaser: nova opção "Escolher original da biblioteca" para selecionar vídeo de `uploads/` direto no passo 3.' },
      { type: 'fix', text: 'Wizard: navegação para Teaser liberada sem depender de concluir legenda/burn no passo anterior.' },
    ],
  },
  {
    version: 'v1.10.6', date: '2026-03-04',
    items: [
      { type: 'fix', text: 'Upload: corrigido 502/503 definitivo — Uvicorn tinha --limit-concurrency 20 causando rejeição de requests durante uploads paralelos. Aumentado para 500.' },
    ],
  },
  {
    version: 'v1.10.5', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Upload: corrigido 503 causado por 20 workers simultâneos saturando o event loop. Reduzido para 8 workers paralelos. Ops SQLite agora são async (asyncio.to_thread) para não bloquear o servidor.' },
      { type: 'fix', text: 'Upload: chunk mantido em 25MB (2.5x menos requests) com 8 workers (melhoria real de ~3x vs configuração anterior).' },
    ],
  },
  {
    version: 'v1.10.3', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Upload chunked: estado do multipart upload agora persiste no SQLite — não perde mais a sessão de upload quando o servidor é atualizado/reiniciado durante o envio do arquivo.' },
    ],
  },
  {
    version: 'v1.10.2', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Vision API: cadeia completa de fallback — xAI direto (grok-2-vision-latest → grok-2-vision-1212 → grok-4 → grok-4-fast → grok-2-vision → grok-vision-beta) → OpenRouter Grok → OpenRouter DeepSeek.' },
      { type: 'feat', text: 'Vision: novo token:openrouter usado automaticamente como fallback se todos os modelos xAI falharem.' },
    ],
  },
  {
    version: 'v1.10.1', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Settings: novo card "Diagnóstico Vision API (xAI)" — testa cada modelo grok-2-vision com pixel mínimo e exibe os erros HTTP completos para enviar ao suporte xAI.' },
    ],
  },
  {
    version: 'v1.10.0', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Thumbnail IA: novo fallback automático para Flux (fal.ai) quando Grok bloqueia por moderação, mantendo geração em 2 variantes.' },
      { type: 'feat', text: 'Settings: suporte ao `token:fal` para habilitar geração por Flux direto no endpoint `/api/thumbnail/ai-generate`.' },
      { type: 'fix', text: 'Diagnóstico de provider na resposta da thumbnail IA (`provider_used`, `used_fal_fallback`) para rastrear se a imagem veio de Grok ou Flux.' },
    ],
  },
  {
    version: 'v1.9.9', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Teaser/Narração: novo botão para gerar áudio IA separado (`/api/teaser/narration/generate`) com preview em player antes de renderizar o teaser.' },
      { type: 'feat', text: 'Teaser/Narração: agora aceita inserir áudio externo (upload) para usar no mix final, sem depender apenas de TTS.' },
      { type: 'feat', text: 'Teaser/Narração: adicionada sincronização por offset em segundos (adiantar/atrasar voz), além de persistência de `narration_object_key` no wizard.' },
      { type: 'fix', text: 'TTS: fallback automático para OpenAI (`token:openai`) quando a conta Grok Voice não tiver permissão (`Team is not authorized`).' },
      { type: 'fix', text: 'Presigned stream URL agora detecta áudio (`.mp3/.m4a/.wav/.ogg`) e retorna `ResponseContentType` correto para reprodução no player.' },
    ],
  },
  {
    version: 'v1.9.8', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Thumbnail IA (Grok Imagine): endpoint agora aplica fallback anti-moderação com prompt sanitizado e tentativas progressivas para reduzir erro "Generated image rejected by content moderation".' },
      { type: 'feat', text: 'Thumbnail IA: suporte real a image-to-image no backend usando `source_image_b64`/`image`, com controle de `strength` para manter coerência com o frame base.' },
      { type: 'feat', text: 'UI da thumbnail IA: feedback explícito quando fallback anti-moderação é usado e orientação automática quando o bloqueio de policy ocorrer.' },
    ],
  },
  {
    version: 'v1.9.7', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Passo 3 (Teaser): nova opção de narração IA opcional com texto livre, escolha de voz e controle de velocidade.' },
      { type: 'feat', text: 'Teaser: mix de áudio configurável (volume do áudio original + volume da narração) durante a renderização final.' },
      { type: 'feat', text: 'Configuração de narração do teaser agora persiste no wizard por run, mantendo parâmetros após refresh.' },
    ],
  },
  {
    version: 'v1.9.6', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Passo 4: novo gerador de thumbnail por IA (Grok Imagine) com prompt livre e geração de 2 versões para escolha.' },
      { type: 'feat', text: 'Thumbnail IA: ao escolher uma versão, ela vira a base do editor profissional por camadas para ajuste manual fino.' },
      { type: 'fix', text: 'Settings: backend agora aceita salvar tokens de `grok`, `groq` e `gemini` além de `openai/deepseek/openrouter`.' },
    ],
  },
  {
    version: 'v1.9.5', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Editor de thumbnail: corrigido botão Remover para camadas de legenda (não recria automaticamente após excluir).' },
      { type: 'fix', text: 'Editor de thumbnail: botão "Enviar para trás" com feedback quando o elemento já está no fundo ou quando não há outra camada para mover.' },
    ],
  },
  {
    version: 'v1.9.4', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Teaser: removida sobreposição extra de logo quando a fonte já é vídeo queimado, evitando duplicação da marca.' },
      { type: 'feat', text: 'Passo 4 (Thumbnail): editor profissional por camadas (logo opcional, imagem extra, textos), com seleção de elemento, ordem de camadas, opacidade, rotação e posicionamento fino por arraste.' },
      { type: 'feat', text: 'Thumbnail: logo não é mais queimada automaticamente; agora entra apenas como elemento editável quando você adicionar manualmente.' },
    ],
  },
  {
    version: 'v1.9.3', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Passo 3 (Teaser): seleção de fonte agora prioriza vídeos já queimados (logo+legenda), com picker de arquivos do run/geral e bloqueio de fallback para original.' },
      { type: 'feat', text: 'Concat teaser + principal agora permite escolher posição: início ou final do vídeo.' },
      { type: 'feat', text: 'Passo 4 (Thumbnail): editor avançado com crop/zoom, brilho, contraste, saturação, matiz e escala de saída 1x/2x/3x.' },
      { type: 'feat', text: 'Thumbnail: seleção de fonte de frame HQ em vídeos queimados + auto extração HQ ao abrir o passo quando há fonte definida.' },
    ],
  },
  {
    version: 'v1.9.2', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Passo 2: nova opção para selecionar um vídeo legendado já existente (do run atual ou de todos os `burns/`) e continuar o fluxo sem gerar novamente.' },
      { type: 'feat', text: 'Ao selecionar vídeo legendado existente, o Wizard já habilita "Continuar para Teaser" e persiste o `burned_object_key` no estado.' },
    ],
  },
  {
    version: 'v1.9.1', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Wizard agora persiste estado por run (`request_json.wizard_state`): passo atual, parâmetros e object keys são restaurados após refresh.' },
      { type: 'feat', text: 'Mídia já processada (burn/teaser/combinado) é reidratada automaticamente por `object_key`, evitando precisar reprocessar para continuar o fluxo.' },
      { type: 'feat', text: 'Passo da Logo ganhou presets reutilizáveis com seleção rápida e botão para salvar a configuração atual como padrão global.' },
    ],
  },
  {
    version: 'v1.9.0', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Editor SRT profissional no Passo 2: Find & Replace com contagem de ocorrências (3/12), prev/next, match case, substituir um ou todos.' },
      { type: 'feat', text: 'Atalhos de teclado no editor: Ctrl+H abre busca, F3/Shift+F3 navega ocorrências, Escape fecha o painel.' },
      { type: 'feat', text: 'Barra de ferramentas SRT: remover fillers (uh/ah/hmm/né/tipo), limpar espaços, renumerar entradas.' },
      { type: 'feat', text: 'Stats bar em tempo real: segmentos, palavras, caracteres. Status bar com linha e coluna do cursor.' },
    ],
  },
  {
    version: 'v1.8.9', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Wizard Passo 2: botão "Continuar para Teaser" agora habilita corretamente logo após concluir o burn (sem precisar recarregar a página).' },
      { type: 'fix', text: 'Wizard Passo 3: botão "Gerar Teaser" passa a habilitar também quando existe apenas `video_object_key` original do run, respeitando o fallback já suportado no backend.' },
    ],
  },
  {
    version: 'v1.8.8', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Fila de burn visível no Wizard: status agora mostra posição real (`queue_position/queue_size`) quando o job está aguardando processamento.' },
      { type: 'feat', text: 'Novo cancelamento de burn: botão "Cancelar" durante fila/processamento + endpoint backend para interromper job pendente ou em execução.' },
      { type: 'feat', text: 'Novo endpoint `/api/burn-subtitles/queue` para listar fila pendente e jobs em execução para diagnóstico operacional.' },
    ],
  },
  {
    version: 'v1.8.7', date: '2026-03-03',
    items: [
      { type: 'perf', text: 'Modo desempenho máximo ativado para burn: preset padrão `ultrafast` e `FFMPEG_BURN_THREADS=0` (ffmpeg usa todos os cores disponíveis).' },
      { type: 'perf', text: 'Backend do burn aceita presets mais agressivos (`ultrafast`, `superfast`) e passa a priorizar throughput bruto na geração do vídeo legendado.' },
      { type: 'perf', text: 'Swarm sem limite de memória para o serviço + `BURN_MAX_PARALLEL=1` para concentrar todos os recursos da máquina em um único processamento por vez.' },
    ],
  },
  {
    version: 'v1.8.6', date: '2026-03-02',
    items: [
      { type: 'feat', text: 'Tradução imediata de SRT: ao mudar o idioma no Passo 2, o SRT atual é traduzido na hora via Google Translate e aparece no editor para revisão humana antes de queimar.' },
      { type: 'feat', text: 'Novo endpoint POST /api/translate-srt: traduz SRT completo mantendo timestamps — sem necessidade de retranscrever.' },
    ],
  },
  {
    version: 'v1.8.5', date: '2026-03-02',
    items: [
      { type: 'fix', text: 'Preview da logo: fundo do preview agora é neutro (xadrez escuro) por padrão — a logo aparece isolada sem o vídeo atrás, com botão "Mostrar vídeo" para alternar.' },
      { type: 'fix', text: 'Teaser: corrigido erro "missing_video_object_key" quando o vídeo legendado ainda não existe — agora usa o vídeo original do upload como fallback.' },
    ],
  },
  {
    version: 'v1.8.4', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Estabilidade do burn-subtitles: jobs agora entram em fila no backend (limite de paralelismo) para evitar reinício do serviço em processamento pesado.' },
      { type: 'fix', text: 'FFmpeg do burn com controle de threads (`FFMPEG_BURN_THREADS`, padrão 2) para reduzir pico de memória e evitar erro 502 durante geração.' },
      { type: 'fix', text: 'Polling do burn mais resiliente: retries automáticos para falhas transitórias (502/503/504/rede) e mensagem clara quando o job se perde após reinício do serviço.' },
    ],
  },
  {
    version: 'v1.8.3', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Legenda no Wizard: seleção de idioma agora aplica tradução automática do SRT para o idioma escolhido e já deixa o texto no editor para correção humana.' },
      { type: 'feat', text: 'Transcribe API aceita `translate_to` e retorna metadados de idioma (`source_lang`, `target_lang`, `translated`) no transcript.' },
      { type: 'fix', text: 'Status da transcrição atualizado para refletir quando há tradução junto com a transcrição.' },
    ],
  },
  {
    version: 'v1.8.2', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Burn de legenda/logo com perfil de velocidade configurável (`x264_preset`: Equilibrado/rápido/turbo) para reduzir tempo de processamento sem alterar o fluxo.' },
      { type: 'feat', text: 'Wizard Passo 2: novo seletor "Velocidade de processamento" integrado ao backend do burn-subtitles.' },
      { type: 'chore', text: 'Padrão do burn ajustado para preset `fast` (mais rápido que `medium`) com fallback seguro para clientes antigos.' },
    ],
  },
  {
    version: 'v1.8.1', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Editor de logo profissional no Wizard: controle fino de posição, escala e opacidade com preview interativo e ajuste por arraste.' },
      { type: 'feat', text: 'Burn e teaser agora respeitam escala e opacidade da logo (`logo_scale_pct` e `logo_opacity`) para manter consistência visual em todo o fluxo.' },
      { type: 'feat', text: 'Thumbnail HQ: novo endpoint `/api/thumbnail/highres` para extrair frame em alta qualidade direto do vídeo (inclusive para runs antigos com screenshots comprimidos).' },
      { type: 'fix', text: 'Thumbnail export com qualidade máxima: opção PNG sem perda (padrão) e JPEG com controle de qualidade.' },
    ],
  },
  {
    version: 'v1.8.0', date: '2026-03-03',
    items: [
      { type: 'feat', text: 'Criação convertida para Wizard em 5 passos: Logo → Legenda → Teaser → Thumbnail → Post Final, com navegação por etapas e estado persistente entre passos.' },
      { type: 'feat', text: 'Teaser avançado: seleção manual de cenas baseada nos screenshots do run, mantendo controle de duração por cena e qualidade (CRF).' },
      { type: 'feat', text: 'Thumbnail final: geração com logo queimada + legenda da thumbnail (manual ou extraída da primeira linha do SRT).' },
      { type: 'feat', text: 'Post Final: visualização unificada de teaser e vídeo completo (legendado/concatenado), com opções de download e dados de publicação (título, descrição, tags, categorias).' },
      { type: 'feat', text: 'Backend teaser: endpoint `/api/teaser/generate` agora aceita `selected_frame_indexes` e `frames_count` para priorizar cenas escolhidas no wizard.' },
    ],
  },
  {
    version: 'v1.7.3', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Teaser automático: corrigido erro `Nenhum clip foi extraído` com fallback de extração sem áudio quando o ffmpeg falha no mapeamento/encode de áudio.' },
      { type: 'fix', text: 'Teaser: extração de cenas ficou mais tolerante (timeout maior por clip + preset `veryfast`) para vídeos pesados.' },
      { type: 'feat', text: 'Diagnóstico aprimorado no status do teaser: backend agora retorna detalhe real da primeira falha de ffmpeg e amostra de erros (`debug_failures`).' },
    ],
  },
  {
    version: 'v1.7.2', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Estabilidade teaser/burn: removidos bloqueios do event loop nos workers de teaser e concatenação (ffmpeg agora roda via `asyncio.to_thread`), evitando travamento global da API durante processamento.' },
      { type: 'fix', text: 'Erro intermitente 502 durante polling (`/api/teaser/status`, `/api/burn-subtitles/status`, `/health`) mitigado ao eliminar chamadas bloqueantes (`proc.wait`) em corrotinas assíncronas.' },
      { type: 'chore', text: 'Bump de versão para refletir correção de estabilidade em produção.' },
    ],
  },
  {
    version: 'v1.7.1', date: '2026-03-03',
    items: [
      { type: 'fix', text: 'Teaser automático: corrigido envio de `video_object_key` no frontend com fallback para a chave original do run quando ainda não existe vídeo legendado (resolve erro `missing_video_object_key`).' },
      { type: 'fix', text: 'Concat teaser + principal: payload do frontend ajustado para o contrato do backend (`teaser_object_key` e `main_object_key`).' },
      { type: 'chore', text: 'Bump de versão e atualização de cache-busting do app.js para garantir carregamento imediato da UI corrigida.' },
    ],
  },
  {
    version: 'v1.7.0', date: '2026-03-02',
    items: [
      { type: 'feat', text: 'Nova página "Referência": browser independente do XVideos com busca geral, por atriz/pornstar e por canal/studio — thumbnails, player inline, métricas (views/likes/duração).' },
      { type: 'feat', text: 'Editor Criação — posição da logo: sliders H% e V% (0=esquerda/topo, 100=direita/baixo) para posicionar a logo em qualquer ponto do vídeo legendado.' },
      { type: 'feat', text: 'Editor Criação — Teaser automático: extrai as N melhores cenas do vídeo (detecção por cenas) e gera um clip de destaque. Opção de baixar o teaser ou inclui-lo como introdução ao vídeo.' },
      { type: 'feat', text: 'Backend: GET /xvideos/pornstar e GET /xvideos/channel — endpoints dedicados para busca estruturada de pornstar/canal.' },
      { type: 'feat', text: 'Backend: POST /api/teaser/generate e GET /api/teaser/status/{job_id} — geração de teaser em background job.' },
      { type: 'feat', text: 'Backend: POST /api/teaser/prepend — concatena teaser + vídeo principal em background job (retorna vídeo combinado).' },
    ],
  },
  {
    version: 'v1.6.1', date: '2026-03-02',
    items: [
      { type: 'feat', text: 'Burn subtitles: seletor de Resolução (1080p/720p/Original) — padrão 1080p reduz arquivo em até 80% vs vídeos 4K originais.' },
      { type: 'feat', text: 'Burn subtitles: seletor de Qualidade/CRF (Boa CRF26 / Leve CRF30 / Alta CRF20) — "Leve" pode reduzir arquivo até 60% com qualidade visual similar.' },
      { type: 'fix',  text: 'Burn subtitles: preset trocado de ultrafast para medium — compressão muito melhor, arquivo menor com mesma qualidade visual.' },
    ],
  },
  {
    version: 'v1.6.0', date: '2026-03-02',
    items: [
      { type: 'fix',  text: 'Player em Criação: preload="none" em todos os players — browser não baixa o vídeo automaticamente, elimina travamento ao abrir a seção com vídeos grandes.' },
      { type: 'fix',  text: 'Download do vídeo legendado: trocado a.download (forçava download como Blob em memória — impossível para 10GB) por window.open, usando Content-Disposition:attachment da URL presigned.' },
      { type: 'feat', text: 'Novo endpoint GET /api/video-download-url: gera presigned URL fresca com Content-Disposition:attachment para qualquer objeto do MinIO.' },
      { type: 'feat', text: 'Botão "Baixar vídeo original" no player de Criação — download streaming direto do MinIO sem passar pelo backend.' },
    ],
  },
  {
    version: 'v1.5.9', date: '2026-03-02',
    items: [
      { type: 'fix',  text: 'XVideos — atriz/canal: em vez de adivinhar o slug, busca textualmente e extrai a URL real do perfil dos resultados. Resolve "Monica Matos" → /models/monica-mattos e canais como Bangbros.' },
      { type: 'fix',  text: 'Screenshots: removido redimensionamento para 640px, agora salva na resolução original com qualidade máxima JPEG (-q:v 2). Adequado para uso como thumbnail.' },
      { type: 'fix',  text: 'Upload chunked: pool contínuo (workers independentes) em vez de batch — cada conexão começa o próximo chunk imediatamente sem esperar a mais lenta do grupo.' },
    ],
  },
  {
    version: 'v1.5.8', date: '2026-03-02',
    items: [
      { type: 'fix', text: 'Upload chunked: chunks reduzidos de 100MB para 10MB para garantir que cada parte termine dentro do readTimeout de 60s do Traefik. 6 partes em paralelo mantêm velocidade máxima.' },
      { type: 'fix', text: 'Todo upload (qualquer tamanho) agora usa o chunked multipart — elimina 502 em vídeos grandes.' },
    ],
  },
  {
    version: 'v1.5.7', date: '2026-03-02',
    items: [
      { type: 'fix', text: 'Upload chunked: 4 partes de 100MB enviadas em paralelo (antes era 1 de 50MB sequencial). Reduz tempo de upload ~4× ao usar o link de internet ao máximo.' },
    ],
  },
  {
    version: 'v1.5.6', date: '2026-03-02',
    items: [
      { type: 'fix',  text: 'Upload de vídeos grandes (+5GB): implementado upload chunked em pedaços de 50MB via API multipart do MinIO. Elimina 502 Bad Gateway do Traefik causado por timeout em uploads lentos.' },
      { type: 'feat', text: 'Progresso por partes exibido durante upload chunked: "enviando parte X/Y (Z%)".' },
    ],
  },
  {
    version: 'v1.5.5', date: '2026-03-02',
    items: [
      { type: 'fix',  text: 'XVideos — lógica de busca refeita: filtros do usuário (país/categoria/qtd atores) SUBSTITUEM a query automática em vez de acumular, eliminando conflitos como "brasileira japonesa".' },
      { type: 'fix',  text: 'XVideos — modo automático (sem filtros) usa análise do vídeo; modo filtrado usa apenas filtros do usuário; pornstar/canal têm prioridade máxima.' },
    ],
  },
  {
    version: 'v1.5.4', date: '2026-03-02',
    items: [
      { type: 'fix',  text: 'XVideos — filtros completamente refeitos: duração usa SortVideoTime nativo da API (não mais texto ignorado), país mapeado para keywords EN reconhecidas pelo XVideos (ex: Brasil→"brasileira")' },
      { type: 'feat', text: 'XVideos — qtd de atores vira keyword semântica: Solo/Casal/Trio/Quarteto/Gangbang' },
      { type: 'feat', text: 'XVideos — Canal/Studio busca pela página estruturada do canal (fetch_channel_videos) igual ao pornstar, com fallback textual' },
      { type: 'feat', text: 'Pós-filtros de views mín/máx e curtidas mín aplicados sobre os resultados retornados (sem suporte nativo no XVideos)' },
      { type: 'refactor', text: 'UI: duração virou select de faixas (Qualquer/Curto/Médio/Longo/Muito longo), removidos campos comentários (sem suporte), país tem lista de sugestões (datalist)' },
    ],
  },
  {
    version: 'v1.5.3', date: '2026-03-02',
    items: [
      { type: 'feat', text: 'XVideos: quando "Atriz/Ator" preenchido, busca diretamente na página de pornstar do XVideos (slug URL) — muito mais preciso que busca textual' },
      { type: 'fix',  text: 'Timestamps em Runs e Criação agora mostram horário local do browser (pt-BR) em vez de UTC' },
      { type: 'feat', text: 'Legenda: novos controles antes do burn — tamanho da fonte (10–72), cor (Branco/Amarelo/Ciano/Laranja/Preto) e delay em segundos (+ atrasa / − adianta)' },
    ],
  },
  {
    version: 'v1.5.2', date: '2026-03-02',
    items: [
      { type: 'feat', text: 'Analyze: botão "Selecionar do servidor" lista vídeos já enviados ao MinIO para reutilizar sem novo upload' },
      { type: 'feat', text: 'Upload refeito como label clicável — sem botão separado, dispara automaticamente ao escolher arquivo' },
      { type: 'feat', text: 'Backend: GET /uploads/list lista objetos do prefix uploads/ com nome, tamanho e data' },
    ],
  },
  {
    version: 'v1.5.1', date: '2026-03-02',
    items: [
      { type: 'feat', text: 'Runs: botão "Buscar Referências Agora" para runs sem referências XVideos (timeout no analyze) — re-faz o scraping sem precisar reanalisar' },
      { type: 'fix',  text: 'Changelog atualizado com todas as versões v1.3.10→v1.5.1' },
    ],
  },
  {
    version: 'v1.5.0', date: '2026-03-02',
    items: [
      { type: 'feat', text: 'Transcrição local com faster-whisper (modelo small, 465MB) — sem API key, sem censura, roda 100% no servidor' },
      { type: 'fix',  text: 'Frames de vision reduzidos para 640px (era 1920px) — reduz uso de RAM ~9x durante análise' },
      { type: 'fix',  text: 'Limite de memória Docker: 2GB para evitar que OOM killer derrube outros serviços do servidor' },
    ],
  },
  {
    version: 'v1.4.4', date: '2026-03-02',
    items: [
      { type: 'feat', text: 'Burn subtitles: player de vídeo embutido no resultado — assista o vídeo legendado sem precisar baixar' },
      { type: 'fix',  text: 'Settings: token "groq" adicionado à lista de providers (estava faltando, impedia configurar Groq Whisper)' },
    ],
  },
  {
    version: 'v1.4.3', date: '2026-03-02',
    items: [
      { type: 'fix',  text: 'burnSubtitlesReupload(): upload via proxy backend (era presigned PUT direto ao MinIO — CORS bloqueava)' },
    ],
  },
  {
    version: 'v1.4.2', date: '2026-03-02',
    items: [
      { type: 'fix',  text: 'Upload inicial do vídeo (uploadVideo) migrado para /uploads/proxy — elimina erro CORS do MinIO no presigned PUT direto' },
    ],
  },
  {
    version: 'v1.4.1', date: '2026-03-02',
    items: [
      { type: 'fix',  text: 'Criação: Vision — Análise Visual voltou a aparecer após reescrita do renderCriacaoDetail (regressão v1.4.0)' },
      { type: 'fix',  text: 'criacaoState: adicionados campos visionAnalysis e _reqData que estavam faltando' },
    ],
  },
  {
    version: 'v1.4.0', date: '2026-03-02',
    items: [
      { type: 'feat', text: 'Criação: Compare → botão "Usar esta versão" aplica texto da comparação diretamente no Criação' },
      { type: 'feat', text: 'Criação: logo agora é queimada no vídeo via ffmpeg filter_complex (era só no preview do browser)' },
      { type: 'feat', text: 'Criação: seleção manual de frame/thumbnail — clique em qualquer frame da grid para escolher' },
      { type: 'feat', text: 'Criação: transcrição com Groq Whisper (whisper-large-v3-turbo) como alternativa ao OpenAI' },
      { type: 'feat', text: 'Criação: editor de transcrição SRT com salvar, baixar e reprocessar — transcrição não muda mais a cada analyze' },
      { type: 'feat', text: 'Backend: PUT /runs/{id}/transcript — salva transcrição editada no run' },
    ],
  },
  {
    version: 'v1.3.11', date: '2026-03-01',
    items: [
      { type: 'fix',  text: 'ffmpeg deadlock corrigido: stderr redirecionado para arquivo (era PIPE) — burn não trava mais em 10%' },
      { type: 'fix',  text: 'Preset ffmpeg: ultrafast -crf 23 (era fast -crf 18) — burn 3× mais rápido' },
    ],
  },
  {
    version: 'v1.3.10', date: '2026-03-01',
    items: [
      { type: 'fix',  text: 'Vídeo não é mais deletado após analyze — burn-subtitles sempre encontra o arquivo no MinIO sem precisar de re-upload (elimina fluxo CORS)' },
    ],
  },
  {
    version: 'v1.3.9', date: '2026-03-01',
    items: [
      { type: 'fix',  text: 'Backend: burn-subtitles agora retorna job_id imediatamente (background job) — elimina timeout de 30 min no Traefik durante ffmpeg' },
      { type: 'fix',  text: 'Frontend: burnSubtitles() inicia job e delega para _pollBurnJob() que faz polling a cada 3s até concluir ou dar erro' },
      { type: 'fix',  text: 'Novo endpoint GET /api/burn-subtitles/status/{job_id} retorna {status, detail, video_url, filename}' },
    ],
  },
  {
    version: 'v1.3.8', date: '2026-03-01',
    items: [
      { type: 'fix',  text: 'Backend: após ffmpeg, resultado é enviado ao MinIO (burns/) e retorna presigned URL (1h) — elimina streaming de vídeo grande pelo Traefik (resolvia ERR_FAILED por timeout de resposta)' },
      { type: 'fix',  text: 'Frontend: burnSubtitles() agora trata resposta JSON {ok, video_url} (novo caminho S3) e blob binário (fallback) separadamente' },
      { type: 'fix',  text: 'downloadBurnedVideo() e player usam criacaoState.burnedVideoUrl em vez de burnedBlobUrl' },
    ],
  },
  {
    version: 'v1.3.7', date: '2026-03-01',
    items: [
      { type: 'fix',  text: 'Criação: vídeo original é apagado após /analyze — burn-subtitles agora detecta (410 video_deleted) e mostra re-upload com PUT direto ao MinIO (sem passar pelo Traefik)' },
      { type: 'fix',  text: 'Backend: /api/burn-subtitles aceita video_object_key opcional para re-upload; limpa objeto temporário após queima' },
      { type: 'feat', text: 'Frontend: burnSubtitlesReupload() — upload com barra de progresso (XHR) → presigned PUT → burn' },
    ],
  },
  {
    version: 'v1.3.6', date: '2026-03-01',
    items: [
      { type: 'fix',  text: 'Criação: "Gerar versão legendada" não exige mais upload do vídeo pelo browser — o servidor baixa diretamente do MinIO (resolve ERR_FAILED por limite de body no Traefik)' },
      { type: 'fix',  text: 'Backend: /api/burn-subtitles agora aceita JSON {run_id} em vez de multipart/form-data; baixa vídeo via S3 SDK (httpx como fallback)' },
    ],
  },
  {
    version: 'v1.3.1', date: '2026-03-01',
    items: [
      { type: 'feat', text: 'Criação: seção "PREVIEW NO XVIDEOS (SIMULAÇÃO)" — player 16:9 com thumbnail + logo overlay + título/descrição/tags no layout do XVideos' },
      { type: 'feat', text: 'Criação: logo carregada pelo usuário aparece simultaneamente no preview E na thumbnail canvas' },
      { type: 'feat', text: 'Criação: botão "Baixar SRT" — gera arquivo de legenda a partir da transcrição Whisper do run' },
      { type: 'feat', text: 'Criação: botão "Gerar versão legendada" — queima legenda no vídeo via ffmpeg no servidor e oferece download .mp4' },
      { type: 'feat', text: 'Backend: GET /runs/{id}/srt — download do arquivo SRT gerado a partir dos segmentos Whisper' },
      { type: 'feat', text: 'Backend: POST /api/burn-subtitles — aceita vídeo + run_id, queima legenda com libx264 -crf 18, retorna .mp4' },
      { type: 'fix',  text: 'Frames: qualidade melhorada para -q:v 2 (era 4) + resolução máxima 1920px via scale filter' },
    ],
  },
  {
    version: 'v1.3.0', date: '2026-03-01',
    items: [
      { type: 'feat', text: 'Nova aba "Criação": gera post XVideos completo (título, descrição, tags, hook) a partir da análise Vision do run' },
      { type: 'feat', text: 'Endpoint POST /api/create-post via Grok 3 (fallback Grok 2) com response_format JSON' },
      { type: 'feat', text: 'Thumbnail com overlay de logo: Canvas API desenha frame recomendado + logo carregada pelo usuário' },
      { type: 'feat', text: 'Agendamento de posts: POST /api/scheduled-posts + GET + PATCH status (pending/cancelled)' },
      { type: 'feat', text: 'Vision Prompts 1 e 2 refinados: ênfase em detalhes explícitos de cenas, atos, posições, fetiches e contexto' },
    ],
  },
  {
    version: 'v1.2.2', date: '2026-03-01',
    items: [
      { type: 'fix',   text: 'Ollama: timeout aumentado para 720s (12 min) — cobre geração de 1024 tokens no CPU @ 3 tok/s' },
      { type: 'fix',   text: 'Ollama: prompt truncado para ≤3800 tokens antes de enviar — evita corte silencioso pelo modelo' },
      { type: 'fix',   text: 'Ollama: limite de output fixado em 1024 tokens via num_predict para evitar loop infinito' },
      { type: 'feat',  text: 'Compare: aviso ao usar modelo local — "pode levar 5-15 min no CPU"' },
    ],
  },
  {
    version: 'v1.2.1', date: '2026-03-01',
    items: [
      { type: 'fix',  text: 'Ollama: timeout aumentado de 60s para 300s — corrige erro de timeout no cold start (modelo carregando do disco)' },
      { type: 'feat', text: 'Runs: preview inline de vídeo nas referências — clique na thumbnail para assistir o clip sem sair da plataforma' },
      { type: 'fix',  text: 'Runs: frames Vision IA agora exibem corretamente (prefixo data:image/jpeg;base64 faltando)' },
      { type: 'fix',  text: 'Runs: descrição Vision IA com formatação correta (white-space:pre-wrap + fallback para debug info)' },
      { type: 'feat', text: 'Runs: cards de referência redesenhados com thumbnail 16:9, overlay de play e ↗ link externo' },
    ],
  },
  {
    version: 'v1.2.0', date: '2026-03-01',
    items: [
      { type: 'feat', text: 'Runs: nova visualização detalhada com sidebar + painel de detalhes' },
      { type: 'feat', text: 'Runs: galeria de frames Vision IA com visualização em tela cheia' },
      { type: 'feat', text: 'Runs: cards de referência XVideos com thumbnail e link direto ao vídeo' },
      { type: 'feat', text: 'Runs: seleção de referências com checkboxes + recálculo de prompt' },
      { type: 'feat', text: 'Runs: descrição consolidada da análise Vision IA visível no painel' },
      { type: 'feat', text: 'Backend: endpoint POST /runs/{id}/reprompt para regenerar prompt com referências filtradas' },
      { type: 'fix',  text: 'Ollama: OLLAMA_MAX_LOADED_MODELS=1 + OLLAMA_KEEP_ALIVE=5m no systemd para evitar OOM com múltiplos runners' },
    ],
  },
  {
    version: 'v1.1.6', date: '2026-03-01',
    items: [
      { type: 'fix',   text: 'Ollama: exibe mensagem real de erro (ex: memória insuficiente) em vez de HTTPStatusError genérico' },
      { type: 'chore', text: 'Lista de modelos Ollama atualizada — removido llama3.3 (40 GB, inviável), adicionados modelos leves ≤4 GB' },
      { type: 'chore', text: 'Bump de versão' },
    ],
  },
  {
    version: 'v1.1.5', date: '2026-03-01',
    items: [
      { type: 'fix',   text: 'Hotfix crítico: corrigido erro "name \'probe\' is not defined" que quebrava toda a análise' },
      { type: 'fix',   text: 'OpenRouter: captura body real do erro HTTP (404/429) em vez de raise_for_status genérico' },
      { type: 'chore', text: 'Modelos OpenRouter atualizados — removidos IDs quebrados/404, mantidos apenas confirmados OK' },
      { type: 'feat',  text: 'Mensagem amigável para erro 404 de modelo não encontrado/removido no provedor' },
    ],
  },
  {
    version: 'v1.1.4', date: '2026-03-01',
    items: [
      { type: 'feat',  text: 'Busca de referências XVideos reescrita com query inteligente: idioma→nacionalidade, etnia, categoria, ato específico' },
      { type: 'feat',  text: 'Filtro de duração automático nas referências (±30% da duração real do vídeo)' },
    ],
  },
  {
    version: 'v1.1.3', date: '2026-03-01',
    items: [
      { type: 'fix',   text: 'Ollama local funcionando em Docker: OLLAMA_HOST=0.0.0.0 no serviço systemd' },
      { type: 'chore', text: 'OLLAMA_BASE_URL aponta para 172.20.0.1:11434 (docker_gwbridge) no Dockerfile' },
    ],
  },
  {
    version: 'v1.1.2', date: '2026-02-28',
    items: [
      { type: 'feat',  text: 'Vision Prompts 1 e 2 reescritos: "Versão Técnica + Putão" — precisão técnica + linguagem explícita brasileira' },
    ],
  },
  {
    version: 'v1.1.1', date: '2026-02-28',
    items: [
      { type: 'feat',  text: 'Toda pipeline automática (Vision) migrada de OpenAI para Grok (grok-2-vision-1212, 🔞 9/10)' },
      { type: 'feat',  text: 'Settings: campos de token para Grok e Gemini' },
      { type: 'chore', text: 'Modelos na Compare atualizados com score 🔞 e tags pago/free/local' },
    ],
  },
  {
    version: 'v1.1.0', date: '2026-02-28',
    items: [
      { type: 'feat',  text: 'Adicionados provedores Grok (xAI) e Gemini (Google) na Compare' },
      { type: 'feat',  text: 'Tags [free⚡] / [$] / [local] nos modelos da Compare' },
      { type: 'feat',  text: 'Score de permissividade adulta 🔞 0-10 em cada modelo' },
      { type: 'feat',  text: 'Vision Prompts 1 e 2 substituídos por versão "putão" explícita' },
    ],
  },
  {
    version: 'v1.0.9', date: '2026-02-27',
    items: [
      { type: 'feat',  text: 'Prompt LLM de geração de metadata reescrito — persona copywriter de putaria brasileira' },
    ],
  },
];

const MP_OS_ICON_PATHS = {
  bolt: '<path d="M13 2 4 14h7l-1 8 9-13h-7z"/>',
  analyze: '<circle cx="11" cy="11" r="6.5"/><path d="m20.5 20.5-4-4"/><path d="M11 8v6M8 11h6"/>',
  compare: '<path d="M12 3v18"/><path d="M7 7 3 12l4 5M17 7l4 5-4 5"/>',
  runs: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9h18M7 13h6M7 16.5h9"/><circle cx="6" cy="6.5" r=".6" fill="currentColor"/>',
  media: '<rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 6l2.4-2.6h6L14 6"/><circle cx="12" cy="12.5" r="3"/>',
  refs: '<circle cx="11" cy="11" r="6.5"/><path d="m20.5 20.5-4-4M11 8l1 2 2 .3-1.5 1.5.4 2-1.9-1-1.9 1 .4-2L8 10.3l2-.3z"/>',
  flow: '<path d="M6 5a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM18 5a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM12 15a2 2 0 1 1 0 4 2 2 0 0 1 0-4z"/><path d="M8 7h6M7.5 8.5 11 15M16.5 8.5 13 15"/>',
  autoeditor: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3 9h18M8 5v4M16 5v4"/><path d="m10.5 12.5 4 2-4 2z" fill="currentColor"/>',
  enhance: '<path d="M5 12h3l2-7 3 14 2-7h4"/><path d="M19 4l.7 1.8L21.5 6.5l-1.8.7L19 9l-.7-1.8L16.5 6.5l1.8-.7z" fill="currentColor"/>',
  captions: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 10h4M13 10h3M7 14h6M15 14h2"/>',
  logo: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 15l3-3 2 2 2-3 3 4"/><circle cx="9" cy="9" r="1.2"/>',
  scissors: '<path d="M4 7a2.5 2.5 0 1 0 4 2M4 17a2.5 2.5 0 1 0 4-2M20 4 8 14M20 20 8 10"/>',
  thumbnail: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 15l3-3 2 2 3-4 3 5"/>',
  post: '<path d="M5 3h10l4 4v14H5z"/><path d="M9 9h6M9 13h6M9 17h4"/>',
  telegram: '<path d="M21 4 3 11l5 2 2 6 3-4 4 3z"/><path d="m8 13 8-6-5 7"/>',
  broadcast: '<circle cx="12" cy="12" r="2.4"/><path d="M7.5 7.5a6 6 0 0 0 0 9M16.5 7.5a6 6 0 0 1 0 9M5 5a9 9 0 0 0 0 14M19 5a9 9 0 0 1 0 14"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="16" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/><rect x="7" y="13" width="3.5" height="3.5" rx="1"/>',
  users: '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 5.2a3 3 0 0 1 0 5.6M16.5 19a5.5 5.5 0 0 0-2-4.3"/>',
  trending: '<path d="M3 16l5-5 3 3 7-7"/><path d="M15 7h5v5"/>',
  dollar: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v10M14.5 9.3a2.6 2.6 0 0 0-2.5-1.3c-1.5 0-2.5.8-2.5 2s1 1.7 2.5 2 2.5.7 2.5 2-1 2-2.5 2a2.6 2.6 0 0 1-2.5-1.3"/>',
  shield: '<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6z"/><path d="m9 12 2 2 4-4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.4M12 18.6V21M4.5 7l2 1.2M17.5 15.8l2 1.2M19.5 7l-2 1.2M6.5 15.8l-2 1.2"/>',
};

const MP_OS_ROUTE_ICONS = {
  analyze: 'analyze',
  compare: 'compare',
  runs: 'runs',
  media: 'media',
  referencia: 'refs',
  autoeditor: 'autoeditor',
  videoenhancer: 'enhance',
  criacao: 'post',
  telegram: 'telegram',
  publisher: 'broadcast',
  calendar: 'calendar',
  creators: 'users',
  trends: 'trending',
  financial: 'dollar',
  dmca: 'shield',
  settings: 'settings',
};

function mpOsSvgIcon(name) {
  const path = MP_OS_ICON_PATHS[name] || '';
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

function paintMetaPornOsIcons() {
  document.querySelectorAll('a[data-route]').forEach(a => {
    const iconName = a.dataset.osIcon || MP_OS_ROUTE_ICONS[a.dataset.route];
    if (!iconName) return;
    const navIcon = a.querySelector('.nav-icon');
    if (navIcon && navIcon.dataset.osPainted !== '1') {
      navIcon.innerHTML = mpOsSvgIcon(iconName);
      navIcon.dataset.osPainted = '1';
    }
    const pinIcon = a.querySelector('.pin-ic');
    if (pinIcon && pinIcon.dataset.osPainted !== '1') {
      pinIcon.innerHTML = mpOsSvgIcon(iconName);
      pinIcon.dataset.osPainted = '1';
    }
  });

  document.querySelectorAll('[data-start-icon]').forEach(el => {
    if (el.dataset.osPainted === '1') return;
    el.innerHTML = mpOsSvgIcon(el.dataset.startIcon);
    el.dataset.osPainted = '1';
  });
}

function osToggleStart(force) {
  const menu = document.getElementById('osStartMenu');
  if (!menu) return;
  const shouldOpen = typeof force === 'boolean' ? force : menu.getAttribute('aria-hidden') === 'true';
  menu.setAttribute('aria-hidden', shouldOpen ? 'false' : 'true');
  document.body.classList.toggle('os-start-open', shouldOpen);
  if (shouldOpen) {
    paintMetaPornOsIcons();
    setTimeout(() => document.getElementById('osStartSearch')?.focus(), 40);
  }
}

function osCloseStart() {
  const menu = document.getElementById('osStartMenu');
  if (!menu) return;
  menu.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('os-start-open');
}

function osFilterStartMenu() {
  const query = (document.getElementById('osStartSearch')?.value || '').trim().toLowerCase();
  document.querySelectorAll('.os-start-app[data-start-route]').forEach(a => {
    const hiddenByAuth = a.dataset.authHidden === '1';
    const text = (a.textContent || '').toLowerCase();
    const hiddenBySearch = query && !text.includes(query);
    a.style.display = hiddenByAuth || hiddenBySearch ? 'none' : '';
  });
}

function osRestoreWindow() {
  document.body.classList.remove('os-window-hidden');
}

function osShowDesktopHome() {
  document.body.classList.add('os-window-hidden', 'os-desktop-home');
  osCloseStart();
  document.querySelectorAll('a[data-route], .os-start-app[data-start-route]').forEach(a => {
    a.classList.remove('active');
  });
}

function osMinimizeWindow() {
  document.body.classList.add('os-window-hidden');
  osCloseStart();
}

function osCloseWindow() {
  document.body.classList.add('os-window-hidden');
  osCloseStart();
}

function osSyncShellRoute(name) {
  document.body.classList.remove('os-desktop-home');
  osRestoreWindow();
  osCloseStart();
  document.querySelectorAll('.os-start-app[data-start-route]').forEach(a => {
    a.classList.toggle('active', a.dataset.startRoute === name);
  });
}

function osApplyStartMenuVisibility(user) {
  const perms = user ? (user.permissions || []) : [];
  document.querySelectorAll('.os-start-app[data-start-route]').forEach(a => {
    a.dataset.authHidden = (!user || !perms.includes(a.dataset.startRoute)) ? '1' : '0';
  });
  osFilterStartMenu();
}

function renderChangelog() {
  const wrap = qs('changelogList');
  if (!wrap) return;
  wrap.innerHTML = '';
  CHANGELOG.forEach((entry, i) => {
    const div = document.createElement('div');
    div.className = 'cl-entry' + (i === 0 ? ' latest' : '');
    const items = entry.items.map(it =>
      `<li class="${it.type}">${it.text}</li>`
    ).join('');
    div.innerHTML = `
      <div class="cl-version">${entry.version}</div>
      <div class="cl-date">${entry.date}</div>
      <ul class="cl-items">${items}</ul>
    `;
    wrap.appendChild(div);
  });
}

// ── REFERÊNCIA ───────────────────────────────────────────────────────────────
function updateRefSearchType() {
  const t = qs('refSearchType')?.value;
  const labelEl = qs('refSearchLabel');
  const sortCol = qs('refSortCol');
  const hint = qs('refSearchHint');
  if (!t) return;
  if (t === 'search') {
    if (labelEl) labelEl.textContent = 'Query / Termo';
    if (sortCol) sortCol.style.display = '';
    if (hint) hint.textContent = 'Busca geral com filtros nativos do XVideos';
  } else if (t === 'pornstar') {
    if (labelEl) labelEl.textContent = 'Nome da Atriz / Pornstar';
    if (sortCol) sortCol.style.display = 'none';
    if (hint) hint.textContent = 'Busca pela página estruturada da pornstar — muito mais precisa que busca textual';
  } else if (t === 'channel') {
    if (labelEl) labelEl.textContent = 'Nome do Canal / Studio';
    if (sortCol) sortCol.style.display = 'none';
    if (hint) hint.textContent = 'Busca pela página estruturada do canal/studio';
  }
}

async function doRefSearch() {
  const type = qs('refSearchType')?.value || 'search';
  const query = (qs('refSearchQuery')?.value || '').trim();
  if (!query) return toast('Digite o que buscar', 'bad');
  const sort = qs('refSearchSort')?.value || 'views';
  const limit = parseInt(qs('refSearchLimit')?.value || '20', 10);
  const area = qs('refSearchResults');
  const btn  = qs('btnRefSearch');

  if (btn) { btn.disabled = true; btn.textContent = 'Buscando…'; }
  area.innerHTML = '<div class="hint" style="padding:28px;text-align:center;">⏳ Buscando no XVideos… (pode levar alguns segundos)</div>';

  try {
    let res, sourceInfo;
    if (type === 'search') {
      res = await apiFetch(`/xvideos/search?query=${encodeURIComponent(query)}&limit=${limit}&sort=${sort}`);
      sourceInfo = `Busca geral: "${query}" · sort: ${sort}`;
    } else if (type === 'pornstar') {
      res = await apiFetch(`/xvideos/pornstar?name=${encodeURIComponent(query)}&limit=${limit}`);
      sourceInfo = res?.pornstar_url ? `Pornstar URL: ${res.pornstar_url}` : `Busca textual: "${query}"`;
    } else {
      res = await apiFetch(`/xvideos/channel?name=${encodeURIComponent(query)}&limit=${limit}`);
      sourceInfo = res?.channel_url ? `Canal URL: ${res.channel_url}` : `Busca textual: "${query}"`;
    }

    const videos = res?.videos || [];
    if (!videos.length) {
      area.innerHTML = `<section class="card"><div class="criacao-empty">Nenhum resultado para "${esc(query)}"</div></section>`;
      return;
    }

    area.innerHTML = `
      <section class="card">
        <div class="refs-actions">
          <h2>${videos.length} vídeo(s)</h2>
          <span class="hint" style="font-size:11px;flex:1;">${esc(sourceInfo)}</span>
        </div>
        <div class="refs-grid">
          ${videos.map(v => renderRefCard(v)).join('')}
        </div>
      </section>
    `;
    toast(`${videos.length} vídeos encontrados`);
  } catch (e) {
    area.innerHTML = `<section class="card"><div class="hint" style="color:var(--bad);">Erro: ${esc(e.message)}</div></section>`;
    toast('Erro: ' + e.message, 'bad');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Buscar'; }
  }
}

// ANALYZE
let analyzeTab = 'prompt';
function setAnalyzeTab(name) {
  analyzeTab = name;
  document.querySelectorAll('#page-analyze .tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  qs('anPrompt').classList.toggle('hidden', name !== 'prompt');
  qs('anSrtMain').classList.toggle('hidden', name !== 'srt');
  qs('anVision').classList.toggle('hidden', name !== 'vision');
  qs('anJson').classList.toggle('hidden', name !== 'json');
}

let _uploadListVisible = false;

async function toggleUploadList() {
  const area = qs('anUploadList');
  if (!area) return;
  _uploadListVisible = !_uploadListVisible;
  area.classList.toggle('hidden', !_uploadListVisible);
  if (_uploadListVisible) await loadUploadList();
}

async function loadUploadList() {
  const area = qs('anUploadList');
  if (!area) return;
  area.innerHTML = '<div style="padding:8px;color:var(--muted)">Carregando…</div>';
  try {
    const res = await apiFetch('/uploads/list?max_keys=100');
    if (res.error) throw new Error(res.detail || res.error);
    const items = res.items || [];
    if (!items.length) {
      area.innerHTML = '<div style="padding:8px;color:var(--muted)">Nenhum vídeo no servidor ainda.</div>';
      return;
    }
    area.innerHTML = items.map(it => {
      const date = it.last_modified ? it.last_modified.slice(0,10) : '';
      const fname = esc(it.filename);
      const key   = esc(it.object_key);
      const keyJson = JSON.stringify(String(it.object_key || ''));
      const urlJson = JSON.stringify(String(it.public_url || ''));
      const nameJson = JSON.stringify(String(it.filename || ''));
      return `<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;border-bottom:1px solid var(--border);">
        <div style="flex:1;min-width:0;">
          <div style="font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${key}">${fname}</div>
          <div style="font-size:11px;color:var(--muted)">${it.size_mb} MB · ${date}</div>
        </div>
        <button class="btn" style="font-size:11px;padding:3px 8px;white-space:nowrap;"
          onclick='selectExistingVideo(${keyJson},${urlJson},${nameJson})'>Usar</button>
        <button class="btn" style="font-size:11px;padding:3px 8px;white-space:nowrap;"
          onclick='validateStoredVideo(${keyJson})'>Validar</button>
        <button class="btn" style="font-size:11px;padding:3px 8px;white-space:nowrap;"
          onclick='deleteStoredObject(${keyJson}, { label: ${nameJson}, refresh: true })'>Excluir</button>
      </div>`;
    }).join('');
  } catch(e) {
    area.innerHTML = `<div style="padding:8px;color:var(--bad)">Erro: ${esc(e.message)}</div>`;
  }
}

async function validateStoredVideo(objectKey, opts = {}) {
  const key = _normalizeObjectKeyish(objectKey);
  if (!key) throw new Error('object_key inválido para validação');
  const payload = {
    object_key: key,
    delete_if_invalid: !!opts.deleteIfInvalid,
  };
  const headers = { 'Content-Type': 'application/json' };
  if (state.apiKey) headers['X-API-Key'] = state.apiKey;
  const res = await fetch('/uploads/validate', {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok && res.status !== 422) {
    throw new Error(data.detail || data.error || `Erro ${res.status}`);
  }
  if (res.status === 422 || data.valid === false) {
    const msg = data.detail || 'O vídeo falhou na validação.';
    if (!opts.silent) toast(msg, 'bad');
    return { ok: false, ...data };
  }
  if (!opts.silent) toast(data.detail || 'Vídeo validado com sucesso', 'good');
  return { ok: true, ...data };
}

async function deleteStoredObject(objectKey, opts = {}) {
  const key = _normalizeObjectKeyish(objectKey);
  if (!key) return toast('object_key inválido', 'bad');
  const label = String(opts.label || key);
  if (!confirm(`Excluir do storage?\n\n${label}`)) return;
  try {
    await apiFetch(`/uploads/object?object_key=${encodeURIComponent(key)}`, { method: 'DELETE' });
    if (state.videoObjectKey === key) {
      state.videoObjectKey = null;
      state.videoUrl = null;
      qs('anObjectKey').textContent = '-';
      qs('anVideoUrl').textContent = '-';
      qs('anUploadStatus').textContent = 'status: vídeo removido do storage';
      _resetAnalyzeUploadProgress();
    }
    if (opts.refresh) await loadUploadList();
    toast('Arquivo excluído do storage', 'good');
  } catch (e) {
    toast('Erro ao excluir: ' + e.message, 'bad');
  }
}

async function selectExistingVideo(objectKey, publicUrl, filename) {
  try {
    _resetAnalyzeUploadProgress();
    qs('anUploadStatus').textContent = 'status: validando vídeo no storage…';
    const validation = await validateStoredVideo(objectKey, { silent: true });
    if (!validation.ok) {
      qs('anUploadStatus').textContent = `status: vídeo inválido — ${validation.detail || validation.error || 'falha na validação'}`;
      return;
    }

    state.videoObjectKey = objectKey;
    state.videoUrl       = publicUrl;
    qs('anObjectKey').textContent = objectKey;
    qs('anVideoUrl').textContent  = publicUrl;
    // Oculta a lista após seleção
    _uploadListVisible = false;
    qs('anUploadList').classList.add('hidden');
    state.videoOriginalFilename = filename || '';
    qs('anUploadStatus').textContent = `status: vídeo selecionado (${filename}) — escolha abaixo como transcrever`;
    transcribeProgress.hide();
    toast(`Vídeo selecionado: ${filename}`);
  } catch(e) {
    qs('anUploadStatus').textContent = `status: erro ao selecionar vídeo — ${e.message}`;
    toast(e.message, 'bad');
  }
}

function _mediaCategoryLabel(category) {
  if (category === 'burns') return 'Queimado';
  if (category === 'teasers') return 'Teaser';
  return 'Original';
}

function _formatMediaClock(seconds) {
  const safe = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = safe % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function _mediaMetadataForItem(item) {
  const key = String(item?.object_key || '').trim();
  const cached = key ? (mediaManagerState.metadataCache[key] || {}) : {};
  const raw = item?.metadata || item?.probe || {};
  const meta = { ...raw, ...cached };
  const duration = Number(meta.duration_seconds || item?.duration_seconds || 0);
  const width = Number(meta.width || item?.width || 0);
  const height = Number(meta.height || item?.height || 0);
  const fps = Number(meta.avg_fps || meta.fps || item?.fps || 0);
  const hasAudio = meta.has_audio != null ? !!meta.has_audio : null;
  return {
    duration,
    durationLabel: duration > 0 ? _formatMediaClock(duration) : '--:--',
    width,
    height,
    resolutionLabel: width && height ? `${width}×${height}` : 'resolução...',
    fps,
    fpsLabel: fps > 0 ? `${Number(fps).toFixed(fps >= 50 ? 2 : 0)} fps` : 'fps...',
    hasAudio,
    audioLabel: hasAudio == null ? 'áudio...' : (hasAudio ? 'com áudio' : 'sem áudio'),
  };
}

function _mediaSelectedSet() {
  return new Set((mediaManagerState.selectedKeys || []).map(v => String(v || '').trim()).filter(Boolean));
}

function _setMediaSelectedSet(setLike) {
  mediaManagerState.selectedKeys = Array.from(setLike || []).map(v => String(v || '').trim()).filter(Boolean);
}

function _inlineJsonArg(value) {
  return JSON.stringify(String(value ?? ''))
    .replace(/&/g, '\\u0026')
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/'/g, '\\u0027');
}

function _mediaTileAspectRatio(shape = mediaManagerState.tileShape) {
  if (shape === '4x3') return '4 / 3';
  if (shape === '1x1') return '1 / 1';
  if (shape === 'poster') return '2 / 3';
  return '16 / 9';
}

function _syncMediaManagerViewControls() {
  const mode = mediaManagerState.viewMode === 'list' ? 'list' : 'icons';
  const size = Math.max(140, Math.min(parseInt(mediaManagerState.tileSize || 190, 10) || 190, 340));
  const shape = ['16x9', '4x3', '1x1', 'poster'].includes(mediaManagerState.tileShape) ? mediaManagerState.tileShape : '16x9';
  mediaManagerState.viewMode = mode;
  mediaManagerState.tileSize = size;
  mediaManagerState.tileShape = shape;

  const btnIcons = qs('btnMediaViewIcons');
  const btnList = qs('btnMediaViewList');
  if (btnIcons) btnIcons.classList.toggle('primary', mode === 'icons');
  if (btnList) btnList.classList.toggle('primary', mode === 'list');

  const sizeEl = qs('mediaManagerTileSize');
  const sizeLabel = qs('mediaManagerTileSizeLabel');
  const shapeEl = qs('mediaManagerTileShape');
  if (sizeEl) sizeEl.value = String(size);
  if (sizeLabel) sizeLabel.textContent = `${size}px`;
  if (shapeEl) shapeEl.value = shape;
}

function _applyMediaManagerGridStyle() {
  const listEl = qs('mediaManagerList');
  if (!listEl) return;
  listEl.style.setProperty('--media-tile-size', `${mediaManagerState.tileSize || 190}px`);
  listEl.style.setProperty('--media-tile-ratio', _mediaTileAspectRatio());
}

function setMediaManagerViewMode(mode) {
  mediaManagerState.viewMode = mode === 'list' ? 'list' : 'icons';
  _safeStorageSet('mediaManagerViewMode', mediaManagerState.viewMode);
  _syncMediaManagerViewControls();
  renderMediaManagerList();
}

function setMediaManagerTileSize(value) {
  mediaManagerState.tileSize = Math.max(140, Math.min(parseInt(value || 190, 10) || 190, 340));
  _safeStorageSet('mediaManagerTileSize', mediaManagerState.tileSize);
  _syncMediaManagerViewControls();
  _applyMediaManagerGridStyle();
}

function setMediaManagerTileShape(shape) {
  mediaManagerState.tileShape = ['16x9', '4x3', '1x1', 'poster'].includes(shape) ? shape : '16x9';
  _safeStorageSet('mediaManagerTileShape', mediaManagerState.tileShape);
  _syncMediaManagerViewControls();
  _applyMediaManagerGridStyle();
}

function _getMediaManagerFilteredItems() {
  const search = String(mediaManagerState.search || '').trim().toLowerCase();
  const selectedCategory = mediaManagerState.category || 'all';
  return (mediaManagerState.items || []).filter(item => {
    const category = String(item.category || 'uploads');
    if (selectedCategory !== 'all' && category !== selectedCategory) return false;
    if (!search) return true;
    const haystack = [
      item.filename,
      item.object_key,
      category,
      item.last_modified,
    ].join(' ').toLowerCase();
    return haystack.includes(search);
  });
}

function _updateMediaSelectionStats(totalVisible = null) {
  const el = qs('mediaManagerSelectionStats');
  if (!el) return;
  const set = _mediaSelectedSet();
  const count = set.size;
  const suffix = Number.isFinite(totalVisible) ? ` de ${totalVisible}` : '';
  el.textContent = `${count} selecionado(s)${suffix}`;
  const bulk = qs('mediaManagerBulkbar');
  if (bulk) bulk.classList.toggle('has-selection', count > 0);
  _updateMediaActionFooter(set);
}

function _updateMediaActionFooter(set) {
  const footer = qs('mediaActionFooter');
  if (!footer) return;
  const count = set ? set.size : 0;
  const isMediaPage = document.body.classList.contains('os-desktop-home') === false
    && !!document.getElementById('page-media')?.classList.contains('active');
  const show = count > 0 && isMediaPage;
  footer.classList.toggle('visible', show);
  const countEl = qs('mediaFooterCount');
  const fileEl = qs('mediaFooterFilename');
  if (countEl) countEl.textContent = count === 1 ? '1 arquivo' : `${count} arquivos`;
  if (fileEl) {
    if (count === 1 && set) {
      const key = Array.from(set)[0] || '';
      fileEl.textContent = key.split('/').pop() || key;
    } else {
      fileEl.textContent = count > 1 ? 'selecionados' : '';
    }
  }
}

function mediaFooterAction(action) {
  const set = _mediaSelectedSet();
  if (!set.size) return;
  const keys = Array.from(set);
  const firstKey = keys[0];
  if (action === 'analyze') {
    location.hash = 'analyze';
    setTimeout(() => {
      const inp = document.getElementById('anObjectKey');
      if (inp) { inp.value = firstKey; inp.dispatchEvent(new Event('input')); }
    }, 300);
  } else if (action === 'autoeditor') {
    location.hash = 'autoeditor';
    setTimeout(() => {
      const setSourceFn = window.aeSetSourceFromKey;
      if (typeof setSourceFn === 'function') {
        keys.forEach(k => setSourceFn(k));
      } else {
        const hint = document.getElementById('aeVideoInfo');
        if (hint) hint.textContent = `${keys.length} arquivo(s) selecionado(s): ${keys.map(k => k.split('/').pop()).join(', ')}`;
      }
    }, 300);
  } else if (action === 'legenda') {
    location.hash = 'criacao';
    setTimeout(() => {
      if (window.criacaoSelectRunByKey) window.criacaoSelectRunByKey(firstKey);
      else { const tab = document.querySelector('[data-criacao-tab="legenda"]'); if (tab) tab.click(); }
    }, 300);
  } else if (action === 'logo') {
    location.hash = 'criacao';
  } else if (action === 'teaser') {
    location.hash = 'criacao';
  } else if (action === 'thumbnail') {
    location.hash = 'criacao';
  } else if (action === 'publisher') {
    location.hash = 'publisher';
  }
}

function toggleManagedMediaSelection(objectKey, checked) {
  const key = _normalizeObjectKeyish(objectKey);
  if (!key) return;
  const set = _mediaSelectedSet();
  if (checked) set.add(key);
  else set.delete(key);
  _setMediaSelectedSet(set);
  _syncManagedMediaSelectionDom(key, checked);
  _updateMediaSelectionStats(_getMediaManagerFilteredItems().length);
}

function selectAllManagedMediaFiltered() {
  const set = _mediaSelectedSet();
  _getMediaManagerFilteredItems().forEach(item => set.add(String(item.object_key || '').trim()));
  _setMediaSelectedSet(set);
  renderMediaManagerList();
}

function clearManagedMediaSelection() {
  mediaManagerState.selectedKeys = [];
  renderMediaManagerList();
}

function _syncManagedMediaSelectionDom(objectKey, selected) {
  const key = String(objectKey || '').trim();
  if (!key) return;
  document.querySelectorAll('#mediaManagerList [data-media-key]').forEach(el => {
    if (el.dataset.mediaKey !== key) return;
    el.classList.toggle('is-selected', !!selected);
    const cb = el.querySelector('input[type="checkbox"][data-media-select]');
    if (cb) cb.checked = !!selected;
  });
}

function _syncMediaManagerFiltersFromDom() {
  const searchEl = qs('mediaManagerSearch');
  const limitEl = qs('mediaManagerLimit');
  mediaManagerState.search = String(searchEl?.value || mediaManagerState.search || '').trim();
  mediaManagerState.maxKeys = Math.max(10, Math.min(parseInt(limitEl?.value || mediaManagerState.maxKeys || 80, 10) || 80, 500));
  if (limitEl) limitEl.value = String(mediaManagerState.maxKeys);
}

function _setMediaManagerLoading(text) {
  const stats = qs('mediaManagerStats');
  const list = qs('mediaManagerList');
  if (stats) stats.textContent = text || 'Carregando…';
  if (list) list.innerHTML = '<div class="criacao-empty">Carregando arquivos…</div>';
}

function _mediaDriveJobForKey(objectKey) {
  return mediaManagerState.driveJobs[String(objectKey || '').trim()] || null;
}

function setMediaManagerCategory(category) {
  mediaManagerState.category = ['all', 'uploads', 'burns', 'teasers'].includes(category) ? category : 'all';
  ['all', 'uploads', 'burns', 'teasers'].forEach(name => {
    const btn = qs(`btnMediaTab${name.charAt(0).toUpperCase()}${name.slice(1)}`);
    if (btn) btn.classList.toggle('active', mediaManagerState.category === name);
  });
  renderMediaManagerList();
}

function setMediaManagerSearch(value) {
  mediaManagerState.search = String(value || '').trim();
  renderMediaManagerList();
}

async function refreshGoogleDriveConfig(opts = {}) {
  const silent = !!opts.silent;
  try {
    const res = await apiFetch('/api/media-manager/google-drive/config');
    mediaManagerState.driveConfig = res || null;
    const folderEl = qs('mediaDriveFolderId');
    const statusEl = qs('mediaDriveStatus');
    if (folderEl && document.activeElement !== folderEl) folderEl.value = res?.folder_id || '';
    if (statusEl) {
      statusEl.textContent = res?.detail || 'Google Drive pronto.';
      statusEl.style.color = res?.configured ? 'var(--good)' : 'var(--muted)';
      if (res?.service_account_email) {
        statusEl.textContent += ` Conta: ${res.service_account_email}`;
      }
    }
    if (!silent) toast(res?.configured ? 'Configuração do Google Drive carregada' : 'Google Drive ainda não configurado', res?.configured ? 'good' : 'bad');
  } catch (e) {
    const statusEl = qs('mediaDriveStatus');
    if (statusEl) {
      statusEl.textContent = `Erro ao carregar config: ${e.message}`;
      statusEl.style.color = 'var(--bad)';
    }
    if (!silent) toast('Erro ao carregar Google Drive: ' + e.message, 'bad');
  }
}

async function saveGoogleDriveConfig() {
  const folderId = String(qs('mediaDriveFolderId')?.value || '').trim();
  const serviceAccountJson = String(qs('mediaDriveServiceAccount')?.value || '');
  try {
    const res = await apiFetch('/api/media-manager/google-drive/config', {
      method: 'POST',
      body: JSON.stringify({
        folder_id: folderId,
        service_account_json: serviceAccountJson,
      }),
    });
    mediaManagerState.driveConfig = res || null;
    const ta = qs('mediaDriveServiceAccount');
    if (ta) ta.value = '';
    await refreshGoogleDriveConfig({ silent: true });
    toast(res?.configured ? 'Google Drive configurado' : 'Configuração salva, mas ainda falta completar os dados', res?.configured ? 'good' : 'bad');
  } catch (e) {
    toast('Erro ao salvar Google Drive: ' + e.message, 'bad');
  }
}

function _driveIntakeSelectedSet() {
  return new Set((mediaManagerState.driveIntakeSelectedIds || []).map(v => String(v || '').trim()).filter(Boolean));
}

function _setDriveIntakeSelectedSet(setLike) {
  mediaManagerState.driveIntakeSelectedIds = Array.from(setLike || []).map(v => String(v || '').trim()).filter(Boolean);
}

function _updateDriveIntakeSelectionStats(totalVisible = null) {
  const el = qs('mediaDriveIntakeSelectionStats');
  if (!el) return;
  const count = _driveIntakeSelectedSet().size;
  const suffix = Number.isFinite(totalVisible) ? ` de ${totalVisible}` : '';
  el.textContent = `${count} selecionado(s)${suffix}`;
}

async function loadMediaDriveCreatorOptions() {
  try {
    if (!agencyState.creators?.length) {
      const data = await agencyFetch('/api/creators?limit=200').catch(() => ({ creators: [] }));
      agencyState.creators = data.creators || [];
    }
    const sel = qs('mediaDriveCreatorSelect');
    if (!sel) return;
    const current = mediaManagerState.driveIntakeCreatorId || sel.value || '';
    const options = ['<option value="">Selecione um criador</option>']
      .concat((agencyState.creators || []).map(c =>
        `<option value="${esc(c.creator_id)}">${esc(c.name)}${c.drive_folder_id ? ' · Drive próprio' : ''}</option>`
      ));
    sel.innerHTML = options.join('');
    if (current) sel.value = current;
  } catch (e) {
    const statusEl = qs('mediaDriveIntakeStatus');
    if (statusEl) {
      statusEl.textContent = `Erro ao carregar criadores: ${e.message}`;
      statusEl.style.color = 'var(--bad)';
    }
  }
}

function toggleDriveIntakeSelection(fileId, checked) {
  const key = String(fileId || '').trim();
  if (!key) return;
  const set = _driveIntakeSelectedSet();
  if (checked) set.add(key);
  else set.delete(key);
  _setDriveIntakeSelectedSet(set);
  _updateDriveIntakeSelectionStats((mediaManagerState.driveIntakeItems || []).length);
}

function clearDriveIntakeSelection() {
  mediaManagerState.driveIntakeSelectedIds = [];
  renderDriveIntakeList();
}

function selectAllDriveIntakeFiles() {
  const set = _driveIntakeSelectedSet();
  (mediaManagerState.driveIntakeItems || []).forEach(item => {
    if (!item?.is_folder && item?.id) set.add(String(item.id).trim());
  });
  _setDriveIntakeSelectedSet(set);
  renderDriveIntakeList();
}

function _driveIntakeJobForFile(fileId) {
  return mediaManagerState.driveIntakeJobs[String(fileId || '').trim()] || null;
}

async function reloadDriveIntakeFiles(opts = {}) {
  const creatorId = String(qs('mediaDriveCreatorSelect')?.value || mediaManagerState.driveIntakeCreatorId || '').trim();
  mediaManagerState.driveIntakeCreatorId = creatorId;
  const statusEl = qs('mediaDriveIntakeStatus');
  if (!creatorId) {
    mediaManagerState.driveIntakeItems = [];
    mediaManagerState.driveIntakeConfig = null;
    renderDriveIntakeList();
    if (statusEl) {
      statusEl.textContent = 'Selecione um criador para listar os arquivos do Drive.';
      statusEl.style.color = 'var(--muted)';
    }
    return;
  }
  if (statusEl) {
    statusEl.textContent = 'Lendo pasta do Google Drive do criador…';
    statusEl.style.color = 'var(--muted)';
  }
  try {
    const res = await apiFetch(`/api/media-manager/google-drive/intake/files?creator_id=${encodeURIComponent(creatorId)}&page_size=100`);
    mediaManagerState.driveIntakeItems = Array.isArray(res.items) ? res.items : [];
    mediaManagerState.driveIntakeConfig = res.config || null;
    renderDriveIntakeList();
    const cfg = res.config || {};
    if (statusEl) {
      const sourceFolder = cfg.folder_source === 'creator' ? 'pasta do criador' : 'pasta global';
      const sourceCreds = cfg.credentials_source === 'creator' ? 'credenciais do criador' : 'credenciais globais';
      statusEl.textContent = `${res.count || mediaManagerState.driveIntakeItems.length} arquivo(s) encontrados · ${sourceFolder} · ${sourceCreds}${cfg.service_account_email ? ` · ${cfg.service_account_email}` : ''}`;
      statusEl.style.color = 'var(--good)';
    }
  } catch (e) {
    mediaManagerState.driveIntakeItems = [];
    renderDriveIntakeList();
    if (statusEl) {
      statusEl.textContent = `Erro ao listar Google Drive: ${e.message}`;
      statusEl.style.color = 'var(--bad)';
    }
    toast('Erro ao listar arquivos do Drive: ' + e.message, 'bad');
  }
}

function renderDriveIntakeList() {
  const listEl = qs('mediaDriveIntakeList');
  if (!listEl) return;
  const items = mediaManagerState.driveIntakeItems || [];
  const selectedSet = _driveIntakeSelectedSet();
  const allowed = new Set(items.map(item => String(item.id || '').trim()).filter(Boolean));
  _setDriveIntakeSelectedSet(new Set(Array.from(selectedSet).filter(id => allowed.has(id))));
  const finalSelected = _driveIntakeSelectedSet();
  _updateDriveIntakeSelectionStats(items.length);
  if (!items.length) {
    listEl.innerHTML = '<div class="criacao-empty" style="padding:24px;">Nenhum arquivo encontrado nesta pasta.</div>';
    return;
  }
  listEl.innerHTML = items.map(item => {
    const id = String(item.id || '');
    const name = String(item.name || 'arquivo');
    const size = item.size_mb ? `${item.size_mb} MB` : '-';
	    const modified = item.modified_time ? fmtDate(item.modified_time) : '-';
	    const mime = String(item.mime_type || '');
	    const videoMeta = item.video_meta || {};
	    const durationMs = Number(videoMeta.durationMillis || 0);
	    const duration = durationMs > 0 ? _formatMediaClock(durationMs / 1000) : '--:--';
	    const resolution = videoMeta.width && videoMeta.height ? `${videoMeta.width}×${videoMeta.height}` : 'resolução...';
	    const job = _driveIntakeJobForFile(id);
	    const disabled = item.is_folder ? 'disabled' : '';
    const jobHtml = job
      ? `<div class="media-manager-status">${esc(job.detail || 'Importação em andamento')}
          ${job.object_key ? ` · <span style="color:var(--good)">importado</span>` : ''}
        </div>`
      : '';
    return `
	      <div class="media-manager-row ${finalSelected.has(id) ? 'is-selected' : ''}">
	        <div class="media-manager-main">
	          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:4px;">
	            <label style="display:flex;align-items:center;gap:6px;font-size:12px;">
	              <input type="checkbox" ${finalSelected.has(id) ? 'checked' : ''} ${disabled} onchange='toggleDriveIntakeSelection(${JSON.stringify(id)}, this.checked)'>
              <span>Selecionar</span>
            </label>
            <strong style="font-size:13px;">${esc(name)}</strong>
	            <span class="badge">${esc(size)}</span>
	            <span class="badge">${esc(modified)}</span>
	            <span class="badge">${esc(item.is_folder ? 'Pasta' : (mime || 'arquivo'))}</span>
	            <span class="badge">${esc(duration)}</span>
	            <span class="badge">${esc(resolution)}</span>
	          </div>
          <div class="hint" style="word-break:break-all;">${esc(id)}</div>
          ${jobHtml}
        </div>
        <div class="media-manager-actions">
          ${item.web_view_link ? `<button class="btn" onclick="window.open(${JSON.stringify(item.web_view_link)}, '_blank')">Abrir Drive</button>` : ''}
          <button class="btn primary" ${disabled} onclick='importDriveIntakeFile(${JSON.stringify(id)}, ${JSON.stringify(name)})'>Importar</button>
        </div>
      </div>
    `;
  }).join('');
}

async function importDriveIntakeFile(fileId, filename) {
  const creatorId = String(mediaManagerState.driveIntakeCreatorId || qs('mediaDriveCreatorSelect')?.value || '').trim();
  if (!creatorId) return toast('Selecione um criador antes de importar', 'bad');
  const safeFileId = String(fileId || '').trim();
  if (!safeFileId) return toast('Arquivo inválido para importação', 'bad');
  try {
    const res = await apiFetch('/api/media-manager/google-drive/intake/import', {
      method: 'POST',
      body: JSON.stringify({
        creator_id: creatorId,
        drive_file_id: safeFileId,
        filename: filename || undefined,
      }),
    });
    if (!res?.job_id) throw new Error('Servidor não retornou job_id');
    mediaManagerState.driveIntakeJobs[safeFileId] = { status: 'pending', detail: 'Importação iniciada…' };
    renderDriveIntakeList();
    toast('Importação do Google Drive iniciada', 'good');
    _pollDriveIntakeImportJob(res.job_id, safeFileId);
  } catch (e) {
    toast('Erro ao importar do Drive: ' + e.message, 'bad');
  }
}

async function _pollDriveIntakeImportJob(jobId, fileId) {
  const safeFileId = String(fileId || '').trim();
  if (!jobId || !safeFileId) return;
  while (true) {
    try {
      const job = await apiFetch(`/api/media-manager/google-drive/intake/import/${encodeURIComponent(jobId)}`);
      mediaManagerState.driveIntakeJobs[safeFileId] = job || {};
      renderDriveIntakeList();
      if (job?.status === 'done') {
        toast('Arquivo recebido do Google Drive', 'good');
        await reloadMediaManagerFiles({ silent: true });
        return;
      }
      if (job?.status === 'error' || job?.status === 'cancelled') {
        toast('Falha ao importar do Drive: ' + (job?.detail || job?.error || 'erro'), 'bad');
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 2500));
    } catch (e) {
      mediaManagerState.driveIntakeJobs[safeFileId] = { status: 'error', detail: e.message };
      renderDriveIntakeList();
      toast('Erro ao acompanhar importação do Drive: ' + e.message, 'bad');
      return;
    }
  }
}

async function importSelectedDriveIntakeFiles() {
  const ids = Array.from(_driveIntakeSelectedSet());
  if (!ids.length) return toast('Selecione ao menos um arquivo do Drive', 'bad');
  for (const id of ids) {
    const item = (mediaManagerState.driveIntakeItems || []).find(v => String(v.id || '').trim() === id);
    if (item?.is_folder) continue;
    await importDriveIntakeFile(id, item?.name || undefined);
  }
}

async function reloadMediaManagerFiles(opts = {}) {
  _syncMediaManagerFiltersFromDom();
  if (!opts.silent) _setMediaManagerLoading('Carregando biblioteca…');
  const maxKeys = mediaManagerState.maxKeys;
  const prefixes = ['uploads', 'burns', 'teasers'];
  const results = await Promise.allSettled(
    prefixes.map(prefix => apiFetch(`/uploads/list?prefix=${encodeURIComponent(prefix)}&max_keys=${maxKeys}`))
  );
  const items = [];
  const errors = [];
  results.forEach((result, idx) => {
    const prefix = prefixes[idx];
    if (result.status !== 'fulfilled') {
      errors.push(`${prefix}: ${result.reason?.message || 'falha'}`);
      return;
    }
    const list = Array.isArray(result.value?.items) ? result.value.items : [];
    list.forEach(item => {
      items.push({
        ...item,
        category: prefix,
      });
    });
  });
  items.sort((a, b) => String(b.last_modified || '').localeCompare(String(a.last_modified || '')));
  mediaManagerState.items = items;
  mediaManagerState.loaded = true;
  renderMediaManagerList(errors);
}

async function loadMediaManagerPage(force = false) {
  _syncMediaManagerFiltersFromDom();
  _syncMediaManagerViewControls();
  setMediaManagerCategory(mediaManagerState.category || 'all');
  await loadMediaDriveCreatorOptions();
  if (!mediaManagerState.loaded || force) {
    await Promise.all([
      refreshGoogleDriveConfig({ silent: true }),
      reloadMediaManagerFiles({ silent: false }),
    ]);
    if (mediaManagerState.driveIntakeCreatorId || qs('mediaDriveCreatorSelect')?.value) {
      await reloadDriveIntakeFiles({ silent: true });
    } else {
      renderDriveIntakeList();
    }
    return;
  }
  await refreshGoogleDriveConfig({ silent: true });
  if (mediaManagerState.driveIntakeCreatorId || qs('mediaDriveCreatorSelect')?.value) {
    await reloadDriveIntakeFiles({ silent: true });
  } else {
    renderDriveIntakeList();
  }
  renderMediaManagerList();
}

function renderMediaManagerList(errors = []) {
  const listEl = qs('mediaManagerList');
  const statsEl = qs('mediaManagerStats');
  if (!listEl || !statsEl) return;
  const filtered = _getMediaManagerFilteredItems();
  let selectedSet = _mediaSelectedSet();

  const counts = { uploads: 0, burns: 0, teasers: 0 };
  (mediaManagerState.items || []).forEach(item => {
    const category = String(item.category || 'uploads');
    counts[category] = (counts[category] || 0) + 1;
  });
  const allowedKeys = new Set((mediaManagerState.items || []).map(item => String(item.object_key || '').trim()).filter(Boolean));
  _setMediaSelectedSet(new Set(Array.from(selectedSet).filter(key => allowedKeys.has(key))));
  selectedSet = _mediaSelectedSet();
  const extra = Array.isArray(errors) && errors.length ? ` · erros parciais: ${errors.join(' | ')}` : '';
  statsEl.textContent = `Originais: ${counts.uploads || 0} · Queimados: ${counts.burns || 0} · Teasers: ${counts.teasers || 0} · exibindo ${filtered.length}${extra}`;
  _updateMediaSelectionStats(filtered.length);

  if (!filtered.length) {
    listEl.className = 'media-manager-grid is-list';
    listEl.innerHTML = '<div class="criacao-empty">Nenhum arquivo encontrado com esse filtro.</div>';
    return;
  }

  const useIcons = mediaManagerState.viewMode !== 'list';
  listEl.className = `media-manager-grid ${useIcons ? 'is-icons' : 'is-list'}`;
  _applyMediaManagerGridStyle();
  listEl.innerHTML = filtered.map(item => (
    useIcons
      ? _renderManagedMediaTile(item, selectedSet)
      : _renderManagedMediaRow(item, selectedSet)
  )).join('');
  _hydrateMediaMetadata(filtered);
  if (useIcons) _hydrateMediaTilePreviews();
}

function _managedMediaItemViewModel(item, selectedSet) {
  const key = String(item.object_key || '');
  const filename = _cleanFilename(String(item.filename || key.split('/').pop() || 'arquivo'));
  const label = _mediaCategoryLabel(String(item.category || 'uploads'));
  const date = item.last_modified ? fmtDate(item.last_modified) : '-';
  const size = item.size_mb != null ? `${item.size_mb} MB` : '-';
  const meta = _mediaMetadataForItem(item);
  const keyArg = _inlineJsonArg(key);
  const fileArg = _inlineJsonArg(filename);
  const labelArg = _inlineJsonArg(filename);
  const driveJob = _mediaDriveJobForKey(key);
  const driveStatus = driveJob
    ? `<div class="media-manager-status">${esc(driveJob.detail || 'Upload no Google Drive em andamento')}
        ${driveJob.drive_web_view_link ? ` · <a href="${esc(driveJob.drive_web_view_link)}" target="_blank" rel="noreferrer">Abrir no Drive</a>` : ''}
      </div>`
    : '';
  return { key, filename, label, date, size, meta, keyArg, fileArg, labelArg, driveStatus, selected: selectedSet.has(key) };
}

function _renderManagedMediaRow(item, selectedSet) {
  const vm = _managedMediaItemViewModel(item, selectedSet);
  return `
    <div class="media-manager-row ${vm.selected ? 'is-selected' : ''}" data-media-key="${escAttr(vm.key)}">
      <div class="media-manager-main">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:4px;">
          <label style="display:flex;align-items:center;gap:6px;font-size:12px;">
            <input type="checkbox" data-media-select ${vm.selected ? 'checked' : ''} onchange='toggleManagedMediaSelection(${vm.keyArg}, this.checked)'>
            <span>Selecionar</span>
          </label>
          <strong style="font-size:13px;">${esc(vm.filename)}</strong>
          <span class="badge">${esc(vm.label)}</span>
          <span class="badge">${esc(vm.size)}</span>
          <span class="badge">${esc(vm.date)}</span>
          <span class="badge js-media-duration">${esc(vm.meta.durationLabel)}</span>
          <span class="badge js-media-resolution">${esc(vm.meta.resolutionLabel)}</span>
          <span class="badge js-media-fps">${esc(vm.meta.fpsLabel)}</span>
          <span class="badge js-media-audio">${esc(vm.meta.audioLabel)}</span>
        </div>
        <div class="hint" style="word-break:break-all;">${esc(vm.key)}</div>
        ${vm.driveStatus}
      </div>
      <div class="media-manager-actions">
        <button class="btn" onclick='previewManagedMedia(${vm.keyArg}, ${vm.labelArg})'>Player</button>
        <button class="btn" onclick='downloadManagedMedia(${vm.keyArg}, ${vm.fileArg})'>Baixar</button>
        <button class="btn" onclick='renameManagedMedia(${vm.keyArg}, ${vm.fileArg})'>Renomear</button>
        <button class="btn" onclick='sendManagedMediaToDrive(${vm.keyArg}, ${vm.fileArg})'>Drive</button>
        <button class="btn" onclick='deleteManagedMedia(${vm.keyArg}, ${vm.labelArg})'>Excluir</button>
      </div>
    </div>
  `;
}

function _renderManagedMediaTile(item, selectedSet) {
  const vm = _managedMediaItemViewModel(item, selectedSet);
  return `
    <div class="media-tile ${vm.selected ? 'is-selected' : ''}" data-media-key="${escAttr(vm.key)}" ondblclick='previewManagedMedia(${vm.keyArg}, ${vm.labelArg})'>
      <div class="media-tile-cover is-loading" data-media-preview-key="${escAttr(vm.key)}" data-media-preview-label="${escAttr(vm.filename)}"
        onclick='previewManagedMedia(${vm.keyArg}, ${vm.labelArg})'>
        <img class="media-tile-img" alt="" loading="lazy" decoding="async">
        <div class="media-tile-skeleton">Capa em fila…</div>
        <span class="media-tile-badge">${esc(vm.label)}</span>
        <span class="media-tile-duration js-media-duration">${esc(vm.meta.durationLabel)}</span>
        <label class="media-tile-check" onclick="event.stopPropagation()">
          <input type="checkbox" data-media-select ${vm.selected ? 'checked' : ''} onchange='toggleManagedMediaSelection(${vm.keyArg}, this.checked)'>
          <span>Selecionar</span>
        </label>
        <button type="button" class="media-tile-play" onclick='event.stopPropagation();previewManagedMedia(${vm.keyArg}, ${vm.labelArg})'>▶</button>
      </div>
      <div class="media-tile-name" title="${esc(vm.filename)}">${esc(vm.filename)}</div>
      <div class="media-tile-meta">
        <span>${esc(vm.size)}</span>
        <span>${esc(vm.date)}</span>
      </div>
      <div class="media-tile-meta media-tile-tech">
        <span class="js-media-resolution">${esc(vm.meta.resolutionLabel)}</span>
        <span class="js-media-fps">${esc(vm.meta.fpsLabel)}</span>
        <span class="js-media-audio">${esc(vm.meta.audioLabel)}</span>
      </div>
      ${vm.driveStatus}
      <div class="media-tile-actions">
        <button class="btn" onclick='previewManagedMedia(${vm.keyArg}, ${vm.labelArg})'>Player</button>
        <button class="btn" onclick='downloadManagedMedia(${vm.keyArg}, ${vm.fileArg})'>Baixar</button>
        <button class="btn" onclick='renameManagedMedia(${vm.keyArg}, ${vm.fileArg})'>Renomear</button>
        <button class="btn" onclick='sendManagedMediaToDrive(${vm.keyArg}, ${vm.fileArg})'>Drive</button>
        <button class="btn" onclick='deleteManagedMedia(${vm.keyArg}, ${vm.labelArg})' style="grid-column:1 / -1;">Excluir</button>
      </div>
    </div>
  `;
}

function _hydrateMediaTilePreviews() {
  const listEl = qs('mediaManagerList');
  if (!listEl) return;
  if (mediaManagerState.previewObserver) {
    try { mediaManagerState.previewObserver.disconnect(); } catch (_) {}
    mediaManagerState.previewObserver = null;
  }
  const covers = Array.from(listEl.querySelectorAll('.media-tile-cover[data-media-preview-key]'));
  if (!covers.length) return;
  covers.slice(0, 12).forEach(_enqueueMediaTilePreview);
  if (!('IntersectionObserver' in window)) {
    covers.slice(12, 24).forEach(_enqueueMediaTilePreview);
    return;
  }
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      observer.unobserve(entry.target);
      _enqueueMediaTilePreview(entry.target);
    });
  }, { rootMargin: '120px 0px', threshold: 0.01 });
  mediaManagerState.previewObserver = observer;
  covers.slice(12).forEach(el => observer.observe(el));
}

function _enqueueMediaTilePreview(el) {
  if (!el || el.dataset.loaded === '1' || el.dataset.queued === '1') return;
  el.dataset.queued = '1';
  mediaManagerState.thumbQueue.push(el);
  _pumpMediaTilePreviewQueue();
}

function _pumpMediaTilePreviewQueue() {
  const limit = 4;
  while (mediaManagerState.thumbActive < limit && mediaManagerState.thumbQueue.length) {
    const el = mediaManagerState.thumbQueue.shift();
    if (!el || el.dataset.loaded === '1') continue;
    mediaManagerState.thumbActive += 1;
    _loadMediaTilePreview(el)
      .catch(() => {})
      .finally(() => {
        mediaManagerState.thumbActive = Math.max(0, mediaManagerState.thumbActive - 1);
        _pumpMediaTilePreviewQueue();
      });
  }
}

async function _loadMediaTilePreview(el) {
  if (!el || el.dataset.loaded === '1') return;
  el.dataset.loaded = '1';
  const key = _normalizeObjectKeyish(el.dataset.mediaPreviewKey || '');
  const img = el.querySelector('img.media-tile-img');
  if (!key || !img) {
    el.classList.remove('is-loading');
    el.classList.add('is-error');
    const skeleton = el.querySelector('.media-tile-skeleton');
    if (skeleton) skeleton.textContent = 'Capa indisponível';
    return;
  }

  const markReady = () => {
    el.classList.remove('is-loading', 'is-error');
    el.classList.add('is-ready');
  };
  const markError = () => {
    el.classList.remove('is-loading');
    el.classList.add('is-error');
    const skeleton = el.querySelector('.media-tile-skeleton');
    if (skeleton) skeleton.textContent = 'Sem preview';
  };

  try {
    const res = await apiFetch(`/api/media-manager/thumbnail-url?object_key=${encodeURIComponent(key)}&width=520&t=8`);
    if (res?.metadata) {
      mediaManagerState.metadataCache[key] = res.metadata;
      _applyMediaMetadataToDom(key);
    }
    if (!res?.url) throw new Error('thumb_url_failed');
    img.onload = markReady;
    img.onerror = markError;
    img.src = res.url;
  } catch (_) {
    markError();
  }
}

function _hydrateMediaMetadata(items) {
  const keys = [];
  (items || []).forEach(item => {
    const key = String(item?.object_key || '').trim();
    if (!key || mediaManagerState.metadataCache[key] || mediaManagerState.metadataPending.has(key)) return;
    keys.push(key);
  });
  const batch = keys.slice(0, 120);
  if (!batch.length) return;
  batch.forEach(key => mediaManagerState.metadataPending.add(key));
  apiFetch('/api/media-manager/metadata/batch', {
    method: 'POST',
    body: JSON.stringify({ object_keys: batch }),
  }).then(res => {
    const itemsMap = res?.items || {};
    Object.entries(itemsMap).forEach(([key, meta]) => {
      mediaManagerState.metadataCache[key] = meta || {};
      const item = (mediaManagerState.items || []).find(it => String(it.object_key || '').trim() === key);
      if (item && meta) item.metadata = meta;
      _applyMediaMetadataToDom(key);
    });
  }).catch(() => {
    // Metadata is decorative; do not block the file grid.
  }).finally(() => {
    batch.forEach(key => mediaManagerState.metadataPending.delete(key));
  });
}

function _applyMediaMetadataToDom(objectKey) {
  const key = String(objectKey || '').trim();
  if (!key) return;
  const item = (mediaManagerState.items || []).find(it => String(it.object_key || '').trim() === key) || { object_key: key };
  const meta = _mediaMetadataForItem(item);
  document.querySelectorAll('#mediaManagerList [data-media-key]').forEach(el => {
    if (el.dataset.mediaKey !== key) return;
    const durationEl = el.querySelector('.js-media-duration');
    const resolutionEl = el.querySelector('.js-media-resolution');
    const fpsEl = el.querySelector('.js-media-fps');
    const audioEl = el.querySelector('.js-media-audio');
    if (durationEl) durationEl.textContent = meta.durationLabel;
    if (resolutionEl) resolutionEl.textContent = meta.resolutionLabel;
    if (fpsEl) fpsEl.textContent = meta.fpsLabel;
    if (audioEl) audioEl.textContent = meta.audioLabel;
  });
}

async function previewManagedMedia(objectKey, label) {
  const key = _normalizeObjectKeyish(objectKey);
  if (!key) return toast('Arquivo inválido para preview', 'bad');
  const video = qs('mediaPreviewVideo');
  const empty = qs('mediaPreviewEmpty');
  const meta = qs('mediaPreviewMeta');
  if (!video || !empty || !meta) return;
  empty.textContent = 'Carregando preview…';
  empty.classList.remove('hidden');
  video.classList.add('hidden');
  meta.textContent = `${label || 'Arquivo'} · preparando player…`;
  try {
    const previewUrl = await _getAdaptivePreviewUrl(key, { maxHeight: 1080, maxFps: 30 }) || await _getVideoStreamUrl(key);
    if (!previewUrl) throw new Error('Não foi possível gerar URL de preview');
    video.src = previewUrl;
    video.onloadedmetadata = () => {
      const duration = Number.isFinite(video.duration) ? _formatMediaClock(video.duration) : 'minutagem indisponível';
      const resLabel = video.videoWidth && video.videoHeight ? `${video.videoWidth}×${video.videoHeight}` : 'resolução indisponível';
      meta.textContent = `${label || 'Arquivo'} · ${duration} · ${resLabel} · ${key}`;
    };
    video.load();
    empty.classList.add('hidden');
    video.classList.remove('hidden');
    mediaManagerState.previewObjectKey = key;
    mediaManagerState.previewLabel = String(label || '');
    meta.textContent = `${label || 'Arquivo'} · carregando minutagem… · ${key}`;
  } catch (e) {
    empty.textContent = `Erro ao abrir player: ${e.message}`;
    meta.textContent = `${label || 'Arquivo'} · falha no preview`;
    toast('Erro ao abrir player: ' + e.message, 'bad');
  }
}

async function downloadManagedMedia(objectKey, filename) {
  const key = _normalizeObjectKeyish(objectKey);
  if (!key) return toast('Arquivo inválido para download', 'bad');
  try {
    const res = await apiFetch(`/api/video-download-url?object_key=${encodeURIComponent(key)}&filename=${encodeURIComponent(filename || 'arquivo')}`);
    if (res?.error || !res?.url) throw new Error(res?.detail || res?.error || 'URL inválida');
    window.open(res.url, '_blank');
  } catch (e) {
    toast('Erro ao gerar download: ' + e.message, 'bad');
  }
}

async function renameManagedMedia(objectKey, filename) {
  const key = _normalizeObjectKeyish(objectKey);
  if (!key) return toast('Arquivo inválido para renomear', 'bad');
  const currentName = String(filename || key.split('/').pop() || 'arquivo.mp4');
  const nextName = prompt('Novo nome do arquivo:', currentName);
  if (!nextName || nextName.trim() === currentName) return;
  try {
    const res = await apiFetch('/api/media-manager/rename', {
      method: 'POST',
      body: JSON.stringify({
        object_key: key,
        new_filename: nextName.trim(),
      }),
    });
    const item = res?.item || null;
    if (item?.object_key && mediaManagerState.previewObjectKey === key) {
      await previewManagedMedia(item.object_key, item.filename || nextName.trim());
    }
    toast('Arquivo renomeado', 'good');
    await reloadMediaManagerFiles({ silent: true });
  } catch (e) {
    toast('Erro ao renomear: ' + e.message, 'bad');
  }
}

async function deleteManagedMedia(objectKey, label) {
  const key = _normalizeObjectKeyish(objectKey);
  if (!key) return toast('Arquivo inválido para exclusão', 'bad');
  if (!confirm(`Excluir este arquivo do servidor?\n\n${label || key}`)) return;
  try {
    await apiFetch(`/uploads/object?object_key=${encodeURIComponent(key)}`, { method: 'DELETE' });
    if (mediaManagerState.previewObjectKey === key) {
      const video = qs('mediaPreviewVideo');
      const empty = qs('mediaPreviewEmpty');
      const meta = qs('mediaPreviewMeta');
      if (video) {
        video.pause();
        video.removeAttribute('src');
        video.load();
        video.classList.add('hidden');
      }
      if (empty) {
        empty.textContent = 'Selecione um arquivo para abrir no player.';
        empty.classList.remove('hidden');
      }
      if (meta) meta.textContent = '-';
      mediaManagerState.previewObjectKey = '';
      mediaManagerState.previewLabel = '';
    }
    toast('Arquivo excluído', 'good');
    await reloadMediaManagerFiles({ silent: true });
  } catch (e) {
    toast('Erro ao excluir: ' + e.message, 'bad');
  }
}

async function sendManagedMediaToDrive(objectKey, filename) {
  const key = _normalizeObjectKeyish(objectKey);
  if (!key) return toast('Arquivo inválido para envio', 'bad');
  try {
    const res = await apiFetch('/api/media-manager/google-drive/upload', {
      method: 'POST',
      body: JSON.stringify({
        object_key: key,
        filename: filename || undefined,
      }),
    });
    if (!res?.job_id) throw new Error('Servidor não retornou job_id');
    mediaManagerState.driveJobs[key] = { status: 'pending', detail: 'Upload para o Google Drive iniciado…' };
    renderMediaManagerList();
    toast('Upload para o Google Drive iniciado', 'good');
    _pollManagedMediaDriveJob(res.job_id, key);
  } catch (e) {
    toast('Erro ao enviar para o Drive: ' + e.message, 'bad');
  }
}

async function _pollManagedMediaDriveJob(jobId, objectKey) {
  const key = _normalizeObjectKeyish(objectKey);
  if (!key || !jobId) return;
  while (true) {
    try {
      const job = await apiFetch(`/api/media-manager/google-drive/upload/${encodeURIComponent(jobId)}`);
      mediaManagerState.driveJobs[key] = job || {};
      renderMediaManagerList();
      if (job?.status === 'done') {
        toast('Arquivo enviado ao Google Drive', 'good');
        return;
      }
      if (job?.status === 'error' || job?.status === 'cancelled') {
        toast('Falha no upload para o Drive: ' + (job?.detail || job?.error || 'erro'), 'bad');
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 2500));
    } catch (e) {
      mediaManagerState.driveJobs[key] = { status: 'error', detail: e.message };
      renderMediaManagerList();
      toast('Erro ao acompanhar upload do Drive: ' + e.message, 'bad');
      return;
    }
  }
}

async function bulkDeleteManagedMedia() {
  const keys = Array.from(_mediaSelectedSet());
  if (!keys.length) return toast('Selecione ao menos um arquivo', 'bad');
  if (!confirm(`Excluir ${keys.length} arquivo(s) do servidor? Esta ação não pode ser desfeita.`)) return;
  let okCount = 0;
  const failures = [];
  for (const key of keys) {
    try {
      await apiFetch(`/uploads/object?object_key=${encodeURIComponent(key)}`, { method: 'DELETE' });
      okCount += 1;
      const current = _mediaSelectedSet();
      current.delete(key);
      _setMediaSelectedSet(current);
    } catch (e) {
      failures.push(`${key}: ${e.message}`);
    }
  }
  await reloadMediaManagerFiles({ silent: true });
  if (okCount) toast(`${okCount} arquivo(s) excluído(s)`, 'good');
  if (failures.length) toast(`Falha em ${failures.length} exclusão(ões)`, 'bad');
}

async function bulkSendManagedMediaToDrive() {
  const keys = Array.from(_mediaSelectedSet());
  if (!keys.length) return toast('Selecione ao menos um arquivo', 'bad');
  const cfg = mediaManagerState.driveConfig || {};
  if (!cfg?.has_credentials || !cfg?.folder_id || !cfg?.service_account_email) {
    return toast('Configure o Google Drive antes de usar o envio em lote', 'bad');
  }
  let started = 0;
  const failures = [];
  for (const key of keys) {
    const item = (mediaManagerState.items || []).find(it => String(it.object_key || '').trim() === key);
    try {
      const res = await apiFetch('/api/media-manager/google-drive/upload', {
        method: 'POST',
        body: JSON.stringify({
          object_key: key,
          filename: item?.filename || undefined,
        }),
      });
      if (!res?.job_id) throw new Error('Servidor não retornou job_id');
      mediaManagerState.driveJobs[key] = { status: 'pending', detail: 'Upload para o Google Drive iniciado…' };
      started += 1;
      _pollManagedMediaDriveJob(res.job_id, key);
    } catch (e) {
      failures.push(`${key}: ${e.message}`);
    }
  }
  renderMediaManagerList();
  if (started) toast(`${started} upload(s) iniciados para o Drive`, 'good');
  if (failures.length) toast(`Falha em ${failures.length} upload(s)`, 'bad');
}

function _formatUploadBytes(bytes) {
  const n = Number(bytes || 0);
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = n;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  const digits = value >= 100 || idx === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[idx]}`;
}

let _anUploadProgressLast = '';
let _anUploadBatchTotal = 1;

function _pushAnalyzeUploadHistory(label, kind = 'active') {
  const hist = qs('anUploadProgressHistory');
  if (!hist || !label) return;
  const clean = String(label)
    .replace(/^[✓✗!⏳📤]+\s*/u, '')
    .replace(/\s+\d+%$/g, '')
    .trim();
  if (!clean || clean === _anUploadProgressLast) return;
  _anUploadProgressLast = clean;
  const item = document.createElement('div');
  item.className = `op-progress-history-item ${kind}`;
  item.textContent = `${kind === 'good' ? '✓' : kind === 'bad' ? '!' : '•'} ${clean}`;
  hist.prepend(item);
  while (hist.children.length > 6) hist.lastElementChild?.remove();
}

function _setAnalyzeUploadProgress(pct, label, kind = 'active') {
  const isBatchUpload = Number(_anUploadBatchTotal || 1) > 1;
  const wrap = qs('anUploadProgressWrap');
  const fill = qs('anUploadProgressFill');
  const text = qs('anUploadProgressLabel');
  const ring = qs('anUploadProgressRing');
  const pctText = qs('anUploadProgressPct');
  const stateText = qs('anUploadProgressState');
  const titleText = qs('anUploadProgressTitle');
  const safePct = Math.max(0, Math.min(100, Number(pct || 0)));
  const roundedPct = Math.round(safePct);
  const stateLabel = kind === 'bad'
    ? 'erro'
    : kind === 'good'
      ? 'ok'
      : kind === 'waiting'
        ? 'confirme'
        : safePct <= 0
          ? 'aguarde'
          : 'enviando';
  const titleLabel = kind === 'bad'
    ? (isBatchUpload ? 'Falha nos uploads' : 'Falha no upload')
    : kind === 'good'
      ? (isBatchUpload ? 'Uploads concluídos' : 'Upload concluído')
      : kind === 'waiting'
        ? 'Aguardando confirmação'
        : safePct <= 0
          ? 'Preparando envio'
          : (isBatchUpload ? 'Enviando uploads' : 'Enviando arquivo');
  if (wrap) {
    wrap.style.display = '';
    wrap.style.setProperty('--upload-pct', String(safePct));
    wrap.classList.toggle('is-good', kind === 'good');
    wrap.classList.toggle('is-bad', kind === 'bad');
  }
  if (ring) ring.style.setProperty('--upload-pct', String(safePct));
  if (pctText) pctText.textContent = `${roundedPct}%`;
  if (stateText) stateText.textContent = stateLabel;
  if (titleText) titleText.textContent = titleLabel;
  if (fill) {
    fill.style.width = `${safePct}%`;
    fill.style.background = kind === 'bad'
      ? 'linear-gradient(90deg, #fb2f68, #ff7aa2)'
      : kind === 'good'
        ? 'linear-gradient(90deg, #22c55e, #86efac)'
        : 'linear-gradient(90deg, #0896ff, #1de7ff, #69f4ff)';
  }
  if (text) text.textContent = label || '';
  if (kind !== 'active' || safePct <= 0 || safePct >= 100 || /preparando|aguardando|validando|conclu/i.test(String(label || ''))) {
    _pushAnalyzeUploadHistory(label, kind);
  }
}

function _resetAnalyzeUploadProgress() {
  const wrap = qs('anUploadProgressWrap');
  const fill = qs('anUploadProgressFill');
  const text = qs('anUploadProgressLabel');
  const ring = qs('anUploadProgressRing');
  const pctText = qs('anUploadProgressPct');
  const stateText = qs('anUploadProgressState');
  const titleText = qs('anUploadProgressTitle');
  const hist = qs('anUploadProgressHistory');
  _anUploadProgressLast = '';
  _anUploadBatchTotal = 1;
  if (wrap) wrap.style.display = 'none';
  if (wrap) {
    wrap.style.setProperty('--upload-pct', '0');
    wrap.classList.remove('is-good', 'is-bad');
  }
  if (ring) ring.style.setProperty('--upload-pct', '0');
  if (pctText) pctText.textContent = '0%';
  if (stateText) stateText.textContent = 'pronto';
  if (titleText) titleText.textContent = 'Aguardando upload';
  if (fill) {
    fill.style.width = '0%';
    fill.style.background = 'linear-gradient(90deg, #0896ff, #1de7ff, #69f4ff)';
  }
  if (text) text.textContent = 'Selecione um arquivo para iniciar.';
  if (hist) hist.innerHTML = '';
}

const UI_LARGE_UPLOAD_THRESHOLD = 128 * 1024 * 1024;
const UI_LARGE_UPLOAD_CHUNK_SIZE = 16 * 1024 * 1024;

function _uploadSleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function _isTransientUploadError(err) {
  const msg = String(err?.message || '');
  return /failed to fetch|network|falha de rede|err_network_changed|load failed|temporar|timeout|time.?out|tempo esgotado|\\b5\\d\\d\\b|502|503|504/i.test(msg);
}

function _uploadTimeoutMs(bytes, minMs = 120000) {
  const size = Math.max(0, Number(bytes) || 0);
  const slowLinkMs = Math.ceil(size / (128 * 1024) * 1000) + minMs;
  return Math.max(minMs, Math.min(30 * 60 * 1000, slowLinkMs));
}

async function _retryUploadStep(fn, attempts = 8) {
  let lastErr = null;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (!_isTransientUploadError(err) || attempt >= attempts) throw err;
      await _uploadSleep(Math.min(10000, 600 * Math.pow(1.65, attempt - 1)));
    }
  }
  throw lastErr || new Error('Falha temporária no upload');
}

let _uiUploadModalState = null;
let _uiUploadModalSeq = 0;

function _formatUiUploadEta(ms) {
  const sec = Math.max(0, Math.ceil((ms || 0) / 1000));
  if (sec <= 0) return 'menos de 1s restante';
  if (sec < 60) return `${sec}s restantes`;
  const min = Math.floor(sec / 60);
  const rest = sec % 60;
  if (min < 60) return rest ? `${min}min ${rest}s restantes` : `${min}min restantes`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h ${m}min restantes` : `${h}h restantes`;
}

function _ensureUiUploadModalStyle() {
  if (document.getElementById('ui-upload-modal-style')) return;
  const style = document.createElement('style');
  style.id = 'ui-upload-modal-style';
  style.textContent = `
    #ui-upload-modal{--pct:0;position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;background:rgba(255,255,255,.94);backdrop-filter:blur(18px);font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1b2231}
    #ui-upload-modal .ui-up-wrap{width:min(440px,88vw);display:flex;flex-direction:column;align-items:center;text-align:center;gap:18px}
    #ui-upload-modal .ui-up-ring{position:relative;width:188px;height:188px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(#ff7a18 calc(var(--pct) * 1%),rgba(255,122,24,.14) 0);box-shadow:0 22px 70px rgba(255,122,24,.24),0 0 0 1px rgba(255,122,24,.18)}
    #ui-upload-modal .ui-up-ring::before{content:"";position:absolute;width:142px;height:142px;border-radius:50%;background:#fff;box-shadow:inset 0 0 0 1px rgba(20,28,45,.08)}
    #ui-upload-modal .ui-up-pct{position:relative;z-index:1;font-size:36px;font-weight:800;color:#ff7a18;letter-spacing:0}
    #ui-upload-modal .ui-up-title{font-size:22px;font-weight:800;color:#1b2231}
    #ui-upload-modal .ui-up-detail{font-size:14px;font-weight:600;color:#4b5568;min-height:22px}
    #ui-upload-modal .ui-up-eta{font-size:13px;color:#8b95a6;min-height:20px}
    #ui-upload-modal .ui-up-file{max-width:100%;font-family:"JetBrains Mono","Courier New",monospace;font-size:11px;color:#8b95a6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    #ui-upload-modal.is-error .ui-up-ring{background:conic-gradient(#fb2f68 calc(var(--pct) * 1%),rgba(251,47,104,.14) 0);box-shadow:0 22px 70px rgba(251,47,104,.22)}
    #ui-upload-modal.is-error .ui-up-pct{color:#fb2f68}
    #ui-upload-modal.is-done .ui-up-ring{background:conic-gradient(#1faa5a calc(var(--pct) * 1%),rgba(31,170,90,.14) 0);box-shadow:0 22px 70px rgba(31,170,90,.20)}
    #ui-upload-modal.is-done .ui-up-pct{color:#1faa5a}
  `;
  document.head.appendChild(style);
}

function _showUiUploadModal(file) {
  _ensureUiUploadModalStyle();
  const token = ++_uiUploadModalSeq;
  const existing = document.getElementById('ui-upload-modal');
  if (existing && _uiUploadModalState) {
    _uiUploadModalState.active = (_uiUploadModalState.active || 1) + 1;
    existing.querySelector('.ui-up-file').textContent = `${_uiUploadModalState.active} uploads em andamento`;
    _updateUiUploadModal(_uiUploadModalState.pct || 0, `Preparando ${_uiUploadModalState.active} uploads...`);
    return token;
  }

  const el = document.createElement('div');
  el.id = 'ui-upload-modal';
  el.innerHTML = `
    <div class="ui-up-wrap" role="status" aria-live="polite">
      <div class="ui-up-ring"><div class="ui-up-pct">0%</div></div>
      <div class="ui-up-title">Enviando arquivo</div>
      <div class="ui-up-detail">Preparando arquivo...</div>
      <div class="ui-up-eta">calculando tempo restante</div>
      <div class="ui-up-file"></div>
    </div>`;
  document.body.appendChild(el);
  _uiUploadModalState = { el, start: Date.now(), pct: 0, active: 1, token };
  el.querySelector('.ui-up-file').textContent = file?.name || 'upload.bin';
  _updateUiUploadModal(0, 'Preparando arquivo...');
  return token;
}

function _updateUiUploadModal(pct, detail) {
  const state = _uiUploadModalState;
  if (!state?.el) return;
  const safePct = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  state.pct = Math.max(state.pct || 0, safePct);
  const rounded = Math.round(state.pct);
  state.el.style.setProperty('--pct', String(rounded));
  state.el.querySelector('.ui-up-pct').textContent = `${rounded}%`;
  if (detail) state.el.querySelector('.ui-up-detail').textContent = detail;
  const etaEl = state.el.querySelector('.ui-up-eta');
  if (rounded <= 1) etaEl.textContent = 'calculando tempo restante';
  else if (rounded >= 99) etaEl.textContent = 'finalizando...';
  else etaEl.textContent = _formatUiUploadEta((Date.now() - state.start) * (100 - rounded) / rounded);
}

async function _finishUiUploadModal(token, kind, detail) {
  const state = _uiUploadModalState;
  if (!state?.el) return;
  state.active = Math.max(0, (state.active || 1) - 1);
  if (kind === 'done' && state.active > 0) {
    _updateUiUploadModal(state.pct || 0, `${detail || 'Upload concluído.'} ${state.active} upload${state.active === 1 ? '' : 's'} em andamento...`);
    return;
  }
  if (kind === 'error') state.active = 0;
  state.el.classList.toggle('is-done', kind === 'done');
  state.el.classList.toggle('is-error', kind === 'error');
  _updateUiUploadModal(kind === 'done' ? 100 : state.pct || 0, detail);
  await _uploadSleep(kind === 'done' ? 650 : 1600);
  if (_uiUploadModalState === state) {
    state.el.remove();
    _uiUploadModalState = null;
  }
}

function _uploadXhrJson({ method = 'POST', url, body, headers = {}, onProgress, onStart, timeoutMs = 0 }) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    if (timeoutMs) xhr.timeout = timeoutMs;
    if (state.apiKey) xhr.setRequestHeader('X-API-Key', state.apiKey);
    Object.keys(headers || {}).forEach(name => xhr.setRequestHeader(name, headers[name]));
    xhr.upload.onloadstart = () => {
      if (onStart) onStart();
    };
    xhr.upload.onprogress = (evt) => {
      if (!onProgress || !evt.lengthComputable) return;
      onProgress(evt.loaded, evt.total);
    };
    xhr.onload = () => {
      let data = {};
      try {
        data = JSON.parse(xhr.responseText || '{}');
      } catch (_) {
        data = {};
      }
      if (xhr.status >= 200 && xhr.status < 300 && data.ok) {
        resolve(data);
        return;
      }
      reject(new Error(data.detail || data.error || `HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error('Falha de rede no upload'));
    xhr.onabort = () => reject(new Error('Upload cancelado pelo navegador'));
    xhr.ontimeout = () => reject(new Error('Tempo esgotado no upload'));
    xhr.send(body);
  });
}

async function _uploadViaLocalStream(file, opts, prefix, validateVideo, deleteIfInvalid) {
  const url = `/uploads/local-stream?prefix=${encodeURIComponent(prefix)}`
    + (validateVideo ? '&validate=1' : '')
    + (deleteIfInvalid ? '&delete_if_invalid=1' : '');
  if (opts.onDetail) opts.onDetail('Enviando arquivo para o servidor...');
  return _uploadXhrJson({
    method: 'POST',
    url,
    body: file,
    headers: {
      'X-Filename': file.name || 'upload.bin',
      'X-File-Size': String(file.size || 0),
      'Content-Type': file.type || 'application/octet-stream',
    },
    onStart: () => {
      if (opts.onStart) opts.onStart(file.size || 0);
    },
    onProgress: (loaded, total) => {
      if (!opts.onProgress) return;
      opts.onProgress(loaded, total || file.size || 0);
    },
    timeoutMs: _uploadTimeoutMs(file.size || 0, 180000),
  });
}

async function _abortChunkUpload(uploadId) {
  if (!uploadId) return;
  try {
    await apiFetch('/uploads/chunk/abort', {
      method: 'POST',
      body: JSON.stringify({ upload_id: uploadId }),
    });
  } catch (_) {}
}

async function _uploadChunkPartWithRetry(args) {
  return _retryUploadStep(async () => {
      const form = new FormData();
      form.append('upload_id', args.uploadId);
      form.append('part_number', String(args.partNumber));
      form.append('chunk', args.blob, args.filename || 'chunk.bin');
      return await _uploadXhrJson({
        method: 'POST',
        url: '/uploads/chunk/part',
        body: form,
        timeoutMs: _uploadTimeoutMs(args.blob?.size || 0),
        onProgress: (loaded) => {
          if (args.onProgress) args.onProgress(args.uploadedBefore + loaded, args.totalSize);
        },
      });
  }, 8);
}

async function _uploadViaChunked(file, opts, prefix, validateVideo, deleteIfInvalid) {
  const totalSize = Math.max(0, file.size || 0);
  const chunkSize = UI_LARGE_UPLOAD_CHUNK_SIZE;
  const totalParts = Math.max(1, Math.ceil(totalSize / chunkSize));
  if (opts.onStart) opts.onStart(totalSize);
  if (opts.onDetail) opts.onDetail('Preparando upload em partes...');
  const init = await _retryUploadStep(() => apiFetch('/uploads/chunk/init', {
    method: 'POST',
    body: JSON.stringify({
      filename: file.name || 'upload.bin',
      content_type: file.type || 'application/octet-stream',
      prefix,
      size: totalSize,
      chunk_size: chunkSize,
      total_parts: totalParts,
      validate: validateVideo,
      delete_if_invalid: deleteIfInvalid,
    }),
  }), 5);
  if (!init?.ok || !init.upload_id) {
    throw new Error(init?.detail || init?.error || 'Falha ao iniciar upload em partes');
  }

  const uploadId = init.upload_id;
  try {
    for (let index = 0; index < totalParts; index++) {
      const start = index * chunkSize;
      const end = Math.min(totalSize, start + chunkSize);
      if (opts.onDetail) opts.onDetail(`Enviando parte ${index + 1} de ${totalParts}...`);
      await _uploadChunkPartWithRetry({
        uploadId,
        partNumber: index + 1,
        blob: file.slice(start, end),
        filename: file.name || 'upload.bin',
        uploadedBefore: start,
        totalSize,
        onProgress: opts.onProgress,
      });
      if (opts.onProgress) opts.onProgress(end, totalSize);
    }
    if (opts.onDetail) opts.onDetail('Finalizando envio e validando mídia...');
    const done = await _retryUploadStep(() => _uploadXhrJson({
      method: 'POST',
      url: '/uploads/chunk/complete',
      body: JSON.stringify({ upload_id: uploadId }),
      headers: { 'Content-Type': 'application/json' },
      timeoutMs: 10 * 60 * 1000,
    }), 8);
    if (!done?.ok || !done.object_key) {
      throw new Error(done?.detail || done?.error || 'Falha ao concluir upload em partes');
    }
    if (opts.onProgress) opts.onProgress(totalSize, totalSize);
    return done;
  } catch (err) {
    await _abortChunkUpload(uploadId);
    throw err;
  }
}

// Upload direto ao backend. Arquivos grandes usam partes menores para evitar 502/timeouts.
async function _uploadViaProxy(file, opts = {}) {
  const prefix = String(opts.prefix || 'uploads').trim() || 'uploads';
  const validateVideo = !!opts.validateVideo;
  const deleteIfInvalid = !!opts.deleteIfInvalid;
  const modalToken = _showUiUploadModal(file);
  const modalOpts = {
    ...opts,
    onDetail: (detail) => {
      _updateUiUploadModal(_uiUploadModalState?.pct || 0, detail);
      if (opts.onDetail) opts.onDetail(detail);
    },
    onStart: (total) => {
      _updateUiUploadModal(0, 'Conexão aberta para upload...');
      if (opts.onStart) opts.onStart(total);
    },
    onProgress: (loaded, total) => {
      const safeTotal = total || file.size || 0;
      if (safeTotal > 0) {
        _updateUiUploadModal(Math.round(Math.max(0, Math.min(loaded || 0, safeTotal)) / safeTotal * 100));
      }
      if (opts.onProgress) opts.onProgress(loaded, total);
    },
  };
  try {
    let result;
    if ((file.size || 0) >= UI_LARGE_UPLOAD_THRESHOLD) {
      result = await _uploadViaChunked(file, modalOpts, prefix, validateVideo, deleteIfInvalid);
    } else {
      result = await _retryUploadStep(() => _uploadViaLocalStream(file, modalOpts, prefix, validateVideo, deleteIfInvalid), 5);
    }
    await _finishUiUploadModal(modalToken, 'done', 'Upload concluído.');
    return result;
  } catch (err) {
    await _finishUiUploadModal(modalToken, 'error', `Upload falhou: ${err?.message || err}`);
    throw err;
  }
}

function _selectAnalyzeUploadedVideo(proxy, file) {
  state.videoObjectKey = proxy?.object_key || null;
  state.videoUrl = proxy?.public_url || null;
  state.videoOriginalFilename = file?.name || '';
  const keyEl = qs('anObjectKey');
  const urlEl = qs('anVideoUrl');
  if (keyEl) keyEl.textContent = state.videoObjectKey || '-';
  if (urlEl) urlEl.textContent = state.videoUrl || '-';
}

async function _saveAnalyzeUploadMeta(proxy, file) {
  if (!proxy?.object_key) return;
  try {
    await apiFetch('/uploads/set-meta', { method: 'POST', body: JSON.stringify({
      object_key: proxy.object_key,
      display_name: file?.name || '',
      company_id: '',
      company_name: '',
    })});
  } catch (_) {}
}

function _analyzeTranscribeProviderLabel(provider) {
  return ({
    auto: 'Auto estrito',
    assemblyai: 'AssemblyAI',
    groq: 'OpenRouter STT',
    openrouter: 'OpenRouter STT',
    openai: 'OpenAI',
    local: 'Local',
    premium: '⭐ Premium (large-v3)',
  })[provider] || provider || 'Auto estrito';
}

async function transcribeAnalyzeSelected(provider = 'auto') {
  const objectKeyText = (qs('anObjectKey')?.textContent || '').trim();
  const objectKey = (state.videoObjectKey || (objectKeyText !== '-' ? objectKeyText : '') || '').trim();
  if (!objectKey) return toast('Selecione ou suba um vídeo antes de transcrever', 'bad');
  const providerName = _analyzeTranscribeProviderLabel(provider);
  try {
    qs('anUploadStatus').textContent = `status: transcrevendo com ${providerName}…`;
    transcribeProgress.start([
      { pct: 18, label: 'Baixando vídeo do storage…',  minMs: 2500 },
      { pct: 42, label: 'Extraindo áudio com ffmpeg…', minMs: 3500 },
      { pct: 88, label: provider === 'assemblyai' ? 'AssemblyAI processando áudio…' : provider === 'premium' ? 'Carregando modelo large-v3 e transcrevendo…' : `Transcrevendo com ${providerName}…`, minMs: 99999 },
    ]);
    const lang = qs('anLang')?.value || null;
    const includeVocalizations = qs('anIncludeVocalizations')?.checked === true;
    const enhanceAudio = qs('anTranscribeEnhanceAudio')?.checked === true;
    const payload = {
      video_object_key: objectKey,
      provider,
      adult_mode: true,
      include_vocalizations: includeVocalizations,
      enhance_audio: enhanceAudio,
    };
    if (lang && lang !== 'auto') payload.language = lang;
    const tr = await apiFetch('/transcribe', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    if (tr?.ok && tr?.transcript?.text) {
      qs('anTranscript').value = tr.transcript.text;
      qs('anSrt').textContent = tr.transcript.srt || '';
      state.transcriptSegments = tr.transcript.segments || [];
      state.transcriptSrt = tr.transcript.srt || '';
      if (tr.probe) {
        if (tr.probe.duration_seconds) qs('anDur').value = tr.probe.duration_seconds.toFixed(1);
        if (tr.probe.width) qs('anW').value = tr.probe.width;
        if (tr.probe.height) qs('anH').value = tr.probe.height;
        if (tr.probe.fps) qs('anFps').value = tr.probe.fps;
      }
      transcribeProgress.complete('✓ Transcrição concluída');
      qs('anUploadStatus').textContent = 'status: transcrição concluída';
      toast(`Transcrição preenchida via ${tr.transcript.provider || providerName}`);
    } else if (tr?.error) {
      const detail = tr.detail ? ` — ${tr.detail}` : '';
      transcribeProgress.error(`✗ ${tr.error}${detail}`);
      qs('anUploadStatus').textContent = `status: transcrição falhou (${tr.error}${detail})`;
      toast('Transcrição falhou: ' + (tr.detail || tr.error), 'bad');
    } else {
      transcribeProgress.hide();
      qs('anUploadStatus').textContent = 'status: transcrição não retornou texto';
    }
  } catch (e) {
    transcribeProgress.error(`✗ ${e.message}`);
    qs('anUploadStatus').textContent = 'status: erro transcrição';
    toast('Erro ao transcrever: ' + e.message, 'bad');
  }
}

async function uploadVideo() {
  const input = qs('anVideoFile');
  const files = Array.from(input?.files || []).filter(Boolean);
  if (!files.length) return toast('Selecione um ou mais vídeos', 'bad');

  const totalFiles = files.length;
  const totalBytes = files.reduce((sum, file) => sum + (file.size || 0), 0);
  const loadedByIndex = new Map(files.map((_, idx) => [idx, 0]));
  const startedAt = Date.now();
  const results = [];
  const failures = [];
  let completed = 0;
  let nextIndex = 0;

  _anUploadBatchTotal = totalFiles;

  const batchLabel = totalFiles === 1 ? '1 vídeo' : `${totalFiles} vídeos`;
  qs('anUploadStatus').textContent = `status: preparando upload de ${batchLabel} (${_formatUploadBytes(totalBytes)})`;
  _setAnalyzeUploadProgress(0, `Preparando envio de ${batchLabel}. O upload começa automaticamente, sem formulário.`, 'active');

  const updateBatchProgress = (label, kind = 'active') => {
    const loaded = Array.from(loadedByIndex.values()).reduce((sum, value) => sum + value, 0);
    const pct = totalBytes > 0 ? Math.min(100, Math.round((loaded / totalBytes) * 100)) : 0;
    const elapsedSec = Math.max(0.001, (Date.now() - startedAt) / 1000);
    const speed = loaded > 0 ? `${_formatUploadBytes(loaded / elapsedSec)}/s` : '';
    const suffix = speed && kind === 'active' ? ` · ${speed}` : '';
    qs('anUploadStatus').textContent = `status: ${completed}/${totalFiles} enviados, ${failures.length} falharam — ${pct}%${suffix}`;
    _setAnalyzeUploadProgress(pct, label, kind);
  };

  const uploadOne = async (file, index) => {
    const fileSizeText = _formatUploadBytes(file.size || 0);
    updateBatchProgress(`Arquivo ${index + 1}/${totalFiles}: iniciando ${file.name || 'vídeo'} (${fileSizeText})…`);
    try {
      const proxy = await _uploadViaProxy(file, {
        prefix: 'uploads',
        validateVideo: true,
        deleteIfInvalid: true,
        onStart: () => {
          loadedByIndex.set(index, 0);
          updateBatchProgress(`Arquivo ${index + 1}/${totalFiles}: conexão aberta para ${file.name || 'vídeo'}…`);
        },
        onProgress: (loaded, total) => {
          const safeLoaded = Math.max(0, Math.min(loaded || 0, total || file.size || 0));
          loadedByIndex.set(index, safeLoaded);
          const loadedText = _formatUploadBytes(safeLoaded);
          const totalText = _formatUploadBytes(total || file.size || 0);
          updateBatchProgress(`Arquivo ${index + 1}/${totalFiles}: ${file.name || 'vídeo'} — ${loadedText}/${totalText}…`);
        },
      });

      loadedByIndex.set(index, file.size || 0);
      completed += 1;
      await _saveAnalyzeUploadMeta(proxy, file);
      results.push({ file, proxy, index });
      _pushAnalyzeUploadHistory(`✓ ${file.name || 'vídeo'} enviado`, 'good');
      updateBatchProgress(`Arquivo ${index + 1}/${totalFiles}: upload concluído — ${file.name || 'vídeo'}.`);
    } catch (e) {
      loadedByIndex.set(index, file.size || 0);
      failures.push({ file, error: e });
      _pushAnalyzeUploadHistory(`✗ ${file.name || 'vídeo'} falhou: ${e.message}`, 'bad');
      updateBatchProgress(`Arquivo ${index + 1}/${totalFiles}: falha em ${file.name || 'vídeo'} — ${e.message}.`);
    }
  };

  const worker = async () => {
    while (nextIndex < totalFiles) {
      const index = nextIndex;
      nextIndex += 1;
      await uploadOne(files[index], index);
    }
  };

  try {
    const parallelUploads = Math.min(2, totalFiles);
    await Promise.all(Array.from({ length: parallelUploads }, worker));

    if (!results.length) {
      const firstError = failures[0]?.error?.message || 'nenhum arquivo foi enviado';
      qs('anUploadStatus').textContent = `status: todos os uploads falharam — ${firstError}`;
      _setAnalyzeUploadProgress(100, `Todos os uploads falharam: ${firstError}`, 'bad');
      toast('Todos os uploads falharam: ' + firstError, 'bad');
      return;
    }

    const selected = results[results.length - 1];
    _selectAnalyzeUploadedVideo(selected.proxy, selected.file);

    if (failures.length) {
      qs('anUploadStatus').textContent = `status: ${results.length}/${totalFiles} uploads concluídos; ${failures.length} falharam. Selecionado: ${selected.file.name}`;
      _setAnalyzeUploadProgress(100, `${results.length}/${totalFiles} uploads concluídos. ${failures.length} falharam. Último enviado selecionado: ${selected.file.name}.`, 'bad');
      toast(`${results.length}/${totalFiles} uploads concluídos; ${failures.length} falharam`, 'bad');
      return;
    }

    qs('anUploadStatus').textContent = `status: ${results.length} upload${results.length === 1 ? '' : 's'} concluído${results.length === 1 ? '' : 's'}. Selecionado: ${selected.file.name}`;
    _setAnalyzeUploadProgress(100, `${results.length} upload${results.length === 1 ? '' : 's'} concluído${results.length === 1 ? '' : 's'}. ${selected.file.name} ficou selecionado.`, 'good');
    toast(results.length === 1 ? 'Upload concluído' : `${results.length} uploads concluídos`, 'good');

    transcribeProgress.hide();
  } catch (e) {
    qs('anUploadStatus').textContent = `status: erro no upload — ${e.message}`;
    _setAnalyzeUploadProgress(100, `Erro no upload: ${e.message}`, 'bad');
    toast(e.message, 'bad');
  } finally {
    if (input) input.value = '';
  }
}

async function doAnalyze() {
  const text = qs('anTranscript').value.trim();

  const limit = parseInt(qs('anLimit').value || '20', 10);
  const lang = qs('anLang').value || 'auto';

  const duration = parseFloat(qs('anDur').value || '0');
  const width = parseInt(qs('anW').value || '0', 10);
  const height = parseInt(qs('anH').value || '0', 10);
  const fps = parseFloat(qs('anFps').value || '0');

  // Coletar sites selecionados
  const refSites = Array.from(document.querySelectorAll('input[name="ref_site"]:checked')).map(i => i.value);
  const objectKeyText = (qs('anObjectKey')?.textContent || '').trim();
  const videoUrlText = (qs('anVideoUrl')?.textContent || '').trim();
  const resolvedObjectKey = ((state.videoObjectKey || '') || (objectKeyText !== '-' ? objectKeyText : '')).trim() || null;
  const resolvedVideoUrl = ((state.videoUrl || '') || (videoUrlText !== '-' ? videoUrlText : '')).trim() || null;

  state.videoObjectKey = resolvedObjectKey;
  state.videoUrl = resolvedVideoUrl;

  const payload = {
    video_object_key: resolvedObjectKey,
    video_url: resolvedVideoUrl,
    original_filename: state.videoOriginalFilename || '',
    video_metadata: {
      probe: {
        duration_seconds: duration || 0,
        width: width || 0,
        height: height || 0,
        fps: fps || 0,
      }
    },
    transcript: text ? { provider: 'local', lang, text, segments: state.transcriptSegments || [], srt: state.transcriptSrt || qs('anSrt')?.textContent || '' } : null,
    stt_provider: 'none',

    // Filtros de Referência
    ref_sites: refSites,
    ref_actor:       qs('refActor').value.trim() || null,
    ref_actor_count: qs('refActorCount').value || null,
    ref_country:     qs('refCountry').value.trim() || null,
    ref_category:    qs('refCategory').value.trim() || null,
    ref_studio:      qs('refStudio').value.trim() || null,
    // Duração: select nativo → converte para dur_min/dur_max em segundos
    ...((() => {
      const durRange = qs('refDurRange').value;
      if (durRange === '1-3')  return { ref_dur_min: 60,  ref_dur_max: 180 };
      if (durRange === '3-10') return { ref_dur_min: 180, ref_dur_max: 600 };
      if (durRange === '10-20') return { ref_dur_min: 600, ref_dur_max: 1200 };
      if (durRange === '20+')  return { ref_dur_min: 1200, ref_dur_max: null };
      return { ref_dur_min: null, ref_dur_max: null };
    })()),
    // Pós-filtros
    ref_views_min: parseInt(qs('refViewsMin').value) || null,
    ref_views_max: parseInt(qs('refViewsMax').value) || null,
    ref_likes_min: parseInt(qs('refLikesMin').value) || null,

    limit: limit || 20,
  };

  qs('btnAnalyze').disabled = true;
  qs('btnAnalyze').textContent = 'Analisando…';
  analyzeProgress.start([
    { pct: 10, label: 'Baixando vídeo do storage…',       minMs: 5000  },
    { pct: 25, label: 'Extraindo frames por cena…',       minMs: 10000 },
    { pct: 45, label: 'Analisando frames com Vision AI…', minMs: 20000 },
    { pct: 65, label: 'Carregando referências…',          minMs: 8000  },
    { pct: 80, label: 'LLM gerando metadados…',           minMs: 99999 },
  ]);
  let _analyzePollTimer = null;
  try {
    const startRes = await apiFetch('/analyze/start', { method: 'POST', body: JSON.stringify(payload) });
    const jobId = startRes.job_id;
    const r = await new Promise((resolve, reject) => {
      _analyzePollTimer = setInterval(async () => {
        try {
          const job = await apiFetch(`/analyze/status/${jobId}`);
          if (job.progress_pct != null) analyzeProgress._updatePct(job.progress_pct, job.detail || '');
          if (job.status === 'done') {
            clearInterval(_analyzePollTimer);
            resolve(job.result);
          } else if (job.status === 'error') {
            clearInterval(_analyzePollTimer);
            reject(new Error(job.detail || 'Analyze falhou'));
          }
        } catch (pollErr) { /* continua polling em erros transientes */ }
      }, 2000);
    });
    state.lastAnalyze = r;
    qs('anRunId').textContent = r.run_id || '-';
    const prompt = r?.grok?.markdown_prompt_ptbr_keep_original || '';
    qs('anPrompt').textContent = prompt;
    qs('anJson').textContent = JSON.stringify(r, null, 2);

    // Render Vision
    const vis = r.vision || {};
    const framesWrap = qs('anVisionFrames');
    framesWrap.innerHTML = '';
    (vis.frames || []).forEach(b64 => {
      const img = document.createElement('img');
      img.src = `data:image/jpeg;base64,${b64}`;
      img.className = 'clickable-frame';
      img.onclick = () => analyzeScreenshot(img.src);
      framesWrap.appendChild(img);
    });
    const ana = vis.analysis || {};
    const vdbg = vis.debug || {};
    const skipReasonMap = {
      no_video_object_key: 'nenhum vídeo selecionado para análise',
      s3_not_configured: 'storage não configurado no backend',
      duration_zero_after_probe: 'duração do vídeo inválida/zerada',
      no_frames_extracted: 'nenhum frame foi extraído',
      analyze_exception: 'erro interno durante o analyze',
    };
    let visionDesc = '';
    if (typeof ana.description === 'string' && ana.description.trim()) {
      visionDesc = ana.description;
    } else if (r.error) {
      visionDesc = `Analyze falhou: ${r.error}`;
    } else if (ana._api_error) {
      visionDesc = `Erro Vision API (${ana._api_error}): ${ana._detail || 'sem detalhe'}`;
    } else if (ana._exception) {
      visionDesc = `Falha interna Vision: ${ana._exception}`;
    } else if (ana._refused) {
      visionDesc = 'Vision recusou a análise (policy/moderação).';
    } else if (vdbg.analysis_error === 'missing_grok_token') {
      visionDesc = 'Vision não executada: configure token:grok em Settings.';
    } else if (vdbg.analysis_error) {
      visionDesc = `Vision falhou: ${vdbg.analysis_error}`;
    } else if (vdbg.error) {
      visionDesc = `Vision falhou: ${vdbg.error}`;
    } else if (vdbg.skipped_reason) {
      const reason = skipReasonMap[vdbg.skipped_reason] || vdbg.skipped_reason;
      visionDesc = `Vision não executada: ${reason}`;
    } else {
      visionDesc = resolvedObjectKey
        ? 'Vision não retornou diagnóstico (veja JSON).'
        : 'Vision não executada: nenhum vídeo selecionado para análise.';
    }
    const tagsText = Array.isArray(ana.tags) && ana.tags.length ? ana.tags.join(', ') : '-';
    qs('anVisionAnalysis').innerHTML = `
      <p><b>IA Vision (Consolidada):</b> ${visionDesc}</p>
      <p><b>Tags Sugeridas:</b> ${tagsText}</p>
    `;

    setAnalyzeTab('prompt');
    analyzeProgress.complete('✓ Análise concluída');
    toast('Análise concluída');
  } catch (e) {
    analyzeProgress.error(`✗ ${e.message}`);
    toast(e.message, 'bad');
  } finally {
    if (_analyzePollTimer) clearInterval(_analyzePollTimer);
    qs('btnAnalyze').disabled = false;
    qs('btnAnalyze').textContent = 'Analisar';
  }
}

async function analyzeScreenshot(providedB64 = null) {
  if (providedB64) {
    return _doVisionRequest(providedB64);
  }

  const file = qs('scrFile').files?.[0];
  if (!file) return toast('Selecione uma imagem primeiro', 'bad');

  const reader = new FileReader();
  reader.onload = (e) => _doVisionRequest(e.target.result);
  reader.readAsDataURL(file);
}

async function _doVisionRequest(base64) {
  qs('btnScrAnalyze').disabled = true;
  qs('btnScrAnalyze').textContent = 'Analisando...';
  try {
    const res = await apiFetch('/api/screenshot/analyze', {
      method: 'POST',
      body: JSON.stringify({ image_base64: base64 })
    });
    if (res.error) {
      const detail = String(res.detail || res.error || 'vision_failed');
      const modelInfo = res.model_used ? ` (modelo: ${res.model_used})` : '';
      throw new Error(`${detail}${modelInfo}`);
    }

    // Se estivermos na aba Vision, atualizar o resultado lá também
    if (qs('anVisionAnalysis')) {
      qs('anVisionAnalysis').innerHTML = `
            <p><b>IA Vision (Individual):</b> ${res.description}</p>
            <p><b>Tags Sugeridas:</b> ${(res.tags || []).join(', ')}</p>
        `;
      setAnalyzeTab('vision');
    }

    qs('scrResult').classList.remove('hidden');
    qs('scrDesc').textContent = res.description;
    qs('scrTags').textContent = (res.tags || []).join(', ');
    toast('Screenshot analisado');
  } catch (err) {
    toast('Erro na análise: ' + err.message, 'bad');
  } finally {
    qs('btnScrAnalyze').disabled = false;
    qs('btnScrAnalyze').textContent = 'Analisar com IA';
  }
}

function clearAnalyze() {
  qs('anTranscript').value = '';
  qs('anRunId').textContent = '-';
  qs('anPrompt').textContent = '';
  qs('anJson').textContent = '';
  qs('anObjectKey').textContent = '-';
  qs('anVideoUrl').textContent = '-';
  qs('anUploadStatus').textContent = 'status: -';
  qs('anVideoFile').value = '';
  _resetAnalyzeUploadProgress();
  state.videoObjectKey = null;
  state.videoUrl = null;
  state.lastAnalyze = null;
}

function downloadSrt() {
  const txt = qs('anSrt').textContent;
  if (!txt) return toast('SRT está vazio', 'bad');
  const blob = new Blob([txt], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `legenda_${qs('anRunId').textContent || 'video'}.srt`;
  a.click();
  URL.revokeObjectURL(url);
}

async function copyText(txt) {
  try {
    await navigator.clipboard.writeText(txt);
    toast('Copiado');
  } catch (e) {
    toast('Falha ao copiar', 'bad');
  }
}

// COMPARE
let _ollamaStatusCache = null;
async function _checkOllamaWarning() {
  const pa = qs('cmpProvA').value;
  const pb = qs('cmpProvB').value;
  if (pa !== 'ollama' && pb !== 'ollama') return;
  try {
    if (!_ollamaStatusCache) {
      const r = await fetch('/api/ollama/status');
      _ollamaStatusCache = await r.json();
      setTimeout(() => { _ollamaStatusCache = null; }, 30000); // cache 30s
    }
    const loaded = _ollamaStatusCache?.loaded || [];
    const cpuModels = loaded.filter(m => !m.on_gpu);
    if (cpuModels.length) {
      const names = cpuModels.map(m => `${m.name} (${m.params})`).join(', ');
      toast(`Ollama sem GPU: ${names} — inferência em CPU, lento`, 'bad');
    }
  } catch (_) {}
}

function wireModelDefaults() {
  qs('cmpProvA').addEventListener('change', () => { updateModelOptions('cmpProvA', 'cmpModelA'); _checkOllamaWarning(); });
  qs('cmpProvB').addEventListener('change', () => { updateModelOptions('cmpProvB', 'cmpModelB'); _checkOllamaWarning(); });
}

function cmpStatusEl(idx) {
  return idx === 0 ? qs('cmpStatusA') : qs('cmpStatusB');
}

function cmpOutEl(idx) {
  return idx === 0 ? qs('cmpOutA') : qs('cmpOutB');
}

function friendlyProviderError(provider, rawError) {
  const txt = String(rawError || '').trim();
  const lower = txt.toLowerCase();

  if (!txt) return 'unknown';
  if (lower.includes('missing_api_key')) return `token não configurado para ${provider} (Settings)`;
  if (provider === 'deepseek' && (lower.includes('402') || lower.includes('payment required'))) {
    return 'DeepSeek sem saldo/crédito (HTTP 402 Payment Required)';
  }
  if (lower.includes('401') || lower.includes('unauthorized')) return `token inválido ou sem permissão (${provider})`;
  if (lower.includes('402') || lower.includes('payment required')) return `sem crédito/saldo (${provider})`;
  if (lower.includes('429') || lower.includes('rate limit')) return `limite de taxa excedido — tente outro modelo (${provider})`;
  if (lower.includes('404') || lower.includes('no endpoints found') || lower.includes('not a valid model')) return `modelo não encontrado/indisponível no ${provider} — ID incorreto ou removido`;
  if (lower.includes('timeout')) return provider === 'ollama'
    ? 'timeout — modelo local ainda carregando, aguarde ~30s e tente novamente'
    : `timeout de resposta (${provider})`;
  return txt;
}

function parseSseBlock(block) {
  const lines = block.split(/\r?\n/);
  let ev = 'message';
  const dataLines = [];
  lines.forEach(line => {
    if (line.startsWith('event:')) ev = line.slice(6).trim();
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  });
  if (!dataLines.length) return null;
  return { event: ev, data: dataLines.join('\n') };
}

let _compareProgressLast = '';

function _compareProgressReset() {
  _compareProgressLast = '';
  const hist = qs('cmpProgressHistory');
  if (hist) hist.innerHTML = '';
}

function _compareProgressPush(detail, kind = 'active') {
  const hist = qs('cmpProgressHistory');
  if (!hist || !detail) return;
  const clean = String(detail).replace(/^[✓✗!•⏳]+\s*/u, '').trim();
  if (!clean || clean === _compareProgressLast) return;
  _compareProgressLast = clean;
  const item = document.createElement('div');
  item.className = `op-progress-history-item ${kind}`;
  item.textContent = `${kind === 'good' ? '✓' : kind === 'bad' ? '!' : '•'} ${clean}`;
  hist.prepend(item);
  while (hist.children.length > 6) hist.lastElementChild?.remove();
}

function _setCompareProgress(pct, detail, kind = 'active', opts = {}) {
  const wrap = qs('cmpProgressWrap');
  if (!wrap) return;
  const safePct = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  wrap.style.display = 'grid';
  wrap.classList.toggle('is-good', kind === 'good');
  wrap.classList.toggle('is-bad', kind === 'bad');
  wrap.style.setProperty('--upload-pct', safePct.toFixed(1));
  qs('cmpProgressRing')?.style.setProperty('--upload-pct', safePct.toFixed(1));
  if (qs('cmpProgressPct')) qs('cmpProgressPct').textContent = `${Math.round(safePct)}%`;
  if (qs('cmpProgressState')) {
    qs('cmpProgressState').textContent = kind === 'good' ? 'ok' : kind === 'bad' ? 'erro' : (safePct > 8 ? 'rodando' : 'aguarde');
  }
  if (qs('cmpProgressLabel')) qs('cmpProgressLabel').textContent = detail || 'Processando comparação…';
  if (qs('cmpProgBarFill')) qs('cmpProgBarFill').style.width = `${safePct.toFixed(1)}%`;
  if (opts.log !== false) _compareProgressPush(detail, kind);
}

function applyCompareStreamMessage(msg) {
  // delega para o handler de progresso detalhado se ativo
  if (window._cmpApplyPatch) window._cmpApplyPatch(msg);

  const idx = Number(msg?.provider_index);
  if (!(idx === 0 || idx === 1)) return false;

  const ev = msg?.event;
  if (ev === 'provider_start') {
    cmpStatusEl(idx).textContent = 'running…';
    return false;
  }
  if (ev === 'delta') {
    cmpOutEl(idx).textContent += msg?.delta || '';
    return false;
  }
  if (ev === 'provider_done') {
    cmpStatusEl(idx).textContent = 'done ✓';
    return true;
  }
  if (ev === 'error') {
    const friendly = friendlyProviderError(msg?.provider || 'provider', msg?.error);
    cmpStatusEl(idx).textContent = `erro: ${friendly}`;
    return true;
  }
  return false;
}

async function doCompareStream(payload) {
  const headers = { 'content-type': 'application/json' };
  if (state.apiKey) headers['X-API-Key'] = state.apiKey;

  const res = await fetch('/llm/compare/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });
  const ct = res.headers.get('content-type') || '';
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    if (ct.includes('application/json')) {
      const j = await res.json();
      msg = j?.detail || j?.error || JSON.stringify(j);
    } else {
      msg = await res.text();
    }
    throw new Error(`stream_error: ${msg}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error('stream_error: sem body para leitura');

  const decoder = new TextDecoder();
  let doneProviders = 0;
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';

    blocks.forEach(block => {
      const parsed = parseSseBlock(block);
      if (!parsed) return;

      let obj = null;
      try {
        obj = JSON.parse(parsed.data);
      } catch (e) {
        return;
      }
      if (!obj || typeof obj !== 'object') return;
      if (!obj.event) obj.event = parsed.event;

      if (applyCompareStreamMessage(obj)) doneProviders += 1;
    });

    if (doneProviders >= 2) return;
  }

  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer.trim());
    if (parsed) {
      try {
        const obj = JSON.parse(parsed.data);
        if (obj && typeof obj === 'object') {
          if (!obj.event) obj.event = parsed.event;
          if (applyCompareStreamMessage(obj)) doneProviders += 1;
        }
      } catch (e) {
        // ignore malformed tail chunk
      }
    }
  }

  if (doneProviders === 0) {
    throw new Error('stream_error: conexão encerrada sem eventos');
  }
}

async function doCompareNonStream(payload) {
  const r = await apiFetch('/llm/compare', { method: 'POST', body: JSON.stringify(payload) });
  const a = r.results?.[0];
  const b = r.results?.[1];

  qs('cmpStatusA').textContent = a?.ok ? 'status: done' : `status: error (${friendlyProviderError(a?.provider || 'provider', a?.error)})`;
  qs('cmpStatusB').textContent = b?.ok ? 'status: done' : `status: error (${friendlyProviderError(b?.provider || 'provider', b?.error)})`;
  qs('cmpOutA').textContent = a?.text || '';
  qs('cmpOutB').textContent = b?.text || '';
}

async function doCompare() {
  const prompt = qs('cmpPrompt').value.trim();
  if (!prompt) return toast('Prompt vazio', 'bad');

  const pa = qs('cmpProvA').value;
  const pb = qs('cmpProvB').value;
  const ma = qs('cmpModelA').value.trim();
  const mb = qs('cmpModelB').value.trim();
  if (!ma || !mb) return toast('Defina os modelos dos dois providers', 'bad');

  const temperature = parseFloat(qs('cmpTemp').value || '0.7');
  const max_tokens = parseInt(qs('cmpMax').value || '1200', 10);

  const payload = {
    prompt_markdown: prompt,
    providers: [
      { name: pa, model: ma },
      { name: pb, model: mb },
    ],
    params: { temperature, max_tokens },
  };

  // Avisa sobre modelos CPU-only lentos
  const ollamaModels = [];
  if (pa === 'ollama') ollamaModels.push(`A:${ma}`);
  if (pb === 'ollama') ollamaModels.push(`B:${mb}`);
  if (ollamaModels.length) {
    const isMixtral = ollamaModels.some(m => m.includes('mixtral'));
    if (isMixtral) {
      const ok = confirm(
        'AVISO: dolphin-mixtral:8x7b tem 46.7B parâmetros rodando em CPU.\n' +
        'Estimativa: 15-40 minutos para completar.\n\n' +
        'Recomendado: use dolphin3:8b (8B params, ~3-5 min) ou um provider online.\n\n' +
        'Continuar mesmo assim?'
      );
      if (!ok) return;
    } else {
      toast(`Ollama CPU (sem GPU): ${ollamaModels.join(', ')} — aguarde alguns minutos`, 'bad');
    }
  }

  qs('btnCompare').disabled = true;
  qs('btnCompare').textContent = 'Comparando…';
  qs('cmpOutA').textContent = '';
  qs('cmpOutB').textContent = '';
  qs('cmpStatusA').textContent = 'aguardando…';
  qs('cmpStatusB').textContent = 'aguardando…';
  _compareProgressReset();

  // ── progresso detalhado ──
  const _progState = { tokA: 0, tokB: 0, startMs: Date.now() };
  function _cmpProgUpdate() {
    const secs = Math.floor((Date.now() - _progState.startMs) / 1000);
    const mm = String(Math.floor(secs / 60)).padStart(2, '0');
    const ss = String(secs % 60).padStart(2, '0');
    qs('cmpProgElapsed').textContent = `${mm}:${ss}`;
    qs('cmpProgTokensA').textContent = `${_progState.tokA} tok`;
    qs('cmpProgTokensB').textContent = `${_progState.tokB} tok`;
    const tokenTarget = Math.max(1, (max_tokens || 1200) * 2);
    const tokenPct = Math.min(66, ((_progState.tokA + _progState.tokB) / tokenTarget) * 66);
    const timePct = Math.min(20, secs / 3);
    const pct = Math.min(94, 8 + tokenPct + timePct);
    _setCompareProgress(pct, `Gerando respostas · A ${_progState.tokA} tok · B ${_progState.tokB} tok · ${mm}:${ss}`, 'active', { log: false });
  }
  function _cmpProgSetState(idx, state, detail) {
    const dot = qs(idx === 0 ? 'cmpProgDotA' : 'cmpProgDotB');
    const det = qs(idx === 0 ? 'cmpProgDetailA' : 'cmpProgDetailB');
    dot.className = 'cmp-prog-dot ' + state;
    det.textContent = detail;
  }
  function _cmpProgSetNames(nameA, nameB) {
    qs('cmpProgNameA').textContent = nameA;
    qs('cmpProgNameB').textContent = nameB;
  }

  // inicializa nomes com provider+model
  _cmpProgSetNames(
    `A: ${pa}/${(qs('cmpModelA').value || '').split(':')[0]}`,
    `B: ${pb}/${(qs('cmpModelB').value || '').split(':')[0]}`
  );
  _cmpProgSetState(0, 'running', 'conectando…');
  _cmpProgSetState(1, 'running', 'conectando…');
  _setCompareProgress(8, 'Conectando aos dois modelos…');

  const _tickInterval = setInterval(_cmpProgUpdate, 500);

  // intercepta deltas para contar tokens em tempo real
  window._cmpProgStateRef = _progState;
  const _patchedApply = function(msg) {
    const idx = Number(msg?.provider_index);
    if (msg?.event === 'delta') {
      if (idx === 0) _progState.tokA++;
      else if (idx === 1) _progState.tokB++;
      // atualiza detalhe com velocidade approx a cada 20 tokens
      if ((idx === 0 && _progState.tokA % 20 === 0) || (idx === 1 && _progState.tokB % 20 === 0)) {
        const secs = Math.max(1, (Date.now() - _progState.startMs) / 1000);
        const tok = idx === 0 ? _progState.tokA : _progState.tokB;
        const tps = (tok / secs).toFixed(1);
        _cmpProgSetState(idx, 'running', `${tok} tokens • ${tps} tok/s`);
      }
    } else if (msg?.event === 'provider_start') {
      _cmpProgSetState(idx, 'running', 'gerando…');
      _compareProgressPush(`Provider ${idx === 0 ? 'A' : 'B'} começou a gerar`);
    } else if (msg?.event === 'provider_done') {
      const secs = Math.max(1, (Date.now() - _progState.startMs) / 1000);
      const tok = idx === 0 ? _progState.tokA : _progState.tokB;
      _cmpProgSetState(idx, 'done', `${tok} tokens em ${secs.toFixed(1)}s`);
      _compareProgressPush(`Provider ${idx === 0 ? 'A' : 'B'} concluído`, 'good');
    } else if (msg?.event === 'error') {
      _cmpProgSetState(idx, 'error', msg?.error || 'erro');
      _compareProgressPush(`Provider ${idx === 0 ? 'A' : 'B'} falhou: ${msg?.error || 'erro'}`, 'bad');
    }
  };
  // monkey-patch temporário
  window._cmpApplyPatch = _patchedApply;

  try {
    await doCompareStream(payload);
    _setCompareProgress(100, 'Comparação finalizada', 'good');
    toast('Comparação finalizada');
  } catch (streamErr) {
    try {
      _cmpProgSetState(0, 'running', 'modo não-stream…');
      _cmpProgSetState(1, 'running', 'modo não-stream…');
      _setCompareProgress(55, 'Stream instável. Tentando modo não-stream…');
      await doCompareNonStream(payload);
      _setCompareProgress(100, 'Comparação finalizada via modo não-stream', 'good');
      toast('Concluído via não-stream');
    } catch (e) {
      _cmpProgSetState(0, 'error', 'falhou');
      _cmpProgSetState(1, 'error', 'falhou');
      _setCompareProgress(100, (e && e.message) || (streamErr && streamErr.message) || 'Falha na comparação', 'bad');
      toast((e && e.message) || (streamErr && streamErr.message) || 'Falha na comparação', 'bad');
    }
  } finally {
    clearInterval(_tickInterval);
    _cmpProgUpdate();
    window._cmpApplyPatch = null;
    qs('btnCompare').disabled = false;
    qs('btnCompare').textContent = 'Iniciar comparação';
  }
}

function clearCompare() {
  qs('cmpOutA').textContent = '';
  qs('cmpOutB').textContent = '';
  qs('cmpStatusA').textContent = 'status: -';
  qs('cmpStatusB').textContent = 'status: -';
}

function useCmpVersion(idx) {
  const text = (idx === 0 ? qs('cmpOutA') : qs('cmpOutB'))?.textContent?.trim();
  if (!text) return toast('Versão vazia', 'bad');
  criacaoState.compareText = text;
  
  const parsed = parseCompareText(text);
  criacaoState.compareTitles = parsed.titles;
  criacaoState.compareDescription = parsed.description;
  criacaoState.compareTags = parsed.tags;
  criacaoState.compareFirst10sHook = parsed.first10sHook;
  
  toast('Versão selecionada — vá para Criação para aplicar', 'good');
  location.hash = '#criacao';
  if (criacaoState.runId) renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function parseCompareText(text) {
  const result = {
    titles: [],
    description: '',
    tags: [],
    first10sHook: '',
  };
  
  if (!text) return result;
  
  const lines = text.split('\n');
  let currentSection = '';
  let descriptionLines = [];
  let inTags = false;
  let inTitles = false;
  
  for (const line of lines) {
    const trimmed = line.trim();
    const lowerLine = trimmed.toLowerCase();
    
    if (lowerLine.includes('título') || lowerLine.includes('title') || /^\*\*título/i.test(trimmed) || /^#{1,3}\s*título/i.test(trimmed)) {
      inTitles = true;
      inTags = false;
      currentSection = 'titles';
      continue;
    }
    
    if (lowerLine.includes('descrição') || lowerLine.includes('description') || /^#{1,3}\s*descri/i.test(trimmed)) {
      inTitles = false;
      inTags = false;
      currentSection = 'description';
      continue;
    }
    
    if (lowerLine.includes('tag') || /^#{1,3}\s*tag/i.test(trimmed) || lowerLine.includes('hashtag')) {
      inTitles = false;
      inTags = true;
      currentSection = 'tags';
      continue;
    }
    
    if (lowerLine.includes('hook') || lowerLine.includes('primeiros 10') || lowerLine.includes('10 segundos')) {
      inTitles = false;
      inTags = false;
      currentSection = 'hook';
      continue;
    }
    
    if (trimmed.startsWith('#') || trimmed === '') {
      if (currentSection === 'description' && descriptionLines.length > 0) {
        result.description = descriptionLines.join(' ').trim();
        descriptionLines = [];
      }
      inTitles = false;
      inTags = false;
      currentSection = '';
      continue;
    }
    
    let cleanLine = trimmed.replace(/^[-*•]\s*/, '').replace(/\*\*/g, '').trim();
    if (!cleanLine) continue;
    
    if (currentSection === 'titles' && (trimmed.match(/^[A-Z]:\s/i) || trimmed.match(/^[-*]\s/i) || trimmed.match(/^\d+[\.\)]\s/i))) {
      if (cleanLine.match(/^[A-Z]:\s/i)) {
        cleanLine = cleanLine.replace(/^[A-Z]:\s*/i, '');
      }
      cleanLine = cleanLine.replace(/^[-*•]\s*/, '').replace(/^\d+[\.\)]\s*/, '').trim();
      if (cleanLine && cleanLine.length > 5) {
        result.titles.push(cleanLine);
      }
    } else if (currentSection === 'description') {
      if (trimmed.match(/^\d+[\.,]\s/) || !trimmed.match(/^[A-Z]{2,}/)) {
        cleanLine = trimmed.replace(/^[-*•]\s*/, '').trim();
      }
      if (cleanLine && !cleanLine.match(/^\d+$/) && cleanLine.length > 3) {
        descriptionLines.push(cleanLine);
      }
    } else if (currentSection === 'tags') {
      const tagLine = trimmed.replace(/^[-*#\s]+/, '').trim();
      const tags = tagLine.split(/[,\s]+/).filter(t => t.length > 1 && !t.match(/^\d+$/));
      result.tags.push(...tags);
    } else if (currentSection === 'hook') {
      if (!result.first10sHook && cleanLine.length > 5) {
        result.first10sHook = cleanLine;
      }
    }
  }
  
  if (descriptionLines.length > 0) {
    result.description = descriptionLines.join(' ').trim();
  }
  
  result.tags = [...new Set(result.tags)].slice(0, 50);
  
  return result;
}

function _cleanFilename(fname) {
  // Strip "local:" prefix if present, then take last path segment
  let s = (fname || '').replace(/^local:/, '');
  const lastSeg = s.split('/').pop() || s;
  // Strip UUID prefix: {uuid4}-rest
  s = lastSeg.replace(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-/i, '');
  // Strip any leading code up to first _-_ (e.g. "0406_-_" or "0414_03_-_")
  s = s.replace(/^.*?_-(?=_)/, '');
  return s || lastSeg;
}

// RUNS
function _updateDeletionActionButtons() {
  const runId = String(state.selectedRunId || '').trim();
  const criacaoRunId = String(state.selectedCriacaoRunId || criacaoState.runId || '').trim();
  const runBtn = qs('btnRunDeleteSelected');
  if (runBtn) {
    runBtn.disabled = !runId;
    runBtn.title = runId ? `Excluir run ${runId}` : 'Selecione um run primeiro';
  }
  const clearBtn = qs('btnCriacaoClearSelected');
  if (clearBtn) {
    clearBtn.disabled = !criacaoRunId;
    clearBtn.title = criacaoRunId ? `Limpar criação ${criacaoRunId}` : 'Selecione um run primeiro';
  }
  const deleteBtn = qs('btnCriacaoDeleteSelected');
  if (deleteBtn) {
    deleteBtn.disabled = !criacaoRunId;
    deleteBtn.title = criacaoRunId ? `Excluir tudo ${criacaoRunId}` : 'Selecione um run primeiro';
  }
}

function deleteSelectedRun() {
  const id = String(state.selectedRunId || state.lastRunDetail?.id || '').trim();
  if (!id) return toast('Selecione um run primeiro', 'bad');
  deleteRun(id);
}

function clearSelectedCriacaoRun() {
  const id = String(state.selectedCriacaoRunId || criacaoState.runId || '').trim();
  if (!id) return toast('Selecione um run na Criação primeiro', 'bad');
  clearCriacaoRun(id);
}

function deleteSelectedCriacaoRun() {
  const id = String(state.selectedCriacaoRunId || criacaoState.runId || '').trim();
  if (!id) return toast('Selecione um run na Criação primeiro', 'bad');
  deleteRun(id);
}

async function reloadRuns() {
  try {
    const limit = parseInt(qs('runsLimit').value || '50', 10);
    const r = await apiFetch(`/runs?limit=${limit}`);
    const list = qs('runsList');
    list.innerHTML = '';

    (r.runs || []).forEach(item => {
      const row = document.createElement('div');
      row.className = 'run-item';
      row.dataset.id = item.id;

      const snippet = item.transcript_snippet || item.source || '';
      const dateStr = fmtDate(item.created_at);
      const rawFilename = item.original_filename || _cleanFilename(item.video_object_key || '');
      const displayName = rawFilename || ((item.id || '').slice(0, 20) + '…');
      row.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
          <div class="run-item-id" title="${esc(item.id || '')}">${esc(displayName)}</div>
          <button class="btn" style="font-size:10px;padding:2px 7px;color:var(--bad);border-color:rgba(255,68,85,.45);" onclick="event.stopPropagation();deleteRun('${escAttr(item.id || '')}')">Excluir</button>
        </div>
        <div class="run-item-date">${dateStr}</div>
        ${snippet ? `<div class="run-item-snippet">${esc(snippet)}</div>` : ''}
        <div class="run-item-status ${item.error ? 'err' : 'ok'}">${item.error ? '✕ Erro' : '✓ OK'}</div>
      `;
      row.onclick = () => loadRunDetail(item.id, row);
      list.appendChild(row);
    });
    _updateDeletionActionButtons();
  } catch (e) {
    toast(e.message, 'bad');
  }
}

function _clearRunLocalState(runId) {
  const id = String(runId || '').trim();
  if (!id) return;
  try { sessionStorage.removeItem(_wizardSessionKey(id)); } catch (_) {}
  try { state.runFramesCache?.delete(id); } catch (_) {}
  if (state.lastRunDetail && String(state.lastRunDetail.id || '') === id) {
    state.lastRunDetail = null;
    state.selectedRunId = null;
    const detail = qs('runsDetail');
    if (detail) detail.innerHTML = '<div class="run-detail-empty">Selecione um run na lista para ver detalhes</div>';
  }
  if (String(criacaoState.runId || '') === id) {
    state.selectedCriacaoRunId = null;
    criacaoState.runId = null;
    criacaoState.frames = [];
    criacaoState.postResult = null;
    criacaoState.activeBurnJobId = null;
    _revokeLogoPreviewHqUrl();
    const detail = qs('criacaoDetail');
    if (detail) detail.innerHTML = '<div class="criacao-empty">Selecione um run na lista para gerar o post</div>';
  }
  _updateDeletionActionButtons();
}

async function deleteRun(runId) {
  const id = String(runId || '').trim();
  if (!id) return toast('Run inválido', 'bad');
  if (!confirm('Excluir este run e os arquivos vinculados só a ele? Esta ação não pode ser desfeita.')) return;
  try {
    const res = await apiFetch(`/runs/${encodeURIComponent(id)}?delete_media=true`, { method: 'DELETE' });
    _clearRunLocalState(id);
    await Promise.allSettled([reloadRuns(), loadCriacaoRuns()]);
    const deletedCount = (res.deleted_media || []).length;
    const skippedCount = (res.skipped_media || []).length;
    toast(`Run excluído. Mídias apagadas: ${deletedCount}${skippedCount ? ` · preservadas por uso em outro run: ${skippedCount}` : ''}`, 'good');
  } catch (e) {
    toast('Erro ao excluir run: ' + e.message, 'bad');
  }
}

async function clearCriacaoRun(runId) {
  const id = String(runId || criacaoState.runId || '').trim();
  if (!id) return toast('Nenhum run selecionado', 'bad');
  if (!confirm('Limpar a criação deste run? Isso remove vídeos derivados, fila/post agendado e estado do wizard, mantendo o run original.')) return;
  try {
    const res = await apiFetch(`/runs/${encodeURIComponent(id)}/creation`, { method: 'DELETE' });
    _clearRunLocalState(id);
    await loadCriacaoRuns();
    const deletedCount = (res.deleted_media || []).length;
    toast(`Criação limpa. Mídias apagadas: ${deletedCount}`, 'good');
  } catch (e) {
    toast('Erro ao limpar criação: ' + e.message, 'bad');
  }
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escAttr(s) {
  return esc(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Converte ISO UTC para horário local do browser (pt-BR)
function fmtDate(iso) {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('pt-BR', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  } catch { return iso.replace('T', ' ').slice(0, 16); }
}

function openFrame(i) {
  const frames = window._detailFrames;
  if (!frames || !frames[i]) return;
  const b64 = frames[i];
  try {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let j = 0; j < binary.length; j++) bytes[j] = binary.charCodeAt(j);
    const blob = new Blob([bytes], { type: 'image/jpeg' });
    const url = URL.createObjectURL(blob);
    const w = window.open(url, '_blank');
    if (w) setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (e) {
    const w = window.open('', '_blank');
    if (w) w.document.write(`<html><body style="margin:0;background:#000"><img src="data:image/jpeg;base64,${b64}" style="max-width:100%;max-height:100vh;object-fit:contain"></body></html>`);
  }
}

async function loadRunDetail(id, rowEl) {
  // mark active
  document.querySelectorAll('.run-item').forEach(el => el.classList.remove('active'));
  if (rowEl) rowEl.classList.add('active');
  state.selectedRunId = String(id || '').trim();
  _updateDeletionActionButtons();

  const reqId = (state.runDetailRequestId || 0) + 1;
  state.runDetailRequestId = reqId;
  if (state.runDetailAbort) {
    try { state.runDetailAbort.abort(); } catch (_) {}
  }
  const ac = new AbortController();
  state.runDetailAbort = ac;

  try {
    const r = await apiFetch(`/runs/${id}/light`, { signal: ac.signal });
    if (reqId !== state.runDetailRequestId) return;
    state.lastRunDetail = r;
    state.runDetailFramesLoadingFor = id;
    renderRunDetail(r);
    _loadRunFramesForDetail(id, reqId);
  } catch (e) {
    if (e?.name === 'AbortError' || /aborted|aborterror/i.test(String(e?.message || ''))) return;
    toast(e.message, 'bad');
  }
}

function _parseRunResult(runLike) {
  if (!runLike || typeof runLike !== 'object') return {};
  const raw = runLike.result_json;
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch { return {}; }
  }
  if (raw && typeof raw === 'object') return raw;
  return runLike;
}

function _parseRunRequest(runLike) {
  if (!runLike || typeof runLike !== 'object') return {};
  const raw = runLike.request_json;
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch { return {}; }
  }
  if (raw && typeof raw === 'object') return raw;
  return {};
}

function _mergeRunFrames(runLike, frames = []) {
  const result = _parseRunResult(runLike);
  const vision = result.vision || {};
  vision.frames = Array.isArray(frames) ? frames : [];
  vision.frames_count = vision.frames.length;
  result.vision = vision;
  if (runLike && typeof runLike === 'object') runLike.result_json = result;
  return runLike;
}

async function _loadRunFramesForDetail(runId, reqId = state.runDetailRequestId) {
  try {
    let frames = state.runFramesCache.get(runId);
    if (!Array.isArray(frames)) {
      const rf = await apiFetch(`/runs/${runId}/frames`);
      frames = Array.isArray(rf?.frames) ? rf.frames : [];
      state.runFramesCache.set(runId, frames);
    }
    if (reqId !== state.runDetailRequestId) return;
    if (!state.lastRunDetail || String(state.lastRunDetail.id || '') !== String(runId)) return;
    _mergeRunFrames(state.lastRunDetail, frames);
    state.runDetailFramesLoadingFor = null;
    renderRunDetail(state.lastRunDetail);
  } catch (e) {
    if (reqId !== state.runDetailRequestId) return;
    state.runDetailFramesLoadingFor = null;
    renderRunDetail(state.lastRunDetail || {});
    toast(`Erro ao carregar screenshots: ${e.message}`, 'bad');
  }
}

function loadRunFramesNow() {
  const run = state.lastRunDetail || {};
  const runId = String(run.id || _parseRunResult(run).run_id || '').trim();
  if (!runId) return;
  state.runDetailFramesLoadingFor = runId;
  renderRunDetail(run);
  _loadRunFramesForDetail(runId, state.runDetailRequestId);
}

function renderRunDetail(r) {
  const container = qs('runsDetail');
  const result = _parseRunResult(r);

  const vision   = result.vision   || {};
  const sources  = result.sources  || {};
  const suggested = result.suggested || {};
  const grok     = result.grok     || {};
  const storage  = result.storage  || {};

  const xvTop    = sources.xvideos_top    || {};
  const xvSearch = sources.xvideos_search || {};
  const searchQuery = sources.xvideos_search_query || '';

  const topVids    = xvTop.videos    || [];
  const searchVids = xvSearch.videos || [];
  const allVids    = [...topVids, ...searchVids];

  const frames  = Array.isArray(vision.frames) ? vision.frames : [];
  const framesCount = Math.max(frames.length, parseInt(vision.frames_count || '0', 10) || 0);
  const activeRunId = String(r?.id || result?.run_id || '').trim();
  const framesLoading = !!activeRunId && state.runDetailFramesLoadingFor === activeRunId;
  const tags    = suggested.tags || [];
  const prompt  = grok.markdown_prompt_ptbr_keep_original || '';
  const dateStr = fmtDate(result.created_at);

  // Vision analysis text
  let visText = '';
  let visDebug = '';
  if (vision.analysis) {
    if (typeof vision.analysis === 'string') {
      visText = vision.analysis;
    } else if (vision.analysis.description) {
      visText = vision.analysis.description;
    } else {
      // API error, refusal, or unexpected format — show raw JSON for debugging
      visDebug = JSON.stringify(vision.analysis, null, 2);
    }
  } else if (vision.debug && vision.debug.skipped_reason) {
    visDebug = 'Vision não executada: ' + vision.debug.skipped_reason;
  }

  // Store frames globally for fullscreen open
  window._detailFrames = frames;

  container.innerHTML = `
    <div class="detail-section card">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
        <div>
          <div style="font-family:'Bebas Neue',sans-serif; font-size:16px; letter-spacing:1.5px; color:var(--muted);">${esc(result.run_id || '')}</div>
          <div class="hint">${esc(dateStr)}</div>
        </div>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          <button class="btn" onclick="copyDetailPrompt()">Copiar prompt</button>
          <button class="btn primary" onclick="detailToCompare()">→ Compare</button>
          <button class="btn" style="color:var(--bad);border-color:rgba(255,68,85,.45);" onclick="deleteRun('${escAttr(activeRunId)}')">Excluir run</button>
        </div>
      </div>
    </div>

    ${frames.length > 0 ? `
    <div class="detail-section card">
      <h2>Vision IA — ${frames.length} frames</h2>
      <div class="frames-grid">
        ${frames.map((f, fi) => `<img src="data:image/jpeg;base64,${f}" alt="frame ${fi+1}" class="clickable-frame" loading="lazy" onclick="openFrame(${fi})">`).join('')}
      </div>
      ${visText ? `<div style="font-size:13px; color:var(--text); line-height:1.65; white-space:pre-wrap; border-top:1px solid var(--line); padding-top:12px; margin-top:12px;">${esc(visText)}</div>` : ''}
      ${visDebug ? `<pre style="font-size:11px; color:var(--muted); background:var(--bg2); border-radius:7px; padding:10px; margin-top:12px; overflow:auto; max-height:180px;">${esc(visDebug)}</pre>` : ''}
    </div>` : (framesCount > 0 ? `
    <div class="detail-section card">
      <h2>Vision IA — ${framesCount} frames</h2>
      <div class="hint">${framesLoading ? 'Carregando screenshots…' : 'Screenshots ainda não carregados para acelerar a troca de runs.'}</div>
      <div class="row" style="margin-top:8px;">
        <button class="btn" onclick="loadRunFramesNow()" ${framesLoading ? 'disabled' : ''}>${framesLoading ? '⏳ Carregando…' : 'Carregar screenshots agora'}</button>
      </div>
      ${visText ? `<div style="font-size:13px; color:var(--text); line-height:1.65; white-space:pre-wrap; border-top:1px solid var(--line); padding-top:12px; margin-top:12px;">${esc(visText)}</div>` : ''}
      ${visDebug ? `<pre style="font-size:11px; color:var(--muted); background:var(--bg2); border-radius:7px; padding:10px; margin-top:12px; overflow:auto; max-height:180px;">${esc(visDebug)}</pre>` : ''}
    </div>` : `
    <div class="detail-section card">
      <h2>Vision IA</h2>
      <div class="hint">${visDebug ? esc(visDebug) : 'Nenhum frame extraído neste run.'}</div>
    </div>`)}

    ${tags.length > 0 ? `
    <div class="detail-section card">
      <h2>Tags sugeridas (${tags.length})</h2>
      <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:6px;">
        ${tags.map(t => `<span class="tag-chip">${esc(t)}</span>`).join('')}
      </div>
    </div>` : ''}

    ${allVids.length === 0 ? `
    <div class="detail-section card" id="refsCard">
      <div class="refs-actions">
        <h2>Referências XVideos</h2>
        <button class="btn primary" id="btnFetchRefs" onclick="fetchRunRefs('${result.run_id || ''}')">🔍 Buscar Referências Agora</button>
      </div>
      <div class="hint" id="fetchRefsStatus">Nenhuma referência encontrada neste run — clique para buscar no XVideos.</div>
      <div id="refsGridTop" style="margin-top:10px;"></div>
      <div id="refsGridSearch" style="margin-top:10px;"></div>
    </div>` : `
    <div class="detail-section card" id="refsCard">
      <div class="refs-actions">
        <h2>Referências (${allVids.length})</h2>
        <button class="btn" onclick="toggleAllRefs(true)">Selecionar todas</button>
        <button class="btn" onclick="toggleAllRefs(false)">Desmarcar todas</button>
        <button class="btn primary" onclick="repromptSelected()">↺ Recalcular prompt</button>
      </div>

      ${topVids.length > 0 ? `
        <div class="hint" style="margin-bottom:8px;">Top por views (${topVids.length})</div>
        <div class="refs-grid" id="refsGridTop">
          ${topVids.map(v => renderRefCard(v)).join('')}
        </div>` : ''}

      ${searchVids.length > 0 ? `
        <div class="hint" style="margin:14px 0 8px; border-top:1px solid var(--line); padding-top:12px;">
          Busca temática: <code style="color:var(--text); font-size:11px;">${esc(searchQuery)}</code> (${searchVids.length})
        </div>
        <div class="refs-grid" id="refsGridSearch">
          ${searchVids.map(v => renderRefCard(v)).join('')}
        </div>` : ''}
    </div>`}

    <div class="detail-section card">
      <details>
        <summary style="cursor:pointer; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:1px; color:var(--muted); user-select:none;">
          Prompt completo — clique para expandir
        </summary>
        <pre class="output" id="detailPromptPre" style="margin-top:12px; max-height:420px;">${esc(prompt)}</pre>
      </details>
    </div>

    <div class="detail-section card">
      <h2>Re-analisar</h2>
      <div class="hint" style="margin-bottom:10px;">Abre a aba Analyze preenchida com os dados deste run.</div>
      <button class="btn" onclick="prefillAnalyzeFromRun()">Preencher Analyze com este run</button>
    </div>
  `;
}

function thumbToPreview(thumb) {
  // Derive XVideos preview MP4 URL from thumbnail URL
  // thumb:   .../thumbs169ll/XX/XX/XX/ID/1.jpg
  // preview: .../videopreview/XX/XX/XX/ID_169.mp4
  if (!thumb) return '';
  const p = thumb
    .replace(/\/thumbs[^/]+\//, '/videopreview/')
    .replace(/\/\d+\.\w{2,4}$/, '_169.mp4');
  return p !== thumb ? p : '';
}

function loadRefVideoEl(el) {
  const preview = el.dataset.preview;
  const thumb   = el.dataset.thumb;
  const link    = el.dataset.link;
  if (!preview) {
    // No preview — open in new tab
    if (link) window.open(link, '_blank');
    return;
  }
  el.onclick = null; // prevent double trigger
  el.style.cursor = 'default';

  const video = document.createElement('video');
  video.src = preview;
  if (thumb) video.poster = thumb;
  video.controls = true;
  video.autoplay  = true;
  video.muted     = true;
  video.loop      = false;
  video.style.cssText = 'width:100%;display:block;border-radius:6px;aspect-ratio:16/9;object-fit:cover;background:#000;';

  video.onerror = () => {
    // Preview failed (CORS / not available) — show fallback with link
    el.innerHTML = `
      <div style="position:relative;">
        <img src="${thumb}" style="width:100%;display:block;border-radius:6px;aspect-ratio:16/9;object-fit:cover;">
        <a href="${link}" target="_blank"
           style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
                  background:rgba(0,0,0,.55);border-radius:6px;color:#fff;font-size:13px;font-weight:600;gap:6px;">
          ▶ Ver no XVideos
        </a>
      </div>`;
  };

  el.innerHTML = '';
  el.appendChild(video);
}

function renderRefCard(v) {
  const tags5    = (v.tags || []).slice(0, 5).join(', ');
  const thumb    = v.thumb || '';
  const videoUrl = v.url || '#';
  const preview  = thumbToPreview(thumb);

  const mediaHtml = thumb ? `
    <div class="ref-media"
         data-thumb="${esc(thumb)}"
         data-preview="${esc(preview)}"
         data-link="${esc(videoUrl)}"
         onclick="loadRefVideoEl(this)">
      <img src="${esc(thumb)}" alt="" class="ref-thumb" loading="lazy">
      <div class="ref-play-overlay">
        <span class="ref-play-btn">▶</span>
        ${preview ? '' : `<span style="font-size:10px;margin-top:2px;opacity:.8;">Abrir XVideos</span>`}
      </div>
    </div>` : '';

  return `
    <div class="ref-card" data-url="${esc(v.url || '')}" data-checked="true">
      <div class="ref-card-top">
        <label class="ref-checkbox-wrap" title="Incluir no prompt">
          <input type="checkbox" checked
            onchange="this.closest('.ref-card').dataset.checked = this.checked ? 'true' : 'false';
                      this.closest('.ref-card').classList.toggle('deselected', !this.checked);">
        </label>
        <a href="${esc(videoUrl)}" target="_blank" class="ref-ext-link" title="Abrir no XVideos">↗</a>
      </div>
      ${mediaHtml}
      <div class="ref-body">
        <a href="${esc(videoUrl)}" target="_blank" class="ref-title">${esc(v.title || '(sem título)')}</a>
        <div class="ref-meta">
          ${v.duration_raw ? `<span>⏱ ${esc(v.duration_raw)}</span>` : ''}
          ${v.views_raw    ? `<span>👁 ${esc(String(v.views_raw))}</span>` : ''}
          ${v.likes_raw    ? `<span>♥ ${esc(String(v.likes_raw))}</span>` : ''}
        </div>
        ${tags5 ? `<div class="ref-tags">${esc(tags5)}</div>` : ''}
      </div>
    </div>`;
}

function toggleAllRefs(checked) {
  document.querySelectorAll('#refsCard .ref-card').forEach(card => {
    card.dataset.checked = checked ? 'true' : 'false';
    card.classList.toggle('deselected', !checked);
    const cb = card.querySelector('input[type=checkbox]');
    if (cb) cb.checked = checked;
  });
}

async function fetchRunRefs(runId) {
  const btn = qs('btnFetchRefs');
  const st  = qs('fetchRefsStatus');
  if (!runId) return toast('run_id não disponível', 'bad');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Buscando…'; }
  if (st)  st.textContent = 'Buscando referências no XVideos… (pode levar 30s)';
  try {
    const res = await apiFetch(`/runs/${runId}/fetch-refs`, { method: 'POST' });
    if (res.error) throw new Error(res.detail || res.error);
    toast(`✓ ${res.top + res.search} referências encontradas`, 'good');
    // Recarregar o run para mostrar as referências
    await loadRunDetail(runId, null);
  } catch (e) {
    if (st)  st.textContent = 'Erro: ' + e.message;
    if (btn) { btn.disabled = false; btn.textContent = '🔍 Buscar Referências Agora'; }
    toast('Erro: ' + e.message, 'bad');
  }
}

async function repromptSelected() {
  const run = state.lastRunDetail;
  if (!run) return toast('Nenhum run carregado', 'bad');
  const result = _parseRunResult(run);
  const run_id = result.run_id || run.id;
  if (!run_id) return toast('run_id não encontrado', 'bad');

  const selectedUrls = [...document.querySelectorAll('#refsCard .ref-card[data-checked="true"]')]
    .map(el => el.dataset.url).filter(Boolean);

  if (!selectedUrls.length) return toast('Selecione pelo menos uma referência', 'bad');

  try {
    const res = await apiFetch(`/runs/${run_id}/reprompt`, {
      method: 'POST',
      body: JSON.stringify({ selected_urls: selectedUrls }),
    });
    if (res.error) return toast('Erro: ' + res.error, 'bad');

    // Update prompt pre
    const pre = document.getElementById('detailPromptPre');
    if (pre) pre.textContent = res.prompt || '';

    // Also update lastRunDetail so detailToCompare uses new prompt
    if (!state.lastRunDetail._reprompt) state.lastRunDetail._reprompt = {};
    state.lastRunDetail._reprompt.prompt = res.prompt;

    // open prompt section
    const details = pre?.closest('details');
    if (details) details.open = true;

    toast(`Prompt recalculado com ${res.selected_count} referências`, 'good');
  } catch (e) {
    toast(e.message, 'bad');
  }
}

function copyDetailPrompt() {
  const pre = document.getElementById('detailPromptPre');
  copyText(pre?.textContent || '');
}

function detailToCompare() {
  const run = state.lastRunDetail;
  if (!run) return toast('Nenhum run carregado', 'bad');
  // Use reprompted version if available
  const prompt = run._reprompt?.prompt
    || (() => {
      const result = _parseRunResult(run);
      return (result?.grok?.markdown_prompt_ptbr_keep_original || '').trim();
    })();
  if (!prompt) return toast('Run não tem prompt', 'bad');
  qs('cmpPrompt').value = prompt;
  location.hash = '#compare';
}

function prefillAnalyzeFromRun() {
  const run = state.lastRunDetail;
  if (!run) return toast('Nenhum run carregado', 'bad');
  let reqData = {};
  let result = {};
  try {
    reqData = _parseRunRequest(run);
  } catch {
    reqData = {};
  }
  try {
    result = _parseRunResult(run);
  } catch {
    result = {};
  }

  const inputs = result.inputs || {};
  const tr = reqData.transcript || {};
  const transcriptText = String(tr.text || inputs.transcript_snippet || '').trim();
  if (transcriptText) qs('anTranscript').value = transcriptText;

  state.transcriptSegments = Array.isArray(tr.segments) ? tr.segments : [];
  state.transcriptSrt = String(tr.srt || '').trim();
  qs('anSrt').textContent = state.transcriptSrt || '';

  const probe = ((reqData.video_metadata || {}).probe || {});
  if (probe.duration_seconds) qs('anDur').value = Number(probe.duration_seconds).toFixed(1);
  if (probe.width) qs('anW').value = probe.width;
  if (probe.height) qs('anH').value = probe.height;
  if (probe.fps) qs('anFps').value = probe.fps;

  const objectKey = String(reqData.video_object_key || '').trim();
  const videoUrl = String(reqData.video_url || '').trim();
  state.videoObjectKey = objectKey || null;
  state.videoUrl = videoUrl || null;
  qs('anObjectKey').textContent = state.videoObjectKey || '-';
  qs('anVideoUrl').textContent = state.videoUrl || '-';
  qs('anUploadStatus').textContent = state.videoObjectKey
    ? 'status: vídeo herdado do run selecionado'
    : 'status: run sem video_object_key (Vision será pulada)';

  location.hash = '#analyze';
  toast(state.videoObjectKey ? 'Analyze preenchido com vídeo e transcrição do run' : 'Analyze preenchido (sem vídeo para Vision)');
}

function toCompareFromAnalyze() {
  const prompt = (state.lastAnalyze?.grok?.markdown_prompt_ptbr_keep_original || '').trim();
  if (!prompt) return toast('Sem prompt disponível', 'bad');
  qs('cmpPrompt').value = prompt;
  location.hash = '#compare';
}

function toCompareFromRun() {
  detailToCompare();
}

// ── CRIAÇÃO ──────────────────────────────────────────────────────────────────
const CRIACAO_MAX_STEP = 5;
const WIZARD_SESSION_PREFIX = 'adult_meta_wizard_run:';
const DEFAULT_LOGO_PRESET = {
  id: 'saved',
  name: 'Padrão salvo',
  logo_x: 97,
  logo_y: 97,
  logo_scale_pct: 20,
  logo_opacity: 85,
};
const LOGO_PRESET_OPTIONS = [
  { id: 'saved', name: 'Padrão salvo' },
  { id: 'bottom_right', name: 'Canto inferior direito', logo_x: 97, logo_y: 97, logo_scale_pct: 20, logo_opacity: 85 },
  { id: 'top_right', name: 'Canto superior direito', logo_x: 97, logo_y: 3, logo_scale_pct: 20, logo_opacity: 85 },
  { id: 'center_soft', name: 'Centro discreto', logo_x: 50, logo_y: 50, logo_scale_pct: 24, logo_opacity: 55 },
  { id: 'bottom_center', name: 'Rodapé central', logo_x: 50, logo_y: 94, logo_scale_pct: 22, logo_opacity: 70 },
];
const BURN_LOGO_MAX_COUNT = 6;

let _savedLogoPreset = { ...DEFAULT_LOGO_PRESET };
let _logoProfiles = [];
let _logoProfilesUpdatedAt = null;
let _wizardPersistTimer = null;
let _logoPreviewRefreshTimer = null;
let _logoPreviewOverlayRaf = null;
let _burnCandidatesCache = { burn: [], teaser: [], thumb: [], original: [] };
let _thumbRenderBoxes = [];
let _thumbDragState = null;
const _thumbImgCache = new Map();

const criacaoState = {
  runId: null,
  frames: [],
  framesLoading: false,
  framesExpectedCount: 0,
  visionAnalysis: null,
  postResult: null,
  logoProfileId: '',
  logoProfileName: '',
  logoCompanyDraftName: '',
  logoB64: null,
  logoName: '',
  burnLogos: [],
  burnLogoActiveIdx: 0,
  burnLogoTargetCount: 1,
  videoUrl: null,
  hasTranscript: false,
  burnedVideoUrl: null,
  burnedFilename: null,
  burnedObjectKey: null,
  burnedWarning: null,
  showBurnQueue: false,
  burnedQuality: '26',
  burnedResolution: '1080',
  burnedPreset: 'ultrafast',
  selectedFrameIdx: null,
  thumbFrameIdx: null,
  thumbSubtitle: '',
  compareText: null,
  compareTitles: [],
  compareDescription: '',
  compareTags: [],
  compareFirst10sHook: '',
  _reqData: null,
  teaserUrl: null,
  teaserObjectKey: null,
  teaserLogoUrl: null,
  teaserLogoObjectKey: null,
  teaserLogoFilename: null,
  teaserCombinedUrl: null,
  teaserCombinedObjectKey: null,
  teaserSourceType: 'burned',
  teaserSourceObjectKey: null,
  teaserConcatMode: 'start',
  teaserSelectedFrames: [],
  teaserSceneDurationsByFrame: {},
  teaserQuality: '26',
  teaserClipDuration: '6',
  teaserNumClips: '8',
  teaserAutoDistribute: false,
  teaserTargetDurationMin: '11',
  teaserFirstClipMin: '1',
  teaserLastClipMin: '1',
  teaserForceLogoOverlay: false,
  teaserLogos: [],
  teaserLogoActiveIdx: 0,
  teaserLogoAutoSeeded: false,
  teaserNarrationEnabled: false,
  teaserOriginalAudioVolume: 100,
  teaserNarrationVolume: 120,
  teaserNarrationOffsetSec: 0,
  teaserNarrationObjectKey: null,
  teaserNarrationAudioUrl: null,
  teaserNarrationUsed: false,
  teaserOpenerObjectKey: null,
  teaserOpenerUrl: null,
  teaserOpenerPosition: 'start',
  logoX: 97,
  logoY: 97,
  logoScalePct: 20,
  logoOpacity: 85,
  logoPresetChoice: 'saved',
  logoProfileLayoutLinked: true,
  thumbSourceB64: null,
  thumbSourceFrameIdx: null,
  thumbSourceInfo: '',
  thumbVideoObjectKey: null,
  thumbExportFormat: 'png',
  thumbJpegQuality: 98,
  thumbOutputScale: 2,
  thumbCropX: 50,
  thumbCropY: 50,
  thumbZoom: 1,
  thumbBrightness: 100,
  thumbContrast: 100,
  thumbSaturation: 100,
  thumbHue: 0,
  thumbAutoHqTried: false,
  thumbElements: [],
  thumbSelectedElementId: null,
  transcriptDraft: '',
  transcribeSourceLang: 'pt',
  transcribeTargetLang: '',
  transcribeAdultMode: true,
  transcribeIncludeVocalizations: true,
  activeBurnJobId: null,
  burnSkipSubtitles: false,
  burnFontSize: 22,
  burnFontColor: 'white',
  burnSubDelay: 0,
  step: 1,
  logoPreviewHqFrame: null,
  logoPreviewHqUrl: '',
  logoPreviewHqInfo: '',
  logoPreviewHqLoading: false,
  logoPreviewComposited: false,
  logoPreviewBgVisible: true,
  logoPreviewHqWidth: 0,
  logoPreviewHqHeight: 0,
};

function _wizardSessionKey(runId) {
  return `${WIZARD_SESSION_PREFIX}${runId || ''}`;
}

function _toNum(value, fallback, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return _clamp(n, min, max);
}

function _parseIntWithDefault(value, fallback) {
  if (value == null) return fallback;
  const raw = String(value).trim();
  if (!raw) return fallback;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? n : fallback;
}

function _normalizeObjectKeyish(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (/^(data:|blob:)/i.test(raw)) return '';
  if (/^local:[a-z0-9][a-z0-9._/\-]{0,1023}$/i.test(raw)) return raw;

  const fromPath = (pathname) => {
    const parts = String(pathname || '').split('/').map(p => p.trim()).filter(Boolean);
    if (!parts.length) return '';
    if (parts[0] === 'metaporn' && parts.length >= 2) return decodeURIComponent(parts.slice(1).join('/'));
    if (/^(uploads|burns|teasers|previews|combined|narrations-manual|teasers-openers)\b/i.test(parts[0])) return decodeURIComponent(parts.join('/'));
    if (parts.length >= 2 && /^(uploads|burns|teasers|previews|combined|narrations-manual|teasers-openers)\b/i.test(parts[1])) {
      return decodeURIComponent(parts.slice(1).join('/'));
    }
    return '';
  };

  if (/^https?:\/\//i.test(raw)) {
    try {
      const url = new URL(raw);
      const ref = decodeURIComponent(url.searchParams.get('ref') || '').trim();
      if (/^local:[a-z0-9][a-z0-9._/\-]{0,1023}$/i.test(ref)) return ref;
      return fromPath(url.pathname);
    } catch (_) {
      return '';
    }
  }

  if (raw.startsWith('/')) {
    try {
      const url = new URL(raw, location.origin);
      const ref = decodeURIComponent(url.searchParams.get('ref') || '').trim();
      if (/^local:[a-z0-9][a-z0-9._/\-]{0,1023}$/i.test(ref)) return ref;
      return fromPath(url.pathname);
    } catch (_) {
      return fromPath(raw);
    }
  }

  if (/^s3:\/\//i.test(raw)) {
    const s3Path = raw.replace(/^s3:\/\//i, '');
    const slash = s3Path.indexOf('/');
    return slash >= 0 ? s3Path.slice(slash + 1) : '';
  }

  return raw.replace(/^\/+/, '');
}

function _currentPreviewVideoSize() {
  const hqWidth = parseInt(criacaoState.logoPreviewHqWidth || '0', 10) || 0;
  const hqHeight = parseInt(criacaoState.logoPreviewHqHeight || '0', 10) || 0;
  if (hqWidth > 0 && hqHeight > 0) return { width: hqWidth, height: hqHeight };

  const hqInfo = String(criacaoState.logoPreviewHqInfo || '');
  const hqMatch = hqInfo.match(/(\d+)\D+(\d+)/);
  if (hqMatch) {
    const width = parseInt(hqMatch[1] || '0', 10) || 0;
    const height = parseInt(hqMatch[2] || '0', 10) || 0;
    if (width > 0 && height > 0) return { width, height };
  }

  const probe = (((criacaoState._reqData || {}).video_metadata || {}).probe || {});
  const probeWidth = parseInt(probe.width || '0', 10) || 0;
  const probeHeight = parseInt(probe.height || '0', 10) || 0;
  if (probeWidth > 0 && probeHeight > 0) return { width: probeWidth, height: probeHeight };

  return null;
}

function _previewWrapStyle() {
  const size = _currentPreviewVideoSize();
  if (!size) return '';
  return `aspect-ratio:${size.width} / ${size.height};`;
}

function _selectedBurnMaxHeight() {
  return Math.max(0, _parseIntWithDefault(qs('burnResolution')?.value ?? criacaoState.burnedResolution ?? '1080', 1080));
}

function _burnResultVideoStyle(maxHeightPx = 340) {
  const ratioStyle = _previewWrapStyle() || 'aspect-ratio:16 / 9;';
  return `width:100%;${ratioStyle}max-height:${maxHeightPx}px;border-radius:8px;background:#000;display:block;object-fit:contain;`;
}

function _framePreviewSrc(src) {
  const raw = String(src || '').trim();
  if (!raw) return '';
  if (/^(data:|blob:|https?:)/i.test(raw)) return raw;
  return `data:image/jpeg;base64,${raw}`;
}

function _revokeObjectUrl(url) {
  const raw = String(url || '').trim();
  if (!raw.startsWith('blob:')) return;
  try { URL.revokeObjectURL(raw); } catch (_) {}
}

function _revokeLogoPreviewHqUrl() {
  _revokeObjectUrl(criacaoState.logoPreviewHqUrl);
  criacaoState.logoPreviewHqUrl = '';
}

function _syncLogoPreviewDom() {
  const wrap = qs('logoPreviewWrap');
  const bg = qs('logoPreviewBg');
  const overlay = qs('logoPreviewOverlay');
  const btn = qs('btnLoadHqLogoPreview');
  const info = qs('logoPreviewHqInfo');
  const size = _currentPreviewVideoSize();

  if (wrap) {
    if (size?.width > 0 && size?.height > 0) {
      wrap.style.aspectRatio = `${size.width} / ${size.height}`;
    } else {
      wrap.style.removeProperty('aspect-ratio');
    }
  }

  if (bg) {
    const frameIdx = _currentThumbFrameIdx();
    const fallbackFrame = criacaoState.frames[frameIdx] || '';
    const nextSrc = _framePreviewSrc(criacaoState.logoPreviewHqUrl || fallbackFrame);
    if (nextSrc) bg.src = nextSrc;
    bg.classList.toggle('hidden', !criacaoState.logoPreviewBgVisible);
  }

  const overlays = wrap ? Array.from(wrap.querySelectorAll('.burn-logo-preview-overlay')) : [];
  if (overlays.length) {
    const logos = _burnLogoList();
    const activeIdx = _burnActiveLogoIndex();
    overlays.forEach((ov) => {
      const idx = parseInt(ov.dataset.logoIndex || '-1', 10);
      const item = logos[idx];
      ov.classList.toggle('composited-proxy', !!criacaoState.logoPreviewComposited);
      ov.classList.toggle('active', idx === activeIdx);
      if (item?.src && ov.getAttribute('src') !== item.src) ov.setAttribute('src', item.src);
    });
  } else if (overlay) {
    overlay.classList.toggle('composited-proxy', !!criacaoState.logoPreviewComposited);
    if (criacaoState.logoB64 && overlay.getAttribute('src') !== criacaoState.logoB64) {
      overlay.setAttribute('src', criacaoState.logoB64);
    }
  }

  if (btn) {
    btn.textContent = criacaoState.logoPreviewHqLoading ? '⏳' : (criacaoState.logoPreviewHqUrl ? '✓ HQ' : '📷 HQ');
  }

  if (info) {
    const frameIdx = _currentThumbFrameIdx();
    const hasFallbackFrame = !!(criacaoState.frames[frameIdx] || '');
    info.textContent = criacaoState.logoPreviewHqUrl
      ? (criacaoState.logoPreviewHqInfo || 'HQ')
      : (hasFallbackFrame ? 'baixa res — HQ atualiza sozinho' : '');
  }

  _updateLogoPreviewOverlay();
}

function _invalidateLogoPreviewComposited() {
  const hadCompositedPreview = !!criacaoState.logoPreviewComposited;
  criacaoState.logoPreviewComposited = false;
  // If the last HQ preview already had the logo baked in, drop it immediately
  // before drawing the draggable overlay again. Otherwise the user sees two logos
  // until the fresh HQ request finishes.
  if (hadCompositedPreview) {
    _revokeLogoPreviewHqUrl();
    criacaoState.logoPreviewHqFrame = null;
    criacaoState.logoPreviewHqUrl = '';
    criacaoState.logoPreviewHqInfo = '';
  }
  _syncLogoPreviewDom();
}

function _beginLogoLiveEdit() {
  if (!criacaoState.logoPreviewComposited) return;
  _invalidateLogoPreviewComposited();
}

function _scheduleLogoPreviewHqRefresh() {
  if (_logoPreviewRefreshTimer) clearTimeout(_logoPreviewRefreshTimer);
  if (criacaoState.step !== 1) return;
  if (!criacaoState.runId) return;
  if (!criacaoState.logoPreviewHqUrl && !(criacaoState.frames || []).length) return;
  _logoPreviewRefreshTimer = setTimeout(() => {
    _logoPreviewRefreshTimer = null;
    loadLogoPreviewHqFrame({ silent: true });
  }, 350);
}

function _ensureLogoPreviewHq(force = false) {
  if (criacaoState.step !== 1) return;
  if (!criacaoState.runId) return;
  if (criacaoState.logoPreviewHqLoading) return;
  if (!force && criacaoState.logoPreviewHqUrl) return;
  loadLogoPreviewHqFrame({ silent: true });
}

function _blobUrlFromBase64(b64, mime = 'image/jpeg') {
  const binary = atob(String(b64 || ''));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: mime }));
}

function _preloadImageSrc(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(src);
    img.onerror = () => reject(new Error('Falha ao carregar imagem HQ'));
    img.src = src;
  });
}

function _resolveOriginalVideoObjectKey() {
  const req = (criacaoState && criacaoState._reqData && typeof criacaoState._reqData === 'object')
    ? criacaoState._reqData
    : {};
  const candidates = [
    req.video_object_key,
    req.original_video_object_key,
    req.raw_video_object_key,
    req.object_key,
    req?.storage?.object_key,
    req?.video?.object_key,
    req?.upload?.object_key,
    req?.source?.object_key,
    req.video_url,
  ];
  for (const c of candidates) {
    const key = _normalizeObjectKeyish(c);
    if (key) return key;
  }
  return '';
}

function _teaserLogoDefaults() {
  return {
    x: _toNum(criacaoState.logoX, 97, 0, 100),
    y: _toNum(criacaoState.logoY, 97, 0, 100),
    scale_pct: _toNum(criacaoState.logoScalePct, 20, 5, 100),
    opacity: _toNum(criacaoState.logoOpacity, 85, 5, 100),
    remove_bg: false,
    bg_key_color: '#ffffff',
    bg_similarity: 0.18,
    bg_blend: 0.08,
  };
}

function _teaserNormalizeLogo(raw) {
  const src = raw && typeof raw === 'object' ? raw : {};
  const d = _teaserLogoDefaults();
  const name = String(src.name || 'logo').trim() || 'logo';
  const logoSrc = String(src.src || src.b64 || src.logo_b64 || '').trim();
  const mime = String(src.mime || '').trim().toLowerCase();
  const isGif = mime === 'image/gif' || /\.gif$/i.test(name) || /^data:image\/gif/i.test(logoSrc);
  return {
    id: String(src.id || `logo_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`),
    name,
    src: logoSrc,
    mime: mime || (isGif ? 'image/gif' : ''),
    isGif: !!isGif,
    x: _toNum(src.x, d.x, 0, 100),
    y: _toNum(src.y, d.y, 0, 100),
    scale_pct: _toNum(src.scale_pct, d.scale_pct, 5, 100),
    opacity: _toNum(src.opacity, d.opacity, 5, 100),
    remove_bg: !!src.remove_bg,
    sync_main: !!src.sync_main,
    bg_key_color: /^#?[0-9a-fA-F]{6}$/.test(String(src.bg_key_color || ''))
      ? (String(src.bg_key_color).startsWith('#') ? String(src.bg_key_color) : `#${String(src.bg_key_color)}`)
      : d.bg_key_color,
    bg_similarity: _toNum(src.bg_similarity, d.bg_similarity, 0.01, 0.60),
    bg_blend: _toNum(src.bg_blend, d.bg_blend, 0.0, 0.40),
  };
}

function _burnLogoDefaults() {
  return {
    x: _toNum(criacaoState.logoX, 97, 0, 100),
    y: _toNum(criacaoState.logoY, 97, 0, 100),
    scale_pct: _toNum(criacaoState.logoScalePct, 20, 5, 100),
    opacity: _toNum(criacaoState.logoOpacity, 85, 5, 100),
    enabled: true,
  };
}

function _burnNormalizeLogo(raw) {
  const src = raw && typeof raw === 'object' ? raw : {};
  const d = _burnLogoDefaults();
  const name = String(src.name || src.logo_name || criacaoState.logoName || 'logo').trim() || 'logo';
  const logoSrc = String(src.src || src.b64 || src.logo_b64 || '').trim();
  const mime = String(src.mime || '').trim().toLowerCase();
  const isGif = mime === 'image/gif' || /\.gif$/i.test(name) || /^data:image\/gif/i.test(logoSrc);
  return {
    id: String(src.id || `burn_logo_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`),
    name,
    src: logoSrc,
    mime: mime || (isGif ? 'image/gif' : ''),
    isGif: !!isGif,
    x: _toNum(src.x ?? src.logo_x, d.x, 0, 100),
    y: _toNum(src.y ?? src.logo_y, d.y, 0, 100),
    scale_pct: _toNum(src.scale_pct ?? src.logo_scale_pct, d.scale_pct, 5, 100),
    opacity: _toNum(src.opacity ?? src.logo_opacity, d.opacity, 5, 100),
    enabled: src.enabled !== false,
    sync_main: !!src.sync_main,
  };
}

function _burnLogoList(opts = {}) {
  const seedFromLegacy = opts.seedFromLegacy !== false;
  let list = Array.isArray(criacaoState.burnLogos) ? criacaoState.burnLogos : [];
  if (!list.length && seedFromLegacy && criacaoState.logoB64) {
    list = [_burnNormalizeLogo({
      name: criacaoState.logoName || 'logo-passo-1',
      src: criacaoState.logoB64,
      mime: /^data:image\/gif/i.test(String(criacaoState.logoB64 || '')) ? 'image/gif' : 'image/png',
      x: criacaoState.logoX,
      y: criacaoState.logoY,
      scale_pct: criacaoState.logoScalePct,
      opacity: criacaoState.logoOpacity,
      enabled: true,
      sync_main: true,
    })];
  }
  list = list
    .map(_burnNormalizeLogo)
    .filter((item) => !!item.src)
    .slice(0, BURN_LOGO_MAX_COUNT);
  criacaoState.burnLogos = list;
  if (criacaoState.burnLogoActiveIdx >= list.length) {
    criacaoState.burnLogoActiveIdx = Math.max(0, list.length - 1);
  }
  return list;
}

function _burnActiveLogoIndex() {
  const len = Array.isArray(criacaoState.burnLogos) ? criacaoState.burnLogos.length : 0;
  const maxIdx = Math.max(0, len - 1);
  criacaoState.burnLogoActiveIdx = _clamp(parseInt(criacaoState.burnLogoActiveIdx || 0, 10) || 0, 0, maxIdx);
  return criacaoState.burnLogoActiveIdx;
}

function _burnActiveLogo() {
  const list = _burnLogoList(); // single call — assigns criacaoState.burnLogos = list
  if (!list.length) return null;
  const idx = _burnActiveLogoIndex(); // uses criacaoState.burnLogos.length (same list)
  return list[idx] || null; // list[idx] === criacaoState.burnLogos[idx] ✓
}

function _syncLegacyLogoFromBurnLogo(logo) {
  const item = logo ? _burnNormalizeLogo(logo) : null;
  if (!item || !item.src) {
    criacaoState.logoB64 = null;
    criacaoState.logoName = '';
    return;
  }
  criacaoState.logoB64 = item.src;
  criacaoState.logoName = item.name;
  criacaoState.logoX = item.x;
  criacaoState.logoY = item.y;
  criacaoState.logoScalePct = item.scale_pct;
  criacaoState.logoOpacity = item.opacity;
}

function _syncLegacyLogoFromActiveBurnLogo() {
  _syncLegacyLogoFromBurnLogo(_burnActiveLogo());
  _syncMainLogoIntoThumbElements();
}

function _burnLogoPayloadList() {
  return _burnLogoList()
    .map(_burnNormalizeLogo)
    .filter((l) => !!l.src && l.enabled !== false)
    .slice(0, BURN_LOGO_MAX_COUNT)
    .map((l) => ({
      b64: l.src,
      name: l.name,
      mime: l.mime || (l.isGif ? 'image/gif' : 'image/png'),
      x: _toNum(l.x, 97, 0, 100),
      y: _toNum(l.y, 97, 0, 100),
      scale_pct: _toNum(l.scale_pct, 20, 5, 100),
      opacity: _toNum(l.opacity, 85, 5, 100),
      enabled: l.enabled !== false,
      sync_main: !!l.sync_main,
    }));
}

function _normalizeLogoPreset(preset, fallback = DEFAULT_LOGO_PRESET) {
  const src = (preset && typeof preset === 'object') ? preset : {};
  return {
    id: String(src.id || fallback.id || 'saved'),
    name: String(src.name || fallback.name || 'Padrão salvo').trim() || 'Padrão salvo',
    logo_x: _toNum(src.logo_x, fallback.logo_x ?? 97, 0, 100),
    logo_y: _toNum(src.logo_y, fallback.logo_y ?? 97, 0, 100),
    logo_scale_pct: _toNum(src.logo_scale_pct, fallback.logo_scale_pct ?? 20, 5, 100),
    logo_opacity: _toNum(src.logo_opacity, fallback.logo_opacity ?? 85, 5, 100),
  };
}

function _presetById(id) {
  if ((id || 'saved') === 'saved') {
    return _normalizeLogoPreset({ ..._savedLogoPreset, id: 'saved' });
  }
  const found = LOGO_PRESET_OPTIONS.find(p => p.id === id);
  return _normalizeLogoPreset(found || LOGO_PRESET_OPTIONS[1]);
}

function _presetLabel(p) {
  const pp = _normalizeLogoPreset(p);
  return `${pp.name} (${pp.logo_x.toFixed(0)}%/${pp.logo_y.toFixed(0)}% · ${pp.logo_scale_pct.toFixed(0)}% · ${pp.logo_opacity.toFixed(0)}%)`;
}

function _renderLogoPresetOptions() {
  return LOGO_PRESET_OPTIONS.map(p => {
    const chosen = (criacaoState.logoPresetChoice || 'saved') === p.id ? 'selected' : '';
    const base = p.id === 'saved' ? _savedLogoPreset : p;
    return `<option value="${p.id}" ${chosen}>${esc(_presetLabel(base))}</option>`;
  }).join('');
}

async function _loadSavedLogoPreset() {
  try {
    const headers = {};
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch('/settings/wizard/logo-preset', { headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) return;
    _savedLogoPreset = _normalizeLogoPreset({ ...(data.preset || {}), id: 'saved' });
  } catch (_) {
    // fallback silencioso para preset local padrão
  }
}

function applyLogoPreset(presetId) {
  const p = _presetById(presetId || 'saved');
  criacaoState.logoPresetChoice = p.id || 'saved';
  if (p.id !== 'saved') criacaoState.logoProfileLayoutLinked = false;
  _setLogoPos(p.logo_x, p.logo_y);
  _setLogoStyle(p.logo_scale_pct, p.logo_opacity);
  _invalidateLogoPreviewComposited();
  _scheduleLogoPreviewHqRefresh();
  _persistWizardState();
}

async function saveCurrentLogoPreset() {
  const payload = {
    name: 'Padrão salvo',
    logo_x: criacaoState.logoX,
    logo_y: criacaoState.logoY,
    logo_scale_pct: criacaoState.logoScalePct,
    logo_opacity: criacaoState.logoOpacity,
  };
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch('/settings/wizard/logo-preset', {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);
    _savedLogoPreset = _normalizeLogoPreset({ ...(data.preset || payload), id: 'saved' });
    criacaoState.logoPresetChoice = 'saved';
    _persistWizardState({ immediate: true });
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    toast('Preset padrão da logo salvo', 'good');
  } catch (e) {
    toast('Erro ao salvar preset: ' + e.message, 'bad');
  }
}

function _normalizeLogoProfile(src = {}) {
  const preset = _normalizeLogoPreset(src);
  const companyName = String(src.company_name || src.name || '').trim();
  const rawLogos = Array.isArray(src.logos) ? src.logos : [];
  let logos = rawLogos
    .map((logo, idx) => _burnNormalizeLogo({
      ...logo,
      name: logo?.name || logo?.logo_name || (idx === 0 ? src.logo_name : `logo-${idx + 1}`),
      src: logo?.src || logo?.b64 || logo?.logo_b64 || '',
      x: logo?.x ?? logo?.logo_x,
      y: logo?.y ?? logo?.logo_y,
      scale_pct: logo?.scale_pct ?? logo?.logo_scale_pct,
      opacity: logo?.opacity ?? logo?.logo_opacity,
    }))
    .filter((item) => !!item.src)
    .slice(0, BURN_LOGO_MAX_COUNT);
  if (!logos.length && (src.logo_b64 || src.logoB64)) {
    logos = [_burnNormalizeLogo({
      name: src.logo_name || src.logoName || `${companyName || 'empresa'}.png`,
      src: src.logo_b64 || src.logoB64 || '',
      x: preset.logo_x,
      y: preset.logo_y,
      scale_pct: preset.logo_scale_pct,
      opacity: preset.logo_opacity,
      enabled: true,
      sync_main: true,
    })];
  }
  return {
    id: String(src.id || '').trim(),
    company_name: companyName,
    logo_name: String(src.logo_name || src.logoName || '').trim(),
    logo_object_key: _normalizeObjectKeyish(src.logo_object_key || src.logoObjectKey || '') || null,
    logo_b64: typeof src.logo_b64 === 'string' ? src.logo_b64 : (typeof src.logoB64 === 'string' ? src.logoB64 : ''),
    logo_stream_url: typeof src.logo_stream_url === 'string' ? src.logo_stream_url : '',
    logos,
    logo_available: src.logo_available !== false && !!(logos.length || src.logo_b64 || src.logoB64 || src.logo_object_key || src.logoObjectKey),
    updated_at: String(src.updated_at || '').trim(),
    ...preset,
  };
}

function _setLogoProfiles(list) {
  _logoProfiles = (Array.isArray(list) ? list : [])
    .map(_normalizeLogoProfile)
    .filter((item) => !!item.id && !!item.company_name)
    .sort((a, b) => String(a.company_name || '').localeCompare(String(b.company_name || ''), 'pt-BR', { sensitivity: 'base' }));
}

function _logoProfileById(id) {
  const safeId = String(id || '').trim();
  if (!safeId) return null;
  return _logoProfiles.find((item) => item.id === safeId) || null;
}

function _findLogoProfileByCompanyName(name) {
  const target = String(name || '').trim().toLowerCase();
  if (!target) return null;
  return _logoProfiles.find((item) => String(item.company_name || '').trim().toLowerCase() === target) || null;
}

function _syncMainLogoIntoThumbElements() {
  _thumbElements().forEach(el => {
    if (el?.type === 'image' && el?.role === 'logo') el.src = criacaoState.logoB64 || '';
  });
}

function _renderLogoProfileOptions() {
  const current = String(criacaoState.logoProfileId || '').trim();
  const items = [
    `<option value="" ${current ? '' : 'selected'}>Escolher empresa salva…</option>`,
  ];
  _logoProfiles.forEach((profile) => {
    const chosen = current && current === profile.id ? 'selected' : '';
    const logoCount = Array.isArray(profile.logos) && profile.logos.length ? profile.logos.length : 1;
    const label = `${profile.company_name} · ${logoCount} logo(s) (${profile.logo_x.toFixed(0)}%/${profile.logo_y.toFixed(0)}% · ${profile.logo_scale_pct.toFixed(0)}%)`;
    items.push(`<option value="${escAttr(profile.id)}" ${chosen}>${esc(label)}</option>`);
  });
  return items.join('');
}

function _profileLogoForActive(profile) {
  const p = _normalizeLogoProfile(profile || {});
  const logos = Array.isArray(p.logos) ? p.logos : [];
  if (!logos.length) return null;
  const active = _burnActiveLogo();
  if (active?.id) {
    const found = logos.find((lg) => String(lg.id || '') === String(active.id || ''));
    if (found) return found;
  }
  const idx = _burnActiveLogoIndex();
  return logos[Math.min(idx, logos.length - 1)] || logos[0] || null;
}

function _markLogoProfileLayoutCustomIfNeeded() {
  if (!criacaoState.logoProfileId) return false;
  if (criacaoState.logoProfileLayoutLinked === false) return false;
  const profile = _logoProfileById(criacaoState.logoProfileId);
  if (!profile) return false;
  const profileLogo = _profileLogoForActive(profile) || profile;
  const differs = (
    Math.abs(Number(criacaoState.logoX || 0) - Number(profileLogo.x ?? profileLogo.logo_x ?? 0)) > 0.05
    || Math.abs(Number(criacaoState.logoY || 0) - Number(profileLogo.y ?? profileLogo.logo_y ?? 0)) > 0.05
    || Math.abs(Number(criacaoState.logoScalePct || 0) - Number(profileLogo.scale_pct ?? profileLogo.logo_scale_pct ?? 0)) > 0.05
    || Math.abs(Number(criacaoState.logoOpacity || 0) - Number(profileLogo.opacity ?? profileLogo.logo_opacity ?? 0)) > 0.05
  );
  if (!differs) return false;
  criacaoState.logoProfileLayoutLinked = false;
  return true;
}

function _isLogoLayoutMatchingProfile() {
  if (!criacaoState.logoProfileId) return null;
  const profile = _logoProfileById(criacaoState.logoProfileId);
  if (!profile) return null;
  const profileLogo = _profileLogoForActive(profile) || profile;
  const differs = (
    Math.abs(Number(criacaoState.logoX || 0) - Number(profileLogo.x ?? profileLogo.logo_x ?? 0)) > 0.05
    || Math.abs(Number(criacaoState.logoY || 0) - Number(profileLogo.y ?? profileLogo.logo_y ?? 0)) > 0.05
    || Math.abs(Number(criacaoState.logoScalePct || 0) - Number(profileLogo.scale_pct ?? profileLogo.logo_scale_pct ?? 0)) > 0.05
    || Math.abs(Number(criacaoState.logoOpacity || 0) - Number(profileLogo.opacity ?? profileLogo.logo_opacity ?? 0)) > 0.05
  );
  return !differs;
}

function _syncLogoLayoutLinkBeforeRender() {
  if (criacaoState.logoProfileLayoutLinked === false) return false;
  const matches = _isLogoLayoutMatchingProfile();
  if (matches === false) {
    criacaoState.logoProfileLayoutLinked = false;
    return true;
  }
  return false;
}

function _applyLogoProfileToState(profile, opts = {}) {
  const item = _normalizeLogoProfile(profile || {});
  if (!item.id || !item.company_name) return false;
  const applyLayout = opts.applyLayout !== false;
  const persist = opts.persist !== false;
  const render = opts.render !== false;
  const refreshHq = opts.refreshHq !== false;
  const setDraftName = opts.setDraftName !== false;

  criacaoState.logoProfileId = item.id;
  criacaoState.logoProfileName = item.company_name;
  criacaoState.logoProfileLayoutLinked = true;
  if (setDraftName || !String(criacaoState.logoCompanyDraftName || '').trim()) {
    criacaoState.logoCompanyDraftName = item.company_name;
  }
  const profileLogos = Array.isArray(item.logos) && item.logos.length
    ? item.logos.map(_burnNormalizeLogo).filter((lg) => !!lg.src).slice(0, BURN_LOGO_MAX_COUNT)
    : [];
  if (profileLogos.length) {
    criacaoState.burnLogos = profileLogos;
    criacaoState.burnLogoActiveIdx = 0;
    criacaoState.burnLogoTargetCount = Math.max(1, Math.min(BURN_LOGO_MAX_COUNT, profileLogos.length));
    _syncLegacyLogoFromActiveBurnLogo();
  } else if (item.logo_b64) {
    criacaoState.burnLogos = [_burnNormalizeLogo({
      name: item.logo_name || `${item.company_name}.png`,
      src: item.logo_b64,
      x: item.logo_x,
      y: item.logo_y,
      scale_pct: item.logo_scale_pct,
      opacity: item.logo_opacity,
      enabled: true,
      sync_main: true,
    })];
    criacaoState.burnLogoActiveIdx = 0;
    criacaoState.burnLogoTargetCount = 1;
    _syncLegacyLogoFromActiveBurnLogo();
  }
  if (applyLayout && !profileLogos.length) {
    criacaoState.logoX = item.logo_x;
    criacaoState.logoY = item.logo_y;
    criacaoState.logoScalePct = item.logo_scale_pct;
    criacaoState.logoOpacity = item.logo_opacity;
    const active = _burnActiveLogo();
    if (active) {
      active.x = item.logo_x;
      active.y = item.logo_y;
      active.scale_pct = item.logo_scale_pct;
      active.opacity = item.logo_opacity;
      _syncLegacyLogoFromActiveBurnLogo();
    }
  }

  _invalidateLogoPreviewComposited();
  if (refreshHq) _scheduleLogoPreviewHqRefresh();
  if (persist) _persistWizardState({ immediate: !!opts.immediate });
  if (render && criacaoState.runId) renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
  if (opts.redrawThumb !== false) drawThumbWithLogo(false);
  return true;
}

function _hydrateSelectedLogoProfileIntoState(opts = {}) {
  if (!criacaoState.logoProfileId) return false;
  const profile = _logoProfileById(criacaoState.logoProfileId);
  if (!profile) return false;
  const applyLinkedLayout = opts.applyLayout === true
    || (opts.applyLayout !== false && criacaoState.logoProfileLayoutLinked !== false);
  if (opts.force || !criacaoState.logoB64 || applyLinkedLayout) {
    return _applyLogoProfileToState(profile, {
      applyLayout: applyLinkedLayout,
      persist: false,
      render: false,
      refreshHq: false,
      setDraftName: !String(criacaoState.logoCompanyDraftName || '').trim(),
      redrawThumb: false,
    });
  }
  if (!criacaoState.logoProfileName) criacaoState.logoProfileName = profile.company_name;
  if (!String(criacaoState.logoCompanyDraftName || '').trim()) criacaoState.logoCompanyDraftName = profile.company_name;
  return true;
}

async function _loadLogoProfiles() {
  try {
    const headers = {};
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch('/settings/wizard/logo-profiles', { headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) return;
    _setLogoProfiles(data.profiles || []);
    _logoProfilesUpdatedAt = data.updated_at || null;
    if (criacaoState.logoProfileId) {
      _hydrateSelectedLogoProfileIntoState({ force: criacaoState.logoProfileLayoutLinked !== false });
    }
  } catch (_) {
    // fallback silencioso
  }
}

async function applyLogoCompany(profileId) {
  const safeId = String(profileId || '').trim();
  if (!safeId) {
    criacaoState.logoProfileId = '';
    criacaoState.logoProfileName = '';
    criacaoState.logoProfileLayoutLinked = false;
    _persistWizardState({ immediate: true });
    if (criacaoState.runId) renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    return;
  }
  const profile = _logoProfileById(safeId);
  if (!profile) return toast('Empresa salva não encontrada', 'bad');
  _applyLogoProfileToState(profile, { immediate: true });
  toast(`Logo da empresa "${profile.company_name}" aplicada`, 'good');
}

function _setLogoCompanyDraft(value) {
  criacaoState.logoCompanyDraftName = String(value || '').slice(0, 80);
  _persistWizardState();
}

async function saveCurrentLogoCompany() {
  _syncCriacaoDraftsFromDom();
  const burnLogos = _burnLogoPayloadList();
  if (!burnLogos.length) return toast('Envie pelo menos uma logo antes de salvar a empresa', 'bad');
  const companyName = String(criacaoState.logoCompanyDraftName || criacaoState.logoProfileName || '').trim();
  if (!companyName) return toast('Digite o nome da empresa para salvar as logos', 'bad');
  const primaryLogo = burnLogos[0];

  const selectedProfile = _logoProfileById(criacaoState.logoProfileId);
  const sameNameProfile = _findLogoProfileByCompanyName(companyName);
  const shouldUpdateSelected = !!(
    selectedProfile &&
    String(selectedProfile.company_name || '').trim().toLowerCase() === companyName.toLowerCase()
  );
  const profileId = String((shouldUpdateSelected ? selectedProfile?.id : sameNameProfile?.id) || '').trim();
  if (sameNameProfile && sameNameProfile.id !== profileId) {
    const ok = confirm(`Já existe uma empresa salva com o nome "${sameNameProfile.company_name}". Deseja substituir a logo e o posicionamento salvos?`);
    if (!ok) return;
  }

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch('/settings/wizard/logo-profiles', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        profile_id: profileId || null,
        company_name: companyName,
        logo_b64: primaryLogo.b64,
        logo_name: primaryLogo.name || `${companyName}.png`,
        logo_x: primaryLogo.x,
        logo_y: primaryLogo.y,
        logo_scale_pct: primaryLogo.scale_pct,
        logo_opacity: primaryLogo.opacity,
        logos: burnLogos,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);
    _setLogoProfiles(data.profiles || []);
    _logoProfilesUpdatedAt = data.updated_at || null;
    const savedProfile = _normalizeLogoProfile(data.profile || {});
    _applyLogoProfileToState(savedProfile, { immediate: true });
    toast(`Empresa "${savedProfile.company_name}" salva com ${burnLogos.length} logo(s)`, 'good');
  } catch (e) {
    toast('Erro ao salvar empresa: ' + e.message, 'bad');
  }
}

async function deleteSelectedLogoCompany() {
  const profileId = String(criacaoState.logoProfileId || '').trim();
  const profile = _logoProfileById(profileId);
  if (!profileId || !profile) return toast('Selecione uma empresa salva primeiro', 'bad');
  if (!confirm(`Excluir a empresa "${profile.company_name}" da biblioteca de logos?`)) return;
  try {
    const headers = {};
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch(`/settings/wizard/logo-profiles/${encodeURIComponent(profileId)}`, {
      method: 'DELETE',
      headers,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);
    _setLogoProfiles(data.profiles || []);
    _logoProfilesUpdatedAt = data.updated_at || null;
    criacaoState.logoProfileId = '';
    criacaoState.logoProfileName = '';
    criacaoState.logoProfileLayoutLinked = false;
    if (String(criacaoState.logoCompanyDraftName || '').trim().toLowerCase() === String(profile.company_name || '').trim().toLowerCase()) {
      criacaoState.logoCompanyDraftName = '';
    }
    _persistWizardState({ immediate: true });
    if (criacaoState.runId) renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    toast(`Empresa "${profile.company_name}" excluída da biblioteca`, 'good');
  } catch (e) {
    toast('Erro ao excluir empresa: ' + e.message, 'bad');
  }
}

function _wizardRemotePayload() {
  return {
    step: _clamp(parseInt(criacaoState.step || 1, 10), 1, CRIACAO_MAX_STEP),
    logo_preset_choice: criacaoState.logoPresetChoice || 'saved',
    logo_profile_id: criacaoState.logoProfileId || null,
    logo_profile_name: criacaoState.logoProfileName || null,
    logo_profile_layout_linked: criacaoState.logoProfileLayoutLinked !== false,
    logo_x: criacaoState.logoX,
    logo_y: criacaoState.logoY,
    logo_scale_pct: criacaoState.logoScalePct,
    logo_opacity: criacaoState.logoOpacity,
    burn_logo_count: _burnLogoList({ seedFromLegacy: false }).length,
    burn_logo_target_count: _clamp(parseInt(criacaoState.burnLogoTargetCount || 1, 10) || 1, 1, BURN_LOGO_MAX_COUNT),
    burn_logo_active_idx: _clamp(parseInt(criacaoState.burnLogoActiveIdx || 0, 10) || 0, 0, BURN_LOGO_MAX_COUNT - 1),
    burned_object_key: _normalizeObjectKeyish(criacaoState.burnedObjectKey) || null,
    burned_filename: criacaoState.burnedFilename || null,
    burned_quality: String(criacaoState.burnedQuality || '26'),
    burned_resolution: String(criacaoState.burnedResolution || '1080'),
    burned_preset: String(criacaoState.burnedPreset || 'ultrafast'),
    teaser_object_key: _normalizeObjectKeyish(criacaoState.teaserObjectKey) || null,
    teaser_logo_object_key: _normalizeObjectKeyish(criacaoState.teaserLogoObjectKey) || null,
    teaser_logo_filename: String(criacaoState.teaserLogoFilename || '').trim() || null,
    teaser_combined_object_key: _normalizeObjectKeyish(criacaoState.teaserCombinedObjectKey) || null,
    teaser_source_type: criacaoState.teaserSourceType || 'burned',
    teaser_source_object_key: _normalizeObjectKeyish(criacaoState.teaserSourceObjectKey) || null,
    teaser_concat_mode: criacaoState.teaserConcatMode || 'start',
    teaser_selected_frames: (criacaoState.teaserSelectedFrames || []).slice(0, 60),
    teaser_scene_durations_by_frame: (criacaoState.teaserSceneDurationsByFrame && typeof criacaoState.teaserSceneDurationsByFrame === 'object')
      ? criacaoState.teaserSceneDurationsByFrame
      : {},
    teaser_quality: String(criacaoState.teaserQuality || '26'),
    teaser_clip_duration: String(criacaoState.teaserClipDuration || '6'),
    teaser_num_clips: String(criacaoState.teaserNumClips || '8'),
    teaser_auto_distribute: !!criacaoState.teaserAutoDistribute,
    teaser_target_duration_min: String(criacaoState.teaserTargetDurationMin || '11'),
    teaser_first_clip_min: String(criacaoState.teaserFirstClipMin || '1'),
    teaser_last_clip_min: String(criacaoState.teaserLastClipMin || '1'),
    teaser_force_logo_overlay: !!criacaoState.teaserForceLogoOverlay,
    teaser_logo_count: Array.isArray(criacaoState.teaserLogos) ? criacaoState.teaserLogos.length : 0,
    teaser_narration_enabled: !!criacaoState.teaserNarrationEnabled,
    teaser_original_audio_volume: Number(criacaoState.teaserOriginalAudioVolume || 100),
    teaser_narration_volume: Number(criacaoState.teaserNarrationVolume || 120),
    teaser_narration_offset_sec: Number(criacaoState.teaserNarrationOffsetSec || 0),
    teaser_narration_object_key: _normalizeObjectKeyish(criacaoState.teaserNarrationObjectKey) || null,
    teaser_narration_used: !!criacaoState.teaserNarrationUsed,
    teaser_opener_object_key: _normalizeObjectKeyish(criacaoState.teaserOpenerObjectKey) || null,
    teaser_opener_position: criacaoState.teaserOpenerPosition === 'end' ? 'end' : 'start',
    thumb_frame_idx: (criacaoState.thumbFrameIdx == null ? null : parseInt(criacaoState.thumbFrameIdx, 10)),
    thumb_subtitle: criacaoState.thumbSubtitle || '',
    thumb_video_object_key: _normalizeObjectKeyish(criacaoState.thumbVideoObjectKey) || null,
    thumb_export_format: criacaoState.thumbExportFormat || 'png',
    thumb_jpeg_quality: parseInt(criacaoState.thumbJpegQuality || 98, 10),
    thumb_output_scale: parseInt(criacaoState.thumbOutputScale || 2, 10),
    thumb_crop_x: Number(criacaoState.thumbCropX || 50),
    thumb_crop_y: Number(criacaoState.thumbCropY || 50),
    thumb_zoom: Number(criacaoState.thumbZoom || 1),
    thumb_brightness: Number(criacaoState.thumbBrightness || 100),
    thumb_contrast: Number(criacaoState.thumbContrast || 100),
    thumb_saturation: Number(criacaoState.thumbSaturation || 100),
    thumb_hue: Number(criacaoState.thumbHue || 0),
  };
}

function _wizardSessionPayload() {
  return {
    logoProfileId: criacaoState.logoProfileId || '',
    logoProfileName: criacaoState.logoProfileName || '',
    logoProfileLayoutLinked: criacaoState.logoProfileLayoutLinked !== false,
    logoCompanyDraftName: criacaoState.logoCompanyDraftName || '',
    logoB64: criacaoState.logoB64 || null,
    logoName: criacaoState.logoName || '',
    burnLogos: Array.isArray(criacaoState.burnLogos)
      ? criacaoState.burnLogos.map(_burnNormalizeLogo).filter((x) => !!x.src).slice(0, BURN_LOGO_MAX_COUNT)
      : [],
    burnLogoActiveIdx: _clamp(parseInt(criacaoState.burnLogoActiveIdx || 0, 10) || 0, 0, BURN_LOGO_MAX_COUNT - 1),
    burnLogoTargetCount: _clamp(parseInt(criacaoState.burnLogoTargetCount || 1, 10) || 1, 1, BURN_LOGO_MAX_COUNT),
    teaserLogos: Array.isArray(criacaoState.teaserLogos)
      ? criacaoState.teaserLogos.map(_teaserNormalizeLogo).slice(0, 6)
      : [],
    teaserLogoActiveIdx: _clamp(parseInt(criacaoState.teaserLogoActiveIdx || 0, 10) || 0, 0, 50),
    transcriptDraft: criacaoState.transcriptDraft || '',
    thumbElements: Array.isArray(criacaoState.thumbElements) ? criacaoState.thumbElements : [],
    thumbSelectedElementId: criacaoState.thumbSelectedElementId || null,
    compareText: criacaoState.compareText || null,
    compareTitles: criacaoState.compareTitles || [],
    compareDescription: criacaoState.compareDescription || '',
    compareTags: criacaoState.compareTags || [],
    compareFirst10sHook: criacaoState.compareFirst10sHook || '',
    wizard: _wizardRemotePayload(),
  };
}

function _applyWizardRemoteState(ws) {
  if (!ws || typeof ws !== 'object') return;
  if (ws.logo_preset_choice) criacaoState.logoPresetChoice = String(ws.logo_preset_choice);
  if (ws.logo_profile_id != null) criacaoState.logoProfileId = String(ws.logo_profile_id || '').trim();
  if (ws.logo_profile_name != null) criacaoState.logoProfileName = String(ws.logo_profile_name || '').trim();
  if (ws.logo_profile_layout_linked != null) criacaoState.logoProfileLayoutLinked = !!ws.logo_profile_layout_linked;
  if (ws.logo_x != null) criacaoState.logoX = _toNum(ws.logo_x, criacaoState.logoX, 0, 100);
  if (ws.logo_y != null) criacaoState.logoY = _toNum(ws.logo_y, criacaoState.logoY, 0, 100);
  if (ws.logo_scale_pct != null) criacaoState.logoScalePct = _toNum(ws.logo_scale_pct, criacaoState.logoScalePct, 5, 100);
  if (ws.logo_opacity != null) criacaoState.logoOpacity = _toNum(ws.logo_opacity, criacaoState.logoOpacity, 5, 100);
  if (ws.burn_logo_target_count != null) {
    criacaoState.burnLogoTargetCount = _clamp(parseInt(ws.burn_logo_target_count, 10) || 1, 1, BURN_LOGO_MAX_COUNT);
  }
  if (ws.burn_logo_active_idx != null) {
    criacaoState.burnLogoActiveIdx = _clamp(parseInt(ws.burn_logo_active_idx, 10) || 0, 0, BURN_LOGO_MAX_COUNT - 1);
  }

  if (ws.burned_object_key) criacaoState.burnedObjectKey = _normalizeObjectKeyish(ws.burned_object_key);
  if (ws.burned_filename) criacaoState.burnedFilename = String(ws.burned_filename);
  if (ws.burned_quality) criacaoState.burnedQuality = String(ws.burned_quality);
  if (ws.burned_resolution) criacaoState.burnedResolution = String(ws.burned_resolution);
  if (ws.burned_preset) criacaoState.burnedPreset = String(ws.burned_preset);

  if (ws.teaser_object_key) criacaoState.teaserObjectKey = _normalizeObjectKeyish(ws.teaser_object_key);
  if (ws.teaser_logo_object_key) criacaoState.teaserLogoObjectKey = _normalizeObjectKeyish(ws.teaser_logo_object_key);
  if (ws.teaser_logo_filename) criacaoState.teaserLogoFilename = String(ws.teaser_logo_filename || '').trim() || null;
  if (ws.teaser_combined_object_key) criacaoState.teaserCombinedObjectKey = _normalizeObjectKeyish(ws.teaser_combined_object_key);
  if (ws.teaser_source_type) {
    const st = String(ws.teaser_source_type).toLowerCase();
    criacaoState.teaserSourceType = st === 'original' ? 'original' : 'burned';
  }
  if (ws.teaser_source_object_key) criacaoState.teaserSourceObjectKey = _normalizeObjectKeyish(ws.teaser_source_object_key);
  if (ws.teaser_concat_mode) criacaoState.teaserConcatMode = String(ws.teaser_concat_mode) === 'end' ? 'end' : 'start';
  if (Array.isArray(ws.teaser_selected_frames)) {
    criacaoState.teaserSelectedFrames = ws.teaser_selected_frames
      .map(v => parseInt(v, 10))
      .filter(v => Number.isInteger(v) && v >= 0)
      .slice(0, 60);
  }
  if (ws.teaser_scene_durations_by_frame && typeof ws.teaser_scene_durations_by_frame === 'object') {
    const map = {};
    Object.entries(ws.teaser_scene_durations_by_frame).forEach(([k, v]) => {
      const idx = parseInt(k, 10);
      const dur = Number(v);
      if (!Number.isInteger(idx) || idx < 0 || !Number.isFinite(dur)) return;
      map[idx] = _clamp(dur, 1, TEASER_MAX_SCENE_DURATION_SEC);
    });
    criacaoState.teaserSceneDurationsByFrame = map;
  }
  if (ws.teaser_quality) criacaoState.teaserQuality = String(ws.teaser_quality);
  if (ws.teaser_clip_duration) {
    criacaoState.teaserClipDuration = String(_clamp(Number(ws.teaser_clip_duration) || 6, 2, TEASER_MAX_SCENE_DURATION_SEC));
  }
  if (ws.teaser_num_clips) {
    criacaoState.teaserNumClips = String(_clamp(parseInt(ws.teaser_num_clips, 10) || 8, 2, TEASER_MAX_NUM_CLIPS));
  }
  if (ws.teaser_auto_distribute != null) criacaoState.teaserAutoDistribute = !!ws.teaser_auto_distribute;
  if (ws.teaser_target_duration_min != null) {
    criacaoState.teaserTargetDurationMin = String(_clamp(Number(ws.teaser_target_duration_min) || 0, 0.1, TEASER_MAX_TOTAL_DURATION_SEC / 60));
  }
  if (ws.teaser_first_clip_min != null) {
    criacaoState.teaserFirstClipMin = String(_clamp(Number(ws.teaser_first_clip_min) || 0, 0, TEASER_MAX_SCENE_DURATION_SEC / 60));
  }
  if (ws.teaser_last_clip_min != null) {
    criacaoState.teaserLastClipMin = String(_clamp(Number(ws.teaser_last_clip_min) || 0, 0, TEASER_MAX_SCENE_DURATION_SEC / 60));
  }
  if (ws.teaser_force_logo_overlay != null) criacaoState.teaserForceLogoOverlay = !!ws.teaser_force_logo_overlay;
  _setTeaserSource(criacaoState.teaserSourceType, criacaoState.teaserSourceObjectKey, { persist: false, render: false });
  if (ws.teaser_logo_count != null && Number(ws.teaser_logo_count) > 0) criacaoState.teaserLogoAutoSeeded = true;
  if (ws.teaser_narration_enabled != null) criacaoState.teaserNarrationEnabled = !!ws.teaser_narration_enabled;
  if (ws.teaser_original_audio_volume != null) {
    const vv = Number(ws.teaser_original_audio_volume);
    const normalized = Number.isFinite(vv) && vv <= 2.01 ? vv * 100 : vv;
    criacaoState.teaserOriginalAudioVolume = _toNum(normalized, 100, 0, 200);
  }
  if (ws.teaser_narration_volume != null) {
    const vv = Number(ws.teaser_narration_volume);
    const normalized = Number.isFinite(vv) && vv <= 2.01 ? vv * 100 : vv;
    criacaoState.teaserNarrationVolume = _toNum(normalized, 120, 0, 200);
  }
  if (ws.teaser_narration_offset_sec != null) {
    criacaoState.teaserNarrationOffsetSec = _toNum(ws.teaser_narration_offset_sec, 0, -30, 30);
  }
  if (ws.teaser_narration_object_key) {
    criacaoState.teaserNarrationObjectKey = _normalizeObjectKeyish(ws.teaser_narration_object_key);
  }
  if (ws.teaser_narration_used != null) criacaoState.teaserNarrationUsed = !!ws.teaser_narration_used;
  if (ws.teaser_opener_object_key != null) {
    const openerKey = _normalizeObjectKeyish(ws.teaser_opener_object_key);
    criacaoState.teaserOpenerObjectKey = openerKey || null;
    if (!openerKey) criacaoState.teaserOpenerUrl = null;
  }
  if (ws.teaser_opener_position) {
    criacaoState.teaserOpenerPosition = String(ws.teaser_opener_position) === 'end' ? 'end' : 'start';
  }

  if (ws.thumb_frame_idx != null) criacaoState.thumbFrameIdx = parseInt(ws.thumb_frame_idx, 10);
  if (ws.thumb_subtitle != null) criacaoState.thumbSubtitle = String(ws.thumb_subtitle || '');
  if (ws.thumb_video_object_key) criacaoState.thumbVideoObjectKey = _normalizeObjectKeyish(ws.thumb_video_object_key);
  if (ws.thumb_export_format) criacaoState.thumbExportFormat = ws.thumb_export_format === 'jpg' ? 'jpg' : 'png';
  if (ws.thumb_jpeg_quality != null) criacaoState.thumbJpegQuality = parseInt(ws.thumb_jpeg_quality, 10) || 98;
  if (ws.thumb_output_scale != null) criacaoState.thumbOutputScale = _clamp(parseInt(ws.thumb_output_scale, 10) || 2, 1, 3);
  if (ws.thumb_crop_x != null) criacaoState.thumbCropX = _toNum(ws.thumb_crop_x, 50, 0, 100);
  if (ws.thumb_crop_y != null) criacaoState.thumbCropY = _toNum(ws.thumb_crop_y, 50, 0, 100);
  if (ws.thumb_zoom != null) criacaoState.thumbZoom = _toNum(ws.thumb_zoom, 1, 1, 3);
  if (ws.thumb_brightness != null) criacaoState.thumbBrightness = _toNum(ws.thumb_brightness, 100, 40, 180);
  if (ws.thumb_contrast != null) criacaoState.thumbContrast = _toNum(ws.thumb_contrast, 100, 40, 180);
  if (ws.thumb_saturation != null) criacaoState.thumbSaturation = _toNum(ws.thumb_saturation, 100, 0, 220);
  if (ws.thumb_hue != null) criacaoState.thumbHue = _toNum(ws.thumb_hue, 0, -180, 180);

  if (ws.step != null) {
    criacaoState.step = _clamp(parseInt(ws.step, 10) || 1, 1, CRIACAO_MAX_STEP);
  }
}

function _applyWizardSessionState(data) {
  if (!data || typeof data !== 'object') return;
  if (typeof data.logoProfileId === 'string') criacaoState.logoProfileId = data.logoProfileId;
  if (typeof data.logoProfileName === 'string') criacaoState.logoProfileName = data.logoProfileName;
  if (data.logoProfileLayoutLinked != null) criacaoState.logoProfileLayoutLinked = !!data.logoProfileLayoutLinked;
  if (typeof data.logoCompanyDraftName === 'string') criacaoState.logoCompanyDraftName = data.logoCompanyDraftName;
  if (data.logoB64) criacaoState.logoB64 = data.logoB64;
  if (typeof data.logoName === 'string') criacaoState.logoName = data.logoName;
  if (Array.isArray(data.burnLogos)) {
    criacaoState.burnLogos = data.burnLogos
      .map(_burnNormalizeLogo)
      .filter((x) => !!x.src)
      .slice(0, BURN_LOGO_MAX_COUNT);
  }
  if (data.burnLogoTargetCount != null) {
    criacaoState.burnLogoTargetCount = _clamp(parseInt(data.burnLogoTargetCount, 10) || 1, 1, BURN_LOGO_MAX_COUNT);
  }
  if (data.burnLogoActiveIdx != null) {
    const maxIdx = Math.max(0, (criacaoState.burnLogos || []).length - 1);
    criacaoState.burnLogoActiveIdx = _clamp(parseInt(data.burnLogoActiveIdx, 10) || 0, 0, maxIdx);
  }
  if ((criacaoState.burnLogos || []).length) _syncLegacyLogoFromActiveBurnLogo();
  if (Array.isArray(data.teaserLogos)) {
    criacaoState.teaserLogos = data.teaserLogos
      .map(_teaserNormalizeLogo)
      .filter((x) => !!x.src)
      .slice(0, 6);
    if (criacaoState.teaserLogos.length) criacaoState.teaserLogoAutoSeeded = true;
  }
  if (data.teaserLogoActiveIdx != null) {
    const maxIdx = Math.max(0, (criacaoState.teaserLogos || []).length - 1);
    criacaoState.teaserLogoActiveIdx = _clamp(parseInt(data.teaserLogoActiveIdx, 10) || 0, 0, maxIdx);
  }
  if (typeof data.transcriptDraft === 'string' && data.transcriptDraft.trim()) {
    criacaoState.transcriptDraft = data.transcriptDraft;
    criacaoState.hasTranscript = true;
  }
  if (Array.isArray(data.thumbElements)) {
    criacaoState.thumbElements = data.thumbElements.slice(0, 30);
  }
  if (data.thumbSelectedElementId) {
    criacaoState.thumbSelectedElementId = String(data.thumbSelectedElementId);
  }
  if (data.compareText != null) criacaoState.compareText = data.compareText;
  if (Array.isArray(data.compareTitles)) criacaoState.compareTitles = data.compareTitles;
  if (data.compareDescription) criacaoState.compareDescription = data.compareDescription;
  if (Array.isArray(data.compareTags)) criacaoState.compareTags = data.compareTags;
  if (data.compareFirst10sHook) criacaoState.compareFirst10sHook = data.compareFirst10sHook;
  if (data.wizard && typeof data.wizard === 'object') {
    _applyWizardRemoteState(data.wizard);
  }
}

function _saveWizardSessionState() {
  if (!criacaoState.runId) return;
  try {
    sessionStorage.setItem(_wizardSessionKey(criacaoState.runId), JSON.stringify(_wizardSessionPayload()));
  } catch (_) {
    // ignore quota/session errors
  }
}

function _loadWizardSessionState(runId) {
  if (!runId) return null;
  try {
    const raw = sessionStorage.getItem(_wizardSessionKey(runId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (_) {
    return null;
  }
}

async function _persistWizardStateRemoteNow() {
  if (!criacaoState.runId) return;
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const payload = _wizardRemotePayload();
    const res = await fetch(`/runs/${criacaoState.runId}/wizard-state`, {
      method: 'PUT',
      headers,
      body: JSON.stringify({ state: payload }),
    });
    if (!res.ok) return;
    if (criacaoState._reqData) criacaoState._reqData.wizard_state = payload;
  } catch (_) {
    // best effort only
  }
}

function _persistWizardState(opts = {}) {
  const immediate = !!opts.immediate;
  _saveWizardSessionState();
  if (!criacaoState.runId) return;
  if (_wizardPersistTimer) clearTimeout(_wizardPersistTimer);
  if (immediate) {
    _persistWizardStateRemoteNow();
    return;
  }
  _wizardPersistTimer = setTimeout(() => {
    _persistWizardStateRemoteNow();
  }, 700);
}

async function _getVideoStreamUrl(objectKey) {
  const normalizedKey = _normalizeObjectKeyish(objectKey);
  if (!normalizedKey) return null;
  if (!window._streamUrlCache) window._streamUrlCache = new Map();
  const cache = window._streamUrlCache;
  const now = Date.now();
  const hit = cache.get(normalizedKey);
  if (hit && hit.url && hit.expires_at > now) return hit.url;
  try {
    const res = await apiFetch(`/api/video-stream-url?object_key=${encodeURIComponent(normalizedKey)}`);
    if (res?.error) return null;
    const url = res?.url || null;
    if (url) {
      // Presigned URL expira em 1h no backend; reusa por 50 min para reduzir chamadas repetidas.
      cache.set(normalizedKey, { url, expires_at: now + (50 * 60 * 1000) });
    }
    return url;
  } catch (_) {
    return null;
  }
}

async function _getAdaptivePreviewUrl(objectKey, opts = {}) {
  const normalizedKey = _normalizeObjectKeyish(objectKey);
  if (!normalizedKey) return null;
  const maxHeight = _clamp(parseInt(opts.maxHeight || 1080, 10) || 1080, 360, 2160);
  const maxFps = _clamp(parseInt(opts.maxFps || 30, 10) || 30, 24, 60);
  if (!window._adaptivePreviewCache) window._adaptivePreviewCache = new Map();
  const cache = window._adaptivePreviewCache;
  const cacheKey = `${normalizedKey}|h${maxHeight}|f${maxFps}`;
  const now = Date.now();
  const hit = cache.get(cacheKey);
  if (hit && hit.url && hit.expires_at > now) return hit.url;
  try {
    const res = await apiFetch(
      `/api/video-preview-url?object_key=${encodeURIComponent(normalizedKey)}&max_height=${maxHeight}&max_fps=${maxFps}`
    );
    if (res?.error) return null;
    const url = res?.url || null;
    if (url) {
      cache.set(cacheKey, { url, expires_at: now + (50 * 60 * 1000) });
    }
    return url;
  } catch (_) {
    return null;
  }
}

function _isAttachmentLikeUrl(url) {
  const raw = String(url || '').trim().toLowerCase();
  if (!raw) return false;
  if (raw.includes('response-content-disposition=attachment')) return true;
  if (raw.includes('response-content-disposition%3dattachment')) return true;
  if (raw.includes('attachment%3b')) return true;
  return false;
}

async function _hydrateWizardMediaUrls() {
  let changed = false;
  const originalSourceKey = _resolveOriginalVideoObjectKey();
  const targets = [];
  if ((!criacaoState.burnedVideoUrl || _isAttachmentLikeUrl(criacaoState.burnedVideoUrl)) && criacaoState.burnedObjectKey) {
    targets.push({ field: 'burnedVideoUrl', key: criacaoState.burnedObjectKey, mode: 'stream' });
  }
  if (criacaoState.teaserObjectKey) {
    // Prefere stream completo para preservar qualidade e áudio; fallback para preview se falhar.
    targets.push({ field: 'teaserUrl', key: criacaoState.teaserObjectKey, mode: 'stream', force: true });
  }
  if ((!criacaoState.teaserLogoUrl || _isAttachmentLikeUrl(criacaoState.teaserLogoUrl)) && criacaoState.teaserLogoObjectKey) {
    targets.push({ field: 'teaserLogoUrl', key: criacaoState.teaserLogoObjectKey, mode: 'stream' });
  }
  if ((!criacaoState.teaserCombinedUrl || _isAttachmentLikeUrl(criacaoState.teaserCombinedUrl)) && criacaoState.teaserCombinedObjectKey) {
    targets.push({ field: 'teaserCombinedUrl', key: criacaoState.teaserCombinedObjectKey, mode: 'stream' });
  }
  if ((!criacaoState.teaserNarrationAudioUrl || _isAttachmentLikeUrl(criacaoState.teaserNarrationAudioUrl)) && criacaoState.teaserNarrationObjectKey) {
    targets.push({ field: 'teaserNarrationAudioUrl', key: criacaoState.teaserNarrationObjectKey, mode: 'stream' });
  }
  if ((!criacaoState.teaserOpenerUrl || _isAttachmentLikeUrl(criacaoState.teaserOpenerUrl)) && criacaoState.teaserOpenerObjectKey) {
    targets.push({ field: 'teaserOpenerUrl', key: criacaoState.teaserOpenerObjectKey, mode: 'stream' });
  }
  if (targets.length) {
    const urls = await Promise.all(
      targets.map(async (t) => {
        if (t.mode === 'adaptive') {
          return _getAdaptivePreviewUrl(t.key, { maxHeight: 1080, maxFps: 30 });
        }
        const streamUrl = await _getVideoStreamUrl(t.key);
        if (streamUrl) return streamUrl;
        // fallback: preview adaptativo quando stream falhar
        return _getAdaptivePreviewUrl(t.key, { maxHeight: 1080, maxFps: 30 });
      })
    );
    urls.forEach((u, idx) => {
      if (!u) return;
      const target = targets[idx];
      const field = target.field;
      if (target.force) {
        if (criacaoState[field] !== u) {
          criacaoState[field] = u;
          changed = true;
        }
        return;
      }
      if (!criacaoState[field] || _isAttachmentLikeUrl(criacaoState[field])) {
        criacaoState[field] = u;
        changed = true;
      }
    });
  }
  if (_setTeaserSource(criacaoState.teaserSourceType, criacaoState.teaserSourceObjectKey, { persist: false, render: false })) {
    changed = true;
  }
  if (!criacaoState.thumbVideoObjectKey && (criacaoState.burnedObjectKey || criacaoState.teaserCombinedObjectKey)) {
    criacaoState.thumbVideoObjectKey = criacaoState.burnedObjectKey || criacaoState.teaserCombinedObjectKey;
    changed = true;
  }
  return changed;
}

function _resetCriacaoForRun(id, frames, reqData, visionAnalysis) {
  criacaoState.runId = id;
  criacaoState.frames = frames || [];
  criacaoState.framesLoading = false;
  criacaoState.framesExpectedCount = (frames || []).length;
  criacaoState.visionAnalysis = visionAnalysis || null;
  criacaoState.videoUrl = reqData.video_url || null;
  criacaoState._reqData = reqData;

  const tr = reqData.transcript || {};
  criacaoState.hasTranscript = !!(tr.text || tr.srt || tr.segments?.length);
  criacaoState.transcriptDraft = (tr.srt || '').trim();
  criacaoState.transcribeSourceLang = 'pt';
  criacaoState.transcribeTargetLang = '';
  criacaoState.transcribeAdultMode = true;
  criacaoState.transcribeIncludeVocalizations = true;

  criacaoState.postResult = null;
  criacaoState.selectedFrameIdx = null;
  criacaoState.thumbFrameIdx = 0;
  criacaoState.thumbSubtitle = '';

  criacaoState.logoProfileId = '';
  criacaoState.logoProfileName = '';
  criacaoState.logoCompanyDraftName = '';
  criacaoState.logoB64 = null;
  criacaoState.logoName = '';
  criacaoState.burnLogos = [];
  criacaoState.burnLogoActiveIdx = 0;
  criacaoState.burnLogoTargetCount = 1;
  criacaoState.logoPresetChoice = 'saved';
  criacaoState.logoX = _savedLogoPreset.logo_x ?? 97;
  criacaoState.logoY = _savedLogoPreset.logo_y ?? 97;
  criacaoState.logoScalePct = _savedLogoPreset.logo_scale_pct ?? 20;
  criacaoState.logoOpacity = _savedLogoPreset.logo_opacity ?? 85;
  criacaoState.thumbSourceB64 = null;
  criacaoState.thumbSourceFrameIdx = null;
  criacaoState.thumbSourceInfo = '';
  criacaoState.thumbVideoObjectKey = null;
  criacaoState.thumbExportFormat = 'png';
  criacaoState.thumbJpegQuality = 98;
  criacaoState.thumbOutputScale = 2;
  criacaoState.thumbCropX = 50;
  criacaoState.thumbCropY = 50;
  criacaoState.thumbZoom = 1;
  criacaoState.thumbBrightness = 100;
  criacaoState.thumbContrast = 100;
  criacaoState.thumbSaturation = 100;
  criacaoState.thumbHue = 0;
  criacaoState.thumbAutoHqTried = false;
  criacaoState.thumbElements = [];
  criacaoState.thumbSelectedElementId = null;

  criacaoState.burnedVideoUrl = null;
  criacaoState.burnedFilename = null;
  criacaoState.burnedObjectKey = null;
  criacaoState.burnedPreset = 'ultrafast';
  criacaoState.activeBurnJobId = null;
  criacaoState.burnSkipSubtitles = false;
  criacaoState.burnFontSize = 22;
  criacaoState.burnFontColor = 'white';
  criacaoState.burnSubDelay = 0;
  _revokeLogoPreviewHqUrl();
  criacaoState.logoPreviewHqFrame = null;
  criacaoState.logoPreviewHqUrl = '';
  criacaoState.logoPreviewHqInfo = '';
  criacaoState.logoPreviewHqLoading = false;
  criacaoState.logoPreviewComposited = false;
  criacaoState.logoPreviewBgVisible = true;
  criacaoState.logoPreviewHqWidth = 0;
  criacaoState.logoPreviewHqHeight = 0;

  criacaoState.teaserUrl = null;
  criacaoState.teaserObjectKey = null;
  criacaoState.teaserLogoUrl = null;
  criacaoState.teaserLogoObjectKey = null;
  criacaoState.teaserLogoFilename = null;
  criacaoState.teaserCombinedUrl = null;
  criacaoState.teaserCombinedObjectKey = null;
  const originalKey = String(reqData?.video_object_key || '').trim();
  criacaoState.teaserSourceType = originalKey ? 'original' : 'burned';
  criacaoState.teaserSourceObjectKey = originalKey || null;
  criacaoState.teaserConcatMode = 'start';
  criacaoState.teaserSelectedFrames = [];
  criacaoState.teaserSceneDurationsByFrame = {};
  criacaoState.teaserForceLogoOverlay = false;
  criacaoState.teaserLogos = [];
  criacaoState.teaserLogoActiveIdx = 0;
  criacaoState.teaserLogoAutoSeeded = false;
  criacaoState.teaserNarrationEnabled = false;
  criacaoState.teaserOriginalAudioVolume = 100;
  criacaoState.teaserNarrationVolume = 120;
  criacaoState.teaserNarrationOffsetSec = 0;
  criacaoState.teaserNarrationObjectKey = null;
  criacaoState.teaserNarrationAudioUrl = null;
  criacaoState.teaserNarrationUsed = false;
  criacaoState.teaserOpenerObjectKey = null;
  criacaoState.teaserOpenerUrl = null;
  criacaoState.teaserOpenerPosition = 'start';

  criacaoState.step = 1;
}

function _syncCriacaoDraftsFromDom() {
  const ta = qs('transcriptSrtEdit');
  if (ta) criacaoState.transcriptDraft = ta.value;
  const sub = qs('thumbSubtitleInput');
  if (sub) criacaoState.thumbSubtitle = sub.value;
  const clips = qs('teaserClips');
  const dur = qs('teaserClipDur');
  const qual = qs('teaserQuality');
  const burnQ = qs('burnQuality');
  const burnR = qs('burnResolution');
  const burnP = qs('burnPreset');
  const burnFontSize = qs('burnFontSize');
  const burnFontColor = qs('burnFontColor');
  const burnSubDelay = qs('burnSubDelay');
  const transcribeSourceLang = qs('transcribeSourceLang');
  const transcribeLang = qs('transcribeLang');
  const transcribeAdultMode = qs('transcribeAdultMode');
  const transcribeIncludeVocalizations = qs('transcribeIncludeVocalizations');
  const tScale = qs('thumbOutputScale');
  const tCropX = qs('thumbCropX');
  const tCropY = qs('thumbCropY');
  const tZoom = qs('thumbZoom');
  const tBr = qs('thumbBrightness');
  const tCt = qs('thumbContrast');
  const tSat = qs('thumbSaturation');
  const tHue = qs('thumbHue');
  const tConcat = qs('teaserConcatMode');
  const tSourceType = qs('teaserSourceType');
  const tForceLogo = qs('teaserForceLogo');
  const tNarrEnabled = qs('teaserNarrationEnabled');
  const tOrigVol = qs('teaserOriginalAudioVolume');
  const tNarrVol = qs('teaserNarrationVolume');
  const tNarrOffset = qs('teaserNarrationOffsetSec');
  const tOpenerPos = qs('teaserOpenerPosition');
  const logoCompanyName = qs('logoCompanyName');
  const logoX = qs('logoX');
  const logoY = qs('logoY');
  const logoScale = qs('logoScale');
  const logoOpacity = qs('logoOpacity');
  const burnLogoTargetCount = qs('burnLogoTargetCount');
  if (clips) criacaoState.teaserNumClips = String(_clamp(parseInt(clips.value, 10) || parseInt(criacaoState.teaserNumClips || '8', 10) || 8, 2, TEASER_MAX_NUM_CLIPS));
  if (dur) criacaoState.teaserClipDuration = String(_clamp(parseFloat(dur.value) || parseFloat(criacaoState.teaserClipDuration || '6') || 6, 2, TEASER_MAX_SCENE_DURATION_SEC));
  if (qual) criacaoState.teaserQuality = qual.value || criacaoState.teaserQuality;
  if (burnQ) criacaoState.burnedQuality = burnQ.value || criacaoState.burnedQuality;
  if (burnR) criacaoState.burnedResolution = burnR.value || criacaoState.burnedResolution;
  if (burnP) criacaoState.burnedPreset = burnP.value || criacaoState.burnedPreset;
  if (burnFontSize) criacaoState.burnFontSize = _clamp(parseInt(burnFontSize.value, 10) || criacaoState.burnFontSize || 22, 6, 72);
  if (burnFontColor) criacaoState.burnFontColor = burnFontColor.value || criacaoState.burnFontColor || 'white';
  if (burnSubDelay) criacaoState.burnSubDelay = _toNum(burnSubDelay.value, criacaoState.burnSubDelay || 0, -30, 30);
  if (transcribeSourceLang) criacaoState.transcribeSourceLang = transcribeSourceLang.value || 'pt';
  if (transcribeLang) criacaoState.transcribeTargetLang = transcribeLang.value || '';
  if (transcribeAdultMode) criacaoState.transcribeAdultMode = !!transcribeAdultMode.checked;
  if (transcribeIncludeVocalizations) criacaoState.transcribeIncludeVocalizations = !!transcribeIncludeVocalizations.checked;
  if (tScale) criacaoState.thumbOutputScale = _clamp(parseInt(tScale.value, 10) || criacaoState.thumbOutputScale, 1, 3);
  if (tCropX) criacaoState.thumbCropX = _toNum(tCropX.value, criacaoState.thumbCropX, 0, 100);
  if (tCropY) criacaoState.thumbCropY = _toNum(tCropY.value, criacaoState.thumbCropY, 0, 100);
  if (tZoom) criacaoState.thumbZoom = _toNum(tZoom.value, criacaoState.thumbZoom, 1, 3);
  if (tBr) criacaoState.thumbBrightness = _toNum(tBr.value, criacaoState.thumbBrightness, 40, 180);
  if (tCt) criacaoState.thumbContrast = _toNum(tCt.value, criacaoState.thumbContrast, 40, 180);
  if (tSat) criacaoState.thumbSaturation = _toNum(tSat.value, criacaoState.thumbSaturation, 0, 220);
  if (tHue) criacaoState.thumbHue = _toNum(tHue.value, criacaoState.thumbHue, -180, 180);
  if (tConcat) criacaoState.teaserConcatMode = tConcat.value === 'end' ? 'end' : 'start';
  if (tSourceType) criacaoState.teaserSourceType = tSourceType.value === 'original' ? 'original' : 'burned';
  if (tForceLogo) criacaoState.teaserForceLogoOverlay = !!tForceLogo.checked;
  _setTeaserSource(criacaoState.teaserSourceType, criacaoState.teaserSourceObjectKey, { persist: false, render: false });
  if (tNarrEnabled) criacaoState.teaserNarrationEnabled = !!tNarrEnabled.checked;
  if (tOrigVol) criacaoState.teaserOriginalAudioVolume = _toNum(tOrigVol.value, criacaoState.teaserOriginalAudioVolume, 0, 200);
  if (tNarrVol) criacaoState.teaserNarrationVolume = _toNum(tNarrVol.value, criacaoState.teaserNarrationVolume, 0, 200);
  if (tNarrOffset) criacaoState.teaserNarrationOffsetSec = _toNum(tNarrOffset.value, criacaoState.teaserNarrationOffsetSec, -30, 30);
  if (tOpenerPos) criacaoState.teaserOpenerPosition = tOpenerPos.value === 'end' ? 'end' : 'start';
  if (logoCompanyName) criacaoState.logoCompanyDraftName = String(logoCompanyName.value || '').slice(0, 80);
  if (logoX) criacaoState.logoX = _toNum(logoX.value, criacaoState.logoX, 0, 100);
  if (logoY) criacaoState.logoY = _toNum(logoY.value, criacaoState.logoY, 0, 100);
  if (logoScale) criacaoState.logoScalePct = _toNum(logoScale.value, criacaoState.logoScalePct, 5, 100);
  if (logoOpacity) criacaoState.logoOpacity = _toNum(logoOpacity.value, criacaoState.logoOpacity, 5, 100);
  if (burnLogoTargetCount) {
    criacaoState.burnLogoTargetCount = _clamp(parseInt(burnLogoTargetCount.value, 10) || criacaoState.burnLogoTargetCount || 1, 1, BURN_LOGO_MAX_COUNT);
  }
  const activeBurnLogo = _burnActiveLogo();
  if (activeBurnLogo) {
    activeBurnLogo.x = criacaoState.logoX;
    activeBurnLogo.y = criacaoState.logoY;
    activeBurnLogo.scale_pct = criacaoState.logoScalePct;
    activeBurnLogo.opacity = criacaoState.logoOpacity;
    activeBurnLogo.sync_main = false;
  }
  _persistWizardState();
}

function _clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

function _currentThumbFrameIdx() {
  if (criacaoState.thumbFrameIdx != null) return criacaoState.thumbFrameIdx;
  if (criacaoState.selectedFrameIdx != null) return criacaoState.selectedFrameIdx;
  return 0;
}

function _getThumbSourceForFrame(frameIdx) {
  if (criacaoState.thumbSourceB64 && criacaoState.thumbSourceFrameIdx === frameIdx) {
    return criacaoState.thumbSourceB64;
  }
  return criacaoState.frames?.[frameIdx] || '';
}

function _thumbFrameToSrc(frame) {
  const raw = String(frame || '');
  if (!raw) return '';
  if (raw.startsWith('data:image/')) return raw;
  return `data:image/jpeg;base64,${raw}`;
}

function _criacaoStepDone(step) {
  if (step === 1) return !!(criacaoState.logoB64 || criacaoState.burnedObjectKey || criacaoState.teaserObjectKey);
  if (step === 2) return !!(criacaoState.burnedVideoUrl || criacaoState.burnedObjectKey);
  if (step === 3) return !!(criacaoState.teaserUrl || criacaoState.teaserObjectKey);
  if (step === 4) return (criacaoState.thumbFrameIdx != null) || (criacaoState.selectedFrameIdx != null);
  if (step === 5) return !!criacaoState.postResult;
  return false;
}

function setCriacaoStep(step) {
  if (!criacaoState.runId) return;
  _syncCriacaoDraftsFromDom();
  const n = Math.max(1, Math.min(CRIACAO_MAX_STEP, parseInt(step, 10) || 1));
  criacaoState.step = n;
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function nextCriacaoStep() {
  setCriacaoStep(criacaoState.step + 1);
}

function prevCriacaoStep() {
  setCriacaoStep(criacaoState.step - 1);
}

async function loadCriacaoRuns() {
  try {
    const limit = parseInt(qs('criacaoLimit')?.value || '30', 10);
    const r = await apiFetch(`/runs?limit=${limit}`);
    const list = qs('criacaoRunList');
    list.innerHTML = '';
    (r.runs || []).forEach(item => {
      const el = document.createElement('div');
      el.className = 'criacao-run-item';
      el.dataset.id = item.id;
      const dateStr = fmtDate(item.created_at);
      const rawFilename = item.original_filename || _cleanFilename(item.video_object_key || '');
      const displayName = rawFilename || ((item.id || '').slice(0, 18) + '…');
      el.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
          <div class="criacao-run-id" title="${esc(item.id || '')}">${esc(displayName)}</div>
          <button class="btn" style="font-size:10px;padding:2px 7px;color:var(--bad);border-color:rgba(255,68,85,.45);" onclick="event.stopPropagation();clearCriacaoRun('${escAttr(item.id || '')}')">Limpar</button>
        </div>
        <div class="criacao-run-date">${esc(dateStr)}</div>
        <span class="badge ${item.error ? 'bad' : 'good'}" style="margin-top:4px;">${item.error ? 'erro' : 'ok'}</span>
      `;
      el.onclick = () => selectCriacaoRun(item.id, el);
      list.appendChild(el);
    });
    _updateDeletionActionButtons();
  } catch (e) {
    toast(e.message, 'bad');
  }
}

async function selectCriacaoRun(id, rowEl) {
  document.querySelectorAll('.criacao-run-item').forEach(el => el.classList.remove('active'));
  if (rowEl) rowEl.classList.add('active');
  state.selectedCriacaoRunId = String(id || '').trim();
  _updateDeletionActionButtons();

  const reqId = (state.criacaoRequestId || 0) + 1;
  state.criacaoRequestId = reqId;
  if (state.criacaoAbort) {
    try { state.criacaoAbort.abort(); } catch (_) {}
  }
  const ac = new AbortController();
  state.criacaoAbort = ac;

  try {
    const r = await apiFetch(`/runs/${id}/wizard-data`, { signal: ac.signal });
    if (reqId !== state.criacaoRequestId) return;
    const result = _parseRunResult(r);
    const reqData = _parseRunRequest(r);
    const storageKey = String((result?.storage?.object_key || r?.video_object_key || '')).trim();
    if (!String(reqData.video_object_key || '').trim() && storageKey) reqData.video_object_key = storageKey;
    const frames = [];

    _resetCriacaoForRun(id, frames, reqData, (result.vision || {}).analysis || null);
    const expectedFrames = parseInt((result.vision || {}).frames_count || '0', 10) || 0;
    criacaoState.framesExpectedCount = expectedFrames;
    criacaoState.framesLoading = expectedFrames > 0;
    _applyWizardRemoteState(reqData.wizard_state || {});
    _applyWizardSessionState(_loadWizardSessionState(id));
    if (criacaoState.logoProfileId && (reqData.wizard_state || {}).logo_profile_layout_linked == null) {
      const sessionState = _loadWizardSessionState(id);
      if (sessionState?.logoProfileLayoutLinked == null) criacaoState.logoProfileLayoutLinked = true;
    }
    _hydrateSelectedLogoProfileIntoState();
    renderCriacaoDetail(id, frames);

    _hydrateWizardMediaUrls().then((changed) => {
      if (reqId !== state.criacaoRequestId) return;
      if (changed) renderCriacaoDetail(id, criacaoState.frames);
    }).catch(() => {});

    _loadCriacaoFramesAsync(id, reqId);
  } catch (e) {
    if (e?.name === 'AbortError' || /aborted|aborterror/i.test(String(e?.message || ''))) return;
    toast(e.message, 'bad');
  }
}

async function _loadCriacaoFramesAsync(runId, reqId = state.criacaoRequestId) {
  try {
    let frames = state.runFramesCache.get(runId);
    if (!Array.isArray(frames)) {
      const rf = await apiFetch(`/runs/${runId}/frames`);
      frames = Array.isArray(rf?.frames) ? rf.frames : [];
      state.runFramesCache.set(runId, frames);
    }
    if (reqId !== state.criacaoRequestId) return;
    if (String(criacaoState.runId || '') !== String(runId)) return;
    criacaoState.frames = frames;
    criacaoState.framesExpectedCount = frames.length;
    criacaoState.framesLoading = false;
    if (criacaoState.thumbFrameIdx == null && frames.length) criacaoState.thumbFrameIdx = 0;
    renderCriacaoDetail(runId, frames);
  } catch (e) {
    if (reqId !== state.criacaoRequestId) return;
    criacaoState.framesLoading = false;
    toast(`Erro ao carregar screenshots do run: ${e.message}`, 'bad');
  }
}

function _buildVisionHtml(va) {
  if (!va || va._refused || va._api_error || va._exception) {
    const why = va?._refused ? 'Modelo recusou análise.'
      : va?._api_error ? `Erro API: ${va._api_error}`
      : va?._exception ? `Exceção: ${va._exception}`
      : 'Análise visual não disponível para este run.';
    return `<div class="hint" style="padding:8px 0;">${why}</div>`;
  }
  const desc = va.description || '';
  const cats = (va.categories || []).map(c => `<span class="tag-chip">${esc(c)}</span>`).join('');
  const tags = (va.tags || []).map(t => `<span class="tag-chip" style="opacity:.75;">${esc(t)}</span>`).join('');
  const perf = va.performers || {};
  const perfStr = [
    perf.count != null ? `${perf.count} performer(s)` : '',
    perf.genders || '',
    perf.ethnicities_visible || '',
    perf.body_types || '',
  ].filter(Boolean).join(' · ');
  const scenes = (va.scenes || []);
  const scenesHtml = scenes.length
    ? '<ul style="margin:6px 0 0 16px;font-size:12px;">'
      + scenes.slice(0, 4).map(s =>
        `<li><strong>Frame ${s.frame_index ?? '?'}</strong>: ${esc(s.acts || '')}${s.position ? ' — ' + esc(s.position) : ''}</li>`
      ).join('')
      + (scenes.length > 4 ? `<li style="opacity:.6;">+ ${scenes.length - 4} cenas…</li>` : '')
      + '</ul>'
    : '';

  return `
    ${desc ? `<p style="font-size:13px;line-height:1.5;margin:0 0 10px;">${esc(desc)}</p>` : ''}
    ${perfStr ? `<div class="hint" style="margin-bottom:8px;">👥 ${esc(perfStr)}</div>` : ''}
    ${cats ? `<div style="margin-bottom:8px;"><strong style="font-size:11px;color:var(--muted);">CATEGORIAS</strong><br>${cats}</div>` : ''}
    ${scenesHtml}
    ${tags ? `<details style="margin-top:8px;"><summary style="font-size:11px;cursor:pointer;color:var(--muted);">SEO Tags (${(va.tags || []).length})</summary><div style="margin-top:6px;">${tags}</div></details>` : ''}
  `;
}

function _renderWizardProgress() {
  const labels = [
    '1. Logo',
    '2. Legenda',
    '3. Teaser',
    '4. Thumbnail',
    '5. Post Final',
  ];
  return `
    <div class="wizard-progress">
      ${labels.map((label, idx) => {
        const step = idx + 1;
        const active = step === criacaoState.step ? 'active' : '';
        const done = _criacaoStepDone(step) ? 'done' : '';
        return `<button class="wizard-step ${active} ${done}" onclick="setCriacaoStep(${step})">${label}</button>`;
      }).join('')}
    </div>
    <div class="wizard-nav">
      <button class="btn" onclick="prevCriacaoStep()" ${criacaoState.step <= 1 ? 'disabled' : ''}>← Anterior</button>
      <div class="hint">Passo ${criacaoState.step}/5</div>
      <button class="btn primary" onclick="nextCriacaoStep()" ${criacaoState.step >= 5 ? 'disabled' : ''}>Próximo →</button>
    </div>
  `;
}

function _renderFrameSelector({ multi = false, selected = [], singleSelected = null, onClick = 'selectCriacaoFrame' } = {}) {
  const frames = criacaoState.frames || [];
  if (!frames.length) {
    if (criacaoState.framesLoading) {
      const n = Math.max(0, parseInt(criacaoState.framesExpectedCount || '0', 10) || 0);
      return `<div class="hint">⏳ Carregando screenshots do run${n ? ` (${n} esperados)` : ''}…</div>`;
    }
    return '<div class="hint">Nenhum screenshot disponível neste run.</div>';
  }
  return `
    <div class="wizard-frames-grid">
      ${frames.map((f, i) => {
        const isSel = multi ? selected.includes(i) : (singleSelected === i);
        return `
          <button class="wizard-frame ${isSel ? 'selected' : ''}" onclick="${onClick}(${i})" title="Frame ${i}">
            <img src="data:image/jpeg;base64,${f}" alt="frame ${i}">
            <span>Frame ${i}</span>
          </button>
        `;
      }).join('')}
    </div>
  `;
}

function _renderStepLogo() {
  const frameIdx = _currentThumbFrameIdx();
  const frame = criacaoState.frames[frameIdx] || '';
  const canContinue = true;
  const selectedProfile = _logoProfileById(criacaoState.logoProfileId);
  const burnLogos = _burnLogoList();
  const targetCount = _clamp(parseInt(criacaoState.burnLogoTargetCount || 1, 10) || 1, 1, BURN_LOGO_MAX_COUNT);
  const activeLogoIdx = burnLogos.length ? _burnActiveLogoIndex() : -1;
  const activeLogo = burnLogos.length ? burnLogos[activeLogoIdx] : null;
  const activeLogoDisabled = activeLogo ? '' : 'disabled';
  const posDisabled = ''; // position always editable regardless of logo state
  const companyDraftValue = criacaoState.logoCompanyDraftName || criacaoState.logoProfileName || '';
  const logoStatusText = burnLogos.length
    ? `✓ ${burnLogos.length}/${targetCount} logo(s) carregada(s)${criacaoState.logoProfileName ? ` · empresa: ${criacaoState.logoProfileName}` : ''}`
    : (criacaoState.logoProfileName ? `Empresa selecionada: ${criacaoState.logoProfileName}` : 'Nenhuma logo enviada.');
  const previewSrc = criacaoState.logoPreviewHqUrl || frame;
  const previewImgSrc = _framePreviewSrc(previewSrc);
  const bgClass = 'logo-preview-bg' + (criacaoState.logoPreviewBgVisible ? '' : ' hidden');
  const bgImgHtml = previewImgSrc
    ? `<img id="logoPreviewBg" class="${bgClass}" src="${esc(previewImgSrc)}" alt="preview frame">`
    : (criacaoState.framesLoading ? '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:12px;">⏳ Carregando frames…</div>' : '');
  const toggleBtnHtml = previewImgSrc
    ? `<button class="btn" id="btnToggleBg" style="font-size:11px;padding:2px 8px;" onclick="_togglePreviewBg()">${criacaoState.logoPreviewBgVisible ? 'Ocultar vídeo' : 'Mostrar vídeo'}</button>`
    : '';
  const hqBtnLabel = criacaoState.logoPreviewHqLoading ? '⏳' : (criacaoState.logoPreviewHqUrl ? '✓ HQ' : '📷 HQ');
  const hqInfoHtml = criacaoState.logoPreviewHqUrl
    ? `<span id="logoPreviewHqInfo" class="hint" style="font-size:10px;">${esc(criacaoState.logoPreviewHqInfo || 'HQ')}</span>`
    : `<span id="logoPreviewHqInfo" class="hint" style="font-size:10px;">${frame ? 'baixa res — HQ atualiza sozinho' : ''}</span>`;
  const addLogoDisabled = burnLogos.length >= Math.min(targetCount, BURN_LOGO_MAX_COUNT);
  const logoRows = burnLogos.map((lg, idx) => `
    <div class="teaser-logo-item burn-logo-item ${idx === activeLogoIdx ? 'active' : ''}" data-burn-logo-index="${idx}" onclick="selectBurnLogo(${idx})">
      <div style="display:flex;align-items:center;gap:8px;min-width:0;">
        <span class="badge" style="font-size:10px;">#${idx + 1}</span>
        <span class="hint" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px;">${esc(lg.name)}${lg.isGif ? ' (GIF)' : ''}</span>
      </div>
      <button class="btn" style="padding:2px 8px;font-size:11px;" onclick="event.stopPropagation();removeBurnLogo(${idx});">Remover</button>
    </div>
  `).join('');
  const logoOverlayHtml = burnLogos.length
    ? burnLogos.map((lg, idx) => `
      <img
        class="logo-preview-overlay burn-logo-preview-overlay ${idx === activeLogoIdx ? 'active' : ''}${criacaoState.logoPreviewComposited ? ' composited-proxy' : ''}"
        data-logo-index="${idx}"
        src="${lg.src}"
        alt="logo ${idx + 1}"
        onpointerdown="startBurnLogoDrag(event, ${idx})"
      >
    `).join('')
    : '';
  const previewWrapStyle = _previewWrapStyle();
  const activeX = activeLogo ? _toNum(activeLogo.x, criacaoState.logoX, 0, 100) : _toNum(criacaoState.logoX, 97, 0, 100);
  const activeY = activeLogo ? _toNum(activeLogo.y, criacaoState.logoY, 0, 100) : _toNum(criacaoState.logoY, 97, 0, 100);
  const activeScale = activeLogo ? _toNum(activeLogo.scale_pct, criacaoState.logoScalePct, 5, 100) : _toNum(criacaoState.logoScalePct, 20, 5, 100);
  const activeOpacity = activeLogo ? _toNum(activeLogo.opacity, criacaoState.logoOpacity, 5, 100) : _toNum(criacaoState.logoOpacity, 85, 5, 100);
  const positionPresets = [
    { label: 'Topo Esq.', x: 0, y: 0, icon: '↖' },
    { label: 'Topo', x: 50, y: 0, icon: '↑' },
    { label: 'Topo Dir.', x: 100, y: 0, icon: '↗' },
    { label: 'Esquerda', x: 0, y: 50, icon: '←' },
    { label: 'Centro', x: 50, y: 50, icon: '◎' },
    { label: 'Direita', x: 100, y: 50, icon: '→' },
    { label: 'Baixo Esq.', x: 0, y: 100, icon: '↙' },
    { label: 'Baixo', x: 50, y: 100, icon: '↓' },
    { label: 'Baixo Dir.', x: 100, y: 100, icon: '↘' },
  ];
  const positionButtonsHtml = positionPresets.map((p) => {
    const isActive = activeLogo && Math.abs(activeX - p.x) <= 1 && Math.abs(activeY - p.y) <= 1;
    return `
      <button type="button" class="logo-pos-btn ${isActive ? 'active' : ''}" onclick="_setLogoPos(${p.x}, ${p.y})" ${posDisabled} title="${escAttr(p.label)}">
        <b>${p.icon}</b>
        <span>${esc(p.label)}</span>
      </button>
    `;
  }).join('');

  return `
    <div class="detail-section card">
      <h2>Passo 1 — Adicionar Logo</h2>
      <div class="hint" style="margin-bottom:10px;">Editor avançado de logos: defina quantas marcas vai usar, suba uma por uma, posicione cada logo e salve o conjunto por empresa.</div>
      <div class="row wrap" style="gap:10px;align-items:flex-end;margin-bottom:8px;">
        <div class="col grow">
          <label>Empresa salva</label>
          <select id="logoCompanySelect" onchange="applyLogoCompany(this.value)">
            ${_renderLogoProfileOptions()}
          </select>
          <div class="hint" style="margin-top:6px;">Escolha uma empresa para reaplicar as logos armazenadas e os posicionamentos ideais automaticamente.</div>
        </div>
        <div class="col">
          <label>&nbsp;</label>
          <button class="btn" onclick="deleteSelectedLogoCompany()" ${selectedProfile ? '' : 'disabled'}>Excluir empresa</button>
        </div>
      </div>
      <div class="row wrap" style="gap:10px;align-items:flex-end;margin-bottom:8px;">
        <div class="col grow">
          <label>Nome da empresa para salvar este conjunto</label>
          <input id="logoCompanyName" type="text" value="${escAttr(companyDraftValue)}" maxlength="80" placeholder="Ex.: Empresa X" oninput="_setLogoCompanyDraft(this.value)">
          <div class="hint" style="margin-top:6px;">Envie as logos, ajuste posição/escala/opacidade de cada uma e salve uma vez. Depois basta escolher a empresa acima.</div>
        </div>
        <div class="col">
          <label>&nbsp;</label>
          <button class="btn" onclick="saveCurrentLogoCompany()" ${burnLogos.length ? '' : 'disabled'}>Salvar empresa</button>
        </div>
      </div>
      <div class="row wrap" style="gap:10px;align-items:flex-end;margin-bottom:8px;">
        <div class="col grow">
          <label>Preset de posição/escala/opacidade</label>
          <select id="logoPresetSelect" onchange="applyLogoPreset(this.value)">
            ${_renderLogoPresetOptions()}
          </select>
        </div>
        <div class="col">
          <label>&nbsp;</label>
          <button class="btn" onclick="saveCurrentLogoPreset()">Salvar atual como padrão</button>
        </div>
      </div>
      <div class="row wrap" style="gap:10px;align-items:flex-end;">
        <div class="col">
          <label>Quantidade de logos</label>
          <input id="burnLogoTargetCount" type="number" min="1" max="${BURN_LOGO_MAX_COUNT}" value="${targetCount}" onchange="setBurnLogoTargetCount(this.value)" style="width:90px;">
        </div>
        <div class="col grow">
          <label>Adicionar logo (${burnLogos.length}/${targetCount})</label>
          <input type="file" id="burnLogoInput" accept="image/*,.gif,.svg" onchange="loadBurnLogo(this)" ${addLogoDisabled ? 'disabled' : ''}>
          <div id="burnLogoStatus" class="hint" style="margin-top:6px;">${esc(logoStatusText)}</div>
        </div>
        <div class="col">
          <label>&nbsp;</label>
          <button class="btn" onclick="clearBurnLogos()" ${burnLogos.length ? '' : 'disabled'}>Limpar logos</button>
        </div>
      </div>
      ${logoRows ? `<div style="margin-top:8px;display:grid;gap:6px;">${logoRows}</div>` : ''}

      <div class="logo-studio ${activeLogo ? '' : 'is-disabled'}">
        <div class="logo-stage-card">
          <div class="logo-studio-head">
            <div>
              <strong>Preview de posicionamento</strong>
              <span>${activeLogo ? `arraste a logo #${activeLogoIdx + 1} direto no vídeo` : 'adicione uma logo para editar'}</span>
            </div>
            <div class="logo-stage-actions">
              ${toggleBtnHtml}
              <button class="btn" id="btnLoadHqLogoPreview" onclick="loadLogoPreviewHqFrame()">${hqBtnLabel}</button>
              ${hqInfoHtml}
            </div>
          </div>
          <div class="logo-preview-wrap logo-stage-preview" id="logoPreviewWrap" style="${previewWrapStyle}">
            ${bgImgHtml}
            ${logoOverlayHtml}
          </div>
          <div class="logo-stage-footer">
            <span>Use o mouse para arrastar, ou ajuste com precisão no painel ao lado.</span>
            <span id="logoXYReadout">X ${activeX.toFixed(1)}% · Y ${activeY.toFixed(1)}%</span>
          </div>
        </div>

        <div class="logo-control-card">
          <div class="logo-control-head">
            <div>
              <strong>${activeLogo ? `Logo ativa #${activeLogoIdx + 1}` : 'Nenhuma logo ativa'}</strong>
              <span>${activeLogo ? esc(activeLogo.name) : 'Envie ou selecione uma logo para liberar os controles.'}</span>
            </div>
            <button class="btn" onclick="saveCurrentLogoCompany()" ${burnLogos.length ? '' : 'disabled'}>Salvar empresa</button>
          </div>

          <div class="logo-control-block">
            <label>Posição rápida</label>
            <div class="logo-pos-grid">
              ${positionButtonsHtml}
            </div>
          </div>

          <div class="logo-control-block">
            <label>Ajuste fino</label>
            <div class="logo-nudge-pad">
              <span></span>
              <button class="logo-nudge-btn" onclick="nudgeLogo(0,-0.25)" ${posDisabled}>↑ fino</button>
              <span></span>
              <button class="logo-nudge-btn" onclick="nudgeLogo(-0.25,0)" ${posDisabled}>← fino</button>
              <button class="logo-nudge-btn strong" onclick="_setLogoPos(50,50)" ${posDisabled}>Centro</button>
              <button class="logo-nudge-btn" onclick="nudgeLogo(0.25,0)" ${posDisabled}>fino →</button>
              <span></span>
              <button class="logo-nudge-btn" onclick="nudgeLogo(0,0.25)" ${posDisabled}>↓ fino</button>
              <span></span>
            </div>
            <div class="logo-nudge-row">
              <button class="btn" onclick="nudgeLogo(-1,0)" ${posDisabled}>← 1%</button>
              <button class="btn" onclick="nudgeLogo(1,0)" ${posDisabled}>1% →</button>
              <button class="btn" onclick="nudgeLogo(0,-1)" ${posDisabled}>↑ 1%</button>
              <button class="btn" onclick="nudgeLogo(0,1)" ${posDisabled}>↓ 1%</button>
            </div>
          </div>

          <div class="logo-control-block">
            <label>Coordenadas e estilo</label>
            <div class="logo-field-grid">
              <div>
                <span>X</span>
                <input id="logoXNum" type="number" min="0" max="100" step="0.1" value="${activeX.toFixed(1)}" oninput="_setLogoPos(parseFloat(this.value), undefined, {persist:false, refreshHq:false, redrawThumb:false})" onchange="_commitLogoLayoutChange()" ${posDisabled}>
              </div>
              <div>
                <span>Y</span>
                <input id="logoYNum" type="number" min="0" max="100" step="0.1" value="${activeY.toFixed(1)}" oninput="_setLogoPos(undefined, parseFloat(this.value), {persist:false, refreshHq:false, redrawThumb:false})" onchange="_commitLogoLayoutChange()" ${posDisabled}>
              </div>
              <div>
                <span>Tamanho</span>
                <input id="logoScaleNum" type="number" min="5" max="100" step="0.1" value="${activeScale.toFixed(1)}" oninput="_setLogoStyle(parseFloat(this.value), undefined, {persist:false, refreshHq:false, redrawThumb:false})" onchange="_commitLogoLayoutChange()" ${activeLogoDisabled}>
              </div>
              <div>
                <span>Opacidade</span>
                <input id="logoOpacityNum" type="number" min="5" max="100" step="1" value="${activeOpacity.toFixed(0)}" oninput="_setLogoStyle(undefined, parseFloat(this.value), {persist:false, refreshHq:false, redrawThumb:false})" onchange="_commitLogoLayoutChange()" ${activeLogoDisabled}>
              </div>
            </div>
          </div>

          <div class="logo-control-block">
            <div class="logo-slider-row">
              <label>Horizontal <b id="logoXVal">${activeX.toFixed(1)}%</b></label>
              <input id="logoX" type="range" min="0" max="100" step="0.1" value="${activeX}" oninput="_setLogoPos(undefined, undefined, {persist:false, refreshHq:false, redrawThumb:false})" onchange="_commitLogoLayoutChange()" ${posDisabled}>
            </div>
            <div class="logo-slider-row">
              <label>Vertical <b id="logoYVal">${activeY.toFixed(1)}%</b></label>
              <input id="logoY" type="range" min="0" max="100" step="0.1" value="${activeY}" oninput="_setLogoPos(undefined, undefined, {persist:false, refreshHq:false, redrawThumb:false})" onchange="_commitLogoLayoutChange()" ${posDisabled}>
            </div>
            <div class="logo-slider-row">
              <label>Tamanho (% da largura do vídeo) <b id="logoScaleVal">${activeScale.toFixed(1)}%</b></label>
              <input id="logoScale" type="range" min="5" max="100" step="0.1" value="${activeScale}" oninput="_setLogoStyle(undefined, undefined, {persist:false, refreshHq:false, redrawThumb:false})" onchange="_commitLogoLayoutChange()" ${activeLogoDisabled}>
            </div>
            <div class="logo-slider-row">
              <label>Opacidade <b id="logoOpacityVal">${activeOpacity.toFixed(0)}%</b></label>
              <input id="logoOpacity" type="range" min="5" max="100" step="1" value="${activeOpacity}" oninput="_setLogoStyle(undefined, undefined, {persist:false, refreshHq:false, redrawThumb:false})" onchange="_commitLogoLayoutChange()" ${activeLogoDisabled}>
            </div>
          </div>
        </div>
      </div>

      <div class="row" style="margin-top:12px;">
        <button class="btn primary" onclick="setCriacaoStep(2)" ${canContinue ? '' : 'disabled'}>Continuar para Legenda</button>
      </div>
    </div>
  `;
}

function _renderBurnResultHtml() {
  if (!criacaoState.burnedVideoUrl && !criacaoState.burnedObjectKey) return '';
  const videoStyle = _burnResultVideoStyle();
  return `
    <div style="margin-top:10px;">
      <div style="margin-bottom:8px;font-size:12px;color:var(--good);">✓ Vídeo legendado pronto${criacaoState.burnedObjectKey ? '' : ' (URL expirada)'}</div>
      ${criacaoState.burnedWarning ? `<div class="hint" style="margin-bottom:8px;color:var(--muted);">⚠ ${esc(criacaoState.burnedWarning)}</div>` : ''}
      ${criacaoState.burnedVideoUrl ? `<video controls playsinline preload="metadata" style="${videoStyle}margin-bottom:10px;" src="${criacaoState.burnedVideoUrl}"></video>` : `<div class="hint" style="margin-bottom:10px;">URL do vídeo expirou — use "⬇ Baixar" para gerar novo link.</div>`}
      <div class="row" style="gap:8px;flex-wrap:wrap;">
        ${criacaoState.burnedObjectKey ? '<button class="btn primary" onclick="downloadBurnedVideo()">⬇ Baixar vídeo legendado</button>' : ''}
        <button class="btn" onclick="burnSubtitles()">↺ Reprocessar</button>
        ${criacaoState.burnedObjectKey ? '<button class="btn" style="color:var(--bad);border-color:var(--bad);" onclick="deleteBurnedVideo()">🗑 Deletar</button>' : ''}
      </div>
    </div>
  `;
}

function _renderStepLegenda(runId) {
  const canGoTeaser = true;
  const srcLang = criacaoState.transcribeSourceLang || 'pt';
  const targetLang = criacaoState.transcribeTargetLang || '';
  const subtitlePreviewFrameIdx = criacaoState.selectedFrameIdx ?? 0;
  const subtitlePreviewFrame = criacaoState.frames?.[subtitlePreviewFrameIdx] || '';
  const subtitlePreviewBg = subtitlePreviewFrame
    ? `background-image:linear-gradient(180deg,rgba(0,0,0,.10),rgba(0,0,0,.75)),url('data:image/jpeg;base64,${subtitlePreviewFrame}');background-size:cover;background-position:center;`
    : `background:radial-gradient(circle at 20% 20%,rgba(32,213,255,.26),transparent 34%),linear-gradient(135deg,#151827,#05060b 72%);`;
  return `
    <div class="detail-section card">
      <h2>Passo 2 — Gerar Vídeo Legendado</h2>
      <div class="hint" style="margin-bottom:10px;">Transcreva/edite a legenda e gere o vídeo final com logo queimada.</div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px;margin-bottom:10px;">
        <div class="col">
          <label>Idioma falado no vídeo</label>
          <select id="transcribeSourceLang" style="padding:5px 8px;border-radius:6px;background:var(--card);color:var(--text);border:1px solid var(--line);font-size:13px;width:100%;" onchange="criacaoState.transcribeSourceLang=this.value;_persistWizardState();">
            <option value="pt" ${srcLang === 'pt' ? 'selected' : ''}>Português (recomendado)</option>
            <option value="en" ${srcLang === 'en' ? 'selected' : ''}>English</option>
            <option value="es" ${srcLang === 'es' ? 'selected' : ''}>Español</option>
            <option value="fr" ${srcLang === 'fr' ? 'selected' : ''}>Français</option>
            <option value="de" ${srcLang === 'de' ? 'selected' : ''}>Deutsch</option>
            <option value="it" ${srcLang === 'it' ? 'selected' : ''}>Italiano</option>
            <option value="ja" ${srcLang === 'ja' ? 'selected' : ''}>日本語</option>
            <option value="zh" ${srcLang === 'zh' ? 'selected' : ''}>中文</option>
            <option value="auto" ${srcLang === 'auto' ? 'selected' : ''}>Auto (risco maior)</option>
          </select>
        </div>
        <div class="col">
          <label>Traduzir legenda para</label>
          <select id="transcribeLang" style="padding:5px 8px;border-radius:6px;background:var(--card);color:var(--text);border:1px solid var(--line);font-size:13px;width:100%;" onchange="onTranslateLangChange()">
            <option value="" ${!targetLang ? 'selected' : ''}>Não traduzir</option>
            <option value="pt" ${targetLang === 'pt' ? 'selected' : ''}>Português</option>
            <option value="en" ${targetLang === 'en' ? 'selected' : ''}>English</option>
            <option value="es" ${targetLang === 'es' ? 'selected' : ''}>Español</option>
            <option value="fr" ${targetLang === 'fr' ? 'selected' : ''}>Français</option>
            <option value="de" ${targetLang === 'de' ? 'selected' : ''}>Deutsch</option>
            <option value="it" ${targetLang === 'it' ? 'selected' : ''}>Italiano</option>
            <option value="ja" ${targetLang === 'ja' ? 'selected' : ''}>日本語</option>
            <option value="zh" ${targetLang === 'zh' ? 'selected' : ''}>中文</option>
          </select>
        </div>
      </div>

      <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px;">
        <button class="btn primary" onclick="reTranscribe('auto')" title="Modo conservador/local: não inventa fala quando o áudio não está claro">⚡ Auto estrito</button>
        <button class="btn primary" onclick="reTranscribe('whisper_sync')" title="Faster-Whisper premium: timestamps por palavra, sem pós-processamento LLM">Whisper Sync</button>
        <button class="btn primary" onclick="reTranscribe('deepgram')" title="Deepgram Nova-2: timestamps por palavra, melhor para sincronia de legenda">Deepgram Sync</button>
        <button class="btn" onclick="reTranscribe('assemblyai')" title="AssemblyAI Universal-3 Pro → Universal-2">AssemblyAI</button>
        <button class="btn" onclick="reTranscribe('groq')" title="OpenRouter STT usando token:openrouter">OpenRouter STT</button>
        <button class="btn" onclick="reTranscribe('openai')" title="OpenAI Whisper">OpenAI</button>
        <button class="btn" onclick="reTranscribe('local')" title="Faster-Whisper local (CPU)">🖥 Local</button>
        <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);">
          <input id="transcribeAdultMode" type="checkbox" ${criacaoState.transcribeAdultMode !== false ? 'checked' : ''} onchange="criacaoState.transcribeAdultMode=!!this.checked;_persistWizardState();">
          Adulto sem censura
        </label>
        <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);">
          <input id="transcribeIncludeVocalizations" type="checkbox" ${criacaoState.transcribeIncludeVocalizations !== false ? 'checked' : ''} onchange="criacaoState.transcribeIncludeVocalizations=!!this.checked;_persistWizardState();">
          Gemidos claros
        </label>
        <span class="hint">Para queimar legenda, prefira Whisper Sync ou Deepgram Sync: ambos usam timestamps reais. OpenRouter pode acertar vocabulário, mas o tempo é estimado.</span>
      </div>

      <div class="srt-editor-wrap">
        <!-- Toolbar -->
        <div class="srt-editor-toolbar">
          <button class="btn" style="font-size:12px;padding:3px 8px;" onclick="_srtToggleFindReplace()" title="Buscar e substituir (Ctrl+H)">🔍 Buscar / Substituir</button>
          <div style="width:1px;height:18px;background:var(--line2);margin:0 2px;"></div>
          <button class="btn" style="font-size:12px;padding:3px 8px;" onclick="_srtQuickFix('fillers')" title="Remove uh, um, ah, hmm, né, tipo…">✂ Fillers</button>
          <button class="btn" style="font-size:12px;padding:3px 8px;" onclick="_srtQuickFix('trim_blank')" title="Remove linhas em branco extras">⬜ Espaços</button>
          <button class="btn" style="font-size:12px;padding:3px 8px;" onclick="_srtQuickFix('renumber')" title="Renumera as entradas SRT sequencialmente"># Renumerar</button>
          <span id="srtStats" class="srt-stats">—</span>
        </div>

        <!-- Painel Find & Replace -->
        <div class="srt-find-panel" id="srtFindPanel">
          <div class="srt-find-row">
            <span style="font-size:11px;color:var(--muted);min-width:70px;">Buscar:</span>
            <input id="srtFindInput" class="srt-find-input" placeholder="texto a buscar…" oninput="_srtFindChange()" onkeydown="_srtFindKey(event)">
            <span id="srtMatchCount" class="srt-match-count"></span>
            <button class="btn" style="padding:3px 7px;font-size:13px;" onclick="_srtFindPrev()" title="Anterior (Shift+F3)">↑</button>
            <button class="btn" style="padding:3px 7px;font-size:13px;" onclick="_srtFindNext()" title="Próximo (F3 / Enter)">↓</button>
            <label class="srt-find-opt"><input type="checkbox" id="srtMatchCase" onchange="_srtFindChange()"> Aa</label>
            <label class="srt-find-opt"><input type="checkbox" id="srtWholeWord" onchange="_srtFindChange()"> \\b</label>
            <button class="btn" style="padding:3px 7px;font-size:12px;margin-left:auto;" onclick="_srtToggleFindReplace(false)">✕</button>
          </div>
          <div class="srt-find-row">
            <span style="font-size:11px;color:var(--muted);min-width:70px;">Substituir:</span>
            <input id="srtReplaceInput" class="srt-find-input" placeholder="substituir por…" onkeydown="_srtReplaceKey(event)">
            <button class="btn" style="padding:3px 10px;font-size:12px;" onclick="_srtReplaceCurrent()">Substituir</button>
            <button class="btn primary" style="padding:3px 10px;font-size:12px;" onclick="_srtReplaceAll()">Substituir tudo</button>
          </div>
        </div>

        <!-- Textarea -->
        <textarea
          id="transcriptSrtEdit"
          class="srt-editor-textarea"
          placeholder="SRT aparece aqui após transcrição. Edite livremente."
          spellcheck="false"
          autocorrect="off"
          autocapitalize="off"
        ></textarea>

        <!-- Status bar -->
        <div class="srt-statusbar">
          <span id="srtCursor">Linha 1, Col 1</span>
          <span id="transcriptStatus">${criacaoState.hasTranscript ? 'Legenda pronta para uso.' : 'Sem legenda ainda.'}</span>
        </div>
      </div>

      <div class="row" style="gap:8px;margin-top:8px;flex-wrap:wrap;">
        <button class="btn primary" onclick="saveTranscript()">💾 Salvar SRT</button>
        <a class="btn" href="/runs/${runId}/srt" download>⬇ Baixar SRT</a>
      </div>

      <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--line);">
        <div class="row wrap" style="gap:8px;margin-bottom:8px;align-items:flex-end;">
          <div class="col">
            <label>Tamanho da legenda</label>
            <input id="burnFontSize" type="number" value="${criacaoState.burnFontSize || 22}" min="6" max="72" style="width:70px;" oninput="updateSubtitlePreview()" onchange="_syncCriacaoDraftsFromDom();updateSubtitlePreview();">
          </div>
          <div class="col">
            <label>Cor</label>
            <select id="burnFontColor" onchange="_syncCriacaoDraftsFromDom();updateSubtitlePreview();">
              <option value="white" ${(criacaoState.burnFontColor || 'white') === 'white' ? 'selected' : ''}>Branco</option>
              <option value="yellow" ${criacaoState.burnFontColor === 'yellow' ? 'selected' : ''}>Amarelo</option>
              <option value="cyan" ${criacaoState.burnFontColor === 'cyan' ? 'selected' : ''}>Ciano</option>
              <option value="orange" ${criacaoState.burnFontColor === 'orange' ? 'selected' : ''}>Laranja</option>
              <option value="black" ${criacaoState.burnFontColor === 'black' ? 'selected' : ''}>Preto</option>
            </select>
          </div>
          <div class="col">
            <label>Delay (s)</label>
            <input id="burnSubDelay" type="number" value="${criacaoState.burnSubDelay || 0}" step="0.5" style="width:80px;" oninput="updateSubtitlePreview()" onchange="_syncCriacaoDraftsFromDom();updateSubtitlePreview();">
          </div>
          <div class="col">
            <label>Resolução</label>
            <select id="burnResolution" onchange="criacaoState.burnedResolution=this.value;_persistWizardState();_ensureLogoPreviewHq(true);">
              <option value="1080" ${criacaoState.burnedResolution === '1080' ? 'selected' : ''}>1080p</option>
              <option value="720" ${criacaoState.burnedResolution === '720' ? 'selected' : ''}>720p</option>
              <option value="2160" ${criacaoState.burnedResolution === '2160' ? 'selected' : ''}>4K (2160p)</option>
              <option value="0" ${criacaoState.burnedResolution === '0' ? 'selected' : ''}>Original</option>
            </select>
          </div>
          <div class="col">
            <label>Qualidade</label>
            <select id="burnQuality">
              <option value="26" ${criacaoState.burnedQuality === '26' ? 'selected' : ''}>Boa (CRF 26)</option>
              <option value="30" ${criacaoState.burnedQuality === '30' ? 'selected' : ''}>Leve (CRF 30)</option>
              <option value="20" ${criacaoState.burnedQuality === '20' ? 'selected' : ''}>Alta (CRF 20)</option>
            </select>
          </div>
          <div class="col">
            <label>Velocidade</label>
            <select id="burnPreset">
              <option value="ultrafast" ${(!criacaoState.burnedPreset || criacaoState.burnedPreset === 'ultrafast') ? 'selected' : ''}>Ultra rápido ⚡ (ultrafast) — recomendado</option>
              <option value="veryfast" ${criacaoState.burnedPreset === 'veryfast' ? 'selected' : ''}>Turbo (veryfast)</option>
              <option value="faster" ${criacaoState.burnedPreset === 'faster' ? 'selected' : ''}>Mais rápido (faster)</option>
              <option value="fast" ${criacaoState.burnedPreset === 'fast' ? 'selected' : ''}>Rápido (fast)</option>
              <option value="medium" ${criacaoState.burnedPreset === 'medium' ? 'selected' : ''}>Equilibrado (medium)</option>
            </select>
          </div>
        </div>

        <div style="margin:10px 0 12px;padding:12px;border:1px solid rgba(32,213,255,.22);border-radius:14px;background:rgba(5,8,14,.45);">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;">
            <strong style="font-size:12px;letter-spacing:.5px;text-transform:uppercase;color:var(--muted);">Preview da legenda</strong>
            <span id="subtitlePreviewHint" class="hint">Ajuste tamanho/cor antes de queimar.</span>
          </div>
          <div id="subtitlePreviewScreen" style="position:relative;overflow:hidden;border-radius:12px;border:1px solid rgba(255,255,255,.10);aspect-ratio:16/9;max-height:260px;${subtitlePreviewBg}">
            <div style="position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,0) 46%,rgba(0,0,0,.72) 100%);"></div>
            <div id="subtitlePreviewText" style="position:absolute;left:5%;right:5%;bottom:7%;text-align:center;font-family:Arial,Helvetica,sans-serif;font-weight:800;line-height:1.18;padding:0 8px;word-break:normal;white-space:normal;">
              Preview da legenda na tela
            </div>
          </div>
        </div>

        <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center;">
          <button class="btn run" style="padding:10px 18px;font-size:13.5px;" onclick="triggerBurnSubs()" ${criacaoState.hasTranscript || criacaoState.burnSkipSubtitles ? '' : 'disabled'}>
            ${criacaoState.burnSkipSubtitles ? '▣ Queimar só logo (sem legenda)' : '▣ Gerar versão legendada com logo'}
          </button>
          <button class="btn${criacaoState.burnSkipSubtitles ? ' primary' : ''}" onclick="criacaoState.burnSkipSubtitles=!criacaoState.burnSkipSubtitles;_persistWizardState();renderCriacaoDetail(criacaoState.runId,criacaoState.frames);" style="${criacaoState.burnSkipSubtitles ? 'background:var(--warn,#c47a00);' : ''}">
            ${criacaoState.burnSkipSubtitles ? '✓ Sem legenda' : 'Sem legenda'}
          </button>
          ${(!criacaoState.hasTranscript && !criacaoState.burnSkipSubtitles) ? '<span class="hint">Transcreva primeiro ou clique em "Sem legenda"</span>' : ''}
        </div>
        <div class="row" style="gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:10px;padding:10px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(255,255,255,.03);">
          <div class="col">
            <label>Prévia no minuto</label>
            <input id="burnPreviewMinute" type="number" value="0" min="0" step="0.5" style="width:90px;">
          </div>
          <button class="btn" onclick="burnDiagnoseSubtitles()">🩺 Diagnosticar SRT</button>
          <button class="btn primary" onclick="burnQuickPreview()">⚡ Prévia rápida 60s</button>
          <span class="hint" style="align-self:center;">Use antes da queima completa para testar sincronia sem esperar horas.</span>
        </div>
        <div id="burnPreviewArea" style="margin-top:8px;"></div>
        <button class="btn" onclick="loadExistingBurnedVideos('run')">📁 Usar vídeo legendado deste run</button>
        <button class="btn" onclick="loadExistingBurnedVideos('all')">🗂 Buscar em todos os legendados</button>
        <span class="hint" style="width:100%;">Dica: selecione um vídeo legendado já pronto para continuar sem gerar de novo.</span>
        <div id="burnSubsArea" style="margin-top:10px;">${_renderBurnResultHtml()}</div>
        <div id="burnSelectArea" style="margin-top:8px;"></div>
      </div>

      <div class="row" style="margin-top:12px;">
        <button id="btnGoTeaser" class="btn primary" onclick="setCriacaoStep(3)" ${canGoTeaser ? '' : 'disabled'}>Continuar para Teaser</button>
      </div>
    </div>
  `;
}

function _renderTeaserResultHtml() {
  if (!criacaoState.teaserUrl) return '';
  const modeLabel = criacaoState.teaserConcatMode === 'end' ? 'no final' : 'no início';
  const narUsed = !!criacaoState.teaserNarrationUsed;
  const openerUsed = !!criacaoState.teaserOpenerObjectKey;
  const openerLabel = criacaoState.teaserOpenerPosition === 'end' ? 'final' : 'início';
  return `
    <div>
      <div style="margin-bottom:8px;font-size:12px;color:var(--good);">✓ Teaser gerado com sucesso!</div>
      ${narUsed ? '<div class="hint" style="margin-bottom:8px;color:var(--good);">🔊 Narração aplicada.</div>' : ''}
      ${openerUsed ? `<div class="hint" style="margin-bottom:8px;color:var(--good);">🎞 Vídeo de abertura aplicado no ${openerLabel}.</div>` : ''}
      <video controls playsinline preload="metadata" style="width:100%;max-height:280px;border-radius:8px;background:#000;display:block;margin-bottom:10px;" src="${criacaoState.teaserUrl}"></video>
      <div class="row" style="gap:8px;flex-wrap:wrap;">
        <button class="btn primary" onclick="downloadTeaserVideo()">⬇ Baixar Teaser</button>
        <button class="btn" onclick="burnLogoOnTeaser()">🔥 Queimar logo no teaser</button>
        <button class="btn" onclick="deleteTeaserVideo()">🗑 Excluir teaser</button>
        <button class="btn" onclick="prependTeaser()" ${criacaoState.burnedObjectKey ? '' : 'disabled'}>🔗 Inserir teaser ${modeLabel}</button>
      </div>
      <div id="teaserLogoBurnArea" style="margin-top:8px;"></div>
      ${criacaoState.teaserCombinedUrl ? `
        <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--line);">
          <div style="margin-bottom:6px;font-size:12px;color:var(--good);">✓ Vídeo completo (teaser + legendado)</div>
          <video controls playsinline preload="metadata" style="width:100%;max-height:280px;border-radius:8px;background:#000;display:block;margin-bottom:10px;" src="${criacaoState.teaserCombinedUrl}"></video>
          <button class="btn primary" onclick="downloadCombinedVideo()">⬇ Baixar vídeo completo</button>
        </div>
      ` : ''}
      ${criacaoState.teaserLogoUrl ? `
        <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--line);">
          <div style="margin-bottom:6px;font-size:12px;color:var(--good);">✓ Teaser com logo queimada</div>
          <video controls playsinline preload="metadata" style="width:100%;max-height:280px;border-radius:8px;background:#000;display:block;margin-bottom:10px;" src="${criacaoState.teaserLogoUrl}"></video>
          <div class="row" style="gap:8px;flex-wrap:wrap;">
            <button class="btn primary" onclick="downloadTeaserLogoVideo()">⬇ Baixar teaser com logo</button>
            <button class="btn" onclick="useTeaserLogoAsMain()">Usar este teaser</button>
            <button class="btn" onclick="deleteTeaserLogoVideo()">🗑 Excluir teaser com logo</button>
          </div>
        </div>
      ` : ''}
    </div>
  `;
}

function _renderTeaserNarrationAudioHtml() {
  const key = criacaoState.teaserNarrationObjectKey || '';
  const url = criacaoState.teaserNarrationAudioUrl || '';
  if (!key && !url) {
    return '<div class="hint">Nenhum áudio de narração selecionado.</div>';
  }
  return `
    <div style="margin-top:8px;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg2);">
      <div class="hint" style="margin-bottom:6px;">Áudio atual: ${esc(key ? _burnFileNameFromKey(key) : 'narration.mp3')}</div>
      ${url ? `<audio controls preload="none" style="width:100%;max-width:520px;"><source src="${url}" type="audio/mpeg"></audio>` : '<div class="hint">Áudio salvo, mas sem URL de preview ainda.</div>'}
      <div class="row wrap" style="gap:6px;margin-top:8px;">
        <button class="btn" onclick="clearTeaserNarrationAudio()">Remover áudio</button>
      </div>
    </div>
  `;
}

function _renderTeaserOpenerHtml() {
  const key = String(criacaoState.teaserOpenerObjectKey || '').trim();
  const url = String(criacaoState.teaserOpenerUrl || '').trim();
  if (!key && !url) {
    return '<div class="hint">Nenhum vídeo de abertura selecionado.</div>';
  }
  return `
    <div style="margin-top:8px;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg2);">
      <div class="hint" style="margin-bottom:6px;">Abertura atual: ${esc(key ? _burnFileNameFromKey(key) : 'video-abertura.mp4')}</div>
      ${url ? `<video controls playsinline preload="metadata" style="width:100%;max-width:520px;border-radius:8px;background:#000;"><source src="${url}" type="video/mp4"></video>` : '<div class="hint">Vídeo salvo, mas sem URL de preview ainda.</div>'}
      <div class="row wrap" style="gap:6px;margin-top:8px;">
        <button class="btn" onclick="clearTeaserOpenerVideo()">Remover abertura</button>
      </div>
    </div>
  `;
}

function _renderStepTeaser() {
  if (
    !criacaoState.teaserLogoAutoSeeded &&
    (!Array.isArray(criacaoState.teaserLogos) || !criacaoState.teaserLogos.length) &&
    criacaoState.logoB64
  ) {
    criacaoState.teaserLogos = [_teaserNormalizeLogo({
      name: criacaoState.logoName || 'logo-passo-1',
      src: criacaoState.logoB64,
      mime: /^data:image\/gif/i.test(String(criacaoState.logoB64 || '')) ? 'image/gif' : 'image/png',
      x: criacaoState.logoX,
      y: criacaoState.logoY,
      scale_pct: criacaoState.logoScalePct,
      opacity: criacaoState.logoOpacity,
      sync_main: true,
    })];
    criacaoState.teaserLogoActiveIdx = 0;
    criacaoState.teaserLogoAutoSeeded = true;
    _persistWizardState();
  }
  if (_syncInheritedTeaserLogosFromMain()) _persistWizardState();
  _setTeaserSource(criacaoState.teaserSourceType, criacaoState.teaserSourceObjectKey, { persist: false, render: false });
  const selected = criacaoState.teaserSelectedFrames || [];
  const sourceType = criacaoState.teaserSourceType === 'original' ? 'original' : 'burned';
  const originalSourceKey = _resolveOriginalVideoObjectKey();
  const teaserSourceKey = sourceType === 'original'
    ? (criacaoState.teaserSourceObjectKey || originalSourceKey || '')
    : (criacaoState.teaserSourceObjectKey || criacaoState.burnedObjectKey || '');
  const hasTeaserSource = !!teaserSourceKey;
  const sourceShort = teaserSourceKey
    ? _burnFileNameFromKey(teaserSourceKey)
    : (sourceType === 'original' ? 'Nenhum vídeo original disponível neste run' : 'Nenhum vídeo queimado selecionado');
  const sourceLocksLogoOff = sourceType === 'burned' && !!teaserSourceKey;
  const logoEnabled = !sourceLocksLogoOff && !!criacaoState.teaserForceLogoOverlay;
  const teaserLogos = _teaserLogoList().map(_teaserNormalizeLogo).slice(0, 6);
  criacaoState.teaserLogos = teaserLogos;
  if (criacaoState.teaserLogoActiveIdx >= teaserLogos.length) {
    criacaoState.teaserLogoActiveIdx = Math.max(0, teaserLogos.length - 1);
  }
  const activeLogoIdx = teaserLogos.length ? _teaserActiveLogoIndex() : -1;
  const activeLogo = teaserLogos.length ? teaserLogos[activeLogoIdx] : null;
  const activeLogoDisabled = activeLogo ? '' : 'disabled';
  const activeLogoLinked = !!(activeLogo && activeLogo.sync_main);
  const logoRows = teaserLogos.map((lg, idx) => `
    <div class="teaser-logo-item ${idx === activeLogoIdx ? 'active' : ''}" onclick="selectTeaserLogo(${idx})">
      <div style="display:flex;align-items:center;gap:8px;min-width:0;">
        <span class="badge" style="font-size:10px;">#${idx + 1}</span>
        <span class="hint" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px;">${esc(lg.name)}${lg.isGif ? ' (GIF)' : ''}</span>
      </div>
      <button class="btn" style="padding:2px 8px;font-size:11px;" onclick="event.stopPropagation();removeTeaserLogo(${idx});">Remover</button>
    </div>
  `).join('');
  const teaserPreviewOverlays = teaserLogos.length
    ? teaserLogos.map((lg, idx) => `
      <img
        class="logo-preview-overlay teaser-logo-preview-overlay ${idx === activeLogoIdx ? 'active' : ''}"
        data-logo-index="${idx}"
        src="${lg.src}"
        alt="logo ${idx + 1}"
        onpointerdown="startTeaserLogoDrag(event, ${idx})"
      >
    `).join('')
    : '';
  const previewFrameIdx = selected.length ? selected[0] : _currentThumbFrameIdx();
  const previewFrame = (criacaoState.frames || [])[previewFrameIdx] || '';
  const concatMode = criacaoState.teaserConcatMode === 'end' ? 'end' : 'start';
  const narEnabled = !!criacaoState.teaserNarrationEnabled;
  const narDisabled = narEnabled ? '' : 'disabled';
  const origVol = _toNum(criacaoState.teaserOriginalAudioVolume, 100, 0, 200);
  const narVol = _toNum(criacaoState.teaserNarrationVolume, 120, 0, 200);
  const narOffset = _toNum(criacaoState.teaserNarrationOffsetSec, 0, -30, 30);
  const openerPosition = criacaoState.teaserOpenerPosition === 'end' ? 'end' : 'start';
  const selectedDurRows = selected.map((idx) => `
    <div class="row wrap" style="gap:8px;align-items:center;margin-top:4px;">
      <div class="hint" style="min-width:90px;">Frame ${idx}</div>
      <input
        type="number"
        min="1"
        max="${TEASER_MAX_SCENE_DURATION_SEC}"
        step="0.5"
        value="${esc(String(_teaserSceneDurationForFrame(idx)))}"
        onchange="setTeaserFrameDuration(${idx}, this.value)"
        style="width:90px;"
      >
      <span class="hint">segundos</span>
    </div>
  `).join('');
  const plannerSceneCount = _teaserPlannerSceneCount(criacaoState.teaserNumClips, selected);
  const plannerPreview = _buildTeaserDurationPlan(
    plannerSceneCount,
    criacaoState.teaserTargetDurationMin,
    criacaoState.teaserFirstClipMin,
    criacaoState.teaserLastClipMin,
  );
  const plannerSummaryText = plannerPreview.ok
    ? `Plano: ${plannerPreview.sceneCount} cena(s), total ${_formatDurationCompact(plannerPreview.totalSec)}, média ${plannerPreview.defaultSceneSec.toFixed(1)}s por cena.`
    : plannerPreview.detail;
  const plannerSummaryColor = plannerPreview.ok ? 'var(--muted)' : 'var(--bad)';
  const previewWrapStyle = _previewWrapStyle();
  return `
    <div class="detail-section card">
      <h2>Passo 3 — Teaser Automático por Cenas</h2>
      <div class="hint" style="margin-bottom:10px;">Escolha a fonte (original/queimado), selecione cenas e ajuste duração por cena.</div>

      <div class="row wrap" style="gap:8px;align-items:flex-end;margin-bottom:10px;">
        <div class="col">
          <label>Tipo de fonte</label>
          <select id="teaserSourceType" onchange="setTeaserSourceType(this.value)">
            <option value="burned" ${sourceType === 'burned' ? 'selected' : ''}>Vídeo queimado</option>
            <option value="original" ${sourceType === 'original' ? 'selected' : ''}>Vídeo original</option>
          </select>
        </div>
        <div class="col grow">
          <label>Fonte do teaser</label>
          <div class="hint">${esc(sourceShort)}</div>
        </div>
        ${sourceType === 'burned'
          ? `
            <button class="btn" onclick="loadExistingBurnedVideosFor('teaser','run')">📁 Deste run</button>
            <button class="btn" onclick="loadExistingBurnedVideosFor('teaser','all')">🗂 Todos queimados</button>
          `
          : `
            <button class="btn" onclick="useOriginalVideoAsTeaserSource()">🎞 Usar original do run</button>
            <button class="btn" onclick="loadOriginalVideosForTeaser()">🗂 Escolher original da biblioteca</button>
          `
        }
      </div>
      <div id="teaserSelectArea" style="margin-bottom:10px;">${sourceType === 'original' ? '' : ''}</div>

      <div style="margin-bottom:10px;">
        <label>Selecione cenas baseadas nos screenshots (opcional, recomendado)</label>
        <div class="row" style="gap:8px;margin:6px 0 10px;flex-wrap:wrap;">
          <button class="btn" onclick="selectAllTeaserFrames()">Selecionar todos</button>
          <button class="btn" onclick="clearTeaserFrames()">Limpar seleção</button>
          <span class="hint">Selecionados: ${selected.length}</span>
        </div>
        ${_renderFrameSelector({ multi: true, selected, onClick: 'toggleTeaserFrame' })}
      </div>

      <div class="row wrap" style="gap:8px;margin-top:12px;align-items:flex-end;">
        <div class="col">
          <label>Nº de cenas</label>
          <input id="teaserClips" type="number" value="${esc(criacaoState.teaserNumClips)}" min="2" max="${TEASER_MAX_NUM_CLIPS}" style="width:70px;" onchange="criacaoState.teaserNumClips=this.value;updateTeaserPlannerSettings()">
        </div>
        <div class="col">
          <label>Duração por cena (s)</label>
          <input id="teaserClipDur" type="number" value="${esc(criacaoState.teaserClipDuration)}" min="2" max="${TEASER_MAX_SCENE_DURATION_SEC}" style="width:90px;" onchange="criacaoState.teaserClipDuration=this.value;_persistWizardState()">
        </div>
        <div class="col">
          <label>Qualidade</label>
          <select id="teaserQuality" onchange="criacaoState.teaserQuality=this.value;_persistWizardState()">
            <option value="26" ${criacaoState.teaserQuality === '26' ? 'selected' : ''}>Boa (CRF 26)</option>
            <option value="30" ${criacaoState.teaserQuality === '30' ? 'selected' : ''}>Leve (CRF 30)</option>
            <option value="20" ${criacaoState.teaserQuality === '20' ? 'selected' : ''}>Alta (CRF 20)</option>
          </select>
        </div>
      </div>
      <div style="margin-top:10px;padding:10px;border:1px dashed var(--line);border-radius:8px;background:var(--bg2);">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
          <input id="teaserAutoDistribute" type="checkbox" ${criacaoState.teaserAutoDistribute ? 'checked' : ''} onchange="updateTeaserPlannerSettings()">
          ⏱ Planejar teaser por minutos totais
        </label>
        <div class="hint" style="margin-top:4px;">Defina o tempo total do teaser, quanto vai na primeira parte e quanto vai na parte final. O restante é distribuído automaticamente nas cenas do meio.</div>
        <div class="row wrap" style="gap:8px;margin-top:8px;align-items:flex-end;">
          <div class="col">
            <label>Total do teaser (min)</label>
            <input id="teaserTotalMinutes" type="number" min="0.1" max="${(TEASER_MAX_TOTAL_DURATION_SEC / 60).toFixed(1)}" step="0.1" value="${esc(String(criacaoState.teaserTargetDurationMin || '11'))}" onchange="updateTeaserPlannerSettings()">
          </div>
          <div class="col">
            <label>Parte 1 (min)</label>
            <input id="teaserFirstClipMinutes" type="number" min="0" max="${(TEASER_MAX_SCENE_DURATION_SEC / 60).toFixed(1)}" step="0.1" value="${esc(String(criacaoState.teaserFirstClipMin || '1'))}" onchange="updateTeaserPlannerSettings()">
          </div>
          <div class="col">
            <label>Parte final (min)</label>
            <input id="teaserLastClipMinutes" type="number" min="0" max="${(TEASER_MAX_SCENE_DURATION_SEC / 60).toFixed(1)}" step="0.1" value="${esc(String(criacaoState.teaserLastClipMin || '1'))}" onchange="updateTeaserPlannerSettings()">
          </div>
          <button class="btn" onclick="applyTeaserDurationPlan()">Distribuir durações</button>
        </div>
        <div id="teaserAutoPlanSummary" class="hint" style="margin-top:6px;color:${plannerSummaryColor};">${esc(plannerSummaryText)}</div>
        <div class="hint" style="margin-top:4px;">Se você marcar cenas manualmente, a distribuição usa a quantidade selecionada. Sem seleção manual, usa o Nº de cenas acima.</div>
      </div>
      <div class="hint" style="margin-top:6px;">Até ${TEASER_MAX_SCENE_DURATION_SEC}s por cena. Limite seguro atual por job: ${Math.round(TEASER_MAX_TOTAL_DURATION_SEC / 60)} minutos de teaser.</div>
      ${selected.length ? `
        <div style="margin-top:10px;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--bg2);">
          <label>Duração individual por cena</label>
          <div class="hint" style="margin-top:4px;">A duração abaixo prevalece por frame selecionado. Cenas automáticas usam a duração padrão.</div>
          ${selectedDurRows}
          <div class="row wrap" style="gap:8px;margin-top:8px;">
            <button class="btn" onclick="applyDefaultTeaserDurationToSelected()">Aplicar padrão (${esc(criacaoState.teaserClipDuration)}s) em todas</button>
          </div>
        </div>
      ` : ''}

      <div style="margin-top:14px;padding:12px;border:2px solid ${logoEnabled ? 'var(--accent)' : 'var(--line)'};border-radius:8px;background:var(--bg2);opacity:${sourceLocksLogoOff ? '.84' : '1'};">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
          <div style="display:flex;align-items:center;gap:10px;cursor:${sourceLocksLogoOff ? 'not-allowed' : 'pointer'};" ${sourceLocksLogoOff ? '' : `onclick="setTeaserForceLogoOverlay(${logoEnabled ? 'false' : 'true'})"`}>
            <div style="width:42px;height:22px;border-radius:11px;background:${logoEnabled ? 'var(--accent)' : 'var(--muted)'};position:relative;transition:background .2s;flex-shrink:0;">
              <div style="position:absolute;top:3px;left:${logoEnabled ? '23px' : '3px'};width:16px;height:16px;border-radius:50%;background:#fff;transition:left .2s;"></div>
            </div>
            <strong style="font-size:14px;color:${logoEnabled ? 'var(--accent)' : 'var(--fg)'};user-select:none;">🏷 Aplicar logo no teaser</strong>
            <input id="teaserForceLogo" type="checkbox" ${logoEnabled ? 'checked' : ''} onchange="setTeaserForceLogoOverlay(this.checked)" style="display:none;" ${sourceLocksLogoOff ? 'disabled' : ''}>
          </div>
          <span class="hint" style="color:${sourceLocksLogoOff ? 'var(--good)' : (logoEnabled ? 'var(--good)' : 'var(--muted)')};">${sourceLocksLogoOff ? '✓ Fonte já é o vídeo queimado; logo extra bloqueada' : (logoEnabled ? '✓ Logo ativa no render final' : '✗ Logo desativada no render final')}</span>
        </div>
        <div class="hint" style="margin-top:6px;">${sourceLocksLogoOff ? 'O teaser usa a logo já embutida no vídeo queimado. Os controles abaixo ficam só como referência ou para um burn separado depois.' : 'Suporta múltiplas logos, incluindo GIF animado. Em vídeo já queimado pode duplicar marca.'}</div>
        <div class="row wrap" style="gap:8px;align-items:flex-end;margin-top:8px;">
          <div class="col grow">
            <label>Arquivos de logo (PNG/JPG/SVG/GIF)</label>
            <input id="teaserLogoInput" type="file" multiple accept="image/*,.gif,.svg" onchange="loadTeaserLogos(this)">
            <div class="hint" style="margin-top:6px;">${teaserLogos.length ? `${teaserLogos.length} logo(s) carregada(s)` : 'Nenhuma logo adicionada'}</div>
          </div>
          <button class="btn" onclick="addMainLogoToTeaser()" ${criacaoState.logoB64 ? '' : 'disabled'}>Usar logo do Passo 1</button>
          <button class="btn" onclick="clearAllTeaserLogos()" ${teaserLogos.length ? '' : 'disabled'}>Limpar logos</button>
        </div>
        ${logoRows ? `<div style="margin-top:8px;display:grid;gap:6px;">${logoRows}</div>` : ''}
        <div class="row wrap" style="gap:12px;align-items:flex-end;margin-top:8px;opacity:${activeLogo ? '1' : '.6'};">
          <div class="col">
            <label>Horizontal</label>
            <input type="range" min="0" max="100" step="0.1" value="${activeLogo ? activeLogo.x : 97}" oninput="setTeaserLogoField('x', this.value)" ${activeLogoDisabled}>
            <div class="hint">${activeLogo ? activeLogo.x.toFixed(1) : '0'}%</div>
          </div>
          <div class="col">
            <label>Vertical</label>
            <input type="range" min="0" max="100" step="0.1" value="${activeLogo ? activeLogo.y : 97}" oninput="setTeaserLogoField('y', this.value)" ${activeLogoDisabled}>
            <div class="hint">${activeLogo ? activeLogo.y.toFixed(1) : '0'}%</div>
          </div>
          <div class="col">
            <label>Escala (% da largura do vídeo)</label>
            <input type="range" min="5" max="100" step="0.1" value="${activeLogo ? activeLogo.scale_pct : 20}" oninput="setTeaserLogoField('scale_pct', this.value)" ${activeLogoDisabled}>
            <div class="hint">${activeLogo ? activeLogo.scale_pct.toFixed(1) : '0'}%</div>
          </div>
          <div class="col">
            <label>Opacidade</label>
            <input type="range" min="5" max="100" step="1" value="${activeLogo ? activeLogo.opacity : 85}" oninput="setTeaserLogoField('opacity', this.value)" ${activeLogoDisabled}>
            <div class="hint">${activeLogo ? activeLogo.opacity.toFixed(0) : '0'}%</div>
          </div>
        </div>
        <div class="row wrap" style="gap:10px;align-items:center;margin-top:6px;opacity:${activeLogo ? '1' : '.6'};">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
            <input type="checkbox" ${activeLogoLinked ? 'checked' : ''} onchange="setTeaserLogoSyncMain(this.checked)" ${activeLogoDisabled}>
            Vincular ao Passo 1
          </label>
          <button class="btn" onclick="syncActiveTeaserLogoFromMain()" ${activeLogoDisabled}>Sincronizar agora</button>
          <span class="hint">Passo 1: ${criacaoState.logoX.toFixed(1)}% / ${criacaoState.logoY.toFixed(1)}% · ${criacaoState.logoScalePct.toFixed(1)}% · ${criacaoState.logoOpacity.toFixed(0)}%</span>
        </div>
        <div class="row wrap" style="gap:10px;align-items:flex-end;margin-top:8px;opacity:${activeLogo ? '1' : '.6'};">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
            <input type="checkbox" ${activeLogo && activeLogo.remove_bg ? 'checked' : ''} onchange="setTeaserLogoField('remove_bg', this.checked)" ${activeLogoDisabled}>
            Remover fundo da logo
          </label>
          <div class="col">
            <label>Cor do fundo</label>
            <input type="color" value="${activeLogo ? activeLogo.bg_key_color : '#ffffff'}" onchange="setTeaserLogoField('bg_key_color', this.value)" ${activeLogoDisabled}>
          </div>
          <div class="col">
            <label>Sensibilidade</label>
            <input type="range" min="0.01" max="0.60" step="0.01" value="${activeLogo ? activeLogo.bg_similarity : 0.18}" oninput="setTeaserLogoField('bg_similarity', this.value)" ${activeLogoDisabled}>
            <div class="hint">${activeLogo ? activeLogo.bg_similarity.toFixed(2) : '0.18'}</div>
          </div>
          <div class="col">
            <label>Suavização</label>
            <input type="range" min="0.00" max="0.40" step="0.01" value="${activeLogo ? activeLogo.bg_blend : 0.08}" oninput="setTeaserLogoField('bg_blend', this.value)" ${activeLogoDisabled}>
            <div class="hint">${activeLogo ? activeLogo.bg_blend.toFixed(2) : '0.08'}</div>
          </div>
        </div>
        <div class="row" style="align-items:center;gap:10px;margin:8px 0 6px;">
          <label style="margin:0;">Preview da logo no teaser</label>
          ${previewFrame ? `<button class="btn" id="btnToggleTeaserBg" style="font-size:11px;padding:2px 8px;" onclick="_toggleTeaserPreviewBg()">Mostrar vídeo</button>` : ''}
        </div>
        <div class="logo-preview-wrap" id="teaserLogoPreviewWrap" style="${previewWrapStyle}">
          ${previewFrame ? `<img id="teaserLogoPreviewBg" class="logo-preview-bg hidden" src="data:image/jpeg;base64,${previewFrame}" alt="preview frame">` : ''}
          ${teaserPreviewOverlays}
        </div>
      </div>

      <div style="margin-top:10px;padding:10px;border:1px dashed var(--line);border-radius:8px;">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
          <input id="teaserNarrationEnabled" type="checkbox" ${narEnabled ? 'checked' : ''} onchange="toggleTeaserNarrationEnabled(this.checked)">
          🔊 Adicionar narração por áudio (opcional)
        </label>
        <div class="hint" style="margin-top:4px;margin-bottom:8px;">Envie um arquivo de áudio para sobrepor no teaser final.</div>

        <div class="row wrap" style="gap:8px;margin-top:8px;align-items:flex-end;">
          <label class="btn teaser-narration-field" style="${narEnabled ? '' : 'pointer-events:none;opacity:.5;'}">
            ⬆ Enviar áudio
            <input id="teaserNarrationUpload" type="file" accept="audio/*,.mp3,.m4a,.wav" style="display:none;" onchange="uploadTeaserNarrationAudio(this)" ${narDisabled}>
          </label>
        </div>
        ${_renderTeaserNarrationAudioHtml()}

        <div class="row wrap" style="gap:8px;margin-top:8px;align-items:flex-end;">
          <div class="col">
            <label>Áudio original (%)</label>
            <input id="teaserOriginalAudioVolume" class="teaser-narration-field" type="number" min="0" max="200" step="5" value="${esc(String(Math.round(origVol)))}" onchange="updateTeaserNarrationSettings()" ${narDisabled}>
          </div>
          <div class="col">
            <label>Narração (%)</label>
            <input id="teaserNarrationVolume" class="teaser-narration-field" type="number" min="0" max="200" step="5" value="${esc(String(Math.round(narVol)))}" onchange="updateTeaserNarrationSettings()" ${narDisabled}>
          </div>
          <div class="col">
            <label>Sincronização (s)</label>
            <input id="teaserNarrationOffsetSec" class="teaser-narration-field" type="number" min="-30" max="30" step="0.1" value="${esc(narOffset.toFixed(1))}" onchange="updateTeaserNarrationSettings()" ${narDisabled}>
          </div>
        </div>
      </div>

      <div style="margin-top:10px;padding:10px;border:1px dashed var(--line);border-radius:8px;">
        <div class="row wrap" style="gap:10px;align-items:flex-end;">
          <div class="col grow">
            <label>Vídeo de abertura (opcional)</label>
            <div class="hint">Suba um clipe para entrar no início ou no final do teaser.</div>
          </div>
          <label class="btn">
            ⬆ Enviar abertura
            <input id="teaserOpenerUpload" type="file" accept="video/mp4,video/*" style="display:none;" onchange="uploadTeaserOpenerVideo(this)">
          </label>
        </div>
        ${_renderTeaserOpenerHtml()}
        <div class="row wrap" style="gap:8px;margin-top:8px;align-items:flex-end;">
          <div class="col">
            <label>Posição da abertura</label>
            <select id="teaserOpenerPosition" onchange="setTeaserOpenerPosition(this.value)">
              <option value="start" ${openerPosition === 'start' ? 'selected' : ''}>Início do teaser</option>
              <option value="end" ${openerPosition === 'end' ? 'selected' : ''}>Final do teaser</option>
            </select>
          </div>
        </div>
      </div>

      <div class="row wrap" style="gap:8px;margin-top:12px;">
        <button class="btn primary" onclick="generateTeaser()" ${hasTeaserSource ? '' : 'disabled'}>🎬 Gerar Teaser</button>
      </div>
      ${!hasTeaserSource ? `<div class="hint" style="margin-top:6px;">${sourceType === 'original' ? 'Selecione/defina o vídeo original para gerar teaser.' : 'Selecione um vídeo queimado para gerar teaser.'}</div>` : ''}

      <div id="teaserArea" style="margin-top:10px;">${_renderTeaserResultHtml()}</div>

      <div class="row wrap" style="margin-top:12px;gap:8px;align-items:flex-end;">
        <div class="col">
          <label>Posição do teaser no vídeo final</label>
          <select id="teaserConcatMode" onchange="setTeaserConcatMode(this.value)">
            <option value="start" ${concatMode === 'start' ? 'selected' : ''}>Início</option>
            <option value="end" ${concatMode === 'end' ? 'selected' : ''}>Final</option>
          </select>
        </div>
      </div>

      <div class="row" style="margin-top:12px;">
        <button class="btn primary" onclick="setCriacaoStep(4)">Continuar para Thumbnail</button>
      </div>
    </div>
  `;
}

function toggleTeaserNarrationEnabled(enabled) {
  criacaoState.teaserNarrationEnabled = !!enabled;
  document.querySelectorAll('.teaser-narration-field').forEach((el) => {
    el.disabled = !criacaoState.teaserNarrationEnabled;
  });
  _persistWizardState();
}

function updateTeaserNarrationSettings() {
  const enabled = !!qs('teaserNarrationEnabled')?.checked;
  criacaoState.teaserNarrationEnabled = enabled;

  const ov = parseFloat(qs('teaserOriginalAudioVolume')?.value || `${criacaoState.teaserOriginalAudioVolume || 100}`);
  criacaoState.teaserOriginalAudioVolume = _clamp(Number.isFinite(ov) ? ov : 100, 0, 200);

  const nv = parseFloat(qs('teaserNarrationVolume')?.value || `${criacaoState.teaserNarrationVolume || 120}`);
  criacaoState.teaserNarrationVolume = _clamp(Number.isFinite(nv) ? nv : 120, 0, 200);

  const off = parseFloat(qs('teaserNarrationOffsetSec')?.value || `${criacaoState.teaserNarrationOffsetSec || 0}`);
  criacaoState.teaserNarrationOffsetSec = _clamp(Number.isFinite(off) ? off : 0, -30, 30);

  _persistWizardState();
}

async function uploadTeaserNarrationAudio(input) {
  const file = input?.files?.[0];
  if (!file) return;
  try {
    const xhrRes = await _uploadViaProxy(file, { prefix: 'narrations-manual' });

    const objectKey = String(xhrRes.object_key || '').trim();
    if (!objectKey) throw new Error('Upload não retornou object_key');
    criacaoState.teaserNarrationEnabled = true;
    criacaoState.teaserNarrationObjectKey = objectKey;
    criacaoState.teaserNarrationAudioUrl = await _getVideoStreamUrl(objectKey);
    _persistWizardState({ immediate: true });
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    toast('Áudio enviado para narração', 'good');
  } catch (e) {
    toast('Erro ao enviar áudio: ' + e.message, 'bad');
  } finally {
    if (input) input.value = '';
  }
}

function clearTeaserNarrationAudio() {
  criacaoState.teaserNarrationObjectKey = null;
  criacaoState.teaserNarrationAudioUrl = null;
  _persistWizardState({ immediate: true });
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function setTeaserOpenerPosition(pos) {
  criacaoState.teaserOpenerPosition = pos === 'end' ? 'end' : 'start';
  _persistWizardState();
}

async function uploadTeaserOpenerVideo(input) {
  const file = input?.files?.[0];
  if (!file) return;
  try {
    const xhrRes = await _uploadViaProxy(file, {
      prefix: 'teasers-openers',
      validateVideo: true,
      deleteIfInvalid: true,
    });

    const objectKey = String(xhrRes.object_key || '').trim();
    if (!objectKey) throw new Error('Upload não retornou object_key');
    criacaoState.teaserOpenerObjectKey = objectKey;
    criacaoState.teaserOpenerUrl = await _getVideoStreamUrl(objectKey);
    _persistWizardState({ immediate: true });
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    toast('Vídeo de abertura enviado', 'good');
  } catch (e) {
    toast('Erro ao enviar abertura: ' + e.message, 'bad');
  } finally {
    if (input) input.value = '';
  }
}

function clearTeaserOpenerVideo() {
  criacaoState.teaserOpenerObjectKey = null;
  criacaoState.teaserOpenerUrl = null;
  _persistWizardState({ immediate: true });
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function _thumbNewElementId(prefix = 'el') {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function _thumbElementLabel(el, idx) {
  const type = el?.type === 'text' ? 'Texto' : 'Imagem';
  const name = String(el?.name || `${type} ${idx + 1}`);
  return `${idx + 1}. ${name} (${type})`;
}

function _thumbElements() {
  if (!Array.isArray(criacaoState.thumbElements)) criacaoState.thumbElements = [];
  return criacaoState.thumbElements;
}

function _thumbSelectedElement() {
  const list = _thumbElements();
  if (!list.length) return null;
  const id = criacaoState.thumbSelectedElementId;
  if (!id) return list[list.length - 1];
  return list.find(e => e.id === id) || list[list.length - 1];
}

function _thumbEnsureSelected() {
  const el = _thumbSelectedElement();
  criacaoState.thumbSelectedElementId = el ? el.id : null;
  return el;
}

function _thumbElementOptionsHtml() {
  const list = _thumbElements();
  if (!list.length) return '<option value="">Sem elementos</option>';
  return list.map((el, idx) => {
    const sel = (criacaoState.thumbSelectedElementId || '') === el.id ? 'selected' : '';
    return `<option value="${esc(el.id)}" ${sel}>${esc(_thumbElementLabel(el, idx))}</option>`;
  }).join('');
}

function _thumbAddElement(el, opts = {}) {
  const { select = true, persist = true } = opts;
  const list = _thumbElements();
  list.push(el);
  if (select) criacaoState.thumbSelectedElementId = el.id;
  if (persist) _persistWizardState();
}

function _thumbFindCaptionElement() {
  return _thumbElements().find(e => e.type === 'text' && e.role === 'caption') || null;
}

function _thumbDeleteCaptionElement(opts = {}) {
  const { persist = true } = opts;
  const list = _thumbElements();
  const idx = list.findIndex(e => e.type === 'text' && e.role === 'caption');
  if (idx < 0) return;
  const removedId = list[idx]?.id;
  list.splice(idx, 1);
  if (criacaoState.thumbSelectedElementId === removedId) {
    criacaoState.thumbSelectedElementId = list.length ? list[list.length - 1].id : null;
  }
  if (persist) _persistWizardState();
}

function _thumbUpsertCaptionElement(text, opts = {}) {
  const { persist = true, select = false } = opts;
  const clean = String(text || '').trim();
  if (!clean) {
    _thumbDeleteCaptionElement({ persist });
    return;
  }
  const existing = _thumbFindCaptionElement();
  if (existing) {
    existing.text = clean;
    existing.name = 'Legenda';
    if (select) criacaoState.thumbSelectedElementId = existing.id;
  } else {
    _thumbAddElement({
      id: _thumbNewElementId('caption'),
      type: 'text',
      role: 'caption',
      name: 'Legenda',
      text: clean,
      x: 50,
      y: 92,
      scale: 6,
      opacity: 100,
      rotation: 0,
      color: '#ffffff',
      strokeColor: '#000000',
      strokeWidth: 4,
      fontFamily: 'Outfit, Arial, sans-serif',
      fontWeight: '700',
    }, { select, persist: false });
  }
  if (persist) _persistWizardState();
}

function addThumbLogoElement() {
  if (!criacaoState.logoB64) return toast('Envie uma logo no Passo 1 primeiro', 'bad');
  _thumbAddElement({
    id: _thumbNewElementId('logo'),
    type: 'image',
    role: 'logo',
    name: 'Logo',
    src: criacaoState.logoB64,
    x: criacaoState.logoX || 85,
    y: criacaoState.logoY || 85,
    scale: criacaoState.logoScalePct || 20,
    opacity: criacaoState.logoOpacity || 85,
    rotation: 0,
  }, { select: true, persist: true });
  _updateThumbElementControlValues();
  drawThumbWithLogo(true);
}

function addThumbTextElement() {
  const txt = (qs('thumbNewText')?.value || '').trim();
  if (!txt) return toast('Digite um texto para adicionar', 'bad');
  _thumbAddElement({
    id: _thumbNewElementId('text'),
    type: 'text',
    name: 'Texto',
    text: txt,
    x: 50,
    y: 50,
    scale: 6,
    opacity: 100,
    rotation: 0,
    color: '#ffffff',
    strokeColor: '#000000',
    strokeWidth: 3,
    fontFamily: 'Outfit, Arial, sans-serif',
    fontWeight: '700',
  }, { select: true, persist: true });
  const inp = qs('thumbNewText');
  if (inp) inp.value = '';
  _updateThumbElementControlValues();
  drawThumbWithLogo(true);
}

function addThumbImageElement(input) {
  const file = input?.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const src = String(e.target?.result || '');
    if (!src) return;
    _thumbAddElement({
      id: _thumbNewElementId('img'),
      type: 'image',
      name: file.name || 'Imagem',
      src,
      x: 50,
      y: 50,
      scale: 24,
      opacity: 100,
      rotation: 0,
    }, { select: true, persist: true });
    _updateThumbElementControlValues();
    drawThumbWithLogo(true);
    input.value = '';
  };
  reader.readAsDataURL(file);
}

function selectThumbElement(id) {
  criacaoState.thumbSelectedElementId = id || null;
  _persistWizardState();
  _updateThumbElementControlValues();
  drawThumbWithLogo(false);
}

function moveThumbSelectedElement(dir) {
  const list = _thumbElements();
  const el = _thumbSelectedElement();
  if (!el) return;
  if (list.length < 2) {
    toast('Adicione mais de uma camada para mover ordem', 'bad');
    return;
  }
  const idx = list.findIndex(x => x.id === el.id);
  if (idx < 0) return;
  if (dir === 'up' && idx >= list.length - 1) {
    toast('Elemento já está na frente', 'bad');
    return;
  }
  if (dir === 'down' && idx <= 0) {
    toast('Elemento já está no fundo', 'bad');
    return;
  }
  if (dir === 'up' && idx < list.length - 1) {
    const tmp = list[idx + 1];
    list[idx + 1] = list[idx];
    list[idx] = tmp;
  } else if (dir === 'down' && idx > 0) {
    const tmp = list[idx - 1];
    list[idx - 1] = list[idx];
    list[idx] = tmp;
  }
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function deleteThumbSelectedElement() {
  const list = _thumbElements();
  const el = _thumbSelectedElement();
  if (!el) return;
  const idx = list.findIndex(x => x.id === el.id);
  if (idx < 0) return;

  // Se remover a camada de legenda, limpa o campo para não recriar no próximo render.
  if (el.role === 'caption') {
    criacaoState.thumbSubtitle = '';
    const input = qs('thumbSubtitleInput');
    if (input) input.value = '';
  }

  list.splice(idx, 1);
  criacaoState.thumbSelectedElementId = list.length ? list[Math.max(0, idx - 1)].id : null;
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function setThumbElementProp(prop, value) {
  const el = _thumbSelectedElement();
  if (!el) return;
  if (prop === 'x') el.x = _toNum(value, el.x ?? 50, 0, 100);
  if (prop === 'y') el.y = _toNum(value, el.y ?? 50, 0, 100);
  if (prop === 'scale') {
    const max = el.type === 'text' ? 30 : 120;
    const min = el.type === 'text' ? 1 : 2;
    el.scale = _toNum(value, el.scale ?? (el.type === 'text' ? 6 : 20), min, max);
  }
  if (prop === 'opacity') el.opacity = _toNum(value, el.opacity ?? 100, 0, 100);
  if (prop === 'rotation') el.rotation = _toNum(value, el.rotation ?? 0, -180, 180);
  if (prop === 'text') el.text = String(value || '');
  if (prop === 'color') el.color = String(value || '#ffffff');
  if (prop === 'strokeColor') el.strokeColor = String(value || '#000000');
  if (prop === 'strokeWidth') el.strokeWidth = _toNum(value, el.strokeWidth ?? 3, 0, 12);
  if (prop === 'name') el.name = String(value || '');
  if (el.role === 'caption') {
    criacaoState.thumbSubtitle = String(el.text || '');
    const input = qs('thumbSubtitleInput');
    if (input) input.value = criacaoState.thumbSubtitle;
    if (!String(el.text || '').trim()) {
      _thumbDeleteCaptionElement({ persist: false });
    }
  }
  _persistWizardState();
  _updateThumbElementControlValues();
  drawThumbWithLogo(false);
}

function _updateThumbElementControlValues() {
  const el = _thumbEnsureSelected();
  const setVal = (id, v) => { const x = qs(id); if (x) x.value = String(v); };
  const setTxt = (id, t) => { const x = qs(id); if (x) x.textContent = t; };
  const listSel = qs('thumbElementSelect');
  if (listSel) listSel.innerHTML = _thumbElementOptionsHtml();

  const controls = qs('thumbElementControls');
  const noSel = qs('thumbNoElementHint');
  const textControls = qs('thumbTextControls');
  const typeEl = qs('thumbElType');
  if (typeEl) typeEl.textContent = el ? (el.type === 'text' ? 'Texto' : 'Imagem') : 'Nenhum';

  if (!el) {
    if (controls) controls.style.opacity = '.5';
    if (noSel) noSel.style.display = 'block';
    if (textControls) textControls.style.display = 'none';
    return;
  }

  if (controls) controls.style.opacity = '1';
  if (noSel) noSel.style.display = 'none';
  if (textControls) textControls.style.display = (el.type === 'text') ? 'block' : 'none';

  const scaleMin = el.type === 'text' ? 1 : 2;
  const scaleMax = el.type === 'text' ? 30 : 120;
  const scaleStep = el.type === 'text' ? '0.1' : '0.2';
  const scaleInput = qs('thumbElScale');
  if (scaleInput) {
    scaleInput.min = String(scaleMin);
    scaleInput.max = String(scaleMax);
    scaleInput.step = scaleStep;
  }

  setVal('thumbElName', el.name || '');
  setVal('thumbElX', el.x ?? 50);
  setVal('thumbElY', el.y ?? 50);
  setVal('thumbElScale', el.scale ?? (el.type === 'text' ? 6 : 20));
  setVal('thumbElOpacity', el.opacity ?? 100);
  setVal('thumbElRotation', el.rotation ?? 0);
  setVal('thumbElText', el.text || '');
  setVal('thumbElColor', el.color || '#ffffff');
  setVal('thumbElStrokeColor', el.strokeColor || '#000000');
  setVal('thumbElStrokeWidth', el.strokeWidth ?? 3);
  setTxt('thumbElXVal', `${Number(el.x ?? 50).toFixed(1)}%`);
  setTxt('thumbElYVal', `${Number(el.y ?? 50).toFixed(1)}%`);
  setTxt('thumbElScaleVal', el.type === 'text'
    ? `${Number(el.scale ?? 6).toFixed(1)}% altura`
    : `${Number(el.scale ?? 20).toFixed(1)}% largura`);
  setTxt('thumbElOpacityVal', `${Math.round(Number(el.opacity ?? 100))}%`);
  setTxt('thumbElRotationVal', `${Math.round(Number(el.rotation ?? 0))}°`);
}

function _thumbLoadImage(src) {
  const key = String(src || '');
  if (!key) return Promise.reject(new Error('empty_image_src'));
  if (_thumbImgCache.has(key)) return _thumbImgCache.get(key);
  const p = new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => {
      _thumbImgCache.delete(key);
      reject(new Error('image_load_failed'));
    };
    img.src = key;
  });
  _thumbImgCache.set(key, p);
  return p;
}

function _thumbCanvasPoint(ev, canvas) {
  if (!ev || !canvas) return null;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const x = (ev.clientX - rect.left) * (canvas.width / rect.width);
  const y = (ev.clientY - rect.top) * (canvas.height / rect.height);
  return { x, y };
}

function _thumbHitTest(px, py) {
  for (let i = _thumbRenderBoxes.length - 1; i >= 0; i--) {
    const b = _thumbRenderBoxes[i];
    if (px >= b.x && px <= (b.x + b.w) && py >= b.y && py <= (b.y + b.h)) {
      return b;
    }
  }
  return null;
}

function _bindThumbCanvasInteractions() {
  const canvas = qs('thumbCanvas');
  if (!canvas) return;

  canvas.onpointerdown = (ev) => {
    const pt = _thumbCanvasPoint(ev, canvas);
    if (!pt) return;
    const hit = _thumbHitTest(pt.x, pt.y);
    if (!hit) return;
    ev.preventDefault();
    if (canvas.setPointerCapture) {
      try { canvas.setPointerCapture(ev.pointerId); } catch (_) {}
    }
    criacaoState.thumbSelectedElementId = hit.id;
    _thumbDragState = {
      pointerId: ev.pointerId,
      elementId: hit.id,
      offsetX: pt.x - hit.cx,
      offsetY: pt.y - hit.cy,
    };
    canvas.style.cursor = 'grabbing';
    _persistWizardState();
    _updateThumbElementControlValues();
    drawThumbWithLogo(false);
  };

  canvas.onpointermove = (ev) => {
    const pt = _thumbCanvasPoint(ev, canvas);
    if (!pt) return;
    if (_thumbDragState && _thumbDragState.pointerId === ev.pointerId) {
      const list = _thumbElements();
      const el = list.find(x => x.id === _thumbDragState.elementId);
      if (!el) return;
      const cx = pt.x - _thumbDragState.offsetX;
      const cy = pt.y - _thumbDragState.offsetY;
      el.x = _clamp((cx / canvas.width) * 100, 0, 100);
      el.y = _clamp((cy / canvas.height) * 100, 0, 100);
      if (el.role === 'caption') criacaoState.thumbSubtitle = String(el.text || '');
      _saveWizardSessionState();
      _updateThumbElementControlValues();
      drawThumbWithLogo(false);
      return;
    }
    const hit = _thumbHitTest(pt.x, pt.y);
    canvas.style.cursor = hit ? 'grab' : 'default';
  };

  canvas.onpointerup = (ev) => {
    if (_thumbDragState && _thumbDragState.pointerId === ev.pointerId) {
      _thumbDragState = null;
      canvas.style.cursor = 'default';
      _persistWizardState({ immediate: true });
      drawThumbWithLogo(false);
    }
  };

  canvas.onpointercancel = () => {
    _thumbDragState = null;
    canvas.style.cursor = 'default';
  };
}

function _renderStepThumb() {
  const frameIdx = _currentThumbFrameIdx();
  const frame = _getThumbSourceForFrame(frameIdx);
  const caption = criacaoState.thumbSubtitle || '';
  const thumbKey = criacaoState.thumbVideoObjectKey || criacaoState.burnedObjectKey || '';
  const thumbSourceLabel = thumbKey ? _burnFileNameFromKey(thumbKey) : 'Nenhum vídeo queimado selecionado';
  const selected = _thumbEnsureSelected();
  const hasSelected = !!selected;
  const dis = hasSelected ? '' : 'disabled';
  const selectedScaleMin = selected?.type === 'text' ? 1 : 2;
  const selectedScaleMax = selected?.type === 'text' ? 30 : 120;
  const selectedScaleStep = selected?.type === 'text' ? '0.1' : '0.2';
  const selectedScale = selected?.scale ?? (selected?.type === 'text' ? 6 : 20);
  const selectedType = selected ? (selected.type === 'text' ? 'Texto' : 'Imagem') : 'Nenhum';

  return `
    <div class="detail-section card">
      <h2>Passo 4 — Thumbnail Profissional</h2>
      <div class="hint" style="margin-bottom:10px;">Editor por camadas: logo opcional, imagens extras e textos. Nada é queimado automaticamente na thumb.</div>

      <div class="row wrap" style="gap:8px;align-items:flex-end;margin-bottom:10px;">
        <div class="col grow">
          <label>Fonte do frame HQ (queimado)</label>
          <div class="hint">${esc(thumbSourceLabel)}</div>
        </div>
        <button class="btn" onclick="loadExistingBurnedVideosFor('thumb','run')">📁 Deste run</button>
        <button class="btn" onclick="loadExistingBurnedVideosFor('thumb','all')">🗂 Todos queimados</button>
      </div>
      <div id="thumbVideoSelectArea" style="margin-bottom:10px;"></div>

      <div style="margin-bottom:10px;">
        <label>Escolha o screenshot base da thumbnail</label>
        ${_renderFrameSelector({ singleSelected: frameIdx, onClick: 'selectThumbFrame' })}
      </div>

      <div class="row wrap" style="gap:8px;align-items:flex-end;margin-top:8px;">
        <div class="col grow">
          <label>Qualidade da base</label>
          <div class="hint" id="thumbHQStatus">${criacaoState.thumbSourceInfo || 'Usando screenshot do run (pode ser comprimido em runs antigos).'}</div>
        </div>
        <button class="btn" onclick="loadHighResThumbnailFrame()" ${thumbKey ? '' : 'disabled'}>🔍 Carregar frame HQ do vídeo queimado</button>
      </div>

      <div class="row wrap" style="gap:8px;align-items:flex-end;margin-top:8px;">
        <div class="col grow">
          <label>Legenda da thumbnail</label>
          <input id="thumbSubtitleInput" type="text" value="${esc(caption)}" oninput="updateThumbSubtitle(this.value)" placeholder="Ex: Ela implorou até o final">
          <div class="hint">A legenda vira uma camada de texto editável (posição, cor, opacidade, etc.).</div>
        </div>
        <button class="btn" onclick="useFirstSubtitleAsThumbCaption()">Usar primeira legenda do SRT</button>
      </div>

      <div style="margin-top:12px;padding:12px;background:var(--bg2);border:1px solid var(--line);border-radius:8px;">
        <div class="hint" style="margin-bottom:8px;">Editor de imagem base</div>
        <div class="row wrap" style="gap:10px;align-items:flex-end;">
          <div class="col">
            <label>Saída</label>
            <select id="thumbOutputScale" onchange="setThumbEditor('outputScale', this.value)">
              <option value="1" ${criacaoState.thumbOutputScale === 1 ? 'selected' : ''}>1x</option>
              <option value="2" ${criacaoState.thumbOutputScale === 2 ? 'selected' : ''}>2x (recomendado)</option>
              <option value="3" ${criacaoState.thumbOutputScale === 3 ? 'selected' : ''}>3x</option>
            </select>
          </div>
          <div class="col">
            <label>Zoom</label>
            <input id="thumbZoom" type="range" min="1" max="3" step="0.01" value="${criacaoState.thumbZoom}" oninput="setThumbEditor('zoom', this.value)">
            <div class="hint" id="thumbZoomVal">${Number(criacaoState.thumbZoom).toFixed(2)}x</div>
          </div>
          <div class="col">
            <label>Crop X</label>
            <input id="thumbCropX" type="range" min="0" max="100" step="0.1" value="${criacaoState.thumbCropX}" oninput="setThumbEditor('cropX', this.value)">
            <div class="hint" id="thumbCropXVal">${Number(criacaoState.thumbCropX).toFixed(1)}%</div>
          </div>
          <div class="col">
            <label>Crop Y</label>
            <input id="thumbCropY" type="range" min="0" max="100" step="0.1" value="${criacaoState.thumbCropY}" oninput="setThumbEditor('cropY', this.value)">
            <div class="hint" id="thumbCropYVal">${Number(criacaoState.thumbCropY).toFixed(1)}%</div>
          </div>
        </div>
        <div class="row wrap" style="gap:10px;align-items:flex-end;margin-top:8px;">
          <div class="col">
            <label>Brilho</label>
            <input id="thumbBrightness" type="range" min="40" max="180" value="${criacaoState.thumbBrightness}" oninput="setThumbEditor('brightness', this.value)">
            <div class="hint" id="thumbBrightnessVal">${Math.round(criacaoState.thumbBrightness)}%</div>
          </div>
          <div class="col">
            <label>Contraste</label>
            <input id="thumbContrast" type="range" min="40" max="180" value="${criacaoState.thumbContrast}" oninput="setThumbEditor('contrast', this.value)">
            <div class="hint" id="thumbContrastVal">${Math.round(criacaoState.thumbContrast)}%</div>
          </div>
          <div class="col">
            <label>Saturação</label>
            <input id="thumbSaturation" type="range" min="0" max="220" value="${criacaoState.thumbSaturation}" oninput="setThumbEditor('saturation', this.value)">
            <div class="hint" id="thumbSaturationVal">${Math.round(criacaoState.thumbSaturation)}%</div>
          </div>
          <div class="col">
            <label>Matiz</label>
            <input id="thumbHue" type="range" min="-180" max="180" value="${criacaoState.thumbHue}" oninput="setThumbEditor('hue', this.value)">
            <div class="hint" id="thumbHueVal">${Math.round(criacaoState.thumbHue)}°</div>
          </div>
          <div class="col">
            <label>&nbsp;</label>
            <button class="btn" onclick="resetThumbEditor()">Resetar editor base</button>
          </div>
        </div>
      </div>

      <div style="margin-top:12px;padding:12px;background:var(--bg2);border:1px solid var(--line);border-radius:8px;">
        <div class="hint" style="margin-bottom:8px;">Camadas de elementos</div>
        <div class="row wrap" style="gap:8px;align-items:flex-end;">
          <button class="btn" onclick="addThumbLogoElement()">➕ Adicionar logo</button>
          <label class="btn" style="cursor:pointer;">
            🖼 Adicionar imagem
            <input type="file" accept="image/*" style="display:none;" onchange="addThumbImageElement(this)">
          </label>
          <div class="col grow">
            <label>Novo texto</label>
            <input id="thumbNewText" type="text" placeholder="Digite e clique em Adicionar texto">
          </div>
          <button class="btn" onclick="addThumbTextElement()">➕ Adicionar texto</button>
        </div>

        <div class="row wrap" style="gap:8px;align-items:flex-end;margin-top:8px;">
          <div class="col grow">
            <label>Elementos (${_thumbElements().length})</label>
            <select id="thumbElementSelect" onchange="selectThumbElement(this.value)">
              ${_thumbElementOptionsHtml()}
            </select>
          </div>
          <button class="btn" onclick="moveThumbSelectedElement('up')" ${dis}>⬆ Trazer frente</button>
          <button class="btn" onclick="moveThumbSelectedElement('down')" ${dis}>⬇ Enviar para trás</button>
          <button class="btn" onclick="deleteThumbSelectedElement()" ${dis}>🗑 Remover</button>
        </div>

        <div id="thumbElementControls" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--line);${hasSelected ? '' : 'opacity:.5;'}">
          <div id="thumbNoElementHint" class="hint" style="${hasSelected ? 'display:none;' : ''}">Adicione um elemento para editar propriedades.</div>
          <div class="row wrap" style="gap:8px;align-items:flex-end;">
            <div class="col grow">
              <label>Nome</label>
              <input id="thumbElName" type="text" value="${esc(selected?.name || '')}" oninput="setThumbElementProp('name', this.value)" ${dis}>
            </div>
            <div class="col">
              <label>Tipo</label>
              <div id="thumbElType" class="hint" style="padding:9px 0;">${selectedType}</div>
            </div>
          </div>
          <div class="row wrap" style="gap:10px;align-items:flex-end;">
            <div class="col">
              <label>Posição X</label>
              <input id="thumbElX" type="range" min="0" max="100" step="0.1" value="${selected?.x ?? 50}" oninput="setThumbElementProp('x', this.value)" ${dis}>
              <div class="hint" id="thumbElXVal">${Number(selected?.x ?? 50).toFixed(1)}%</div>
            </div>
            <div class="col">
              <label>Posição Y</label>
              <input id="thumbElY" type="range" min="0" max="100" step="0.1" value="${selected?.y ?? 50}" oninput="setThumbElementProp('y', this.value)" ${dis}>
              <div class="hint" id="thumbElYVal">${Number(selected?.y ?? 50).toFixed(1)}%</div>
            </div>
            <div class="col">
              <label>Escala</label>
              <input id="thumbElScale" type="range" min="${selectedScaleMin}" max="${selectedScaleMax}" step="${selectedScaleStep}" value="${selectedScale}" oninput="setThumbElementProp('scale', this.value)" ${dis}>
              <div class="hint" id="thumbElScaleVal">${selected?.type === 'text' ? `${Number(selectedScale).toFixed(1)}% altura` : `${Number(selectedScale).toFixed(1)}% largura`}</div>
            </div>
            <div class="col">
              <label>Opacidade</label>
              <input id="thumbElOpacity" type="range" min="0" max="100" step="1" value="${selected?.opacity ?? 100}" oninput="setThumbElementProp('opacity', this.value)" ${dis}>
              <div class="hint" id="thumbElOpacityVal">${Math.round(Number(selected?.opacity ?? 100))}%</div>
            </div>
            <div class="col">
              <label>Rotação</label>
              <input id="thumbElRotation" type="range" min="-180" max="180" step="1" value="${selected?.rotation ?? 0}" oninput="setThumbElementProp('rotation', this.value)" ${dis}>
              <div class="hint" id="thumbElRotationVal">${Math.round(Number(selected?.rotation ?? 0))}°</div>
            </div>
          </div>
          <div id="thumbTextControls" style="margin-top:8px;${selected?.type === 'text' ? '' : 'display:none;'}">
            <div class="row wrap" style="gap:10px;align-items:flex-end;">
              <div class="col grow">
                <label>Texto</label>
                <input id="thumbElText" type="text" value="${esc(selected?.text || '')}" oninput="setThumbElementProp('text', this.value)" ${dis}>
              </div>
              <div class="col">
                <label>Cor</label>
                <input id="thumbElColor" type="color" value="${esc(selected?.color || '#ffffff')}" oninput="setThumbElementProp('color', this.value)" ${dis}>
              </div>
              <div class="col">
                <label>Contorno</label>
                <input id="thumbElStrokeColor" type="color" value="${esc(selected?.strokeColor || '#000000')}" oninput="setThumbElementProp('strokeColor', this.value)" ${dis}>
              </div>
              <div class="col">
                <label>Esp. contorno</label>
                <input id="thumbElStrokeWidth" type="range" min="0" max="12" step="0.5" value="${selected?.strokeWidth ?? 3}" oninput="setThumbElementProp('strokeWidth', this.value)" ${dis}>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="row wrap" style="gap:8px;align-items:flex-end;margin-top:8px;">
        <div class="col">
          <label>Formato de exportação</label>
          <select id="thumbExportFmt" onchange="setThumbExportFormat(this.value)">
            <option value="png" ${criacaoState.thumbExportFormat === 'png' ? 'selected' : ''}>PNG (máxima qualidade)</option>
            <option value="jpg" ${criacaoState.thumbExportFormat === 'jpg' ? 'selected' : ''}>JPEG (arquivo menor)</option>
          </select>
        </div>
        <div class="col">
          <label>Qualidade JPEG</label>
          <input id="thumbJpegQuality" type="range" min="70" max="100" value="${criacaoState.thumbJpegQuality}" ${criacaoState.thumbExportFormat === 'png' ? 'disabled' : ''} oninput="setThumbJpegQuality(this.value)">
          <div class="hint" id="thumbJpegQualityVal">${criacaoState.thumbJpegQuality}%</div>
        </div>
      </div>

      <div style="margin-top:12px;">
        ${frame ? `
          <div class="post-thumb-wrap" id="thumbWrap">
            <img src="${_thumbFrameToSrc(frame)}" alt="thumb" class="post-thumb-img" id="thumbImg">
            <span class="post-thumb-badge">Thumbnail base</span>
          </div>
          <canvas id="thumbCanvas" class="post-logo-canvas" style="display:none;margin-top:8px;touch-action:none;"></canvas>
          <div class="hint" style="margin-top:6px;">Arraste os elementos direto no canvas para reposicionar.</div>
        ` : '<div class="hint">Sem frame para montar thumbnail.</div>'}
      </div>

      <div class="row" style="margin-top:10px;gap:8px;flex-wrap:wrap;">
        <button class="btn primary" onclick="drawThumbWithLogo(true)">Gerar Thumbnail</button>
        <button class="btn" onclick="downloadThumbnail()">⬇ Baixar Thumbnail</button>
      </div>

      <div class="row" style="margin-top:12px;">
        <button class="btn primary" onclick="setCriacaoStep(5)">Continuar para Post Final</button>
      </div>
    </div>
  `;
}

function _renderStepPost() {
  const qualityLabel = `Legenda: CRF ${criacaoState.burnedQuality || '26'} (${criacaoState.burnedPreset || 'ultrafast'}) · Teaser: CRF ${criacaoState.teaserQuality || '26'}`;
  return `
    <div class="detail-section card">
      <h2>Passo 5 — Gerar Post Completo</h2>
      <div class="hint" style="margin-bottom:10px;">Gera título, descrição e tags com preview do vídeo completo, teaser e opções de download.</div>
      <div class="hint" style="margin-bottom:8px;">Qualidade atual: ${esc(qualityLabel)}</div>
      <button class="btn primary" id="btnGerarPost" onclick="generatePost()">✦ Gerar Post XVideos</button>
      ${criacaoState.compareText ? `<button class="btn" style="margin-left:8px;" onclick="applyCmpTextAsPost()">Usar texto do Compare</button>` : ''}
      <div id="postResultArea" style="margin-top:14px;"></div>
    </div>
  `;
}

function renderCriacaoDetail(runId, frames) {
  const container = qs('criacaoDetail');
  if (!container) return;

  const cmBanner = criacaoState.compareText
    ? `<div class="detail-section card" style="border-color:var(--pri);">
        <h2>Texto do Compare selecionado</h2>
        <pre class="output" style="max-height:200px;white-space:pre-wrap;">${esc(criacaoState.compareText)}</pre>
        <div class="row" style="gap:8px;margin-top:8px;">
          <button class="btn primary" onclick="applyCmpTextAsPost()">↳ Usar como post</button>
          <button class="btn" onclick="criacaoState.compareText=null;renderCriacaoDetail('${runId}', criacaoState.frames)">✕ Descartar</button>
        </div>
      </div>`
    : '';

  let stepHtml = '';
  if (criacaoState.step === 1) stepHtml = _renderStepLogo();
  if (criacaoState.step === 2) stepHtml = _renderStepLegenda(runId);
  if (criacaoState.step === 3) stepHtml = _renderStepTeaser();
  if (criacaoState.step === 4) stepHtml = _renderStepThumb();
  if (criacaoState.step === 5) stepHtml = _renderStepPost();

  container.innerHTML = `
    ${cmBanner}

    <div class="detail-section card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <div>
          <div style="font-family:'Bebas Neue',sans-serif;font-size:15px;letter-spacing:1.5px;color:var(--muted);">${esc(runId.slice(0, 24))}…</div>
          <div class="hint">${frames.length} screenshots disponíveis</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <span class="badge">Wizard de Criação</span>
          <button class="btn" onclick="clearCriacaoRun('${escAttr(runId)}')">Limpar criação</button>
          <button class="btn" style="color:var(--bad);border-color:rgba(255,68,85,.45);" onclick="deleteRun('${escAttr(runId)}')">Excluir tudo</button>
        </div>
      </div>
      ${_renderWizardProgress()}
    </div>

    ${stepHtml}

    <div class="detail-section card">
      <h2>Vision — Análise Visual</h2>
      ${_buildVisionHtml(criacaoState.visionAnalysis)}
    </div>
  `;

  _postRenderCriacao(runId);
}

function _postRenderCriacao(runId) {
  _setLogoPos(criacaoState.logoX, criacaoState.logoY, { persist: false, refreshHq: false, redrawThumb: false });
  _setLogoStyle(criacaoState.logoScalePct, criacaoState.logoOpacity, { persist: false, refreshHq: false, redrawThumb: false });
  if (criacaoState.step === 3) {
    _updateTeaserLogoPreview();
  }

  if (criacaoState.step === 1) {
    _ensureLogoPreviewHq();
  }

  if (criacaoState.step === 2) {
    const ta = qs('transcriptSrtEdit');
    if (ta) {
      if (criacaoState.transcriptDraft) {
        ta.value = criacaoState.transcriptDraft;
        _srtUpdateStats();
        _srtUpdateCursor();
      } else {
        _loadTranscriptIntoEditor(runId);
      }
    }
    _srtEditorInit();
    updateSubtitlePreview();
  }

  if (criacaoState.step === 4) {
    const input = qs('thumbSubtitleInput');
    if (input) input.value = criacaoState.thumbSubtitle || '';
    setThumbExportFormat(criacaoState.thumbExportFormat);
    setThumbJpegQuality(criacaoState.thumbJpegQuality);
    _updateThumbEditorLabels();
    _updateThumbElementControlValues();
    drawThumbWithLogo(false);
    const hqKey = criacaoState.thumbVideoObjectKey || criacaoState.burnedObjectKey || '';
    if (!criacaoState.thumbSourceB64 && hqKey && !criacaoState.thumbAutoHqTried) {
      criacaoState.thumbAutoHqTried = true;
      loadHighResThumbnailFrame();
    }
  }

  if (criacaoState.step === 5 && criacaoState.postResult) {
    renderPostResult(criacaoState.postResult);
  }
}

function selectCriacaoFrame(idx) {
  criacaoState.selectedFrameIdx = idx;
  if (criacaoState.thumbFrameIdx == null) criacaoState.thumbFrameIdx = idx;
  if (criacaoState.thumbSourceFrameIdx !== idx) {
    criacaoState.thumbSourceB64 = null;
    criacaoState.thumbSourceFrameIdx = null;
    criacaoState.thumbSourceInfo = '';
  }
  const src = criacaoState.frames[idx] ? `data:image/jpeg;base64,${criacaoState.frames[idx]}` : '';
  const vid = document.querySelector('.xv-player-wrap video');
  const imgEl = document.querySelector('.xv-player-wrap img:not(.xv-logo-overlay)');
  if (vid && src) vid.poster = src;
  if (imgEl && src) imgEl.src = src;
  _persistWizardState();
  toast(`Frame ${idx} selecionado`, 'good');
}

function selectThumbFrame(idx) {
  criacaoState.thumbFrameIdx = idx;
  criacaoState.selectedFrameIdx = idx;
  criacaoState.thumbSourceB64 = null;
  criacaoState.thumbSourceFrameIdx = null;
  criacaoState.thumbSourceInfo = '';
  criacaoState.thumbAutoHqTried = false;
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function toggleTeaserFrame(idx) {
  const arr = criacaoState.teaserSelectedFrames || [];
  const at = arr.indexOf(idx);
  if (at >= 0) {
    arr.splice(at, 1);
    if (criacaoState.teaserSceneDurationsByFrame && Object.prototype.hasOwnProperty.call(criacaoState.teaserSceneDurationsByFrame, idx)) {
      delete criacaoState.teaserSceneDurationsByFrame[idx];
    }
  } else {
    arr.push(idx);
    if (!criacaoState.teaserSceneDurationsByFrame) criacaoState.teaserSceneDurationsByFrame = {};
    if (criacaoState.teaserSceneDurationsByFrame[idx] == null) {
      const d = _clamp(parseFloat(criacaoState.teaserClipDuration || '6') || 6, 1, TEASER_MAX_SCENE_DURATION_SEC);
      criacaoState.teaserSceneDurationsByFrame[idx] = d;
    }
  }
  arr.sort((a, b) => a - b);
  criacaoState.teaserSelectedFrames = arr;
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function selectAllTeaserFrames() {
  criacaoState.teaserSelectedFrames = criacaoState.frames.map((_, i) => i);
  if (!criacaoState.teaserSceneDurationsByFrame) criacaoState.teaserSceneDurationsByFrame = {};
  const d = _clamp(parseFloat(criacaoState.teaserClipDuration || '6') || 6, 1, TEASER_MAX_SCENE_DURATION_SEC);
  criacaoState.teaserSelectedFrames.forEach((idx) => {
    if (criacaoState.teaserSceneDurationsByFrame[idx] == null) criacaoState.teaserSceneDurationsByFrame[idx] = d;
  });
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function clearTeaserFrames() {
  criacaoState.teaserSelectedFrames = [];
  criacaoState.teaserSceneDurationsByFrame = {};
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function _teaserSceneDurationDefault() {
  return _clamp(parseFloat(criacaoState.teaserClipDuration || '6') || 6, 1, TEASER_MAX_SCENE_DURATION_SEC);
}

function _teaserSceneDurationForFrame(frameIdx) {
  if (!criacaoState.teaserSceneDurationsByFrame) criacaoState.teaserSceneDurationsByFrame = {};
  const raw = criacaoState.teaserSceneDurationsByFrame[frameIdx];
  const fallback = _teaserSceneDurationDefault();
  return _clamp(Number.isFinite(Number(raw)) ? Number(raw) : fallback, 1, TEASER_MAX_SCENE_DURATION_SEC);
}

function setTeaserFrameDuration(frameIdx, value) {
  if (!criacaoState.teaserSceneDurationsByFrame) criacaoState.teaserSceneDurationsByFrame = {};
  const v = _clamp(parseFloat(value) || _teaserSceneDurationDefault(), 1, TEASER_MAX_SCENE_DURATION_SEC);
  criacaoState.teaserSceneDurationsByFrame[frameIdx] = v;
  _persistWizardState();
}

function applyDefaultTeaserDurationToSelected() {
  const d = _teaserSceneDurationDefault();
  if (!criacaoState.teaserSceneDurationsByFrame) criacaoState.teaserSceneDurationsByFrame = {};
  (criacaoState.teaserSelectedFrames || []).forEach((idx) => {
    criacaoState.teaserSceneDurationsByFrame[idx] = d;
  });
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function _estimateTeaserRequestedDurationSec(numClips, clipDuration, selectedFrameIndexes, perSceneDurations) {
  const safeNumClips = _clamp(parseInt(numClips, 10) || 0, 0, TEASER_MAX_NUM_CLIPS);
  const safeClipDuration = _clamp(Number.isFinite(Number(clipDuration)) ? Number(clipDuration) : 6, 2, TEASER_MAX_SCENE_DURATION_SEC);
  let total = 0;
  let remaining = safeNumClips;
  const seen = new Set();
  (selectedFrameIndexes || []).forEach((rawIdx) => {
    if (remaining <= 0) return;
    const idx = parseInt(rawIdx, 10);
    if (!Number.isInteger(idx) || idx < 0 || seen.has(idx)) return;
    seen.add(idx);
    const rawDur = perSceneDurations && Object.prototype.hasOwnProperty.call(perSceneDurations, idx)
      ? perSceneDurations[idx]
      : safeClipDuration;
    total += _clamp(Number.isFinite(Number(rawDur)) ? Number(rawDur) : safeClipDuration, 1, TEASER_MAX_SCENE_DURATION_SEC);
    remaining -= 1;
  });
  if (remaining > 0) total += remaining * safeClipDuration;
  return total;
}

function _teaserPlannerSceneCount(numClips, selectedFrameIndexes) {
  const selectedCount = Math.min((selectedFrameIndexes || []).length, TEASER_MAX_NUM_CLIPS);
  if (selectedCount > 0) return selectedCount;
  return _clamp(parseInt(numClips, 10) || 0, 1, TEASER_MAX_NUM_CLIPS);
}

function _buildTeaserDurationPlan(sceneCount, totalMinutes, firstMinutes, lastMinutes) {
  const safeCount = _clamp(parseInt(sceneCount, 10) || 0, 1, TEASER_MAX_NUM_CLIPS);
  const minSceneSec = 2;
  const maxSceneSec = TEASER_MAX_SCENE_DURATION_SEC;
  const requestedTotalSec = (Number(totalMinutes) || 0) * 60;
  if (requestedTotalSec <= 0) {
    return { ok: false, detail: 'Defina quantos minutos o teaser deve ter.' };
  }
  const maxTotalForCount = Math.min(TEASER_MAX_TOTAL_DURATION_SEC, safeCount * maxSceneSec);
  if (requestedTotalSec > maxTotalForCount + 0.001) {
    return {
      ok: false,
      detail: `${safeCount} cena(s) suportam no máximo ${_formatDurationCompact(maxTotalForCount)} sem estourar o limite por cena.`,
    };
  }

  const totalSec = Math.max(minSceneSec * safeCount, Math.min(requestedTotalSec, TEASER_MAX_TOTAL_DURATION_SEC));
  let firstSec = _clamp((Number(firstMinutes) || 0) * 60, 0, maxSceneSec);
  let lastSec = _clamp((Number(lastMinutes) || 0) * 60, 0, maxSceneSec);
  let durations = [];

  if (safeCount === 1) {
    durations = [Math.min(maxSceneSec, totalSec)];
  } else if (safeCount === 2) {
    if (firstSec <= 0 && lastSec <= 0) {
      firstSec = totalSec / 2;
      lastSec = totalSec / 2;
    }
    const fixedTotal = Math.max(firstSec + lastSec, 0.001);
    if (fixedTotal > totalSec) {
      const scale = totalSec / fixedTotal;
      firstSec *= scale;
      lastSec *= scale;
    } else if (fixedTotal < totalSec) {
      const bonus = (totalSec - fixedTotal) / 2;
      firstSec += bonus;
      lastSec += bonus;
    }
    durations = [firstSec, lastSec];
  } else {
    const middleCount = safeCount - 2;
    const minMiddleTotal = middleCount * minSceneSec;
    if (firstSec <= 0 && lastSec <= 0) {
      firstSec = minSceneSec;
      lastSec = minSceneSec;
    }
    const maxFixedAllowed = Math.max(minSceneSec * 2, totalSec - minMiddleTotal);
    const requestedFixed = Math.max(firstSec + lastSec, 0.001);
    if (requestedFixed > maxFixedAllowed) {
      const scale = maxFixedAllowed / requestedFixed;
      firstSec *= scale;
      lastSec *= scale;
    }
    const remaining = Math.max(minMiddleTotal, totalSec - firstSec - lastSec);
    const middleSec = remaining / middleCount;
    durations = [firstSec, ...Array(middleCount).fill(middleSec), lastSec];
  }

  durations = durations.map((d) => _clamp(Math.round(d * 10) / 10, minSceneSec, maxSceneSec));
  const roundedTotal = durations.reduce((sum, d) => sum + d, 0);
  const diff = Math.round((totalSec - roundedTotal) * 10) / 10;
  if (Math.abs(diff) >= 0.1 && durations.length) {
    const lastIdx = durations.length - 1;
    durations[lastIdx] = _clamp(Math.round((durations[lastIdx] + diff) * 10) / 10, minSceneSec, maxSceneSec);
  }

  const finalTotal = durations.reduce((sum, d) => sum + d, 0);
  const defaultSceneSec = _clamp(Math.round((finalTotal / safeCount) * 10) / 10, minSceneSec, maxSceneSec);
  const middleSceneSec = durations.length > 2
    ? durations.slice(1, durations.length - 1).reduce((sum, d) => sum + d, 0) / Math.max(1, durations.length - 2)
    : defaultSceneSec;

  return {
    ok: true,
    sceneCount: safeCount,
    totalSec: finalTotal,
    durationsSec: durations,
    defaultSceneSec,
    middleSceneSec: _clamp(Math.round(middleSceneSec * 10) / 10, minSceneSec, maxSceneSec),
  };
}

function updateTeaserPlannerSettings() {
  criacaoState.teaserAutoDistribute = !!qs('teaserAutoDistribute')?.checked;
  criacaoState.teaserTargetDurationMin = String(_clamp(Number(qs('teaserTotalMinutes')?.value || criacaoState.teaserTargetDurationMin || 11) || 0, 0.1, TEASER_MAX_TOTAL_DURATION_SEC / 60));
  criacaoState.teaserFirstClipMin = String(_clamp(Number(qs('teaserFirstClipMinutes')?.value || criacaoState.teaserFirstClipMin || 1) || 0, 0, TEASER_MAX_SCENE_DURATION_SEC / 60));
  criacaoState.teaserLastClipMin = String(_clamp(Number(qs('teaserLastClipMinutes')?.value || criacaoState.teaserLastClipMin || 1) || 0, 0, TEASER_MAX_SCENE_DURATION_SEC / 60));
  _persistWizardState();
  const summaryEl = qs('teaserAutoPlanSummary');
  if (!summaryEl) return;
  const sceneCount = _teaserPlannerSceneCount(qs('teaserClips')?.value || criacaoState.teaserNumClips, criacaoState.teaserSelectedFrames || []);
  const plan = _buildTeaserDurationPlan(
    sceneCount,
    criacaoState.teaserTargetDurationMin,
    criacaoState.teaserFirstClipMin,
    criacaoState.teaserLastClipMin,
  );
  summaryEl.textContent = plan.ok
    ? `Plano: ${plan.sceneCount} cena(s), total ${_formatDurationCompact(plan.totalSec)}, média ${plan.defaultSceneSec.toFixed(1)}s por cena.`
    : plan.detail;
  summaryEl.style.color = plan.ok ? 'var(--muted)' : 'var(--bad)';
}

function applyTeaserDurationPlan() {
  const selected = (criacaoState.teaserSelectedFrames || []).slice(0, TEASER_MAX_NUM_CLIPS).sort((a, b) => a - b);
  const sceneCount = _teaserPlannerSceneCount(qs('teaserClips')?.value || criacaoState.teaserNumClips, selected);
  const plan = _buildTeaserDurationPlan(
    sceneCount,
    qs('teaserTotalMinutes')?.value || criacaoState.teaserTargetDurationMin,
    qs('teaserFirstClipMinutes')?.value || criacaoState.teaserFirstClipMin,
    qs('teaserLastClipMinutes')?.value || criacaoState.teaserLastClipMin,
  );
  if (!plan.ok) return toast(plan.detail, 'bad');

  criacaoState.teaserAutoDistribute = !!qs('teaserAutoDistribute')?.checked;
  criacaoState.teaserTargetDurationMin = String(qs('teaserTotalMinutes')?.value || criacaoState.teaserTargetDurationMin);
  criacaoState.teaserFirstClipMin = String(qs('teaserFirstClipMinutes')?.value || criacaoState.teaserFirstClipMin);
  criacaoState.teaserLastClipMin = String(qs('teaserLastClipMinutes')?.value || criacaoState.teaserLastClipMin);
  criacaoState.teaserNumClips = String(plan.sceneCount);
  criacaoState.teaserClipDuration = String(plan.defaultSceneSec);
  if (!criacaoState.teaserSceneDurationsByFrame) criacaoState.teaserSceneDurationsByFrame = {};
  if (selected.length) {
    selected.slice(0, plan.sceneCount).forEach((idx, pos) => {
      criacaoState.teaserSceneDurationsByFrame[idx] = plan.durationsSec[pos];
    });
  }
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
  toast(`Distribuição aplicada: ${_formatDurationCompact(plan.totalSec)} em ${plan.sceneCount} cena(s).`, 'good');
}

function _formatDurationCompact(seconds) {
  const safe = Math.max(0, Math.round(Number(seconds) || 0));
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = safe % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
  if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

function _isBurnedMediaObjectKey(objectKey) {
  const key = String(_normalizeObjectKeyish(objectKey) || '').trim().toLowerCase();
  return !!key && (/^(local:)?burns\//.test(key) || /^(local:)?combined\//.test(key));
}

function _setTeaserSource(type, objectKey = null, opts = {}) {
  const persist = opts.persist === true;
  const immediate = !!opts.immediate;
  const shouldRender = opts.render === true;
  // explicit=true: respeita a escolha do usuário sem forçar fallback de tipo
  const explicit = !!opts.explicit;
  const originalKey = _normalizeObjectKeyish(_resolveOriginalVideoObjectKey()) || null;
  const burnedKey = _normalizeObjectKeyish(criacaoState.burnedObjectKey) || null;
  const requestedType = String(type || '').toLowerCase() === 'original' ? 'original' : 'burned';
  let nextKey = _normalizeObjectKeyish(objectKey) || null;
  let nextType = requestedType;

  if (nextKey) {
    // Chave fornecida → deriva o tipo da própria chave
    nextType = _isBurnedMediaObjectKey(nextKey) ? 'burned' : 'original';
  } else if (!explicit) {
    // Apenas em modo auto: converte tipo se não houver chave disponível para o tipo pedido
    if (nextType === 'burned' && !burnedKey && originalKey) {
      nextType = 'original';
    } else if (nextType === 'original' && !originalKey && burnedKey) {
      nextType = 'burned';
    }
  }

  // Resolve a chave dentro do tipo escolhido
  if (!nextKey) nextKey = nextType === 'burned' ? burnedKey : originalKey;
  // Last-resort só em modo auto (não explícito): usa qualquer chave disponível
  if (!nextKey && !explicit) {
    nextKey = nextType === 'burned' ? (burnedKey || originalKey) : (originalKey || burnedKey);
  }
  // Re-deriva o tipo da chave final (só quando há chave)
  if (nextKey && _isBurnedMediaObjectKey(nextKey)) nextType = 'burned';
  else if (nextKey) nextType = 'original';
  // Em modo explícito sem chave, mantém o tipo pedido (UI mostrará "sem vídeo disponível")
  if (!nextKey && explicit) nextType = requestedType;

  let changed = false;
  if (criacaoState.teaserSourceType !== nextType) {
    criacaoState.teaserSourceType = nextType;
    changed = true;
  }
  if ((_normalizeObjectKeyish(criacaoState.teaserSourceObjectKey) || null) !== nextKey) {
    criacaoState.teaserSourceObjectKey = nextKey;
    changed = true;
  }
  if (nextType === 'burned' && criacaoState.teaserForceLogoOverlay) {
    criacaoState.teaserForceLogoOverlay = false;
    changed = true;
  }

  if (persist && changed) _persistWizardState({ immediate });
  if (shouldRender && criacaoState.runId) renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
  return changed;
}

function setTeaserSourceType(type) {
  // explicit=true: não converte automaticamente p/ burned quando original não está disponível
  _setTeaserSource(type, null, { persist: true, immediate: true, render: true, explicit: true });
}

function useOriginalVideoAsTeaserSource() {
  const originalKey = _resolveOriginalVideoObjectKey();
  if (!originalKey) return toast('Este run não possui vídeo original salvo.', 'bad');
  _setTeaserSource('original', originalKey, { persist: true, immediate: true, render: true });
  toast('Fonte do teaser definida para vídeo original', 'good');
}

function setTeaserForceLogoOverlay(enabled) {
  if (_isBurnedMediaObjectKey(criacaoState.teaserSourceObjectKey) && enabled) {
    criacaoState.teaserForceLogoOverlay = false;
    _persistWizardState();
    if (criacaoState.step === 3) renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    return toast('Com fonte em vídeo queimado, a logo extra fica desligada para evitar duplicação.', 'bad');
  }
  criacaoState.teaserForceLogoOverlay = !!enabled;
  _persistWizardState();
  if (criacaoState.step === 3) renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function _teaserLogoList() {
  if (!Array.isArray(criacaoState.teaserLogos)) criacaoState.teaserLogos = [];
  return criacaoState.teaserLogos;
}

function _teaserActiveLogoIndex() {
  const list = _teaserLogoList();
  const maxIdx = Math.max(0, list.length - 1);
  criacaoState.teaserLogoActiveIdx = _clamp(parseInt(criacaoState.teaserLogoActiveIdx || 0, 10) || 0, 0, maxIdx);
  return criacaoState.teaserLogoActiveIdx;
}

function _teaserActiveLogo() {
  const list = _teaserLogoList();
  if (!list.length) return null;
  return list[_teaserActiveLogoIndex()] || null;
}

function _teaserLogoPayloadList() {
  return _teaserLogoList()
    .map(_teaserNormalizeLogo)
    .filter((l) => !!l.src)
    .slice(0, 6)
    .map((l) => ({
      b64: l.src,
      name: l.name,
      mime: l.mime || (l.isGif ? 'image/gif' : 'image/png'),
      x: _toNum(l.x, 97, 0, 100),
      y: _toNum(l.y, 97, 0, 100),
      scale_pct: _toNum(l.scale_pct, 20, 5, 100),
      opacity: _toNum(l.opacity, 85, 5, 100),
      remove_bg: !!l.remove_bg,
      sync_main: !!l.sync_main,
      bg_key_color: l.bg_key_color || '#ffffff',
      bg_similarity: _toNum(l.bg_similarity, 0.18, 0.01, 0.60),
      bg_blend: _toNum(l.bg_blend, 0.08, 0.0, 0.40),
    }));
}

function _syncInheritedTeaserLogosFromMain() {
  const list = _teaserLogoList();
  if (!list.length) return false;
  const hasProfileLogo = !!String(criacaoState.logoProfileId || criacaoState.logoProfileName || '').trim();
  // Se não há logo no Passo 1, remove logos sync_main do teaser (eram derivadas dela).
  if (!criacaoState.logoB64) {
    // Perfis salvos guardam a imagem no servidor por object_key. Mesmo sem
    // dataURL no browser, o backend consegue resolver a logo pelo perfil.
    if (hasProfileLogo) return false;
    const filtered = list.filter((l) => !l.sync_main);
    if (filtered.length < list.length) {
      criacaoState.teaserLogos = filtered;
      if (!filtered.length) {
        criacaoState.teaserForceLogoOverlay = false;
        criacaoState.teaserLogoAutoSeeded = false;
      }
      return true;
    }
    return false;
  }
  const mainMime = /^data:image\/gif/i.test(String(criacaoState.logoB64 || '')) ? 'image/gif' : 'image/png';
  let changed = false;
  for (let i = 0; i < list.length; i += 1) {
    const current = _teaserNormalizeLogo(list[i]);
    if (!current.sync_main) continue;
    const synced = _teaserNormalizeLogo({
      ...current,
      name: criacaoState.logoName || current.name || 'logo-passo-1',
      src: criacaoState.logoB64,
      mime: mainMime,
      x: criacaoState.logoX,
      y: criacaoState.logoY,
      scale_pct: criacaoState.logoScalePct,
      opacity: criacaoState.logoOpacity,
      sync_main: true,
    });
    if (JSON.stringify(current) !== JSON.stringify(synced)) {
      list[i] = synced;
      changed = true;
    }
  }
  if (changed) criacaoState.teaserLogos = list;
  return changed;
}

function selectTeaserLogo(idx) {
  const list = _teaserLogoList();
  if (!list.length) return;
  criacaoState.teaserLogoActiveIdx = _clamp(parseInt(idx, 10) || 0, 0, list.length - 1);
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function removeTeaserLogo(idx) {
  const list = _teaserLogoList();
  const i = parseInt(idx, 10);
  if (!Number.isInteger(i) || i < 0 || i >= list.length) return;
  list.splice(i, 1);
  criacaoState.teaserLogos = list;
  if (!list.length) {
    criacaoState.teaserLogoActiveIdx = 0;
    criacaoState.teaserForceLogoOverlay = false;
    criacaoState.teaserLogoAutoSeeded = false;
  } else {
    criacaoState.teaserLogoActiveIdx = _clamp(criacaoState.teaserLogoActiveIdx, 0, list.length - 1);
  }
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function clearAllTeaserLogos() {
  criacaoState.teaserLogos = [];
  criacaoState.teaserLogoActiveIdx = 0;
  criacaoState.teaserLogoAutoSeeded = true;
  criacaoState.teaserForceLogoOverlay = false;
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

async function loadTeaserLogos(input) {
  const files = Array.from(input?.files || []).slice(0, 6);
  if (!files.length) return;
  const list = _teaserLogoList();
  const maxCanAdd = Math.max(0, 6 - list.length);
  const allowed = files.slice(0, maxCanAdd);
  if (!allowed.length) {
    toast('Limite de 6 logos no teaser atingido.', 'bad');
    return;
  }
  try {
    const readOne = (file) => new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (ev) => resolve({
        name: file.name || 'logo',
        mime: String(file.type || '').toLowerCase(),
        src: String(ev?.target?.result || ''),
      });
      reader.onerror = () => reject(new Error(`Falha ao ler ${file.name || 'arquivo'}`));
      reader.readAsDataURL(file);
    });
    const loaded = await Promise.all(allowed.map(readOne));
    loaded.forEach((raw) => {
      const normalized = _teaserNormalizeLogo(raw);
      if (normalized.src) list.push(normalized);
    });
    criacaoState.teaserLogos = list.slice(0, 6);
    criacaoState.teaserLogoAutoSeeded = true;
    if (criacaoState.teaserLogos.length && criacaoState.teaserSourceType !== 'burned') criacaoState.teaserForceLogoOverlay = true;
    criacaoState.teaserLogoActiveIdx = Math.max(0, criacaoState.teaserLogos.length - 1);
    _setTeaserSource(criacaoState.teaserSourceType, criacaoState.teaserSourceObjectKey, { persist: false, render: false });
    _persistWizardState();
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    toast(`${loaded.length} logo(s) adicionada(s) ao teaser`, 'good');
  } catch (e) {
    toast(`Erro ao carregar logo: ${e.message}`, 'bad');
  } finally {
    if (input) input.value = '';
  }
}

function addMainLogoToTeaser() {
  if (!criacaoState.logoB64) return toast('Não há logo no Passo 1 para reutilizar.', 'bad');
  const list = _teaserLogoList();
  if (list.length >= 6) return toast('Limite de 6 logos no teaser atingido.', 'bad');
  const item = _teaserNormalizeLogo({
    name: criacaoState.logoName || 'logo-passo-1',
    src: criacaoState.logoB64,
    mime: /^data:image\/gif/i.test(String(criacaoState.logoB64 || '')) ? 'image/gif' : 'image/png',
    x: criacaoState.logoX,
    y: criacaoState.logoY,
    scale_pct: criacaoState.logoScalePct,
    opacity: criacaoState.logoOpacity,
    sync_main: true,
  });
  list.push(item);
  criacaoState.teaserLogos = list;
  criacaoState.teaserLogoAutoSeeded = true;
  if (criacaoState.teaserSourceType !== 'burned') criacaoState.teaserForceLogoOverlay = true;
  criacaoState.teaserLogoActiveIdx = list.length - 1;
  _setTeaserSource(criacaoState.teaserSourceType, criacaoState.teaserSourceObjectKey, { persist: false, render: false });
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

async function loadOriginalVideosForTeaser() {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  const area = qs('teaserSelectArea');
  if (!area) return;
  area.innerHTML = '<span class="hint">⏳ Carregando vídeos originais…</span>';
  try {
    const res = await apiFetch('/uploads/list?prefix=uploads&max_keys=120');
    const items = (Array.isArray(res?.items) ? res.items : [])
      .filter(it => String(it?.object_key || '').toLowerCase().endsWith('.mp4'))
      .slice(0, 30);
    _burnCandidatesCache.original = items;
    if (!items.length) {
      area.innerHTML = '<div class="hint">Nenhum vídeo original encontrado na biblioteca.</div>';
      return;
    }
    area.innerHTML = `
      <div class="hint" style="margin-bottom:6px;">${items.length} vídeo(s) original(is) encontrado(s)</div>
      <div style="display:grid;gap:6px;">
        ${items.map((it, idx) => {
          const key = String(it.object_key || '');
          const fname = _burnFileNameFromKey(key);
          const date = it.last_modified ? fmtDate(it.last_modified) : '';
          const size = it.size_mb != null ? `${it.size_mb} MB` : '';
          return `
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px;border:1px solid var(--line);border-radius:8px;background:var(--bg2);">
              <div style="flex:1;min-width:220px;">
                <div style="font-size:12px;font-weight:600;">${esc(fname)}</div>
                <div class="hint" style="font-size:11px;">${esc(size)} ${size && date ? '·' : ''} ${esc(date)}</div>
                <div class="hint" style="font-size:10px;opacity:.8;word-break:break-all;">${esc(key)}</div>
              </div>
              <button class="btn primary" onclick="useOriginalTeaserSourceByIndex(${idx})">Usar este</button>
            </div>
          `;
        }).join('')}
      </div>
    `;
  } catch (e) {
    area.innerHTML = `<span class="hint" style="color:var(--bad);">Erro ao listar originais: ${esc(e.message)}</span>`;
  }
}

async function useOriginalTeaserSourceByIndex(idx) {
  const list = _burnCandidatesCache.original || [];
  const item = list[Number(idx)];
  if (!item) return toast('Vídeo original selecionado inválido', 'bad');
  const objectKey = String(item.object_key || '').trim();
  if (!objectKey) return toast('Object key inválida', 'bad');
  try {
    const streamUrl = await _getVideoStreamUrl(objectKey);
    _setTeaserSource('original', objectKey, { persist: false, render: false });
    if (!criacaoState._reqData || typeof criacaoState._reqData !== 'object') criacaoState._reqData = {};
    if (!String(criacaoState._reqData.video_object_key || '').trim()) {
      criacaoState._reqData.video_object_key = objectKey;
      if (!criacaoState.videoUrl && streamUrl) criacaoState.videoUrl = streamUrl;
    }
    _persistWizardState({ immediate: true });
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    const area = qs('teaserSelectArea');
    if (area) area.innerHTML = '<span class="hint" style="color:var(--good);">✓ Vídeo original selecionado para o teaser.</span>';
  } catch (e) {
    toast('Erro ao selecionar original: ' + e.message, 'bad');
  }
}

function setTeaserLogoField(field, value) {
  const logo = _teaserActiveLogo();
  if (!logo) return;
  if (field === 'x') logo.x = _toNum(value, logo.x, 0, 100);
  if (field === 'y') logo.y = _toNum(value, logo.y, 0, 100);
  if (field === 'scale_pct') logo.scale_pct = _toNum(value, logo.scale_pct, 5, 100);
  if (field === 'opacity') logo.opacity = _toNum(value, logo.opacity, 5, 100);
  if (field === 'remove_bg') logo.remove_bg = !!value;
  if (field === 'bg_key_color') {
    const raw = String(value || '#ffffff').trim();
    logo.bg_key_color = /^#?[0-9a-fA-F]{6}$/.test(raw) ? (raw.startsWith('#') ? raw : `#${raw}`) : '#ffffff';
  }
  if (field === 'bg_similarity') logo.bg_similarity = _toNum(value, logo.bg_similarity, 0.01, 0.60);
  if (field === 'bg_blend') logo.bg_blend = _toNum(value, logo.bg_blend, 0.0, 0.40);
  logo.sync_main = false;
  _persistWizardState();
  _updateTeaserLogoPreview();
}

function syncActiveTeaserLogoFromMain() {
  const logo = _teaserActiveLogo();
  if (!logo || !criacaoState.logoB64) return toast('Envie uma logo no Passo 1 primeiro', 'bad');
  const mainMime = /^data:image\/gif/i.test(String(criacaoState.logoB64 || '')) ? 'image/gif' : 'image/png';
  logo.name = criacaoState.logoName || logo.name || 'logo-passo-1';
  logo.src = criacaoState.logoB64;
  logo.mime = mainMime;
  logo.x = _toNum(criacaoState.logoX, logo.x, 0, 100);
  logo.y = _toNum(criacaoState.logoY, logo.y, 0, 100);
  logo.scale_pct = _toNum(criacaoState.logoScalePct, logo.scale_pct, 5, 100);
  logo.opacity = _toNum(criacaoState.logoOpacity, logo.opacity, 5, 100);
  logo.sync_main = true;
  _persistWizardState();
  _updateTeaserLogoPreview();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
  toast('Logo do teaser sincronizada com o Passo 1', 'good');
}

function setTeaserLogoSyncMain(enabled) {
  const logo = _teaserActiveLogo();
  if (!logo) return;
  if (enabled) {
    syncActiveTeaserLogoFromMain();
    return;
  }
  logo.sync_main = false;
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function _toggleTeaserPreviewBg() {
  const bg = qs('teaserLogoPreviewBg');
  const btn = qs('btnToggleTeaserBg');
  if (!bg) return;
  const isHidden = bg.classList.toggle('hidden');
  if (btn) btn.textContent = isHidden ? 'Mostrar vídeo' : 'Ocultar vídeo';
}

function _updateTeaserLogoPreview() {
  const wrap = qs('teaserLogoPreviewWrap');
  if (!wrap) return;
  const overlays = Array.from(wrap.querySelectorAll('.teaser-logo-preview-overlay'));
  if (!overlays.length) return;
  requestAnimationFrame(() => {
    const cw = wrap.clientWidth || 1;
    const ch = wrap.clientHeight || 1;
    overlays.forEach((ov) => {
      const idx = parseInt(ov.dataset.logoIndex || '-1', 10);
      const item = _teaserLogoList()[idx];
      if (!item) return;
      ov.style.width = `${_toNum(item.scale_pct, 20, 5, 100)}%`;
      ov.style.opacity = `${_toNum(item.opacity, 85, 5, 100) / 100}`;
      const lw = ov.offsetWidth || (cw * _toNum(item.scale_pct, 20, 5, 100) / 100);
      const lh = ov.offsetHeight || (lw * 0.35);
      const xPx = (cw - lw) * (_toNum(item.x, 97, 0, 100) / 100);
      const yPx = (ch - lh) * (_toNum(item.y, 97, 0, 100) / 100);
      ov.style.left = `${_clamp(xPx, 0, Math.max(0, cw - lw))}px`;
      ov.style.top = `${_clamp(yPx, 0, Math.max(0, ch - lh))}px`;
    });
  });
}

function startTeaserLogoDrag(ev, idx) {
  const logoIdx = parseInt(idx, 10);
  const list = _teaserLogoList();
  if (!Number.isInteger(logoIdx) || logoIdx < 0 || logoIdx >= list.length) return;
  const wrap = qs('teaserLogoPreviewWrap');
  const overlay = wrap?.querySelector(`.teaser-logo-preview-overlay[data-logo-index="${logoIdx}"]`);
  if (!wrap || !overlay) return;
  ev.preventDefault();
  criacaoState.teaserLogoActiveIdx = logoIdx;
  const logo = list[logoIdx];

  const move = (e) => {
    const point = { x: e.clientX, y: e.clientY };
    const rect = wrap.getBoundingClientRect();
    const ovRect = overlay.getBoundingClientRect();
    const lw = ovRect.width || rect.width * (_toNum(logo.scale_pct, 20, 5, 100) / 100);
    const lh = ovRect.height || lw * 0.35;
    let xPx = point.x - rect.left - (lw / 2);
    let yPx = point.y - rect.top - (lh / 2);
    xPx = _clamp(xPx, 0, Math.max(0, rect.width - lw));
    yPx = _clamp(yPx, 0, Math.max(0, rect.height - lh));
    const xPct = (rect.width - lw) > 0 ? (xPx / (rect.width - lw)) * 100 : 0;
    const yPct = (rect.height - lh) > 0 ? (yPx / (rect.height - lh)) * 100 : 0;
    logo.x = _clamp(xPct, 0, 100);
    logo.y = _clamp(yPct, 0, 100);
    _updateTeaserLogoPreview();
  };

  const up = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    _persistWizardState();
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
  };

  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
  move(ev);
}

function updateThumbSubtitle(v) {
  const text = String(v || '');
  criacaoState.thumbSubtitle = text;
  _thumbUpsertCaptionElement(text, { persist: false });
  _persistWizardState();
  _updateThumbElementControlValues();
  drawThumbWithLogo(false);
}

function setThumbExportFormat(fmt) {
  criacaoState.thumbExportFormat = (fmt === 'jpg') ? 'jpg' : 'png';
  const q = qs('thumbJpegQuality');
  if (q) q.disabled = criacaoState.thumbExportFormat === 'png';
  _persistWizardState();
}

function setThumbJpegQuality(v) {
  const q = _clamp(parseInt(v, 10) || 98, 70, 100);
  criacaoState.thumbJpegQuality = q;
  const lbl = qs('thumbJpegQualityVal');
  if (lbl) lbl.textContent = `${q}%`;
  _persistWizardState();
}

function _updateThumbEditorLabels() {
  const setTxt = (id, text) => { const el = qs(id); if (el) el.textContent = text; };
  setTxt('thumbZoomVal', `${Number(criacaoState.thumbZoom || 1).toFixed(2)}x`);
  setTxt('thumbCropXVal', `${Number(criacaoState.thumbCropX || 50).toFixed(1)}%`);
  setTxt('thumbCropYVal', `${Number(criacaoState.thumbCropY || 50).toFixed(1)}%`);
  setTxt('thumbBrightnessVal', `${Math.round(criacaoState.thumbBrightness || 100)}%`);
  setTxt('thumbContrastVal', `${Math.round(criacaoState.thumbContrast || 100)}%`);
  setTxt('thumbSaturationVal', `${Math.round(criacaoState.thumbSaturation || 100)}%`);
  setTxt('thumbHueVal', `${Math.round(criacaoState.thumbHue || 0)}°`);
}

function setThumbEditor(field, value) {
  if (field === 'outputScale') criacaoState.thumbOutputScale = _clamp(parseInt(value, 10) || 2, 1, 3);
  if (field === 'zoom') criacaoState.thumbZoom = _toNum(value, criacaoState.thumbZoom, 1, 3);
  if (field === 'cropX') criacaoState.thumbCropX = _toNum(value, criacaoState.thumbCropX, 0, 100);
  if (field === 'cropY') criacaoState.thumbCropY = _toNum(value, criacaoState.thumbCropY, 0, 100);
  if (field === 'brightness') criacaoState.thumbBrightness = _toNum(value, criacaoState.thumbBrightness, 40, 180);
  if (field === 'contrast') criacaoState.thumbContrast = _toNum(value, criacaoState.thumbContrast, 40, 180);
  if (field === 'saturation') criacaoState.thumbSaturation = _toNum(value, criacaoState.thumbSaturation, 0, 220);
  if (field === 'hue') criacaoState.thumbHue = _toNum(value, criacaoState.thumbHue, -180, 180);
  _updateThumbEditorLabels();
  _persistWizardState();
  drawThumbWithLogo(false);
}

function resetThumbEditor() {
  criacaoState.thumbOutputScale = 2;
  criacaoState.thumbCropX = 50;
  criacaoState.thumbCropY = 50;
  criacaoState.thumbZoom = 1;
  criacaoState.thumbBrightness = 100;
  criacaoState.thumbContrast = 100;
  criacaoState.thumbSaturation = 100;
  criacaoState.thumbHue = 0;
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

async function loadLogoPreviewHqFrame(opts = {}) {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  const silent = !!opts.silent;
  _syncCriacaoDraftsFromDom();
  const frameIdx = _currentThumbFrameIdx();
  // Use the shared helper that checks all known object_key fields
  const objectKey = _resolveOriginalVideoObjectKey() || criacaoState.burnedObjectKey || '';
  let nextHqUrl = '';

  criacaoState.logoPreviewHqLoading = true;
  if (criacaoState.step === 1) {
    _syncLogoPreviewDom();
  } else {
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
  }

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const body = {
      run_id: criacaoState.runId,
      frame_index: frameIdx,
      frames_count: (criacaoState.frames || []).length || 10,
      max_height: _selectedBurnMaxHeight(),
    };
    if (objectKey) body.object_key = objectKey;
    // No editor de logo (Passo 1), o frame HQ precisa ser limpo: a logo fica
    // sempre como overlay editável por cima. Se o servidor já compõe a logo no
    // frame, o usuário perde a referência visual do que está sendo arrastado.
    const shouldCompositeLogoInHq = criacaoState.step !== 1;
    const burnLogoPayload = shouldCompositeLogoInHq ? _burnLogoPayloadList() : [];
    if (shouldCompositeLogoInHq && burnLogoPayload.length) {
      body.logos = burnLogoPayload;
      const firstLogo = burnLogoPayload[0];
      body.logo_b64 = firstLogo.b64;
      body.logo_x = firstLogo.x;
      body.logo_y = firstLogo.y;
      body.logo_scale_pct = firstLogo.scale_pct;
      body.logo_opacity = firstLogo.opacity;
    } else if (shouldCompositeLogoInHq && criacaoState.logoB64) {
      body.logo_b64 = criacaoState.logoB64;
      body.logo_x = criacaoState.logoX;
      body.logo_y = criacaoState.logoY;
      body.logo_scale_pct = criacaoState.logoScalePct;
      body.logo_opacity = criacaoState.logoOpacity;
    }
    const res = await fetch('/api/thumbnail/highres', { method: 'POST', headers, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);

    const hqB64 = data.frame_b64 || null;
    if (!hqB64) throw new Error('Servidor não retornou frame HQ');
    nextHqUrl = _blobUrlFromBase64(hqB64, 'image/jpeg');
    await _preloadImageSrc(nextHqUrl);

    _revokeLogoPreviewHqUrl();
    criacaoState.logoPreviewHqFrame = null;
    criacaoState.logoPreviewHqUrl = nextHqUrl;
    criacaoState.logoPreviewHqInfo = (data.width && data.height) ? `${data.width}×${data.height}` : 'HQ';
    criacaoState.logoPreviewHqWidth = parseInt(data.width || '0', 10) || 0;
    criacaoState.logoPreviewHqHeight = parseInt(data.height || '0', 10) || 0;
    criacaoState.logoPreviewComposited = shouldCompositeLogoInHq && !!data.composited_logo;
    criacaoState.logoPreviewHqLoading = false;
    criacaoState.logoPreviewBgVisible = true;

    if (criacaoState.step === 1) {
      _syncLogoPreviewDom();
    } else {
      renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    }
    _persistWizardState();
    if (!silent) {
      toast('Frame HQ ' + (data.width && data.height ? data.width + 'x' + data.height : '') + ' carregado', 'good');
    }
  } catch (e) {
    _revokeObjectUrl(nextHqUrl);
    criacaoState.logoPreviewHqLoading = false;
    criacaoState.logoPreviewComposited = false;
    criacaoState.logoPreviewHqWidth = 0;
    criacaoState.logoPreviewHqHeight = 0;
    if (criacaoState.step === 1) {
      _syncLogoPreviewDom();
    } else {
      renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    }
    if (!silent) {
      toast('Erro ao carregar frame HQ: ' + e.message, 'bad');
    }
  }
}

async function loadHighResThumbnailFrame() {
  const frameIdx = _currentThumbFrameIdx();
  const objectKey = criacaoState.thumbVideoObjectKey || criacaoState.burnedObjectKey || criacaoState.teaserSourceObjectKey || '';
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  if (!objectKey) return toast('Selecione um vídeo queimado para extrair frame HQ', 'bad');
  criacaoState.thumbAutoHqTried = true;

  const st = qs('thumbHQStatus');
  if (st) st.textContent = '⏳ Extraindo frame em alta qualidade do vídeo…';

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch('/api/thumbnail/highres', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        run_id: criacaoState.runId,
        frame_index: frameIdx,
        frames_count: (criacaoState.frames || []).length || 10,
        object_key: objectKey,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) {
      throw new Error(data.detail || data.error || `Erro ${res.status}`);
    }

    criacaoState.thumbSourceB64 = data.frame_b64 || null;
    criacaoState.thumbSourceFrameIdx = frameIdx;
    criacaoState.thumbSourceInfo = data.width && data.height
      ? `Frame HQ carregado (${data.width}x${data.height})`
      : 'Frame HQ carregado';
    criacaoState.thumbVideoObjectKey = objectKey;
    _persistWizardState();

    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    toast('Frame HQ carregado para a thumbnail', 'good');
  } catch (e) {
    if (st) st.textContent = `Erro ao extrair frame HQ: ${e.message}`;
    toast('Erro ao carregar frame HQ: ' + e.message, 'bad');
  }
}

function _extractFirstSubtitleLine(srtContent) {
  const lines = (srtContent || '').split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  for (const line of lines) {
    if (/^\d+$/.test(line)) continue;
    if (/^\d{2}:\d{2}:\d{2},\d{3}\s+-->/.test(line)) continue;
    return line;
  }
  return '';
}

function updateSubtitlePreview() {
  const preview = qs('subtitlePreviewText');
  if (!preview) return;
  const size = _clamp(parseInt(qs('burnFontSize')?.value || criacaoState.burnFontSize || '22', 10) || 22, 6, 72);
  const colorKey = qs('burnFontColor')?.value || criacaoState.burnFontColor || 'white';
  const delay = _toNum(qs('burnSubDelay')?.value, criacaoState.burnSubDelay || 0, -30, 30);
  criacaoState.burnFontSize = size;
  criacaoState.burnFontColor = colorKey;
  criacaoState.burnSubDelay = delay;

  const colorMap = {
    white: '#f7f7f7',
    yellow: '#fff04a',
    cyan: '#39e7ff',
    orange: '#ffb347',
    black: '#050505',
  };
  const cssColor = colorMap[colorKey] || colorMap.white;
  const fromEditor = qs('transcriptSrtEdit')?.value || criacaoState.transcriptDraft || '';
  const text = _extractFirstSubtitleLine(fromEditor) || 'Preview da legenda na tela';
  const cssSize = Math.round(size * 1.18);
  preview.textContent = text;
  preview.style.fontSize = `${cssSize}px`;
  preview.style.color = cssColor;
  preview.style.textShadow = colorKey === 'black'
    ? '0 0 2px #fff, 0 1px 3px rgba(255,255,255,.75)'
    : '0 0 2px #000, 0 2px 4px #000, 0 0 8px rgba(0,0,0,.85)';
  const hint = qs('subtitlePreviewHint');
  if (hint) hint.textContent = `Tamanho ${size}px · ${colorKey} · delay ${delay >= 0 ? '+' : ''}${delay}s`;
}

function useFirstSubtitleAsThumbCaption() {
  const ta = qs('transcriptSrtEdit');
  const fromEditor = ta ? ta.value : criacaoState.transcriptDraft;
  const text = _extractFirstSubtitleLine(fromEditor);
  if (!text) return toast('Não encontrei texto de legenda para usar na thumbnail', 'bad');
  const input = qs('thumbSubtitleInput');
  if (input) input.value = text;
  updateThumbSubtitle(text);
  drawThumbWithLogo(true);
}

async function _loadTranscriptIntoEditor(runId) {
  const ta = qs('transcriptSrtEdit');
  const st = qs('transcriptStatus');
  if (!ta) return;
  try {
    const r = await fetch(`/runs/${runId}/srt`, { headers: state.apiKey ? { 'X-API-Key': state.apiKey } : {} });
    if (r.ok) {
      const text = await r.text();
      ta.value = text;
      criacaoState.transcriptDraft = text;
      criacaoState.hasTranscript = !!text.trim();
      const burnBtn = document.querySelector('button[onclick=\"triggerBurnSubs()\"]');
      if (burnBtn) burnBtn.disabled = !criacaoState.hasTranscript;
      if (st) st.textContent = 'SRT carregado do servidor.';
      _srtUpdateStats();
      updateSubtitlePreview();
      return;
    }
    ta.value = '';
    if (st) st.textContent = 'Sem transcrição — transcreva o vídeo para gerar o SRT.';
  } catch (e) {
    ta.value = '';
  }
  updateSubtitlePreview();
}

function loadBurnLogo(input) {
  const file = input.files?.[0];
  if (!file) return;
  const list = _burnLogoList();
  const targetCount = _clamp(parseInt(criacaoState.burnLogoTargetCount || 1, 10) || 1, 1, BURN_LOGO_MAX_COUNT);
  const allowedCount = Math.min(targetCount, BURN_LOGO_MAX_COUNT);
  if (list.length >= allowedCount) {
    if (input) input.value = '';
    return toast(`Quantidade definida: ${allowedCount} logo(s). Aumente a quantidade ou remova uma logo para adicionar outra.`, 'bad');
  }
  const inferredCompanyName = String(file.name || '')
    .replace(/\.[a-z0-9]+$/i, '')
    .replace(/[_-]+/g, ' ')
    .trim()
    .slice(0, 80);
  const reader = new FileReader();
  reader.onload = e => {
    _syncCriacaoDraftsFromDom();
    const logo = _burnNormalizeLogo({
      name: file.name,
      src: String(e.target.result || ''),
      mime: String(file.type || '').toLowerCase(),
      x: criacaoState.logoX,
      y: criacaoState.logoY,
      scale_pct: criacaoState.logoScalePct,
      opacity: criacaoState.logoOpacity,
      enabled: true,
    });
    list.push(logo);
    criacaoState.burnLogos = list.slice(0, BURN_LOGO_MAX_COUNT);
    criacaoState.burnLogoActiveIdx = Math.max(0, criacaoState.burnLogos.length - 1);
    _syncLegacyLogoFromActiveBurnLogo();
    criacaoState.logoProfileLayoutLinked = false;
    if (!String(criacaoState.logoCompanyDraftName || '').trim() && inferredCompanyName) {
      criacaoState.logoCompanyDraftName = inferredCompanyName;
    }
    criacaoState.logoPresetChoice = 'saved';
    _syncMainLogoIntoThumbElements();
    const st = qs('burnLogoStatus');
    if (st) {
      const companySuffix = criacaoState.logoProfileName ? ` · empresa: ${criacaoState.logoProfileName}` : '';
      st.textContent = `✓ ${criacaoState.burnLogos.length} logo(s) carregada(s)${companySuffix}`;
    }
    _invalidateLogoPreviewComposited();
    _persistWizardState({ immediate: true });
    drawThumbWithLogo(false);
    if (criacaoState.runId) renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    _scheduleLogoPreviewHqRefresh();
  };
  reader.readAsDataURL(file);
  if (input) input.value = '';
}

function loadLogo(input) {
  loadBurnLogo(input);
}

function setBurnLogoTargetCount(value) {
  criacaoState.burnLogoTargetCount = _clamp(parseInt(value, 10) || 1, 1, BURN_LOGO_MAX_COUNT);
  _persistWizardState();
  if (criacaoState.runId) renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function selectBurnLogo(idx) {
  const list = _burnLogoList();
  if (!list.length) return;
  criacaoState.burnLogoActiveIdx = _clamp(parseInt(idx, 10) || 0, 0, list.length - 1);
  _syncLegacyLogoFromActiveBurnLogo();
  _persistWizardState();
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function removeBurnLogo(idx) {
  const list = _burnLogoList();
  const i = parseInt(idx, 10);
  if (!Number.isInteger(i) || i < 0 || i >= list.length) return;
  list.splice(i, 1);
  criacaoState.burnLogos = list;
  criacaoState.burnLogoActiveIdx = _clamp(criacaoState.burnLogoActiveIdx, 0, Math.max(0, list.length - 1));
  if (list.length) {
    _syncLegacyLogoFromActiveBurnLogo();
  } else {
    _syncLegacyLogoFromBurnLogo(null);
    _syncMainLogoIntoThumbElements();
  }
  criacaoState.logoProfileLayoutLinked = false;
  _invalidateLogoPreviewComposited();
  _persistWizardState({ immediate: true });
  drawThumbWithLogo(false);
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function clearBurnLogos() {
  criacaoState.burnLogos = [];
  criacaoState.burnLogoActiveIdx = 0;
  _syncLegacyLogoFromBurnLogo(null);
  _syncMainLogoIntoThumbElements();
  criacaoState.logoProfileLayoutLinked = false;
  _invalidateLogoPreviewComposited();
  _persistWizardState({ immediate: true });
  drawThumbWithLogo(false);
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
}

function _setLogoPos(x, y, opts = {}) {
  const persist = opts.persist !== false;
  const refreshHq = opts.refreshHq !== false;
  const redrawThumb = opts.redrawThumb !== false;
  const xEl = qs('logoX');
  const yEl = qs('logoY');
  const xNumEl = qs('logoXNum');
  const yNumEl = qs('logoYNum');
  if (x !== undefined) {
    criacaoState.logoX = _toNum(x, criacaoState.logoX, 0, 100);
  } else if (xEl) {
    criacaoState.logoX = _toNum(xEl.value, criacaoState.logoX, 0, 100);
  }
  if (y !== undefined) {
    criacaoState.logoY = _toNum(y, criacaoState.logoY, 0, 100);
  } else if (yEl) {
    criacaoState.logoY = _toNum(yEl.value, criacaoState.logoY, 0, 100);
  }

  if (xEl) xEl.value = String(criacaoState.logoX);
  if (yEl) yEl.value = String(criacaoState.logoY);
  if (xNumEl) xNumEl.value = criacaoState.logoX.toFixed(1);
  if (yNumEl) yNumEl.value = criacaoState.logoY.toFixed(1);

  const xLbl = qs('logoXVal');
  const yLbl = qs('logoYVal');
  if (xLbl) xLbl.textContent = `${criacaoState.logoX.toFixed(1)}%`;
  if (yLbl) yLbl.textContent = `${criacaoState.logoY.toFixed(1)}%`;
  const xyReadout = qs('logoXYReadout');
  if (xyReadout) xyReadout.textContent = `X ${criacaoState.logoX.toFixed(1)}% · Y ${criacaoState.logoY.toFixed(1)}%`;
  // Update active logo directly in criacaoState.burnLogos (avoid double _burnLogoList re-normalization)
  _burnLogoList(); // ensure criacaoState.burnLogos is populated/filtered
  const _activeIdx = _burnActiveLogoIndex();
  const _burnArr = criacaoState.burnLogos;
  if (Array.isArray(_burnArr) && _burnArr[_activeIdx]) {
    _burnArr[_activeIdx].x = criacaoState.logoX;
    _burnArr[_activeIdx].y = criacaoState.logoY;
    _burnArr[_activeIdx].sync_main = false;
  }
  _markLogoProfileLayoutCustomIfNeeded();

  if (!refreshHq) _beginLogoLiveEdit();
  _updateLogoPreviewOverlay();
  if (_syncInheritedTeaserLogosFromMain()) _updateTeaserLogoPreview();
  if (refreshHq) {
    _invalidateLogoPreviewComposited();
    _scheduleLogoPreviewHqRefresh();
  }
  if (persist) _persistWizardState();
  if (redrawThumb) drawThumbWithLogo(false);
}

function _setLogoStyle(scalePct, opacityPct, opts = {}) {
  const persist = opts.persist !== false;
  const refreshHq = opts.refreshHq !== false;
  const redrawThumb = opts.redrawThumb !== false;
  const sEl = qs('logoScale');
  const oEl = qs('logoOpacity');
  const sNumEl = qs('logoScaleNum');
  const oNumEl = qs('logoOpacityNum');
  if (scalePct !== undefined) {
    criacaoState.logoScalePct = _toNum(scalePct, criacaoState.logoScalePct, 5, 100);
  } else if (sEl) {
    criacaoState.logoScalePct = _toNum(sEl.value, criacaoState.logoScalePct, 5, 100);
  }
  if (opacityPct !== undefined) {
    criacaoState.logoOpacity = _toNum(opacityPct, criacaoState.logoOpacity, 5, 100);
  } else if (oEl) {
    criacaoState.logoOpacity = _toNum(oEl.value, criacaoState.logoOpacity, 5, 100);
  }
  if (sEl) sEl.value = String(criacaoState.logoScalePct);
  if (oEl) oEl.value = String(criacaoState.logoOpacity);
  if (sNumEl) sNumEl.value = criacaoState.logoScalePct.toFixed(1);
  if (oNumEl) oNumEl.value = criacaoState.logoOpacity.toFixed(0);

  const sLbl = qs('logoScaleVal');
  const oLbl = qs('logoOpacityVal');
  if (sLbl) sLbl.textContent = `${criacaoState.logoScalePct.toFixed(1)}%`;
  if (oLbl) oLbl.textContent = `${criacaoState.logoOpacity.toFixed(0)}%`;
  const active = _burnActiveLogo();
  if (active) {
    active.scale_pct = criacaoState.logoScalePct;
    active.opacity = criacaoState.logoOpacity;
    active.sync_main = false;
  }
  _markLogoProfileLayoutCustomIfNeeded();

  if (!refreshHq) _beginLogoLiveEdit();
  _updateLogoPreviewOverlay();
  if (_syncInheritedTeaserLogosFromMain()) _updateTeaserLogoPreview();
  if (refreshHq) {
    _invalidateLogoPreviewComposited();
    _scheduleLogoPreviewHqRefresh();
  }
  if (persist) _persistWizardState();
  if (redrawThumb) drawThumbWithLogo(false);
}

function _syncBurnLogoControlValues(logo = null) {
  const active = logo || _burnActiveLogo();
  const x = active ? _toNum(active.x, criacaoState.logoX, 0, 100) : _toNum(criacaoState.logoX, 97, 0, 100);
  const y = active ? _toNum(active.y, criacaoState.logoY, 0, 100) : _toNum(criacaoState.logoY, 97, 0, 100);
  const scale = active ? _toNum(active.scale_pct, criacaoState.logoScalePct, 5, 100) : _toNum(criacaoState.logoScalePct, 20, 5, 100);
  const opacity = active ? _toNum(active.opacity, criacaoState.logoOpacity, 5, 100) : _toNum(criacaoState.logoOpacity, 85, 5, 100);
  const setValue = (id, value) => {
    const el = qs(id);
    if (el) el.value = String(value);
  };
  const setText = (id, text) => {
    const el = qs(id);
    if (el) el.textContent = text;
  };
  setValue('logoX', x);
  setValue('logoY', y);
  setValue('logoScale', scale);
  setValue('logoOpacity', opacity);
  setValue('logoXNum', x.toFixed(1));
  setValue('logoYNum', y.toFixed(1));
  setValue('logoScaleNum', scale.toFixed(1));
  setValue('logoOpacityNum', opacity.toFixed(0));
  setText('logoXVal', `${x.toFixed(1)}%`);
  setText('logoYVal', `${y.toFixed(1)}%`);
  setText('logoScaleVal', `${scale.toFixed(1)}%`);
  setText('logoOpacityVal', `${opacity.toFixed(0)}%`);
  setText('logoXYReadout', `X ${x.toFixed(1)}% · Y ${y.toFixed(1)}%`);
}

function _syncBurnLogoActiveUi() {
  const activeIdx = _burnActiveLogoIndex();
  document.querySelectorAll('[data-burn-logo-index]').forEach((el) => {
    el.classList.toggle('active', parseInt(el.dataset.burnLogoIndex || '-1', 10) === activeIdx);
  });
  _syncBurnLogoControlValues(_burnActiveLogo());
  _updateLogoPreviewOverlay();
}

function _commitLogoLayoutChange(opts = {}) {
  const refreshHq = opts.refreshHq !== false;
  const persist = opts.persist !== false;
  const redrawThumb = opts.redrawThumb !== false;
  _syncLegacyLogoFromActiveBurnLogo();
  _markLogoProfileLayoutCustomIfNeeded();
  if (refreshHq) {
    _invalidateLogoPreviewComposited();
    _scheduleLogoPreviewHqRefresh();
  }
  if (persist) _persistWizardState();
  if (redrawThumb) drawThumbWithLogo(false);
}

function _togglePreviewBg() {
  const bg = qs('logoPreviewBg');
  const btn = qs('btnToggleBg');
  if (!bg) return;
  const isHidden = bg.classList.toggle('hidden');
  criacaoState.logoPreviewBgVisible = !isHidden;
  if (btn) btn.textContent = isHidden ? 'Mostrar vídeo' : 'Ocultar vídeo';
}

function _updateLogoPreviewOverlay() {
  const wrap = qs('logoPreviewWrap');
  if (!wrap) return;
  const logos = _burnLogoList();
  const overlays = Array.from(wrap.querySelectorAll('.burn-logo-preview-overlay'));
  if (!overlays.length || !logos.length) return;
  if (_logoPreviewOverlayRaf) return;
  _logoPreviewOverlayRaf = requestAnimationFrame(() => {
    _logoPreviewOverlayRaf = null;
    const activeIdx = _burnActiveLogoIndex();
    const cw = wrap.clientWidth || 1;
    const ch = wrap.clientHeight || 1;
    overlays.forEach((overlay) => {
      const idx = parseInt(overlay.dataset.logoIndex || '-1', 10);
      const logo = logos[idx];
      if (!logo) return;
      const scalePct = _toNum(logo.scale_pct, 20, 5, 100);
      overlay.classList.toggle('active', idx === activeIdx);
      overlay.style.width = `${scalePct}%`;
      overlay.style.opacity = `${_toNum(logo.opacity, 85, 5, 100) / 100}`;
      const lw = overlay.offsetWidth || (cw * scalePct / 100);
      const lh = overlay.offsetHeight || (lw * 0.35);
      const xPx = (cw - lw) * (_toNum(logo.x, 97, 0, 100) / 100);
      const yPx = (ch - lh) * (_toNum(logo.y, 97, 0, 100) / 100);
      overlay.style.left = '0px';
      overlay.style.top = '0px';
      overlay.style.transform = `translate3d(${_clamp(xPx, 0, Math.max(0, cw - lw))}px, ${_clamp(yPx, 0, Math.max(0, ch - lh))}px, 0)`;
    });
  });
}

function nudgeLogo(dx, dy) {
  const active = _burnActiveLogo();
  const baseX = active ? _toNum(active.x, criacaoState.logoX, 0, 100) : _toNum(criacaoState.logoX, 97, 0, 100);
  const baseY = active ? _toNum(active.y, criacaoState.logoY, 0, 100) : _toNum(criacaoState.logoY, 97, 0, 100);
  _setLogoPos(
    _clamp(baseX + (dx || 0), 0, 100),
    _clamp(baseY + (dy || 0), 0, 100),
  );
}

function startLogoDrag(ev) {
  startBurnLogoDrag(ev, _burnActiveLogoIndex());
}

function startBurnLogoDrag(ev, idx) {
  const logoIdx = parseInt(idx, 10);
  const list = _burnLogoList();
  if (!Number.isInteger(logoIdx) || logoIdx < 0 || logoIdx >= list.length) return;
  const wrap = qs('logoPreviewWrap');
  const overlay = wrap?.querySelector(`.burn-logo-preview-overlay[data-logo-index="${logoIdx}"]`);
  if (!wrap || !overlay) return;
  ev.preventDefault();
  criacaoState.burnLogoActiveIdx = logoIdx;
  const logo = list[logoIdx];
  _beginLogoLiveEdit();
  _syncLegacyLogoFromBurnLogo(logo);
  _syncBurnLogoActiveUi();
  try { overlay.setPointerCapture?.(ev.pointerId); } catch (_) {}

  const move = (e) => {
    const point = { x: e.clientX, y: e.clientY };
    const rect = wrap.getBoundingClientRect();
    const ovRect = overlay.getBoundingClientRect();
    const scalePct = _toNum(logo.scale_pct, 20, 5, 100);
    const lw = ovRect.width || rect.width * (scalePct / 100);
    const lh = ovRect.height || lw * 0.35;
    let xPx = point.x - rect.left - (lw / 2);
    let yPx = point.y - rect.top - (lh / 2);
    xPx = _clamp(xPx, 0, Math.max(0, rect.width - lw));
    yPx = _clamp(yPx, 0, Math.max(0, rect.height - lh));
    const xPct = (rect.width - lw) > 0 ? (xPx / (rect.width - lw)) * 100 : 0;
    const yPct = (rect.height - lh) > 0 ? (yPx / (rect.height - lh)) * 100 : 0;
    logo.x = _clamp(xPct, 0, 100);
    logo.y = _clamp(yPct, 0, 100);
    _syncLegacyLogoFromBurnLogo(logo);
    _syncBurnLogoControlValues(logo);
    _updateLogoPreviewOverlay();
  };

  const up = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    window.removeEventListener('pointercancel', up);
    logo.sync_main = false;
    try { overlay.releasePointerCapture?.(ev.pointerId); } catch (_) {}
    _commitLogoLayoutChange();
  };

  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
  window.addEventListener('pointercancel', up);
  move(ev);
}

async function onTranslateLangChange() {
  const langSel = qs('transcribeLang');
  const ta = qs('transcriptSrtEdit');
  const st = qs('transcriptStatus');
  if (!langSel || !ta) return;

  const targetLang = langSel.value;
  criacaoState.transcribeTargetLang = targetLang || '';
  _persistWizardState();
  const srt = ta.value.trim();

  // Sem idioma selecionado: nada a fazer
  if (!targetLang) {
    if (st) st.textContent = 'Idioma original — nenhuma tradução aplicada.';
    return;
  }

  // Sem SRT ainda: só informa que a próxima transcrição já vai traduzir
  if (!srt) {
    if (st) st.textContent = `Idioma selecionado: ${targetLang.toUpperCase()}. Transcreva para gerar o SRT traduzido.`;
    return;
  }

  // Tem SRT → traduz imediatamente
  if (st) st.textContent = `⏳ Traduzindo para ${targetLang.toUpperCase()}…`;
  langSel.disabled = true;

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch('/api/translate-srt', {
      method: 'POST',
      headers,
      body: JSON.stringify({ srt, target_lang: targetLang }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(data.detail || data.error || `Erro ${res.status}`);
    }
    ta.value = data.srt;
    criacaoState.transcriptDraft = data.srt;
    updateSubtitlePreview();
    if (st) st.textContent = `✓ SRT traduzido para ${targetLang.toUpperCase()} (${data.segments_count} segmentos). Revise e salve se necessário.`;
    toast(`Tradução para ${targetLang.toUpperCase()} aplicada no editor!`, 'good');
  } catch (e) {
    if (st) st.textContent = `Erro na tradução: ${e.message}`;
    toast('Erro ao traduzir: ' + e.message, 'bad');
  } finally {
    langSel.disabled = false;
  }
}

function _transcribeLangLabel(code) {
  return ({
    pt: 'Português',
    en: 'English',
    es: 'Español',
    fr: 'Français',
    de: 'Deutsch',
    it: 'Italiano',
    ja: '日本語',
    zh: '中文',
    auto: 'Auto',
  })[code] || code || 'Auto';
}

async function reTranscribe(provider) {
  const videoObjectKey = (() => {
    try {
      return _resolveOriginalVideoObjectKey();
    } catch {
      return '';
    }
  })();
  if (!videoObjectKey) return toast('Este run não tem video_object_key — não é possível transcrever', 'bad');

  const targetLang = (qs('transcribeLang')?.value || '').trim();
  const sourceLang = (qs('transcribeSourceLang')?.value || criacaoState.transcribeSourceLang || 'pt').trim();
  const adultMode = qs('transcribeAdultMode')?.checked !== false;
  const includeVocalizations = qs('transcribeIncludeVocalizations')?.checked !== false;
  criacaoState.transcribeSourceLang = sourceLang || 'pt';
  criacaoState.transcribeTargetLang = targetLang || '';
  criacaoState.transcribeAdultMode = adultMode;
  criacaoState.transcribeIncludeVocalizations = includeVocalizations;
  const targetLabel = _transcribeLangLabel(targetLang);
  const sourceLabel = _transcribeLangLabel(sourceLang);
  const ta = qs('transcriptSrtEdit');
  const st = qs('transcriptStatus');
  if (st) {
    const providerLabel = provider === 'local'
      ? 'localmente'
      : provider === 'whisper_sync'
        ? 'Whisper Sync…'
      : provider === 'deepgram'
        ? 'Deepgram Sync…'
      : provider === 'assemblyai'
        ? 'AssemblyAI…'
        : (provider === 'groq' || provider === 'openrouter')
          ? 'OpenRouter STT…'
        : provider === 'auto'
          ? 'modo estrito/local…'
          : `${provider}…`;
    const base = provider === 'local'
      ? '⏳ Transcrevendo localmente…'
      : `⏳ Transcrevendo com ${providerLabel}`;
    st.textContent = targetLang
      ? `${base} fala em ${sourceLabel}, traduzindo para ${targetLabel || targetLang}…`
      : `${base} fala em ${sourceLabel}…`;
  }

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const body = { video_object_key: videoObjectKey, provider };
    if (sourceLang && sourceLang !== 'auto') body.language = sourceLang;
    body.adult_mode = adultMode;
    body.include_vocalizations = includeVocalizations;
    body.enhance_audio = true;
    if (targetLang) body.translate_to = targetLang;
    const res = await fetch('/transcribe', {
      method: 'POST', headers,
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.detail || data.error);
    const srt = data.transcript?.srt || '';
    if (ta) ta.value = srt;
    criacaoState.transcriptDraft = srt;
    updateSubtitlePreview();
    if (st) {
      if (data.transcript?.translated && (data.transcript?.target_lang || targetLang)) {
        st.textContent = `✓ Transcrição traduzida para ${(data.transcript?.target_lang || targetLang).toUpperCase()} pronta para revisão.`;
      } else {
        const usedProvider = data.transcript?.provider || provider;
        st.textContent = `✓ Transcrição pronta (${usedProvider}).`;
      }
    }
    criacaoState.hasTranscript = !!srt.trim();
    await _saveTranscriptData(data.transcript);
    const usedProvider = data.transcript?.provider || provider;
    toast(data.transcript?.translated ? `Transcrição e tradução concluídas via ${usedProvider} — SRT salvo!` : `Transcrição concluída via ${usedProvider} — SRT salvo!`, 'good');
  } catch (e) {
    if (st) st.textContent = `Erro: ${e.message}`;
    toast('Erro: ' + e.message, 'bad');
  }
}

// ═══════════════════════════════════════════════════════════════════
// SRT EDITOR PROFISSIONAL — Find/Replace, Stats, Quick Fix
// ═══════════════════════════════════════════════════════════════════
const _srtFind = { matches: [], idx: 0 };

function _srtEditorInit() {
  const ta = qs('transcriptSrtEdit');
  if (!ta) return;
  ta.addEventListener('input', () => {
    _syncCriacaoDraftsFromDom();
    _srtUpdateStats();
    updateSubtitlePreview();
    if (qs('srtFindInput')?.value) _srtFindChange();
  });
  ta.addEventListener('keyup', _srtUpdateCursor);
  ta.addEventListener('click', _srtUpdateCursor);
  ta.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'h' || e.key === 'f')) {
      e.preventDefault();
      _srtToggleFindReplace(true);
    }
  });
  _srtUpdateStats();
  _srtUpdateCursor();
  // F3 / Shift+F3 para next/prev no documento inteiro
  const _onDocKey = e => {
    if (!qs('transcriptSrtEdit')) { document.removeEventListener('keydown', _onDocKey); return; }
    if (e.key === 'Escape' && qs('srtFindPanel')?.style.display !== 'none') { _srtToggleFindReplace(false); }
    if (e.key === 'F3') { e.preventDefault(); e.shiftKey ? _srtFindPrev() : _srtFindNext(); }
  };
  document.addEventListener('keydown', _onDocKey);
}

function _srtUpdateStats() {
  const ta = qs('transcriptSrtEdit');
  const el = qs('srtStats');
  if (!ta || !el) return;
  const txt = ta.value;
  const segs = (txt.match(/^\d+\s*$/gm) || []).length;
  const words = txt
    .split('\n')
    .filter(l => l.trim() && !/^\d+$/.test(l.trim()) && !/-->/.test(l))
    .join(' ')
    .split(/\s+/)
    .filter(w => w).length;
  el.textContent = `${segs} segmentos · ${words} palavras · ${txt.length} chars`;
}

function _srtUpdateCursor() {
  const ta = qs('transcriptSrtEdit');
  const el = qs('srtCursor');
  if (!ta || !el) return;
  const before = ta.value.substring(0, ta.selectionStart);
  const lines = before.split('\n');
  el.textContent = `Linha ${lines.length}, Col ${lines[lines.length - 1].length + 1}`;
}

function _srtToggleFindReplace(force) {
  const panel = qs('srtFindPanel');
  if (!panel) return;
  const show = force !== undefined ? force : panel.style.display === 'none';
  panel.style.display = show ? 'block' : 'none';
  if (show) {
    const fi = qs('srtFindInput');
    if (fi) { fi.focus(); fi.select(); }
  } else {
    _srtFind.matches = [];
    _srtFind.idx = 0;
    const c = qs('srtMatchCount');
    if (c) { c.textContent = ''; c.className = 'srt-match-count'; }
  }
}

function _srtBuildRegex() {
  const term = qs('srtFindInput')?.value || '';
  if (!term) return null;
  const mc  = qs('srtMatchCase')?.checked;
  const wb  = qs('srtWholeWord')?.checked;
  const esc = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pat = wb ? `\\b${esc}\\b` : esc;
  try { return new RegExp(pat, mc ? 'g' : 'gi'); } catch { return null; }
}

function _srtFindChange() {
  const ta = qs('transcriptSrtEdit');
  const countEl = qs('srtMatchCount');
  if (!ta) return;
  _srtFind.matches = [];
  _srtFind.idx = 0;
  const re = _srtBuildRegex();
  if (!re) { if (countEl) { countEl.textContent = ''; countEl.className = 'srt-match-count'; } return; }
  let m;
  const txt = ta.value;
  while ((m = re.exec(txt)) !== null && _srtFind.matches.length < 5000) {
    _srtFind.matches.push({ start: m.index, end: m.index + m[0].length });
  }
  const total = _srtFind.matches.length;
  if (countEl) {
    countEl.textContent = total ? `1 / ${total}` : 'sem resultado';
    countEl.className = 'srt-match-count' + (total ? '' : ' no-match');
  }
  if (total) _srtScrollToMatch(ta, 0);
}

function _srtFindKey(e) {
  if (e.key === 'Enter') { e.shiftKey ? _srtFindPrev() : _srtFindNext(); }
  if (e.key === 'Escape') _srtToggleFindReplace(false);
}

function _srtReplaceKey(e) {
  if (e.key === 'Enter') _srtReplaceCurrent();
  if (e.key === 'Escape') _srtToggleFindReplace(false);
}

function _srtFindNext() {
  if (!_srtFind.matches.length) return;
  _srtFind.idx = (_srtFind.idx + 1) % _srtFind.matches.length;
  _srtScrollToMatch(qs('transcriptSrtEdit'), _srtFind.idx);
  _srtSyncCount();
}

function _srtFindPrev() {
  if (!_srtFind.matches.length) return;
  _srtFind.idx = (_srtFind.idx - 1 + _srtFind.matches.length) % _srtFind.matches.length;
  _srtScrollToMatch(qs('transcriptSrtEdit'), _srtFind.idx);
  _srtSyncCount();
}

function _srtSyncCount() {
  const c = qs('srtMatchCount');
  if (c && _srtFind.matches.length) c.textContent = `${_srtFind.idx + 1} / ${_srtFind.matches.length}`;
}

function _srtScrollToMatch(ta, idx) {
  if (!ta || !_srtFind.matches[idx]) return;
  const { start, end } = _srtFind.matches[idx];
  ta.focus();
  ta.setSelectionRange(start, end);
  const linesBefore = ta.value.substring(0, start).split('\n').length;
  ta.scrollTop = Math.max(0, (linesBefore - 5) * 19);
}

function _srtReplaceCurrent() {
  const ta = qs('transcriptSrtEdit');
  const replVal = qs('srtReplaceInput')?.value ?? '';
  if (!ta || !_srtFind.matches.length) return;
  const { start, end } = _srtFind.matches[_srtFind.idx];
  ta.value = ta.value.substring(0, start) + replVal + ta.value.substring(end);
  criacaoState.transcriptDraft = ta.value;
  _srtUpdateStats();
  _srtFindChange();
  if (_srtFind.matches.length) {
    const newPos = start + replVal.length;
    const ni = _srtFind.matches.findIndex(x => x.start >= newPos);
    _srtFind.idx = ni >= 0 ? ni : 0;
    _srtScrollToMatch(ta, _srtFind.idx);
    _srtSyncCount();
  }
}

function _srtReplaceAll() {
  const ta = qs('transcriptSrtEdit');
  const replVal = qs('srtReplaceInput')?.value ?? '';
  if (!ta) return;
  const re = _srtBuildRegex();
  if (!re) return toast('Digite o texto a buscar', 'bad');
  const count = (ta.value.match(re) || []).length;
  if (!count) return toast('Nenhuma ocorrência encontrada', 'bad');
  ta.value = ta.value.replace(re, replVal);
  criacaoState.transcriptDraft = ta.value;
  _srtFind.matches = [];
  const c = qs('srtMatchCount');
  if (c) { c.textContent = ''; c.className = 'srt-match-count'; }
  _srtUpdateStats();
  toast(`${count} substituição${count !== 1 ? 'ões' : ''} realizada${count !== 1 ? 's' : ''}!`, 'good');
}

function _srtQuickFix(action) {
  const ta = qs('transcriptSrtEdit');
  if (!ta) return;
  let txt = ta.value;
  if (action === 'fillers') {
    const fillers = ['\\buh+\\b', '\\bum+\\b', '\\bah+\\b', '\\beh+\\b', '\\bhmm*\\b', '\\bné\\b', '\\btipo\\b', '\\bassim\\b', '\\baf+\\b'];
    let total = 0;
    fillers.forEach(f => {
      const re = new RegExp(f, 'gi');
      const hits = (txt.match(re) || []).length;
      total += hits;
      txt = txt.replace(re, '');
    });
    txt = txt.replace(/ {2,}/g, ' ').replace(/ ,/g, ',').replace(/ \./g, '.');
    if (!total) return toast('Nenhum filler encontrado', 'bad');
    toast(`${total} filler${total !== 1 ? 's' : ''} removido${total !== 1 ? 's' : ''}!`, 'good');
  } else if (action === 'trim_blank') {
    txt = txt.replace(/\n{3,}/g, '\n\n').trim();
    toast('Linhas extras removidas', 'good');
  } else if (action === 'renumber') {
    let n = 1;
    txt = txt.replace(/^(\d+)(\r?\n\d{2}:\d{2}:\d{2})/gm, () => `${n++}$2`);
    toast('Entradas renumeradas', 'good');
  }
  ta.value = txt;
  criacaoState.transcriptDraft = txt;
  _srtUpdateStats();
}
// ═══════════════════════════════════════════════════════════════════

async function saveTranscript() {
  const ta = qs('transcriptSrtEdit');
  if (!criacaoState.runId || !ta) return;
  const srt = ta.value.trim();
  criacaoState.transcriptDraft = srt;
  updateSubtitlePreview();
  await _saveTranscriptData({ srt, text: srt, segments: [] });
  criacaoState.hasTranscript = !!srt;
}

async function _saveTranscriptData(transcript) {
  const st = qs('transcriptStatus');
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch(`/runs/${criacaoState.runId}/transcript`, {
      method: 'PUT', headers,
      body: JSON.stringify({ transcript }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Erro ao salvar');
    if (st) st.textContent = '✓ SRT salvo.';
    toast('Transcrição salva!', 'good');
  } catch (e) {
    if (st) st.textContent = `Erro ao salvar: ${e.message}`;
    toast('Erro ao salvar: ' + e.message, 'bad');
  }
}

async function generatePost() {
  const btn = qs('btnGerarPost');
  if (!criacaoState.runId) return toast('Selecione um run primeiro', 'bad');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Gerando…';
  }
  try {
    const res = await apiFetch('/api/create-post', {
      method: 'POST',
      body: JSON.stringify({ video_id: criacaoState.runId }),
    });
    if (res.error) throw new Error(res.error + (res.detail ? ': ' + res.detail : ''));
    criacaoState.postResult = res;
    renderPostResult(res);
    toast('Post gerado!', 'good');
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '✦ Gerar Post XVideos';
    }
  }
}

function renderPostResult(res) {
  const area = qs('postResultArea');
  if (!area) return;

  const rec = res.recommended_thumbnail || {};
  const pd = res.post_data || {};
  const frameIdx = criacaoState.thumbFrameIdx != null
    ? criacaoState.thumbFrameIdx
    : (criacaoState.selectedFrameIdx != null ? criacaoState.selectedFrameIdx : (rec.frame_index ?? 0));
  const frame = _getThumbSourceForFrame(frameIdx);
  const frameSrc = _thumbFrameToSrc(frame);

  const teaserSrc = criacaoState.teaserUrl || '';
  const fullVideoSrc = criacaoState.teaserCombinedUrl || criacaoState.burnedVideoUrl || criacaoState.videoUrl || '';

  const tags = (pd.tags || []).map(t => `<span class="tag-chip">${esc(t)}</span>`).join('');
  const cats = (pd.categories || []).join(', ');

  area.innerHTML = `
    <div class="detail-section card" style="border-color:var(--pri);border-width:2px;">
      <div class="xv-section-label">▶ PREVIEW FINAL</div>

      <div class="row wrap" style="gap:12px;">
        <div class="col grow" style="min-width:260px;">
          <label>Vídeo completo</label>
          ${fullVideoSrc
            ? `<video id="xvVideo" controls playsinline preload="metadata" poster="${frameSrc}" style="width:100%;border-radius:8px;background:#000;"><source src="${fullVideoSrc}" type="video/mp4"></video>`
            : '<div class="criacao-empty">Sem vídeo completo</div>'}
          <div class="row" style="margin-top:8px;gap:8px;flex-wrap:wrap;">
            ${criacaoState.burnedVideoUrl ? '<button class="btn" onclick="downloadBurnedVideo()">⬇ Baixar legendado</button>' : ''}
            ${criacaoState.teaserCombinedUrl ? '<button class="btn" onclick="downloadCombinedVideo()">⬇ Baixar completo</button>' : ''}
            ${criacaoState.videoUrl ? '<button class="btn" onclick="downloadOriginalVideo()">⬇ Baixar original</button>' : ''}
            ${criacaoState.burnedObjectKey ? '<button class="btn" style="color:var(--bad);border-color:var(--bad);" onclick="deleteBurnedVideo()">🗑 Deletar queimado</button>' : ''}
          </div>
        </div>

        <div class="col grow" style="min-width:260px;">
          <label>Teaser</label>
          ${teaserSrc
            ? `<video controls playsinline preload="metadata" style="width:100%;border-radius:8px;background:#000;"><source src="${teaserSrc}" type="video/mp4"></video>`
            : '<div class="criacao-empty">Teaser ainda não gerado</div>'}
          ${teaserSrc ? '<div style="margin-top:8px;"><button class="btn" onclick="downloadTeaserVideo()">⬇ Baixar teaser</button></div>' : ''}
        </div>
      </div>
    </div>

    <div class="detail-section card">
      <h2>Thumbnail final</h2>
      ${frameSrc ? `
        <div class="post-thumb-wrap" id="thumbWrap">
          <img src="${frameSrc}" alt="thumb" class="post-thumb-img" id="thumbImg">
          <span class="post-thumb-badge">Thumbnail</span>
        </div>
        <canvas id="thumbCanvas" class="post-logo-canvas" style="display:none;margin-top:8px;"></canvas>
        <div class="row" style="margin-top:10px;gap:8px;">
          <button class="btn" onclick="drawThumbWithLogo(true)">Atualizar thumbnail</button>
          <button class="btn" onclick="downloadThumbnail()">⬇ Baixar thumbnail</button>
        </div>
      ` : '<div class="hint">Frame não disponível</div>'}
    </div>

    <div class="detail-section card">
      <h2>Dados do Post</h2>
      <div class="post-field">
        <label>Título (${(pd.title || '').length}/100)</label>
        <div class="output" style="max-height:60px;font-size:14px;font-weight:600;">${esc(pd.title || '')}</div>
        <button class="btn" style="margin-top:5px;" onclick="copyText(${JSON.stringify(pd.title || '')})">Copiar título</button>
      </div>
      ${(res.compare_titles && res.compare_titles.length > 1) ? `
      <div class="post-field">
        <label>Opções de título (${res.compare_titles.length})</label>
        <div class="output" style="max-height:120px;">
          ${res.compare_titles.map((t, i) => `<div style="margin-bottom:6px;padding:6px;background:rgba(255,255,255,0.05);border-radius:4px;">
            <strong>Opção ${String.fromCharCode(65 + i)}:</strong> ${esc(t)}
            <button class="btn" style="margin-left:8px;padding:2px 8px;font-size:11px;" onclick="copyText(${JSON.stringify(t)})">Copiar</button>
          </div>`).join('')}
        </div>
      </div>` : ''}
      <div class="post-field">
        <label>Hook primeiros 10s</label>
        <div class="output" style="max-height:60px;">${esc(pd.first_10s_hook || '')}</div>
      </div>
      <div class="post-field">
        <label>Descrição (${(pd.description || '').length} chars)</label>
        <div class="output">${esc(pd.description || '')}</div>
        <button class="btn" style="margin-top:5px;" onclick="copyText(${JSON.stringify(pd.description || '')})">Copiar descrição</button>
      </div>
      <div class="post-field">
        <label>Categorias</label>
        <div class="output" style="max-height:50px;">${esc(cats)}</div>
      </div>
      <div class="post-field">
        <label>Tags (${(pd.tags || []).length})</label>
        <div class="post-tags-wrap" style="margin-top:6px;">${tags}</div>
        <button class="btn" style="margin-top:8px;" onclick="copyText(${JSON.stringify((pd.tags || []).join(', '))})">Copiar tags</button>
      </div>
    </div>

    <div class="detail-section card">
      <h2>Texto pronto para copiar</h2>
      <pre class="output" id="readyToPostPre" style="max-height:320px;">${esc(res.ready_to_post || '')}</pre>
      <div class="row" style="margin-top:10px;gap:8px;">
        <button class="btn primary" onclick="copyText(qs('readyToPostPre').textContent)">Copiar tudo</button>
      </div>
    </div>

    <div class="detail-section card">
      <h2>Agendar post</h2>
      <div class="row" style="gap:10px;flex-wrap:wrap;align-items:flex-end;">
        <div class="col grow">
          <label class="hint">Data e hora</label>
          <input type="datetime-local" id="schedDateTime" style="margin-top:4px;">
        </div>
        <button class="btn primary" onclick="schedulePost()">📅 Agendar</button>
      </div>
    </div>
  `;

  drawThumbWithLogo(false);
}

function applyCmpTextAsPost() {
  if (!criacaoState.compareText) return;
  
  const title = criacaoState.compareTitles?.[0] || '';
  const description = criacaoState.compareDescription || criacaoState.compareText;
  const tags = criacaoState.compareTags || [];
  const first10sHook = criacaoState.compareFirst10sHook || '';
  
  const fakeResult = {
    recommended_thumbnail: {},
    post_data: { 
      title: title, 
      description: description, 
      tags: tags, 
      categories: [], 
      first_10s_hook: first10sHook 
    },
    ready_to_post: criacaoState.compareText,
    compare_titles: criacaoState.compareTitles || [],
  };
  criacaoState.postResult = fakeResult;
  criacaoState.compareText = null;
  criacaoState.compareTitles = [];
  criacaoState.compareDescription = '';
  criacaoState.compareTags = [];
  criacaoState.compareFirst10sHook = '';
  criacaoState.step = 5;
  _persistWizardState({ immediate: true });
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
  renderPostResult(fakeResult);
  toast('Texto do Compare aplicado no Post Final', 'good');
}

async function drawThumbWithLogo(forceCanvas) {
  const wrap = qs('thumbWrap');
  const img = qs('thumbImg');
  const canvas = qs('thumbCanvas');
  if (!img || !canvas) return;
  if (!img.complete || !img.naturalWidth) {
    img.onload = () => drawThumbWithLogo(forceCanvas);
    return;
  }

  const srcW = img.naturalWidth || 1280;
  const srcH = img.naturalHeight || 720;
  const outputScale = _clamp(parseInt(criacaoState.thumbOutputScale || 2, 10) || 2, 1, 3);
  const w = Math.max(320, Math.min(7680, Math.round(srcW * outputScale)));
  const h = Math.max(180, Math.min(4320, Math.round(srcH * outputScale)));
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';

  // Crop/zoom + ajustes de cor
  const zoom = _toNum(criacaoState.thumbZoom, 1, 1, 3);
  const cropW = srcW / zoom;
  const cropH = srcH / zoom;
  const maxCropX = Math.max(0, srcW - cropW);
  const maxCropY = Math.max(0, srcH - cropH);
  const cropX = maxCropX * (_toNum(criacaoState.thumbCropX, 50, 0, 100) / 100);
  const cropY = maxCropY * (_toNum(criacaoState.thumbCropY, 50, 0, 100) / 100);
  const bright = _toNum(criacaoState.thumbBrightness, 100, 40, 180);
  const contrast = _toNum(criacaoState.thumbContrast, 100, 40, 180);
  const sat = _toNum(criacaoState.thumbSaturation, 100, 0, 220);
  const hue = _toNum(criacaoState.thumbHue, 0, -180, 180);
  ctx.filter = `brightness(${bright}%) contrast(${contrast}%) saturate(${sat}%) hue-rotate(${hue}deg)`;
  ctx.drawImage(img, cropX, cropY, cropW, cropH, 0, 0, w, h);
  ctx.filter = 'none';

  const captionInput = qs('thumbSubtitleInput');
  const caption = (captionInput ? captionInput.value : criacaoState.thumbSubtitle || '').trim();
  criacaoState.thumbSubtitle = caption;

  // Legenda da thumb vira uma camada editável (sem queimá-la automaticamente fora do editor).
  if (caption) _thumbUpsertCaptionElement(caption, { persist: false });
  else _thumbDeleteCaptionElement({ persist: false });

  const selected = _thumbEnsureSelected();
  const selectedId = selected ? selected.id : null;
  const list = _thumbElements();
  _thumbRenderBoxes = [];

  for (const el of list) {
    if (!el || typeof el !== 'object') continue;
    const xPct = _toNum(el.x, 50, 0, 100);
    const yPct = _toNum(el.y, 50, 0, 100);
    const cx = w * (xPct / 100);
    const cy = h * (yPct / 100);
    const alpha = _toNum(el.opacity, 100, 0, 100) / 100;
    const rotationRad = _toNum(el.rotation, 0, -180, 180) * (Math.PI / 180);
    const isSelected = selectedId && el.id === selectedId;

    if (el.type === 'text') {
      const text = String(el.text || '').trim();
      if (!text) continue;
      const fontSize = Math.max(14, Math.round(h * (_toNum(el.scale, 6, 1, 30) / 100)));
      const fontWeight = String(el.fontWeight || '700');
      const fontFamily = String(el.fontFamily || 'Outfit, Arial, sans-serif');
      const strokeWidth = _toNum(el.strokeWidth, 3, 0, 12);

      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.translate(cx, cy);
      ctx.rotate(rotationRad);
      ctx.font = `${fontWeight} ${fontSize}px ${fontFamily}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      if (strokeWidth > 0) {
        ctx.lineWidth = strokeWidth;
        ctx.strokeStyle = String(el.strokeColor || '#000000');
        ctx.strokeText(text, 0, 0);
      }
      ctx.fillStyle = String(el.color || '#ffffff');
      ctx.fillText(text, 0, 0);

      const metrics = ctx.measureText(text);
      const tw = Math.max(1, metrics.width);
      const th = Math.max(1, fontSize * 1.2);

      if (isSelected) {
        ctx.save();
        ctx.strokeStyle = 'rgba(232,0,42,0.95)';
        ctx.lineWidth = Math.max(2, Math.round(w * 0.0025));
        ctx.setLineDash([8, 6]);
        ctx.strokeRect(-tw / 2 - 8, -th / 2 - 6, tw + 16, th + 12);
        ctx.restore();
      }
      ctx.restore();

      _thumbRenderBoxes.push({
        id: el.id,
        x: cx - (tw / 2) - 10,
        y: cy - (th / 2) - 8,
        w: tw + 20,
        h: th + 16,
        cx,
        cy,
      });
      continue;
    }

    const src = String(el.src || '');
    if (!src) continue;
    let pic = null;
    try {
      pic = await _thumbLoadImage(src);
    } catch (_) {
      continue;
    }
    if (!pic?.naturalWidth || !pic?.naturalHeight) continue;

    const ew = Math.max(8, Math.min(w * 1.5, w * (_toNum(el.scale, 20, 2, 120) / 100)));
    const eh = Math.max(8, ew * (pic.naturalHeight / pic.naturalWidth));

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.translate(cx, cy);
    ctx.rotate(rotationRad);
    ctx.drawImage(pic, -ew / 2, -eh / 2, ew, eh);
    if (isSelected) {
      ctx.save();
      ctx.strokeStyle = 'rgba(232,0,42,0.95)';
      ctx.lineWidth = Math.max(2, Math.round(w * 0.0025));
      ctx.setLineDash([8, 6]);
      ctx.strokeRect(-ew / 2, -eh / 2, ew, eh);
      ctx.restore();
    }
    ctx.restore();

    _thumbRenderBoxes.push({
      id: el.id,
      x: cx - (ew / 2),
      y: cy - (eh / 2),
      w: ew,
      h: eh,
      cx,
      cy,
    });
  }

  if (forceCanvas) {
    canvas.style.display = 'block';
    if (wrap) wrap.style.display = 'none';
  }
  canvas.style.display = 'block';
  if (wrap) wrap.style.display = 'none';
  _bindThumbCanvasInteractions();
  _updateThumbElementControlValues();
}

function downloadThumbnail() {
  const canvas = qs('thumbCanvas');
  const img = qs('thumbImg');
  if (canvas && canvas.style.display !== 'none') {
    const fmt = criacaoState.thumbExportFormat === 'jpg' ? 'jpg' : 'png';
    const q = _clamp((criacaoState.thumbJpegQuality || 98) / 100, 0.7, 1.0);
    const mime = fmt === 'png' ? 'image/png' : 'image/jpeg';
    canvas.toBlob((blob) => {
      if (!blob) return toast('Falha ao exportar thumbnail', 'bad');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `thumb_${criacaoState.runId?.slice(0, 8) || 'post'}_${canvas.width}x${canvas.height}.${fmt}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, mime, q);
    return;
  }
  if (img) {
    const a = document.createElement('a');
    a.href = img.src;
    a.download = `thumb_${criacaoState.runId?.slice(0, 8) || 'post'}.jpg`;
    a.click();
    return;
  }
  toast('Nenhuma thumbnail disponível', 'bad');
}

async function downloadOriginalVideo() {
  const objectKey = _normalizeObjectKeyish(_resolveOriginalVideoObjectKey());
  if (!objectKey) return toast('Chave do vídeo não encontrada', 'bad');
  toast('Gerando link de download…');
  const res = await apiFetch(`/api/video-download-url?object_key=${encodeURIComponent(objectKey)}&filename=video_original`);
  if (res?.error) return toast('Erro ao gerar link: ' + (res.detail || res.error), 'bad');
  window.open(res.url, '_blank');
}

async function deleteBurnedVideo() {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  if (!confirm('Deletar o vídeo queimado do servidor? Esta ação não pode ser desfeita.')) return;
  const headers = { 'Content-Type': 'application/json' };
  if (state.apiKey) headers['X-API-Key'] = state.apiKey;
  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(criacaoState.runId)}/burned-video`, { method: 'DELETE', headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);
    criacaoState.burnedObjectKey = null;
    criacaoState.burnedVideoUrl = null;
    criacaoState.burnedFilename = null;
    _persistWizardState({ immediate: true });
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    toast('Vídeo queimado deletado.', 'good');
  } catch (e) {
    toast('Erro ao deletar: ' + e.message, 'bad');
  }
}

async function deleteTeaserVideo() {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  if (!confirm('Deletar o teaser do servidor? Esta ação não pode ser desfeita.')) return;
  const headers = { 'Content-Type': 'application/json' };
  if (state.apiKey) headers['X-API-Key'] = state.apiKey;
  try {
    const payload = {
      object_key: _normalizeObjectKeyish(criacaoState.teaserObjectKey) || null,
      teaser_object_key: _normalizeObjectKeyish(criacaoState.teaserObjectKey) || null,
    };
    const res = await fetch(`/api/runs/${encodeURIComponent(criacaoState.runId)}/teaser-video`, {
      method: 'DELETE',
      headers,
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);
    criacaoState.teaserObjectKey = null;
    criacaoState.teaserUrl = null;
    _persistWizardState({ immediate: true });
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    toast('Teaser deletado.', 'good');
  } catch (e) {
    toast('Erro ao deletar teaser: ' + e.message, 'bad');
  }
}

async function burnLogoOnTeaser() {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  if (!criacaoState.teaserObjectKey) return toast('Gere o teaser antes de queimar a logo', 'bad');
  _syncCriacaoDraftsFromDom();
  const linkChanged = _syncLogoLayoutLinkBeforeRender();
  if (linkChanged) _persistWizardState({ immediate: true });

  const area = qs('teaserLogoBurnArea');
  if (area) {
    area.innerHTML = _teaserLogoBurnProgressHtml();
    _setTeaserLogoBurnProgress(2, 'Preparando queima da logo no teaser…');
  }

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const body = {
      run_id: criacaoState.runId,
      teaser_object_key: _normalizeObjectKeyish(criacaoState.teaserObjectKey),
      logo_profile_id: criacaoState.logoProfileId || null,
      logo_profile_name: criacaoState.logoProfileName || null,
      logo_profile_layout_linked: criacaoState.logoProfileLayoutLinked !== false,
      logo_x: criacaoState.logoX,
      logo_y: criacaoState.logoY,
      logo_scale_pct: criacaoState.logoScalePct,
      logo_opacity: criacaoState.logoOpacity,
      output_crf: parseInt(criacaoState.teaserQuality || '26', 10),
      max_height: 0,
      x264_preset: criacaoState.burnedPreset || 'veryfast',
    };
    const teaserLogoPayload = _teaserLogoPayloadList();
    if (teaserLogoPayload.length) {
      body.logos = teaserLogoPayload;
      const firstLogo = teaserLogoPayload[0];
      body.logo_b64 = firstLogo.b64;
      body.logo_x = firstLogo.x;
      body.logo_y = firstLogo.y;
      body.logo_scale_pct = firstLogo.scale_pct;
      body.logo_opacity = firstLogo.opacity;
    } else if (criacaoState.logoB64) {
      body.logo_b64 = criacaoState.logoB64;
    }

    const res = await fetch('/api/teaser/burn-logo', { method: 'POST', headers, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);
    const jobId = data.job_id;
    if (!jobId) throw new Error('Servidor não retornou job_id');
    await _pollTeaserLogoBurnJob(jobId, area);
  } catch (e) {
    if (area) area.innerHTML = `<span class="hint" style="color:var(--bad);">Erro: ${e.message}</span>`;
    toast('Erro: ' + e.message, 'bad');
  }
}

function _teaserLogoBurnProgressHtml() {
  return `
    <div id="teaserLogoBurnProgressWrap" class="upload-progress-card op-progress-card" style="display:grid;margin-top:10px;">
      <div class="upload-progress-ring" id="teaserLogoBurnProgressRing" style="--upload-pct:0;">
        <div class="upload-progress-inner">
          <div class="upload-progress-percent" id="teaserLogoBurnProgressPct">0%</div>
          <div class="upload-progress-state" id="teaserLogoBurnProgressState">aguarde</div>
        </div>
      </div>
      <div class="upload-progress-copy">
        <div class="upload-progress-title" id="teaserLogoBurnProgressTitle">Queimando logo no teaser</div>
        <div class="upload-progress-detail" id="teaserLogoBurnProgressLabel">Preparando…</div>
        <div class="upload-progress-track"><div class="upload-progress-fill" id="teaserLogoBurnProgressFill" style="width:0%"></div></div>
        <div class="op-progress-history" id="teaserLogoBurnProgressHistory"></div>
      </div>
    </div>`;
}

let _teaserLogoBurnProgressLast = '';

function _setTeaserLogoBurnProgress(pct, detail, kind = 'active') {
  const wrap = qs('teaserLogoBurnProgressWrap');
  if (!wrap) return;
  const safePct = Math.max(0, Math.min(100, Number.isFinite(Number(pct)) ? Number(pct) : 0));
  wrap.classList.toggle('is-good', kind === 'good');
  wrap.classList.toggle('is-bad', kind === 'bad');
  wrap.style.setProperty('--upload-pct', safePct.toFixed(1));
  qs('teaserLogoBurnProgressRing')?.style.setProperty('--upload-pct', safePct.toFixed(1));
  if (qs('teaserLogoBurnProgressPct')) qs('teaserLogoBurnProgressPct').textContent = `${Math.round(safePct)}%`;
  if (qs('teaserLogoBurnProgressState')) {
    qs('teaserLogoBurnProgressState').textContent = kind === 'good' ? 'ok' : kind === 'bad' ? 'erro' : (safePct > 8 ? 'rodando' : 'aguarde');
  }
  if (qs('teaserLogoBurnProgressLabel')) qs('teaserLogoBurnProgressLabel').textContent = detail || 'Processando…';
  if (qs('teaserLogoBurnProgressFill')) qs('teaserLogoBurnProgressFill').style.width = `${safePct.toFixed(1)}%`;
  const hist = qs('teaserLogoBurnProgressHistory');
  const clean = String(detail || '').replace(/^[✓✗!•⏳]+\s*/u, '').trim();
  if (hist && clean && clean !== _teaserLogoBurnProgressLast) {
    _teaserLogoBurnProgressLast = clean;
    const item = document.createElement('div');
    item.className = `op-progress-history-item ${kind}`;
    item.textContent = `${kind === 'good' ? '✓' : kind === 'bad' ? '!' : '•'} ${clean}`;
    hist.prepend(item);
    while (hist.children.length > 6) hist.lastElementChild?.remove();
  }
}

async function _pollTeaserLogoBurnJob(jobId, area) {
  const headers = state.apiKey ? { 'X-API-Key': state.apiKey } : {};
  const startedAt = Date.now();
  let lastPct = 2;
  while (true) {
    const res = await fetch(`/api/burn-subtitles/status/${jobId}`, { headers });
    const job = await res.json().catch(() => ({}));
    if (!res.ok || job.error === 'job_not_found') {
      _setTeaserLogoBurnProgress(100, 'Job não encontrado.', 'bad');
      return;
    }
    const status = job.status;
    if (status === 'done') {
      const objectKey = _normalizeObjectKeyish(job.object_key);
      const filename = job.filename || null;
      criacaoState.teaserLogoObjectKey = objectKey || null;
      criacaoState.teaserLogoFilename = filename;
      if (objectKey) {
        try {
          criacaoState.teaserLogoUrl = await _getVideoStreamUrl(objectKey);
        } catch (_) {
          criacaoState.teaserLogoUrl = job.video_url || null;
        }
      } else {
        criacaoState.teaserLogoUrl = job.video_url || null;
      }
      _persistWizardState({ immediate: true });
      if (area) {
        area.innerHTML = _teaserLogoBurnProgressHtml();
        _setTeaserLogoBurnProgress(100, '✓ Teaser com logo pronto.', 'good');
      }
      renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
      toast('Teaser com logo pronto!', 'good');
      return;
    }
    if (status === 'error' || status === 'cancelled') {
      _setTeaserLogoBurnProgress(100, `Erro: ${job.detail || job.error || 'falha no processamento'}`, 'bad');
      toast('Erro no burn do teaser: ' + (job.detail || job.error || 'falha'), 'bad');
      return;
    }
    const detail = job.detail || 'Processando…';
    const realPct = Number(job.pct ?? job.progress_pct);
    if (Number.isFinite(realPct)) lastPct = Math.max(lastPct, Math.min(99, realPct));
    else if (/ffmpeg/i.test(detail)) lastPct = Math.max(lastPct, 12);
    else if (/salvando/i.test(detail)) lastPct = Math.max(lastPct, 96);
    _setTeaserLogoBurnProgress(lastPct, detail);
    if (Date.now() - startedAt > 1000 * 60 * 180) {
      _setTeaserLogoBurnProgress(100, 'Tempo excedido no burn do teaser.', 'bad');
      return;
    }
    await new Promise(r => setTimeout(r, 3000));
  }
}

async function downloadTeaserLogoVideo() {
  const objectKey = _normalizeObjectKeyish(criacaoState.teaserLogoObjectKey);
  if (objectKey) {
    toast('Gerando link de download…');
    const res = await apiFetch(`/api/video-download-url?object_key=${encodeURIComponent(objectKey)}&filename=teaser_logo`);
    if (res?.error) return toast('Erro ao gerar link: ' + (res.detail || res.error), 'bad');
    window.open(res.url, '_blank');
    return;
  }
  const url = criacaoState.teaserLogoUrl;
  if (!url) return toast('Nenhum teaser com logo disponível', 'bad');
  window.open(url, '_blank');
}

async function deleteTeaserLogoVideo() {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  if (!criacaoState.teaserLogoObjectKey) return toast('Nenhum teaser com logo disponível', 'bad');
  if (!confirm('Deletar o teaser com logo do servidor? Esta ação não pode ser desfeita.')) return;
  const headers = { 'Content-Type': 'application/json' };
  if (state.apiKey) headers['X-API-Key'] = state.apiKey;
  try {
    const payload = {
      object_key: _normalizeObjectKeyish(criacaoState.teaserLogoObjectKey) || null,
      teaser_logo_object_key: _normalizeObjectKeyish(criacaoState.teaserLogoObjectKey) || null,
    };
    const res = await fetch(`/api/runs/${encodeURIComponent(criacaoState.runId)}/teaser-video`, {
      method: 'DELETE',
      headers,
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);
    criacaoState.teaserLogoObjectKey = null;
    criacaoState.teaserLogoUrl = null;
    criacaoState.teaserLogoFilename = null;
    _persistWizardState({ immediate: true });
    renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    toast('Teaser com logo deletado.', 'good');
  } catch (e) {
    toast('Erro ao deletar teaser com logo: ' + e.message, 'bad');
  }
}

function useTeaserLogoAsMain() {
  if (!criacaoState.teaserLogoObjectKey && !criacaoState.teaserLogoUrl) {
    return toast('Nenhum teaser com logo disponível', 'bad');
  }
  criacaoState.teaserObjectKey = _normalizeObjectKeyish(criacaoState.teaserLogoObjectKey) || criacaoState.teaserObjectKey;
  criacaoState.teaserUrl = criacaoState.teaserLogoUrl || criacaoState.teaserUrl;
  _persistWizardState({ immediate: true });
  renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
  toast('Teaser atualizado para a versão com logo', 'good');
}

async function downloadBurnedVideo() {
  const objectKey = _normalizeObjectKeyish(criacaoState.burnedObjectKey);
  if (objectKey) {
    toast('Gerando link de download…');
    const res = await apiFetch(`/api/video-download-url?object_key=${encodeURIComponent(objectKey)}&filename=video_legendado`);
    if (res?.error) return toast('Erro ao gerar link: ' + (res.detail || res.error), 'bad');
    window.open(res.url, '_blank');
    return;
  }
  const url = criacaoState.burnedVideoUrl;
  if (!url) return toast('Nenhum vídeo processado ainda', 'bad');
  window.open(url, '_blank');
}

async function downloadTeaserVideo() {
  const objectKey = _normalizeObjectKeyish(criacaoState.teaserObjectKey);
  if (objectKey) {
    toast('Gerando link de download…');
    const res = await apiFetch(`/api/video-download-url?object_key=${encodeURIComponent(objectKey)}&filename=teaser`);
    if (res?.error) return toast('Erro ao gerar link: ' + (res.detail || res.error), 'bad');
    window.open(res.url, '_blank');
    return;
  }
  const url = criacaoState.teaserUrl;
  if (!url) return toast('Nenhum teaser disponível', 'bad');
  window.open(url, '_blank');
}

async function downloadCombinedVideo() {
  const objectKey = _normalizeObjectKeyish(criacaoState.teaserCombinedObjectKey);
  if (objectKey) {
    toast('Gerando link de download…');
    const res = await apiFetch(`/api/video-download-url?object_key=${encodeURIComponent(objectKey)}&filename=video_completo`);
    if (res?.error) return toast('Erro ao gerar link: ' + (res.detail || res.error), 'bad');
    window.open(res.url, '_blank');
    return;
  }
  const url = criacaoState.teaserCombinedUrl;
  if (!url) return toast('Nenhum vídeo combinado disponível', 'bad');
  window.open(url, '_blank');
}

function triggerBurnSubs() {
  burnSubtitles();
}

function _burnFileNameFromKey(objectKey = '') {
  const base = String(objectKey || '').split('/').pop() || '';
  return _cleanFilename(base) || base;
}

function _burnPickerAreaId(target = 'burn') {
  if (target === 'teaser') return 'teaserSelectArea';
  if (target === 'thumb') return 'thumbVideoSelectArea';
  return 'burnSelectArea';
}

function _burnPickerUseFn(target = 'burn') {
  if (target === 'teaser') return 'useTeaserSourceByIndex';
  if (target === 'thumb') return 'useThumbSourceByIndex';
  return 'useExistingBurnedVideoByIndex';
}

function _burnPickerDoneText(target = 'burn') {
  if (target === 'teaser') return '✓ Fonte do teaser definida.';
  if (target === 'thumb') return '✓ Fonte do thumbnail definida.';
  return '✓ Vídeo legendado selecionado com sucesso.';
}

async function loadExistingBurnedVideosFor(target = 'burn', scope = 'run') {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  const area = qs(_burnPickerAreaId(target));
  if (!area) return;
  area.innerHTML = '<span class="hint">⏳ Carregando vídeos legendados…</span>';

  try {
    const runPrefix = `burns/${String(criacaoState.runId || '').slice(0, 8)}`;
    const prefix = scope === 'all' ? 'burns' : runPrefix;
    const maxKeys = scope === 'all' ? 120 : 60;
    const res = await apiFetch(`/uploads/list?prefix=${encodeURIComponent(prefix)}&max_keys=${maxKeys}`);
    const all = Array.isArray(res?.items) ? res.items : [];
    const items = all
      .filter(it => String(it?.object_key || '').toLowerCase().endsWith('.mp4'))
      .slice(0, 30);

    _burnCandidatesCache[target] = items;

    if (!items.length) {
      if (scope === 'run') {
        area.innerHTML = `
          <div class="hint">Nenhum vídeo legendado encontrado para este run (${esc(runPrefix)}).</div>
          <button class="btn" style="margin-top:6px;" onclick="loadExistingBurnedVideosFor('${target}','all')">Buscar em todos os legendados</button>
        `;
      } else {
        area.innerHTML = '<div class="hint">Nenhum vídeo legendado encontrado no servidor.</div>';
      }
      return;
    }

    area.innerHTML = `
      <div class="hint" style="margin-bottom:6px;">${items.length} vídeo(s) encontrado(s)</div>
      <div style="display:grid;gap:6px;">
        ${items.map((it, idx) => {
          const key = String(it.object_key || '');
          const fname = _burnFileNameFromKey(key);
          const date = it.last_modified ? fmtDate(it.last_modified) : '';
          const size = it.size_mb != null ? `${it.size_mb} MB` : '';
          return `
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px;border:1px solid var(--line);border-radius:8px;background:var(--bg2);">
              <div style="flex:1;min-width:220px;">
                <div style="font-size:12px;font-weight:600;">${esc(fname)}</div>
                <div class="hint" style="font-size:11px;">${esc(size)} ${size && date ? '·' : ''} ${esc(date)}</div>
                <div class="hint" style="font-size:10px;opacity:.8;word-break:break-all;">${esc(key)}</div>
              </div>
              <button class="btn primary" onclick="${_burnPickerUseFn(target)}(${idx})">Usar este</button>
            </div>
          `;
        }).join('')}
      </div>
    `;
  } catch (e) {
    area.innerHTML = `<span class="hint" style="color:var(--bad);">Erro ao listar legendados: ${esc(e.message)}</span>`;
  }
}

async function loadExistingBurnedVideos(scope = 'run') {
  return loadExistingBurnedVideosFor('burn', scope);
}

async function _useBurnedCandidate(target = 'burn', idx = 0) {
  const list = _burnCandidatesCache[target] || [];
  const item = list[Number(idx)];
  if (!item) return toast('Vídeo selecionado inválido', 'bad');
  const objectKey = String(item.object_key || '');
  if (!objectKey) return toast('Object key inválida', 'bad');

  const area = target === 'burn' ? qs('burnSubsArea') : null;
  if (area) area.innerHTML = '<span class="hint">⏳ Carregando vídeo selecionado…</span>';

  try {
    let streamUrl = await _getVideoStreamUrl(objectKey);
    if (!streamUrl) streamUrl = item.public_url || null;
    if (!streamUrl) throw new Error('Não foi possível gerar URL de stream');

    if (target === 'burn') {
      _syncCriacaoDraftsFromDom();
      _burnApplyResult(streamUrl, _burnFileNameFromKey(objectKey), area, objectKey);
    } else if (target === 'teaser') {
      _setTeaserSource('burned', objectKey, { persist: false, render: false });
      if (!criacaoState.burnedObjectKey) {
        criacaoState.burnedObjectKey = objectKey;
        criacaoState.burnedVideoUrl = streamUrl;
        criacaoState.burnedFilename = _burnFileNameFromKey(objectKey);
      }
      _persistWizardState({ immediate: true });
      renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
    } else if (target === 'thumb') {
      criacaoState.thumbVideoObjectKey = objectKey;
      criacaoState.thumbSourceB64 = null;
      criacaoState.thumbSourceFrameIdx = null;
      criacaoState.thumbSourceInfo = 'Fonte de vídeo definida. Clique em "Carregar frame HQ".';
      criacaoState.thumbAutoHqTried = false;
      _persistWizardState({ immediate: true });
      renderCriacaoDetail(criacaoState.runId, criacaoState.frames);
      if (criacaoState.step === 4) {
        setTimeout(() => { loadHighResThumbnailFrame(); }, 30);
      }
    }

    const listArea = qs(_burnPickerAreaId(target));
    if (listArea) listArea.innerHTML = `<span class="hint" style="color:var(--good);">${_burnPickerDoneText(target)}</span>`;
  } catch (e) {
    if (area) area.innerHTML = `<span class="hint" style="color:var(--bad);">Erro: ${esc(e.message)}</span>`;
    toast('Erro ao usar vídeo legendado: ' + e.message, 'bad');
  }
}

async function useExistingBurnedVideoByIndex(idx) {
  return _useBurnedCandidate('burn', idx);
}

async function useTeaserSourceByIndex(idx) {
  return _useBurnedCandidate('teaser', idx);
}

async function useThumbSourceByIndex(idx) {
  return _useBurnedCandidate('thumb', idx);
}

const _operationProgressState = {};

function _operationProgressReset(id) {
  delete _operationProgressState[id];
}

function _operationProgressKindLabel(kind, pct) {
  if (kind === 'good') return 'ok';
  if (kind === 'bad') return 'erro';
  if (kind === 'waiting') return 'fila';
  return pct > 2 ? 'rodando' : 'aguarde';
}

function _operationProgressPush(id, detail, kind = 'active') {
  const st = _operationProgressState[id] ||= { pct: 0, history: [], last: '' };
  const clean = String(detail || '')
    .replace(/[.]{2,}$/g, '')
    .replace(/^[✓✗!⏳📤🎬🔍🤖✂️🔊🎞️]+\s*/u, '')
    .trim();
  if (!clean || clean === st.last) return st;
  st.last = clean;
  st.history.unshift({ text: clean, kind });
  st.history = st.history.slice(0, 6);
  return st;
}

function _renderOperationProgressHtml(id, title, detail, opts = {}) {
  const st = _operationProgressState[id] ||= { pct: 0, history: [], last: '' };
  const kind = opts.kind || 'active';
  if (Number.isFinite(opts.pct)) {
    st.pct = Math.max(0, Math.min(100, opts.pct));
  } else if (kind === 'good' || kind === 'bad') {
    st.pct = 100;
  } else {
    const pctFromDetail = detail ? parseInt(detail.match(/(\d+)%/)?.[1], 10) : null;
    if (Number.isFinite(pctFromDetail)) {
      st.pct = Math.max(0, Math.min(99, pctFromDetail));
    } else {
      st.pct = Math.max(0, Math.min(96, (st.pct || 0) + 4));
    }
  }
  _operationProgressPush(id, detail, kind);

  const dots = Number.isFinite(opts.dots) ? '.'.repeat(Math.max(0, opts.dots || 0)) : '';
  const pct = Math.max(0, Math.min(100, st.pct || 0));
  const cardClass = kind === 'good' ? 'is-good' : kind === 'bad' ? 'is-bad' : '';
  const history = (st.history || []).map(item => (
    `<div class="op-progress-history-item ${esc(item.kind || '')}">${item.kind === 'good' ? '✓' : item.kind === 'bad' ? '!' : '•'} ${esc(item.text)}</div>`
  )).join('');

  return `
    <div class="upload-progress-card op-progress-card ${cardClass}" id="${escAttr(id)}ProgressCard" style="--upload-pct:${pct.toFixed(1)};">
      <div class="upload-progress-ring" style="--upload-pct:${pct.toFixed(1)};">
        <div class="upload-progress-inner">
          <div class="upload-progress-percent">${Math.round(pct)}%</div>
          <div class="upload-progress-state">${esc(_operationProgressKindLabel(kind, pct))}</div>
        </div>
      </div>
      <div class="upload-progress-copy">
        <div class="upload-progress-title">${esc(title || 'Processando')}</div>
        <div class="upload-progress-detail">${esc(detail || 'Processando…')}${dots}</div>
        <div class="upload-progress-track">
          <div class="op-progress-fill" style="width:${pct.toFixed(1)}%;"></div>
        </div>
        <div class="op-progress-history">${history}</div>
        ${opts.extra || ''}
      </div>
    </div>
  `;
}

function _renderBurnProgressHtml(detail, dots = 0, queueLabel = '', pct) {
  const suffix = '.'.repeat(Math.max(0, dots || 0));
  const showQueue = !!criacaoState.showBurnQueue;
  const extra = `
    <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap;">
      <button class="btn" onclick="cancelBurnJob()" ${criacaoState.activeBurnJobId ? '' : 'disabled'}>Cancelar</button>
      <button id="btnToggleBurnQueue" class="btn" onclick="_toggleBurnQueueView()">${showQueue ? 'Ocultar fila' : 'Ver fila'}</button>
    </div>
    <div id="burnQueueView" class="hint" style="margin-top:6px;display:${showQueue ? 'block' : 'none'};"></div>
  `;
  return _renderOperationProgressHtml(
    'burn',
    criacaoState.burnSkipSubtitles ? 'Queimar logo' : 'Queimar logo e legenda',
    `${detail || 'Processando…'}${queueLabel}${suffix}`,
    { pct, extra }
  );
}

function _toggleBurnQueueView(forceOpen = null) {
  criacaoState.showBurnQueue = forceOpen == null ? !criacaoState.showBurnQueue : !!forceOpen;
  const box = qs('burnQueueView');
  if (box) {
    box.style.display = criacaoState.showBurnQueue ? 'block' : 'none';
    if (!criacaoState.showBurnQueue) box.textContent = '';
  }
  const btn = qs('btnToggleBurnQueue');
  if (btn) btn.textContent = criacaoState.showBurnQueue ? 'Ocultar fila' : 'Ver fila';
  if (criacaoState.showBurnQueue) void _refreshBurnQueueView({ force: true });
}

async function _refreshBurnQueueView(opts = {}) {
  const force = !!opts.force;
  const quiet = !!opts.quiet;
  if (!criacaoState.showBurnQueue && !force) return;
  const box = qs('burnQueueView');
  if (!box) return;
  const now = Date.now();
  if (!force && _burnQueueRefreshInFlight) return _burnQueueRefreshInFlight;
  if (!force && (now - _burnQueueLastRefreshAt) < 12000) return;

  const task = (async () => {
    let timer = null;
    try {
      const headers = {};
      if (state.apiKey) headers['X-API-Key'] = state.apiKey;
      const controller = new AbortController();
      timer = setTimeout(() => controller.abort(), 4000);
      const res = await fetch('/api/burn-subtitles/queue', {
        headers,
        cache: 'no-store',
        signal: controller.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);

      const pending = data.pending || [];
      const running = data.running || [];
      if (!pending.length && !running.length) {
        box.textContent = 'Fila vazia.';
        _burnQueueLastRefreshAt = Date.now();
        return;
      }

      const lines = [];
      const fmtBurnQueueItem = (x, fallback) => {
        const detail = String(x.detail || fallback || 'processando');
        const pctNum = Number(x.progress_pct);
        const pct = Number.isFinite(pctNum) ? `${Math.max(0, Math.min(100, Math.round(pctNum)))}%` : '';
        const detailWithPct = pct && !/%/.test(detail) ? `${pct} · ${detail}` : detail;
        const run = x.run_id ? ` · run ${(x.run_id || '').slice(0, 8)}` : '';
        return `${(x.job_id || '').slice(0, 8)} (${detailWithPct}${run})`;
      };
      if (running.length) {
        lines.push(`Rodando: ${running.map(x => fmtBurnQueueItem(x, 'processando')).join(' · ')}`);
      }
      if (pending.length) {
        const top = pending.slice(0, 5).map(x => `#${x.position} ${fmtBurnQueueItem(x, 'aguardando')}`).join(' · ');
        lines.push(`Fila: ${top}${pending.length > 5 ? ` · +${pending.length - 5}` : ''}`);
      }
      box.textContent = lines.join(' | ');
      _burnQueueLastRefreshAt = Date.now();
    } catch (e) {
      if (quiet) return;
      const msg = e?.name === 'AbortError' ? 'tempo esgotado' : (e?.message || 'erro desconhecido');
      box.textContent = `Não foi possível carregar fila: ${msg}`;
    } finally {
      if (timer) clearTimeout(timer);
    }
  })();

  _burnQueueRefreshInFlight = task;
  try {
    return await task;
  } finally {
    if (_burnQueueRefreshInFlight === task) _burnQueueRefreshInFlight = null;
  }
}

function _burnApplyResult(videoUrl, filename, area, objectKey, warning = '') {
  const normalizedObjectKey = _normalizeObjectKeyish(objectKey);
  const originalSourceKey = _normalizeObjectKeyish(_resolveOriginalVideoObjectKey()) || null;
  criacaoState.burnedFilename = filename;
  criacaoState.activeBurnJobId = null;
  criacaoState.burnStartInFlight = false;
  criacaoState.burnedWarning = warning || null;
  criacaoState.showBurnQueue = false;
  if (normalizedObjectKey) criacaoState.burnedObjectKey = normalizedObjectKey;
  if (
    normalizedObjectKey &&
    (
      !criacaoState.teaserSourceObjectKey
      || (criacaoState.teaserSourceType === 'original' && originalSourceKey && _normalizeObjectKeyish(criacaoState.teaserSourceObjectKey) === originalSourceKey)
    )
  ) {
    _setTeaserSource('burned', normalizedObjectKey, { persist: false, render: false });
  }
  if (!criacaoState.thumbVideoObjectKey && normalizedObjectKey) criacaoState.thumbVideoObjectKey = normalizedObjectKey;

  const goTeaserBtn = qs('btnGoTeaser');
  if (goTeaserBtn) goTeaserBtn.disabled = false;

  const applyResult = (resolvedUrl) => {
    criacaoState.burnedVideoUrl = resolvedUrl || videoUrl || null;

    const playerWrap = document.querySelector('.xv-player-wrap');
    if (playerWrap) {
      const size = _currentPreviewVideoSize();
      if (size?.width > 0 && size?.height > 0) {
        playerWrap.style.aspectRatio = `${size.width} / ${size.height}`;
      }
      const oldMedia = playerWrap.querySelector('video, img:not(.xv-logo-overlay)');
      if (oldMedia) {
        const vid = document.createElement('video');
        vid.controls = true;
        vid.preload = 'metadata';
        vid.playsInline = true;
        vid.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block;background:#000;';
        if (criacaoState.burnedVideoUrl) vid.src = criacaoState.burnedVideoUrl;
        oldMedia.replaceWith(vid);
      }
    }

    if (area) area.innerHTML = _renderBurnResultHtml();
    _persistWizardState({ immediate: true });
    if (criacaoState.postResult) renderPostResult(criacaoState.postResult);
    toast(warning ? 'Vídeo legendado pronto em modo recuperação.' : 'Vídeo legendado pronto!', 'good');
  };

  if (normalizedObjectKey) {
    _getVideoStreamUrl(normalizedObjectKey)
      .then((u) => applyResult(u || videoUrl))
      .catch(() => applyResult(videoUrl));
    return;
  }
  applyResult(videoUrl);
}

function _collectBurnRequestBody(videoObjectKey) {
  _syncCriacaoDraftsFromDom();
  const linkChanged = _syncLogoLayoutLinkBeforeRender();
  if (linkChanged) _persistWizardState({ immediate: true });

  const burnQuality = qs('burnQuality')?.value || criacaoState.burnedQuality || '26';
  const burnResolution = qs('burnResolution')?.value || criacaoState.burnedResolution || '1080';
  const burnPreset = qs('burnPreset')?.value || criacaoState.burnedPreset || 'ultrafast';
  criacaoState.burnedQuality = burnQuality;
  criacaoState.burnedResolution = burnResolution;
  criacaoState.burnedPreset = burnPreset;
  _persistWizardState();

  const bodyObj = {
    run_id: criacaoState.runId,
    font_size: parseInt(qs('burnFontSize')?.value || String(criacaoState.burnFontSize || 22), 10),
    font_color: qs('burnFontColor')?.value || criacaoState.burnFontColor || 'white',
    sub_delay_secs: parseFloat(qs('burnSubDelay')?.value || String(criacaoState.burnSubDelay || 0)),
    output_crf: parseInt(burnQuality, 10),
    max_height: parseInt(burnResolution, 10),
    x264_preset: burnPreset,
    logo_profile_id: criacaoState.logoProfileId || null,
    logo_profile_name: criacaoState.logoProfileName || null,
    logo_profile_layout_linked: criacaoState.logoProfileLayoutLinked !== false,
    logo_x: criacaoState.logoX,
    logo_y: criacaoState.logoY,
    logo_scale_pct: criacaoState.logoScalePct,
    logo_opacity: criacaoState.logoOpacity,
  };

  const burnLogoPayload = _burnLogoPayloadList();
  if (burnLogoPayload.length) {
    bodyObj.logos = burnLogoPayload;
    const firstLogo = burnLogoPayload[0];
    bodyObj.logo_b64 = firstLogo.b64;
    bodyObj.logo_x = firstLogo.x;
    bodyObj.logo_y = firstLogo.y;
    bodyObj.logo_scale_pct = firstLogo.scale_pct;
    bodyObj.logo_opacity = firstLogo.opacity;
  }

  const logoList = _burnLogoList();
  if (logoList.length) {
    bodyObj.logo_position_overrides = logoList.slice(0, parseInt(criacaoState.burnLogoTargetCount || 1, 10) || 1).map(l => ({
      x: _toNum(l.x, criacaoState.logoX, 0, 100),
      y: _toNum(l.y, criacaoState.logoY, 0, 100),
      scale_pct: _toNum(l.scale_pct, criacaoState.logoScalePct, 5, 100),
      opacity: _toNum(l.opacity, criacaoState.logoOpacity, 5, 100),
    }));
  }

  const normalizedVideoObjectKey = _normalizeObjectKeyish(videoObjectKey);
  if (normalizedVideoObjectKey) bodyObj.video_object_key = normalizedVideoObjectKey;
  if (!bodyObj.logo_b64 && criacaoState.logoB64) bodyObj.logo_b64 = criacaoState.logoB64;
  if (criacaoState.burnSkipSubtitles) bodyObj.skip_subtitles = true;

  const srtFromEditor = (qs('transcriptSrtEdit')?.value || criacaoState.transcriptDraft || '').trim();
  if (srtFromEditor) bodyObj.srt_content = srtFromEditor;
  return bodyObj;
}

function _burnClock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function _renderBurnDiagnostics(data) {
  const coverage = data?.coverage || {};
  const timing = data?.timing || {};
  const warnings = data?.warnings || [];
  const gaps = coverage.large_gaps || [];
  const warningHtml = warnings.length
    ? warnings.map(w => `<div style="color:#ffcc66;margin-top:4px;">⚠ ${esc(w)}</div>`).join('')
    : '<div style="color:var(--ok);margin-top:4px;">✓ Nenhum buraco gigante detectado no SRT.</div>';
  const gapHtml = gaps.length
    ? gaps.slice(0, 8).map(g => `<div style="display:flex;gap:8px;justify-content:space-between;border-top:1px solid rgba(255,255,255,.06);padding:5px 0;font-size:12px;">
        <span>${_burnClock(g.start)} → ${_burnClock(g.end)}</span>
        <strong>${_burnClock(g.duration)}</strong>
      </div>`).join('')
    : '<div class="hint" style="margin-top:6px;">Sem gaps acima de 2 minutos.</div>';
  return `<div style="padding:12px;border:1px solid rgba(32,213,255,.25);border-radius:12px;background:rgba(5,8,14,.62);">
    <div style="font-weight:800;margin-bottom:6px;">Diagnóstico da legenda</div>
    <div class="hint">Cues: ${coverage.segments_count || 0} · Última legenda: ${_burnClock(coverage.last_end_seconds)} · Duração do vídeo: ${_burnClock(coverage.media_duration_seconds)}</div>
    <div class="hint">Tempo coberto por texto: ${_burnClock(coverage.active_subtitle_seconds)} · Maior buraco: ${_burnClock(coverage.longest_gap_seconds)}</div>
    ${warningHtml}
    ${timing?.likely_synthetic_chunk_timing ? '<div style="color:#ffcc66;margin-top:4px;">⚠ Timing sintético detectado; o backend tenta redistribuir antes da queima.</div>' : ''}
    <div style="margin-top:10px;">${gapHtml}</div>
  </div>`;
}

async function burnDiagnoseSubtitles() {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  const area = qs('burnPreviewArea');
  if (area) area.innerHTML = '<div class="hint">Analisando SRT e duração do vídeo…</div>';
  try {
    const data = await apiFetch('/api/burn-subtitles/diagnose', {
      method: 'POST',
      body: JSON.stringify(_collectBurnRequestBody()),
    });
    if (area) area.innerHTML = _renderBurnDiagnostics(data);
    if ((data.warnings || []).length) toast('Diagnóstico encontrou buracos na legenda', 'bad');
    else toast('Diagnóstico concluído', 'good');
  } catch (e) {
    if (area) area.innerHTML = `<div style="color:var(--bad);padding:10px;border:1px solid rgba(255,80,80,.35);border-radius:10px;">${esc(e.message)}</div>`;
    toast(e.message, 'bad');
  }
}

async function burnQuickPreview() {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  const area = qs('burnPreviewArea');
  const minute = Math.max(0, parseFloat(qs('burnPreviewMinute')?.value || '0') || 0);
  const bodyObj = _collectBurnRequestBody();
  bodyObj.timestamp = minute * 60;
  bodyObj.duration_seconds = 60;
  if (area) area.innerHTML = `<div class="hint">Gerando prévia de 60s a partir de ${_burnClock(bodyObj.timestamp)}…</div>`;
  try {
    const data = await apiFetch('/api/burn-subtitles/preview', {
      method: 'POST',
      body: JSON.stringify(bodyObj),
    });
    const diagnostics = data.diagnostics?.coverage ? _renderBurnDiagnostics({ coverage: data.diagnostics.coverage, timing: data.diagnostics.before || {}, warnings: [] }) : '';
    if (area) {
      area.innerHTML = `<div style="padding:12px;border:1px solid rgba(32,213,255,.25);border-radius:12px;background:rgba(5,8,14,.62);">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:8px;">
          <strong>Prévia rápida: ${_burnClock(data.start_seconds)} → ${_burnClock((data.start_seconds || 0) + (data.duration_seconds || 0))}</strong>
          <button class="btn" onclick="window.open('${escAttr(data.video_url || '')}','_blank')">Abrir</button>
        </div>
        <video src="${escAttr(data.video_url || '')}" controls playsinline preload="metadata" style="width:100%;max-height:360px;background:#000;border-radius:10px;"></video>
      </div>
      <div style="margin-top:8px;">${diagnostics}</div>`;
    }
    toast('Prévia rápida pronta', 'good');
  } catch (e) {
    if (area) area.innerHTML = `<div style="color:var(--bad);padding:10px;border:1px solid rgba(255,80,80,.35);border-radius:10px;">${esc(e.message)}</div>`;
    toast(e.message, 'bad');
  }
}

async function burnSubtitles(videoObjectKey) {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  if (criacaoState.burnStartInFlight || criacaoState.activeBurnJobId) {
    return toast('Já existe uma queima em andamento para este run. Aguarde terminar ou cancele o job ativo.', 'bad');
  }
  criacaoState.burnStartInFlight = true;
  _syncCriacaoDraftsFromDom();
  const linkChanged = _syncLogoLayoutLinkBeforeRender();
  if (linkChanged) _persistWizardState({ immediate: true });
  const area = qs('burnSubsArea');
  criacaoState.burnedWarning = null;
  criacaoState.showBurnQueue = false;
  _burnQueueLastRefreshAt = 0;
  _operationProgressReset('burn');
  if (area) area.innerHTML = _renderBurnProgressHtml('Iniciando processamento…', 0);

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const bodyObj = _collectBurnRequestBody(videoObjectKey);

    const res = await fetch('/api/burn-subtitles', { method: 'POST', headers, body: JSON.stringify(bodyObj) });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      if (err.error === 'video_deleted') {
        _showBurnReupload(area);
        return;
      }
      throw new Error(err.detail || err.error || 'Erro no servidor');
    }

    const { job_id } = await res.json();
    if (!job_id) throw new Error('Servidor não retornou job_id');
    criacaoState.activeBurnJobId = job_id;
    criacaoState.burnStartInFlight = false;
    await _pollBurnJob(job_id, area);
  } catch (e) {
    criacaoState.burnStartInFlight = false;
    criacaoState.activeBurnJobId = null;
    if (area) area.innerHTML = _renderOperationProgressHtml(
      'burn',
      criacaoState.burnSkipSubtitles ? 'Queimar logo' : 'Queimar logo e legenda',
      `Erro: ${e.message}`,
      {
        kind: 'bad',
        extra: '<button class="btn" style="margin-top:10px;" onclick="burnSubtitles()">Tentar novamente</button>',
      },
    );
    toast('Erro: ' + e.message, 'bad');
  }
}

async function cancelBurnJob() {
  const jobId = criacaoState.activeBurnJobId;
  if (!jobId) return toast('Nenhum job ativo para cancelar', 'bad');
  try {
    const headers = {};
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch(`/api/burn-subtitles/cancel/${jobId}`, { method: 'POST', headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.detail || data.error || `Erro ${res.status}`);

    const area = qs('burnSubsArea');
    if (data.status === 'cancelled') {
      criacaoState.activeBurnJobId = null;
      criacaoState.burnStartInFlight = false;
      if (area) area.innerHTML = _renderOperationProgressHtml(
        'burn',
        criacaoState.burnSkipSubtitles ? 'Queimar logo' : 'Queimar logo e legenda',
        'Processamento cancelado.',
        {
          pct: 100,
          kind: 'bad',
          extra: '<button class="btn" style="margin-top:10px;" onclick="burnSubtitles()">Gerar novamente</button>',
        },
      );
      toast('Job cancelado', 'good');
      return;
    }
    if (area) area.innerHTML = _renderBurnProgressHtml('Cancelamento solicitado…', 0);
    toast('Cancelamento solicitado', 'good');
  } catch (e) {
    toast('Erro ao cancelar: ' + e.message, 'bad');
  }
}

async function _pollBurnJob(jobId, area) {
  const headers = {};
  if (state.apiKey) headers['X-API-Key'] = state.apiKey;
  let dots = 0;
  let transientErrs = 0;
  const maxTransientErrs = 20;

  const _isTransientMsg = (msg) => /status\s*(502|503|504|520|522|524)|failed to fetch|networkerror|load failed/i.test(msg || '');

  while (true) {
    await new Promise(r => setTimeout(r, 3000));
    dots = (dots % 3) + 1;
    try {
      const res = await fetch(`/api/burn-subtitles/status/${jobId}`, { headers });
      if (!res.ok) {
        let errBody = null;
        try { errBody = await res.json(); } catch {}
        if (res.status === 404 && errBody?.error === 'job_not_found') {
          throw new Error('O serviço reiniciou durante o processamento e este job foi perdido. Gere novamente o vídeo legendado.');
        }
        const statusMsg = errBody?.detail || errBody?.error || `Status ${res.status}`;
        if (_isTransientMsg(statusMsg) && transientErrs < maxTransientErrs) {
          transientErrs++;
          if (area) area.innerHTML = _renderBurnProgressHtml(`Conexão instável com o servidor (${transientErrs}/${maxTransientErrs})… tentando reconectar`, dots);
          if (criacaoState.showBurnQueue) await _refreshBurnQueueView();
          continue;
        }
        throw new Error(statusMsg);
      }
      transientErrs = 0;
      const job = await res.json();
      if (job.status === 'pending' || job.status === 'running') {
        const detail = job.detail || (job.status === 'running' ? 'Processando…' : 'Aguardando…');
        let queueLabel = '';
        if (job.status === 'pending' && job.queue_position) {
          const total = job.queue_size || job.queue_position;
          queueLabel = ` (fila ${job.queue_position}/${total})`;
        }
        if (area) area.innerHTML = _renderBurnProgressHtml(detail, dots, queueLabel, job.progress_pct);
        if (criacaoState.showBurnQueue) void _refreshBurnQueueView({ quiet: true });
        continue;
      }
      if (job.status === 'cancelled') {
        criacaoState.activeBurnJobId = null;
        criacaoState.burnStartInFlight = false;
        if (area) area.innerHTML = _renderOperationProgressHtml(
          'burn',
          criacaoState.burnSkipSubtitles ? 'Queimar logo' : 'Queimar logo e legenda',
          'Processamento cancelado.',
          {
            pct: 100,
            kind: 'bad',
            extra: '<button class="btn" style="margin-top:10px;" onclick="burnSubtitles()">Gerar novamente</button>',
          },
        );
        toast('Processamento cancelado', 'good');
        return;
      }
      if (job.status === 'done') {
        _burnApplyResult(job.video_url, job.filename, area, job.object_key, job.warning || '');
        return;
      }
      if (job.error === 'video_deleted') {
        criacaoState.activeBurnJobId = null;
        criacaoState.burnStartInFlight = false;
        _showBurnReupload(area);
        return;
      }
      throw new Error(job.detail || job.error || 'Erro no servidor');
    } catch (e) {
      const msg = e?.message || String(e);
      if (_isTransientMsg(msg) && transientErrs < maxTransientErrs) {
        transientErrs++;
        if (area) area.innerHTML = _renderBurnProgressHtml(`Falha temporária (${transientErrs}/${maxTransientErrs})… reconectando`, dots);
        if (criacaoState.showBurnQueue) void _refreshBurnQueueView({ force: true, quiet: true });
        continue;
      }
      criacaoState.activeBurnJobId = null;
      criacaoState.burnStartInFlight = false;
      if (area) area.innerHTML = _renderOperationProgressHtml(
        'burn',
        criacaoState.burnSkipSubtitles ? 'Queimar logo' : 'Queimar logo e legenda',
        `Erro: ${e.message}`,
        {
          kind: 'bad',
          extra: '<button class="btn" style="margin-top:10px;" onclick="burnSubtitles()">Tentar novamente</button>',
        },
      );
      toast('Erro: ' + e.message, 'bad');
      return;
    }
  }
}

function _showBurnReupload(area) {
  if (!area) return;
  area.innerHTML = `
    <div style="margin-bottom:6px;font-size:12px;color:var(--bad);">
      ⚠ O vídeo original foi removido do servidor após o processamento.<br>Selecione o arquivo .mp4 para aplicar a legenda:
    </div>
    <input type="file" id="burnSubsFile" accept="video/mp4,video/*" style="margin-bottom:6px;">
    <button class="btn primary" onclick="burnSubtitlesReupload()">📤 Enviar e processar</button>
  `;
}

async function generateTeaser() {
  if (!criacaoState.runId) return toast('Nenhum run selecionado', 'bad');
  const area = qs('teaserArea');
  if (!area) return;
  _syncCriacaoDraftsFromDom();
  _setTeaserSource(criacaoState.teaserSourceType, criacaoState.teaserSourceObjectKey, { persist: false, render: false });

  const sourceType = criacaoState.teaserSourceType === 'original' ? 'original' : 'burned';
  const originalSourceKey = _resolveOriginalVideoObjectKey();
  const videoObjectKey = (
    sourceType === 'original'
      ? (criacaoState.teaserSourceObjectKey || originalSourceKey || '')
      : (criacaoState.teaserSourceObjectKey || criacaoState.burnedObjectKey || '')
  ).trim() || null;
  if (!videoObjectKey) {
    return toast(sourceType === 'original'
      ? 'Selecione um vídeo original para gerar teaser.'
      : 'Selecione um vídeo queimado para gerar teaser.', 'bad');
  }

  const numClipsRaw = parseInt(qs('teaserClips')?.value || criacaoState.teaserNumClips || '8', 10);
  const clipDurRaw = parseFloat(qs('teaserClipDur')?.value || criacaoState.teaserClipDuration || '6');
  let numClips = _clamp(Number.isFinite(numClipsRaw) ? numClipsRaw : 8, 2, TEASER_MAX_NUM_CLIPS);
  let clipDur = _clamp(Number.isFinite(clipDurRaw) ? clipDurRaw : 6, 2, TEASER_MAX_SCENE_DURATION_SEC);
  const outputCrf = parseInt(qs('teaserQuality')?.value || criacaoState.teaserQuality || '26', 10);
  const outputMaxHeight = 1080;
  const outputMaxFps = 30;
  const autoDistribute = !!qs('teaserAutoDistribute')?.checked;
  const teaserTotalMinutes = qs('teaserTotalMinutes')?.value || criacaoState.teaserTargetDurationMin || '11';
  const teaserFirstMinutes = qs('teaserFirstClipMinutes')?.value || criacaoState.teaserFirstClipMin || '1';
  const teaserLastMinutes = qs('teaserLastClipMinutes')?.value || criacaoState.teaserLastClipMin || '1';
  const narrationEnabled = !!qs('teaserNarrationEnabled')?.checked;
  const originalVolRaw = parseFloat(qs('teaserOriginalAudioVolume')?.value || `${criacaoState.teaserOriginalAudioVolume || 100}`);
  const narrationVolRaw = parseFloat(qs('teaserNarrationVolume')?.value || `${criacaoState.teaserNarrationVolume || 120}`);
  const narrationOffsetRaw = parseFloat(qs('teaserNarrationOffsetSec')?.value || `${criacaoState.teaserNarrationOffsetSec || 0}`);
  const narrationObjectKey = String(criacaoState.teaserNarrationObjectKey || '').trim();
  const openerObjectKey = String(criacaoState.teaserOpenerObjectKey || '').trim();
  const openerPosition = (qs('teaserOpenerPosition')?.value || criacaoState.teaserOpenerPosition || 'start') === 'end' ? 'end' : 'start';
  const originalVolPct = _clamp(Number.isFinite(originalVolRaw) ? originalVolRaw : 100, 0, 200);
  const narrationVolPct = _clamp(Number.isFinite(narrationVolRaw) ? narrationVolRaw : 120, 0, 200);
  const narrationOffsetSec = _clamp(Number.isFinite(narrationOffsetRaw) ? narrationOffsetRaw : 0, -30, 30);

  if (narrationEnabled && !narrationObjectKey) {
    return toast('Envie um áudio de narração antes de gerar o teaser.', 'bad');
  }

  criacaoState.teaserNumClips = String(numClips);
  criacaoState.teaserClipDuration = String(clipDur);
  criacaoState.teaserQuality = String(outputCrf);
  criacaoState.teaserAutoDistribute = autoDistribute;
  criacaoState.teaserTargetDurationMin = String(teaserTotalMinutes);
  criacaoState.teaserFirstClipMin = String(teaserFirstMinutes);
  criacaoState.teaserLastClipMin = String(teaserLastMinutes);
  criacaoState.teaserSourceType = sourceType;
  criacaoState.teaserSourceObjectKey = videoObjectKey;
  if (sourceType === 'burned') criacaoState.teaserForceLogoOverlay = false;
  criacaoState.teaserNarrationEnabled = narrationEnabled;
  criacaoState.teaserOriginalAudioVolume = originalVolPct;
  criacaoState.teaserNarrationVolume = narrationVolPct;
  criacaoState.teaserNarrationOffsetSec = narrationOffsetSec;
  criacaoState.teaserOpenerPosition = openerPosition;
  criacaoState.teaserNarrationUsed = false;
  _persistWizardState();

  let selectedFrameIndexes = (criacaoState.teaserSelectedFrames || []).slice().sort((a, b) => a - b);
  const perSceneDurations = {};
  let orderedSceneDurations = [];
  if (autoDistribute) {
    const planSceneCount = _teaserPlannerSceneCount(numClips, selectedFrameIndexes);
    const plan = _buildTeaserDurationPlan(
      planSceneCount,
      teaserTotalMinutes,
      teaserFirstMinutes,
      teaserLastMinutes,
    );
    if (!plan.ok) return toast(plan.detail, 'bad');
    numClips = plan.sceneCount;
    clipDur = _clamp(plan.defaultSceneSec, 2, TEASER_MAX_SCENE_DURATION_SEC);
    orderedSceneDurations = plan.durationsSec.slice(0, numClips);
    if (selectedFrameIndexes.length) {
      selectedFrameIndexes = selectedFrameIndexes.slice(0, numClips);
      selectedFrameIndexes.forEach((idx, pos) => {
        perSceneDurations[idx] = orderedSceneDurations[pos];
      });
    }
  } else {
    selectedFrameIndexes.forEach((idx) => {
      const v = _teaserSceneDurationForFrame(idx);
      perSceneDurations[idx] = _clamp(v, 1, TEASER_MAX_SCENE_DURATION_SEC);
    });
  }
  criacaoState.teaserNumClips = String(numClips);
  criacaoState.teaserClipDuration = String(clipDur);
  _persistWizardState();
  if (_syncInheritedTeaserLogosFromMain()) _persistWizardState();
  const requestedTeaserDuration = _estimateTeaserRequestedDurationSec(
    numClips,
    clipDur,
    selectedFrameIndexes,
    perSceneDurations,
    orderedSceneDurations,
  );
  if (requestedTeaserDuration > TEASER_MAX_TOTAL_DURATION_SEC) {
    return toast(
      `Teaser muito longo: ${_formatDurationCompact(requestedTeaserDuration)}. Limite seguro atual: ${_formatDurationCompact(TEASER_MAX_TOTAL_DURATION_SEC)} por job.`,
      'bad',
    );
  }
  const teaserLogoPayload = _teaserLogoPayloadList();

  _operationProgressReset('teaser');
  area.innerHTML = _renderOperationProgressHtml('teaser', 'Gerar teaser', 'Iniciando geração do teaser…', { pct: 8 });

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const linkChanged = _syncLogoLayoutLinkBeforeRender();
    if (linkChanged) _persistWizardState({ immediate: true });

    const body = {
      run_id: criacaoState.runId,
      num_clips: numClips,
      clip_duration: clipDur,
      output_crf: outputCrf,
      output_max_height: outputMaxHeight,
      output_max_fps: outputMaxFps,
      source_type: sourceType,
      video_object_key: videoObjectKey,
      logo_profile_id: criacaoState.logoProfileId || null,
      logo_profile_name: criacaoState.logoProfileName || null,
      logo_profile_layout_linked: criacaoState.logoProfileLayoutLinked !== false,
      selected_frame_indexes: selectedFrameIndexes,
      scene_durations_by_frame: perSceneDurations,
      ordered_scene_durations: orderedSceneDurations,
      frames_count: (criacaoState.frames || []).length,
      force_logo_overlay: sourceType === 'burned' ? false : !!criacaoState.teaserForceLogoOverlay,
      narration: {
        enabled: narrationEnabled,
        object_key: narrationObjectKey || null,
        original_audio_volume: originalVolPct / 100,
        narration_volume: narrationVolPct / 100,
        offset_sec: narrationOffsetSec,
      },
      opener: {
        object_key: openerObjectKey || null,
        position: openerPosition,
      },
    };

    if (sourceType !== 'burned' && criacaoState.teaserForceLogoOverlay && teaserLogoPayload.length) {
      body.logos = teaserLogoPayload;
    } else if (sourceType !== 'burned' && criacaoState.teaserForceLogoOverlay && criacaoState.logoB64) {
      // Compatibilidade: mantém fallback para logo única herdada do Passo 1.
      body.logo_b64 = criacaoState.logoB64;
      body.logo_x = criacaoState.logoX;
      body.logo_y = criacaoState.logoY;
      body.logo_scale_pct = criacaoState.logoScalePct;
      body.logo_opacity = criacaoState.logoOpacity;
    }

    const res = await fetch('/api/teaser/generate', { method: 'POST', headers, body: JSON.stringify(body) });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `Erro ${res.status}`);
    }

    const { job_id } = await res.json();
    if (!job_id) throw new Error('Servidor não retornou job_id');
    await _pollTeaserJob(job_id, area);
  } catch (e) {
    area.innerHTML = _renderOperationProgressHtml(
      'teaser',
      'Gerar teaser',
      `Erro: ${e.message}`,
      {
        kind: 'bad',
        extra: '<button class="btn" style="margin-top:10px;" onclick="generateTeaser()">Tentar novamente</button>',
      },
    );
    toast('Erro ao gerar teaser: ' + e.message, 'bad');
  }
}

async function _pollTeaserJob(jobId, area) {
  const headers = {};
  if (state.apiKey) headers['X-API-Key'] = state.apiKey;
  let dots = 0;

  while (true) {
    await new Promise(r => setTimeout(r, 3000));
    dots = (dots % 3) + 1;
    try {
      const res = await fetch(`/api/teaser/status/${jobId}`, { headers });
      if (!res.ok) throw new Error(`Status ${res.status}`);
      const job = await res.json();
      if (job.status === 'pending' || job.status === 'running') {
        const detail = job.detail || (job.status === 'running' ? 'Processando…' : 'Aguardando…');
        area.innerHTML = _renderOperationProgressHtml('teaser', 'Gerar teaser', detail, { dots });
        continue;
      }
      if (job.status === 'done') {
        area.innerHTML = _renderOperationProgressHtml('teaser', 'Gerar teaser', 'Teaser concluído. Carregando preview…', { pct: 100, kind: 'good' });
        await _updateTeaserPreview(job.video_url, job.object_key, area, job);
        return;
      }
      throw new Error(job.detail || job.error || 'Erro no servidor');
    } catch (e) {
      area.innerHTML = _renderOperationProgressHtml(
        'teaser',
        'Gerar teaser',
        `Erro: ${e.message}`,
        {
          kind: 'bad',
          extra: '<button class="btn" style="margin-top:10px;" onclick="generateTeaser()">Tentar novamente</button>',
        },
      );
      toast('Erro: ' + e.message, 'bad');
      return;
    }
  }
}

async function _updateTeaserPreview(videoUrl, objectKey, area, job = null) {
  let streamUrl = '';
  if (objectKey) {
    try {
      streamUrl = await _getAdaptivePreviewUrl(objectKey, { maxHeight: 1080, maxFps: 30 });
      if (!streamUrl) streamUrl = await _getVideoStreamUrl(objectKey);
    } catch (_) {
      streamUrl = '';
    }
  }
  // Um teaser recém-gerado passa a ser a verdade atual do run.
  // Se existir um teaser com logo derivado de tentativa antiga, limpamos para não confundir a UI.
  criacaoState.teaserLogoUrl = null;
  criacaoState.teaserLogoObjectKey = null;
  criacaoState.teaserLogoFilename = null;
  criacaoState.teaserUrl = streamUrl || videoUrl || null;
  criacaoState.teaserObjectKey = objectKey;
  if (job && typeof job === 'object') {
    criacaoState.teaserNarrationUsed = !!job.narration_used;
    if (job.original_audio_volume != null) {
      criacaoState.teaserOriginalAudioVolume = _toNum(Number(job.original_audio_volume) * 100, criacaoState.teaserOriginalAudioVolume, 0, 200);
    }
    if (job.narration_volume != null) {
      criacaoState.teaserNarrationVolume = _toNum(Number(job.narration_volume) * 100, criacaoState.teaserNarrationVolume, 0, 200);
    }
    if (job.narration_offset_sec != null) {
      criacaoState.teaserNarrationOffsetSec = _toNum(job.narration_offset_sec, criacaoState.teaserNarrationOffsetSec, -30, 30);
    }
    if (job.narration_object_key) {
      criacaoState.teaserNarrationObjectKey = String(job.narration_object_key);
    }
    if (job.opener_object_key != null) {
      const openerKey = String(job.opener_object_key || '').trim();
      criacaoState.teaserOpenerObjectKey = openerKey || null;
      if (!openerKey) criacaoState.teaserOpenerUrl = null;
      if (openerKey && !criacaoState.teaserOpenerUrl) {
        _getVideoStreamUrl(openerKey).then((u) => {
          if (!u) return;
          if (criacaoState.teaserOpenerObjectKey !== openerKey) return;
          criacaoState.teaserOpenerUrl = u;
          _persistWizardState();
          if (area) area.innerHTML = _renderTeaserResultHtml();
        }).catch(() => {});
      }
    }
    if (job.opener_position) {
      criacaoState.teaserOpenerPosition = String(job.opener_position) === 'end' ? 'end' : 'start';
    }
  }
  if (area) area.innerHTML = _renderTeaserResultHtml();
  _persistWizardState({ immediate: true });
  if (criacaoState.postResult) renderPostResult(criacaoState.postResult);
  toast('Teaser pronto!', 'good');
}

function setTeaserConcatMode(mode) {
  criacaoState.teaserConcatMode = mode === 'end' ? 'end' : 'start';
  _persistWizardState();
  const area = qs('teaserArea');
  if (area && criacaoState.teaserUrl) area.innerHTML = _renderTeaserResultHtml();
}

async function prependTeaser() {
  if (!criacaoState.teaserObjectKey) return toast('Gere o teaser primeiro', 'bad');
  if (!criacaoState.burnedObjectKey) return toast('Gere o vídeo legendado primeiro', 'bad');

  const area = qs('teaserArea');
  if (!area) return;

  _operationProgressReset('teaserConcat');
  area.innerHTML = _renderTeaserResultHtml() + `<div id="prependArea" style="margin-top:10px;">${_renderOperationProgressHtml('teaserConcat', 'Concatenar teaser', 'Concatenando teaser + vídeo…', { pct: 8 })}</div>`;
  const prependArea = qs('prependArea');

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;

    const res = await fetch('/api/teaser/prepend', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        run_id: criacaoState.runId,
        teaser_object_key: criacaoState.teaserObjectKey,
        main_object_key: criacaoState.burnedObjectKey,
        position: criacaoState.teaserConcatMode === 'end' ? 'end' : 'start',
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `Erro ${res.status}`);
    }

    const { job_id } = await res.json();
    if (!job_id) throw new Error('Servidor não retornou job_id');

    let dots = 0;
    while (true) {
      await new Promise(r => setTimeout(r, 3000));
      dots = (dots % 3) + 1;
      const sr = await fetch(`/api/teaser/status/${job_id}`, { headers: state.apiKey ? { 'X-API-Key': state.apiKey } : {} });
      if (!sr.ok) throw new Error(`Status ${sr.status}`);
      const job = await sr.json();
      if (job.status === 'pending' || job.status === 'running') {
        if (prependArea) prependArea.innerHTML = _renderOperationProgressHtml('teaserConcat', 'Concatenar teaser', job.detail || 'Concatenando teaser + vídeo…', { dots });
        continue;
      }
      if (job.status === 'done') {
        criacaoState.teaserCombinedObjectKey = job.object_key;
        let combinedUrl = job.video_url || null;
        if (job.object_key) {
          const streamUrl = await _getVideoStreamUrl(job.object_key).catch(() => null);
          if (streamUrl) combinedUrl = streamUrl;
        }
        criacaoState.teaserCombinedUrl = combinedUrl;
        _persistWizardState({ immediate: true });
        if (prependArea) prependArea.innerHTML = _renderOperationProgressHtml('teaserConcat', 'Concatenar teaser', 'Vídeo completo concluído.', { pct: 100, kind: 'good' });
        if (area) area.innerHTML = _renderTeaserResultHtml();
        if (criacaoState.postResult) renderPostResult(criacaoState.postResult);
        toast('Vídeo completo pronto!', 'good');
        return;
      }
      throw new Error(job.detail || job.error || 'Erro no servidor');
    }
  } catch (e) {
    if (prependArea) prependArea.innerHTML = _renderOperationProgressHtml('teaserConcat', 'Concatenar teaser', `Erro: ${e.message}`, { kind: 'bad' });
    toast('Erro ao concatenar: ' + e.message, 'bad');
  }
}

async function burnSubtitlesReupload() {
  const file = qs('burnSubsFile')?.files?.[0];
  if (!file) return toast('Selecione o arquivo de vídeo', 'bad');
  const area = qs('burnSubsArea');

  try {
    _operationProgressReset('burnUpload');
    if (area) area.innerHTML = _renderOperationProgressHtml('burnUpload', 'Enviar vídeo para queima', 'Preparando upload…', { pct: 0 });
    const proxy = await _uploadViaProxy(file, {
      prefix: 'burn-temp',
      validateVideo: true,
      deleteIfInvalid: true,
      onProgress: (loaded, total) => {
        if (total > 0 && area) {
          area.innerHTML = _renderOperationProgressHtml(
            'burnUpload',
            'Enviar vídeo para queima',
            `Enviando vídeo… ${Math.round(loaded / total * 100)}%`,
            { pct: Math.round(loaded / total * 100) },
          );
        }
      },
    });

    if (area) area.innerHTML = _renderOperationProgressHtml('burnUpload', 'Enviar vídeo para queima', 'Upload concluído. Iniciando queima…', { pct: 100, kind: 'good' });
    await burnSubtitles(proxy.object_key);
  } catch (e) {
    if (area) area.innerHTML = _renderOperationProgressHtml(
      'burnUpload',
      'Enviar vídeo para queima',
      `Erro: ${e.message}`,
      {
        kind: 'bad',
        extra: '<button class="btn" style="margin-top:10px;" onclick="_showBurnReupload(qs(\'burnSubsArea\'))">Tentar novamente</button>',
      },
    );
    toast('Erro: ' + e.message, 'bad');
  }
}

async function schedulePost() {
  if (!criacaoState.postResult) return toast('Gere o post primeiro', 'bad');
  const dt = qs('schedDateTime')?.value;
  const schedAt = dt ? new Date(dt).toISOString() : null;

  try {
    const res = await apiFetch('/api/scheduled-posts', {
      method: 'POST',
      body: JSON.stringify({
        run_id: criacaoState.runId,
        post_data: criacaoState.postResult,
        schedule_at: schedAt,
      }),
    });
    if (!res.ok) throw new Error(res.error || 'Erro ao agendar');
    toast('Post agendado! ID: ' + res.id, 'good');
    loadScheduledPosts();
  } catch (e) {
    toast(e.message, 'bad');
  }
}

async function loadScheduledPosts() {
  const wrap = qs('schedList');
  if (!wrap) return;
  try {
    const r = await apiFetch('/api/scheduled-posts');
    const posts = r.posts || [];
    if (!posts.length) {
      wrap.innerHTML = '<div class="criacao-empty">Nenhum agendamento ainda.</div>';
      return;
    }
    wrap.innerHTML = posts.map(p => {
      const pd = p.post_data?.post_data || p.post_data || {};
      const title = pd.title || p.run_id?.slice(0, 20) + '…';
      const dt = p.schedule_at ? fmtDate(p.schedule_at) : 'sem data';
      const statusClass = p.status === 'pending' ? 'pending' : p.status === 'notified' ? 'notified' : 'cancelled';
      return `
        <div class="sched-item">
          <div>
            <div style="font-size:13px;font-weight:500;">${esc(title)}</div>
            <div class="hint">📅 ${esc(dt)} · run: ${esc((p.run_id || '').slice(0, 16))}…</div>
          </div>
          <span class="sched-status ${statusClass}">${esc(p.status)}</span>
          <button class="btn" style="font-size:11px;" onclick="cancelScheduledPost('${esc(p.id)}')">✕</button>
        </div>
      `;
    }).join('');
  } catch (e) {
    wrap.innerHTML = `<div class="criacao-empty">Erro: ${esc(e.message)}</div>`;
  }
}

async function cancelScheduledPost(id) {
  try {
    await apiFetch(`/api/scheduled-posts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'cancelled' }),
    });
    toast('Agendamento cancelado');
    loadScheduledPosts();
  } catch (e) {
    toast(e.message, 'bad');
  }
}

// ─────────────────────────────────────────────────────────────────────────────

function initTabs() {
  document.querySelectorAll('#page-analyze .tab').forEach(b => {
    b.addEventListener('click', () => setAnalyzeTab(b.dataset.tab));
  });
  setAnalyzeTab('prompt');
}

function initButtons() {
  qs('btnSaveApiKey').onclick = saveApiKey;

  qs('btnAnalyze').onclick = doAnalyze;
  qs('btnAnalyzeClear').onclick = clearAnalyze;
  qs('btnCopyPrompt').onclick = () => copyText(qs('anPrompt').textContent || '');
  qs('btnToCompare').onclick = toCompareFromAnalyze;
  qs('btnDownloadSrt').onclick = downloadSrt;

  qs('btnCompare').onclick = doCompare;
  qs('btnCompareClear').onclick = clearCompare;
  qs('btnCopyA').onclick = () => copyText(qs('cmpOutA').textContent || '');
  qs('btnCopyB').onclick = () => copyText(qs('cmpOutB').textContent || '');

  qs('btnRunsReload').onclick = reloadRuns;
  qs('btnRunDeleteSelected').onclick = deleteSelectedRun;
  qs('btnMediaRefresh').onclick = () => loadMediaManagerPage(true);
  qs('btnMediaDriveSave').onclick = saveGoogleDriveConfig;
  qs('btnMediaDriveReload').onclick = () => refreshGoogleDriveConfig();
  qs('btnMediaDriveIntakeReload').onclick = () => reloadDriveIntakeFiles();
  qs('btnMediaDriveImportSelected').onclick = importSelectedDriveIntakeFiles;
  qs('btnMediaDriveSelectAll').onclick = selectAllDriveIntakeFiles;
  qs('btnMediaDriveClearSelected').onclick = clearDriveIntakeSelection;
  qs('btnMediaSelectFiltered').onclick = selectAllManagedMediaFiltered;
  qs('btnMediaClearSelection').onclick = clearManagedMediaSelection;
  qs('btnMediaBulkDrive').onclick = bulkSendManagedMediaToDrive;
  qs('btnMediaBulkDelete').onclick = bulkDeleteManagedMedia;
  qs('btnMediaViewIcons').onclick = () => setMediaManagerViewMode('icons');
  qs('btnMediaViewList').onclick = () => setMediaManagerViewMode('list');
  qs('mediaManagerTileSize').addEventListener('input', (e) => setMediaManagerTileSize(e.target.value));
  qs('mediaManagerTileShape').addEventListener('change', (e) => setMediaManagerTileShape(e.target.value));
  qs('mediaManagerSearch').addEventListener('input', (e) => setMediaManagerSearch(e.target.value));
  qs('mediaManagerLimit').addEventListener('change', () => loadMediaManagerPage(true));
  qs('mediaDriveCreatorSelect').addEventListener('change', (e) => {
    mediaManagerState.driveIntakeCreatorId = String(e.target?.value || '').trim();
    clearDriveIntakeSelection();
    reloadDriveIntakeFiles();
  });

  qs('btnCriacaoReload').onclick = loadCriacaoRuns;
  qs('btnCriacaoClearSelected').onclick = clearSelectedCriacaoRun;
  qs('btnCriacaoDeleteSelected').onclick = deleteSelectedCriacaoRun;

  qs('btnScrAnalyze').onclick = analyzeScreenshot;

  ['cf_portal_brand_name','cf_portal_headline','cf_portal_tagline','cf_portal_primary_color','cf_portal_secondary_color','cf_portal_accent_color','cf_portal_surface_color','cf_portal_text_color']
    .forEach((id) => {
      const el = qs(id);
      if (!el) return;
      el.addEventListener('input', _updateCreatorPortalPreview);
      el.addEventListener('change', _updateCreatorPortalPreview);
    });
}

// Each entry: { id: 'api-model-id', label: 'Nome [$|free|local] 🔞N/10' }
// 🔞 score = permissividade para conteúdo adulto explícito (0=censura total, 10=sem filtro)
const PROVIDER_MODELS = {
  openai: [
    { id: 'gpt-4o',      label: 'gpt-4o [$] 🔞4/10' },
    { id: 'gpt-4o-mini', label: 'gpt-4o-mini [$] 🔞3/10' },
    { id: 'o1',          label: 'o1 [$] 🔞3/10' },
    { id: 'o1-mini',     label: 'o1-mini [$] 🔞3/10' },
    { id: 'o3-mini',     label: 'o3-mini [$] 🔞3/10' },
  ],
  deepseek: [
    { id: 'deepseek-chat',      label: 'deepseek-chat V3 [$] 🔞7/10' },
    { id: 'deepseek-reasoner',  label: 'deepseek-reasoner R1 [$] 🔞7/10' },
  ],
  grok: [
    { id: 'grok-3-beta',          label: 'grok-3-beta [$] 🔞9/10' },
    { id: 'grok-3-mini-beta',     label: 'grok-3-mini-beta [$] 🔞8/10' },
    { id: 'grok-2-vision-1212',   label: 'grok-2-vision-1212 [$] 🔞9/10' },
  ],
  gemini: [
    { id: 'gemini-2.0-flash',      label: 'gemini-2.0-flash [$] 🔞3/10' },
    { id: 'gemini-2.0-flash-lite', label: 'gemini-2.0-flash-lite [free] 🔞3/10' },
    { id: 'gemini-1.5-pro',        label: 'gemini-1.5-pro [$] 🔞3/10' },
    { id: 'gemini-1.5-flash',      label: 'gemini-1.5-flash [free] 🔞3/10' },
    { id: 'gemini-1.5-flash-8b',   label: 'gemini-1.5-flash-8b [free] 🔞3/10' },
  ],
  openrouter: [
    // — Grok via OpenRouter — (testado OK ✓)
    { id: 'x-ai/grok-3-beta',      label: 'Grok 3 Beta [$] 🔞9/10' },
    { id: 'x-ai/grok-3-mini-beta', label: 'Grok 3 Mini [$] 🔞8/10' },
    // — OpenAI via OpenRouter — (testado OK ✓)
    { id: 'openai/gpt-4o',         label: 'GPT-4o [$] 🔞4/10' },
    { id: 'openai/gpt-4o-mini',    label: 'GPT-4o Mini [$] 🔞3/10' },
    // — Anthropic via OpenRouter — (testado OK ✓)
    { id: 'anthropic/claude-3.7-sonnet', label: 'Claude 3.7 Sonnet [$] 🔞2/10' },
    { id: 'anthropic/claude-3.5-sonnet', label: 'Claude 3.5 Sonnet [$] 🔞2/10' },
    { id: 'anthropic/claude-3-haiku',    label: 'Claude 3 Haiku [$] 🔞2/10' },
    // — Google via OpenRouter — (testado OK ✓)
    { id: 'google/gemini-2.0-flash-001', label: 'Gemini 2.0 Flash [$] 🔞3/10' },
    // — DeepSeek via OpenRouter — (testado OK ✓)
    { id: 'deepseek/deepseek-chat', label: 'DeepSeek V3 [$] 🔞7/10' },
    { id: 'deepseek/deepseek-r1',   label: 'DeepSeek R1 [$] 🔞7/10' },
    // — Meta LLaMA via OpenRouter — (testado OK ✓)
    { id: 'meta-llama/llama-3.3-70b-instruct', label: 'LLaMA 3.3 70B [$] 🔞6/10' },
    // — Mistral via OpenRouter — (testado OK ✓)
    { id: 'mistralai/mixtral-8x7b-instruct', label: 'Mixtral 8x7B [$] 🔞7/10' },
    // — Qwen via OpenRouter — (testado OK ✓)
    { id: 'qwen/qwen-2.5-72b-instruct', label: 'Qwen 2.5 72B [$] 🔞7/10' },
    // — Free (rate-limit possível) —
    { id: 'meta-llama/llama-3.2-3b-instruct:free',           label: 'LLaMA 3.2 3B [free⚡] 🔞5/10' },
    { id: 'mistralai/mistral-small-3.1-24b-instruct:free',   label: 'Mistral Small 24B [free⚡] 🔞6/10' },
  ],
  ollama: [
    { id: 'dolphin-mixtral:8x7b',      label: 'Dolphin Mixtral 8x7B [local] 🔞10/10 ⭐melhor' },
    { id: 'dolphin3:8b',               label: 'Dolphin3 8B [local] 🔞10/10 ⚡rápido' },
    { id: 'dolphin-mistral:7b-v2.8',   label: 'Dolphin Mistral 7B [local] 🔞10/10' },
    { id: 'llava-llama3:8b',           label: 'LLaVA LLaMA3 8B [local vision] 🔞8/10' },
  ],
};

function updateModelOptions(provId, selectId) {
  const prov = qs(provId).value;
  const sel = qs(selectId);
  const prev = sel.value;
  sel.innerHTML = '';
  (PROVIDER_MODELS[prov] || []).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id || m;
    opt.textContent = m.label || m;
    sel.appendChild(opt);
  });
  // restore previous selection if still available, else default to first
  if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
}

async function main() {
  // Step 0: config locais
  _pageLoader.step(0);
  loadApiKey();

  // Step 1: perfis de logo
  _pageLoader.step(1);
  await _loadSavedLogoPreset();
  await _loadLogoProfiles();

  // Step 2: autenticação
  _pageLoader.step(2);
  await authInit();

  // Step 3: interface
  _pageLoader.step(3);
  paintMetaPornOsIcons();
  initRouting();
  initTabs();
  initButtons();
  wireModelDefaults();
  updateModelOptions('cmpProvA', 'cmpModelA');
  updateModelOptions('cmpProvB', 'cmpModelB');

  // Step 4: health check / conexão
  _pageLoader.step(4);
  await healthTick();
  setInterval(healthTick, 30000);

  // Step 5: dados iniciais (runs se aba ativa for analyser)
  _pageLoader.step(5);
  await new Promise(r => setTimeout(r, 80));

  // Fechar loader
  _pageLoader.close();
}

// ── SISTEMA DE AJUDA FLUTUANTE ────────────────────────────────────────────────

const helpContent = {
  settings: {
    title: "Ajuda - Settings",
    sections: [
      {
        title: "API Key (Admin)",
        content: `
          <p>A API Key é usada para autenticação em todas as chamadas ao servidor. Ela fica armazenada apenas no seu navegador (sessionStorage) e não é enviada ao servidor de forma persistente.</p>
          <div class="warning">
            <p><strong>⚠️ Importante:</strong> Esta key é diferente das tokens de API dos provedores de IA. Ela serve para proteger o acesso à aplicação.</p>
          </div>
          <p><strong>Como obter:</strong> A API Key deve ser configurada na variável de ambiente <span class="help-code">ADULT_META_API_KEY</span> no servidor.</p>
        `
      },
      {
        title: "Tokens de API",
        content: `
          <p>Os tokens de API são usados para conectar aos serviços de IA (OpenAI, Groq, DeepSeek, etc). Eles são salvos no banco de dados do servidor de forma segura.</p>
          <p><strong>Como configurar:</strong></p>
          <ul>
            <li>Obtenha a API key no site do provedor desejado</li>
            <li>Cole no campo correspondente e clique em "Salvar"</li>
            <li>O sistema mostra apenas se está configurado ou não (nunca exibe a chave)</li>
          </ul>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Recomendamos configurar pelo menos OpenAI ou Groq para ter acesso completo às funcionalidades.</p>
          </div>
        `
      },
      {
        title: "Diagnóstico Vision API",
        content: `
          <p>Esta ferramenta testa a conexão com os modelos xAI (Grok) para análise de visão/computador.</p>
          <p><strong>Quando usar:</strong></p>
          <ul>
            <li>Quando a análise de screenshots não funciona</li>
            <li>Quando recebe erros HTTP do xAI</li>
            <li>Para verificar se o serviço está online</li>
          </ul>
          <p><strong>Como usar:</strong> Clique em "Executar Diagnóstico" e aguarde. O resultado mostra cada modelo testado e o status.</p>
        `
      }
    ]
  },
  analyze: {
    title: "Ajuda - Analyze",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>A página <strong>Analyze</strong> é onde você analisa vídeos para gerar conteúdo automaticamente usando Inteligência Artificial.</p>
          <p>Ela combina: upload de vídeo, transcrição de áudio, análise de frames por IA, busca de referências no XVideos e geração de metadados.</p>
        `
      },
      {
        title: "Upload de Vídeo",
        content: `
          <p><strong> duas formas de adicionar vídeos:</strong></p>
          <ul>
            <li><strong>Selecionar do servidor:</strong> Escolhe um vídeo já enviado anteriormente</li>
            <li><strong>Fazer upload:</strong> Envia um novo vídeo do seu computador</li>
          </ul>
          <p><strong>Sobre uploads:</strong></p>
          <ul>
            <li>Vídeos são armazenados no MinIO (storage S3)</li>
            <li>Tamanho máximo: 5GB por arquivo</li>
            <li>Formatos suportados: MP4, MOV, MKV, AVI, WEBM</li>
          </ul>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Uploads grandes podem demorar. O progresso é mostrado em tempo real.</p>
          </div>
        `
      },
      {
        title: "Transcrição",
        content: `
          <p>A transcrição converte a fala do vídeo em texto. Você pode:</p>
          <ul>
            <li><strong>Deixar em branco:</strong> Se já tiver uma transcrição pronta</li>
            <li><strong>Colar texto:</strong> Transcrição manual ou de outro serviço</li>
            <li><strong>Usar automática:</strong> Clique em "Analisar" que o sistema transcrive se necessário</li>
          </ul>
          <p><strong>Idiomas suportados:</strong> O sistema detecta automaticamente, ou você pode especificar (pt-BR, en, es, etc)</p>
          <div class="warning">
            <p><strong>⚠️ Cuidado:</strong> A transcrição automática pode demorar varios minutos em videos longos. Use a opção local (faster-whisper) para evitar custos de API.</p>
          </div>
        `
      },
      {
        title: "Referências e Filtros",
        content: `
          <p>Os filtros ajudam a encontrar vídeos de referência mais relevantes no XVideos.</p>
          <table class="help-table">
            <tr><th>Filtro</th><th>Descrição</th></tr>
            <tr><td>Atriz/Ator</td><td>Nome da performer (ex: "Mônica Matos")</td></tr>
            <tr><td>Qtd Atores</td><td>Solo (1), Casal (2), Trio (3), etc</td></tr>
            <tr><td>País</td><td>Nacionalidade (Brasil, Japão, EUA, etc)</td></tr>
            <tr><td>Categoria</td><td>Gênero (Teen, MILF, BBW, etc)</td></tr>
            <tr><td>Canal/Studio</td><td>Estúdio produtora</td></tr>
            <tr><td>Duração</td><td>Curto (1-3min), Médio, Longo, Muito longo</td></tr>
            <tr><td>Views mín/máx</td><td>Filtrar por contagem de visualizações</td></tr>
            <tr><td>Curtidas mín</td><td>Filtrar por número de likes</td></tr>
          </table>
        `
      },
      {
        title: "Análise de Screenshot",
        content: `
          <p>Permite analisar uma imagem usando IA de visão (xAI/Grok). Útil para:</p>
          <ul>
            <li>Analisar um frame específico do vídeo</li>
            <li>Obter tags e descrição de uma imagem</li>
            <li>Verificar conteúdo sem precisar do vídeo todo</li>
          </ul>
          <p><strong>Como usar:</strong></p>
          <ol>
            <li>Clique em "Upload de Screenshot"</li>
            <li>Selecione uma imagem do seu computador</li>
            <li>Clique em "Analisar com IA"</li>
          </ol>
          <div class="warning">
            <p><strong>⚠️ Importante:</strong> Requer API key do xAI (Grok) configurada na página Settings.</p>
          </div>
        `
      },
      {
        title: "Botão Analisar",
        content: `
          <p>O botão <strong>"Analisar"</strong> inicia todo o processo de geração de conteúdo:</p>
          <ol>
            <li>Gera transcrição (se necessário)</li>
            <li>Analisa frames do vídeo com IA</li>
            <li>Busca referências no XVideos</li>
            <li>Gera título, descrição, tags, hashtags</li>
            <li>Cria prompt otimizado para post</li>
          </ol>
          <p><strong>Tempo estimado:</strong></p>
          <ul>
            <li>Vídeo curto (até 5 min): 2-5 minutos</li>
            <li>Vídeo médio (5-15 min): 5-10 minutos</li>
            <li>Vídeo longo (15+ min): 10-20 minutos</li>
          </ul>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Enquanto analisa, você pode navegar em outras abas. O resultado fica salvo.</p>
          </div>
        `
      },
      {
        title: "Abas de Resultado",
        content: `
          <p>Após a análise, você pode ver os resultados em diferentes abas:</p>
          <ul>
            <li><strong>Prompt:</strong> Texto gerado para post em formato markdown</li>
            <li><strong>SRT:</strong> Legendas em formato SubRip (timestamps)</li>
            <li><strong>Visão IA:</strong> Frames analisados + descrição da IA</li>
            <li><strong>JSON:</strong> Dados completos em formato técnico</li>
          </ul>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Cancelar o processo no meio - pode deixar dados incompletos</li>
              <li>Recarregar a página durante análise - perde o progresso</li>
              <li>Usar vídeos muito longos para teste - demorado e custoso</li>
              <li>Esquecer de configurar tokens - análise vai falhar</li>
            </ul>
          </div>
        `
      }
    ]
  },
  compare: {
    title: "Ajuda - Compare",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>A página <strong>Compare</strong> permite comparar respostas de diferentes provedores de IA lado a lado.</p>
          <p>Isso é útil para:</p>
          <ul>
            <li>Testar qual modelo gera melhores resultados</li>
            <li>Comparar qualidade entre provedores</li>
            <li>Escolher a melhor resposta para usar</li>
          </ul>
        `
      },
      {
        title: "Como usar",
        content: `
          <p><strong>Passo a passo:</strong></p>
          <ol>
            <li>Escreva ou cole um <strong>prompt</strong> na caixa de texto</li>
            <li>Selecione o <strong>Provider A</strong> (primeiro modelo)</li>
            <li>Selecione o <strong>Provider B</strong> (segundo modelo para comparar)</li>
            <li>Ajuste os <strong>parâmetros</strong> se necessário (temperature, max_tokens)</li>
            <li>Clique em <strong>"Iniciar comparação"</strong></li>
          </ol>
          <p>Ambos os provedores são executados simultaneamente e você vê as respostas em tempo real.</p>
        `
      },
      {
        title: "Providers disponíveis",
        content: `
          <table class="help-table">
            <tr><th>Provider</th><th>Descrição</th></tr>
            <tr><td>grok (xAI)</td><td>Modelos Grok 3 (mais recente)</td></tr>
            <tr><td>openai</td><td>GPT-4o, GPT-4o-mini</td></tr>
            <tr><td>deepseek</td><td>DeepSeek Chat/R1</td></tr>
            <tr><td>gemini</td><td>Google Gemini</td></tr>
            <tr><td>openrouter</td><td>Acesso a múltiplos modelos</td></tr>
            <tr><td>ollama</td><td>Modelos locais</td></tr>
          </table>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Cada provider tem modelos diferentes. Selecione o modelo na caixa suspensa abaixo do provider.</p>
          </div>
        `
      },
      {
        title: "Parâmetros",
        content: `
          <p><strong>Temperature:</strong> Controla a criatividade da IA. Valores:</p>
          <ul>
            <li><strong>0.0 - 0.3:</strong> Respostas mais consistentes e precisas</li>
            <li><strong>0.4 - 0.7:</strong> Equilíbrio (padrão: 0.7)</li>
            <li><strong>0.8 - 1.0:</strong> Mais criativas e variedas</li>
          </ul>
          <p><strong>Max Tokens:</strong> Limite de tokens na resposta. Padrão: 1200.</p>
          <div class="warning">
            <p><strong>⚠️ Cuidado:</strong> Tokens altos podem gerar custos maiores. 1000 tokens ≈ 750 palavras.</p>
          </div>
        `
      },
      {
        title: "Barra de progresso",
        content: `
          <p>Durante a comparação, você vê:</p>
          <ul>
            <li>Barra de progresso total</li>
            <li>Status de cada provider (conectando, processando, concluído)</li>
            <li>Contagem de tokens gerados</li>
            <li>Tempo decorrido</li>
          </ul>
        `
      },
      {
        title: "Usar resultado",
        content: `
          <p>Após ver as respostas, você pode:</p>
          <ul>
            <li>Clique em <strong>"Copiar"</strong> para copiar o texto</li>
            <li>Clique em <strong>"Usar esta versão no Criação"</strong> para enviar ao editor de posts</li>
          </ul>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Compare provedores diferentes para o mesmo prompt e escolha o melhor!</p>
          </div>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Prompts muito longos - pode atingir limite de contexto</li>
              <li>Selecionar o mesmo provider nos dois campos - não há o que comparar</li>
              <li>Usar temperature muito alta para tarefas técnicas - pode gerar erros</li>
            </ul>
          </div>
        `
      }
    ]
  },
  runs: {
    title: "Ajuda - Runs",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>A página <strong>Runs</strong> mostra o histórico de todas as análises realizadas no sistema.</p>
          <p>Cada "run" é uma análise completa de um vídeo, com todos os dados gerados.</p>
        `
      },
      {
        title: "Como usar",
        content: `
          <p><strong>Visualizar um run:</strong></p>
          <ol>
            <li>Na lista à esquerda, clique em qualquer item</li>
            <li>Os detalhes aparecem na área principal</li>
            <li>Você pode ver: transcrição, prompt, SRT, frames, JSON completo</li>
          </ol>
          <p><strong>Filtrar resultados:</strong></p>
          <ul>
            <li>Use o campo <strong>"Limit"</strong> para mostrar mais ou menos itens</li>
            <li>Clique em <strong>"↺"</strong> para atualizar a lista</li>
          </ul>
        `
      },
      {
        title: "Dados do Run",
        content: `
          <p>Cada run contém:</p>
          <ul>
            <li><strong>ID:</strong> Identificador único</li>
            <li><strong>Data:</strong> Quando foi criado</li>
            <li><strong>Source:</strong> Fonte do vídeo (URL ou arquivo)</li>
            <li><strong>Transcrição:</strong> Texto completo do áudio</li>
            <li><strong>Prompt:</strong> Conteúdo gerado pela IA</li>
            <li><strong>SRT:</strong> Legendas com timestamps</li>
            <li><strong>Frames:</strong> Imagens extraídas do vídeo</li>
            <li><strong>Resultado:</strong> Dados completos em JSON</li>
          </ul>
        `
      },
      {
        title: "Ações disponíveis",
        content: `
          <p>Em cada run, você pode:</p>
          <ul>
            <li><strong>Copiar prompt:</strong> Copia o texto gerado</li>
            <li><strong>Baixar SRT:</strong> Download do arquivo de legendas</li>
            <li><strong>Reprompt:</strong> Regenerar com novos parâmetros</li>
            <li><strong>Atualizar transcrição:</strong> Editar texto manualmente</li>
            <li><strong>Buscar referências:</strong> Nova busca no XVideos</li>
          </ul>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Excluir runs que ainda precisa usar</li>
              <li>Alterar manualmente dados se não souber o formato JSON</li>
            </ul>
          </div>
        `
      }
    ]
  },
  media: {
    title: "Ajuda - Arquivos",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>A página de <strong>Gerenciamento de Arquivos</strong> é onde você gerencia todos os vídeos e mídias do sistema.</p>
          <p>Permite visualizar, fazer upload, organizar e enviar arquivos para o Google Drive.</p>
        `
      },
      {
        title: "Categorias",
        content: `
          <p>Os arquivos são organizados em abas:</p>
          <ul>
            <li><strong>Todos:</strong> Todos os arquivos</li>
            <li><strong>Originais:</strong> Vídeos originais上传</li>
            <li><strong>Queimados:</strong> Vídeos com legendas gravadas</li>
            <li><strong>Teasers:</strong> Vídeos curtos promocionais</li>
          </ul>
        `
      },
      {
        title: "Google Drive",
        content: `
          <p>Configure o Google Drive para fazer backup ou upload de mídias.</p>
          <p><strong>Como configurar:</strong></p>
          <ol>
            <li>Crie uma pasta no Google Drive</li>
            <li>Copie o ID da pasta (está na URL depois de /folders/)</li>
            <li>Cole no campo "Pasta ID"</li>
            <li>Crie uma Service Account no Google Cloud Platform</li>
            <li>Cole o JSON da service account no campo correspondente</li>
            <li>Clique em "Salvar config"</li>
          </ol>
          <div class="warning">
            <p><strong>⚠️ Importante:</strong> A service account deve ter permissão de Editor na pasta do Drive.</p>
          </div>
        `
      },
      {
        title: "Player",
        content: `
          <p>Clique em qualquer arquivo para visualizá-lo no player integrado.</p>
          <p>O player mostra:</p>
          <ul>
            <li>Nome do arquivo</li>
            <li>Duração</li>
            <li>Resolução</li>
            <li>Tamanho</li>
          </ul>
        `
      },
      {
        title: "Buscar e filtrar",
        content: `
          <p>Use a caixa de busca para encontrar arquivos por:</p>
          <ul>
            <li>Nome do arquivo</li>
            <li>ID do run</li>
            <li>Data</li>
          </ul>
          <p>Use o campo "Limite" para controlar quantos arquivos são mostrados.</p>
        `
      },
      {
        title: "Ações em lote",
        content: `
          <p>Selecione múltiplos arquivos para ações em lote:</p>
          <ul>
            <li><strong>Selecionar filtrados:</strong> Seleciona todos da lista atual</li>
            <li><strong>Limpar seleção:</strong> Desmarca todos</li>
            <li><strong>Drive em lote:</strong> Envia selecionados para o Google Drive</li>
            <li><strong>Excluir em lote:</strong> Remove arquivos (cuidado!)</li>
          </ul>
          <div class="warning">
            <p><strong>⚠️ Cuidado:</strong> Exclusão é permanente! Sempre faça backup antes.</p>
          </div>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Excluir arquivos originais sem necessidade</li>
              <li>Enviar arquivos muito grandes para o Drive (limite de 15GB)</li>
              <li>Esquecer de configurar o Drive - perde o backup</li>
            </ul>
          </div>
        `
      }
    ]
  },
  referencia: {
    title: "Ajuda - Referência",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>A página de <strong>Referência XVideos</strong> permite buscar vídeos de referência no site XVideos.com.</p>
          <p>Use para encontrar vídeos similares, estudar tendências, ou obter ideias.</p>
        `
      },
      {
        title: "Tipos de busca",
        content: `
          <table class="help-table">
            <tr><th>Tipo</th><th>Descrição</th><th>Exemplo</th></tr>
            <tr><td>Busca Geral</td><td>Busca por palavra-chave</td><td>"brasileira"</td></tr>
            <tr><td>Atriz/Pornstar</td><td>Busca todos os vídeos de uma performer</td><td>"Mia Khalifa"</td></tr>
            <tr><td>Canal/Studio</td><td>Busca vídeos de um estúdio</td><td>"Bangbros"</td></tr>
          </table>
        `
      },
      {
        title: "Ordenação",
        content: `
          <p>Escolha como os resultados são ordenados:</p>
          <ul>
            <li><strong>Views:</strong> Mais visualizados primeiro</li>
            <li><strong>Relevância:</strong> Mais relacionados à busca</li>
            <li><strong>Data:</strong> Mais recentes primeiro</li>
          </ul>
        `
      },
      {
        title: "Como usar",
        content: `
          <p><strong>Passo a passo:</strong></p>
          <ol>
            <li>Selecione o <strong>tipo de busca</strong></li>
            <li>Digite o <strong>termo</strong> de busca</li>
            <li>Escolha a <strong>ordenação</strong></li>
            <li>Defina o <strong>limite</strong> de resultados</li>
            <li>Clique em <strong>"Buscar"</strong></li>
          </ol>
          <p>Os resultados aparecem com thumbnail, título, duração e visualizações.</p>
        `
      },
      {
        title: "Dicas de busca",
        content: `
          <div class="tip">
            <p><strong>💡 Dicas:</strong></p>
            <ul>
              <li>Use termos em inglês para melhores resultados (ex: "brazilian", "teen")</li>
              <li>Combine filtros (categoria + país)</li>
              <li>Busque por atrizes específicas para ver tendências</li>
              <li>Use "Views" para ver o que é mais popular</li>
            </ul>
          </div>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Buscas muito genéricas - muitos resultados irrelevantes</li>
              <li>Limite muito alto - demora muito para carregar</li>
              <li>Usar para baixar vídeos - violação de direitos</li>
            </ul>
          </div>
        `
      }
    ]
  },
  criacao: {
    title: "Ajuda - Criação",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>A página de <strong>Criação de Posts</strong> é onde você cria, edita e agenda posts para publicação.</p>
          <p>Você seleciona um run existente e gera o conteúdo final do post.</p>
        `
      },
      {
        title: "Selecionar um Run",
        content: `
          <p>Na lista à esquerda, escolha um dos runs existentes (resultados de análises anteriores).</p>
          <p>Cada item mostra o ID e a data da análise.</p>
        `
      },
      {
        title: "Editar Conteúdo",
        content: `
          <p>Após selecionar um run, você pode editar:</p>
          <ul>
            <li><strong>Título:</strong> Título do post</li>
            <li><strong>Descrição:</strong> Texto de descrição</li>
            <li><strong>Tags:</strong> Palavras-chave (separadas por vírgula)</li>
            <li><strong>Hashtags:</strong> Hashtags para redes sociais</li>
            <li><strong>Legenda:</strong> Texto curto para resumo</li>
            <li><strong>Slug:</strong> URL amigável</li>
          </ul>
        `
      },
      {
        title: "Gerar Vídeo Legendado",
        content: `
          <p>Para adicionar legendas ao vídeo:</p>
          <ol>
            <li>Selecione o vídeo original na seção "Upload/Legenda"</li>
            <li>Edite o conteúdo SRT se necessário</li>
            <li>Configure as opções (tamanho, cor, posição)</li>
            <li>Clique em <strong>"Gerar Queimado"</strong></li>
            <li>Aguarde o processamento (pode levar vários minutos)</li>
            <li>Faça o download quando pronto</li>
          </ol>
          <div class="warning">
            <p><strong>⚠️ Tempo:</strong> O processo de queima de legendas pode levar de 5 a 30 minutos dependendo do vídeo.</p>
          </div>
        `
      },
      {
        title: "Gerar Teaser",
        content: `
          <p>Teasers são vídeos curtos (30-60 segundos) para divulgação.</p>
          <p><strong>Como criar:</strong></p>
          <ol>
            <li>Selecione o vídeo origem</li>
            <li>Configure o número de cenas (3-20)</li>
            <li>Defina a duração de cada cena</li>
            <li>Clique em <strong>"Gerar Teaser"</strong></li>
            <li>Aguarde a geração</li>
            <li>Baixe ou inclua no vídeo principal</li>
          </ol>
        `
      },
      {
        title: "Agendar Post",
        content: `
          <p>Para agendar um post:</p>
          <ol>
            <li>Preencha todos os campos do post</li>
            <li>Clique em <strong>"Agendar Post"</strong></li>
            <li>Selecione a data e hora</li>
            <li>Confirme o agendamento</li>
          </ol>
          <p>Posts agendados aparecem na lista abaixo e podem ser:</p>
          <ul>
            <li><strong>Pending:</strong> Aguardando publicação</li>
            <li><strong>Published:</strong> Já publicado</li>
            <li><strong>Failed:</strong> Falha na publicação</li>
          </ul>
        `
      },
      {
        title: "Opções de Legenda",
        content: `
          <p><strong>Tamanho da fonte:</strong> 10-72px (padrão: 24px)</p>
          <p><strong>Cores disponíveis:</strong></p>
          <ul>
            <li>Branco (padrão)</li>
            <li>Amarelo</li>
            <li>Ciano</li>
            <li>Laranja</li>
            <li>Preto</li>
          </ul>
          <p><strong>Posição:</strong> Você pode posicionar o logo em diferentes posições do vídeo usando os sliders.</p>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Cancelar proceso de queima - pode corromper o arquivo</li>
              <li>Esquecer de revisar o conteúdo antes de agendar</li>
              <li>Agendar para horário que não tem público</li>
              <li>Usar legenda muito grande - dificulta leitura</li>
            </ul>
          </div>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Sempre visualize o resultado antes de agendar!</p>
          </div>
        `
      }
    ]
  },
  creators: {
    title: "Ajuda - Criadores",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>A página de <strong>Criadores</strong> gerencia o cadastro de todos os criadores de conteúdo da agência.</p>
          <p>Cada criador possui perfil, contas em plataformas e configurações individuais de distribuição e receita.</p>
        `
      },
      {
        title: "Cadastrar um Criador",
        content: `
          <p><strong>Passo a passo:</strong></p>
          <ol>
            <li>Clique em <strong>"+ Novo Criador"</strong></li>
            <li>Preencha nome artístico, email e senha do portal</li>
            <li>Defina as categorias e tags preferidas</li>
            <li>Configure o percentual de comissão da agência</li>
            <li>Clique em <strong>"Salvar"</strong></li>
          </ol>
          <div class="tip">
            <p><strong>💡 Dica:</strong> O nome real é criptografado no banco — nunca fica em texto plano.</p>
          </div>
        `
      },
      {
        title: "Contas de Plataforma",
        content: `
          <p>Cada criador pode ter contas em múltiplas plataformas (XVideos, Pornhub, XNXX, xHamster).</p>
          <p>Para adicionar uma conta:</p>
          <ol>
            <li>Abra o criador e vá em <strong>"Contas"</strong></li>
            <li>Clique em <strong>"+ Adicionar Conta"</strong></li>
            <li>Selecione a plataforma e informe o login</li>
            <li>Cole os cookies de sessão (obtidos após login manual)</li>
          </ol>
          <div class="warning">
            <p><strong>⚠️ Segurança:</strong> Os cookies são criptografados com Fernet antes de serem salvos.</p>
          </div>
        `
      },
      {
        title: "Status do Criador",
        content: `
          <table class="help-table">
            <tr><th>Status</th><th>Significado</th></tr>
            <tr><td>active</td><td>Criador ativo, recebe briefings e publicações automáticas</td></tr>
            <tr><td>inactive</td><td>Pausado — sem automações</td></tr>
            <tr><td>suspended</td><td>Suspenso — sem acesso ao portal</td></tr>
          </table>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Cadastrar cookies expirados — a publicação vai falhar</li>
              <li>Colocar o mesmo email em dois criadores</li>
              <li>Deletar um criador com publicações ativas</li>
            </ul>
          </div>
        `
      }
    ]
  },
  publisher: {
    title: "Ajuda - Publicador",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>O <strong>AutoPublisher</strong> envia vídeos automaticamente para XVideos, Pornhub, XNXX e xHamster usando um navegador automatizado (Playwright/Chromium).</p>
        `
      },
      {
        title: "Como publicar um vídeo",
        content: `
          <p><strong>Passo a passo:</strong></p>
          <ol>
            <li>Selecione o <strong>criador</strong></li>
            <li>Informe a <strong>chave S3</strong> do vídeo (object key no MinIO)</li>
            <li>Preencha título, descrição e tags</li>
            <li>Selecione as <strong>plataformas</strong> de destino</li>
            <li>Clique em <strong>"Publicar Agora"</strong></li>
          </ol>
          <p>O job é criado e roda em segundo plano. Atualize a lista de jobs para ver o progresso.</p>
        `
      },
      {
        title: "Status dos Jobs",
        content: `
          <table class="help-table">
            <tr><th>Status</th><th>Significado</th></tr>
            <tr><td>pending</td><td>Aguardando início</td></tr>
            <tr><td>running</td><td>Publicando agora</td></tr>
            <tr><td>done</td><td>Concluído com sucesso</td></tr>
            <tr><td>partial</td><td>Publicou em algumas plataformas, falhou em outras</td></tr>
            <tr><td>failed</td><td>Falhou em todas as plataformas</td></tr>
          </table>
        `
      },
      {
        title: "Selector Maps",
        content: `
          <p>Os seletores CSS que o Playwright usa para cada plataforma ficam em arquivos JSON editáveis.</p>
          <p>Se uma plataforma atualizar o layout e a publicação falhar, use o painel <strong>"Editar Seletores"</strong> para corrigir sem precisar alterar código.</p>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Em caso de falha, um screenshot de erro é salvo em <span class="help-code">/tmp/{plataforma}_upload_error_*.png</span>.</p>
          </div>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Publicar o mesmo vídeo duas vezes no mesmo canal</li>
              <li>Usar cookies expirados — configure antes na página Criadores</li>
              <li>Rodar muitos jobs simultâneos — pode ser detectado como bot</li>
            </ul>
          </div>
        `
      }
    ]
  },
  trends: {
    title: "Ajuda - Tendências",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>O <strong>Trend Radar</strong> coleta dados de vídeos em alta nas plataformas e gera briefings personalizados de produção para cada criador usando IA.</p>
        `
      },
      {
        title: "Coletar Tendências",
        content: `
          <p>Clique em <strong>"Coletar Agora"</strong> para disparar a coleta manual de tendências.</p>
          <p>A coleta automática roda <strong>todo dia às 06:00</strong> via scheduler.</p>
          <p>Os dados coletados ficam na lista abaixo — mostrando título, views e plataforma.</p>
        `
      },
      {
        title: "Gerar Briefing",
        content: `
          <p>O briefing é um relatório de produção gerado por IA (Grok/xAI) com sugestões de vídeos para o criador.</p>
          <p><strong>Para gerar:</strong></p>
          <ol>
            <li>Selecione um criador no dropdown</li>
            <li>Clique em <strong>"Gerar Briefing"</strong></li>
            <li>Aguarde a IA processar (20-60 segundos)</li>
            <li>O resultado aparece com sugestões de títulos, tags e por que está em alta</li>
          </ol>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Briefings automáticos são gerados toda <strong>segunda às 08:00</strong> para todos os criadores ativos.</p>
          </div>
        `
      },
      {
        title: "Conteúdo do Briefing",
        content: `
          <p>Cada briefing contém:</p>
          <ul>
            <li><strong>Resumo do mercado:</strong> O que está acontecendo esta semana</li>
            <li><strong>Sugestões de vídeos:</strong> Título, conceito, tags, potencial estimado</li>
            <li><strong>O que evitar:</strong> Categorias saturadas ou em queda</li>
          </ul>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Gerar briefing sem ter tokens de IA configurados — vai falhar</li>
              <li>Ignorar a seção "O que evitar" — é baseada em dados reais</li>
            </ul>
          </div>
        `
      }
    ]
  },
  calendar: {
    title: "Ajuda - Agenda",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>O <strong>Editorial Calendar</strong> organiza e agenda as publicações dos criadores ao longo do tempo.</p>
          <p>Permite planejar quando cada vídeo será publicado e em quais plataformas.</p>
        `
      },
      {
        title: "Criar Entrada na Agenda",
        content: `
          <p><strong>Passo a passo:</strong></p>
          <ol>
            <li>Selecione o criador</li>
            <li>Informe a chave S3 do vídeo</li>
            <li>Defina a data/hora de publicação</li>
            <li>Selecione as plataformas</li>
            <li>Clique em <strong>"Agendar"</strong></li>
          </ol>
        `
      },
      {
        title: "Auto-Agendar com IA",
        content: `
          <p>A função <strong>"Auto-Agendar"</strong> usa IA para distribuir automaticamente uma lista de vídeos nos próximos dias, respeitando horários de pico.</p>
          <ul>
            <li>Horário padrão: <strong>22:00 BRT (01:00 UTC)</strong> — maior audiência</li>
            <li>Intervalo mínimo entre publicações: 8 horas</li>
          </ul>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Se a IA não estiver configurada, o sistema distribui igualmente nos horários de pico automaticamente.</p>
          </div>
        `
      },
      {
        title: "Status das Entradas",
        content: `
          <table class="help-table">
            <tr><th>Status</th><th>Significado</th></tr>
            <tr><td>scheduled</td><td>Aguardando a data/hora</td></tr>
            <tr><td>published</td><td>Publicado com sucesso</td></tr>
            <tr><td>failed</td><td>Falha na publicação</td></tr>
            <tr><td>cancelled</td><td>Cancelado manualmente</td></tr>
          </table>
          <p>O scheduler verifica publicações agendadas <strong>a cada 5 minutos</strong>.</p>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Agendar muitos vídeos no mesmo horário no mesmo canal</li>
              <li>Cancelar uma entrada que já está publicando</li>
            </ul>
          </div>
        `
      }
    ]
  },
  financial: {
    title: "Ajuda - Financeiro",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>O módulo <strong>Financeiro</strong> registra receitas, calcula comissões da agência e gera relatórios mensais para cada criador.</p>
        `
      },
      {
        title: "Registrar Receita",
        content: `
          <p><strong>Campos obrigatórios:</strong></p>
          <ul>
            <li><strong>Criador:</strong> A quem a receita pertence</li>
            <li><strong>Plataforma:</strong> XVideos, Pornhub, etc.</li>
            <li><strong>Período:</strong> No formato YYYY-MM (ex: 2026-04)</li>
            <li><strong>Receita Bruta:</strong> Valor total recebido da plataforma</li>
            <li><strong>Taxa da plataforma (%):</strong> O que a plataforma retém (ex: 35%)</li>
          </ul>
          <p>O sistema calcula automaticamente: líquido, comissão da agência e repasse ao criador.</p>
        `
      },
      {
        title: "Relatório Mensal",
        content: `
          <p>O relatório mensal consolida todas as receitas de um criador em um período.</p>
          <p>Mostra: total bruto, total líquido, comissão da agência, repasse ao criador.</p>
          <div class="tip">
            <p><strong>💡 Dica:</strong> Relatórios são enviados por email automaticamente todo <strong>dia 1 de cada mês às 10:00</strong>.</p>
          </div>
        `
      },
      {
        title: "Visão Geral da Agência",
        content: `
          <p>A seção <strong>"Agência"</strong> mostra a receita consolidada de todos os criadores em um período.</p>
          <p>Útil para entender o faturamento total da agência e a comissão gerada.</p>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Registrar receita com período errado — dificulta conciliação</li>
              <li>Informar taxa da plataforma errada — afeta o cálculo do repasse</li>
            </ul>
          </div>
        `
      }
    ]
  },
  dmca: {
    title: "Ajuda - DMCA",
    sections: [
      {
        title: "O que é esta página?",
        content: `
          <p>O módulo <strong>DMCA</strong> protege o conteúdo dos criadores contra pirataria, detectando cópias não autorizadas e enviando notificações de takedown automaticamente.</p>
        `
      },
      {
        title: "Escanear por Infrações",
        content: `
          <p>Clique em <strong>"Escanear Agora"</strong> para iniciar uma busca por cópias dos vídeos de um criador.</p>
          <p>O sistema usa hash de imagem (pHash) para encontrar conteúdo visualmente idêntico ou muito similar.</p>
          <p>Escaneamentos automáticos rodam <strong>a cada 2 dias às 04:00</strong>.</p>
        `
      },
      {
        title: "Notificação de Takedown",
        content: `
          <p>Ao identificar uma infração, você pode enviar uma notificação DMCA:</p>
          <ol>
            <li>Localize a infração na lista</li>
            <li>Clique em <strong>"Enviar Takedown"</strong></li>
            <li>Confirme o envio</li>
          </ol>
          <p>O sistema envia um email formal de notificação DMCA para o contato de abuse do site infrator.</p>
          <div class="warning">
            <p><strong>⚠️ Importante:</strong> Configure o SMTP em variáveis de ambiente antes de usar esta função.</p>
          </div>
        `
      },
      {
        title: "Status das Infrações",
        content: `
          <table class="help-table">
            <tr><th>Status</th><th>Significado</th></tr>
            <tr><td>detected</td><td>Infração encontrada, aguardando ação</td></tr>
            <tr><td>notified</td><td>Notificação de takedown enviada</td></tr>
            <tr><td>resolved</td><td>Conteúdo removido</td></tr>
            <tr><td>ignored</td><td>Marcado manualmente como irrelevante</td></tr>
          </table>
        `
      },
      {
        title: "Estatísticas",
        content: `
          <p>O painel de estatísticas mostra:</p>
          <ul>
            <li>Total de infrações detectadas</li>
            <li>Quantas notificações foram enviadas</li>
            <li>Quantas foram resolvidas</li>
            <li>Taxa de resolução</li>
          </ul>
        `
      },
      {
        title: "O que evitar",
        content: `
          <div class="warning">
            <p><strong>⚠️ Não faça:</strong></p>
            <ul>
              <li>Enviar takedown sem verificar se realmente é uma cópia não autorizada</li>
              <li>Ignorar notificações — conteúdo pirata prejudica o alcance orgânico</li>
            </ul>
          </div>
        `
      }
    ]
  }
};

function toggleHelpPanel() {
  const panel = document.getElementById('helpPanel');
  if (panel) {
    panel.classList.toggle('active');
  }
}

function updateHelpPanel() {
  // Determina qual página está ativa
  let currentPage = 'analyze';
  const pages = ['settings', 'analyze', 'compare', 'runs', 'media', 'referencia', 'criacao', 'telegram', 'autoeditor', 'creators', 'publisher', 'trends', 'calendar', 'financial', 'dmca'];
  
  for (const page of pages) {
    const el = document.getElementById('page-' + page);
    if (el && el.classList.contains('active')) {
      currentPage = page;
      break;
    }
  }
  
  // Atualiza título e conteúdo
  const titleEl = document.getElementById('helpPanelTitle');
  const contentEl = document.getElementById('helpPanelContent');
  
  if (titleEl && contentEl) {
    const content = helpContent[currentPage] || helpContent.analyze;
    titleEl.textContent = content.title;
    
    let html = '';
    for (const section of content.sections) {
      html += `
        <div class="help-section">
          <h4>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <polyline points="10 9 9 9 8 9"/>
            </svg>
            ${section.title}
          </h4>
          ${section.content}
        </div>
      `;
    }
    contentEl.innerHTML = html;
  }
}

// Fecha painel ao clicar fora
document.addEventListener('click', function(e) {
  const panel = document.getElementById('helpPanel');
  const btn = document.querySelector('.help-btn');
  if (panel && panel.classList.contains('active')) {
    if (!panel.contains(e.target) && !btn.contains(e.target)) {
      panel.classList.remove('active');
    }
  }
});

// Fecha painel com ESC
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    const panel = document.getElementById('helpPanel');
    if (panel && panel.classList.contains('active')) {
      panel.classList.remove('active');
    }
  }
});

// Atualiza painel quando muda de página
const originalRouteTo = routeTo;
routeTo = function(name) {
  originalRouteTo(name);
  setTimeout(updateHelpPanel, 100);
};

// Inicializa
setTimeout(updateHelpPanel, 500);

main();

// ═══════════════════════════════════════════════════════════════════════════════
// MÓDULO TELEGRAM — Publicação e agendamento direto para grupos
// ═══════════════════════════════════════════════════════════════════════════════

const tgState = {
  groups: [],
  botConfigured: false,
  teasers: [],
  runs: [],
  composerRunId: '',        // run_id selecionado para gerar legenda com IA
  composerTeaser: null,     // object_key do teaser
  composerCaption: '',
  composerChatId: '',
  composerScheduleAt: '',   // ISO string ou vazio para enviar agora
  composerThumbKey: '',
  queue: [],
};

async function renderTelegramPage() {
  const wrap = qs('telegramPageContent');
  if (!wrap) return;
  wrap.innerHTML = '<div class="criacao-empty">Carregando...</div>';
  try {
    await Promise.all([_tgLoadSettings(), _tgLoadTeasers(), _tgLoadQueue(), _tgLoadRuns()]);
  } catch (e) { /* ignora erro de carregamento parcial */ }
  _tgRender();
}

async function _tgLoadSettings() {
  try {
    const r = await apiFetch('/settings/telegram');
    tgState.webhookConfigured = r.webhook_configured;
    tgState.webhookUrl = r.webhook_url || '';
    tgState.groups = r.groups || [];
  } catch (e) { /* */ }
}

async function _tgLoadTeasers() {
  try {
    const r = await apiFetch('/uploads/list?prefix=teasers&max_keys=200');
    tgState.teasers = (r.items || r.objects || r.files || []).filter(f =>
      String(f.object_key || f.key || '').match(/\.(mp4|mov|webm)$/i)
    );
  } catch (e) { tgState.teasers = []; }
}

async function _tgLoadQueue() {
  try {
    const r = await apiFetch('/api/scheduled-posts');
    tgState.queue = (r.posts || []).sort((a, b) => (a.schedule_at || a.created_at) > (b.schedule_at || b.created_at) ? 1 : -1);
  } catch (e) { tgState.queue = []; }
}

async function _tgLoadRuns() {
  try {
    const r = await apiFetch('/runs?limit=200');
    tgState.runs = (r.runs || []).map(run => {
      const src = (run.source || '').split('/').pop().split('?')[0] || run.id.slice(0, 8);
      const dt = run.created_at ? run.created_at.slice(0, 16).replace('T', ' ') : '';
      return { id: run.id, label: `${src}${dt ? '  ·  ' + dt : ''}` };
    });
  } catch (e) { tgState.runs = []; }
}

function _tgRender() {
  const wrap = qs('telegramPageContent');
  if (!wrap) return;

  const groups = tgState.groups;
  const teasers = tgState.teasers;

  const teaserOptions = teasers.map(t => {
    const key = t.key || t.object_key || '';
    const name = key.split('/').pop();
    return `<option value="${esc(key)}" ${tgState.composerTeaser === key ? 'selected' : ''}>${esc(name)}</option>`;
  }).join('');

  const groupOptions = groups.map(g =>
    `<option value="${esc(g.id)}" ${tgState.composerChatId === g.id ? 'selected' : ''}>${esc(g.name || g.id)}</option>`
  ).join('');

  const queueHtml = tgState.queue.length ? tgState.queue.map(p => {
    const pd = p.post_data || {};
    const name = (pd.caption || pd.title || '').slice(0, 50) || p.run_id?.slice(0, 16) || '—';
    const dt = p.schedule_at ? fmtDate(p.schedule_at) : (p.sent_at ? '✓ ' + fmtDate(p.sent_at) : '(imediato)');
    const statusColor = {sent:'var(--good)', error:'var(--bad)', pending:'var(--accent)', sending:'var(--muted)', cancelled:'var(--muted)'}[p.status] || 'var(--muted)';
    const grpId = pd.chat_id || pd.telegram_chat_id || '';
    const grpName = groups.find(g => g.id === grpId)?.name || grpId || '—';
    const teaserName = (pd.teaser_object_key || '').split('/').pop() || '—';
    return `
      <div class="sched-item" style="align-items:flex-start;gap:10px;">
        <div style="flex:1;min-width:0;">
          <div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(name)}</div>
          <div class="hint" style="margin-top:2px;">📁 ${esc(teaserName)} · 👥 ${esc(grpName)} · 🕐 ${esc(dt)}</div>
          ${p.error_log ? `<div class="hint" style="color:var(--bad);margin-top:2px;">⚠ ${esc(p.error_log)}</div>` : ''}
        </div>
        <span class="badge" style="background:${statusColor};color:#fff;font-size:10px;padding:2px 6px;border-radius:10px;white-space:nowrap;">${esc(p.status)}</span>
        ${p.status === 'pending' ? `<button class="btn" style="font-size:11px;padding:2px 8px;" onclick="tgDeletePost('${p.id}')">✕</button>` : ''}
      </div>
    `;
  }).join('') : '<div class="criacao-empty">Nenhum post na fila ainda.</div>';

  wrap.innerHTML = `
    <h1 style="margin:0 0 20px;">Telegram — Publicação Automática</h1>

    <!-- Configurações n8n -->
    <div class="card detail-section" style="margin-bottom:20px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h2 style="margin:0;">⚙ Configuração n8n + Telegram</h2>
        <span class="badge" style="background:${tgState.webhookConfigured ? 'var(--good)' : 'var(--bad)'};color:#fff;font-size:11px;padding:3px 8px;border-radius:10px;">
          ${tgState.webhookConfigured ? '✓ Webhook configurado' : '✗ Webhook não configurado'}
        </span>
      </div>
      <div class="hint" style="margin-bottom:10px;">Cole a URL do Webhook n8n do seu workflow Telegram. O app detecta automaticamente a URL pública — não precisa configurar nada a mais.</div>
      <div class="row wrap" style="gap:10px;align-items:flex-end;">
        <div class="col grow">
          <label>URL do Webhook n8n (Telegram)</label>
          <input id="tgN8nWebhook" type="url" placeholder="https://webhook.n8nmikael.com.br/webhook/..." style="width:100%;" value="${esc(tgState.webhookUrl || '')}">
        </div>
        <button class="btn primary" onclick="tgSaveWebhook()">Salvar</button>
        <button class="btn" onclick="tgTestWebhook()">Testar</button>
      </div>
      <div id="tgWebhookTestResult" style="margin-top:8px;"></div>
      <div class="hint" style="margin-top:8px;">
        💡 <strong>Como configurar no n8n:</strong> Webhook trigger (POST) → HTTP Request node (para buscar o vídeo) ou Telegram node com <code>video_url</code> do body → Send Video para <code>{{$json.chat_id}}</code> com caption <code>{{$json.caption}}</code>
      </div>

      <!-- Grupos -->
      <div style="margin-top:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <strong>Grupos / Canais cadastrados</strong>
          <button class="btn" onclick="tgShowAddGroup()" style="font-size:11px;padding:4px 10px;">+ Adicionar grupo</button>
        </div>
        <div id="tgGroupList">
          ${groups.length ? groups.map(g => `
            <div class="sched-item" style="padding:6px 10px;">
              <div>
                <span style="font-size:13px;font-weight:500;">${esc(g.name || g.id)}</span>
                <span class="hint" style="margin-left:8px;">${esc(g.id)}</span>
              </div>
              <button class="btn" style="font-size:11px;padding:2px 8px;color:var(--bad);border-color:var(--bad);" onclick="tgRemoveGroup('${esc(g.id)}')">Remover</button>
            </div>
          `).join('') : '<div class="hint">Nenhum grupo cadastrado. Adicione o bot ao grupo, depois adicione o ID do grupo aqui.</div>'}
        </div>
        <div id="tgAddGroupForm" style="display:none;margin-top:10px;padding:10px;border:1px solid var(--line);border-radius:6px;">
          <div class="row wrap" style="gap:8px;align-items:flex-end;">
            <div class="col grow">
              <label>ID do grupo/canal (ex: -1001234567890)</label>
              <input id="tgNewGroupId" type="text" placeholder="-1001234567890">
            </div>
            <div class="col grow">
              <label>Nome (opcional)</label>
              <input id="tgNewGroupName" type="text" placeholder="Meu Canal">
            </div>
            <button class="btn primary" onclick="tgAddGroup()">Adicionar</button>
            <button class="btn" onclick="tgHideAddGroup()">✕</button>
          </div>
          <div class="hint" style="margin-top:6px;">💡 Para descobrir o ID: adicione o bot ao grupo, envie uma mensagem e veja no log do backend, ou use @userinfobot no Telegram.</div>
        </div>
      </div>
    </div>

    <!-- Compositor de Post -->
    <div class="card detail-section" style="margin-bottom:20px;">
      <h2 style="margin-bottom:14px;">📤 Novo Post</h2>
      <div class="row wrap" style="gap:12px;margin-bottom:12px;">
        <div class="col grow">
          <label>Teaser / Vídeo</label>
          <select id="tgComposerTeaser" onchange="tgState.composerTeaser=this.value" style="width:100%;">
            <option value="">— Selecione um teaser —</option>
            ${teaserOptions}
          </select>
        </div>
        <div class="col" style="min-width:200px;">
          <label>Grupo de destino</label>
          <select id="tgComposerGroup" onchange="tgState.composerChatId=this.value" style="width:100%;">
            <option value="">— Selecione um grupo —</option>
            ${groupOptions}
          </select>
        </div>
      </div>

      <div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <label>Legenda / Caption (máx 1024 chars)</label>
          <div style="display:flex;gap:6px;align-items:center;">
            <select id="tgComposerRun" onchange="tgState.composerRunId=this.value" style="font-size:11px;max-width:220px;" title="Selecione o run para gerar legenda com IA">
              <option value="">— Run para IA —</option>
              ${tgState.runs ? tgState.runs.map(r => `<option value="${esc(r.id)}" ${tgState.composerRunId===r.id?'selected':''}>${esc(r.label)}</option>`).join('') : ''}
            </select>
            <button class="btn" style="font-size:11px;padding:2px 8px;" onclick="tgFillCaptionFromRun()">✨ IA</button>
          </div>
        </div>
        <textarea id="tgComposerCaption" rows="4" placeholder="Legenda do post..." style="width:100%;resize:vertical;" oninput="tgState.composerCaption=this.value">${esc(tgState.composerCaption)}</textarea>
        <div class="hint">Suporta HTML: &lt;b&gt;negrito&lt;/b&gt;, &lt;i&gt;itálico&lt;/i&gt;, &lt;a href=&quot;...&quot;&gt;link&lt;/a&gt;</div>
      </div>

      <div class="row wrap" style="gap:12px;margin-bottom:12px;">
        <div class="col grow">
          <label>Thumbnail (opcional)</label>
          <input id="tgComposerThumb" type="text" placeholder="local:teasers/..." style="width:100%;" oninput="tgState.composerThumbKey=this.value">
        </div>
        <div class="col" style="min-width:240px;">
          <label>Quando publicar</label>
          <div class="row" style="gap:6px;align-items:center;">
            <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-weight:normal;">
              <input type="radio" name="tgWhen" value="now" checked onchange="tgState.composerScheduleAt=''"> Agora
            </label>
            <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-weight:normal;">
              <input type="radio" name="tgWhen" value="later" onchange=""> Agendar
            </label>
            <input id="tgScheduleAt" type="datetime-local" style="flex:1;" onchange="tgState.composerScheduleAt=this.value">
          </div>
        </div>
      </div>

      <div class="row" style="gap:10px;">
        <button class="btn create" style="padding:10px 20px;font-size:13.5px;" onclick="tgSubmitPost()">✈ Publicar / Agendar</button>
        <button class="btn" onclick="tgClearComposer()">Limpar</button>
      </div>
      <div id="tgComposerStatus" style="margin-top:8px;"></div>
    </div>

    <!-- Fila de posts -->
    <div class="card detail-section">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h2 style="margin:0;">📋 Fila de Publicações</h2>
        <button class="btn" onclick="tgRefreshQueue()">↺ Atualizar</button>
      </div>
      <div id="tgQueue">${queueHtml}</div>
    </div>
  `;
}

async function tgSaveWebhook() {
  const url = (qs('tgN8nWebhook')?.value || '').trim();
  if (!url) return toast('Cole a URL do webhook n8n', 'bad');
  try {
    await apiFetch('/settings/telegram', { method: 'POST', body: JSON.stringify({ n8n_webhook_url: url }) });
    tgState.webhookConfigured = true;
    tgState.webhookUrl = url;
    toast('Webhook salvo!', 'good');
    _tgRender();
  } catch (e) {
    toast('Erro ao salvar: ' + e.message, 'bad');
  }
}

async function tgSaveAppUrl() {
  const url = (qs('tgAppPublicUrl')?.value || '').trim();
  if (!url) return toast('Digite a URL pública da app', 'bad');
  try {
    await apiFetch('/settings/telegram', { method: 'POST', body: JSON.stringify({ app_public_url: url }) });
    tgState.appPublicUrl = url;
    toast('URL pública salva!', 'good');
  } catch (e) {
    toast('Erro ao salvar: ' + e.message, 'bad');
  }
}

async function tgTestWebhook() {
  const resultEl = qs('tgWebhookTestResult');
  if (resultEl) resultEl.innerHTML = '<span class="hint">Testando webhook...</span>';
  try {
    const r = await apiFetch('/api/telegram/test-webhook', { method: 'POST', body: '{}' });
    if (r.ok) {
      if (resultEl) resultEl.innerHTML = '<span class="hint" style="color:var(--good);">✓ Webhook respondeu OK! n8n conectado.</span>';
    } else {
      if (resultEl) resultEl.innerHTML = `<span class="hint" style="color:var(--bad);">✗ ${esc(r.description || r.error || 'Erro')}</span>`;
    }
  } catch (e) {
    if (resultEl) resultEl.innerHTML = `<span class="hint" style="color:var(--bad);">✗ ${esc(e.message)}</span>`;
  }
}

function tgShowAddGroup() {
  const f = qs('tgAddGroupForm');
  if (f) f.style.display = '';
}

function tgHideAddGroup() {
  const f = qs('tgAddGroupForm');
  if (f) f.style.display = 'none';
}

async function tgAddGroup() {
  const groupId = (qs('tgNewGroupId')?.value || '').trim();
  const groupName = (qs('tgNewGroupName')?.value || '').trim();
  if (!groupId) return toast('Digite o ID do grupo', 'bad');
  try {
    const r = await apiFetch('/settings/telegram/groups', {
      method: 'POST',
      body: JSON.stringify({ group_id: groupId, name: groupName }),
    });
    tgState.groups = r.groups || [];
    toast('Grupo adicionado!', 'good');
    _tgRender();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function tgRemoveGroup(groupId) {
  try {
    const r = await apiFetch(`/settings/telegram/groups/${encodeURIComponent(groupId)}`, { method: 'DELETE' });
    tgState.groups = r.groups || [];
    if (tgState.composerChatId === groupId) tgState.composerChatId = '';
    toast('Grupo removido', 'good');
    _tgRender();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function tgFillCaptionFromRun() {
  // Usa o run selecionado no dropdown; se não houver, mostra erro orientado
  const runId = (qs('tgComposerRun')?.value || tgState.composerRunId || '').trim();
  if (!runId) {
    toast('Selecione um Run no dropdown "Run para IA" antes de gerar a legenda.', 'bad');
    return;
  }

  const statusEl = qs('tgComposerStatus');
  if (statusEl) statusEl.innerHTML = '<span class="hint">✨ Gerando legenda com IA...</span>';

  try {
    const r = await apiFetch('/api/create-post', { method: 'POST', body: JSON.stringify({ video_id: runId }) });
    if (r.error) {
      const msg = r.detail || r.error;
      if (statusEl) statusEl.innerHTML = `<span class="hint" style="color:var(--bad);">✗ ${esc(msg)}</span>`;
      toast('Erro IA: ' + msg, 'bad');
      return;
    }
    const caption = r.caption || r.description || r.title || r.ready_to_post || '';
    if (caption) {
      tgState.composerCaption = caption;
      tgState.composerRunId = runId;
      const el = qs('tgComposerCaption');
      if (el) el.value = caption;
      if (statusEl) statusEl.innerHTML = '<span class="hint" style="color:var(--good);">✓ Legenda gerada com sucesso!</span>';
    } else {
      if (statusEl) statusEl.innerHTML = '<span class="hint" style="color:var(--bad);">IA não retornou texto de legenda</span>';
    }
  } catch (e) {
    if (statusEl) statusEl.innerHTML = `<span class="hint" style="color:var(--bad);">Erro: ${esc(e.message)}</span>`;
  }
}

async function tgSubmitPost() {
  const teaser = (qs('tgComposerTeaser')?.value || tgState.composerTeaser || '').trim();
  const chatId = (qs('tgComposerGroup')?.value || tgState.composerChatId || '').trim();
  const caption = (qs('tgComposerCaption')?.value || tgState.composerCaption || '').trim();
  const thumbKey = (qs('tgComposerThumb')?.value || tgState.composerThumbKey || '').trim();

  const whenNow = document.querySelector('input[name="tgWhen"][value="now"]')?.checked ?? true;
  const schedAt = whenNow ? '' : (qs('tgScheduleAt')?.value || '').trim();

  if (!teaser) return toast('Selecione o teaser', 'bad');
  if (!chatId) return toast('Selecione o grupo de destino', 'bad');

  const statusEl = qs('tgComposerStatus');

  if (whenNow || !schedAt) {
    // Enviar agora
    if (statusEl) statusEl.innerHTML = '<span class="hint">⏳ Enviando para o Telegram...</span>';
    try {
      const body = { teaser_object_key: teaser, chat_id: chatId, caption };
      if (thumbKey) body.thumb_object_key = thumbKey;
      const r = await apiFetch('/api/telegram/send-now', { method: 'POST', body: JSON.stringify(body) });
      if (r.ok) {
        if (statusEl) statusEl.innerHTML = '<span class="hint" style="color:var(--good);">✓ Enviado com sucesso!</span>';
        toast('Enviado ao Telegram!', 'good');
        tgClearComposer();
        await _tgLoadQueue();
        const qEl = qs('tgQueue');
        if (qEl) qEl.innerHTML = tgState.queue.length ? tgState.queue.map(_tgQueueItemHtml).join('') : '<div class="criacao-empty">Nenhum post na fila ainda.</div>';
      } else {
        if (statusEl) statusEl.innerHTML = `<span class="hint" style="color:var(--bad);">✗ ${esc(r.error || r.detail || 'Erro')}</span>`;
        toast('Erro ao enviar: ' + (r.error || r.detail || 'Telegram error'), 'bad');
      }
    } catch (e) {
      if (statusEl) statusEl.innerHTML = `<span class="hint" style="color:var(--bad);">✗ ${esc(e.message)}</span>`;
      toast('Erro: ' + e.message, 'bad');
    }
  } else {
    // Agendar
    if (statusEl) statusEl.innerHTML = '<span class="hint">⏳ Agendando...</span>';
    try {
      const postData = { teaser_object_key: teaser, chat_id: chatId, caption };
      if (thumbKey) postData.thumb_object_key = thumbKey;
      // Converter datetime-local para ISO UTC
      const schedIso = new Date(schedAt).toISOString();
      const r = await apiFetch('/api/scheduled-posts', {
        method: 'POST',
        body: JSON.stringify({ run_id: 'telegram', post_data: postData, schedule_at: schedIso }),
      });
      if (r.ok) {
        if (statusEl) statusEl.innerHTML = '<span class="hint" style="color:var(--good);">✓ Agendado!</span>';
        toast('Post agendado para ' + new Date(schedIso).toLocaleString('pt-BR'), 'good');
        tgClearComposer();
        await tgRefreshQueue();
      } else {
        if (statusEl) statusEl.innerHTML = `<span class="hint" style="color:var(--bad);">✗ ${esc(r.error || 'Erro')}</span>`;
      }
    } catch (e) {
      if (statusEl) statusEl.innerHTML = `<span class="hint" style="color:var(--bad);">✗ ${esc(e.message)}</span>`;
      toast('Erro: ' + e.message, 'bad');
    }
  }
}

function tgClearComposer() {
  tgState.composerTeaser = '';
  tgState.composerChatId = '';
  tgState.composerCaption = '';
  tgState.composerThumbKey = '';
  tgState.composerScheduleAt = '';
  const els = ['tgComposerTeaser', 'tgComposerGroup', 'tgComposerCaption', 'tgComposerThumb', 'tgScheduleAt'];
  els.forEach(id => { const el = qs(id); if (el) el.value = ''; });
  const r = document.querySelector('input[name="tgWhen"][value="now"]');
  if (r) r.checked = true;
}

function _tgQueueItemHtml(p) {
  const pd = p.post_data || {};
  const name = (pd.caption || pd.title || '').slice(0, 60) || p.run_id?.slice(0, 16) || '—';
  const dt = p.schedule_at ? fmtDate(p.schedule_at) : (p.sent_at ? '✓ ' + fmtDate(p.sent_at) : '(imediato)');
  const statusColor = {sent:'var(--good)', error:'var(--bad)', pending:'var(--accent)', sending:'var(--muted)', cancelled:'var(--muted)'}[p.status] || 'var(--muted)';
  const grpId = pd.chat_id || pd.telegram_chat_id || '';
  const grpName = tgState.groups.find(g => g.id === grpId)?.name || grpId || '—';
  const teaserName = (pd.teaser_object_key || '').split('/').pop() || '—';
  return `
    <div class="sched-item" style="align-items:flex-start;gap:10px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(name)}</div>
        <div class="hint" style="margin-top:2px;">📁 ${esc(teaserName)} · 👥 ${esc(grpName)} · 🕐 ${esc(dt)}</div>
        ${p.error_log ? `<div class="hint" style="color:var(--bad);margin-top:2px;">⚠ ${esc(p.error_log)}</div>` : ''}
      </div>
      <span class="badge" style="background:${statusColor};color:#fff;font-size:10px;padding:2px 6px;border-radius:10px;white-space:nowrap;">${esc(p.status)}</span>
      ${p.status === 'pending' ? `<button class="btn" style="font-size:11px;padding:2px 8px;" onclick="tgDeletePost('${esc(p.id)}')">✕</button>` : ''}
    </div>
  `;
}

async function tgRefreshQueue() {
  await _tgLoadQueue();
  const qEl = qs('tgQueue');
  if (qEl) {
    qEl.innerHTML = tgState.queue.length
      ? tgState.queue.map(_tgQueueItemHtml).join('')
      : '<div class="criacao-empty">Nenhum post na fila ainda.</div>';
  }
}

async function tgDeletePost(postId) {
  try {
    await apiFetch(`/api/scheduled-posts/${postId}`, { method: 'DELETE' });
    toast('Post removido da fila', 'good');
    await tgRefreshQueue();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

function _safeJson(str) {
  try { return typeof str === 'string' ? JSON.parse(str) : (str || {}); } catch { return {}; }
}

// ═══════════════════════════════════════════════════════════════════════════
// AGENCY MODULES — Criadores, Publisher, Tendências, Calendário, Financeiro, DMCA
// ═══════════════════════════════════════════════════════════════════════════

// ── Shared state ──────────────────────────────────────────────────────────
const agencyState = {
  creators: [],
  editingCreatorId: null,
  autoEditorPollTimer: null,
  creatorPortalLogoB64: '',
};

// ── Helpers ────────────────────────────────────────────────────────────────
function statusBadge(status) {
  const colors = { active: '#2a9d5c', trial: '#f9a825', paused: '#666', churned: '#c44' };
  const labels = { active: 'Ativo', trial: 'Trial', paused: 'Pausado', churned: 'Churned' };
  const c = colors[status] || '#555';
  return `<span style="background:${c};color:#fff;font-size:10px;padding:2px 7px;border-radius:10px;font-weight:bold">${labels[status] || status}</span>`;
}

function platformIcons(platforms) {
  const icons = { xvideos: '🎬', pornhub: '🟠', xnxx: '🎥', xhamster: '🐹', redtube: '🔴', onlyfans: '💙' };
  return (platforms || []).map(p => {
    const icon = icons[p.platform] || '📡';
    const color = p.status === 'active' ? '#2a9d5c' : p.status === 'expired' ? '#c44' : '#666';
    return `<span title="${p.platform} (${p.status})" style="color:${color};font-size:16px">${icon}</span>`;
  }).join(' ');
}

async function agencyFetch(path, opts = {}) {
  return apiFetch(path, opts);
}

// ═══════════════════════════════════════════════════════════════════════════
// AUTH SYSTEM
// ═══════════════════════════════════════════════════════════════════════════

const authState = {
  session: null,
  checked: false,
};

const SESSION_KEY = 'mp_session';

const ALL_TABS = [
  'analyze','runs','media','referencia','criacao','compare',
  'settings','telegram','autoeditor','videoenhancer','creators','publisher','trends','calendar','financial','dmca',
  'clientes','aprovacao','concorrentes',
];

const TAB_LABELS = {
  analyze: 'Analyze', runs: 'Runs', media: 'Arquivos', referencia: 'Referência',
  criacao: 'Criação', compare: 'Compare', settings: 'Settings', telegram: 'Telegram',
  autoeditor: 'AutoEditor', videoenhancer: 'Video Enhancer', creators: 'Criadores', publisher: 'Publicar', trends: 'Tendências',
  calendar: 'Agenda', financial: 'Financeiro', dmca: 'DMCA',
  clientes: 'Clientes', aprovacao: 'Aprovação', concorrentes: 'Concorrentes',
};

const TAB_GROUPS = {
  analyze: 'Inteligência e Mídia',
  compare: 'Inteligência e Mídia',
  runs: 'Inteligência e Mídia',
  media: 'Inteligência e Mídia',
  referencia: 'Inteligência e Mídia',
  autoeditor: 'Inteligência e Mídia',
  videoenhancer: 'Inteligência e Mídia',
  criacao: 'Operação e Distribuição',
  telegram: 'Operação e Distribuição',
  publisher: 'Operação e Distribuição',
  calendar: 'Operação e Distribuição',
  creators: 'Gestão de Agência',
  trends: 'Gestão de Agência',
  financial: 'Gestão de Agência',
  dmca: 'Gestão de Agência',
  settings: 'Gestão de Agência',
  clientes: 'Gestão de Agência',
  aprovacao: 'Gestão de Agência',
  concorrentes: 'Gestão de Agência',
};

function updateTopbarContext(name) {
  const titleEl = qs('currentPageTitle');
  const eyebrowEl = qs('currentPageEyebrow');
  if (titleEl) titleEl.textContent = TAB_LABELS[name] || 'MetaPorn';
  if (eyebrowEl) eyebrowEl.textContent = TAB_GROUPS[name] || 'Painel MetaPorn';
}

function applySidebarNavFilters() {
  document.querySelectorAll('.nav a[data-route]').forEach(a => {
    const hiddenByAuth = a.dataset.authHidden === '1';
    const hiddenBySearch = a.dataset.searchHidden === '1';
    a.style.display = hiddenByAuth || hiddenBySearch ? 'none' : '';
  });

  document.querySelectorAll('.nav-section').forEach(section => {
    const links = [...section.querySelectorAll('a[data-route]')];
    const hasVisible = links.some(a => a.style.display !== 'none');
    section.style.display = hasVisible ? '' : 'none';
  });
}

function filterSidebarNav() {
  const query = (qs('navSearch')?.value || '').trim().toLowerCase();
  document.querySelectorAll('.nav a[data-route]').forEach(a => {
    const text = (a.textContent || '').toLowerCase();
    a.dataset.searchHidden = query && !text.includes(query) ? '1' : '0';
  });
  applySidebarNavFilters();
}

function toggleSidebar(force) {
  const next = typeof force === 'boolean'
    ? force
    : !document.body.classList.contains('sidebar-open');
  document.body.classList.toggle('sidebar-open', next);
}

function authSaveSession(data) {
  authState.session = data;
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(data));
}

function authLoadSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (raw) authState.session = JSON.parse(raw);
  } catch (e) {}
}

function authClearSession() {
  authState.session = null;
  sessionStorage.removeItem(SESSION_KEY);
}

function authGetToken() {
  return authState.session?.token || null;
}

function authGetUser() {
  return authState.session?.user || null;
}

function authIsAdmin() {
  return authGetUser()?.role === 'admin';
}

function authCanAccess(tab) {
  const user = authGetUser();
  if (!user) return false;
  return (user.permissions || []).includes(tab);
}

// Injeta X-Session-Token em todos os apiFetch
const _origApiFetch = apiFetch;
apiFetch = async function(path, opts = {}) {
  const token = authGetToken();
  if (token) {
    opts.headers = Object.assign({}, opts.headers || {}, { 'X-Session-Token': token });
  }
  return _origApiFetch(path, opts);
};

async function doLogin() {
  const username = (document.getElementById('loginUsername')?.value || '').trim();
  const password = document.getElementById('loginPassword')?.value || '';
  const errEl = document.getElementById('loginError');
  const btn = document.getElementById('loginBtn');

  errEl.classList.remove('visible');
  if (!username || !password) {
    errEl.textContent = 'Preencha usuário e senha.';
    errEl.classList.add('visible');
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Entrando…';

  try {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      const msgs = {
        invalid_credentials: 'Usuário ou senha incorretos.',
        account_inactive: 'Conta desativada. Fale com o administrador.',
        missing_credentials: 'Preencha usuário e senha.',
      };
      errEl.textContent = msgs[data.error] || 'Erro ao fazer login.';
      errEl.classList.add('visible');
      return;
    }

    authSaveSession({ token: data.token, user: data.user });
    authApplySession();

  } catch (e) {
    errEl.textContent = 'Erro de conexão com o servidor.';
    errEl.classList.add('visible');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Entrar';
  }
}

function doLogout() {
  authClearSession();
  document.getElementById('loginUsername').value = '';
  document.getElementById('loginPassword').value = '';
  document.getElementById('loginError').classList.remove('visible');
  document.getElementById('loginScreen').classList.remove('hidden');
  document.getElementById('sessionUserBadge').style.display = 'none';
  authApplyNavVisibility(null);
}

function authApplySession() {
  const user = authGetUser();
  const loginScreen = document.getElementById('loginScreen');

  if (!user) {
    loginScreen?.classList.remove('hidden');
    return;
  }

  loginScreen?.classList.add('hidden');

  const badge = document.getElementById('sessionUserBadge');
  const nameEl = document.getElementById('sessionUsername');
  if (badge && nameEl) {
    nameEl.textContent = user.username + (user.role !== 'viewer' ? ` (${user.role})` : '');
    badge.style.display = 'flex';
  }

  authApplyNavVisibility(user);

  const usersSection = document.getElementById('usersSection');
  if (usersSection) usersSection.style.display = authIsAdmin() ? 'block' : 'none';
}

function authApplyNavVisibility(user) {
  const perms = user ? (user.permissions || []) : [];
  document.querySelectorAll('.nav a[data-route]').forEach(a => {
    const tab = a.dataset.route;
    a.dataset.authHidden = (!user || !perms.includes(tab)) ? '1' : '0';
  });
  osApplyStartMenuVisibility(user);
  applySidebarNavFilters();
}

async function authInit() {
  // Mostra login por padrão até sabermos o estado
  document.getElementById('loginScreen')?.classList.remove('hidden');

  let authEnabled = true;
  try {
    const res = await fetch('/auth/check');
    const data = await res.json();
    authEnabled = !!data.auth_enabled;
  } catch (e) {
    // Servidor offline — mantém tela de login como precaução
    return;
  }

  if (!authEnabled) {
    // Modo aberto: sem usuários configurados — acesso livre
    document.getElementById('loginScreen')?.classList.add('hidden');
    authApplyNavVisibility({ permissions: ALL_TABS });
    // Mostra seção de usuários para setup inicial
    const usersSection = document.getElementById('usersSection');
    if (usersSection) usersSection.style.display = 'block';
    // Mostra badge com indicação de modo aberto
    const badge = document.getElementById('sessionUserBadge');
    const nameEl = document.getElementById('sessionUsername');
    if (badge && nameEl) {
      nameEl.textContent = 'Modo aberto';
      badge.style.display = 'flex';
    }
    return;
  }

  // Auth ativado — tenta sessão salva
  authLoadSession();
  const user = authGetUser();

  if (user) {
    try {
      const res = await fetch('/auth/me', {
        headers: { 'X-Session-Token': authGetToken() },
      });
      if (res.ok) {
        const data = await res.json();
        if (data.user && data.user.permissions) {
          authState.session.user = Object.assign({}, authState.session.user, { permissions: data.user.permissions });
          sessionStorage.setItem(SESSION_KEY, JSON.stringify(authState.session));
        }
        authApplySession();
        return;
      }
    } catch (e) {}
    authClearSession();
  }

  // Sem sessão válida → mostra login
  document.getElementById('loginScreen')?.classList.remove('hidden');
  authApplyNavVisibility(null);
}

// Teclas de atalho no formulário de login
document.getElementById('loginPassword')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') doLogin();
});
document.getElementById('loginUsername')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('loginPassword')?.focus();
});

document.addEventListener('click', e => {
  const link = e.target.closest('a[data-route], a[data-start-route]');
  if (!link) return;
  const name = link.dataset.route || link.dataset.startRoute;
  if (!name) return;
  paintMetaPornOsIcons();
  osCloseStart();
  if ((location.hash || '#analyze') === `#${name}`) routeTo(name);
});

window.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    toggleSidebar(false);
    osCloseStart();
  }
});

window.addEventListener('resize', () => {
  if (window.innerWidth > 900) toggleSidebar(false);
});

// Guard de rota — bloqueia abas sem permissão
const _origRouteTo2 = routeTo;
routeTo = function(name) {
  const user = authGetUser();
  if (user && !authCanAccess(name)) {
    const first = (user.permissions || [])[0];
    if (first && first !== name) routeTo(first);
    return;
  }
  _origRouteTo2(name);
  osSyncShellRoute(name);
  // Carrega usuários ao entrar em Settings: admin logado OU modo aberto
  if (name === 'settings' && (!authGetUser() || authIsAdmin())) usersLoad();
};

// ─── Gerenciamento de Usuários ───────────────────────────────────────────────

async function usersLoad() {
  // Permitido para admin logado OU modo aberto (sem auth configurado)
  if (authGetUser() && !authIsAdmin()) return;
  try {
    const data = await apiFetch('/auth/users');
    usersRender(data.users || []);
  } catch (e) {
    console.warn('usersLoad:', e.message);
  }
}

function usersRender(users) {
  const tbody = document.getElementById('usersTableBody');
  if (!tbody) return;

  if (!users.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px">Nenhum usuário cadastrado</td></tr>';
    return;
  }

  tbody.innerHTML = users.map(u => {
    const perms = u.effective_permissions || u.permissions || [];
    const permHtml = perms.length
      ? perms.map(p => `<span class="perm-chip">${TAB_LABELS[p] || p}</span>`).join('')
      : '<span style="color:var(--muted);font-size:.78rem">defaults do role</span>';
    const statusColor = u.active ? 'var(--good)' : 'var(--bad)';

    return `<tr>
      <td style="font-weight:600">${u.username}</td>
      <td><span class="role-badge ${u.role}">${u.role}</span></td>
      <td style="max-width:240px;line-height:1.8">${permHtml}</td>
      <td style="color:${statusColor}">${u.active ? 'Ativo' : 'Inativo'}</td>
      <td style="text-align:right;white-space:nowrap;display:flex;gap:4px;justify-content:flex-end;flex-wrap:wrap">
        <button class="btn" style="padding:4px 9px;font-size:.75rem" onclick="openUserModal('${u.user_id}')">Editar</button>
        <button class="btn" style="padding:4px 9px;font-size:.75rem" onclick="openResetPassword('${u.user_id}','${u.username}')">🔑 Senha</button>
        <button class="btn" style="padding:4px 9px;font-size:.75rem" onclick="openActivityLog('${u.user_id}','${u.username}')">📋 Log</button>
        <button class="btn" style="padding:4px 9px;font-size:.75rem;color:var(--bad);border-color:rgba(255,68,85,.4)" onclick="deleteUser('${u.user_id}','${u.username}')">Excluir</button>
      </td>
    </tr>`;
  }).join('');
}

let _editingUserId = null;

function buildPermGrid(selectedPerms) {
  const container = document.getElementById('userModalPerms');
  if (!container) return;
  container.innerHTML = ALL_TABS.map(tab => `
    <label>
      <input type="checkbox" value="${tab}" ${selectedPerms.includes(tab) ? 'checked' : ''}>
      ${TAB_LABELS[tab] || tab}
    </label>
  `).join('');
}

function getPermGridValues() {
  return Array.from(document.querySelectorAll('#userModalPerms input[type=checkbox]:checked'))
    .map(cb => cb.value);
}

const ROLE_PERM_DEFAULTS = {
  admin: ALL_TABS,
  editor: ["analyze","runs","media","referencia","criacao","compare","telegram","creators","autoeditor","videoenhancer","publisher","trends","calendar","financial","dmca"],
  viewer: ["analyze","runs","media","referencia"],
};

function userModalRoleChange() {
  const role = document.getElementById('userModalRole')?.value;
  if (role) buildPermGrid(ROLE_PERM_DEFAULTS[role] || []);
}

async function openUserModal(userId = null) {
  _ignoreNextModalClose = true;
  _editingUserId = userId;
  const modal = document.getElementById('userModal');
  const title = document.getElementById('userModalTitle');
  const passLabel = document.getElementById('userModalPassLabel');
  const passwordField = document.getElementById('userModalPassword');

  if (userId) {
    title.textContent = 'Editar Usuário';
    passLabel.textContent = 'Nova Senha (vazio = não alterar)';
    passwordField.value = '';

    try {
      const data = await apiFetch('/auth/users');
      const user = (data.users || []).find(u => u.user_id === userId);
      if (user) {
        document.getElementById('userModalId').value = user.user_id;
        document.getElementById('userModalUsername').value = user.username;
        document.getElementById('userModalRole').value = user.role;
        document.getElementById('userModalActive').value = user.active ? '1' : '0';
        // Use effective_permissions so admin always shows all tabs checked
        buildPermGrid(user.effective_permissions || user.permissions || ROLE_PERM_DEFAULTS[user.role] || []);
      }
    } catch (e) { toast('Erro ao carregar usuário', 'bad'); return; }
  } else {
    title.textContent = 'Novo Usuário';
    passLabel.textContent = 'Senha';
    document.getElementById('userModalId').value = '';
    document.getElementById('userModalUsername').value = '';
    passwordField.value = '';
    document.getElementById('userModalRole').value = 'viewer';
    document.getElementById('userModalActive').value = '1';
    buildPermGrid(ROLE_PERM_DEFAULTS['viewer']);
  }

  modal.classList.add('open');
}

function closeUserModal() {
  document.getElementById('userModal')?.classList.remove('open');
  _editingUserId = null;
}

async function saveUserModal() {
  const userId = _editingUserId;
  const username = (document.getElementById('userModalUsername')?.value || '').trim();
  const password = document.getElementById('userModalPassword')?.value;
  const role = document.getElementById('userModalRole')?.value;
  const active = document.getElementById('userModalActive')?.value === '1';
  const permissions = getPermGridValues();

  if (!username) { toast('Informe um nome de usuário', 'bad'); return; }
  if (!userId && !password) { toast('Informe uma senha', 'bad'); return; }

  const body = { username, role, active, permissions };
  if (password) body.password = password;

  try {
    if (userId) {
      await apiFetch(`/auth/users/${userId}`, { method: 'PUT', body: JSON.stringify(body) });
      toast('Usuário atualizado', 'good');
    } else {
      await apiFetch('/auth/users', { method: 'POST', body: JSON.stringify(body) });
      toast('Usuário criado', 'good');
    }
    closeUserModal();
    usersLoad();
  } catch (e) {
    const msg = e.message.includes('username_taken') ? 'Usuário já existe' : e.message;
    toast('Erro: ' + msg, 'bad');
  }
}

async function deleteUser(userId, username) {
  if (!confirm(`Excluir o usuário "${username}"? Esta ação não pode ser desfeita.`)) return;
  try {
    await apiFetch(`/auth/users/${userId}`, { method: 'DELETE' });
    toast('Usuário excluído', 'good');
    usersLoad();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

// ── Reset de Senha ────────────────────────────────────────────────────────────

function openResetPassword(userId, username) {
  _ignoreNextModalClose = true;
  document.getElementById('resetPasswordUserId').value = userId;
  document.getElementById('resetPasswordTitle').textContent = `Resetar Senha — ${username}`;
  document.getElementById('resetPasswordValue').value = '';
  document.getElementById('resetPasswordModal').style.display = 'flex';
}

function closeResetPassword() {
  document.getElementById('resetPasswordModal').style.display = 'none';
}

async function saveResetPassword() {
  const userId = document.getElementById('resetPasswordUserId').value;
  const password = document.getElementById('resetPasswordValue').value;
  if (!password || password.length < 4) { toast('Senha mínima de 4 caracteres', 'bad'); return; }
  try {
    await apiFetch(`/auth/users/${userId}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ password }),
    });
    toast('Senha atualizada', 'good');
    closeResetPassword();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

// ── Log de Atividade ─────────────────────────────────────────────────────────

const ACTION_LABELS = {
  login: '🔐 Login',
  create_user: '➕ Criou usuário',
  update_user: '✏️ Editou usuário',
  delete_user: '🗑️ Excluiu usuário',
  reset_password: '🔑 Resetou senha',
};

async function openActivityLog(userId = null, title = 'Log de Atividade') {
  _ignoreNextModalClose = true;
  document.getElementById('activityLogTitle').textContent = title;
  const listEl = document.getElementById('activityLogList');
  listEl.innerHTML = '<div style="color:var(--muted);font-size:.85rem">Carregando…</div>';
  document.getElementById('activityLogModal').style.display = 'flex';
  try {
    const url = userId ? `/auth/users/${userId}/logs` : '/auth/logs';
    const data = await apiFetch(url);
    const logs = data.logs || [];
    if (!logs.length) {
      listEl.innerHTML = '<div style="color:var(--muted);font-size:.85rem;text-align:center;padding:20px">Nenhuma atividade registrada</div>';
      return;
    }
    listEl.innerHTML = logs.map(l => {
      const dt = l.created_at ? l.created_at.slice(0, 19).replace('T', ' ') : '';
      const action = ACTION_LABELS[l.action] || l.action;
      const target = l.target ? ` → <strong>${l.target}</strong>` : '';
      const details = l.details ? `<span style="color:var(--muted);font-size:.75rem"> (${l.details})</span>` : '';
      const ip = l.ip ? `<span style="color:var(--muted);font-size:.72rem;margin-left:8px">${l.ip}</span>` : '';
      const actor = !userId ? `<div style="color:var(--muted);font-size:.75rem;margin-top:2px">por <strong>${l.username}</strong></div>` : '';
      return `<div style="background:var(--card2);border-radius:6px;padding:8px 12px;font-size:.82rem;border-left:3px solid var(--line2)">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
          <span>${action}${target}${details}</span>
          <span style="color:var(--muted);font-size:.75rem;white-space:nowrap">${dt}${ip}</span>
        </div>${actor}
      </div>`;
    }).join('');
  } catch (e) {
    listEl.innerHTML = `<div style="color:var(--bad);font-size:.85rem">Erro: ${e.message}</div>`;
  }
}

function closeActivityLog() {
  document.getElementById('activityLogModal').style.display = 'none';
}

let _ignoreNextModalClose = false;

document.addEventListener('click', e => {
  if (_ignoreNextModalClose) { _ignoreNextModalClose = false; return; }
  const modal = document.getElementById('userModal');
  if (modal?.classList.contains('open')) {
    const box = modal.querySelector('.user-modal-box');
    if (box && !box.contains(e.target)) closeUserModal();
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// MODULE 1: CREATORS
// ═══════════════════════════════════════════════════════════════════════════

async function creatorsLoad() {
  try {
    const data = await agencyFetch('/api/creators');
    agencyState.creators = data.creators || [];
    creatorsRender(agencyState.creators);
    // Populate creator dropdowns in other modules
    populateCreatorDropdowns(agencyState.creators);
  } catch (e) {
    toast('Erro ao carregar criadores: ' + e.message, 'bad');
  }
}

function populateCreatorDropdowns(creators) {
  const ids = ['aeCreator', 'ae_creator', 'pub_creator', 'trends_creator', 'dmca_creator', 'fin_creator', 'cal_creator', 'fe_creator'];
  ids.forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const val = sel.value;
    const baseOption = id === 'aeCreator'
      ? '<option value="">Nenhum (uso interno)</option>'
      : '<option value="">Selecione...</option>';
    sel.innerHTML = baseOption +
      creators.map(c => `<option value="${c.creator_id}">${c.name} (${c.status})</option>`).join('');
    if (val) sel.value = val;
  });
}

function creatorsFilter() {
  const q = (document.getElementById('creatorsSearch')?.value || '').toLowerCase();
  const s = document.getElementById('creatorsStatusFilter')?.value || '';
  const filtered = agencyState.creators.filter(c => {
    const nameMatch = c.name.toLowerCase().includes(q);
    const slugMatch = String(c.slug || '').toLowerCase().includes(q);
    const statusMatch = !s || c.status === s;
    return (nameMatch || slugMatch) && statusMatch;
  });
  creatorsRender(filtered);
}

function _creatorPortalBrandingDefaults(src = {}) {
  return {
    brand_name: typeof src.brand_name === 'string' ? src.brand_name : '',
    headline: typeof src.headline === 'string' ? src.headline : '',
    tagline: typeof src.tagline === 'string' ? src.tagline : '',
    primary_color: typeof src.primary_color === 'string' && src.primary_color ? src.primary_color : '#67e8f9',
    secondary_color: typeof src.secondary_color === 'string' && src.secondary_color ? src.secondary_color : '#8b5cf6',
    accent_color: typeof src.accent_color === 'string' && src.accent_color ? src.accent_color : '#22d3ee',
    surface_color: typeof src.surface_color === 'string' && src.surface_color ? src.surface_color : '#0f172a',
    text_color: typeof src.text_color === 'string' && src.text_color ? src.text_color : '#e2e8f0',
    logo_b64: typeof src.logo_b64 === 'string' ? src.logo_b64 : '',
  };
}

function _creatorSlugify(value, fallback = 'criador') {
  const normalized = String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
  return normalized || fallback;
}

function _creatorPortalUrl(slug) {
  const clean = String(slug || '').trim();
  return clean ? `https://criador.caripost.n8nmikael.com.br/${clean}` : '';
}

function _updateCreatorSlugHint() {
  const hint = document.getElementById('cf_slug_hint');
  if (!hint) return;
  const slug = document.getElementById('cf_slug')?.value?.trim() || '';
  hint.textContent = slug
    ? `URL pública: ${_creatorPortalUrl(slug)}`
    : 'URL pública: será gerada automaticamente.';
  const show = slug ? 'inline-block' : 'none';
  const copyBtn = document.getElementById('cf_slug_copy_btn');
  const previewBtn = document.getElementById('cf_slug_preview_btn');
  if (copyBtn) copyBtn.style.display = show;
  if (previewBtn) previewBtn.style.display = show;
}

function creatorsPreviewPortal(slug) {
  const url = _creatorPortalUrl(String(slug || '').trim());
  if (!url) return toast('Este criador ainda não tem slug.', 'bad');
  window.open(url, '_blank', 'noopener,noreferrer');
}

function creatorsSlugEdited() {
  const input = document.getElementById('cf_slug');
  if (!input) return;
  input.dataset.dirty = input.value.trim() ? '1' : '';
  _updateCreatorSlugHint();
}

function creatorsMaybeFillSlug(force = false) {
  const name = document.getElementById('cf_name')?.value || '';
  const slugInput = document.getElementById('cf_slug');
  if (!slugInput) return;
  const hasManualSlug = slugInput.dataset.dirty === '1' && slugInput.value.trim();
  if (force || !hasManualSlug) {
    slugInput.value = name.trim() ? _creatorSlugify(name) : '';
  }
  _updateCreatorSlugHint();
}

function creatorsCopyPortalLink(slug) {
  const url = _creatorPortalUrl(slug);
  if (!url) return toast('Este criador ainda não tem slug.', 'bad');
  navigator.clipboard.writeText(url)
    .then(() => toast('Link do portal copiado!', 'good'))
    .catch(() => toast('Não consegui copiar o link.', 'bad'));
}

function _updateCreatorPortalPreview() {
  const branding = {
    brand_name: document.getElementById('cf_portal_brand_name')?.value?.trim() || '',
    headline: document.getElementById('cf_portal_headline')?.value?.trim() || '',
    tagline: document.getElementById('cf_portal_tagline')?.value?.trim() || '',
    primary_color: document.getElementById('cf_portal_primary_color')?.value || '#67e8f9',
    secondary_color: document.getElementById('cf_portal_secondary_color')?.value || '#8b5cf6',
    accent_color: document.getElementById('cf_portal_accent_color')?.value || '#22d3ee',
    surface_color: document.getElementById('cf_portal_surface_color')?.value || '#0f172a',
    text_color: document.getElementById('cf_portal_text_color')?.value || '#e2e8f0',
    logo_b64: agencyState.creatorPortalLogoB64 || '',
  };
  const wrap = document.getElementById('cf_portal_preview');
  const brand = document.getElementById('cf_portal_preview_brand');
  const headline = document.getElementById('cf_portal_preview_headline');
  const tagline = document.getElementById('cf_portal_preview_tagline');
  const logo = document.getElementById('cf_portal_logo_preview');
  const status = document.getElementById('cf_portal_logo_status');
  if (wrap) {
    wrap.style.background = `linear-gradient(135deg, ${branding.surface_color}, ${branding.secondary_color}22 55%, ${branding.primary_color}18 100%)`;
    wrap.style.borderColor = `${branding.primary_color}55`;
    wrap.style.boxShadow = `0 18px 40px ${branding.secondary_color}22`;
  }
  if (brand) {
    brand.textContent = branding.brand_name || 'MetaPorn Agency';
    brand.style.color = branding.primary_color;
  }
  if (headline) {
    headline.textContent = branding.headline || 'Creator Portal';
    headline.style.color = branding.text_color;
  }
  if (tagline) {
    tagline.textContent = branding.tagline || 'Personalize a experiência visual do criador.';
    tagline.style.color = branding.text_color;
    tagline.style.opacity = '0.85';
  }
  if (logo) {
    if (branding.logo_b64) {
      logo.src = branding.logo_b64;
      logo.style.display = 'block';
      logo.style.border = `1px solid ${branding.primary_color}44`;
    } else {
      logo.removeAttribute('src');
      logo.style.display = 'none';
    }
  }
  if (status) status.textContent = branding.logo_b64 ? 'Logo personalizada pronta.' : 'Sem logo personalizada.';
}

function creatorsPortalLogoSelected(input) {
  const file = input?.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    agencyState.creatorPortalLogoB64 = typeof reader.result === 'string' ? reader.result : '';
    _updateCreatorPortalPreview();
  };
  reader.onerror = () => toast('Erro ao ler logo do portal', 'bad');
  reader.readAsDataURL(file);
}

function creatorsClearPortalLogo() {
  agencyState.creatorPortalLogoB64 = '';
  const input = document.getElementById('cf_portal_logo_file');
  if (input) input.value = '';
  _updateCreatorPortalPreview();
}

function creatorsRender(list) {
  const grid = document.getElementById('creatorsGrid');
  const empty = document.getElementById('creatorsEmpty');
  if (!grid) return;
  if (!list.length) {
    grid.innerHTML = '';
    empty && empty.classList.remove('hidden');
    return;
  }
  empty && empty.classList.add('hidden');
  grid.innerHTML = list.map(c => `
    <div class="card" style="cursor:pointer;transition:border-color .2s" onclick="creatorsShowDetail('${c.creator_id}')"
         onmouseenter="this.style.borderColor='var(--pri)'" onmouseleave="this.style.borderColor=''">
      <div style="display:flex;justify-content:space-between;align-items:start">
        <div>
          <div style="font-size:17px;font-weight:bold;color:#fff">${c.name}</div>
          <div style="font-size:12px;color:#666;margin-top:2px">${c.email}</div>
          ${c.slug ? `<div style="font-size:11px;color:#7dd3fc;margin-top:4px">${esc(_creatorPortalUrl(c.slug))}</div>` : ''}
        </div>
        ${statusBadge(c.status)}
      </div>
      <div style="margin-top:10px;display:flex;align-items:center;gap:8px">
        ${platformIcons(c.platforms || [])}
        <span style="margin-left:auto;font-size:11px;color:#555">${c.platform_count || 0} plataformas</span>
      </div>
      <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn" style="font-size:11px;padding:4px 8px" onclick="event.stopPropagation();creatorsShowEdit('${c.creator_id}')">✏️ Editar</button>
        <button class="btn" style="font-size:11px;padding:4px 8px" onclick="event.stopPropagation();creatorsAddPlatform('${c.creator_id}')">🔗 Plataforma</button>
        <button class="btn primary" style="font-size:11px;padding:4px 8px" onclick="event.stopPropagation();location.hash='publisher';publisherSetCreator('${c.creator_id}')">🚀 Publicar</button>
        ${c.slug ? `<button class="btn" style="font-size:11px;padding:4px 8px" onclick="event.stopPropagation();creatorsCopyPortalLink('${esc(c.slug)}')">📋 Portal</button>
        <button class="btn" style="font-size:11px;padding:4px 8px" onclick="event.stopPropagation();creatorsPreviewPortal('${esc(c.slug)}')">👁 Ver</button>` : ''}
      </div>
    </div>`).join('');
}

async function creatorsShowDetail(id) {
  const modal = document.getElementById('creatorModal');
  const content = document.getElementById('creatorModalContent');
  if (!modal || !content) return;

  content.innerHTML = '<div style="color:#aaa;padding:20px">Carregando...</div>';
  modal.classList.remove('hidden');

  try {
    const c = await agencyFetch(`/api/creators/${id}`);
    const stats = await agencyFetch(`/api/creators/${id}/stats`).catch(() => ({ stats: [] }));

    content.innerHTML = `
      <h2 style="margin-bottom:4px">${c.name} ${statusBadge(c.status)}</h2>
      <div style="color:#666;font-size:13px;margin-bottom:20px">${c.email}</div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;font-size:13px">
        <div><strong style="color:#aaa">Comissão:</strong> ${c.commission_pct}%</div>
        <div><strong style="color:#aaa">Idioma:</strong> ${c.content_language}</div>
        <div><strong style="color:#aaa">WhatsApp:</strong> ${c.whatsapp || '—'}</div>
        <div><strong style="color:#aaa">Frequência Briefing:</strong> ${c.trend_report_frequency}</div>
        <div><strong style="color:#aaa">Slug do portal:</strong> ${c.slug ? esc(c.slug) : '—'}</div>
        <div><strong style="color:#aaa">URL pública:</strong> ${c.slug ? `<a href="${esc(_creatorPortalUrl(c.slug))}" target="_blank" rel="noopener noreferrer" style="color:#7dd3fc">${esc(_creatorPortalUrl(c.slug))}</a>` : '—'}</div>
      </div>

      ${(() => {
        const pb = _creatorPortalBrandingDefaults(c.portal_branding || {});
        return `
          <h3 style="color:#aaa;margin-bottom:8px">Branding do Portal</h3>
          <div style="display:flex;align-items:center;gap:14px;border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:14px;background:linear-gradient(135deg, ${pb.surface_color}, ${pb.secondary_color}22 60%, ${pb.primary_color}16)">
            ${pb.logo_b64 ? `<img src="${esc(pb.logo_b64)}" alt="Logo portal" style="width:58px;height:58px;object-fit:contain;border-radius:14px;background:rgba(255,255,255,.05);padding:8px;border:1px solid ${pb.primary_color}55">` : ''}
            <div style="min-width:0">
              <div style="font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:${pb.primary_color}">${esc(pb.brand_name || 'MetaPorn Agency')}</div>
              <div style="font-size:22px;font-weight:700;color:${pb.text_color || '#fff'};margin-top:4px">${esc(pb.headline || 'Creator Portal')}</div>
              <div style="font-size:13px;color:${pb.text_color || '#cbd5e1'};opacity:.82;margin-top:6px">${esc(pb.tagline || 'Portal personalizado do criador.')}</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
                ${[pb.primary_color, pb.secondary_color, pb.accent_color, pb.surface_color, pb.text_color].map(color => `<span style="width:18px;height:18px;border-radius:999px;border:1px solid rgba(255,255,255,.16);background:${esc(color)}"></span>`).join('')}
              </div>
            </div>
          </div>
        `;
      })()}

      <h3 style="color:#aaa;margin-bottom:8px">Plataformas Conectadas</h3>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px">
        ${(c.platforms || []).map(p => `
          <div style="background:#1a1a1a;border:1px solid #${p.status==='active'?'2a9d5c':'333'};border-radius:6px;padding:8px 12px;font-size:12px">
            <strong>${p.platform}</strong> · ${p.username}<br>
            <span style="color:${p.status==='active'?'#2a9d5c':p.status==='expired'?'#c44':'#666'}">${p.status}</span>
            ${p.last_login_check ? `<span style="color:#555"> · Verificado: ${p.last_login_check.substring(0,10)}</span>` : ''}
          </div>`).join('') || '<div style="color:#555">Nenhuma plataforma configurada</div>'}
      </div>

      ${stats.stats?.length ? `
        <h3 style="color:#aaa;margin-bottom:8px">Últimas Estatísticas</h3>
        <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px">
          ${stats.stats.map(s => `
            <div style="background:#1a1a1a;border:1px solid #333;border-radius:6px;padding:10px;font-size:12px;min-width:140px">
              <div style="font-weight:bold;margin-bottom:4px">${s.platform}</div>
              <div>👁 ${(s.total_views||0).toLocaleString()} views</div>
              <div>👥 ${(s.subscribers||0).toLocaleString()} subs</div>
              <div>🎬 ${(s.total_videos||0)} vídeos</div>
            </div>`).join('')}
        </div>` : ''}

      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
        <button class="btn" onclick="creatorsLoginCheck('${id}')">🔐 Verificar Login</button>
        ${c.slug ? `<button class="btn" onclick="creatorsCopyPortalLink('${esc(c.slug)}')">🔗 Copiar Link do Portal</button>` : ''}
        <button class="btn" onclick="creatorsShowEdit('${id}');creatorsCloseModal()">✏️ Editar</button>
        <button class="btn" style="color:#c44;border-color:#c44" onclick="creatorsDelete('${id}')">🗑 Desativar</button>
      </div>`;
  } catch (e) {
    content.innerHTML = `<div style="color:var(--pri)">Erro: ${e.message}</div>`;
  }
}

function creatorsCloseModal() {
  document.getElementById('creatorModal')?.classList.add('hidden');
}

function togglePill(btn, groupId) {
  const on = btn.dataset.active === '1';
  btn.dataset.active = on ? '' : '1';
  btn.style.background = on ? '#1a1a1a' : '#0e7490';
  btn.style.borderColor = on ? '#444' : '#0e7490';
  btn.style.color = on ? '#aaa' : '#fff';
}

function setPills(groupId, values) {
  const group = document.getElementById(groupId);
  if (!group) return;
  group.querySelectorAll('button[data-val]').forEach(btn => {
    const active = values.includes(btn.dataset.val);
    btn.dataset.active = active ? '1' : '';
    btn.style.background = active ? '#0e7490' : '#1a1a1a';
    btn.style.borderColor = active ? '#0e7490' : '#444';
    btn.style.color = active ? '#fff' : '#aaa';
  });
}

function getPills(groupId) {
  const group = document.getElementById(groupId);
  if (!group) return [];
  return Array.from(group.querySelectorAll('button[data-val]'))
    .filter(btn => btn.dataset.active === '1')
    .map(btn => btn.dataset.val);
}

function aeToggle(id) {
  const btn = document.getElementById(id);
  if (!btn) return;
  btn.classList.toggle('active');
}

function aeIsOn(id) {
  const btn = document.getElementById(id);
  return btn ? btn.classList.contains('active') : false;
}

function creatorsShowAddForm() {
  agencyState.editingCreatorId = null;
  agencyState.creatorPortalLogoB64 = '';
  document.getElementById('creatorFormTitle').textContent = 'Novo Criador';
  document.getElementById('cf_name').value = '';
  document.getElementById('cf_slug').value = '';
  document.getElementById('cf_slug').dataset.dirty = '';
  document.getElementById('cf_email').value = '';
  document.getElementById('cf_whatsapp').value = '';
  document.getElementById('cf_status').value = 'trial';
  document.getElementById('cf_commission').value = '25';
  document.getElementById('cf_lang').value = 'pt-BR';
  document.getElementById('cf_categories').value = '';
  document.getElementById('cf_tags').value = '';
  document.getElementById('cf_reference_channels').value = '';
  document.getElementById('cf_own_channel_urls').value = '';
  setPills('cf_filming_setups_group', []);
  setPills('cf_location_types_group', []);
  document.getElementById('cf_production_level').value = 'amateur';
  document.getElementById('cf_performer_description').value = '';
  document.getElementById('cf_production_constraints').value = '';
  document.getElementById('cf_portal_password').value = '';
  document.getElementById('cf_portal_password2').value = '';
  document.getElementById('cf_notes').value = '';
  document.getElementById('cf_portal_brand_name').value = '';
  document.getElementById('cf_portal_headline').value = '';
  document.getElementById('cf_portal_tagline').value = '';
  document.getElementById('cf_portal_primary_color').value = '#67e8f9';
  document.getElementById('cf_portal_secondary_color').value = '#8b5cf6';
  document.getElementById('cf_portal_accent_color').value = '#22d3ee';
  document.getElementById('cf_portal_surface_color').value = '#0f172a';
  document.getElementById('cf_portal_text_color').value = '#e2e8f0';
  document.getElementById('cf_portal_logo_file').value = '';
  document.getElementById('cf_error').classList.add('hidden');
  _updateCreatorSlugHint();
  _updateCreatorPortalPreview();
  document.getElementById('creatorFormPanel').classList.remove('hidden');
  document.getElementById('creatorFormPanel').scrollIntoView({ behavior: 'smooth' });
}

async function creatorsShowEdit(id) {
  try {
    const c = await agencyFetch(`/api/creators/${id}`);
    agencyState.editingCreatorId = id;
  document.getElementById('creatorFormTitle').textContent = 'Editar Criador';
  document.getElementById('cf_name').value = c.name;
  document.getElementById('cf_slug').value = c.slug || '';
  document.getElementById('cf_slug').dataset.dirty = c.slug ? '1' : '';
    document.getElementById('cf_email').value = c.email;
    document.getElementById('cf_whatsapp').value = c.whatsapp || '';
    document.getElementById('cf_status').value = c.status;
    document.getElementById('cf_commission').value = c.commission_pct;
    document.getElementById('cf_lang').value = c.content_language || 'pt-BR';
    document.getElementById('cf_categories').value = (c.preferred_categories || []).join(', ');
    document.getElementById('cf_tags').value = (c.preferred_tags || []).join(', ');
    document.getElementById('cf_reference_channels').value = (c.reference_channels || []).join('\n');
    document.getElementById('cf_own_channel_urls').value = (c.own_channel_urls || []).join('\n');
    setPills('cf_filming_setups_group', c.filming_setups || []);
    setPills('cf_location_types_group', c.location_types || []);
    document.getElementById('cf_production_level').value = c.production_level || 'amateur';
    document.getElementById('cf_performer_description').value = c.performer_description || '';
    document.getElementById('cf_production_constraints').value = c.production_constraints || '';
    document.getElementById('cf_portal_password').value = '';
    document.getElementById('cf_portal_password2').value = '';
    document.getElementById('cf_notes').value = c.notes || '';
    const pb = _creatorPortalBrandingDefaults(c.portal_branding || {});
    agencyState.creatorPortalLogoB64 = pb.logo_b64 || '';
    document.getElementById('cf_portal_brand_name').value = pb.brand_name || '';
    document.getElementById('cf_portal_headline').value = pb.headline || '';
    document.getElementById('cf_portal_tagline').value = pb.tagline || '';
    document.getElementById('cf_portal_primary_color').value = pb.primary_color;
    document.getElementById('cf_portal_secondary_color').value = pb.secondary_color;
    document.getElementById('cf_portal_accent_color').value = pb.accent_color;
    document.getElementById('cf_portal_surface_color').value = pb.surface_color;
    document.getElementById('cf_portal_text_color').value = pb.text_color;
    document.getElementById('cf_portal_logo_file').value = '';
    document.getElementById('cf_error').classList.add('hidden');
    _updateCreatorSlugHint();
    _updateCreatorPortalPreview();
    document.getElementById('creatorFormPanel').classList.remove('hidden');
    document.getElementById('creatorFormPanel').scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    toast('Erro ao carregar criador: ' + e.message, 'bad');
  }
}

function creatorsHideForm() {
  document.getElementById('creatorFormPanel').classList.add('hidden');
  agencyState.editingCreatorId = null;
}

async function creatorsSave() {
  const name = document.getElementById('cf_name').value.trim();
  const email = document.getElementById('cf_email').value.trim();
  const errDiv = document.getElementById('cf_error');

  if (!name || !email) {
    errDiv.textContent = 'Nome e email são obrigatórios.';
    errDiv.classList.remove('hidden');
    return;
  }

  const pass1 = document.getElementById('cf_portal_password').value;
  const pass2 = document.getElementById('cf_portal_password2').value;
  if (pass1 && pass1 !== pass2) {
    errDiv.textContent = 'As senhas do portal não conferem.';
    errDiv.classList.remove('hidden');
    return;
  }

  const referenceChannels = document.getElementById('cf_reference_channels').value
    .split('\n').map(s => s.trim()).filter(Boolean);

  const payload = {
    name,
    slug: document.getElementById('cf_slug').value.trim() || null,
    email,
    whatsapp: document.getElementById('cf_whatsapp').value.trim() || null,
    status: document.getElementById('cf_status').value,
    commission_pct: parseFloat(document.getElementById('cf_commission').value) || 25,
    content_language: document.getElementById('cf_lang').value || 'pt-BR',
    preferred_categories: document.getElementById('cf_categories').value.split(',').map(s => s.trim()).filter(Boolean),
    preferred_tags: document.getElementById('cf_tags').value.split(',').map(s => s.trim()).filter(Boolean),
    reference_channels: referenceChannels,
    own_channel_urls: document.getElementById('cf_own_channel_urls').value.split('\n').map(s => s.trim()).filter(Boolean),
    filming_setups: getPills('cf_filming_setups_group'),
    location_types: getPills('cf_location_types_group'),
    production_level: document.getElementById('cf_production_level').value || 'amateur',
    performer_description: document.getElementById('cf_performer_description').value.trim() || null,
    production_constraints: document.getElementById('cf_production_constraints').value.trim() || null,
    notes: document.getElementById('cf_notes').value || null,
    portal_branding: {
      brand_name: document.getElementById('cf_portal_brand_name').value.trim() || null,
      headline: document.getElementById('cf_portal_headline').value.trim() || null,
      tagline: document.getElementById('cf_portal_tagline').value.trim() || null,
      primary_color: document.getElementById('cf_portal_primary_color').value || '#67e8f9',
      secondary_color: document.getElementById('cf_portal_secondary_color').value || '#8b5cf6',
      accent_color: document.getElementById('cf_portal_accent_color').value || '#22d3ee',
      surface_color: document.getElementById('cf_portal_surface_color').value || '#0f172a',
      text_color: document.getElementById('cf_portal_text_color').value || '#e2e8f0',
      logo_b64: agencyState.creatorPortalLogoB64 || null,
    },
  };

  try {
    let creatorId = agencyState.editingCreatorId;
    if (creatorId) {
      await agencyFetch(`/api/creators/${creatorId}`, {
        method: 'PUT', body: JSON.stringify(payload)
      });
      toast('Criador atualizado!', 'good');
    } else {
      const created = await agencyFetch('/api/creators', { method: 'POST', body: JSON.stringify(payload) });
      creatorId = created?.creator_id;
      toast('Criador criado!', 'good');
    }

    // Set portal password if provided
    if (pass1 && creatorId) {
      await agencyFetch('/api/portal/set-password', {
        method: 'POST',
        body: JSON.stringify({ creator_id: creatorId, password: pass1 }),
      });
      toast('Senha do portal definida!', 'good');
    }

    creatorsHideForm();
    creatorsLoad();
  } catch (e) {
    errDiv.textContent = 'Erro: ' + e.message;
    errDiv.classList.remove('hidden');
  }
}

async function creatorsDelete(id) {
  if (!confirm('Desativar este criador?')) return;
  try {
    await agencyFetch(`/api/creators/${id}`, { method: 'DELETE' });
    toast('Criador desativado.', 'good');
    creatorsCloseModal();
    creatorsLoad();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function creatorsLoginCheck(id) {
  toast('Verificando login nas plataformas...', 'good');
  try {
    const result = await agencyFetch(`/api/creators/${id}/login-check`, { method: 'POST', body: '{}' });
    const msgs = Object.entries(result.platforms || {}).map(([p, r]) => `${p}: ${r.status}`).join('\n');
    alert('Status de Login:\n\n' + msgs);
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function creatorsAddPlatform(creatorId) {
  const platform = prompt('Plataforma (xvideos, pornhub, xnxx, xhamster):');
  if (!platform) return;
  const username = prompt('Username nesta plataforma:');
  if (!username) return;
  const profileUrl = prompt('URL do perfil (opcional):') || null;

  try {
    await agencyFetch(`/api/creators/${creatorId}/platforms`, {
      method: 'POST',
      body: JSON.stringify({ platform, username, profile_url: profileUrl }),
    });
    toast(`Plataforma ${platform} adicionada!`, 'good');
    creatorsLoad();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// MODULE: AUTOEDITOR
// ═══════════════════════════════════════════════════════════════════════════

let _aeUploadListVisible = false;
let _aePollTimer = null;
let _aeCurrentJobId = '';
const _aeJobsCache = new Map();
const _aeUploadsCache = new Map();
const _aeSelectedKeys = [];
const aeProgress = new AnimatedProgress('aeProgressWrap', 'aeProgressFill', 'aeProgressLabel');

async function autoeditorLoad() {
  if (!agencyState.creators.length) {
    const data = await agencyFetch('/api/creators').catch(() => ({ creators: [] }));
    agencyState.creators = data.creators || [];
  }
  populateCreatorDropdowns(agencyState.creators || []);
  aeUpdateTransitionUI();
  _aeRenderSelectedSources();
  aeLoadJobs();
  aeLoadPrompt();
}

function autoEditorLoad() { return autoeditorLoad(); }

function aeUpdateTransitionUI() {
  const mode = qs('aeTransitionMode')?.value || 'smart';
  const opts = qs('aeTransitionOptions');
  const smartOpts = qs('aeSmartOptions');
  if (opts) opts.style.display = mode === 'none' ? 'none' : '';
  if (smartOpts) smartOpts.style.display = mode === 'smart' ? '' : 'none';
}

function aeStopPolling() {
  if (_aePollTimer) clearInterval(_aePollTimer);
  _aePollTimer = null;
}

async function aeToggleUploadList() {
  const area = qs('aeUploadList');
  if (!area) return;
  _aeUploadListVisible = !_aeUploadListVisible;
  area.classList.toggle('hidden', !_aeUploadListVisible);
  if (_aeUploadListVisible) await aeLoadUploadList();
}

async function aeLoadUploadList() {
  const area = qs('aeUploadList');
  if (!area) return;
  area.innerHTML = '<div style="padding:8px;color:var(--muted)">Carregando…</div>';
  try {
    const res = await apiFetch('/uploads/list?max_keys=200');
    const items = res.items || [];
    _aeUploadsCache.clear();
    items.forEach(item => _aeUploadsCache.set(String(item.object_key || ''), item));
    if (!items.length) {
      area.innerHTML = '<div style="padding:8px;color:var(--muted)">Nenhum vídeo no servidor.</div>';
      return;
    }
    area.innerHTML = items.map(it => {
      const keyJson = JSON.stringify(String(it.object_key || ''));
      const active = _aeSelectedKeys.includes(String(it.object_key || ''));
      return `<div class="item" onclick='aeSelectVideo(${keyJson})'>
        <div style="flex:1;min-width:0;">
          <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(it.filename || it.object_key || '-')}</div>
          <div style="font-size:11px;color:var(--muted)">${it.size_mb || '?'} MB · ${(it.last_modified || '').slice(0,10)}</div>
        </div>
        <button class="btn" style="font-size:11px;padding:4px 10px;" onclick="event.stopPropagation();aeSelectVideo(${keyJson})">${active ? 'Selecionado' : 'Adicionar'}</button>
      </div>`;
    }).join('');
  } catch (e) {
    area.innerHTML = `<div style="padding:8px;color:var(--bad)">${esc(e.message)}</div>`;
  }
}

function _aeRenderSelectedSources() {
  const wrap = qs('aeSelectedSources');
  const info = qs('aeVideoInfo');
  const countLabel = qs('aeObjectKey');
  if (countLabel) {
    countLabel.textContent = `${_aeSelectedKeys.length} vídeo${_aeSelectedKeys.length === 1 ? '' : 's'}`;
  }
  if (info) {
    info.textContent = _aeSelectedKeys.length
      ? `${_aeSelectedKeys.length} vídeo(s) na fila do AutoEditor. A ordem abaixo será respeitada na junção.`
      : 'Nenhum vídeo selecionado';
  }
  if (!wrap) return;
  if (!_aeSelectedKeys.length) {
    wrap.innerHTML = '<div class="hint">Adicione um ou mais vídeos para iniciar o AutoEditor.</div>';
    return;
  }
  wrap.innerHTML = _aeSelectedKeys.map((objectKey, idx) => {
    const meta = _aeUploadsCache.get(String(objectKey || '')) || {};
    const label = meta.filename || objectKey.split('/').pop() || objectKey;
    const size = meta.size_mb ? `${meta.size_mb} MB` : '';
    return `<div class="item">
      <div style="flex:1;min-width:0;">
        <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(idx + 1)}. ${esc(label)}</div>
        <div style="font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(size)} ${size ? '·' : ''} ${esc(objectKey)}</div>
      </div>
      <div style="display:flex;gap:6px;align-items:center;">
        <button class="btn" style="font-size:11px;padding:4px 8px;" onclick="event.stopPropagation();aeMoveVideo('${escAttr(objectKey)}', -1)" ${idx === 0 ? 'disabled' : ''}>↑</button>
        <button class="btn" style="font-size:11px;padding:4px 8px;" onclick="event.stopPropagation();aeMoveVideo('${escAttr(objectKey)}', 1)" ${idx === _aeSelectedKeys.length - 1 ? 'disabled' : ''}>↓</button>
        <button class="btn" style="font-size:11px;padding:4px 8px;" onclick="event.stopPropagation();aeRemoveVideo('${escAttr(objectKey)}')">✕</button>
      </div>
    </div>`;
  }).join('');
}

function aeSelectVideo(objectKey) {
  const key = String(objectKey || '').trim();
  if (!key) return;
  if (!_aeSelectedKeys.includes(key)) {
    _aeSelectedKeys.push(key);
  }
  _aeRenderSelectedSources();
  if (_aeUploadListVisible) aeLoadUploadList();
}

function aeRemoveVideo(objectKey) {
  const idx = _aeSelectedKeys.indexOf(String(objectKey || ''));
  if (idx >= 0) _aeSelectedKeys.splice(idx, 1);
  _aeRenderSelectedSources();
  if (_aeUploadListVisible) aeLoadUploadList();
}

function aeMoveVideo(objectKey, delta) {
  const idx = _aeSelectedKeys.indexOf(String(objectKey || ''));
  if (idx < 0) return;
  const next = idx + Number(delta || 0);
  if (next < 0 || next >= _aeSelectedKeys.length) return;
  const [item] = _aeSelectedKeys.splice(idx, 1);
  _aeSelectedKeys.splice(next, 0, item);
  _aeRenderSelectedSources();
}

function aeClearSelection() {
  _aeSelectedKeys.splice(0, _aeSelectedKeys.length);
  _aeRenderSelectedSources();
  if (_aeUploadListVisible) aeLoadUploadList();
}

async function aeUploadVideo() {
  const fileInput = qs('aeVideoFile');
  if (!fileInput?.files?.length) return;
  const file = fileInput.files[0];
  qs('aeVideoInfo').textContent = `⏳ Enviando ${file.name}...`;
  try {
    const result = await _uploadViaProxy(file, {
      prefix: 'uploads',
      validateVideo: true,
      deleteIfInvalid: true,
    });
    if (result?.object_key) {
      _aeUploadsCache.set(String(result.object_key || ''), {
        object_key: result.object_key,
        filename: file.name,
        size_mb: ((file.size || 0) / 1024 / 1024).toFixed(1),
      });
      aeSelectVideo(result.object_key);
      toast('Upload concluído', 'good');
    }
  } catch (e) {
    qs('aeVideoInfo').textContent = `Erro: ${e.message}`;
    toast(e.message, 'bad');
  }
  fileInput.value = '';
}

async function aeStartJob() {
  const objectKeys = _aeSelectedKeys.slice();
  if (!objectKeys.length) return toast('Selecione ao menos um vídeo primeiro', 'bad');

  const payload = {
    video_object_key: objectKeys[0],
    video_object_keys: objectKeys,
    creator_id: qs('aeCreator')?.value || null,
    title_hint: qs('aeTitleHint')?.value?.trim() || null,
    max_scenes: parseInt(qs('aeMaxScenes')?.value || '60', 10),
    output_crf: parseInt(qs('aeCrf')?.value || '23', 10),
    output_max_height: parseInt(qs('aeMaxHeight')?.value || '1080', 10),
    output_max_fps: parseInt(qs('aeMaxFps')?.value || '30', 10),
    scene_threshold: parseFloat(qs('aeSceneThreshold')?.value || '0.32'),
    min_scene_duration_sec: parseFloat(qs('aeMinScene')?.value || '3'),
    max_scene_duration_sec: parseFloat(qs('aeMaxScene')?.value || '150'),
    audio_normalize: aeIsOn('aeAudioNormBtn'),
    audio_denoise: aeIsOn('aeAudioDenoiseBtn'),
    llm_select: aeIsOn('aeLlmSelectBtn'),
    skip_transcription: aeIsOn('aeSkipTranscriptionBtn'),
    delete_source_on_success: aeIsOn('aeDeleteSourceBtn'),
    transition_mode: qs('aeTransitionMode')?.value || 'smart',
    crossfade_video_sec: parseFloat(qs('aeCrossfadeVideo')?.value || '0.5'),
    crossfade_audio_sec: parseFloat(qs('aeCrossfadeAudio')?.value || '0.3'),
    transition_type: qs('aeTransitionType')?.value || 'fade',
    smart_cut_tolerance_sec: parseFloat(qs('aeSmartTolerance')?.value || '1.5'),
  };

  qs('btnAeStart').disabled = true;
  qs('btnAeStart').textContent = '⏳ Processando…';
  aeProgress.start([
    { pct: 8, label: '📥 Baixando vídeos de origem…', minMs: 3000 },
    { pct: 20, label: '🧩 Unindo as fontes selecionadas…', minMs: 6000 },
    { pct: 34, label: '👁️ Rodando Analyze / Vision…', minMs: 14000 },
    { pct: 50, label: '🎬 Detectando cenas e trechos relevantes…', minMs: 12000 },
    { pct: 68, label: '🤖 IA escolhendo o melhor material…', minMs: 16000 },
    { pct: 84, label: '✂️ Cortando e aplicando transições…', minMs: 30000 },
    { pct: 96, label: '🎞️ Finalizando exportação…', minMs: 6000 },
  ]);

  aeStopPolling();
  try {
    const r = await apiFetch('/api/auto-editor/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    _aeCurrentJobId = r.job_id || '';
    toast('Job iniciado: ' + (_aeCurrentJobId || '').slice(0, 8), 'good');
    _aePollStatus(_aeCurrentJobId);
  } catch (e) {
    aeProgress.error('✗ ' + e.message);
    toast(e.message, 'bad');
    qs('btnAeStart').disabled = false;
    qs('btnAeStart').textContent = '🎬 Iniciar AutoEditor';
  }
}

function autoEditorStart() { return aeStartJob(); }

// Pipeline stages mapping for visual display
const AE_PIPELINE_STAGES = [
  { key: 'download',   label: 'Download',      icon: '⬇' },
  { key: 'analyze',    label: 'Vision IA',      icon: '👁' },
  { key: 'detect',     label: 'Detecção',       icon: '◉' },
  { key: 'select',     label: 'Seleção Grok',   icon: '◈' },
  { key: 'cut',        label: 'Corte',          icon: '✂' },
  { key: 'subtitle',   label: 'Legenda',        icon: '▣' },
  { key: 'logo',       label: 'Logo',           icon: '□' },
  { key: 'render',     label: 'Render',         icon: '▶' },
  { key: 'publish',    label: 'Publicar',       icon: '⬢' },
];

function _aeRenderPipeline(job) {
  const wrap = qs('aePipelineWrap');
  const row = qs('aePipelineRow');
  const detail = qs('aeStepDetail');
  if (!wrap || !row) return;

  if (!job || (job.status !== 'running' && job.status !== 'pending' && job.status !== 'done')) {
    wrap.classList.remove('visible');
    return;
  }

  wrap.classList.add('visible');

  // Infer current stage from detail text
  const detailTxt = String(job.detail || '').toLowerCase();
  let currentStageIdx = -1;
  if (job.status === 'done') currentStageIdx = AE_PIPELINE_STAGES.length;
  else if (detailTxt.includes('baixando') || detailTxt.includes('download')) currentStageIdx = 0;
  else if (detailTxt.includes('vision') || detailTxt.includes('analyze') || detailTxt.includes('analiz')) currentStageIdx = 1;
  else if (detailTxt.includes('detect') || detailTxt.includes('cenas') || detailTxt.includes('frame')) currentStageIdx = 2;
  else if (detailTxt.includes('selecion') || detailTxt.includes('grok') || detailTxt.includes('escolh')) currentStageIdx = 3;
  else if (detailTxt.includes('cort') || detailTxt.includes('cut') || detailTxt.includes('transi')) currentStageIdx = 4;
  else if (detailTxt.includes('legenda') || detailTxt.includes('subtitle') || detailTxt.includes('srt')) currentStageIdx = 5;
  else if (detailTxt.includes('logo') || detailTxt.includes('marca')) currentStageIdx = 6;
  else if (detailTxt.includes('render') || detailTxt.includes('export') || detailTxt.includes('finaliz')) currentStageIdx = 7;
  else if (detailTxt.includes('public')) currentStageIdx = 8;
  else if (job.status === 'running') currentStageIdx = 0;

  let html = '';
  AE_PIPELINE_STAGES.forEach((stage, i) => {
    const isDone = i < currentStageIdx;
    const isRun = i === currentStageIdx;
    const cls = isDone ? 'done' : isRun ? 'run' : '';
    const connDone = i < currentStageIdx;
    const connRun = i === currentStageIdx;
    html += `<div class="ae-pnode ${cls}"><div class="ae-pball">${stage.icon}</div><b>${stage.label}</b><small>${isDone ? 'ok' : isRun ? 'rodando' : 'na fila'}</small></div>`;
    if (i < AE_PIPELINE_STAGES.length - 1) {
      html += `<div class="ae-pconn ${connDone ? 'done' : connRun ? 'run' : ''}"></div>`;
    }
  });
  row.innerHTML = html;

  if (detail) {
    if (job.detail) { detail.textContent = job.detail; detail.classList.add('visible'); }
    else { detail.classList.remove('visible'); }
  }
}

async function _aePollStatus(jobId) {
  if (!jobId) return;
  aeStopPolling();
  _aePollTimer = setInterval(async () => {
    try {
      const r = await apiFetch(`/api/auto-editor/status/${jobId}`);
      _aeCurrentJobId = jobId;
      _aeJobsCache.set(jobId, r);
      if (r.detail) qs('aeProgressLabel').textContent = r.detail;
      _aeRenderPipeline(r);
      _aeShowResult(r);

      if (r.status === 'done') {
        aeStopPolling();
        aeProgress.complete('✓ Edição concluída!');
        qs('btnAeStart').disabled = false;
        qs('btnAeStart').textContent = '🎬 Iniciar AutoEditor';
        aeLoadJobs();
        toast('AutoEditor concluído!', 'good');
      } else if (r.status === 'error') {
        aeStopPolling();
        aeProgress.error('✗ ' + (r.detail || r.error || 'Erro'));
        qs('btnAeStart').disabled = false;
        qs('btnAeStart').textContent = '🎬 Iniciar AutoEditor';
        toast(r.detail || 'Erro', 'bad');
        aeLoadJobs();
      }
    } catch (e) {
      // erro transitório: mantém polling
    }
  }, 3000);
}

function _aeShowResult(job) {
  if (!job) return;
  _aeCurrentJobId = job.job_id || _aeCurrentJobId;
  qs('aeResultEmpty')?.classList.add('hidden');
  qs('aeResultContent')?.classList.remove('hidden');

  const preview = qs('aePreviewVideo');
  if (preview) {
    if (job.result_video_url) {
      preview.src = job.result_video_url;
    } else {
      preview.removeAttribute('src');
      preview.load();
    }
  }

  const inp = job.input_probe || {};
  const out = job.output_probe || {};
  const sourceKeys = Array.isArray(job.source_video_keys) && job.source_video_keys.length
    ? job.source_video_keys
    : (job.source_video_key ? [job.source_video_key] : []);
  const inMin = ((inp.duration_seconds || 0) / 60).toFixed(1);
  const outMin = ((out.duration_seconds || 0) / 60).toFixed(1);
  const scenes = job.selected_scenes || [];
  const vision = job.vision_analysis || {};
  const visionDebug = job.vision_debug || {};

  qs('aeResultMeta').innerHTML = [
    `<b>Status:</b> ${esc(job.status || '-')}`,
    `<b>Fontes:</b> ${esc(sourceKeys.length || 0)} vídeo(s)`,
    `<b>Entrada:</b> ${inMin} min · ${inp.width || '?'}x${inp.height || '?'} · ${inp.fps || '?'}fps`,
    `<b>Áudio entrada:</b> ${inp.has_audio === false ? 'sem áudio' : 'com áudio'}`,
    `<b>Saída:</b> ${outMin} min · ${out.width || '?'}x${out.height || '?'}`,
    `<b>Áudio saída:</b> ${out.has_audio === false ? 'sem áudio' : 'com áudio'}`,
    `<b>Cenas:</b> ${scenes.length} selecionadas`,
    `<b>Método:</b> ${esc(job.selection_method || '?')}`,
    job.detail ? `<b>Detalhe:</b> ${esc(job.detail)}` : '',
  ].filter(Boolean).join('<br>');

  const visionSummary = qs('aeVisionSummary');
  if (visionSummary) {
    const categories = Array.isArray(vision.categories) ? vision.categories.slice(0, 8) : [];
    const desc = String(vision.description || '').trim();
    const visionScenes = Array.isArray(vision.scenes) ? vision.scenes.length : 0;
    const visionSources = Array.isArray(vision.sources) ? vision.sources.length : 0;
    if (desc || categories.length || visionScenes) {
      visionSummary.innerHTML = [
        '<b>Vision usada nesta execução</b>',
        visionSources ? `Fontes analisadas separadamente: ${esc(String(visionSources))}` : '',
        desc ? esc(desc) : '',
        categories.length ? `Categorias: ${esc(categories.join(', '))}` : '',
        visionScenes ? `Frames/cenas relevantes detectados: ${esc(visionScenes)}` : '',
      ].filter(Boolean).join('<br>');
      visionSummary.style.display = '';
    } else if (visionDebug.analysis_error || visionDebug.skipped_reason || visionDebug.error) {
      visionSummary.innerHTML = `<b>Vision</b><br>${esc(visionDebug.analysis_error || visionDebug.skipped_reason || visionDebug.error)}`;
      visionSummary.style.display = '';
    } else {
      visionSummary.innerHTML = '';
      visionSummary.style.display = 'none';
    }
  }

  const list = qs('aeScenesList');
  if (list) {
    list.innerHTML = scenes.map(s => {
      const sourceStart = s.source_start != null ? s.source_start : s.start;
      const sourceEnd = s.source_end != null ? s.source_end : s.end;
      const start = _fmtTime(sourceStart);
      const end = _fmtTime(sourceEnd);
      const dur = (s.duration || 0).toFixed(1);
      const score = (s.score || 0).toFixed(2);
      const barW = Math.min(100, (s.score || 0) * 100);
      const sourceLabel = s.source_label || (s.source_video_key ? String(s.source_video_key).split('/').pop() : '');
      const visionLine = s.vision_excerpt ? `<div style="font-size:11px;color:var(--muted);margin-top:2px;">Vision: ${esc(s.vision_excerpt)}</div>` : '';
      return `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:12px;">
        <span style="color:var(--muted);min-width:24px;">#${esc(s.scene_index)}</span>
        <div style="flex:1;min-width:0;">
          <div style="display:flex;gap:8px;align-items:center;">
            <span style="min-width:120px;">${esc(start)} → ${esc(end)}</span>
            <span style="color:var(--muted);min-width:50px;">${esc(dur)}s</span>
            <span style="color:var(--muted);min-width:44px;">V ${esc(((s.vision_relevance || 0) * 100).toFixed(0))}%</span>
          </div>
          ${sourceLabel ? `<div style="font-size:11px;color:var(--muted);margin-top:2px;">Fonte: ${esc(sourceLabel)}</div>` : ''}
          <div style="flex:1;height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;margin-top:4px;">
            <div style="width:${barW}%;height:100%;background:var(--pri);border-radius:2px;"></div>
          </div>
          ${visionLine}
        </div>
        <span style="color:var(--muted);min-width:36px;text-align:right;">${esc(score)}</span>
      </div>`;
    }).join('') || '<div class="hint">Nenhuma cena disponível.</div>';
  }

  qs('aeResultContent').dataset.objectKey = job.result_video_object_key || '';
}

function _fmtTime(sec) {
  const m = Math.floor((sec || 0) / 60);
  const s = Math.floor((sec || 0) % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

async function aeDownloadResult() {
  const key = qs('aeResultContent')?.dataset?.objectKey;
  if (!key) return toast('Nenhum resultado disponível', 'bad');
  try {
    const r = await apiFetch(`/api/video-download-url?object_key=${encodeURIComponent(key)}&filename=${encodeURIComponent('autoeditor_final')}`);
    if (r.url) window.open(r.url, '_blank');
  } catch (e) {
    toast(e.message, 'bad');
  }
}

async function aeRecut() {
  if (!_aeCurrentJobId) return toast('Nenhum job selecionado.', 'bad');
  const btn = qs('btnAeRecut');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Iniciando re-cut…'; }
  try {
    const r = await apiFetch(`/api/auto-editor/recut/${_aeCurrentJobId}`, { method: 'POST' });
    if (!r?.job_id) throw new Error('Sem job_id na resposta');
    toast('Re-cut iniciado: ' + r.job_id.slice(0, 8), 'good');
    _aeCurrentJobId = r.job_id;
    _aeJobsCache.set(r.job_id, r);
    _aePollStatus(r.job_id);
    aeLoadJobs();
  } catch (e) {
    toast(e.message, 'bad');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✂️ Re-cut'; }
  }
}

function aeCopyObjectKey() {
  const key = qs('aeResultContent')?.dataset?.objectKey || '';
  if (!key) return toast('Nenhum object key disponível', 'bad');
  navigator.clipboard.writeText(key).then(() => toast('Key copiada!', 'good'));
}

async function aeSelectJob(jobId) {
  const cached = _aeJobsCache.get(jobId);
  if (cached) { _aeShowResult(cached); _aeRenderPipeline(cached); }
  if (!jobId) return;
  if (cached?.status === 'pending' || cached?.status === 'running') {
    _aePollStatus(jobId);
    return;
  }
  try {
    const fresh = await apiFetch(`/api/auto-editor/status/${jobId}`);
    _aeJobsCache.set(jobId, fresh);
    _aeShowResult(fresh);
    _aeRenderPipeline(fresh);
    if (fresh.status === 'pending' || fresh.status === 'running') _aePollStatus(jobId);
  } catch (e) {
    toast(e.message, 'bad');
  }
}

async function aeLoadPrompt() {
  const el = document.getElementById('aePromptEditor');
  const status = document.getElementById('aePromptStatus');
  if (!el) return;
  try {
    const r = await apiFetch('/api/auto-editor/config');
    el.value = r.narrative_rules || '';
    if (status) status.textContent = r.is_custom ? '✎ Prompt personalizado ativo' : 'Usando prompt padrão do sistema';
  } catch (e) {
    if (status) status.textContent = 'Erro ao carregar: ' + e.message;
  }
}

async function aeSavePrompt() {
  const el = document.getElementById('aePromptEditor');
  const status = document.getElementById('aePromptStatus');
  if (!el) return;
  const rules = el.value.trim();
  if (!rules) return toast('Prompt não pode ser vazio', 'bad');
  try {
    await apiFetch('/api/auto-editor/config', { method: 'PUT', body: JSON.stringify({ narrative_rules: rules }) });
    if (status) status.textContent = '✓ Salvo — será usado no próximo job/recut';
    toast('Prompt salvo!', 'good');
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function aeResetPrompt() {
  const el = document.getElementById('aePromptEditor');
  const status = document.getElementById('aePromptStatus');
  if (!el) return;
  if (!confirm('Resetar para o prompt padrão do sistema?')) return;
  try {
    const r = await apiFetch('/api/auto-editor/config', { method: 'DELETE' });
    el.value = r.narrative_rules || '';
    if (status) status.textContent = 'Prompt padrão restaurado';
    toast('Prompt resetado', 'good');
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function aeLoadJobs() {
  const area = qs('aeJobsList');
  if (!area) return;
  try {
    const r = await apiFetch('/api/auto-editor/jobs?limit=20');
    const jobs = r.jobs || [];
    _aeJobsCache.clear();
    jobs.forEach(j => _aeJobsCache.set(j.job_id, j));
    if (!jobs.length) {
      area.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px;">Nenhum job ainda.</div>';
      return;
    }
    area.innerHTML = jobs.map(j => {
      const statusColor = j.status === 'done' ? 'var(--ok)' : j.status === 'error' ? 'var(--bad)' : 'var(--muted)';
      const inDur = ((j.input_probe?.duration_seconds || 0) / 60).toFixed(1);
      const outDur = ((j.output_probe?.duration_seconds || 0) / 60).toFixed(1);
      const scenes = (j.selected_scenes || []).length;
      const sourceCount = Array.isArray(j.source_video_keys) && j.source_video_keys.length
        ? j.source_video_keys.length
        : (j.source_video_key ? 1 : 0);
      const date = (j.created_at || '').slice(0, 16).replace('T', ' ');
      const title = j.request?.title_hint || j.source_video_key?.split('/').pop() || (j.job_id || '').slice(0, 8);
      const method = j.selection_method || '?';
      return `<div class="item" onclick="aeSelectJob('${escAttr(j.job_id || '')}')">
        <div style="flex:1;min-width:0;">
          <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(title)}</div>
          <div style="font-size:11px;color:var(--muted);">
            ${esc(sourceCount)} fonte(s) · ${esc(inDur)}min → ${esc(outDur)}min · ${esc(scenes)} cenas · ${esc(method)} · ${esc(date)}
          </div>
        </div>
        <span style="color:${statusColor};font-size:12px;font-weight:bold;">${esc(j.status || '-')}</span>
      </div>`;
    }).join('');
  } catch (e) {
    area.innerHTML = `<div style="color:var(--bad);padding:8px;">${esc(e.message)}</div>`;
  }
}

async function autoEditorCheckStatus() {
  if (!_aeCurrentJobId) return toast('Nenhum job selecionado.', 'bad');
  return aeSelectJob(_aeCurrentJobId);
}

// ═══════════════════════════════════════════════════════════════════════════
// MODULE 2: PUBLISHER
// ═══════════════════════════════════════════════════════════════════════════

async function publisherLoad() {
  if (!agencyState.creators.length) {
    const data = await agencyFetch('/api/creators').catch(() => ({ creators: [] }));
    agencyState.creators = data.creators || [];
    populateCreatorDropdowns(agencyState.creators);
  }
}

function publisherSetCreator(id) {
  const sel = document.getElementById('pub_creator');
  if (sel) sel.value = id;
}

async function publisherPublish() {
  const creator_id = document.getElementById('pub_creator').value;
  const video_object_key = document.getElementById('pub_video_key').value.trim();
  const title = document.getElementById('pub_title').value.trim();
  const description = document.getElementById('pub_desc').value.trim();
  const category = document.getElementById('pub_category').value.trim() || 'Amateur';
  const tags = (document.getElementById('pub_tags').value || '').split(',').map(s => s.trim()).filter(Boolean);
  const platforms = [...document.querySelectorAll('input[name="pub_plat"]:checked')].map(c => c.value);
  const statusDiv = document.getElementById('pub_status');

  if (!creator_id || !video_object_key || !platforms.length) {
    toast('Criador, vídeo e pelo menos uma plataforma são obrigatórios.', 'bad');
    return;
  }

  statusDiv.textContent = '⏳ Iniciando publicação...';
  try {
    const result = await agencyFetch('/api/publisher/publish', {
      method: 'POST',
      body: JSON.stringify({ creator_id, video_object_key, platforms, metadata: { title, description, tags, category } }),
    });
    document.getElementById('pub_job_id').value = result.job_id;
    toast('Publicação iniciada!', 'good');
    // Auto-poll progress
    _publisherPollJob(result.job_id, statusDiv);
  } catch (e) {
    statusDiv.innerHTML = `<span style="color:var(--pri)">❌ Erro: ${e.message}</span>`;
  }
}

async function _publisherPollJob(jobId, statusDiv) {
  const resultDiv = document.getElementById('pub_job_result');
  while (true) {
    try {
      const status = await agencyFetch(`/api/publisher/status/${jobId}`);
      const pct = status.progress_pct ?? 0;
      const detail = status.detail || status.status;
      const isDone = ['done', 'error', 'failed'].includes(status.status);
      // Progress bar
      statusDiv.innerHTML = `
        <div style="font-size:13px;margin-bottom:6px">${detail}</div>
        <div style="background:#1a1a1a;border-radius:6px;height:8px;overflow:hidden;margin-bottom:8px">
          <div style="height:100%;background:${status.status==='error'?'#c44':'#00dcdc'};width:${pct}%;transition:width .4s"></div>
        </div>
        <div style="font-size:11px;color:#888">${pct}% — Job: ${jobId}</div>
      `;
      if (isDone) {
        _publisherRenderResult(status, resultDiv);
        break;
      }
    } catch (e) {
      statusDiv.innerHTML = `<span style="color:var(--pri)">Erro ao verificar: ${e.message}</span>`;
      break;
    }
    await new Promise(r => setTimeout(r, 4000));
  }
}

function _publisherRenderResult(status, resultDiv) {
  const platformsHtml = Object.entries(status.platforms || {}).map(([p, r]) => {
    const color = r.status === 'done' ? '#2a9d5c' : r.status === 'error' ? '#c44' : '#f9a825';
    return `<div style="padding:6px 0;border-bottom:1px solid #222">
      <strong style="color:${color}">${p}</strong>: ${r.status}
      ${r.video_url ? `· <a href="${r.video_url}" target="_blank" style="color:var(--pri)">Ver vídeo ↗</a>` : ''}
      ${r.error ? `<div style="color:#c44;font-size:11px">${r.error}</div>` : ''}
    </div>`;
  }).join('');
  resultDiv.innerHTML = `<strong>Status:</strong> ${status.status} — ${status.detail || ''}<br>${platformsHtml}`;
}

async function publisherCheckStatus() {
  const jobId = document.getElementById('pub_job_id').value.trim();
  const resultDiv = document.getElementById('pub_job_result');
  const statusDiv = document.getElementById('pub_status');
  if (!jobId) return;
  try {
    const status = await agencyFetch(`/api/publisher/status/${jobId}`);
    _publisherRenderResult(status, resultDiv);
    if (statusDiv) {
      statusDiv.innerHTML = `<strong>${status.detail || status.status}</strong> — ${status.progress_pct ?? 0}%`;
    }
  } catch (e) {
    resultDiv.innerHTML = `<span style="color:var(--pri)">Erro: ${e.message}</span>`;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// MODULE 4: TRENDS
// ═══════════════════════════════════════════════════════════════════════════

async function trendsLoad() {
  // Load companies for AI trends selector
  try {
    const r = await apiFetch('/api/companies');
    const companies = r.companies || [];
    const sel = qs('trendsCompanySelector');
    if (sel) {
      _trendsCompanies = companies;
      if (!companies.length) {
        sel.innerHTML = '<span style="color:var(--muted)">Cadastre uma empresa primeiro. <a href="#clientes" data-route="clientes" style="color:var(--pri)">Ir para clientes →</a></span>';
      } else {
        sel.innerHTML = companies.map((c, i) =>
          `<button class="btn ${i === 0 ? 'primary' : ''}" data-comp="${c.id}" onclick="trendsSelectCompany('${c.id}')">${esc(c.name)}</button>`
        ).join('');
        _trendsSelectedCompany = companies[0].id;
      }
    }
    // load latest report for first company
    if (_trendsSelectedCompany) trendsLoadReport(_trendsSelectedCompany);
  } catch (e) { console.error('trendsLoad companies:', e); }

  // Existing: load creators for briefing system
  if (!agencyState.creators.length) {
    const data = await agencyFetch('/api/creators').catch(() => ({ creators: [] }));
    agencyState.creators = data.creators || [];
    populateCreatorDropdowns(agencyState.creators);
  }
  trendsLoadBriefings();
}

let _trendsCompanies = [];
let _trendsSelectedCompany = null;

function trendsSelectCompany(id) {
  _trendsSelectedCompany = id;
  document.querySelectorAll('#trendsCompanySelector .btn').forEach(b => {
    b.classList.toggle('primary', b.dataset.comp === id);
  });
  trendsLoadReport(id);
}

async function trendsLoadReport(companyId) {
  try {
    const r = await apiFetch(`/api/posts/trends/${companyId}`);
    const el = qs('trendsReport');
    if (!el) return;
    const report = r.report;
    const aiEnabled = r.ai_enabled;
    const genBtn = qs('trendsGenBtn');
    if (genBtn) genBtn.textContent = report ? 'Atualizar tendências' : 'Gerar tendências';
    if (!aiEnabled) {
      el.innerHTML = `<div class="card" style="color:var(--muted)">Configure a IA primeiro → <a href="#settings" data-route="settings" style="color:var(--pri)">Configurações</a></div>`;
      return;
    }
    if (!report) {
      el.innerHTML = '<div class="card" style="color:var(--muted);text-align:center;padding:24px">Nenhum briefing gerado ainda.</div>';
      return;
    }
    const p = report.payload || {};
    const themes = p.themes || [];
    const hashtags = p.hashtags || [];
    el.innerHTML = `<div class="card">
      <h2>Briefing gerado em ${new Date(report.created_at).toLocaleString('pt-BR')}</h2>
      <p style="margin-top:12px;color:var(--text2)">${esc(p.summary || '')}</p>
      ${hashtags.length ? `<div style="margin-top:12px;color:var(--accent);font-size:13px">${esc(hashtags.join(' '))}</div>` : ''}
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-top:16px">
      ${themes.map((t, i) => `<div class="card">
        <div style="display:flex;gap:8px;align-items:center">
          <span style="font-size:20px;font-weight:700;color:var(--pri)">${i + 1}</span>
          <strong>${esc(t.title || '')}</strong>
        </div>
        <p style="margin-top:8px;font-size:13px;color:var(--text2)">${esc(t.why || '')}</p>
        ${t.formats && t.formats.length ? `<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${t.formats.map(f => `<span class="badge">${esc(f.toUpperCase())}</span>`).join('')}</div>` : ''}
        ${t.example ? `<div style="margin-top:12px;padding:12px;border:1px solid var(--line);border-radius:8px;font-size:13px;color:var(--muted)">${esc(t.example)}</div>` : ''}
        <button class="btn" style="margin-top:12px" onclick="clienteDetail('${_trendsSelectedCompany}','gerar')">Virar post →</button>
      </div>`).join('')}
    </div>`;
  } catch (e) {
    console.error('trendsLoadReport:', e);
  }
}

async function trendsGenerateAI() {
  if (!_trendsSelectedCompany) { toast('Selecione uma empresa.', 'bad'); return; }
  const btn = qs('trendsGenBtn');
  const status = qs('trendsAIStatus');
  if (btn) btn.disabled = true;
  if (status) status.textContent = 'Gerando (até 1 min)...';
  try {
    await apiFetch(`/api/posts/trends/${_trendsSelectedCompany}/generate`, { method: 'POST', body: '{}' });
    if (status) status.textContent = '';
    await trendsLoadReport(_trendsSelectedCompany);
    toast('Briefing gerado!', 'good');
  } catch (e) {
    if (status) status.textContent = '';
    toast('Erro: ' + e.message, 'bad');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function trendsCollect() {
  try {
    await agencyFetch('/api/trends/collect', { method: 'POST', body: '{}' });
    toast('Coleta de tendências globais iniciada!', 'good');
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function trendsCollectChannels() {
  const creator_id = document.getElementById('trends_creator')?.value;
  if (!creator_id) { toast('Selecione um criador.', 'bad'); return; }
  try {
    const result = await agencyFetch(`/api/trends/collect-channels/${creator_id}`, { method: 'POST', body: '{}' });
    trendsJobStart(result.job_id, `📡 Coletando ${result.channels} canal(is)…`);
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function trendsGenerateBriefingJob() {
  const creator_id = document.getElementById('trends_creator')?.value;
  if (!creator_id) { toast('Selecione um criador.', 'bad'); return; }
  try {
    const result = await agencyFetch(`/api/trends/generate-briefing-job/${creator_id}`, { method: 'POST', body: '{}' });
    trendsJobStart(result.job_id, '🤖 Gerando briefing com Grok…');
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

// ── Job progress panel ────────────────────────────────────────────────────────
let _trendsJobId = null;
let _trendsJobInterval = null;
let _trendsBriefingId = null;

function trendsJobStart(jobId, title) {
  _trendsJobId = jobId;
  _trendsBriefingId = null;
  document.getElementById('trendsJobTitle').textContent = title;
  document.getElementById('trendsJobSteps').innerHTML = '';
  document.getElementById('trendsApprovalPanel').style.display = 'none';
  document.getElementById('trendsJobPanel').style.display = 'block';
  document.getElementById('trendsJobPanel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  clearInterval(_trendsJobInterval);
  _trendsJobInterval = setInterval(trendsJobPoll, 2500);
  trendsJobPoll();
}

async function trendsJobPoll() {
  if (!_trendsJobId) return;
  try {
    const job = await agencyFetch(`/api/trends/job/${_trendsJobId}`);
    trendsJobRender(job);
    if (['done', 'error', 'awaiting_approval'].includes(job.status)) {
      clearInterval(_trendsJobInterval);
      _trendsJobInterval = null;
      if (job.status === 'awaiting_approval' && job.briefing_id) {
        _trendsBriefingId = job.briefing_id;
        document.getElementById('trendsApprovalPanel').style.display = 'block';
        // show briefing preview
        if (job.briefing) trendsShowBriefing(job.briefing);
        trendsLoadBriefings();
      }
      if (job.status === 'done') trendsLoadBriefings();
    }
  } catch (e) {
    clearInterval(_trendsJobInterval);
  }
}

function trendsJobRender(job) {
  const steps = job.steps || [];
  const statusIcon = { done: '✅', running: '⏳', error: '❌', awaiting_approval: '👁' };
  const statusColor = { done: '#2a9d5c', running: '#4fc3f7', error: '#c44', awaiting_approval: '#f9a825' };

  // Progress bar for channel collection
  let progressHtml = '';
  if (job.type === 'collect_channels' && job.channels_total) {
    const pct = Math.round((job.channels_done / job.channels_total) * 100);
    progressHtml = `
      <div style="margin:10px 0">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#666;margin-bottom:4px">
          <span>Canais</span><span>${job.channels_done}/${job.channels_total} — ${job.videos_found || 0} vídeos coletados</span>
        </div>
        <div style="background:#1a1a1a;border-radius:4px;height:6px">
          <div style="background:#4fc3f7;height:6px;border-radius:4px;width:${pct}%;transition:width .4s"></div>
        </div>
      </div>`;
  }

  const stepsHtml = steps.map((s, i) => {
    const icon = statusIcon[s.status] || '⏳';
    const color = statusColor[s.status] || '#aaa';
    const isLast = i === steps.length - 1;
    return `<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 0;${i < steps.length - 1 ? 'border-bottom:1px solid #1a1a1a' : ''}">
      <span style="font-size:14px;margin-top:1px">${icon}</span>
      <div style="flex:1">
        <div style="font-size:13px;color:${isLast && s.status === 'running' ? '#ccc' : color};${isLast && s.status === 'running' ? 'animation:pulse 1.5s infinite' : ''}">${s.label}</div>
        ${s.ts ? `<div style="font-size:10px;color:#444;margin-top:2px">${s.ts.slice(11, 19)}</div>` : ''}
      </div>
    </div>`;
  }).join('');

  document.getElementById('trendsJobSteps').innerHTML = progressHtml + stepsHtml;
}

function trendsJobClear() {
  clearInterval(_trendsJobInterval);
  _trendsJobInterval = null;
  _trendsJobId = null;
  _trendsBriefingId = null;
  document.getElementById('trendsJobPanel').style.display = 'none';
  document.getElementById('trendsLatest').innerHTML = '';
}

async function trendsApproveBriefing(notify) {
  if (!_trendsBriefingId) return;
  try {
    await agencyFetch(`/api/trends/approve-briefing/${_trendsBriefingId}`, {
      method: 'POST',
      body: JSON.stringify({ notify }),
    });
    toast(notify ? '✅ Briefing aprovado e criador notificado!' : '✅ Briefing aprovado (sem notificação)', 'good');
    trendsJobClear();
    trendsLoadBriefings();
  } catch (e) {
    toast('Erro ao aprovar: ' + e.message, 'bad');
  }
}

// trendsGenerateBriefing mantida para compatibilidade com botões antigos
async function trendsGenerateBriefing() {
  trendsGenerateBriefingJob();
}

async function trendsLoadBriefings() {
  const div = document.getElementById('briefingsList');
  if (!div) return;
  const creator_id = document.getElementById('trends_creator')?.value || '';
  const url = creator_id
    ? `/api/trends/briefings?limit=20&creator_id=${creator_id}`
    : '/api/trends/briefings?limit=20';
  try {
    const data = await agencyFetch(url);
    if (!data.briefings?.length) {
      div.innerHTML = '<div class="card" style="color:#555;padding:16px;text-align:center">Nenhum briefing gerado ainda. Selecione um criador e clique em "Gerar Briefing".</div>';
      return;
    }
    const creatorMap = {};
    (agencyState.creators || []).forEach(c => { creatorMap[c.creator_id] = c.name; });
    div.innerHTML = `<h3 style="margin-bottom:12px;color:#aaa">Últimos Briefings (${data.total || data.briefings.length})</h3>` +
      data.briefings.map(b => {
        const content = b.content || {};
        const date = (b.generated_at || '').substring(0, 10);
        const sugg = (content.suggestions || []).length;
        const creatorName = creatorMap[b.creator_id] || b.creator_id || '';
        const hasImagePrompts = (content.suggestions || []).some(s => s.image_prompt);
        return `<div class="card" style="margin-bottom:10px;cursor:pointer;transition:border-color .2s" onmouseenter="this.style.borderColor='#444'" onmouseleave="this.style.borderColor=''" onclick="trendsShowBriefing(${JSON.stringify(b).replace(/"/g,'&quot;')})">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
            <div>
              <strong style="color:#ccc">📊 Briefing ${date}</strong>
              ${creatorName ? `<span style="margin-left:8px;font-size:12px;color:#666">${creatorName}</span>` : ''}
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
              <span style="color:#555;font-size:11px;white-space:nowrap">${sugg} sugestões</span>
              ${hasImagePrompts ? '<span style="font-size:11px;background:#0d0d1a;border:1px solid #2a2a50;color:#7c83e0;padding:1px 6px;border-radius:10px">🖼 prompts IA</span>' : ''}
              ${b.sent_email ? '<span style="font-size:11px;color:#2a9d5c">✉ enviado</span>' : ''}
            </div>
          </div>
          <div style="color:#888;font-size:12px;margin-top:6px;line-height:1.5">${(content.market_summary || '').substring(0, 180)}${(content.market_summary || '').length > 180 ? '...' : ''}</div>
          <div style="margin-top:8px;display:flex;gap:6px">
            <button class="btn" style="font-size:11px;padding:3px 8px" onclick="event.stopPropagation();trendsSendBriefing('${b.briefing_id}')">📧 Email</button>
          </div>
        </div>`;
      }).join('');
  } catch (e) {
    div.innerHTML = `<div style="color:var(--pri)">Erro: ${e.message}</div>`;
  }
}

function trendsShowBriefing(briefing) {
  const content = briefing.content || {};
  const suggestions = (content.suggestions || []);
  const insights = (content.top_channel_insights || []);
  const potentialColor = { low: '#666', medium: '#f9a825', high: '#2a9d5c', viral: '#ff1744' };
  const potentialEmoji = { low: '⬇️', medium: '➡️', high: '⬆️', viral: '🔥' };

  const insightsHtml = insights.length ? `
    <div style="margin-bottom:16px">
      <strong style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#666">📡 Insights dos Canais de Referência</strong>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px;margin-top:10px">
        ${insights.map(ins => `
          <div style="background:#181818;border:1px solid #2a2a2a;border-radius:6px;padding:12px">
            <div style="color:#ccc;font-weight:600;font-size:13px;margin-bottom:4px">${ins.channel || 'Canal'}</div>
            ${ins.best_format ? `<div style="color:#888;font-size:12px">Formato: ${ins.best_format}</div>` : ''}
            ${ins.opportunity ? `<div style="color:#4fc3f7;font-size:12px;margin-top:4px">${ins.opportunity}</div>` : ''}
            ${(ins.top_tags || []).length ? `<div style="margin-top:6px">${ins.top_tags.slice(0,5).map(t=>`<span style="background:#1a2a3a;color:#4fc3f7;font-size:10px;padding:1px 5px;border-radius:3px;margin:1px;display:inline-block">${t}</span>`).join('')}</div>` : ''}
          </div>`).join('')}
      </div>
    </div>` : '';

  const suggestionsHtml = suggestions.map((s, idx) => {
    const imgPrompt = (s.image_prompt || '').replace(/"/g, '&quot;');
    const imgPromptDisplay = (s.image_prompt || '').substring(0, 200) + (s.image_prompt?.length > 200 ? '...' : '');
    return `
      <div style="background:#181818;border:1px solid #2a2a2a;border-radius:6px;padding:14px;margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:8px">
          <strong style="color:var(--pri);line-height:1.4">${potentialEmoji[s.view_potential] || '🟠'} ${s.title || ''}</strong>
          <span style="font-size:11px;color:${potentialColor[s.view_potential] || '#f9a825'};background:rgba(0,0,0,.4);padding:2px 8px;border-radius:10px;white-space:nowrap">${s.view_potential || 'n/a'}</span>
        </div>
        <p style="color:#aaa;font-size:13px;margin-bottom:6px;line-height:1.5">${s.concept || ''}</p>
        ${s.why_trending ? `<p style="color:#f9a825;font-size:12px;margin-bottom:8px;background:#1a1500;padding:6px 10px;border-radius:4px">💡 ${s.why_trending}</p>` : ''}
        <div style="margin-bottom:8px">${(s.tags || []).map(t => `<span style="background:#1a1a2e;color:#7c83e0;font-size:10px;padding:1px 6px;border-radius:3px;margin:1px;display:inline-block">${t}</span>`).join('')}</div>
        ${s.reference_url ? `<a href="${s.reference_url}" target="_blank" style="color:#555;font-size:11px;margin-bottom:8px;display:block">🔗 Ver referência ↗</a>` : ''}
        ${s.image_prompt ? `
          <div style="background:#0d0d1a;border:1px solid #2a2a50;border-radius:6px;padding:10px;margin-top:8px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
              <span style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#5a5a9a">🖼 Prompt Thumbnail IA</span>
              <button class="btn" style="font-size:11px;padding:2px 8px" onclick="trendsCoypImagePrompt(this, '${imgPrompt}')">📋 Copiar</button>
            </div>
            <p style="color:#6a6a8a;font-size:11px;line-height:1.5;font-family:monospace">${imgPromptDisplay}</p>
          </div>` : ''}
      </div>`;
  }).join('');

  const html = `
    <div class="card" style="margin-top:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <h2 style="margin:0">📊 Briefing — ${(briefing.generated_at || '').substring(0, 10)}</h2>
        <button class="btn" style="font-size:12px" onclick="trendsSendBriefing('${briefing.briefing_id}')">📧 Enviar por Email</button>
      </div>
      <div style="background:#1a1a1a;border-left:4px solid var(--pri);padding:12px;margin-bottom:16px;border-radius:0 6px 6px 0">
        <strong style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#666">Resumo do Mercado</strong>
        <p style="color:#bbb;margin-top:6px;line-height:1.6">${content.market_summary || ''}</p>
      </div>
      ${insightsHtml}
      ${suggestions.length ? `<strong style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#666">🎬 Sugestões de Vídeos (${suggestions.length})</strong><div style="margin-top:10px">${suggestionsHtml}</div>` : ''}
      ${content.avoid?.length ? `
        <div style="background:#1a1010;border:1px solid #3a1010;border-radius:6px;padding:12px;margin-top:12px">
          <strong style="color:#c44">⛔ Evitar Esta Semana:</strong>
          <ul style="color:#c44;margin-top:6px;padding-left:16px">${(content.avoid || []).map(a => `<li style="margin-bottom:4px">${a}</li>`).join('')}</ul>
        </div>` : ''}
    </div>`;

  const div = document.getElementById('trendsLatest');
  if (div) div.innerHTML = html;
}

function trendsCoypImagePrompt(btn, prompt) {
  navigator.clipboard.writeText(prompt).then(() => {
    btn.textContent = '✅ Copiado';
    setTimeout(() => { btn.textContent = '📋 Copiar'; }, 2000);
  });
}

async function trendsSendBriefing(briefingId) {
  try {
    await agencyFetch('/api/trends/send-briefing', {
      method: 'POST',
      body: JSON.stringify({ briefing_id: briefingId, channels: ['email'] }),
    });
    toast('Briefing enviado por email!', 'good');
  } catch (e) {
    toast('Erro ao enviar: ' + e.message, 'bad');
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// MODULE 6: CALENDAR
// ═══════════════════════════════════════════════════════════════════════════

async function calendarLoad() {
  if (!agencyState.creators.length) {
    const data = await agencyFetch('/api/creators').catch(() => ({ creators: [] }));
    agencyState.creators = data.creators || [];
    populateCreatorDropdowns(agencyState.creators);
  }
  calendarLoadNext();
}

async function calendarLoadNext() {
  const div = document.getElementById('calendarList');
  if (!div) return;
  try {
    const data = await agencyFetch('/api/calendar/next?days=14');
    if (!data.entries?.length) {
      div.innerHTML = '<div style="color:#555;padding:16px">Nenhuma publicação agendada nos próximos 14 dias.</div>';
      return;
    }
    const statusColor = { scheduled: '#f9a825', publishing: '#4da8da', done: '#2a9d5c', error: '#c44' };
    div.innerHTML = '<h3 style="margin-bottom:12px;color:#aaa">Próximas Publicações (14 dias)</h3>' +
      data.entries.map(e => {
        const dt = new Date(e.publish_at).toLocaleString('pt-BR');
        const color = statusColor[e.status] || '#555';
        return `<div class="card" style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center">
          <div>
            <strong>${e.title || '(sem título)'}</strong><br>
            <span style="font-size:12px;color:#666">${e.publish_platforms?.join(', ')} · ${dt}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <span style="background:${color};color:#fff;font-size:10px;padding:2px 7px;border-radius:10px">${e.status}</span>
            <button class="btn" style="font-size:11px;padding:3px 8px;color:#c44;border-color:#c44"
              onclick="calendarDeleteEntry('${e.entry_id}')">✕</button>
          </div>
        </div>`;
      }).join('');
  } catch (e) {
    div.innerHTML = `<div style="color:var(--pri)">Erro: ${e.message}</div>`;
  }
}

function calendarShowAdd() {
  const form = document.getElementById('calendarAddForm');
  if (!form) return;
  form.classList.remove('hidden');
  // Set default publish time to tomorrow 22:00
  const dt = new Date();
  dt.setDate(dt.getDate() + 1);
  dt.setHours(22, 0, 0);
  const pad = n => String(n).padStart(2, '0');
  document.getElementById('cal_publish_at').value =
    `${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  form.scrollIntoView({ behavior: 'smooth' });
}

async function calendarSaveEntry() {
  const creator_id = document.getElementById('cal_creator').value;
  const video_object_key = document.getElementById('cal_video_key').value.trim();
  const publish_at = document.getElementById('cal_publish_at').value;
  const title = document.getElementById('cal_title').value.trim();
  const platforms = [...document.querySelectorAll('input[name="cal_plat"]:checked')].map(c => c.value);

  if (!creator_id || !video_object_key || !publish_at) {
    toast('Criador, vídeo e data são obrigatórios.', 'bad');
    return;
  }

  try {
    await agencyFetch('/api/calendar', {
      method: 'POST',
      body: JSON.stringify({
        creator_id, video_object_key,
        publish_at: new Date(publish_at).toISOString(),
        publish_platforms: platforms,
        title, cross_promote: true,
        cross_channels: ['telegram'],
      }),
    });
    toast('Publicação agendada!', 'good');
    document.getElementById('calendarAddForm').classList.add('hidden');
    calendarLoadNext();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function calendarDeleteEntry(id) {
  if (!confirm('Cancelar esta publicação?')) return;
  try {
    await agencyFetch(`/api/calendar/${id}`, { method: 'DELETE' });
    toast('Publicação cancelada.', 'good');
    calendarLoadNext();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function calendarAutoSchedule() {
  const creator_id = prompt('ID do criador (cole o creator_id):');
  if (!creator_id) return;
  const keysRaw = prompt('Object keys dos vídeos, separados por vírgula:');
  if (!keysRaw) return;
  const video_keys = keysRaw.split(',').map(s => s.trim()).filter(Boolean);

  try {
    const result = await agencyFetch('/api/calendar/auto-schedule', {
      method: 'POST',
      body: JSON.stringify({ creator_id, video_object_keys: video_keys, period_days: 7 }),
    });
    toast(`${result.created} publicações agendadas automaticamente!`, 'good');
    calendarLoadNext();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// MODULE 7: FINANCIAL
// ═══════════════════════════════════════════════════════════════════════════

async function financialLoad() {
  if (!agencyState.creators.length) {
    const data = await agencyFetch('/api/creators').catch(() => ({ creators: [] }));
    agencyState.creators = data.creators || [];
    populateCreatorDropdowns(agencyState.creators);
  }
  // Set default month to current
  const monthInput = document.getElementById('fin_month');
  if (monthInput && !monthInput.value) {
    const now = new Date();
    monthInput.value = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
  }
}

async function financialAgencyOverview() {
  const card = document.getElementById('financialAgencyCard');
  const dataDiv = document.getElementById('financialAgencyData');
  try {
    const data = await agencyFetch('/api/financial/agency-overview');
    card.classList.remove('hidden');
    dataDiv.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:12px">
        <div style="background:#1a1a1a;border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:22px;color:#2a9d5c;font-weight:bold">R$ ${(data.total_gross_all_creators||0).toFixed(2)}</div>
          <div style="color:#666;font-size:11px">Receita Bruta Total</div>
        </div>
        <div style="background:#1a1a1a;border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:22px;color:var(--pri);font-weight:bold">R$ ${(data.total_agency_commission||0).toFixed(2)}</div>
          <div style="color:#666;font-size:11px">Comissão da Agência</div>
        </div>
        <div style="background:#1a1a1a;border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:22px;color:#4da8da;font-weight:bold">${data.creators_with_earnings||0}</div>
          <div style="color:#666;font-size:11px">Criadores com Receita</div>
        </div>
      </div>
      ${data.top_creators?.length ? `
        <h3 style="color:#aaa;margin:16px 0 8px">Top Criadores</h3>
        ${data.top_creators.map(c => `
          <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1a1a1a;font-size:13px">
            <span>${c.name}</span>
            <span style="color:#2a9d5c">R$ ${c.gross.toFixed(2)}</span>
          </div>`).join('')}` : ''}`;
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function financialCreatorReport() {
  const creator_id = document.getElementById('fin_creator').value;
  const month = document.getElementById('fin_month').value;
  const dataDiv = document.getElementById('financialCreatorData');

  if (!creator_id || !month) {
    toast('Selecione criador e mês.', 'bad');
    return;
  }

  try {
    const report = await agencyFetch(`/api/financial/report/${creator_id}/${month}`);
    dataDiv.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <tr><td style="padding:8px;border:1px solid #222;color:#888">Receita Bruta</td><td style="padding:8px;border:1px solid #222;color:#2a9d5c">R$ ${(report.total_gross||0).toFixed(2)}</td></tr>
        <tr><td style="padding:8px;border:1px solid #222;color:#888">Taxas Plataformas</td><td style="padding:8px;border:1px solid #222;color:#c44">- R$ ${(report.total_platform_fees||0).toFixed(2)}</td></tr>
        <tr><td style="padding:8px;border:1px solid #222;color:#888">Líquido</td><td style="padding:8px;border:1px solid #222">R$ ${(report.total_net||0).toFixed(2)}</td></tr>
        <tr><td style="padding:8px;border:1px solid #222;color:#888">Comissão Agência</td><td style="padding:8px;border:1px solid #222;color:#c44">- R$ ${(report.total_agency_commission||0).toFixed(2)}</td></tr>
        <tr style="background:#1a1a1a"><td style="padding:8px;border:1px solid #222;font-weight:bold">Repasse ao Criador</td><td style="padding:8px;border:1px solid #222;color:var(--pri);font-size:16px;font-weight:bold">R$ ${(report.total_creator_payout||0).toFixed(2)}</td></tr>
        <tr><td style="padding:8px;border:1px solid #222;color:#888">Views no Período</td><td style="padding:8px;border:1px solid #222">${(report.total_views||0).toLocaleString()}</td></tr>
      </table>
      <button class="btn" style="margin-top:10px;font-size:12px" onclick="financialSendReport('${creator_id}','${month}')">📧 Enviar Relatório por Email</button>`;
  } catch (e) {
    dataDiv.innerHTML = `<span style="color:var(--pri)">Erro: ${e.message}</span>`;
  }
}

async function financialSendReport(creator_id, month) {
  try {
    await agencyFetch('/api/financial/generate-report', {
      method: 'POST',
      body: JSON.stringify({ creator_id, month }),
    });
    toast('Relatório enviado!', 'good');
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

function financialShowAddEarning() {
  document.getElementById('financialAddEarningForm')?.classList.remove('hidden');
  // Set current period
  const now = new Date();
  const periodInput = document.getElementById('fe_period');
  if (periodInput) periodInput.value = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
}

async function financialSaveEarning() {
  const creator_id = document.getElementById('fe_creator').value;
  const platform = document.getElementById('fe_platform').value.trim();
  const period = document.getElementById('fe_period').value;
  const gross = parseFloat(document.getElementById('fe_gross').value) || 0;
  const fee_pct = parseFloat(document.getElementById('fe_fee_pct').value) || 0;
  const views = parseInt(document.getElementById('fe_views').value) || 0;

  if (!creator_id || !platform || !period) {
    toast('Criador, plataforma e período são obrigatórios.', 'bad');
    return;
  }

  try {
    await agencyFetch('/api/financial/record-earning', {
      method: 'POST',
      body: JSON.stringify({ creator_id, platform, period, gross_revenue: gross, platform_fee_pct: fee_pct, views_in_period: views }),
    });
    toast('Receita lançada!', 'good');
    document.getElementById('financialAddEarningForm')?.classList.add('hidden');
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// MODULE 5: DMCA
// ═══════════════════════════════════════════════════════════════════════════

async function dmcaLoad() {
  if (!agencyState.creators.length) {
    const data = await agencyFetch('/api/creators').catch(() => ({ creators: [] }));
    agencyState.creators = data.creators || [];
    populateCreatorDropdowns(agencyState.creators);
  }
}

async function dmcaScan() {
  const creator_id = document.getElementById('dmca_creator')?.value;
  const statusDiv = document.getElementById('dmca_scan_status');
  if (!creator_id) { toast('Selecione um criador.', 'bad'); return; }

  statusDiv.textContent = '⏳ Escaneando... (isso pode levar 1-2 minutos)';
  try {
    await agencyFetch('/api/dmca/scan', { method: 'POST', body: JSON.stringify({ creator_id }) });
    statusDiv.textContent = '✅ Scan iniciado em background. Aguarde e recarregue as infrações.';
    toast('DMCA scan iniciado!', 'good');
    setTimeout(dmcaLoadInfringements, 5000);
  } catch (e) {
    statusDiv.innerHTML = `<span style="color:var(--pri)">Erro: ${e.message}</span>`;
  }
}

async function dmcaLoadInfringements() {
  const creator_id = document.getElementById('dmca_creator')?.value;
  const div = document.getElementById('dmcaInfringements');
  if (!div) return;

  try {
    const url = creator_id ? `/api/dmca/infringements?creator_id=${creator_id}` : '/api/dmca/infringements';
    const data = await agencyFetch(url);
    if (!data.infringements?.length) {
      div.innerHTML = '<div style="color:#555;padding:16px">Nenhuma infração detectada.</div>';
      return;
    }
    const statusColor = { detected: '#f9a825', takedown_sent: '#4da8da', removed: '#2a9d5c', ignored: '#555', failed: '#c44' };
    div.innerHTML = '<h3 style="margin-bottom:12px;color:#aaa">Infrações Detectadas (' + data.total + ')</h3>' +
      data.infringements.map(i => `
        <div class="card" style="margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:start">
            <div style="font-size:12px">
              <strong style="color:#aaa">${i.infringing_site}</strong> · ${i.detection_method}<br>
              <a href="${i.infringing_url}" target="_blank" style="color:#4da8da;word-break:break-all">${i.infringing_url}</a>
            </div>
            <span style="background:${statusColor[i.status]||'#555'};color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;white-space:nowrap;margin-left:8px">${i.status}</span>
          </div>
          <div style="margin-top:8px;display:flex;gap:6px">
            ${i.status === 'detected' ? `<button class="btn" style="font-size:11px;padding:3px 8px;color:#c44;border-color:#c44" onclick="dmcaSendTakedown('${i.infringement_id}')">⚖️ Takedown</button>` : ''}
            <button class="btn" style="font-size:11px;padding:3px 8px" onclick="dmcaIgnore('${i.infringement_id}')">Ignorar</button>
          </div>
        </div>`).join('');
  } catch (e) {
    div.innerHTML = `<div style="color:var(--pri)">Erro: ${e.message}</div>`;
  }
}

async function dmcaShowStats() {
  const creator_id = document.getElementById('dmca_creator')?.value;
  const card = document.getElementById('dmcaStatsCard');
  const dataDiv = document.getElementById('dmcaStatsData');
  try {
    const url = creator_id ? `/api/dmca/stats?creator_id=${creator_id}` : '/api/dmca/stats';
    const stats = await agencyFetch(url);
    card.classList.remove('hidden');
    dataDiv.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px;font-size:13px">
        <div style="text-align:center;background:#1a1a1a;padding:10px;border-radius:6px">
          <div style="font-size:24px;color:#f9a825">${stats.total_detected||0}</div>
          <div style="color:#666">Detectadas</div>
        </div>
        <div style="text-align:center;background:#1a1a1a;padding:10px;border-radius:6px">
          <div style="font-size:24px;color:#4da8da">${stats.total_takedown_sent||0}</div>
          <div style="color:#666">Takedowns Enviados</div>
        </div>
        <div style="text-align:center;background:#1a1a1a;padding:10px;border-radius:6px">
          <div style="font-size:24px;color:#2a9d5c">${stats.total_removed||0}</div>
          <div style="color:#666">Removidos</div>
        </div>
      </div>`;
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function dmcaSendTakedown(infringementId) {
  if (!confirm('Enviar DMCA takedown para este site?')) return;
  try {
    const result = await agencyFetch(`/api/dmca/takedown/${infringementId}`, { method: 'POST', body: '{}' });
    if (result.success) {
      toast('Takedown enviado!', 'good');
      dmcaLoadInfringements();
    } else {
      toast('Falha: ' + (result.error || 'erro desconhecido'), 'bad');
    }
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

async function dmcaIgnore(infringementId) {
  try {
    await agencyFetch(`/api/dmca/infringements/${infringementId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'ignored' }),
    });
    toast('Infração marcada como ignorada.', 'good');
    dmcaLoadInfringements();
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
  }
}

// ── Video Enhancer ──────────────────────────────────────────────────────────

let _veSelectedKey = null;
let _veSelectedName = null;
let _vePollTimer = null;

async function veLoad() {
  veLoadJobs();
  veCheckInstall();
}

async function veCheckInstall() {
  const warn = document.getElementById('veInstallWarning');
  try {
    const r = await apiFetch('/api/video-enhancer/check');
    if (warn) warn.style.display = r.ok ? 'none' : 'block';
  } catch (e) {
    if (warn) warn.style.display = 'block';
  }
}

function veToggleUploadList() {
  const el = document.getElementById('veUploadList');
  if (!el) return;
  if (el.classList.contains('hidden')) {
    el.classList.remove('hidden');
    veLoadUploadList();
  } else {
    el.classList.add('hidden');
  }
}

async function veLoadUploadList() {
  const el = document.getElementById('veUploadList');
  if (!el) return;
  el.innerHTML = '<div style="padding:12px;color:var(--muted);text-align:center;font-size:12px;">Carregando...</div>';
  try {
    const data = await apiFetch('/uploads/list?prefix=uploads&max_keys=100');
    const files = data.items || data.files || [];
    if (!files.length) {
      el.innerHTML = '<div style="padding:12px;color:var(--muted);text-align:center;font-size:12px;">Nenhum arquivo encontrado</div>';
      return;
    }
    el.innerHTML = files.map(f => {
      const key = f.object_key || f.key || f.path || '';
      const name = f.filename || f.name || f.object_key?.split('/').pop() || key.split('/').pop();
      return `<div style="padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border);font-size:12px;" 
        onmouseover="this.style.background='#1a1a2e'" onmouseout="this.style.background=''"
        onclick="veSelectVideo('${key.replace(/'/g,"\\'")}','${name.replace(/'/g,"\\'")}')">
        ${name}
      </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div style="padding:12px;color:var(--muted);text-align:center;font-size:12px;">Erro: ${e.message}</div>`;
  }
}

function veSelectVideo(key, name) {
  _veSelectedKey = key;
  _veSelectedName = name;
  const hint = document.getElementById('veSelectedHint');
  if (hint) hint.textContent = '✓ Selecionado: ' + name;
  const list = document.getElementById('veUploadList');
  if (list) list.classList.add('hidden');
}

async function veUploadFile() {
  const input = document.getElementById('veVideoFile');
  if (!input || !input.files.length) return;
  const file = input.files[0];
  const hint = document.getElementById('veSelectedHint');
  if (hint) hint.textContent = '📤 Upload: ' + file.name + ' (pendente — será enviado ao iniciar)';
  _veSelectedKey = null;
  _veSelectedName = file.name;
}

async function veEnhance() {
  const resolution = document.getElementById('veResolution')?.value || '720p';
  const btn = document.getElementById('veBtn');

  // Determine input: file upload or object_key
  const fileInput = document.getElementById('veVideoFile');
  const hasFile = fileInput && fileInput.files.length > 0;

  if (!hasFile && !_veSelectedKey) {
    toast('Selecione um vídeo antes de continuar.', 'bad');
    return;
  }

  if (btn) { btn.disabled = true; btn.textContent = 'Enviando…'; }

  // Show status panel
  const statusEl = document.getElementById('veStatus');
  if (statusEl) statusEl.style.display = 'block';
  _veSetStatus('Enviando para fila…', 0);
  const outputInfo = document.getElementById('veOutputInfo');
  if (outputInfo) outputInfo.style.display = 'none';

  try {
    let data;
    if (hasFile) {
      const fd = new FormData();
      fd.append('file', fileInput.files[0]);
      const res = await fetch(`/api/video-enhancer/enhance?resolution=${resolution}`, {
        method: 'POST',
        headers: { 'X-API-Key': window._apiKey || '' },
        body: fd,
      });
      data = await res.json();
    } else {
      data = await apiFetch('/api/video-enhancer/enhance', {
        method: 'POST',
        body: JSON.stringify({ video_object_key: _veSelectedKey, resolution }),
      });
    }

    if (!data.ok && !data.job_id) {
      toast('Erro: ' + (data.detail || data.error || JSON.stringify(data)), 'bad');
      if (btn) { btn.disabled = false; btn.textContent = '✦ Melhorar Vídeo'; }
      return;
    }

    toast('Job criado: ' + data.job_id, 'good');
    _veStartPoll(data.job_id);
  } catch (e) {
    toast('Erro: ' + e.message, 'bad');
    if (btn) { btn.disabled = false; btn.textContent = '✦ Melhorar Vídeo'; }
  }
}

function _veSetStatus(text, pct) {
  const t = document.getElementById('veStatusText');
  const p = document.getElementById('veStatusPct');
  const bar = document.getElementById('veProgressBar');
  if (t) t.textContent = text;
  if (p) p.textContent = pct + '%';
  if (bar) bar.style.width = pct + '%';
}

function _veStartPoll(jobId) {
  if (_vePollTimer) clearInterval(_vePollTimer);
  _vePollTimer = setInterval(() => _vePoll(jobId), 3000);
  _vePoll(jobId);
}

async function _vePoll(jobId) {
  try {
    const data = await apiFetch(`/api/video-enhancer/status/${jobId}`);
    const pct = data.progress_pct ?? 0;
    const detail = data.detail || data.status || '…';
    _veSetStatus(detail, pct);

    if (data.status === 'done') {
      if (_vePollTimer) { clearInterval(_vePollTimer); _vePollTimer = null; }
      const btn = document.getElementById('veBtn');
      if (btn) { btn.disabled = false; btn.textContent = '✦ Melhorar Vídeo'; }
      const outputInfo = document.getElementById('veOutputInfo');
      const outputPath = document.getElementById('veOutputPath');
      const outputSize = document.getElementById('veOutputSize');
      if (outputInfo) outputInfo.style.display = 'block';
      if (outputPath) outputPath.textContent = data.output_path || '';
      if (outputSize && data.output_size_mb) outputSize.textContent = data.output_size_mb.toFixed(1) + ' MB';
      // Build download/stream links from output_path
      const outPath = data.output_path || '';
      const mediaRoot = '/media';
      if (outPath.startsWith(mediaRoot)) {
        const rel = outPath.slice(mediaRoot.length).replace(/^\//, '');
        const ref = 'local:' + rel;
        const fname = outPath.split('/').pop();
        const dlUrl = `/api/local-media/download?ref=${encodeURIComponent(ref)}&filename=${encodeURIComponent(fname)}`;
        const stUrl = `/api/local-media/stream?ref=${encodeURIComponent(ref)}`;
        const actions = document.getElementById('veOutputActions');
        if (actions) {
          actions.innerHTML = `
            <a href="${stUrl}" target="_blank" class="btn" style="margin-right:8px;">▶ Assistir</a>
            <a href="${dlUrl}" download="${fname}" class="btn">⬇ Baixar</a>`;
        }
      }
      veLoadJobs();
      toast('Vídeo melhorado com sucesso!', 'good');
    } else if (data.status === 'error') {
      if (_vePollTimer) { clearInterval(_vePollTimer); _vePollTimer = null; }
      const btn = document.getElementById('veBtn');
      if (btn) { btn.disabled = false; btn.textContent = '✦ Melhorar Vídeo'; }
      toast('Erro no job: ' + (data.detail || ''), 'bad');
    }
  } catch (e) {
    // keep polling silently
  }
}

async function veLoadJobs() {
  const el = document.getElementById('veJobsList');
  if (!el) return;
  try {
    const data = await apiFetch('/api/video-enhancer/jobs?limit=20');
    const jobs = data.jobs || [];
    if (!jobs.length) {
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px;font-size:13px;">Nenhum job ainda.</div>';
      return;
    }
    el.innerHTML = jobs.map(j => {
      const statusColor = j.status === 'done' ? '#4caf50' : j.status === 'error' ? '#f44336' : j.status === 'running' ? '#2196f3' : '#9e9e9e';
      const pct = j.progress_pct != null ? ` ${j.progress_pct}%` : '';
      const size = j.output_size_mb ? ` · ${parseFloat(j.output_size_mb).toFixed(1)}MB` : '';
      const fname = (j.original_filename || j.output_path || '').split('/').pop();
      let dlBtns = '';
      if (j.status === 'done' && j.output_path && j.output_path.startsWith('/media')) {
        const rel = j.output_path.slice('/media'.length).replace(/^\//, '');
        const ref = encodeURIComponent('local:' + rel);
        const fn = encodeURIComponent(j.output_path.split('/').pop());
        dlBtns = `<div style="margin-top:6px;display:flex;gap:6px;">
          <a href="/api/local-media/stream?ref=${ref}" target="_blank" class="btn" style="font-size:11px;padding:3px 8px;">▶ Assistir</a>
          <a href="/api/local-media/download?ref=${ref}&filename=${fn}" download class="btn" style="font-size:11px;padding:3px 8px;">⬇ Baixar</a>
        </div>`;
      }
      return `<div style="padding:10px 12px;border-bottom:1px solid var(--border);font-size:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div style="flex:1;min-width:0;">
            <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${fname}</div>
            <div style="color:var(--muted);margin-top:2px;">${j.job_id?.slice(0,8)} · ${j.resolution || ''}${size} · ${j.created_at?.slice(0,10) || ''}</div>
          </div>
          <div style="color:${statusColor};font-weight:600;margin-left:12px;white-space:nowrap;">${j.status}${pct}</div>
        </div>
        ${dlBtns}
      </div>`;
     }).join('');
  } catch (e) {
    el.innerHTML = `<div style="color:var(--muted);text-align:center;padding:20px;font-size:13px;">Erro: ${e.message}</div>`;
  }
}

// ── CLIENTES (Companies) ──────────────────────────────────────────────────

let _clientesData = [];
let _clienteCurrent = null;
let _clienteCurrentTab = 'geral';

async function clientesLoad() {
  try {
    const r = await apiFetch('/api/companies');
    _clientesData = r.companies || [];
    clientesRender();
  } catch (e) {
    const grid = qs('clientesGrid');
    if (grid) grid.innerHTML = `<div style="color:var(--bad)">Erro: ${e.message}</div>`;
  }
}

function clientesRender() {
  const grid = qs('clientesGrid');
  const empty = qs('clientesEmpty');
  if (!grid) return;
  const search = (qs('clientesSearch')?.value || '').toLowerCase();
  const filtered = _clientesData.filter(c => c.name.toLowerCase().includes(search));
  if (!filtered.length) {
    grid.innerHTML = '';
    if (empty) empty.classList.remove('hidden');
    return;
  }
  if (empty) empty.classList.add('hidden');
  grid.innerHTML = filtered.map(c => {
    const seg = c.segment || 'Sem segmento';
    const posts = c.post_count || 0;
    const badge = c.active
      ? '<span class="badge good">Ativo</span>'
      : '<span class="badge bad">Inativo</span>';
    return `<div class="card" style="cursor:pointer" onclick="clienteDetail('${c.id}')">
      <div class="row" style="align-items:flex-start;gap:10px">
        <span style="font-size:24px">🏢</span>
        <div class="col grow">
          <strong style="font-size:15px">${esc(c.name)}</strong>
          <div style="color:var(--muted);font-size:12px;margin-top:2px">${esc(seg)} · ${posts} posts no histórico</div>
          <div style="margin-top:8px">${badge}</div>
        </div>
      </div>
      <div class="row" style="margin-top:12px;gap:8px">
        <button class="btn" onclick="event.stopPropagation();clienteDetail('${c.id}','gerar')">Gerar</button>
      </div>
    </div>`;
  }).join('');
}

function clientesFilter() { clientesRender(); }

function clientesShowAddForm() {
  const panel = qs('clienteFormPanel');
  const content = qs('clienteFormContent');
  if (!panel || !content) return;
  panel.classList.remove('hidden');
  content.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px">
      <div><label>Nome *</label><input id="clf_name" type="text" placeholder="Ex: IBIUNET" style="width:100%"/></div>
      <div><label>Segmento</label><input id="clf_segment" type="text" placeholder="Ex: Telecom" style="width:100%"/></div>
      <div><label>Website</label><input id="clf_website" type="text" placeholder="https://" style="width:100%"/></div>
      <div><label>Cidade</label><input id="clf_city" type="text" placeholder="Cidade" style="width:100%"/></div>
      <div><label>Estado</label><input id="clf_state" type="text" placeholder="UF" style="width:100%"/></div>
      <div><label>Telefone</label><input id="clf_phone" type="text" placeholder="(11) 99999-9999" style="width:100%"/></div>
      <div style="grid-column:1/3"><label>Email</label><input id="clf_email" type="email" placeholder="contato@empresa.com" style="width:100%"/></div>
    </div>
    <h3 style="margin-top:20px;font-size:14px;color:var(--muted)">Concorrentes (opcional)</h3>
    <div id="clf_competitors" style="display:flex;flex-direction:column;gap:8px"></div>
    <button class="btn" style="margin-top:8px" onclick="clientesAddCompetitorRow()">+ Adicionar concorrente</button>
    <div class="row" style="margin-top:20px;gap:10px">
      <button class="btn primary" onclick="clientesCreate()">Cadastrar empresa</button>
      <button class="btn" onclick="clientesCloseForm()">Cancelar</button>
    </div>
  `;
  clientesAddCompetitorRow();
}

function clientesAddCompetitorRow() {
  const cont = qs('clf_competitors');
  if (!cont) return;
  const idx = cont.children.length;
  const row = document.createElement('div');
  row.style.cssText = 'display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:8px';
  row.innerHTML = `
    <input type="text" placeholder="Nome" data-comp="name" style="width:100%"/>
    <input type="text" placeholder="@instagram" data-comp="instagram" style="width:100%"/>
    <input type="text" placeholder="https://" data-comp="website" style="width:100%"/>
    <button class="btn" onclick="this.parentElement.remove()" style="padding:4px 8px">✕</button>
  `;
  cont.appendChild(row);
}

function clientesCloseForm() {
  qs('clienteFormPanel').classList.add('hidden');
}

async function clientesCreate() {
  const name = qs('clf_name')?.value.trim();
  if (!name) { alert('Nome é obrigatório'); return; }
  const competitors = [];
  document.querySelectorAll('#clf_competitors > div').forEach(row => {
    const inputs = row.querySelectorAll('[data-comp]');
    const comp = {};
    inputs.forEach(i => comp[i.dataset.comp] = i.value.trim());
    if (comp.name) competitors.push(comp);
  });
  const body = {
    name,
    segment: qs('clf_segment')?.value.trim() || null,
    website: qs('clf_website')?.value.trim() || null,
    city: qs('clf_city')?.value.trim() || null,
    state: qs('clf_state')?.value.trim() || null,
    phone: qs('clf_phone')?.value.trim() || null,
    email: qs('clf_email')?.value.trim() || null,
    competitors,
  };
  try {
    await apiFetch('/api/companies', { method: 'POST', body: JSON.stringify(body) });
    clientesCloseForm();
    await clientesLoad();
  } catch (e) {
    alert('Erro: ' + e.message);
  }
}

async function clienteDetail(id, tab) {
  try {
    const r = await apiFetch(`/api/companies/${id}`);
    _clienteCurrent = r.company;
    _clienteCurrentTab = tab || 'geral';
    qs('clienteFormPanel').classList.add('hidden');
    const panel = qs('clienteDetailPanel');
    panel.classList.remove('hidden');
    qs('clienteDetailName').textContent = _clienteCurrent.name;
    const badge = qs('clienteDetailBadge');
    badge.textContent = _clienteCurrent.active ? 'Ativo' : 'Inativo';
    badge.className = 'badge ' + (_clienteCurrent.active ? 'good' : 'bad');
    clienteTab(_clienteCurrentTab);
    panel.scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    alert('Erro: ' + e.message);
  }
}

function clientesCloseDetail() {
  qs('clienteDetailPanel').classList.add('hidden');
  _clienteCurrent = null;
}

function clienteTab(tab) {
  _clienteCurrentTab = tab;
  document.querySelectorAll('#clienteTabs .tab').forEach(t => t.classList.remove('active'));
  event?.target?.classList?.add?.('active');
  const content = qs('clienteTabContent');
  if (!content || !_clienteCurrent) return;
  const c = _clienteCurrent;
  if (tab === 'geral') clienteRenderGeral(c, content);
  else if (tab === 'visual') clienteRenderVisual(c, content);
  else if (tab === 'voz') clienteRenderVoz(c, content);
  else if (tab === 'concorrentes') clienteRenderConcorrentes(c, content);
  else if (tab === 'gerar') clienteRenderGerar(c, content);
}

function clienteRenderGeral(c, el) {
  const s = c.socials || {};
  el.innerHTML = `<div class="card">
    <h2>Dados Gerais</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px">
      <div><label>Nome</label><input id="cg_name" type="text" value="${esc(c.name || '')}" style="width:100%"/></div>
      <div><label>Segmento</label><input id="cg_segment" type="text" value="${esc(c.segment || '')}" placeholder="Ex: Saúde, Educação, Varejo" style="width:100%"/></div>
      <div><label>Website</label><input id="cg_website" type="text" value="${esc(c.website || '')}" style="width:100%"/></div>
      <div><label>Email</label><input id="cg_email" type="text" value="${esc(c.email || '')}" style="width:100%"/></div>
      <div><label>Cidade</label><input id="cg_city" type="text" value="${esc(c.city || '')}" style="width:100%"/></div>
      <div><label>Estado</label><input id="cg_state" type="text" value="${esc(c.state || '')}" placeholder="SP" style="width:100%"/></div>
      <div><label>Telefone</label><input id="cg_phone" type="text" value="${esc(c.phone || '')}" placeholder="(11) 99999-9999" style="width:100%"/></div>
    </div>
    <h3 style="margin-top:20px;font-size:14px;color:var(--muted)">Redes sociais</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
      <div><label>Instagram</label><input id="cg_social_instagram" type="text" value="${esc(s.instagram || '')}" placeholder="@usuario" style="width:100%"/></div>
      <div><label>Facebook</label><input id="cg_social_facebook" type="text" value="${esc(s.facebook || '')}" style="width:100%"/></div>
      <div><label>TikTok</label><input id="cg_social_tiktok" type="text" value="${esc(s.tiktok || '')}" style="width:100%"/></div>
    </div>
    <div id="cg_msg" style="margin-top:12px"></div>
    <button class="btn primary" style="margin-top:16px" onclick="clienteSaveGeral()">Salvar</button>
  </div>`;
}

async function clienteSaveGeral() {
  if (!_clienteCurrent) return;
  const body = {
    name: qs('cg_name').value.trim(),
    segment: qs('cg_segment').value.trim() || null,
    website: qs('cg_website').value.trim() || null,
    email: qs('cg_email').value.trim() || null,
    city: qs('cg_city').value.trim() || null,
    state: qs('cg_state').value.trim() || null,
    phone: qs('cg_phone').value.trim() || null,
    social_instagram: qs('cg_social_instagram').value.trim(),
    social_facebook: qs('cg_social_facebook').value.trim(),
    social_tiktok: qs('cg_social_tiktok').value.trim(),
  };
  try {
    const r = await apiFetch(`/api/companies/${_clienteCurrent.id}`, { method: 'PUT', body: JSON.stringify(body) });
    _clienteCurrent = r.company;
    qs('clienteDetailName').textContent = _clienteCurrent.name;
    qs('cg_msg').innerHTML = '<span style="color:var(--good)">✓ Salvo</span>';
  } catch (e) {
    qs('cg_msg').innerHTML = `<span style="color:var(--bad)">Erro: ${esc(e.message)}</span>`;
  }
}

function clienteRenderVisual(c, el) {
  const bk = c.brand_kit || {};
  const colors = bk.colors || {};
  const refs = c.references || [];
  el.innerHTML = `<div class="card">
    <h2>Logo da marca</h2>
    <div style="display:flex;align-items:center;gap:16px;margin-top:12px">
      ${bk.logo_url ? `<img src="${esc(bk.logo_url)}" style="max-height:80px;max-width:200px;border-radius:8px;border:1px solid var(--line)"/>` : '<div style="color:var(--muted)">Sem logo</div>'}
      <div>
        <input id="cv_logo" type="file" accept="image/*" style="font-size:12px"/>
        <button class="btn" onclick="clienteUploadLogo()">Upload</button>
      </div>
    </div>
  </div>
  <div class="card" style="margin-top:16px">
    <h2>Paleta de cores</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:12px">
      <div><label>Primária</label><div style="display:flex;align-items:center;gap:8px"><input id="cv_primary" type="color" value="${esc(colors.primary || '#123d8f')}" style="width:50px;height:40px;border:none;background:none;cursor:pointer"/><span id="cv_primary_hex" style="font-family:monospace;font-size:12px">${esc(colors.primary || '#123d8f')}</span></div></div>
      <div><label>Secundária</label><div style="display:flex;align-items:center;gap:8px"><input id="cv_secondary" type="color" value="${esc(colors.secondary || '#fe6601')}" style="width:50px;height:40px;border:none;background:none;cursor:pointer"/><span id="cv_secondary_hex" style="font-family:monospace;font-size:12px">${esc(colors.secondary || '#fe6601')}</span></div></div>
      <div><label>Destaque</label><div style="display:flex;align-items:center;gap:8px"><input id="cv_accent" type="color" value="${esc(colors.accent || '#14b7f0')}" style="width:50px;height:40px;border:none;background:none;cursor:pointer"/><span id="cv_accent_hex" style="font-family:monospace;font-size:12px">${esc(colors.accent || '#14b7f0')}</span></div></div>
    </div>
    <div id="cv_msg" style="margin-top:12px"></div>
    <button class="btn primary" style="margin-top:16px" onclick="clienteSaveVisual()">Salvar cores</button>
  </div>
  <div class="card" style="margin-top:16px">
    <h2>Mood board</h2>
    <div style="display:flex;gap:12px;margin-top:12px;align-items:center">
      <input id="cv_ref" type="file" accept="image/*" style="font-size:12px"/>
      <button class="btn" onclick="clienteUploadReference()">Adicionar referência</button>
    </div>
    <div id="cv_refs" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:12px;margin-top:16px">
      ${refs.map(r => `<div style="position:relative">
        <img src="${esc(r.url)}" style="width:100%;height:100px;object-fit:cover;border-radius:8px;border:1px solid var(--line)"/>
        <button onclick="clienteDeleteReference('${r.id}')" style="position:absolute;top:4px;right:4px;background:rgba(0,0,0,.7);color:#fff;border:none;border-radius:4px;padding:2px 6px;cursor:pointer;font-size:12px">✕</button>
      </div>`).join('')}
    </div>
  </div>`;
  ['primary','secondary','accent'].forEach(k => {
    const inp = qs(`cv_${k}`);
    const hex = qs(`cv_${k}_hex`);
    if (inp && hex) inp.oninput = () => hex.textContent = inp.value;
  });
}

async function clienteUploadLogo() {
  if (!_clienteCurrent) return;
  const file = qs('cv_logo')?.files?.[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const headers = {};
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch(`/api/companies/${_clienteCurrent.id}/logo`, { method: 'POST', body: fd, headers });
    if (!res.ok) throw new Error(await res.text());
    await clienteDetail(_clienteCurrent.id, 'visual');
  } catch (e) { alert('Erro: ' + e.message); }
}

async function clienteSaveVisual() {
  if (!_clienteCurrent) return;
  const body = {
    primaryColor: qs('cv_primary').value,
    secondaryColor: qs('cv_secondary').value,
    accentColor: qs('cv_accent').value,
  };
  try {
    await apiFetch(`/api/companies/${_clienteCurrent.id}/brand-kit`, { method: 'POST', body: JSON.stringify(body) });
    qs('cv_msg').innerHTML = '<span style="color:var(--good)">✓ Cores salvas</span>';
  } catch (e) {
    qs('cv_msg').innerHTML = `<span style="color:var(--bad)">Erro: ${esc(e.message)}</span>`;
  }
}

async function clienteUploadReference() {
  if (!_clienteCurrent) return;
  const file = qs('cv_ref')?.files?.[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const headers = {};
    if (state.apiKey) headers['X-API-Key'] = state.apiKey;
    const res = await fetch(`/api/companies/${_clienteCurrent.id}/references`, { method: 'POST', body: fd, headers });
    if (!res.ok) throw new Error(await res.text());
    await clienteDetail(_clienteCurrent.id, 'visual');
  } catch (e) { alert('Erro: ' + e.message); }
}

async function clienteDeleteReference(assetId) {
  if (!_clienteCurrent) return;
  try {
    await apiFetch(`/api/companies/${_clienteCurrent.id}/references/${assetId}`, { method: 'DELETE' });
    await clienteDetail(_clienteCurrent.id, 'visual');
  } catch (e) { alert('Erro: ' + e.message); }
}

function clienteRenderVoz(c, el) {
  const bk = c.brand_kit || {};
  el.innerHTML = `<div class="card">
    <h2>Voz &amp; Persona</h2>
    <div style="display:flex;flex-direction:column;gap:16px;margin-top:16px">
      <div><label>Tom de voz</label><input id="cvz_voice" type="text" value="${esc(bk.voice || '')}" placeholder="Ex: próximo, confiante, sem jargão técnico" style="width:100%"/></div>
      <div><label>Persona da marca</label><textarea id="cvz_persona" rows="4" placeholder="Descreva a persona..." style="width:100%;resize:vertical">${esc(bk.persona || '')}</textarea></div>
      <div><label>Base para prompt visual</label><textarea id="cvz_visual" rows="3" placeholder="Ex: fundo branco, produto em destaque, cores vibrantes" style="width:100%;resize:vertical">${esc(bk.visual_prompt_base || '')}</textarea></div>
    </div>
    <div id="cvz_msg" style="margin-top:12px"></div>
    <button class="btn primary" style="margin-top:16px" onclick="clienteSaveVoz()">Salvar</button>
  </div>`;
}

async function clienteSaveVoz() {
  if (!_clienteCurrent) return;
  const body = {
    voice: qs('cvz_voice').value.trim(),
    persona: qs('cvz_persona').value.trim(),
    visual_prompt_base: qs('cvz_visual').value.trim(),
  };
  try {
    await apiFetch(`/api/companies/${_clienteCurrent.id}/brand-kit`, { method: 'POST', body: JSON.stringify(body) });
    qs('cvz_msg').innerHTML = '<span style="color:var(--good)">✓ Salvo</span>';
  } catch (e) {
    qs('cvz_msg').innerHTML = `<span style="color:var(--bad)">Erro: ${esc(e.message)}</span>`;
  }
}

function clienteRenderConcorrentes(c, el) {
  const comps = c.competitors || [];
  el.innerHTML = `<div class="card">
    <h2>Concorrentes</h2>
    <div id="cc_list" style="margin-top:16px;display:flex;flex-direction:column;gap:8px">
      ${comps.length ? comps.map(co => {
        const h = co.handles || {};
        return `<div class="card" style="padding:12px;display:flex;align-items:center;justify-content:space-between">
          <div>
            <strong>${esc(co.name)}</strong>
            <div style="color:var(--muted);font-size:12px;margin-top:2px">
              ${h.instagram ? esc(h.instagram) + ' · ' : ''}${h.website ? esc(h.website) : ''}
            </div>
          </div>
          <button class="btn" style="padding:4px 8px" onclick="clienteRemoveCompetitor('${co.id}')">✕</button>
        </div>`;
      }).join('') : '<div style="color:var(--muted);text-align:center;padding:20px">Nenhum concorrente cadastrado.</div>'}
    </div>
    <h3 style="margin-top:20px;font-size:14px;color:var(--muted)">Adicionar concorrente</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:8px">
      <input id="cc_name" type="text" placeholder="Nome *" style="width:100%"/>
      <input id="cc_instagram" type="text" placeholder="@usuario" style="width:100%"/>
      <input id="cc_website" type="text" placeholder="https://" style="width:100%"/>
    </div>
    <div id="cc_msg" style="margin-top:8px"></div>
    <button class="btn primary" style="margin-top:12px" onclick="clienteAddCompetitor()">Adicionar</button>
  </div>`;
}

async function clienteAddCompetitor() {
  if (!_clienteCurrent) return;
  const name = qs('cc_name').value.trim();
  if (!name) { qs('cc_msg').innerHTML = '<span style="color:var(--bad)">Nome é obrigatório</span>'; return; }
  const body = {
    name,
    instagram: qs('cc_instagram').value.trim() || null,
    website: qs('cc_website').value.trim() || null,
  };
  try {
    await apiFetch(`/api/companies/${_clienteCurrent.id}/competitors`, { method: 'POST', body: JSON.stringify(body) });
    await clienteDetail(_clienteCurrent.id, 'concorrentes');
  } catch (e) {
    qs('cc_msg').innerHTML = `<span style="color:var(--bad)">Erro: ${esc(e.message)}</span>`;
  }
}

async function clienteRemoveCompetitor(compId) {
  if (!_clienteCurrent) return;
  try {
    await apiFetch(`/api/companies/${_clienteCurrent.id}/competitors/${compId}`, { method: 'DELETE' });
    await clienteDetail(_clienteCurrent.id, 'concorrentes');
  } catch (e) { alert('Erro: ' + e.message); }
}

function clienteRenderGerar(c, el) {
  el.innerHTML = `<div class="card" style="border:1px solid var(--pri);border-radius:12px">
    <h2>Gerar com IA</h2>
    <textarea id="cg_briefing" rows="3" placeholder="Briefing: o que esse post precisa comunicar? Ex.: promoção de plano 600MB por R$ 89,90 até sexta." style="width:100%;resize:vertical;margin-top:12px"></textarea>
    <div id="cg_ai_msg" style="margin-top:8px"></div>
    <button class="btn primary" style="margin-top:12px" onclick="clienteGenerateAI()">Gerar copy com IA</button>
  </div>
  <div class="card" style="margin-top:16px">
    <h2>Post manual</h2>
    <div style="display:flex;flex-direction:column;gap:12px;margin-top:12px">
      <div><label>Título interno</label><input id="cg_title" type="text" style="width:100%"/></div>
      <div><label>Copy</label><textarea id="cg_copy" rows="6" style="width:100%;resize:vertical;min-height:120px"></textarea></div>
      <div><label>Hashtags</label><input id="cg_hashtags" type="text" placeholder="#exemplo #marca" style="width:100%"/></div>
      <div><label>Redes</label><div id="cg_networks" style="display:flex;gap:8px;flex-wrap:wrap"></div></div>
      <div><label>Agendar para (opcional)</label><input id="cg_scheduled" type="datetime-local" style="width:100%"/></div>
    </div>
    <div id="cg_post_msg" style="margin-top:12px"></div>
    <div class="row" style="margin-top:16px;gap:10px">
      <button class="btn primary" onclick="clienteCreatePost('review')">Enviar para aprovação</button>
      <button class="btn" onclick="clienteCreatePost('draft')">Salvar rascunho</button>
    </div>
  </div>`;
  const nets = ['instagram','facebook','tiktok','youtube','linkedin','x'];
  qs('cg_networks').innerHTML = nets.map((n, i) =>
    `<button class="btn net-btn ${i === 0 ? 'primary' : ''}" data-net="${n}" onclick="this.classList.toggle('primary')">${n}</button>`
  ).join('');
}

async function clienteGenerateAI() {
  if (!_clienteCurrent) return;
  const briefing = qs('cg_briefing').value.trim();
  if (!briefing) { qs('cg_ai_msg').innerHTML = '<span style="color:var(--bad)">Digite um briefing</span>'; return; }
  const networks = Array.from(document.querySelectorAll('.net-btn.primary')).map(b => b.dataset.net);
  qs('cg_ai_msg').innerHTML = '<span style="color:var(--muted)">Gerando...</span>';
  try {
    const r = await apiFetch('/api/posts/generate-ai', { method: 'POST', body: JSON.stringify({
      company_id: _clienteCurrent.id, briefing, networks: networks.length ? networks : ['instagram'],
    })});
    const g = r.generated || {};
    if (qs('cg_title')) qs('cg_title').value = g.title || '';
    if (qs('cg_copy')) qs('cg_copy').value = g.copy || '';
    if (qs('cg_hashtags')) qs('cg_hashtags').value = g.hashtags || '';
    qs('cg_ai_msg').innerHTML = '<span style="color:var(--good)">✓ Copy gerada</span>';
  } catch (e) {
    qs('cg_ai_msg').innerHTML = `<span style="color:var(--bad)">${esc(e.message)}</span>`;
  }
}

async function clienteCreatePost(intent) {
  if (!_clienteCurrent) return;
  const networks = Array.from(document.querySelectorAll('.net-btn.primary')).map(b => b.dataset.net);
  const body = {
    company_id: _clienteCurrent.id,
    title: qs('cg_title').value.trim(),
    copy: qs('cg_copy').value.trim(),
    hashtags: qs('cg_hashtags').value.trim(),
    networks: networks.length ? networks : ['instagram'],
    scheduled_at: qs('cg_scheduled').value || null,
    intent,
  };
  if (!body.copy) { qs('cg_post_msg').innerHTML = '<span style="color:var(--bad)">Copy é obrigatória</span>'; return; }
  try {
    await apiFetch('/api/posts', { method: 'POST', body: JSON.stringify(body) });
    qs('cg_post_msg').innerHTML = `<span style="color:var(--good)">✓ ${intent === 'review' ? 'Enviado para aprovação' : 'Rascunho salvo'}</span>`;
    if (qs('cg_title')) qs('cg_title').value = '';
    if (qs('cg_copy')) qs('cg_copy').value = '';
    if (qs('cg_hashtags')) qs('cg_hashtags').value = '';
  } catch (e) {
    qs('cg_post_msg').innerHTML = `<span style="color:var(--bad)">Erro: ${esc(e.message)}</span>`;
  }
}

// ── APROVAÇÃO (Approval Center) ────────────────────────────────────────────

async function aprovacaoLoad() {
  try {
    const r = await apiFetch('/api/posts?status=DRAFT,REVIEW,APPROVED,SCHEDULED');
    const posts = r.posts || [];
    const review = posts.filter(p => p.status === 'REVIEW');
    const draft = posts.filter(p => p.status === 'DRAFT');
    const approved = posts.filter(p => p.status === 'APPROVED' || p.status === 'SCHEDULED');
    const empty = qs('aprovacaoEmpty');
    if (!posts.length && empty) empty.classList.remove('hidden');
    else if (empty) empty.classList.add('hidden');
    aprovacaoRenderSection('aprovacaoReviewList', review, r.labels);
    aprovacaoRenderSection('aprovacaoDraftList', draft, r.labels);
    aprovacaoRenderSection('aprovacaoApprovedList', approved, r.labels);
  } catch (e) {
    console.error('aprovacaoLoad:', e);
  }
}

function aprovacaoRenderSection(elId, posts, labels) {
  const el = qs(elId);
  if (!el) return;
  if (!posts.length) { el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:16px;font-size:13px">Nenhum post.</div>'; return; }
  el.innerHTML = posts.map(p => {
    const label = (labels || {})[p.status] || p.status;
    const badgeClass = p.status === 'REVIEW' ? 'warn' : (p.status === 'SCHEDULED' ? 'good' : '');
    const nets = (p.networks || []).join(', ');
    const sched = p.scheduled_at ? ` · agendado ${new Date(p.scheduled_at).toLocaleString('pt-BR')}` : '';
    let actions = '';
    if (p.status === 'DRAFT') actions = `<button class="btn" onclick="aprovacaoTransition('${p.id}','REVIEW')">Enviar p/ revisão</button>`;
    else if (p.status === 'REVIEW') actions = `<button class="btn primary" onclick="aprovacaoTransition('${p.id}','APPROVED')">Aprobar</button> <button class="btn" onclick="aprovacaoTransition('${p.id}','DRAFT')">Devolver</button>`;
    else if (p.status === 'APPROVED' && p.scheduled_at) actions = `<button class="btn primary" onclick="aprovacaoTransition('${p.id}','SCHEDULED')">Agendar</button>`;
    actions += ` <button class="btn" style="padding:4px 8px;color:var(--bad)" onclick="aprovacaoDelete('${p.id}')">✕</button>`;
    return `<div class="card" style="padding:16px;margin-bottom:12px">
      <div class="row" style="justify-content:space-between;align-items:flex-start">
        <div class="col grow">
          <strong>${esc(p.title || 'Sem título')}</strong>
          <div style="color:var(--muted);font-size:12px;margin-top:2px">${esc(p.company_name || '')}${sched} · ${esc(nets)}</div>
        </div>
        <span class="badge ${badgeClass}">${esc(label)}</span>
      </div>
      <div style="margin-top:12px;white-space:pre-wrap;font-size:14px;color:var(--text2)">${esc(p.copy || '')}</div>
      ${p.hashtags && p.hashtags.length ? `<div style="margin-top:8px;color:var(--accent);font-size:13px">${esc(p.hashtags.join(' '))}</div>` : ''}
      <div class="row" style="margin-top:12px;gap:8px">${actions}</div>
    </div>`;
  }).join('');
}

async function aprovacaoTransition(postId, to) {
  try {
    await apiFetch(`/api/posts/${postId}/transition`, { method: 'POST', body: JSON.stringify({ to }) });
    await aprovacaoLoad();
  } catch (e) { alert('Erro: ' + e.message); }
}

async function aprovacaoDelete(postId) {
  if (!confirm('Excluir este post?')) return;
  try {
    await apiFetch(`/api/posts/${postId}`, { method: 'DELETE' });
    await aprovacaoLoad();
  } catch (e) { alert('Erro: ' + e.message); }
}

// ── CONCORRENTES (Cross-company benchmark) ─────────────────────────────────

async function concorrentesLoad() {
  try {
    const r = await apiFetch('/api/companies/all/competitors');
    const comps = r.competitors || [];
    const grid = qs('concorrentesGrid');
    const empty = qs('concorrentesEmpty');
    if (!grid) return;
    if (!comps.length) {
      grid.innerHTML = '';
      if (empty) empty.classList.remove('hidden');
      return;
    }
    if (empty) empty.classList.add('hidden');
    grid.innerHTML = comps.map(c => {
      const h = c.handles || {};
      return `<div class="card">
        <strong style="font-size:15px">${esc(c.name)}</strong>
        <div style="color:var(--muted);font-size:12px;margin-top:4px">Concorrente de ${esc(c.company_name || '')}</div>
        ${h.instagram ? `<div style="margin-top:8px;font-size:13px;color:var(--accent)">${esc(h.instagram)}</div>` : ''}
        ${h.website ? `<div style="font-size:13px;color:var(--muted)">${esc(h.website)}</div>` : ''}
      </div>`;
    }).join('');
  } catch (e) {
    console.error('concorrentesLoad:', e);
  }
}

// ── AI SETTINGS ────────────────────────────────────────────────────────────

async function aiLoadSettings() {
  try {
    const r = await apiFetch('/api/ai-settings');
    for (const section of ['ai', 'image', 'video']) {
      const cfg = r[section];
      if (!cfg) continue;
      const pSel = qs(`${section}_provider`);
      const mSel = qs(`${section}_model`);
      const kInp = qs(`${section}_apikey`);
      const kMask = qs(`${section}_keymask`);
      if (pSel && cfg.provider) pSel.value = cfg.provider;
      if (mSel && cfg.model) {
        const opt = document.createElement('option');
        opt.value = cfg.model; opt.textContent = cfg.model; opt.selected = true;
        mSel.innerHTML = ''; mSel.appendChild(opt);
      }
      if (kInp) kInp.value = '';
      if (kMask && cfg.keyMasks && cfg.keyMasks[cfg.provider]) {
        kMask.textContent = `Chave salva: ${cfg.keyMasks[cfg.provider]}. Em branco mantém; cole outra para substituir.`;
      } else if (kMask) {
        kMask.textContent = '';
      }
    }
  } catch (e) {
    console.error('aiLoadSettings:', e);
  }
}

async function aiLoadModels(section) {
  const provider = qs(`${section}_provider`)?.value;
  const apiKey = qs(`${section}_apikey`)?.value.trim();
  if (!provider) return;
  const mSel = qs(`${section}_model`);
  if (mSel) mSel.innerHTML = '<option>Carregando...</option>';
  try {
    const r = await apiFetch('/api/ai-settings/models', { method: 'POST', body: JSON.stringify({ section, provider, api_key: apiKey || null }) });
    const models = r.models || [];
    if (mSel) {
      mSel.innerHTML = models.length
        ? models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('')
        : '<option value="">Nenhum modelo</option>';
    }
    if (r.error) toast(r.error, 'bad');
  } catch (e) {
    if (mSel) mSel.innerHTML = '<option value="">Erro</option>';
    toast('Erro: ' + e.message, 'bad');
  }
}

async function aiSaveSettings() {
  const body = {};
  for (const section of ['ai', 'image']) {
    const provider = qs(`${section}_provider`)?.value;
    const model = qs(`${section}_model`)?.value;
    const apiKey = qs(`${section}_apikey`)?.value.trim();
    body[`${section}.provider`] = provider;
    if (model) body[`${section}.model`] = model;
    if (apiKey) body[`${section}.apiKey.${provider}`] = apiKey;
  }
  try {
    await apiFetch('/api/ai-settings', { method: 'POST', body: JSON.stringify(body) });
    qs('ai_save_msg').innerHTML = '<span style="color:var(--good)">✓ Configurações salvas</span>';
    await aiLoadSettings();
  } catch (e) {
    qs('ai_save_msg').innerHTML = `<span style="color:var(--bad)">Erro: ${esc(e.message)}</span>`;
  }
}

async function aiTest() {
  const el = qs('ai_test_result');
  if (el) el.innerHTML = '<span style="color:var(--muted)">Testando...</span>';
  try {
    const r = await apiFetch('/api/ai-settings/test', { method: 'POST', body: '{}' });
    if (r.test_result === 'ok') {
      el.innerHTML = '<div class="card" style="border:1px solid var(--good);color:var(--good)">✓ Conexão ok — IA pronta para gerar conteúdo.</div>';
    } else {
      el.innerHTML = `<div class="card" style="border:1px solid var(--bad);color:var(--bad)">✕ ${esc(r.message || 'Erro')}</div>`;
    }
  } catch (e) {
    el.innerHTML = `<div class="card" style="border:1px solid var(--bad);color:var(--bad)">✕ ${esc(e.message)}</div>`;
  }
}

// ── HELPERS ────────────────────────────────────────────────────────────────
// esc() and escAttr() already defined earlier in this file
