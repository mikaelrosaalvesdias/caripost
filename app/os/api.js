/* MetaPorn OS — API layer */
(function () {
  'use strict';

  const STORAGE_KEY = 'mp_session_token';
  let _loginShown = false;
  let _isOpen = null; // null=unknown, true=open API, false=auth required

  function getToken() { return localStorage.getItem(STORAGE_KEY) || ''; }
  function setToken(t) { localStorage.setItem(STORAGE_KEY, t); }
  function clearToken() { localStorage.removeItem(STORAGE_KEY); }

  async function mpFetch(url, opts = {}) {
    const token = getToken();
    const headers = { ...(opts.headers || {}) };
    if (!(opts.body instanceof FormData)) {
      headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    }
    if (token) headers['x-session-token'] = token;
    const res = await fetch(url, { ...opts, headers });
    if (res.status === 401) {
      // Only show login if not already shown and not already in open mode
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
          setToken(data.token);
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

  /* Check if API needs auth — hit /runs (always accessible if open) */
  async function checkAuth() {
    try {
      const res = await fetch('/runs?limit=1');
      if (res.status === 401) { _isOpen = false; showLogin(); }
      else { _isOpen = true; } // open mode — no login needed
    } catch { _isOpen = true; } // network error — try anyway
  }

  /* ── Helpers ── */
  function _fmtDate(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' }); }
    catch { return iso.slice(0, 16); }
  }
  function _fmtTime(sec) {
    if (sec == null || sec === '') return '—';
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }
  function _mediaStatus(it) {
    const key = (it.object_key || '').toLowerCase();
    const fn = (it.filename || '').toLowerCase();
    if (key.includes('/burns/') || fn.includes('_burn') || fn.includes('_queimado')) return 'burn';
    if (key.includes('/teasers/') || fn.includes('_teaser')) return 'teaser';
    if (fn.includes('autoeditor') || fn.includes('compil')) return 'autoeditor';
    if (it.category === 'burns') return 'burn';
    if (it.category === 'teasers') return 'teaser';
    return 'original';
  }
  function _mediaTone(s) {
    return s === 'burn' ? 'good' : s === 'teaser' ? 'cy' : s === 'autoeditor' ? 'violet' : '';
  }

  /* ── Public API ── */
  window.mpApi = {
    fetch: mpFetch,
    getToken,
    logout() { clearToken(); window.location.reload(); },

    /* Media files — fetches uploads + burns + teasers in parallel */
    async listMedia() {
      const prefixes = ['uploads', 'burns', 'teasers'];
      const results = await Promise.allSettled(
        prefixes.map(p => mpFetch(`/uploads/list?prefix=${p}&max_keys=150`))
      );
      const items = [];
      results.forEach(r => {
        if (r.status === 'fulfilled' && r.value?.items) {
          r.value.items.forEach(it => items.push(it));
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
          dur: it.duration_label || '',
          size: it.size_mb ? it.size_mb + ' MB' : '',
          date: _fmtDate(it.last_modified),
          object_key: it.object_key,
          public_url: it.public_url || '',
          category: it.category || s,
        };
      });
    },

    /* Runs list */
    async listRuns(limit = 40) {
      const data = await mpFetch(`/runs?limit=${limit}`);
      return (data.runs || []).map(r => ({
        id: r.id,
        date: _fmtDate(r.created_at),
        snip: r.original_filename || r.title || r.id.slice(0, 8),
        ok: !r.error,
        run_id: r.id,
        video_object_key: r.video_object_key,
      }));
    },

    /* Creators */
    async listCreators() {
      const data = await mpFetch('/api/creators');
      return (data.creators || []).map(c => ({
        n: c.name,
        h: '@' + (c.slug || c.name.toLowerCase().replace(/\s+/g, '')),
        subs: '—',
        rev: '—',
        tone: c.status === 'active' ? 'good' : c.status === 'trial' ? 'warn' : '',
        st: c.status || 'ativo',
        id: c.creator_id,
        creator_id: c.creator_id,
      }));
    },

    /* DMCA */
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

    /* AutoEditor jobs */
    async listAeJobs(limit = 10) {
      const data = await mpFetch(`/api/auto-editor/jobs?limit=${limit}`);
      return data.jobs || [];
    },

    /* AutoEditor start */
    async startAutoEditor(payload) {
      return mpFetch('/api/auto-editor/start', { method: 'POST', body: JSON.stringify(payload) });
    },

    /* AutoEditor status */
    async aeStatus(jobId) {
      return mpFetch(`/api/auto-editor/status/${jobId}`);
    },

    /* Upload (presign + PUT) */
    async uploadFile(file, onProgress) {
      const ext = file.name.split('.').pop().toLowerCase();
      const presign = await mpFetch('/uploads/presign', {
        method: 'POST',
        body: JSON.stringify({ filename: file.name, content_type: file.type || 'video/mp4' }),
      });
      if (!presign.upload_url) throw new Error('Falha ao obter URL de upload');
      const xhr = new XMLHttpRequest();
      await new Promise((res, rej) => {
        xhr.upload.onprogress = e => onProgress && onProgress(Math.round(e.loaded / e.total * 100));
        xhr.onload = () => (xhr.status < 300 ? res() : rej(new Error('Upload falhou: ' + xhr.status)));
        xhr.onerror = () => rej(new Error('Erro de rede no upload'));
        xhr.open('PUT', presign.upload_url);
        xhr.setRequestHeader('Content-Type', file.type || 'video/mp4');
        xhr.send(file);
      });
      return presign.object_key;
    },

    /* Financial overview */
    async agencyOverview() {
      return mpFetch('/api/financial/agency-overview').catch(() => null);
    },

    /* Calendar entries */
    async listCalendar() {
      const data = await mpFetch('/api/calendar');
      return data.entries || [];
    },

    /* Trends briefings */
    async listTrends() {
      const data = await mpFetch('/api/trends/briefings');
      return data.briefings || [];
    },

    /* Collect global trends */
    async collectTrends() {
      return mpFetch('/api/trends/collect', { method: 'POST', body: JSON.stringify({}) });
    },

    /* Generate trend briefing for creator */
    async generateBriefing(creatorId) {
      return mpFetch(`/api/trends/generate-briefing-job/${creatorId}`, { method: 'POST', body: JSON.stringify({}) });
    },

    /* DMCA scan */
    async scanDmca(creatorId) {
      return mpFetch('/api/dmca/scan', { method: 'POST', body: JSON.stringify({ creator_id: creatorId || null }) });
    },

    /* DMCA takedown */
    async dmcaTakedown(infringementId) {
      return mpFetch(`/api/dmca/takedown/${infringementId}`, { method: 'POST', body: JSON.stringify({}) });
    },

    /* Publisher platforms */
    async listPublisher() {
      return mpFetch('/api/publishers').catch(() => ({ publishers: [] }));
    },

    /* Telegram groups */
    async listTelegramGroups() {
      return mpFetch('/api/telegram/groups').catch(() => ({ groups: [] }));
    },

    /* Settings / tokens */
    async getTokens() {
      return mpFetch('/api/settings/all').catch(() => ({}));
    },
  };

  window.__mpCheckAuth = checkAuth;
  window.__mpFmtTime = _fmtTime;
})();
