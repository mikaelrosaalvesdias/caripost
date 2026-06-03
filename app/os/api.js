/* MetaPorn OS — API layer: auth + fetch helpers */
(function () {
  'use strict';

  const STORAGE_KEY = 'mp_session_token';

  function getToken() { return localStorage.getItem(STORAGE_KEY) || ''; }
  function setToken(t) { localStorage.setItem(STORAGE_KEY, t); }
  function clearToken() { localStorage.removeItem(STORAGE_KEY); }

  async function mpFetch(url, opts = {}) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    if (token) headers['x-session-token'] = token;
    const res = await fetch(url, { ...opts, headers });
    if (res.status === 401) { clearToken(); showLogin(); throw new Error('unauthorized'); }
    return res.json();
  }

  /* ── Login overlay (shown when no valid session) ── */
  function showLogin() {
    if (document.getElementById('mp-login-overlay')) return;
    const el = document.createElement('div');
    el.id = 'mp-login-overlay';
    el.style.cssText = `
      position:fixed;inset:0;z-index:99999;
      background:radial-gradient(900px 700px at 50% 38%,#13131f,#06060c 72%);
      display:flex;flex-direction:column;align-items:center;justify-content:center;gap:24px;
      font-family:'Space Grotesk','Inter',sans-serif;
    `;
    el.innerHTML = `
      <div style="width:60px;height:60px;border-radius:18px;background:linear-gradient(140deg,#ff1744,#cc1038);display:grid;place-items:center;font-weight:800;font-size:32px;color:#fff;box-shadow:0 12px 40px rgba(255,23,68,.4);">M</div>
      <div style="text-align:center;">
        <div style="font-size:28px;font-weight:700;color:#fff;letter-spacing:.5px;">MetaPorn OS</div>
        <div style="font-size:13px;color:#7c7c98;margin-top:4px;">Admin Platform</div>
      </div>
      <form id="mp-login-form" style="display:flex;flex-direction:column;gap:12px;width:320px;max-width:90vw;">
        <input id="mp-login-user" type="text" placeholder="Usuário" autocomplete="username" style="
          padding:12px 16px;border-radius:11px;border:1px solid rgba(255,255,255,.12);
          background:rgba(255,255,255,.06);color:#fff;font-size:14px;outline:none;font-family:inherit;
        " />
        <input id="mp-login-pass" type="password" placeholder="Senha" autocomplete="current-password" style="
          padding:12px 16px;border-radius:11px;border:1px solid rgba(255,255,255,.12);
          background:rgba(255,255,255,.06);color:#fff;font-size:14px;outline:none;font-family:inherit;
        " />
        <button type="submit" style="
          padding:13px;border-radius:12px;border:none;
          background:linear-gradient(135deg,#ff1744,#cc1038);color:#fff;font-size:15px;
          font-weight:700;cursor:pointer;font-family:inherit;
          box-shadow:0 6px 20px rgba(255,23,68,.32);
        ">Entrar</button>
        <div id="mp-login-err" style="color:#ff6b6b;font-size:13px;text-align:center;min-height:18px;"></div>
      </form>
    `;
    document.body.appendChild(el);
    const form = el.querySelector('#mp-login-form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const user = el.querySelector('#mp-login-user').value.trim();
      const pass = el.querySelector('#mp-login-pass').value;
      const errEl = el.querySelector('#mp-login-err');
      errEl.textContent = '';
      const btn = form.querySelector('button');
      btn.textContent = 'Entrando…'; btn.disabled = true;
      try {
        const res = await fetch('/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: user, password: pass }),
        });
        const data = await res.json();
        if (data.ok && data.token) {
          setToken(data.token);
          el.remove();
          window.__mpApiReady && window.__mpApiReady();
        } else {
          errEl.textContent = data.error === 'invalid_credentials' ? 'Usuário ou senha incorretos.' : (data.error || 'Erro desconhecido');
        }
      } catch (err) {
        errEl.textContent = 'Erro de conexão: ' + err.message;
      } finally {
        btn.textContent = 'Entrar'; btn.disabled = false;
      }
    });
    // focus user field
    setTimeout(() => el.querySelector('#mp-login-user').focus(), 100);
  }

  async function checkSession() {
    const token = getToken();
    if (!token) { showLogin(); return false; }
    try {
      const res = await fetch('/auth/me', { headers: { 'x-session-token': token } });
      if (res.status === 401) { clearToken(); showLogin(); return false; }
      return true;
    } catch {
      return false; // offline? let it try anyway
    }
  }

  /* ── Public API ── */
  window.mpApi = {
    fetch: mpFetch,
    getToken,
    logout() { clearToken(); window.location.reload(); },

    /* Media files */
    async listMedia(category = 'all') {
      const prefix = category === 'burns' ? 'burns' : category === 'teasers' ? 'teasers' : 'uploads';
      const data = await mpFetch(`/uploads/list?prefix=${prefix}&max_keys=200`);
      if (!data.ok) return [];
      return (data.items || []).map(it => ({
        n: it.filename || it.object_key.split('/').pop(),
        s: _mediaStatus(it),
        tone: _mediaTone(it),
        tech: _mediaTech(it),
        dur: it.duration || '',
        size: it.size_mb ? it.size_mb + ' MB' : '',
        date: it.last_modified ? new Date(it.last_modified).toLocaleString('pt-BR', { day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit' }) : '',
        object_key: it.object_key,
        public_url: it.public_url || '',
      }));
    },

    /* Runs list */
    async listRuns(limit = 40) {
      const data = await mpFetch(`/runs?limit=${limit}`);
      return (data.runs || data || []).map(r => ({
        id: r.run_id || r.id,
        date: r.created_at ? new Date(r.created_at).toLocaleString('pt-BR', { day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit' }) : '—',
        snip: r.title || r.prompt_snippet || r.object_key || '(sem título)',
        ok: r.status !== 'error',
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
      }));
    },

    /* Financial overview */
    async agencyOverview() {
      const data = await mpFetch('/api/financial/agency-overview');
      return data;
    },

    /* DMCA infringements */
    async listDmca() {
      const data = await mpFetch('/api/dmca/infringements');
      return (data.infringements || []).map(i => ({
        url: i.infringing_url || i.url,
        c: i.creator_name || i.creator_id || '—',
        s: i.status || 'detectado',
        tone: i.status === 'removed' ? 'good' : i.status === 'takedown_sent' ? 'good' : 'pri',
        d: i.detected_at ? new Date(i.detected_at).toLocaleDateString('pt-BR') : '—',
        id: i.infringement_id || i.id,
      }));
    },

    /* AutoEditor jobs */
    async listAeJobs(limit = 20) {
      const data = await mpFetch(`/api/auto-editor/jobs?limit=${limit}`);
      return data.jobs || data || [];
    },
  };

  window.__mpCheckSession = checkSession;

  function _mediaStatus(it) {
    const key = (it.object_key || '').toLowerCase();
    if (key.includes('/burns/') || key.includes('_burn')) return 'burn';
    if (key.includes('/teasers/') || key.includes('_teaser')) return 'teaser';
    if (key.includes('autoeditor') || key.includes('compil')) return 'autoeditor';
    return 'original';
  }
  function _mediaTone(it) {
    const s = _mediaStatus(it);
    if (s === 'burn') return 'good';
    if (s === 'teaser') return 'cy';
    if (s === 'autoeditor') return 'violet';
    return '';
  }
  function _mediaTech(it) {
    const parts = [];
    if (it.width && it.height) parts.push(`${it.height}p`);
    if (it.duration_seconds) {
      const m = Math.floor(it.duration_seconds / 60), s = Math.round(it.duration_seconds % 60);
      parts.push(`${m}:${String(s).padStart(2,'0')}`);
    }
    return parts.join(' · ') || (it.size_mb ? it.size_mb + ' MB' : '—');
  }
})();
