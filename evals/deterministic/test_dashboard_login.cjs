const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const REQUIRED = [
  'PU_OIDC_AUTHORIZATION_ENDPOINT',
  'PU_OIDC_TOKEN_ENDPOINT',
  'PU_OIDC_CLIENT_ID',
  'PU_OIDC_REDIRECT_URI',
  'PU_OIDC_ISSUER',
];

function jsonResponse(status, body) {
  const text = JSON.stringify(body);
  return {
    status,
    ok: status >= 200 && status < 300,
    async json() { return JSON.parse(text); },
    clone() { return jsonResponse(status, JSON.parse(text)); },
  };
}

function element(id) {
  return {
    id,
    hidden: id === 'login-config' || id === 'login-error',
    textContent: '',
    innerHTML: '',
    listeners: {},
    addEventListener(type, fn) {
      (this.listeners[type] ||= []).push(fn);
    },
    async click() {
      for (const fn of this.listeners.click || []) await fn();
    },
  };
}

function harness(route) {
  const classes = new Set(['logged-out']);
  const els = {
    'login-google': element('login-google'),
    'logout-btn': element('logout-btn'),
    'login-config': element('login-config'),
    'login-error': element('login-error'),
    view: element('view'),
    docklog: element('docklog'),
    'session-user': element('session-user'),
    sub: element('sub'),
    'logout-error': element('logout-error'),
    title: element('title'),
  };
  const calls = [];
  let assigned = null;
  let loops = 0;
  const context = {
    URL,
    console,
    calls,
    location: {assign(url) { assigned = String(url); }},
    localStorage: {
      setItem() { throw new Error('localStorage'); },
      getItem() { return null; },
    },
    sessionStorage: {setItem() { throw new Error('sessionStorage'); }},
    document: {
      body: {
        classList: {
          contains: (name) => classes.has(name),
          add: (name) => classes.add(name),
          remove: (name) => classes.delete(name),
        },
      },
      getElementById: (id) => els[id] || null,
      querySelectorAll: () => [],
    },
    fetch: async (url, init) => {
      calls.push({url, init: init || {}});
      return route(url, init || {});
    },
    startDashboardLoops() { loops += 1; },
    stopDashboardLoops() { loops = 0; },
  };
  context.window = context;
  vm.createContext(context);
  const root = path.join(__dirname, '../../pu/ops/static/js');
  for (const name of ['util.js', 'auth.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), context);
  }
  return {
    context,
    els,
    calls,
    assigned: () => assigned,
    loops: () => loops,
    loggedOut: () => classes.has('logged-out'),
  };
}

test('LG-01 logged-out boot stays on the login screen and drops the API payload', async () => {
  const h = harness((url) => jsonResponse(401, {
    error: url === '/api/auth/csrf' ? 'session_revoked' : 'no authenticated principal',
    leak: 'SECRET-USER',
  }));
  h.els.view.textContent = 'SECRET-FACT';
  h.els.docklog.textContent = 'SECRET-CHAT';
  h.els['session-user'].textContent = 'SECRET-USER';
  await h.context.bootDashboard();
  assert.equal(h.els.view.textContent, '');
  assert.equal(h.els.docklog.textContent, '');
  assert.equal(h.els['session-user'].textContent, '');
  assert.equal(vm.runInContext('D', h.context), null);
  assert.equal(vm.runInContext('puCsrf', h.context), '');
  assert.equal(h.loops(), 0);
  assert.equal(h.loggedOut(), true);
  assert.equal(JSON.stringify({
    view: h.els.view.textContent,
    dock: h.els.docklog.textContent,
    user: h.els['session-user'].textContent,
  }).includes('SECRET'), false);
});

test('LG-01 a later 401 or session_revoked clears data already on screen', async () => {
  const h = harness((url) => {
    if (url === '/api/data') {
      return jsonResponse(401, {error: 'no authenticated principal', home: 'SECRET-HOME'});
    }
    return jsonResponse(403, {error: 'session_revoked', rows: [['SECRET-FACT']]});
  });
  h.context.document.body.classList.remove('logged-out');
  h.els.view.textContent = 'SECRET-FACT';
  vm.runInContext('D = {home:"SECRET-HOME"}; puCsrf = "tok";', h.context);
  h.context.installAuthFetch();
  await h.context.fetch('/api/data');
  assert.equal(h.els.view.textContent, '');
  assert.equal(vm.runInContext('D', h.context), null);
  assert.equal(vm.runInContext('puCsrf', h.context), '');
  assert.equal(h.loggedOut(), true);

  h.context.document.body.classList.remove('logged-out');
  h.els.view.textContent = 'SECRET-FACT';
  vm.runInContext('D = {rows:["SECRET-FACT"]}; puCsrf = "tok";', h.context);
  await h.context.fetch('/api/query', {method: 'POST'});
  assert.equal(h.els.view.textContent, '');
  assert.equal(vm.runInContext('D', h.context), null);
  assert.equal(h.loggedOut(), true);
});

test('LG-02 the Google button navigates to authorization_url and a session shows the user', async () => {
  const url = 'https://idp.test/authorize?state=abc&nonce=n';
  const h = harness((target) => {
    if (target === '/api/auth/login') return jsonResponse(200, {authorization_url: url});
    if (target === '/api/auth/csrf') {
      return jsonResponse(200, {csrf_token: 'csrf-fixed', user_id: 'user-fixed'});
    }
    return jsonResponse(200, {});
  });
  await h.els['login-google'].click();
  assert.equal(h.assigned(), url);
  await h.context.bootDashboard();
  assert.equal(h.loops(), 1);
  assert.equal(h.loggedOut(), false);
  assert.match(h.els['session-user'].textContent, /user-fixed/);
  assert.equal(vm.runInContext('puCsrf', h.context), 'csrf-fixed');
});

test('LG-02 a javascript authorization url is not followed', async () => {
  const h = harness(() => jsonResponse(200, {authorization_url: 'javascript:alert(1)'}));
  await h.els['login-google'].click();
  assert.equal(h.assigned(), null);
  assert.match(h.els['login-error'].textContent, /không hợp lệ/i);
});

test('LG-03 postJSON sends the CSRF token fetched from /api/auth/csrf', async () => {
  const h = harness((url) => {
    if (url === '/api/auth/csrf') {
      return jsonResponse(200, {csrf_token: 'csrf-fixed', user_id: 'user-1'});
    }
    return jsonResponse(200, {ok: true});
  });
  await h.context.bootDashboard();
  await h.context.postJSON('/api/session', {action: 'new'});
  const post = h.calls.find((call) => call.url === '/api/session');
  assert.equal(post.init.method, 'POST');
  assert.equal(post.init.headers['X-CSRF-Token'], 'csrf-fixed');
});

test('LG-04 logout posts CSRF and the next 401 returns to the login screen', async () => {
  const h = harness((url) => {
    if (url === '/api/auth/csrf') {
      return jsonResponse(200, {csrf_token: 'csrf-fixed', user_id: 'user-1'});
    }
    if (url === '/api/auth/logout') return jsonResponse(200, {ok: true});
    return jsonResponse(401, {error: 'session_revoked', leak: 'SECRET-AFTER'});
  });
  await h.context.bootDashboard();
  h.els.view.textContent = 'SECRET-FACT';
  vm.runInContext('D = {facts:["SECRET-FACT"]}', h.context);
  await h.els['logout-btn'].click();
  const post = h.calls.find((call) => call.url === '/api/auth/logout');
  assert.equal(post.init.method, 'POST');
  assert.equal(post.init.headers['X-CSRF-Token'], 'csrf-fixed');
  assert.equal(h.els.view.textContent, '');
  assert.equal(h.els['session-user'].textContent, '');
  assert.equal(h.loggedOut(), true);
  assert.equal(h.loops(), 0);

  h.context.document.body.classList.remove('logged-out');
  h.els.view.textContent = 'SECRET-AFTER';
  vm.runInContext('D = {leak:"SECRET-AFTER"}; puCsrf = "csrf-fixed";', h.context);
  await h.context.fetch('/api/data');
  assert.equal(h.els.view.textContent, '');
  assert.equal(vm.runInContext('D', h.context), null);
  assert.equal(h.loggedOut(), true);
});

test('LG-06 oidc_not_configured lists the required variables and does not navigate', async () => {
  const h = harness(() => jsonResponse(400, {
    error: 'oidc_not_configured',
    required: REQUIRED,
    missing: REQUIRED,
  }));
  await h.els['login-google'].click();
  assert.equal(h.assigned(), null);
  assert.equal(h.els['login-config'].hidden, false);
  for (const name of REQUIRED) {
    assert.ok(h.els['login-config'].innerHTML.includes(name), name);
  }
});

test('LG-06 a payload without the variable list still shows the required names', async () => {
  const h = harness(() => jsonResponse(400, {error: 'oidc_not_configured'}));
  await h.els['login-google'].click();
  assert.equal(h.assigned(), null);
  for (const name of REQUIRED) {
    assert.ok(h.els['login-config'].innerHTML.includes(name), name);
  }
});
