const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function harness(){
  const input={value:'',focus(){this.focused=true;}};
  const ctx=vm.createContext({URL,Intl,Date,VIEWS:{},document:{getElementById(){return input;}}});
  for(const file of ['util.js','notebook.js','render.js','inbox-chat.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../../pu/ops/static/js',file),'utf8'),ctx);
  return {ctx,input};
}
test('citations preserve exact URLs and escape hostile source content',()=>{
  const {ctx}=harness();
  const html=ctx.renderMarkdown('Company [1](https://example.com/a_b_c?q=x&v=2) [thư](https://mail.google.com/mail/u/0/#all/123) <img src=x onerror=alert(1)>');
  assert.ok(html.includes('href="https://example.com/a_b_c?q=x&amp;v=2"'));
  assert.ok(html.includes('class="chat-citation"'));
  assert.ok(html.includes('Mở nguồn thư'));
  assert.ok(!html.includes('<img'));
  assert.ok(!ctx.renderMarkdown('[bad](javascript:alert(1))').includes('<a'));
  assert.ok(ctx.renderMarkdown('`[1](https://example.com)`').includes('<code>[1](https://example.com)</code>'));
});
test('source disclosure deduplicates links, ignores code, and never invents sources',()=>{
  const {ctx}=harness();
  const html=ctx.chatSourcesMarkup('[1](https://a.example/path) [2](https://a.example/path) `<x>` `[3](https://ignored.example)` [x](javascript:alert(1))');
  assert.ok(html.includes('Nguồn tham khảo · 1'));
  assert.ok(html.includes('a.example'));
  assert.ok(!html.includes('ignored.example'));
  assert.equal(ctx.chatSourcesMarkup('No linked evidence.'),'');
  assert.ok(!ctx.chatSourcesMarkup('[a](https://user:password@host.test)').includes('password'));
});
test('suggestions prepare editable text without sending or scheduling',()=>{
  const {ctx,input}=harness();
  ctx.sendChat=()=>{throw new Error('must not send');};
  ctx.chatUseSuggestion({dataset:{prompt:'Evaluate invitation'}});
  assert.equal(input.value,'Evaluate invitation');assert.ok(input.focused);
});
test('current release reference works and legacy evidence cannot enable actions',()=>{
  const {ctx}=harness();
  const ref={release_allowed:true,evidence_policy_version:'company-boundary-v2',quality_policy_version:'report-quality-v2',rubric_version:'report-quality-rubric-v8'};
  assert.equal(ctx.chatReportReleaseReady(ref),true);
  assert.equal(ctx.chatReportReleaseReady({...ref,evidence_policy_version:'company-boundary-v1'}),false);
  assert.equal(ctx.chatReportReleaseReady({...ref,release_allowed:false}),false);
});
test('completed and historical responses expose sources and table content',()=>{
  const {ctx}=harness();
  ctx.fixture={reply:'**Lịch:**\n\n| Ngày | Giờ |\n| --- | --- |\n| 22/10/2026 | 09:00 |\n\n[1](https://example.com)'};
  for(const call of ['chatTurnCard(fixture)','historicalCard(fixture)']){
    const html=vm.runInContext(call,ctx);
    assert.ok(html.includes('chat-answer'));
    assert.ok(html.includes('class="mdtable"'));
    assert.ok(html.includes('Nguồn tham khảo · 1'));
  }
});
