// pu dashboard — formatters + chat card renderers + chatlog + streaming + send.
// Split out of app.js: classic <script>, shared global scope (no build
// step, no modules). Load order + rules: static/README.md.

const money = n => "$" + (n < 0.01 ? n.toFixed(4) : n.toFixed(2));
const secs = ms => ms==null ? "—" : (ms/1000).toFixed(1)+"s";

const gateBadge = g => !g ? "" :
  `<span class="badge ${g.decision==="retrieve"?"retrieve":""}">gate · ${esc(g.decision)}</span><span class="meta" style="margin:0">${esc(g.reason||"")}</span>`;

// A tool call renders as a status row (dot + one-line summary); the raw output
// hides behind a disclosure so an ugly osascript error never floods the page.
const toolRow = x => `<div class="tool ${x.status||"ok"}">
  <div class="tool-head"><span class="dot ${x.status||"ok"}"></span><code>${esc(x.tool)}</code>
    ${x.summary?`<span style="color:var(--ink2)">${esc(x.summary)}</span>`:""}
    ${x.approval_id?`<a class="reveal" onclick="location.hash='approvals/${esc(x.approval_id)}'">approval ${esc(x.approval_status||'pending')}</a>`:""}</div>
  ${x.output!==undefined?`<details><summary>args &amp; raw output</summary>
    <pre>${esc(x.tool)}(${esc(JSON.stringify(x.args,null,1))})\n\n${esc(x.output)}</pre>
  </details>`:""}
</div>`;

// A stored history row -> a CHAT item. Assistant rows with saved telemetry
// (meta: gate/latency/iterations/tools) render as the FULL turn card, so a
// reopened thread looks just like when it was live. Rows without meta (from
// before this was saved, or another gateway) fall back to a plain card.
function histItem(m){
  if (m.role === "user") return {role:"user", text:m.content};
  if (m.meta) return {role:"pu", reply:m.content, gate:m.meta.gate,
                      graph:m.meta.graph,
                      tools:m.meta.tools, iterations:m.meta.iterations,
                      latency_ms:m.meta.latency_ms, response_timing:m.meta.response_timing, model:m.meta.model,
                      provider:m.meta.provider, usage:m.meta.usage, cancelled:m.meta.cancelled, reports:m.meta.reports||[], inbox_validation:m.meta.inbox_validation||[]};
  // Reports are persisted with the turn; approval controls survive reloads.
  return {role:"pu", reply:m.content, historical:true};
}

const turnCard = t => `<div class="card">
  <div class="u">${esc(t.user_message)}</div>
  <div class="meta" style="margin-top:4px">${gateBadge(t.gate)}</div>
  ${(t.tools||[]).map(toolRow).join("")}
  <div class="r">${renderMarkdown(t.reply)}</div>
  <div class="meta">${esc((t.ts||"").replace("T"," ").slice(0,19))} · ${secs(t.latency_ms)} · ${t.iterations??"?"} iter · ${money(t.cost||0)}${t.consolidation?` · consolidated ${t.consolidation.new_facts} fact(s)`:""}</div>
</div>`;

const table = (heads, rows) => rows.length
  ? `<div class="card" style="padding:4px 8px"><table><tr>${heads.map(h=>`<th>${h}</th>`).join("")}</tr>${rows.join("")}</table></div>`
  : `<div class="card empty">nothing here yet</div>`;

const gateSplit = s => {
  if (!(s.gate_skips + s.gate_retrieves))
    return `<div class="splitbar"><div class="seg-skip" style="width:100%;opacity:.35"></div></div>
      <div class="meta" style="margin-top:6px">no turns yet — send a message and the gate starts deciding</div>`;
  const tot = s.gate_skips + s.gate_retrieves;
  const skipPct = Math.round(s.gate_skips/tot*100), retPct = 100-skipPct;
  // only label a segment when it's wide enough to fit the text — otherwise a
  // 0%/tiny segment spills its label past the bar (the "0 retri" bug).
  const seg = (cls, n, label, pct) =>
    `<div class="${cls}" style="width:${pct}%">${pct>=14?`${n} ${label}`:""}</div>`;
  return `<div class="splitbar">
    ${seg("seg-skip", s.gate_skips, "skipped", skipPct)}
    ${seg("seg-ret", s.gate_retrieves, "retrieved", retPct)}
  </div><div class="meta" style="margin-top:6px">the retrieval gate skipped memory on ${skipPct}% of turns — that's latency and bias saved</div>`;
};

// --- Chat gateway: type here, watch the harness run (turns kept in memory)
const CHAT = [];
let ACTIVE_CHAT = null;
function chatElapsedLabel(milliseconds){
  const total=Math.max(0,Math.floor(milliseconds/1000));
  const seconds=String(total%60).padStart(2,'0'),minutes=String(Math.floor(total/60)%60).padStart(2,'0');
  return total>=3600?`${Math.floor(total/3600)}:${minutes}:${seconds}`:`${minutes}:${seconds}`;
}
function chatElapsedMarkup(turn){
  const milliseconds=turn.pending?Date.now()-turn.started:turn.elapsed_ms;
  if(!Number.isFinite(milliseconds))return '';
  return `<div class="chat-response-time"${turn.pending?' data-chat-elapsed role="timer" aria-live="off"':''}>${turn.pending?'Đang xử lý':turn.cancelled?'Đã dừng sau':'Thời gian phản hồi'} · ${chatElapsedLabel(milliseconds)}</div>`;
}
function chatSendIcon(){
  return ACTIVE_CHAT?.pending.pending?'<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>':nbIcon('arrow');
}
function syncChatControls(){
  const active=ACTIVE_CHAT?.pending.pending,stopping=active&&ACTIVE_CHAT.pending.stopping;
  document.querySelectorAll('[data-chat-send],#dsend').forEach(button=>{
    button.innerHTML=chatSendIcon();button.disabled=Boolean(stopping);
    button.setAttribute('aria-label',stopping?'Đang dừng':active?'Dừng trả lời':'Gửi tin nhắn');
    button.title=stopping?'Đang dừng':active?'Dừng trả lời':'Gửi tin nhắn';
    button.classList.toggle('chat-stop',Boolean(active));
  });
}
function chatComposerAction(inputId){
  if(ACTIVE_CHAT?.pending.pending)return stopChat();
  return sendChat(document.getElementById(inputId));
}
async function stopChat(){
  const active=ACTIVE_CHAT;
  if(!active||!active.pending.pending||active.stopSent)return;
  active.pending.stopping=true;delete active.pending.controlError;syncChatControls();syncChatLogs();
  if(!active.ready)return;
  active.stopSent=true;
  try{
    const result=await postJSON('/api/chat/stop',{request_id:active.requestId});
    if(result.error)throw new Error(result.error);
  }catch(error){
    if(ACTIVE_CHAT!==active||!active.pending.pending)return;
    active.stopSent=false;active.pending.stopping=false;
    active.pending.controlError='Chưa gửi được yêu cầu dừng. Anh thử lại nhé.';
    syncChatLogs();
  }
}
// The gate → tools → reply stage strip, shared by the live card and the
// completed/replayed card so the markup can't drift. `live` lights stages up
// (gate flips to done once decided, reply "on" once text streams); otherwise
// every stage is done and the strip carries the .tele class (hidden by the
// stats toggle). (.stages is flexbox, so inter-span whitespace is irrelevant.)
function stagesRow(t, live){
  const gateCls = live ? (t.gate ? "done" : "on") : "done";
  const replyCls = live ? (t.stream ? "on" : "") : "done";
  const tools = (t.tools||[]).map(x => toolChip(x.tool)).join("");
  // graph chip first — the front door. A quick graph turn has NO gate stage
  // (memory retrieval never ran), so the gate chip is honest and disappears.
  const graph = (t.graph && t.graph.route)
    ? `<span class="stage done">graph · ${esc(t.graph.route)}</span>` : "";
  const gate = (t.graph && t.graph.route === "quick") ? ""
    : `<span class="stage ${gateCls}">gate${t.gate?` · ${esc(t.gate.decision)}`:""}</span>`;
  return `<div class="stages${live?"":" tele"}">`
    + graph + gate + tools + `<span class="stage ${replyCls}">reply</span></div>`;
}
const usageFooter = t => t.usage
  ? `<div class="meta">usage · ${t.provider?`${esc(t.provider)} · `:""}${Number(t.usage.in||0).toLocaleString()} in / ${Number(t.usage.out||0).toLocaleString()} out (${t.usage.calls||0} LLM call${t.usage.calls===1?"":"s"})</div>`
  : "";

// The per-turn telemetry footer: seconds · iterations · model · consolidation.
const teleFooter = t => `<div class="meta tele">${secs(t.latency_ms)} · ${t.iterations??"?"} iter${
  t.model?` · ${esc(t.model)}`:""}${t.consolidation?` · consolidated ${t.consolidation.new_facts} fact(s)`:""}</div>`;

const chatTurnCard = t => `<div class="card chat-answer">
  <div class="chat-author"><span class="chat-avatar" aria-hidden="true">P</span> PU <span>Trợ lý của anh</span></div>
  <button class="msg-copy" onclick="copyMsg(this)" data-text="${esc(t.reply)}" title="Sao chép câu trả lời">Sao chép</button>
  ${(t.gate||t.graph)?`${stagesRow(t, false)}
    <div class="meta tele" style="margin:0 0 6px">${esc((t.gate&&t.gate.reason)||(t.graph&&t.graph.reason)||"")}</div>`:""}
  ${nodesRow(t)}
  ${(t.tools||[]).length?`<div class="tele">${(t.tools||[]).map(toolRow).join("")}</div>`:""}
  <div class="r" style="margin-top:8px">${renderMarkdown(t.reply)}</div>
  ${chatSourcesMarkup(t.reply)}
  ${t.cancelled?'<p class="chat-stop-note">Đã dừng theo yêu cầu.</p>':''}
  ${chatElapsedMarkup(t)}
  ${typeof chatReportActions==='function'?chatReportActions(t):''}
  ${typeof chatValidationDetails==='function'?chatValidationDetails(t):''}
  ${usageFooter(t)}
  ${teleFooter(t)}
</div>`;

// While a turn runs we stream it live: stages light up as the harness reaches
// them, and the reply text appears token by token (with a blinking caret).
// Graph nodes as chips: lit while running, with their measured time once done.
// Several lit at once IS the fan-out, which no amount of "thinking…" conveys.
const nodesRow = m => {
  const names = Object.keys(m.nodes || {});
  if (!names.length) return "";
  return `<div class="cmp-stats" style="margin:0 0 6px">` + names.map(n => {
    const s = m.nodes[n];
    const cls = s.status === "running" ? "chip live" : s.status === "error" ? "chip err" : "chip";
    const suffix = s.status === "running" ? "" : s.ms != null ? ` ${s.ms}ms` : "";
    return `<span class="${cls}">${esc(n)}${suffix}</span>`;
  }).join("") + `</div>`;
};

const streamingCard = m => `<div class="card chat-answer chat-answer-pending">
  <div class="chat-author"><span class="chat-avatar" aria-hidden="true">P</span> PU <span>Đang thực hiện yêu cầu</span></div>
  ${chatElapsedMarkup(m)}
  ${m.stopping?'<p class="chat-stop-note" role="status">Đang dừng… Chờ bước đang chạy kết thúc.</p>':''}
  ${m.controlError?`<p role="alert">${esc(m.controlError)}</p>`:''}
  ${m.inboxProgress?`<div class="chat-progress" role="status">${esc(m.inboxProgress)}</div>`:''}
  ${stagesRow(m, true)}
  ${nodesRow(m)}
  ${m.usage?`<div class="meta">usage so far · ${Number(m.usage.in||0).toLocaleString()} in / ${Number(m.usage.out||0).toLocaleString()} out (${m.usage.calls||0} LLM call${m.usage.calls===1?"":"s"})</div>`:""}
  ${m.gate&&m.gate.reason?`<div class="meta" style="margin:0 0 6px">${esc(m.gate.reason)}</div>`:""}
  <div class="tele">${(m.tools||[]).map(toolRow).join("")}</div>
  ${m.stream
     ? `<div class="r" style="margin-top:8px">${renderMarkdown(m.stream)}<span class="caret"></span></div>`
     : `<div class="meta" style="margin:0">Đang chuẩn bị câu trả lời…</div>`}
</div>`;

// Messages loaded from history (a switched/opened conversation) have no live
// latency/iteration data, and their stored form carries an internal
// "[tools used: ...]" annotation — strip both so the thread reads cleanly.
const stripTools = t => (t || "").replace(/\s*\[tools used:[\s\S]*\]\s*$/, "").trim();
const historicalCard = m => `<div class="card chat-answer">
  <div class="chat-author"><span class="chat-avatar" aria-hidden="true">P</span> PU <span>Trợ lý của anh</span></div>
  <button class="msg-copy" onclick="copyMsg(this)" data-text="${esc(stripTools(m.reply))}" title="Sao chép câu trả lời">Sao chép</button>
  <div class="r">${renderMarkdown(stripTools(m.reply))}</div>
  ${chatSourcesMarkup(stripTools(m.reply))}
</div>`;

function renderChatLog(){
  if (!CHAT.length)
    return `<div class="chat-welcome"><div class="chat-welcome-mark" aria-hidden="true">P</div><h2>Anh muốn tìm hiểu điều gì?</h2><p>Từ một lời mời hợp tác đến briefing có nguồn và các lựa chọn lịch.</p><div class="chat-suggestions"><button type="button" data-prompt="Đánh giá lời mời hợp tác trong Gmail, tìm hiểu công ty và kiểm tra lịch trống. Không gửi thư hoặc tạo sự kiện khi chưa được anh xác nhận." onclick="chatUseSuggestion(this)"><b>Đánh giá lời mời</b><span>Đọc email, đối chiếu công ty và điểm cần lưu ý ↗</span></button><button type="button" data-prompt="Hôm nay có email gì mới?" onclick="chatUseSuggestion(this)"><b>Xem inbox hôm nay</b><span>Tìm những trao đổi cần anh chú ý ↗</span></button></div></div>`;
  return CHAT.map(m => m.role==="user"
      ? `<div class="bubble">${esc(m.text)}</div>`
      : m.pending ? streamingCard(m)
      : m.historical ? historicalCard(m)
      : chatTurnCard(m)).join("");
}

function syncChatLogs(forceBottom=false){
  // one conversation, two surfaces: the Chat & watch tab and the side dock
  document.querySelectorAll(".chatlog").forEach(el => {
    const follow=forceBottom||el.scrollHeight-el.scrollTop-el.clientHeight<96;
    const y=el.scrollTop;
    el.innerHTML = renderChatLog();
    el.scrollTop = follow?el.scrollHeight:y;
  });
  syncChatControls();
}

// One streamed harness event updates the live card in place.
function applyStreamEvent(pending, ev){
  if(ev.kind==='chat_started'&&ACTIVE_CHAT?.pending===pending){
    ACTIVE_CHAT.ready=true;
    if(pending.stopping)stopChat();
  }
  if(ev.kind==='inbox_progress')pending.inboxWorkflow=true;
  if(ev.kind==='inbox_progress'||ev.kind==='workflow_stage_started'){
    const labels={inbox:'Đang đọc inbox hôm nay',triage:'Đang lọc đối tác mới',research:'Đang nghiên cứu đối tác',website:'Đang đọc website và sản phẩm',news:'Đang tìm tin tức',knowledge:'Đang tra cứu tri thức',calendar:'Đang kiểm tra lịch trong tuần',email:'Đang phân tích nhu cầu',company:'Đang đối chiếu công ty',web:'Đang xác minh thông tin',memory:'Đang tra cứu lịch sử',report:'Đang viết báo cáo',report_repair:'Đang hoàn thiện nội dung báo cáo',quality_repair:'Đang sửa các điểm chưa đạt trong báo cáo',calendar_refresh:'Đang cập nhật lịch, giữ thông tin công ty đã nghiên cứu',report_cache:'Đang mở báo cáo đã đối chiếu',completed:'Đã hoàn tất'};
    pending.inboxProgress=(labels[ev.stage]||ev.stage||'Đang xử lý')+(ev.company?' · '+ev.company:'');
  }
  // Graph events arrive here too when a workflow is called from the chat box.
  // The trace poller animates the chart either way, but it runs every 450ms
  // and stages play on a 620ms stagger — going straight to graphLive() means
  // the Overview panel swaps to the running workflow the moment you hit send.
  if (ev.kind === "graph_start" && typeof graphLive === "function") graphLive(ev.workflow);
  else if (ev.kind === "graph_end" && typeof graphLive === "function") graphLive(null);
  // Graph nodes are not ToolRegistry tools, so none of them ever reached the
  // tool chips — long-running workflows should surface progress rather than
  // "thinking…". Track them separately and render them the same way, because
  // "which four things are happening right now" is the entire point of a wave.
  if (ev.kind === "node_start"){
    (pending.nodes = pending.nodes || {})[ev.node] = {status: "running"};
  } else if (ev.kind === "node_end"){
    (pending.nodes = pending.nodes || {})[ev.node] =
      {status: ev.error ? "error" : "done", ms: ev.ms};
  }
  if (ev.kind === "gate") pending.gate = {decision: ev.decision, reason: ev.reason};
  else if (ev.kind === "route")
    pending.graph = {route: ev.target === "quick_reply" ? "quick" : "full",
                     reason: (pending.graph || {}).reason};
  else if (ev.kind === "triage") (pending.graph = pending.graph || {}).reason = ev.reason;
  else if (ev.kind === "llm") {
    const usage = ev.usage || {};
    pending.usage = pending.usage || {in:0, out:0, calls:0};
    pending.usage.in += Number(usage.in||0);
    pending.usage.out += Number(usage.out||0);
    pending.usage.calls += 1;
  }
  else if (ev.kind === "text") pending.stream = (pending.stream || "") + (ev.delta || "");
  else if (ev.kind === "tool"){
    (pending.tools = pending.tools || []).push({
      tool: ev.tool, args: ev.args, output: ev.output,
      approval_id: ev.approval_id, approval_status: ev.approval_status,
      action_tool: ev.action_tool,
      status: ev.approval_id ? "warn" : ((ev.output||"").toLowerCase().startsWith("error") ? "error" : "ok"),
      summary: (ev.output || "").split(". ")[0].slice(0,120)});
    if(!pending.inboxWorkflow)pending.stream = "";
  } else if (ev.kind === "done"){
    const partial=pending.stream;
    pending.pending = false; pending.stream = "";
    pending.elapsed_ms=Math.max(0,Date.now()-pending.started);
    if (ev.error) pending.reply = "Error: " + ev.error;
    else Object.assign(pending, ev);   // reply, tools, gate, iterations, latency_ms, consolidation
    if(ev.cancelled&&partial)pending.reply=partial;
  }
}

async function sendChat(fromInput){
  const input = fromInput || document.getElementById("msg") || document.getElementById("dmsg");
  const text = (input && input.value || "").trim();
  if (!text) return;
  if(ACTIVE_CHAT||CHAT.some(m=>m.pending))return;
  input.value = "";
  CHAT.push({role:"user", text});
  const pending = {role:"pu", pending:true, stream:"", started: Date.now()};
  CHAT.push(pending);
  const active={pending,requestId:globalThis.crypto?.randomUUID?.()||`chat-${Date.now()}-${Math.random().toString(16).slice(2)}`,ready:false,stopSent:false};
  ACTIVE_CHAT=active;
  syncChatLogs(true);
  // Touch only clock text; avoid Markdown rerenders and scroll jumps on ticks.
  const ticker = setInterval(() => {
    if(pending.pending)document.querySelectorAll('[data-chat-elapsed]').forEach(el=>{el.textContent=`Đang xử lý · ${chatElapsedLabel(Date.now()-pending.started)}`;});
  }, 250);
  try {
    const res = await fetch("/api/chat/stream", {method:"POST",
      headers:puMutateHeaders(), body:JSON.stringify({message:text,request_id:active.requestId})});
    if(res.ok===false)throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;){
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream:true});
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0){
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith("data:")) continue;
        try { applyStreamEvent(pending, JSON.parse(line.slice(5).trim())); } catch(e){}
        syncChatLogs();
      }
    }
  } catch(e){ Object.assign(pending, {pending:false, reply:pending.stream||"Error: "+e}); }
  clearInterval(ticker);
  if (pending.pending){pending.pending=false;pending.reply=pending.stream||'Kết nối đã kết thúc trước khi có câu trả lời đầy đủ.';}
  pending.elapsed_ms=pending.elapsed_ms??Math.max(0,Date.now()-pending.started);
  if(ACTIVE_CHAT===active)ACTIVE_CHAT=null;
  syncChatLogs();
  if(typeof refresh==='function')await refresh();
  syncChatLogs();
  input.focus();
}
function wireDock(){
  const b = document.getElementById("dsend"), i = document.getElementById("dmsg");
  if (b) b.onclick = () => chatComposerAction('dmsg');
  if (i) i.onkeydown = e => { if (e.key==="Enter") sendChat(i); };
  const close = document.getElementById("dock-close"), reopen = document.getElementById("dock-reopen");
  const setClosed = v => { document.body.classList.toggle("dock-closed", v); localStorage.setItem("dockClosed", v?"1":"0"); };
  if (close) close.onclick = () => setClosed(true);
  if (reopen) reopen.onclick = () => setClosed(false);
  const saved = localStorage.getItem("dockClosed");
  setClosed(saved === null ? window.innerWidth < 1180 : saved === "1");
  syncChatLogs();
}

