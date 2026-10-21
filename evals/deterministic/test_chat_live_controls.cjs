const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function harness(){
  let now=10000,tick,resolveRead;
  const clock={textContent:''},button={innerHTML:'',setAttribute(k,v){this[k]=v;},classList:{toggle(){}}};
  const input={value:'hello',focus(){}};
  const context=vm.createContext({
    URL,TextDecoder,TextEncoder,Intl,Date:class extends Date{static now(){return now;}},VIEWS:{},D:{},CHAT:[],
    document:{getElementById:()=>input,querySelectorAll:selector=>selector==='[data-chat-elapsed]'?[clock]:selector==='[data-chat-send],#dsend'?[button]:[]},
    setTimeout(){},setInterval(fn){tick=fn;return 1;},clearInterval(){tick=null;},
    fetch:async()=>({ok:true,body:{getReader:()=>({read:()=>new Promise(resolve=>{resolveRead=resolve;})})}}),
  });
  for(const file of ['util.js','notebook.js','render.js','inbox-chat.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../../pu/ops/static/js',file),'utf8'),context);
  return {context,button,input,clock,advance(ms){now+=ms;tick?.();},send(event){resolveRead({value:new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`),done:false});},end(){resolveRead({done:true});},hasTimer(){return Boolean(tick);}};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('send becomes stop; timer continues while tokens stream and freezes after completion',async()=>{
  const h=harness();
  const task=h.context.sendChat(h.input);await flush();
  assert.equal(h.button['aria-label'],'Dừng trả lời');assert.ok(h.button.innerHTML.includes('<rect'));
  h.send({kind:'chat_started',request_id:'id'});await flush();
  h.send({kind:'text',delta:'Visible partial'});await flush();
  h.advance(62000);assert.ok(h.clock.textContent.includes('01:02'));
  const html=vm.runInContext('renderChatLog()',h.context);assert.ok(html.includes('Visible partial')&&html.includes('role="timer"'));
  h.send({kind:'done',reply:'Finished'});await flush();h.end();await task;
  assert.equal(h.button['aria-label'],'Gửi tin nhắn');assert.ok(!h.hasTimer());
  assert.ok(vm.runInContext('renderChatLog()',h.context).includes('Thời gian phản hồi · 01:02'));
});

test('early stop waits for acknowledgement, cancels once, keeps partial and preserves typed draft',async()=>{
  const h=harness();let calls=0;
  h.context.postJSON=async(url,payload)=>{assert.equal(url,'/api/chat/stop');assert.ok(payload.request_id);calls++;return {accepted:true};};
  const task=h.context.sendChat(h.input);await flush();h.input.value='Next draft';
  await h.context.stopChat();assert.equal(calls,0);
  h.send({kind:'chat_started'});await flush();assert.equal(calls,1);
  await h.context.stopChat();assert.equal(calls,1);
  assert.equal(h.button['aria-label'],'Đang dừng');assert.ok(h.button.disabled);
  h.send({kind:'text',delta:'Partial before stop'});await flush();
  h.send({kind:'done',cancelled:true,reply:'Stopped'});await flush();h.end();await task;
  assert.equal(h.input.value,'Next draft');assert.equal(h.button['aria-label'],'Gửi tin nhắn');
  assert.ok(vm.runInContext('renderChatLog()',h.context).includes('Partial before stop'));
  assert.ok(vm.runInContext('renderChatLog()',h.context).includes('Đã dừng theo yêu cầu'));
});

test('network failure restores sending and clears the ticker',async()=>{
  const h=harness();h.context.fetch=async()=>{throw new Error('offline');};
  await h.context.sendChat(h.input);
  assert.equal(h.button['aria-label'],'Gửi tin nhắn');assert.ok(!h.button.disabled&&!h.hasTimer());
  assert.ok(vm.runInContext('renderChatLog()',h.context).includes('offline'));
});
