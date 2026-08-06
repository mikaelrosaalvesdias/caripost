const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function storage() {
  const values = new Map();
  return {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
}

function loadApi(response) {
  class FakeFormData {}
  const context = {
    window: {},
    localStorage: storage(),
    sessionStorage: storage(),
    FormData: FakeFormData,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    console,
    fetch: async () => ({
      status: response.status,
      ok: response.status >= 200 && response.status < 300,
      headers: { get: name => name.toLowerCase() === 'content-type' ? (response.contentType || '') : '' },
      json: async () => response.body,
      text: async () => typeof response.body === 'string' ? response.body : '',
    }),
  };
  vm.runInNewContext(fs.readFileSync('app/os/api.js', 'utf8'), context, { filename: 'api.js' });
  return context.window.mpApi;
}

test('JSON 422 is rejected with the API detail', async () => {
  const api = loadApi({ status: 422, contentType: 'application/json', body: { detail: 'site inválido' } });
  await assert.rejects(() => api.getCompany('c1'), /site inválido/);
});

test('text 502 is rejected instead of becoming a success', async () => {
  const api = loadApi({ status: 502, contentType: 'text/plain', body: 'proxy indisponível' });
  await assert.rejects(() => api.getCompany('c1'), /proxy indisponível/);
});

test('JSON 200 still resolves normally', async () => {
  const api = loadApi({ status: 200, contentType: 'application/json', body: { company: { id: 'c1' } } });
  assert.deepEqual(await api.getCompany('c1'), { id: 'c1' });
});

test('HTML error bodies are not dumped into the UI', async () => {
  const api = loadApi({ status: 502, contentType: 'text/html', body: '<html><body>proxy stack trace</body></html>' });
  await assert.rejects(() => api.getCompany('c1'), error => {
    assert.match(error.message, /Erro HTTP 502/);
    assert.doesNotMatch(error.message, /<html>/);
    return true;
  });
});

test('empty JSON success does not fail parsing', async () => {
  const api = loadApi({ status: 204, contentType: 'application/json', body: undefined });
  assert.equal(await api.getCompany('c1'), null);
});
