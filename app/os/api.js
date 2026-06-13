/* MetaPorn OS — API layer: auth, contexto global e todas as funções reais */
(function () {
  'use strict';

  const STORAGE_KEY = 'mp_session_token';
  const LEGACY_SESSION_KEY = 'mp_session';
  const LEGACY_API_KEY = 'adult_meta_api_key';
  let _loginShown = false;
  let _isOpen = null;

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

  async function mpFetch(url, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    if (!(opts.body instanceof FormData)) {
      headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    }
    applyAuthHeaders(headers);
    const res = await fetch(url, { ...opts, headers });
    if (res.status === 401) {
      if (_isOpen !== true) { clearToken(); showLogin(); }
      throw new Error('unauthorized');
    }
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) return res.json();
    return res.text();
  }

  /* ── Login overlay ── */
  function showLogin() {
    if (_loginShown) return;
    _loginShown = true;
    const el = document.createElement('div');
    el.id = 'mp-login-overlay';
    el.style.cssText = [
      'position:fixed;inset:0;z-index:99999;',
      'background:radial-gradient(900px 700px at 50% 38%,#13131f,#06060c 72%);',
      'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:24px;',
      'font-family:"Space Grotesk","Inter",sans-serif;'
    ].join('');
    el.innerHTML = `
      <div style="width:60px;height:60px;border-radius:18px;background:linear-gradient(140deg,#ff1744,#cc1038);display:grid;place-items:center;font-weight:800;font-size:32px;color:#fff;box-shadow:0 12px 40px rgba(255,23,68,.4);">M</div>
      <div style="text-align:center;">
        <div style="font-size:28px;font-weight:700;color:#fff;">MetaPorn OS</div>
        <div style="font-size:13px;color:#7c7c98;margin-top:4px;">Admin Platform</div>
      </div>
      <form id="mp-login-form" style="display:flex;flex-direction:column;gap:12px;width:320px;max-width:90vw;">
        <input id="mp-u" type="text" placeholder="Usuário" autocomplete="username" style="padding:12px 16px;border-radius:11px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:#fff;font-size:14px;outline:none;font-family:inherit;" />
        <input id="mp-p" type="password" placeholder="Senha" autocomplete="current-password" style="padding:12px 16px;border-radius:11px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:#fff;font-size:14px;outline:none;font-family:inherit;" />
        <button type="submit" style="padding:13px;border-radius:12px;border:none;background:linear-gradient(135deg,#ff1744,#cc1038);color:#fff;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;box-shadow:0 6px 20px rgba(255,23,68,.32);">Entrar</button>
        <div id="mp-login-err" style="color:#ff6b6b;font-size:13px;text-align:center;min-height:18px;"></div>
      </form>`;
    document.body.appendChild(el);
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
          el.remove();
        } else {
          errEl.textContent = data.error === 'invalid_credentials' ? 'Usuário ou senha incorretos.' : (data.error || 'Erro');
        }
      } catch (err) {
        errEl.textContent = 'Erro de conexão: ' + err.message;
      } finally { btn.textContent = 'Entrar'; btn.disabled = false; }
    });
    setTimeout(() => document.getElementById('mp-u')?.focus(), 100);
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
      }
      const res = await fetch('/runs?limit=1', { headers: applyAuthHeaders({}) });
      if (res.status === 401) { _isOpen = false; showLogin(); }
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
    if (it.category === 'burns') return 'burn';
    if (it.category === 'teasers') return 'teaser';
    if (it.category === 'autoeditor') return 'autoeditor';
    return 'original';
  }
  function _mediaTone(s) {
    return s === 'burn' ? 'good' : s === 'teaser' ? 'cy' : s === 'autoeditor' ? 'violet' : '';
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

  /* ── Public API ── */
  window.mpApi = {
    fetch: mpFetch,
    getToken,
    fmtTime: _fmtTime,
    fmtDate: _fmtDate,
    logout() { clearToken(); window.location.reload(); },

    /* ════════ MEDIA ════════ */

    async listMedia() {
      const prefixes = ['uploads', 'burns', 'teasers', 'autoeditor'];
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
      const xhr = new XMLHttpRequest();
      const data = await new Promise((res, rej) => {
        xhr.upload.onprogress = e => {
          if (onProgress && e.lengthComputable) onProgress(Math.round(e.loaded / e.total * 100));
        };
        xhr.onload = () => {
          let data = {};
          try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
          if (xhr.status >= 200 && xhr.status < 300 && data.ok && data.object_key) {
            res(data);
            return;
          }
          rej(new Error(data.detail || data.error || 'Upload falhou: ' + xhr.status));
        };
        xhr.onerror = () => rej(new Error('Erro de rede no upload'));
        xhr.onabort = () => rej(new Error('Upload cancelado pelo navegador'));
        xhr.open('POST', '/uploads/local-stream?prefix=uploads&validate=1&delete_if_invalid=1');
        const authHeaders = applyAuthHeaders({});
        Object.keys(authHeaders).forEach(name => xhr.setRequestHeader(name, authHeaders[name]));
        xhr.setRequestHeader('X-Filename', file.name || 'upload.bin');
        xhr.setRequestHeader('X-File-Size', String(file.size || 0));
        xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
        xhr.send(file);
      });
      return data.object_key;
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
    async listDmca() {
      const data = await mpFetch('/api/dmca/infringements');
      return (data.infringements || []).map(i => ({
        url: i.infringing_url || '—',
        c: i.creator_name || i.creator_id || '—',
        s: i.status === 'removed' ? 'removido' : i.status === 'takedown_sent' ? 'takedown enviado' : 'detectado',
        tone: i.status === 'removed' || i.status === 'takedown_sent' ? 'good' : 'pri',
        d: _fmtDate(i.detected_at),
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
    async agencyOverview() {
      return mpFetch('/api/financial/agency-overview').catch(() => null);
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
  };

  window.__mpCheckAuth = checkAuth;
  window.__mpFmtTime = _fmtTime;
})();
