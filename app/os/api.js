/* Caripost OS — API layer: auth, contexto global e todas as funções reais */
(function () {
  'use strict';

  const STORAGE_KEY = 'mp_session_token';
  const LEGACY_SESSION_KEY = 'mp_session';
  const LEGACY_API_KEY = 'adult_meta_api_key';
  let _loginShown = false;
  let _isOpen = null;
  let _loginPromise = null;
  const LARGE_UPLOAD_THRESHOLD = 128 * 1024 * 1024;
  const LARGE_UPLOAD_CHUNK_SIZE = 16 * 1024 * 1024;

  /* ── Contexto global compartilhado entre apps ──
     mpCtx.file = { object_key, filename, s (status), run_id? }
     Setado pelo Arquivos ao clicar numa ação; lido pelos apps de edição. */
  window.mpCtx = { file: null, runId: null };

  function getLegacySession() {
    try {
      const raw = sessionStorage.getItem(LEGACY_SESSION_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) { return null; }
  }
  function getToken() {
    return getLegacySession()?.token || localStorage.getItem(STORAGE_KEY) || '';
  }
  function getApiKey() {
    try {
      return sessionStorage.getItem(LEGACY_API_KEY) || '';
    } catch (_) { return ''; }
  }
  function applyAuthHeaders(headers) {
    const token = getToken();
    const apiKey = getApiKey();
    if (token) headers['X-Session-Token'] = token;
    if (apiKey) headers['X-API-Key'] = apiKey;
    return headers;
  }
  function setToken(t, user) {
    localStorage.setItem(STORAGE_KEY, t);
    if (user) sessionStorage.setItem(LEGACY_SESSION_KEY, JSON.stringify({ token: t, user }));
  }
  function clearToken() {
    localStorage.removeItem(STORAGE_KEY);
    sessionStorage.removeItem(LEGACY_SESSION_KEY);
  }
  function hasAuthCredential() {
    return !!(getToken() || getApiKey());
  }
  function isAuthError(data) {
    return !!data && typeof data === 'object' && (
      data.error === 'unauthorized' ||
      data.detail === 'missing_or_invalid_api_key'
    );
  }
  async function readJson(res) {
    const ct = res.headers.get('content-type') || '';
    if (!ct.includes('application/json')) return null;
    try { return await res.json(); } catch (_) { return null; }
  }

  async function mpFetch(url, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    if (!(opts.body instanceof FormData)) {
      headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    }
    applyAuthHeaders(headers);
    const res = await fetch(url, { ...opts, headers });
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      const data = await res.json();
      if (res.status === 401 || isAuthError(data)) {
        _isOpen = false;
        clearToken();
        showLogin();
        throw new Error(data.detail || data.error || 'unauthorized');
      }
      return data;
    }
    if (res.status === 401) {
      _isOpen = false;
      clearToken();
      showLogin();
      throw new Error('unauthorized');
    }
    return res.text();
  }

  /* ── Login overlay ── */
  function showLogin() {
    if (_loginPromise) return _loginPromise;
    _loginShown = true;
    const el = document.createElement('div');
    el.id = 'mp-login-overlay';
    el.style.cssText = [
      'position:fixed;inset:0;z-index:99999;',
      'background:radial-gradient(900px 700px at 50% 38%,#ffffff,#fff3e6 72%);',
      'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:24px;',
      'font-family:"Space Grotesk","Inter",sans-serif;'
    ].join('');
    el.innerHTML = `
      <div style="width:60px;height:60px;border-radius:18px;background:linear-gradient(140deg,#ff7a18,#d97706);display:grid;place-items:center;font-weight:800;font-size:32px;color:#fff;box-shadow:0 12px 40px rgba(255,122,24,.35);">C</div>
      <div style="text-align:center;">
        <div style="font-size:28px;font-weight:700;color:#1a120a;">Caripost OS</div>
        <div style="font-size:13px;color:#9a8a76;margin-top:4px;">Plataforma de Gestão</div>
      </div>
      <form id="mp-login-form" style="display:flex;flex-direction:column;gap:12px;width:320px;max-width:90vw;">
        <input id="mp-u" type="text" placeholder="Usuário" autocomplete="username" style="padding:12px 16px;border-radius:11px;border:1px solid rgba(0,0,0,.12);background:rgba(0,0,0,.03);color:#1a120a;font-size:14px;outline:none;font-family:inherit;" />
        <input id="mp-p" type="password" placeholder="Senha" autocomplete="current-password" style="padding:12px 16px;border-radius:11px;border:1px solid rgba(0,0,0,.12);background:rgba(0,0,0,.03);color:#1a120a;font-size:14px;outline:none;font-family:inherit;" />
        <button type="submit" style="padding:13px;border-radius:12px;border:none;background:linear-gradient(135deg,#ff7a18,#d97706);color:#fff;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;box-shadow:0 6px 20px rgba(255,122,24,.3);">Entrar</button>
        <div id="mp-login-err" style="color:#e0322c;font-size:13px;text-align:center;min-height:18px;"></div>
      </form>`;
    document.body.appendChild(el);
    _loginPromise = new Promise(resolve => {
      document.getElementById('mp-login-form').addEventListener('submit', async e => {
        e.preventDefault();
        const u = document.getElementById('mp-u').value.trim();
        const p = document.getElementById('mp-p').value;
        const errEl = document.getElementById('mp-login-err');
        const btn = e.target.querySelector('button');
        errEl.textContent = ''; btn.textContent = 'Entrando…'; btn.disabled = true;
        try {
          const res = await fetch('/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u, password: p }),
          });
          const data = await res.json();
          if (data.ok && data.token) {
            setToken(data.token, data.user);
            _loginShown = false;
            _loginPromise = null;
            el.remove();
            resolve(true);
          } else {
            errEl.textContent = data.error === 'invalid_credentials' ? 'Usuário ou senha incorretos.' : (data.error || 'Erro');
          }
        } catch (err) {
          errEl.textContent = 'Erro de conexão: ' + err.message;
        } finally { btn.textContent = 'Entrar'; btn.disabled = false; }
      });
    });
    setTimeout(() => document.getElementById('mp-u')?.focus(), 100);
    return _loginPromise;
  }

  async function ensureAuth() {
    if (hasAuthCredential()) return true;
    _isOpen = false;
    await showLogin();
    if (hasAuthCredential()) return true;
    throw new Error('Faça login antes de enviar o vídeo.');
  }

  async function checkAuth() {
    try {
      const token = getToken();
      if (token) {
        const me = await fetch('/auth/me', { headers: { 'X-Session-Token': token } });
        if (me.ok) {
          const data = await me.json();
          if (data.user) { setToken(token, data.user); _isOpen = false; return; }
        }
        clearToken();
      }
      if (getApiKey()) {
        const res = await fetch('/runs?limit=1', { headers: applyAuthHeaders({}) });
        const data = await readJson(res);
        if (res.status !== 401 && !isAuthError(data)) { _isOpen = true; return; }
      }
      const res = await fetch('/runs?limit=1', { headers: applyAuthHeaders({}) });
      const data = await readJson(res);
      if (res.status === 401 || isAuthError(data)) { _isOpen = false; showLogin(); }
      else { _isOpen = true; }
    } catch { _isOpen = true; }
  }

  /* ── Helpers ── */
  function _fmtDate(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', timeZone:'America/Sao_Paulo' }); }
    catch { return iso.slice(0, 16); }
  }
  function _fmtTime(sec) {
    if (sec == null || sec === '' || isNaN(sec)) return '';
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }
  function _mediaStatus(it) {
    const key = (it.object_key || '').toLowerCase();
    const fn = (it.filename || '').toLowerCase();
    if (key.startsWith('local:burns/') || key.includes('/burns/') || fn.startsWith('legendado_')) return 'burn';
    if (key.startsWith('local:teasers/') || key.includes('/teasers/') || fn.startsWith('teaser_')) return 'teaser';
    if (key.startsWith('local:autoeditor/') || key.includes('/autoeditor/') || fn.startsWith('autoeditor_') || fn.startsWith('recut_')) return 'autoeditor';
    if (key.startsWith('local:cortes/') || key.includes('/cortes/') || fn.startsWith('corte_')) return 'cortes';
    if (it.category === 'burns') return 'burn';
    if (it.category === 'teasers') return 'teaser';
    if (it.category === 'autoeditor') return 'autoeditor';
    if (it.category === 'cortes') return 'cortes';
    return 'original';
  }
  function _mediaTone(s) {
    return s === 'burn' ? 'good' : s === 'teaser' ? 'cy' : s === 'autoeditor' ? 'violet' : s === 'cortes' ? 'cy' : '';
  }
  function _enc(v) { return encodeURIComponent(v); }

  const _thumbCache = {};   // object_key → url (in-memory session cache)
  const _thumbPending = {}; // object_key → Promise (dedupe in-flight)
  let _thumbActive = 0;
  const _thumbQueue = [];
  const THUMB_MAX_CONCURRENT = 6;
  function _thumbNext() {
    while (_thumbActive < THUMB_MAX_CONCURRENT && _thumbQueue.length) {
      const job = _thumbQueue.shift();
      _thumbActive++;
      job().finally(() => { _thumbActive--; _thumbNext(); });
    }
  }
  function _thumbEnqueue(fn) {
    return new Promise((resolve, reject) => {
      _thumbQueue.push(() => fn().then(resolve, reject));
      _thumbNext();
    });
  }
  const _metaCache = {};    // object_key → metadata

  function _authErrorMessage(err) {
    const msg = String(err?.message || '');
    return !!(err?.auth || msg === 'missing_or_invalid_api_key' || msg === 'unauthorized');
  }

  function _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function _isTransientUploadError(err) {
    const msg = String(err?.message || '');
    return !_authErrorMessage(err) && (
      err?.status >= 500 ||
      /failed to fetch|network|erro de rede|err_network_changed|load failed|temporar|timeout|time.?out|tempo esgotado/i.test(msg)
    );
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
        await _sleep(Math.min(10000, 600 * Math.pow(1.65, attempt - 1)));
      }
    }
    throw lastErr || new Error('Falha temporária no upload');
  }

  let _uploadModalState = null;

  function _formatUploadEta(ms) {
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

  function _ensureUploadModalStyle() {
    if (document.getElementById('mp-upload-modal-style')) return;
    const style = document.createElement('style');
    style.id = 'mp-upload-modal-style';
    style.textContent = `
      #mp-upload-modal{--pct:0;position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;background:rgba(255,255,255,.94);backdrop-filter:blur(18px);font-family:"Space Grotesk","Inter",sans-serif;color:#1b2231}
      #mp-upload-modal .mp-up-wrap{width:min(440px,88vw);display:flex;flex-direction:column;align-items:center;text-align:center;gap:18px}
      #mp-upload-modal .mp-up-ring{width:188px;height:188px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(#ff7a18 calc(var(--pct) * 1%),rgba(255,122,24,.14) 0);box-shadow:0 22px 70px rgba(255,122,24,.24),0 0 0 1px rgba(255,122,24,.18)}
      #mp-upload-modal .mp-up-ring::before{content:"";position:absolute;width:142px;height:142px;border-radius:50%;background:#fff;box-shadow:inset 0 0 0 1px rgba(20,28,45,.08)}
      #mp-upload-modal .mp-up-ring{position:relative}
      #mp-upload-modal .mp-up-pct{position:relative;z-index:1;font-size:36px;font-weight:800;color:#ff7a18;letter-spacing:0}
      #mp-upload-modal .mp-up-title{font-size:22px;font-weight:800;color:#1b2231}
      #mp-upload-modal .mp-up-detail{font-size:14px;font-weight:600;color:#4b5568;min-height:22px}
      #mp-upload-modal .mp-up-eta{font-size:13px;color:#8b95a6;min-height:20px}
      #mp-upload-modal .mp-up-file{max-width:100%;font-family:"JetBrains Mono","Courier New",monospace;font-size:11px;color:#8b95a6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #mp-upload-modal.is-error .mp-up-ring{background:conic-gradient(#fb2f68 calc(var(--pct) * 1%),rgba(251,47,104,.14) 0);box-shadow:0 22px 70px rgba(251,47,104,.22)}
      #mp-upload-modal.is-error .mp-up-pct{color:#fb2f68}
      #mp-upload-modal.is-done .mp-up-ring{background:conic-gradient(#1faa5a calc(var(--pct) * 1%),rgba(31,170,90,.14) 0);box-shadow:0 22px 70px rgba(31,170,90,.20)}
      #mp-upload-modal.is-done .mp-up-pct{color:#1faa5a}
    `;
    document.head.appendChild(style);
  }

  function _showUploadModal(file) {
    _ensureUploadModalStyle();
    const existing = document.getElementById('mp-upload-modal');
    if (existing) existing.remove();
    const el = document.createElement('div');
    el.id = 'mp-upload-modal';
    el.innerHTML = `
      <div class="mp-up-wrap" role="status" aria-live="polite">
        <div class="mp-up-ring"><div class="mp-up-pct">0%</div></div>
        <div class="mp-up-title">Enviando vídeo</div>
        <div class="mp-up-detail">Preparando arquivo...</div>
        <div class="mp-up-eta">calculando tempo restante</div>
        <div class="mp-up-file"></div>
      </div>`;
    document.body.appendChild(el);
    _uploadModalState = { el, start: Date.now(), pct: 0, fileName: file?.name || 'upload.bin' };
    el.querySelector('.mp-up-file').textContent = _uploadModalState.fileName;
    _updateUploadModal(0, 'Preparando arquivo...');
  }

  function _updateUploadModal(pct, detail) {
    const state = _uploadModalState;
    if (!state?.el) return;
    const safePct = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
    state.pct = Math.max(state.pct || 0, safePct);
    const rounded = Math.round(state.pct);
    state.el.style.setProperty('--pct', String(rounded));
    state.el.querySelector('.mp-up-pct').textContent = `${rounded}%`;
    if (detail) state.el.querySelector('.mp-up-detail').textContent = detail;
    const etaEl = state.el.querySelector('.mp-up-eta');
    if (rounded <= 1) etaEl.textContent = 'calculando tempo restante';
    else if (rounded >= 99) etaEl.textContent = 'finalizando...';
    else etaEl.textContent = _formatUploadEta((Date.now() - state.start) * (100 - rounded) / rounded);
  }

  async function _finishUploadModal(kind, detail) {
    const state = _uploadModalState;
    if (!state?.el) return;
    state.el.classList.toggle('is-done', kind === 'done');
    state.el.classList.toggle('is-error', kind === 'error');
    _updateUploadModal(kind === 'done' ? 100 : state.pct || 0, detail);
    await _sleep(kind === 'done' ? 650 : 1600);
    state.el.remove();
    _uploadModalState = null;
  }

  function _xhrJsonUpload({ method = 'POST', url, body, headers = {}, onProgress, timeoutMs = 0 }) {
    const xhr = new XMLHttpRequest();
    return new Promise((res, rej) => {
      xhr.upload.onprogress = e => {
        if (onProgress && e.lengthComputable) onProgress(e.loaded, e.total);
      };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
        if (xhr.status >= 200 && xhr.status < 300 && data.ok) {
          res(data);
          return;
        }
        const err = new Error(data.detail || data.error || 'Upload falhou: ' + xhr.status);
        err.status = xhr.status;
        err.data = data;
        if (xhr.status === 401 || isAuthError(data)) {
          err.auth = true;
          _isOpen = false;
          clearToken();
        }
        rej(err);
      };
      xhr.onerror = () => rej(new Error('Erro de rede no upload'));
      xhr.onabort = () => rej(new Error('Upload cancelado pelo navegador'));
      xhr.ontimeout = () => rej(new Error('Tempo esgotado no upload'));
      xhr.open(method, url);
      if (timeoutMs) xhr.timeout = timeoutMs;
      const authHeaders = applyAuthHeaders({});
      Object.keys(authHeaders).forEach(name => xhr.setRequestHeader(name, authHeaders[name]));
      Object.keys(headers || {}).forEach(name => xhr.setRequestHeader(name, headers[name]));
      xhr.send(body);
    });
  }

  async function _uploadSingleFile(file, onProgress) {
    _updateUploadModal(1, 'Enviando arquivo para o servidor...');
    return _xhrJsonUpload({
      method: 'POST',
      url: '/uploads/local-stream?prefix=uploads&validate=1&delete_if_invalid=1',
      body: file,
      headers: {
        'X-Filename': file.name || 'upload.bin',
        'X-File-Size': String(file.size || 0),
        'Content-Type': file.type || 'application/octet-stream',
      },
      onProgress: (loaded, total) => {
        if (total > 0) {
          const pct = Math.round(loaded / total * 100);
          _updateUploadModal(pct, 'Enviando arquivo para o servidor...');
          if (onProgress) onProgress(pct);
        }
      },
      timeoutMs: _uploadTimeoutMs(file.size || 0, 180000),
    });
  }

  async function _abortChunkUpload(uploadId) {
    if (!uploadId) return;
    try {
      await mpFetch('/uploads/chunk/abort', {
        method: 'POST',
        body: JSON.stringify({ upload_id: uploadId }),
      });
    } catch (_) {}
  }

  async function _sendChunkPart({ uploadId, partNumber, totalParts, blob, filename, uploadedBefore, totalSize, onProgress }) {
    const form = new FormData();
    form.append('upload_id', uploadId);
    form.append('part_number', String(partNumber));
    form.append('chunk', blob, filename || 'chunk.bin');
    return _xhrJsonUpload({
      method: 'POST',
      url: '/uploads/chunk/part',
      body: form,
      timeoutMs: _uploadTimeoutMs(blob.size || 0),
      onProgress: (loaded) => {
        if (!totalSize) return;
        const pct = Math.min(99, Math.round((uploadedBefore + loaded) / totalSize * 100));
        _updateUploadModal(pct, `Enviando parte ${partNumber} de ${totalParts}...`);
        if (onProgress) onProgress(pct);
      },
    });
  }

  async function _sendChunkPartWithRetry(args) {
    return _retryUploadStep(() => _sendChunkPart(args), 8);
  }

  async function _uploadChunkedFile(file, onProgress) {
    const totalSize = Math.max(0, file.size || 0);
    const chunkSize = LARGE_UPLOAD_CHUNK_SIZE;
    const totalParts = Math.max(1, Math.ceil(totalSize / chunkSize));
    _updateUploadModal(0, 'Preparando upload em partes...');
    const init = await _retryUploadStep(() => mpFetch('/uploads/chunk/init', {
      method: 'POST',
      body: JSON.stringify({
        filename: file.name || 'upload.bin',
        content_type: file.type || 'application/octet-stream',
        prefix: 'uploads',
        size: totalSize,
        chunk_size: chunkSize,
        total_parts: totalParts,
        validate: true,
        delete_if_invalid: true,
      }),
    }), 5);
    if (!init?.ok || !init.upload_id) {
      throw new Error(init?.detail || init?.error || 'Falha ao iniciar upload em partes');
    }

    const uploadId = init.upload_id;
    let uploaded = 0;
    try {
      for (let index = 0; index < totalParts; index++) {
        const start = index * chunkSize;
        const end = Math.min(totalSize, start + chunkSize);
        const blob = file.slice(start, end);
        _updateUploadModal(Math.round(start / Math.max(1, totalSize) * 100), `Enviando parte ${index + 1} de ${totalParts}...`);
        await _sendChunkPartWithRetry({
          uploadId,
          partNumber: index + 1,
          totalParts,
          blob,
          filename: file.name || 'upload.bin',
          uploadedBefore: start,
          totalSize,
          onProgress,
        });
        uploaded = end;
        if (totalSize > 0) {
          const pct = Math.min(99, Math.round(uploaded / totalSize * 100));
          _updateUploadModal(pct, `Parte ${index + 1} de ${totalParts} enviada.`);
          if (onProgress) onProgress(pct);
        }
      }
      _updateUploadModal(99, 'Finalizando envio e validando vídeo...');
      const done = await _retryUploadStep(() => _xhrJsonUpload({
        method: 'POST',
        url: '/uploads/chunk/complete',
        body: JSON.stringify({ upload_id: uploadId }),
        headers: { 'Content-Type': 'application/json' },
        timeoutMs: 10 * 60 * 1000,
      }), 8);
      if (!done?.ok || !done.object_key) {
        throw new Error(done?.detail || done?.error || 'Falha ao concluir upload em partes');
      }
      if (onProgress) onProgress(100);
      return done;
    } catch (err) {
      await _abortChunkUpload(uploadId);
      throw err;
    }
  }

  /* ── Public API ── */
  window.mpApi = {
    fetch: mpFetch,
    getToken,
    fmtTime: _fmtTime,
    fmtDate: _fmtDate,
    logout() { clearToken(); window.location.reload(); },

    /* ════════ MEDIA ════════ */

    async listMedia() {
      const prefixes = ['uploads', 'burns', 'teasers', 'autoeditor', 'cortes'];
      const results = await Promise.allSettled(
        prefixes.map(p => mpFetch(`/uploads/list?prefix=${p}&max_keys=500`))
      );
      const items = [];
      results.forEach((r, idx) => {
        if (r.status === 'fulfilled' && r.value?.items) {
          r.value.items.forEach(it => items.push({ ...it, category: prefixes[idx] }));
        }
      });
      items.sort((a, b) => (b.last_modified || '').localeCompare(a.last_modified || ''));
      return items.map(it => {
        const s = _mediaStatus(it);
        return {
          n: it.filename || it.object_key.split('/').pop(),
          s,
          tone: _mediaTone(s),
          tech: it.size_mb ? it.size_mb + ' MB' : '—',
          dur: '',
          size: it.size_mb ? it.size_mb + ' MB' : '',
          date: _fmtDate(it.last_modified),
          ts: it.last_modified || '',
          size_bytes: it.size_bytes || 0,
          object_key: it.object_key,
          public_url: it.public_url || '',
          category: it.category || s,
        };
      });
    },

    /* Metadados em lote (rápido ~10ms) — enriquece duração/resolução/fps */
    async metaBatch(keys) {
      const missing = keys.filter(k => !_metaCache[k]);
      if (missing.length) {
        try {
          const r = await mpFetch('/api/media-manager/metadata/batch', {
            method: 'POST', body: JSON.stringify({ object_keys: missing }),
          });
          Object.entries(r.items || {}).forEach(([k, v]) => { _metaCache[k] = v; });
        } catch (_) {}
      }
      const out = {};
      keys.forEach(k => { if (_metaCache[k]) out[k] = _metaCache[k]; });
      return out;
    },

    /* Thumbnail com cache + fila (máx 6 simultâneas — geração no servidor é cara) */
    thumbUrl(key) {
      if (_thumbCache[key]) return Promise.resolve(_thumbCache[key]);
      if (_thumbPending[key]) return _thumbPending[key];
      _thumbPending[key] = _thumbEnqueue(async () => {
        const r = await mpFetch('/api/media-manager/thumbnail-url?object_key=' + _enc(key));
        if (r.url) { _thumbCache[key] = r.url; return r.url; }
        throw new Error('no_thumb');
      }).finally(() => { delete _thumbPending[key]; });
      return _thumbPending[key];
    },

    async streamUrl(key) {
      const r = await mpFetch('/api/video-stream-url?object_key=' + _enc(key));
      return r.url || '';
    },
    async previewUrl(key) {
      const r = await mpFetch('/api/video-preview-url?object_key=' + _enc(key));
      return r.url || '';
    },
    async downloadUrl(key, filename) {
      const r = await mpFetch('/api/video-download-url?object_key=' + _enc(key) + '&filename=' + _enc(filename || 'video'));
      return r.url || '';
    },
    /* Dispara o download de forma confiável (sem popup-block) */
    async download(key, filename) {
      if (!key) { alert('Arquivo indisponível para download.'); return; }
      try {
        const url = await this.downloadUrl(key, filename);
        if (!url) throw new Error('sem url');
        const a = document.createElement('a');
        a.href = url.startsWith('http') ? url : (location.origin + url);
        a.download = filename || key.split('/').pop();
        document.body.appendChild(a); a.click(); a.remove();
      } catch (e) { alert('Falha no download: ' + e.message); }
    },
    async renameMedia(key, newName) {
      return mpFetch('/api/media-manager/rename', {
        method: 'POST', body: JSON.stringify({ object_key: key, new_name: newName }),
      });
    },
    async deleteMedia(key) {
      return mpFetch('/uploads/object?object_key=' + _enc(key), { method: 'DELETE' });
    },

    async uploadFile(file, onProgress) {
      await ensureAuth();
      _showUploadModal(file);
      const sendUpload = async () => {
        if ((file.size || 0) >= LARGE_UPLOAD_THRESHOLD) {
          return _uploadChunkedFile(file, onProgress);
        }
        return _retryUploadStep(() => _uploadSingleFile(file, onProgress), 5);
      };
      try {
        let data;
        try {
          data = await sendUpload();
        } catch (err) {
          if (_authErrorMessage(err)) {
            await showLogin();
            data = await sendUpload();
          } else {
            throw err;
          }
        }
        await _finishUploadModal('done', 'Upload concluído.');
        return data.object_key;
      } catch (err) {
        await _finishUploadModal('error', `Upload falhou: ${err?.message || err}`);
        throw err;
      }
    },

    /* ════════ RUNS / ANALYZE ════════ */

    async listRuns(limit = 60) {
      const data = await mpFetch(`/runs?limit=${limit}`);
      return (data.runs || []).map(r => ({
        id: r.id,
        date: _fmtDate(r.created_at),
        snip: r.original_filename || r.id.slice(0, 8),
        ok: !r.error,
        run_id: r.id,
        video_object_key: r.video_object_key,
      }));
    },

    async getRun(id) {
      const d = await mpFetch('/runs/' + _enc(id));
      let result = d.result_json, request = d.request_json;
      try { if (typeof result === 'string') result = JSON.parse(result); } catch { result = {}; }
      try { if (typeof request === 'string') request = JSON.parse(request); } catch { request = {}; }
      return { ...d, result: result || {}, request: request || {} };
    },

    async getRunFrames(id) {
      const d = await mpFetch('/runs/' + _enc(id) + '/frames');
      return d.frames || [];
    },

    async getRunSrt(id) {
      try { return await mpFetch('/runs/' + _enc(id) + '/srt'); }
      catch { return ''; }
    },

    /* Busca run existente para um object_key (evita re-analisar) */
    async findRunForKey(objectKey) {
      const data = await mpFetch('/runs?limit=100');
      const run = (data.runs || []).find(r => r.video_object_key === objectKey && !r.error);
      return run ? run.id : null;
    },

    /* Garante run para o arquivo: acha existente ou cria via analyze */
    async ensureRun(file, onStatus) {
      if (file.run_id) return file.run_id;
      if (onStatus) onStatus('Procurando análise existente…');
      const existing = await this.findRunForKey(file.object_key);
      if (existing) { file.run_id = existing; return existing; }
      if (onStatus) onStatus('Analisando vídeo (transcrição + IA)… pode levar alguns minutos');
      const r = await mpFetch('/analyze', {
        method: 'POST',
        body: JSON.stringify({
          video_object_key: file.object_key,
          original_filename: file.n || file.filename || '',
          limit: 20,
        }),
      });
      if (!r.run_id) throw new Error(r.error || 'Análise falhou');
      file.run_id = r.run_id;
      return r.run_id;
    },

    async analyze(payload) {
      return mpFetch('/analyze', { method: 'POST', body: JSON.stringify(payload) });
    },
    async analyzeStart(payload) {
      return mpFetch('/analyze/start', { method: 'POST', body: JSON.stringify(payload) });
    },
    async analyzeStatus(jobId) {
      return mpFetch('/analyze/status/' + _enc(jobId));
    },

    /* ════════ LEGENDA / LOGO (burn) ════════ */

    async burnSubtitles(payload) {
      return mpFetch('/api/burn-subtitles', { method: 'POST', body: JSON.stringify(payload) });
    },
    async burnStatus(jobId) {
      return mpFetch('/api/burn-subtitles/status/' + _enc(jobId));
    },
    async logoProfiles() {
      const r = await mpFetch('/settings/wizard/logo-profiles').catch(() => ({}));
      return r.profiles || [];
    },

    /* ════════ TEASER ════════ */

    async teaserGenerate(payload) {
      return mpFetch('/api/teaser/generate', { method: 'POST', body: JSON.stringify(payload) });
    },
    async teaserStatus(jobId) {
      return mpFetch('/api/teaser/status/' + _enc(jobId));
    },

    /* ════════ CORTES ════════ */

    async cortesGenerate(payload) {
      return mpFetch('/api/cortes/generate', { method: 'POST', body: JSON.stringify(payload) });
    },
    async cortesStatus(jobId) {
      return mpFetch('/api/cortes/status/' + _enc(jobId));
    },

    /* ════════ THUMBNAIL ════════ */

    async thumbnailHighres(payload) {
      return mpFetch('/api/thumbnail/highres', { method: 'POST', body: JSON.stringify(payload) });
    },

    /* ════════ COMPARE ════════ */

    async compare(payload) {
      return mpFetch('/llm/compare', { method: 'POST', body: JSON.stringify(payload) });
    },

    /* ════════ REFERÊNCIA (XVideos) ════════ */

    async xvSearch(type, query, limit = 20, sort = 'views') {
      if (type === 'pornstar') return mpFetch(`/xvideos/pornstar?name=${_enc(query)}&limit=${limit}`);
      if (type === 'channel') return mpFetch(`/xvideos/channel?name=${_enc(query)}&limit=${limit}`);
      return mpFetch(`/xvideos/search?query=${_enc(query)}&limit=${limit}&sort=${sort}`);
    },

    /* ════════ AUTOEDITOR ════════ */

    async listAeJobs(limit = 10) {
      const data = await mpFetch(`/api/auto-editor/jobs?limit=${limit}`);
      return data.jobs || [];
    },
    async startAutoEditor(payload) {
      return mpFetch('/api/auto-editor/start', { method: 'POST', body: JSON.stringify(payload) });
    },
    async aeStatus(jobId) {
      return mpFetch(`/api/auto-editor/status/${_enc(jobId)}`);
    },

    /* ════════ VIDEO ENHANCER ════════ */

    async enhancerStart(payload) {
      return mpFetch('/api/video-enhancer/enhance', { method: 'POST', body: JSON.stringify(payload) });
    },
    async enhancerStatus(jobId) {
      return mpFetch('/api/video-enhancer/status/' + _enc(jobId));
    },
    async enhancerJobs() {
      const r = await mpFetch('/api/video-enhancer/jobs').catch(() => ({}));
      return r.jobs || [];
    },

    /* ════════ TELEGRAM ════════ */

    async telegramSettings() {
      return mpFetch('/settings/telegram').catch(() => ({}));
    },
    async telegramSendNow(payload) {
      return mpFetch('/api/telegram/send-now', { method: 'POST', body: JSON.stringify(payload) });
    },

    /* ════════ PUBLISHER ════════ */

    async publisherPlatforms() {
      const r = await mpFetch('/api/publisher/supported-platforms').catch(() => ({}));
      return r.platforms || r.supported || [];
    },
    async publish(payload) {
      return mpFetch('/api/publisher/publish', { method: 'POST', body: JSON.stringify(payload) });
    },
    async publishStatus(jobId) {
      return mpFetch('/api/publisher/status/' + _enc(jobId));
    },
    async socialConfig() {
      return mpFetch('/api/social/config').catch(() => ({ platforms: [] }));
    },
    async socialAccounts(brandId, platform) {
      const qs = new URLSearchParams({ brandId: brandId || '' });
      if (platform) qs.set('platform', platform);
      const r = await mpFetch('/api/social/accounts?' + qs.toString()).catch(() => ({ accounts: [] }));
      return r.accounts || [];
    },
    async socialConnect(payload) {
      return mpFetch('/api/social/connect', { method: 'POST', body: JSON.stringify(payload) });
    },
    async socialDisconnect(id) {
      return mpFetch('/api/social/accounts/' + _enc(id), { method: 'DELETE' });
    },
    async socialCreatePost(payload) {
      return mpFetch('/api/social/posts', { method: 'POST', body: JSON.stringify(payload) });
    },
    async ensureStoryImage(postId) {
      return mpFetch('/api/posts/' + _enc(postId) + '/story-image', { method: 'POST', body: '{}' });
    },
    async socialPublish(postId) {
      return mpFetch('/api/social/posts/' + _enc(postId) + '/publish', { method: 'POST', body: JSON.stringify({}) });
    },
    async socialPostStatus(postId) {
      return mpFetch('/api/social/posts/' + _enc(postId) + '/status');
    },
    async socialPostMetrics(postId) {
      return mpFetch('/api/social/posts/' + _enc(postId) + '/metrics');
    },
    async socialCompetitors(brandId) {
      const r = await mpFetch('/api/social/competitors?brandId=' + _enc(brandId || '')).catch(() => ({ competitors: [] }));
      return r.competitors || [];
    },
    async socialAddCompetitor(payload) {
      return mpFetch('/api/social/competitors', { method: 'POST', body: JSON.stringify(payload) });
    },
    async socialAnalyzeCompetitor(id) {
      return mpFetch('/api/social/competitors/' + _enc(id) + '/analyze', { method: 'POST', body: JSON.stringify({}) });
    },
    async socialReferences(brandId) {
      const r = await mpFetch('/api/social/references?brandId=' + _enc(brandId || '')).catch(() => ({ references: [] }));
      return r.references || [];
    },
    async socialAddReference(payload) {
      return mpFetch('/api/social/references', { method: 'POST', body: JSON.stringify(payload) });
    },
    async socialWorkspace(brandId) {
      return mpFetch('/api/social/workspace?brandId=' + _enc(brandId || ''));
    },
    async socialAnalyzeBrand(brandId, payload) {
      return mpFetch('/api/social/brands/' + _enc(brandId) + '/analyze', { method: 'POST', body: JSON.stringify(payload || {}) });
    },
    async socialGenerateDrafts(brandId, payload) {
      return mpFetch('/api/social/brands/' + _enc(brandId) + '/generate-drafts', { method: 'POST', body: JSON.stringify(payload || {}) });
    },

    /* ════════ AGÊNCIA ════════ */

    async listCreators() {
      const data = await mpFetch('/api/creators');
      return (data.creators || []).map(c => ({
        n: c.name,
        h: '@' + (c.slug || c.name.toLowerCase().replace(/\s+/g, '')),
        subs: '—', rev: '—',
        tone: c.status === 'active' ? 'good' : c.status === 'trial' ? 'warn' : '',
        st: c.status || 'ativo',
        id: c.creator_id, creator_id: c.creator_id,
      }));
    },
    async getCreator(id) {
      return mpFetch('/api/creators/' + _enc(id));
    },
    async createCreator(payload) {
      return mpFetch('/api/creators', { method: 'POST', body: JSON.stringify(payload) });
    },
    async updateCreator(id, payload) {
      return mpFetch('/api/creators/' + _enc(id), { method: 'PUT', body: JSON.stringify(payload) });
    },
    async deleteCreator(id) {
      return mpFetch('/api/creators/' + _enc(id), { method: 'DELETE' });
    },
    async addCreatorPlatform(id, payload) {
      return mpFetch('/api/creators/' + _enc(id) + '/platforms', { method: 'POST', body: JSON.stringify(payload) });
    },
    async removeCreatorPlatform(id, platform) {
      return mpFetch('/api/creators/' + _enc(id) + '/platforms/' + _enc(platform), { method: 'DELETE' });
    },
    async creatorLoginCheck(id, platform) {
      return mpFetch('/api/creators/' + _enc(id) + '/login-check', { method: 'POST', body: JSON.stringify(platform ? { platform } : {}) });
    },
    async creatorScrapeStats(id) {
      return mpFetch('/api/creators/' + _enc(id) + '/scrape-stats', { method: 'POST', body: JSON.stringify({}) });
    },
    async creatorStats(id) {
      return mpFetch('/api/creators/' + _enc(id) + '/stats').catch(() => ({ stats: [] }));
    },
    async listDmca() {
      const data = await mpFetch('/api/dmca/infringements');
      return (data.infringements || []).map(i => ({
        url: i.infringing_url || '—',
        c: i.creator_name || i.creator_id || '—',
        s: i.status === 'removed' ? 'removido' : i.status === 'takedown_sent' ? 'takedown enviado' : 'detectado',
        tone: i.status === 'removed' || i.status === 'takedown_sent' ? 'good' : 'pri',
        d: _fmtDate(i.detected_at),
        rawStatus: i.status || 'detected',
        id: i.infringement_id || i.id,
      }));
    },
    async scanDmca(creatorId) {
      return mpFetch('/api/dmca/scan', { method: 'POST', body: JSON.stringify({ creator_id: creatorId || null }) });
    },
    async dmcaTakedown(id) {
      return mpFetch('/api/dmca/takedown/' + _enc(id), { method: 'POST', body: JSON.stringify({}) });
    },
    async listCalendar() {
      const data = await mpFetch('/api/calendar');
      return data.entries || [];
    },
    async calendarCreate(payload) {
      return mpFetch('/api/calendar', { method: 'POST', body: JSON.stringify(payload) });
    },
    async calendarUpdate(entryId, payload) {
      return mpFetch('/api/calendar/' + _enc(entryId), { method: 'PUT', body: JSON.stringify(payload) });
    },
    async calendarDelete(entryId) {
      return mpFetch('/api/calendar/' + _enc(entryId), { method: 'DELETE' });
    },
    async calendarAutoSchedule(payload) {
      return mpFetch('/api/calendar/auto-schedule', { method: 'POST', body: JSON.stringify(payload) });
    },
    async calendarOptimalTimes() {
      return mpFetch('/api/calendar/optimal-times').catch(() => ({}));
    },
    async listTrends() {
      const data = await mpFetch('/api/trends/briefings');
      return data.briefings || [];
    },
    async collectTrends() {
      return mpFetch('/api/trends/collect', { method: 'POST', body: JSON.stringify({}) });
    },
    async generateBriefing(creatorId) {
      return mpFetch(`/api/trends/generate-briefing-job/${_enc(creatorId)}`, { method: 'POST', body: JSON.stringify({}) });
    },
    async getBriefing(id) {
      return mpFetch('/api/trends/briefings/' + _enc(id));
    },
    async approveBriefing(id, notify = true) {
      return mpFetch('/api/trends/approve-briefing/' + _enc(id), { method: 'POST', body: JSON.stringify({ notify }) });
    },
    async sendBriefing(briefingId, channels) {
      return mpFetch('/api/trends/send-briefing', { method: 'POST', body: JSON.stringify({ briefing_id: briefingId, channels: channels || ['email'] }) });
    },
    async generateAllBriefings() {
      return mpFetch('/api/trends/generate-all-briefings', { method: 'POST', body: JSON.stringify({}) });
    },
    async dmcaBulkTakedown(infringementIds, contactEmail) {
      const body = { infringement_ids: infringementIds };
      if (contactEmail) body.contact_email = contactEmail;
      return mpFetch('/api/dmca/bulk-takedown', { method: 'POST', body: JSON.stringify(body) });
    },
    async dmcaUpdateStatus(id, status) {
      return mpFetch('/api/dmca/infringements/' + _enc(id) + '/status', { method: 'PATCH', body: JSON.stringify({ status }) });
    },
    async dmcaStats(creatorId) {
      const q = creatorId ? '?creator_id=' + _enc(creatorId) : '';
      return mpFetch('/api/dmca/stats' + q).catch(() => ({}));
    },
    async agencyOverview() {
      return mpFetch('/api/financial/agency-overview').catch(() => null);
    },
    async financialRecordEarning(payload) {
      return mpFetch('/api/financial/record-earning', { method: 'POST', body: JSON.stringify(payload) });
    },
    async financialEarnings(params) {
      const qs = new URLSearchParams(params || {}).toString();
      return mpFetch('/api/financial/earnings' + (qs ? '?' + qs : '')).catch(() => ({ earnings: [] }));
    },
    async financialGenerateReport(creatorId, month) {
      return mpFetch('/api/financial/generate-report', { method: 'POST', body: JSON.stringify({ creator_id: creatorId, month: month || null }) });
    },

    /* ════════ SETTINGS ════════ */

    async getTokens() {
      const r = await mpFetch('/settings/tokens').catch(() => ({}));
      return r.tokens || [];
    },
    async saveToken(provider, apiKey) {
      return mpFetch('/settings/tokens', {
        method: 'POST', body: JSON.stringify({ provider, api_key: apiKey }),
      });
    },

    /* ════════ CLIENTES (Companies) ════════ */

    async listCompanies() {
      const r = await mpFetch('/api/companies');
      return r.companies || [];
    },
    async getCompany(id) {
      const r = await mpFetch('/api/companies/' + _enc(id));
      return r.company || null;
    },
    async createCompany(payload) {
      const r = await mpFetch('/api/companies', { method: 'POST', body: JSON.stringify(payload) });
      return r.company;
    },
    async updateCompany(id, payload) {
      const r = await mpFetch('/api/companies/' + _enc(id), { method: 'PUT', body: JSON.stringify(payload) });
      return r.company;
    },
    async deleteCompany(id) {
      return mpFetch('/api/companies/' + _enc(id), { method: 'DELETE' });
    },
    async saveBrandKit(id, payload) {
      const r = await mpFetch('/api/companies/' + _enc(id) + '/brand-kit', { method: 'POST', body: JSON.stringify(payload) });
      return r.brand_kit;
    },
    async uploadLogo(id, file) {
      const fd = new FormData();
      fd.append('file', file);
      return mpFetch('/api/companies/' + _enc(id) + '/logo', { method: 'POST', body: fd, headers: {} });
    },
    async uploadReference(id, file) {
      const fd = new FormData();
      fd.append('file', file);
      return mpFetch('/api/companies/' + _enc(id) + '/references', { method: 'POST', body: fd, headers: {} });
    },
    async deleteReference(id, assetId) {
      return mpFetch('/api/companies/' + _enc(id) + '/references/' + _enc(assetId), { method: 'DELETE' });
    },
    async addCompetitor(id, payload) {
      const r = await mpFetch('/api/companies/' + _enc(id) + '/competitors', { method: 'POST', body: JSON.stringify(payload) });
      return r.competitor;
    },
    async removeCompetitor(id, compId) {
      return mpFetch('/api/companies/' + _enc(id) + '/competitors/' + _enc(compId), { method: 'DELETE' });
    },
    async listAllCompetitors() {
      const r = await mpFetch('/api/companies/all/competitors');
      return r.competitors || [];
    },

    /* ════════ PRODUTOS → SOLUÇÕES (fontes de conteúdo) ════════ */

    async listProducts(companyId) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/products').catch(() => ({ products: [] }));
      return r.products || [];
    },
    async createProduct(companyId, payload) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/products', { method: 'POST', body: JSON.stringify(payload) });
      return r.product;
    },
    async updateProduct(companyId, productId, payload) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/products/' + _enc(productId), { method: 'PUT', body: JSON.stringify(payload) });
      return r.product;
    },
    async deleteProduct(companyId, productId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/products/' + _enc(productId), { method: 'DELETE' });
    },
    async enrichProduct(companyId, productId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/products/' + _enc(productId) + '/enrich', { method: 'POST', body: JSON.stringify(payload || {}) });
    },
    async uploadProductKb(companyId, productId, file) {
      const fd = new FormData();
      fd.append('file', file);
      return mpFetch('/api/companies/' + _enc(companyId) + '/products/' + _enc(productId) + '/kb', { method: 'POST', body: fd, headers: {} });
    },
    async getProductKb(companyId, productId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/products/' + _enc(productId) + '/kb').catch(() => ({ chars: 0, preview: '' }));
    },
    async clearProductKb(companyId, productId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/products/' + _enc(productId) + '/kb', { method: 'DELETE' });
    },

    /* ════════ INFLUENCERS (por empresa) — cadastro + banco de imagem ════════ */
    async listInfluencers(companyId) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/influencers').catch(() => ({ influencers: [] }));
      return r.influencers || [];
    },
    async createInfluencer(companyId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencers', { method: 'POST', body: JSON.stringify(payload) });
    },
    async updateInfluencer(companyId, infId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencers/' + _enc(infId), { method: 'PUT', body: JSON.stringify(payload) });
    },
    async deleteInfluencer(companyId, infId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencers/' + _enc(infId), { method: 'DELETE' });
    },
    async uploadInfluencerPhoto(companyId, infId, file) {
      const fd = new FormData(); fd.append('file', file);
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencers/' + _enc(infId) + '/photo', { method: 'POST', body: fd, headers: {} });
    },
    async deleteInfluencerPhoto(companyId, infId, assetId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencers/' + _enc(infId) + '/photo/' + _enc(assetId), { method: 'DELETE' });
    },
    async listInfCompanies(companyId) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/influencer-companies').catch(() => ({ companies: [] }));
      return r.companies || [];
    },
    async createInfCompany(companyId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencer-companies', { method: 'POST', body: JSON.stringify(payload) });
    },
    async updateInfCompany(companyId, infcoId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencer-companies/' + _enc(infcoId), { method: 'PUT', body: JSON.stringify(payload) });
    },
    async deleteInfCompany(companyId, infcoId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencer-companies/' + _enc(infcoId), { method: 'DELETE' });
    },
    async uploadInfCompanyLogo(companyId, infcoId, file) {
      const fd = new FormData(); fd.append('file', file);
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencer-companies/' + _enc(infcoId) + '/logo', { method: 'POST', body: fd, headers: {} });
    },
    async deleteInfCompanyLogo(companyId, infcoId, assetId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/influencer-companies/' + _enc(infcoId) + '/logo/' + _enc(assetId), { method: 'DELETE' });
    },
    async listEvents(companyId) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/events').catch(() => ({ events: [] }));
      return r.events || [];
    },
    async createEvent(companyId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/events', { method: 'POST', body: JSON.stringify(payload) });
    },
    async updateEvent(companyId, eventId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/events/' + _enc(eventId), { method: 'PUT', body: JSON.stringify(payload) });
    },
    async deleteEvent(companyId, eventId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/events/' + _enc(eventId), { method: 'DELETE' });
    },
    async uploadEventLogo(companyId, eventId, file) {
      const fd = new FormData(); fd.append('file', file);
      return mpFetch('/api/companies/' + _enc(companyId) + '/events/' + _enc(eventId) + '/logo', { method: 'POST', body: fd, headers: {} });
    },
    async deleteEventLogo(companyId, eventId, assetId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/events/' + _enc(eventId) + '/logo/' + _enc(assetId), { method: 'DELETE' });
    },
    async uploadEventImage(companyId, eventId, file) {
      const fd = new FormData(); fd.append('file', file);
      return mpFetch('/api/companies/' + _enc(companyId) + '/events/' + _enc(eventId) + '/image', { method: 'POST', body: fd, headers: {} });
    },
    async deleteEventImage(companyId, eventId, assetId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/events/' + _enc(eventId) + '/image/' + _enc(assetId), { method: 'DELETE' });
    },
    async listOrganizers(companyId) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/event-organizers').catch(() => ({ organizers: [] }));
      return r.organizers || [];
    },
    async createOrganizer(companyId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/event-organizers', { method: 'POST', body: JSON.stringify(payload) });
    },
    async updateOrganizer(companyId, orgId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/event-organizers/' + _enc(orgId), { method: 'PUT', body: JSON.stringify(payload) });
    },
    async deleteOrganizer(companyId, orgId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/event-organizers/' + _enc(orgId), { method: 'DELETE' });
    },
    async uploadOrganizerLogo(companyId, orgId, file) {
      const fd = new FormData(); fd.append('file', file);
      return mpFetch('/api/companies/' + _enc(companyId) + '/event-organizers/' + _enc(orgId) + '/logo', { method: 'POST', body: fd, headers: {} });
    },
    async deleteOrganizerLogo(companyId, orgId, assetId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/event-organizers/' + _enc(orgId) + '/logo/' + _enc(assetId), { method: 'DELETE' });
    },
    async enrichCompany(companyId, payload) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/enrich', { method: 'POST', body: JSON.stringify(payload || {}) });
    },
    async uploadProductLogo(companyId, productId, file) {
      const fd = new FormData();
      fd.append('file', file);
      return mpFetch('/api/companies/' + _enc(companyId) + '/products/' + _enc(productId) + '/logo', { method: 'POST', body: fd, headers: {} });
    },
    async createSolution(companyId, productId, payload) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/products/' + _enc(productId) + '/solutions', { method: 'POST', body: JSON.stringify(payload) });
      return r.solution;
    },
    async updateSolution(companyId, solutionId, payload) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/solutions/' + _enc(solutionId), { method: 'PUT', body: JSON.stringify(payload) });
      return r.solution;
    },
    async deleteSolution(companyId, solutionId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/solutions/' + _enc(solutionId), { method: 'DELETE' });
    },

    /* ════════ MULTI-LOGO (empresa) ════════ */

    async listLogos(companyId) {
      const r = await mpFetch('/api/companies/' + _enc(companyId) + '/logos').catch(() => ({ logos: [] }));
      return r.logos || [];
    },
    async uploadLogoVariant(companyId, file, variant, primary) {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('variant', variant || 'light');
      fd.append('primary', primary ? 'true' : 'false');
      return mpFetch('/api/companies/' + _enc(companyId) + '/logos', { method: 'POST', body: fd, headers: {} });
    },
    async deleteLogo(companyId, assetId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/logos/' + _enc(assetId), { method: 'DELETE' });
    },

    /* ════════ NOTIFICAÇÕES (Evolution WhatsApp + SMTP) ════════ */

    async notifyConfig() {
      return mpFetch('/api/notify/config').catch(() => ({ whatsapp: {}, smtp: {} }));
    },
    async saveNotifyConfig(payload) {
      return mpFetch('/api/notify/config', { method: 'POST', body: JSON.stringify(payload) });
    },
    async notifyTest(payload) {
      return mpFetch('/api/notify/test', { method: 'POST', body: JSON.stringify(payload) });
    },
    async createApprovalLink(payload) {
      return mpFetch('/api/approvals/link', { method: 'POST', body: JSON.stringify(payload) });
    },

    /* ════════ POSTS (Approval) ════════ */

    async listPosts(status) {
      const r = await mpFetch('/api/posts' + (status ? '?status=' + status : ''));
      return r;
    },
    async createPost(payload) {
      const r = await mpFetch('/api/posts', { method: 'POST', body: JSON.stringify(payload) });
      return r.post;
    },
    async transitionPost(id, to) {
      const r = await mpFetch('/api/posts/' + _enc(id) + '/transition', { method: 'POST', body: JSON.stringify({ to }) });
      return r.post;
    },
    async deletePost(id) {
      return mpFetch('/api/posts/' + _enc(id), { method: 'DELETE' });
    },
    async updatePost(id, payload) {
      const r = await mpFetch('/api/posts/' + _enc(id), { method: 'PUT', body: JSON.stringify(payload) });
      return r.post || r;
    },
    async generatePostAI(payload) {
      const r = await mpFetch('/api/posts/generate-ai', { method: 'POST', body: JSON.stringify(payload) });
      return r.generated;
    },
    async generatePostImage(payload) {
      return mpFetch('/api/posts/generate-image', { method: 'POST', body: JSON.stringify(payload) });
    },
    async generateCarousel(payload) {
      return mpFetch('/api/posts/generate-carousel', { method: 'POST', body: JSON.stringify(payload) });
    },
    async generateBriefing(payload) {
      return mpFetch('/api/posts/generate-briefing', { method: 'POST', body: JSON.stringify(payload) });
    },
    async renderCarousel(payload) {
      return mpFetch('/api/posts/render-carousel', { method: 'POST', body: JSON.stringify(payload) });
    },
    async imageTemplates(companyId, type) {
      return mpFetch('/api/posts/image-templates?company_id=' + _enc(companyId || '') + '&type=' + _enc(type || 'carrossel')).catch(() => ({ templates: [] }));
    },
    async saveImageTemplate(payload) {
      return mpFetch('/api/posts/save-template', { method: 'POST', body: JSON.stringify(payload) });
    },
    async getCreativeConfig(companyId) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/creative-config');
    },
    async saveCreativeConfig(companyId, override) {
      return mpFetch('/api/companies/' + _enc(companyId) + '/creative-config', { method: 'POST', body: JSON.stringify({ creative_config: override }) });
    },
    async aiModels() {
      return mpFetch('/api/posts/ai-models').catch(() => ({ image: [] }));
    },
    async setAiModel(payload) {
      return mpFetch('/api/posts/ai-models', { method: 'POST', body: JSON.stringify(payload) });
    },
    async generatePostVideo(payload) {
      return mpFetch('/api/posts/generate-video', { method: 'POST', body: JSON.stringify(payload) });
    },
    async videoStatus(jobsCsv, companyId) {
      return mpFetch('/api/posts/video-status?jobs=' + _enc(jobsCsv) + '&company_id=' + _enc(companyId || ''));
    },
    async videoPreflight(companyId, theme, seconds) {
      return mpFetch('/api/posts/video-preflight', { method: 'POST', body: JSON.stringify({ company_id: companyId, theme: theme || '', seconds: seconds || 0 }) }).catch(() => ({ configured: false }));
    },
    async generateBrandedVideo(payload) {
      return mpFetch('/api/posts/generate-branded-video', { method: 'POST', body: JSON.stringify(payload) });
    },
    async brandedVideoStatus(companyId, job) {
      return mpFetch('/api/posts/branded-video-status', { method: 'POST', body: JSON.stringify({ company_id: companyId, job: job }) }).catch(() => ({ status: 'unknown' }));
    },
    async postStats() {
      return mpFetch('/api/posts/stats');
    },

    /* ════════ AI SETTINGS ════════ */

    async getAISettings() {
      return mpFetch('/api/ai-settings');
    },
    async saveAISettings(payload) {
      const r = await mpFetch('/api/ai-settings', { method: 'POST', body: JSON.stringify(payload) });
      return r;
    },
    async testAI() {
      return mpFetch('/api/ai-settings/test', { method: 'POST', body: JSON.stringify({}) });
    },
    async loadAIModels(section, provider, apiKey) {
      const r = await mpFetch('/api/ai-settings/models', { method: 'POST', body: JSON.stringify({ section, provider, api_key: apiKey || null }) });
      return r.models || [];
    },
    async getAIStatus() {
      return mpFetch('/api/ai-settings/status');
    },
    async getTrendsReport(companyId) {
      return mpFetch('/api/posts/trends/' + _enc(companyId));
    },
    async generateTrendsReport(companyId) {
      const r = await mpFetch('/api/posts/trends/' + _enc(companyId) + '/generate', { method: 'POST', body: JSON.stringify({}) });
      return r.report;
    },
  };

  window.__mpCheckAuth = checkAuth;
  window.__mpFmtTime = _fmtTime;
})();
