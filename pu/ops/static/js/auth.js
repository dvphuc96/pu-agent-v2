// pu dashboard — login screen, CSRF, and session revoke (LOADS BEFORE main.js).
// Classic script, shared global scope. The session cookie stays HttpOnly.
// Nothing in this file persists a browser token.

const OIDC_REQUIRED_ENV = [
  "PU_OIDC_AUTHORIZATION_ENDPOINT",
  "PU_OIDC_TOKEN_ENDPOINT",
  "PU_OIDC_CLIENT_ID",
  "PU_OIDC_REDIRECT_URI",
  "PU_OIDC_ISSUER",
];

function installAuthFetch(){
  const root = typeof window !== "undefined" ? window : globalThis;
  if (root.__puFetchInstalled) return;
  const native = root.fetch.bind(root);
  root.fetch = async function(input, init){
    const res = await native(input, init);
    const url = typeof input === "string" ? input : String((input && input.url) || "");
    if (url.startsWith("/api/")) await noteAuthResponse(res);
    return res;
  };
  root.__puFetchInstalled = true;
}

async function noteAuthResponse(res){
  if (!res || (res.status !== 401 && res.status !== 403)) return;
  let body = null;
  try { body = await res.clone().json(); } catch (err) { body = null; }
  if (res.status === 401 || (body && body.error === "session_revoked")) enterLoggedOut();
}

function renderLoginError(message){
  const el = document.getElementById("login-error");
  if (!el) return;
  el.hidden = false;
  el.textContent = message;
}

function renderOidcMissing(body){
  const el = document.getElementById("login-config");
  if (!el) return;
  const required = body && Array.isArray(body.required) && body.required.length
    ? body.required : OIDC_REQUIRED_ENV;
  el.hidden = false;
  const items = required.map(name => `<li><code>${esc(name)}</code></li>`).join("");
  el.innerHTML = "<p>Chưa cấu hình OIDC. Cần đặt các biến sau:</p><ul>" + items + "</ul>";
  const missing = body && Array.isArray(body.missing) ? body.missing : [];
  if (missing.length && missing.join() !== required.join()){
    const absent = missing.map(name => `<li><code>${esc(name)}</code></li>`).join("");
    el.innerHTML += "<p>Hiện đang thiếu:</p><ul>" + absent + "</ul>";
  }
}

function enterLoggedOut(){
  if (typeof stopDashboardLoops === "function") stopDashboardLoops();
  D = null;
  puCsrf = "";
  if (typeof CHAT !== "undefined" && CHAT) CHAT.length = 0;
  if (typeof ACTIVE_CHAT !== "undefined") ACTIVE_CHAT = null;
  if (typeof evQueue !== "undefined" && evQueue) evQueue.length = 0;
  if (typeof BRIEF !== "undefined" && BRIEF){
    BRIEF.data = null;
    BRIEF.workspaces = [];
    BRIEF.error = "";
  }
  if (typeof NB !== "undefined" && NB){
    NB.items = null;
    NB.detail = null;
    NB.requested = null;
    NB.error = "";
  }
  document.body.classList.add("logged-out");
  ["view", "docklog", "session-user", "sub", "logout-error"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "";
  });
  const title = document.getElementById("title");
  if (title) title.textContent = "";
  document.querySelectorAll(
    ".sessmenu,.modelmenu,#nb-dialog,#chat-approval-dialog"
  ).forEach(el => el.remove());
}

function enterLoggedIn(session){
  puCsrf = (session && session.csrf_token) || "";
  document.body.classList.remove("logged-out");
  const user = document.getElementById("session-user");
  const label = session && session.user_id ? "Đang đăng nhập · " + session.user_id : "Đang đăng nhập";
  if (user) user.textContent = label;
  const err = document.getElementById("logout-error");
  if (err) err.textContent = "";
}

let loginBusy = false;
async function startGoogleLogin(){
  if (loginBusy) return;
  loginBusy = true;
  installAuthFetch();
  const config = document.getElementById("login-config");
  const error = document.getElementById("login-error");
  if (config){ config.hidden = true; config.innerHTML = ""; }
  if (error){ error.hidden = true; error.textContent = ""; }
  try {
    const res = await fetch("/api/auth/login", {cache: "no-store"});
    let body = {};
    try { body = await res.json(); } catch (err) { body = {}; }
    if (body.error === "oidc_not_configured"){
      renderOidcMissing(body);
      return;
    }
    if (!res.ok || !body.authorization_url){
      renderLoginError("Không bắt đầu được đăng nhập.");
      return;
    }
    let target = null;
    try { target = new URL(body.authorization_url); } catch (err) { target = null; }
    if (!target || (target.protocol !== "https:" && target.protocol !== "http:")){
      renderLoginError("Địa chỉ ủy quyền không hợp lệ.");
      return;
    }
    location.assign(target.href);
  } catch (err) {
    renderLoginError("Không kết nối được máy chủ đăng nhập.");
  } finally {
    loginBusy = false;
  }
}

async function logoutDashboard(){
  installAuthFetch();
  const err = document.getElementById("logout-error");
  if (err) err.textContent = "";
  let res;
  try {
    res = await fetch("/api/auth/logout", {
      method: "POST",
      headers: puMutateHeaders(),
      body: "{}",
      cache: "no-store",
    });
  } catch (e) {
    if (err) err.textContent = "Không đăng xuất được. Thử lại.";
    return;
  }
  let body = null;
  try { body = await res.clone().json(); } catch (e) { body = null; }
  if (res.ok || res.status === 401 || (body && body.error === "session_revoked")){
    enterLoggedOut();
    return;
  }
  if (err) err.textContent = "Không đăng xuất được. Thử lại.";
}

async function bootDashboard(){
  installAuthFetch();
  let res;
  try {
    res = await fetch("/api/auth/csrf", {cache: "no-store"});
  } catch (err) {
    enterLoggedOut();
    renderLoginError("Không kết nối được máy chủ.");
    return;
  }
  if (!res.ok){
    enterLoggedOut();
    return;
  }
  let body = {};
  try { body = await res.json(); } catch (err) { body = {}; }
  if (!body.csrf_token){
    enterLoggedOut();
    return;
  }
  enterLoggedIn(body);
  if (typeof startDashboardLoops === "function") startDashboardLoops();
}

function wireAuthControls(){
  const login = document.getElementById("login-google");
  if (login) login.addEventListener("click", () => startGoogleLogin());
  const logout = document.getElementById("logout-btn");
  if (logout) logout.addEventListener("click", () => logoutDashboard());
}
wireAuthControls();
