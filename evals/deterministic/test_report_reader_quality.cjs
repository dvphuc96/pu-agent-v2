const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const node = '/Users/dvphuc/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node';

function harness(){
  const context = vm.createContext({
    URL,
    Intl,
    Date,
    console,
    setTimeout,
    document:{getElementById:()=>null,querySelectorAll:()=>[],querySelector:()=>null},
    location:{hash:'#chat'},
    VIEWS:{},
    D:{approvals:{items:[]}},
    CHAT:[],
    fetch:async()=>({json:async()=>({})}),
  });
  for(const file of ['util.js','notebook.js','briefing.js','render.js','inbox-chat.js']){
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../../pu/ops/static/js',file),'utf8'),context,{filename:file});
  }
  return context;
}

function sources(count=10){
  return Array.from({length:count},(_,index)=>({
    id:`W${index+1}`, source_type:'web', derived:false,
    title:`Nguồn công khai ${index+1}`, url:`https://partner.example/source-${index+1}`,
    published_at:'2026-10-01', excerpt:'Dữ kiện đã đọc',
  }));
}

test('reader maps citations to numbered links and folds extra public sources',()=>{
  const context=harness();
  const report={
    title:'Báo cáo Acme', executive_summary:'Acme hoạt động trong AI [W1][W2] và có quy mô [W10].',
    sections:{company:'Thông tin công ty [W1]',company_scale:'Có mạng lưới vận hành [W9].',meeting_context:'Cuộc họp đã được đề cập [W2].'},
    missing_information:[{text:'Chưa tìm thấy doanh thu',source_ids:['W10']}], sources:sources(10), claims:[{text:'Claim [W1]',source_ids:['W1','W2']}],
    metadata:{quality_policy_version:'report-quality-v2',evidence_policy_version:'company-boundary-v2'},
    evaluation:{release_allowed:true,metrics:{completeness:.8}},
  };
  const html=context.chatReadableReport(report);
  assert.ok(html.includes('href="https://partner.example/source-1"'));
  assert.ok(html.includes('[10]') || html.includes('source-10'));
  assert.ok(html.includes('Xem thêm 2 nguồn đã được trích dẫn'));
  assert.ok(!html.includes('[W1]')&&!html.includes('[W10]'));
  assert.match(html,/<a[^>]+>1<\/a> <a[^>]+>2<\/a>/); // Inline citations remain separated without duplicating audit chips.
  assert.ok(html.includes('Cuộc họp đã được đề cập'));
  assert.ok(!html.includes('](https://'));
});

test('reader honors server citation presentation and keeps canonical duplicate URLs first-seen',()=>{
  const context=harness();
  const report={title:'Acme',executive_summary:'Fact [S1][S2]',sections:{},sources:[
    {id:'S1',source_type:'web',derived:false,title:'Tracked page',url:'https://www.acme.example/about?utm_source=news#team'},
    {id:'S2',source_type:'web',derived:false,title:'Canonical page',url:'https://acme.example/about'},
    {id:'E1',source_type:'email',derived:false,title:'Email'},
  ],claims:[{text:'Claim [S1]',source_ids:['S1']}],contradictions:[{description:'Nguồn khác nhau [S2]',source_ids:['S2']}],missing_information:[{text:'Thiếu dữ liệu',source_ids:['E1']}],metadata:{
    citation_presentation:{S1:{number:2,url:'https://acme.example/about',public:true},S2:{number:1,url:'https://acme.example/about',public:true},E1:{number:null,public:false}},
  }};
  const html=context.chatReadableReport(report);
  assert.ok(html.includes('href="https://www.acme.example/about?utm_source=news#team"'));
  assert.ok(html.includes('>Nguồn khác nhau'));
  assert.match(html,/<a[^>]+>\[1\]<\/a>/);
  assert.ok(html.includes('Mâu thuẫn cần lưu ý')&&html.includes('Email nội bộ'));
});

test('reader renders the new research sections and one consolidated identity warning',()=>{
  const context=harness();
  const report={
    title:'Vinamilk', executive_summary:'Tóm tắt [S1]', sections:{
      company:'Vinamilk', company_scale:'Quy mô [S1]', business_context:'Bối cảnh [S1]',
      meeting_preparation:'Câu hỏi chuẩn bị [S1]', meeting_context:'Nội dung cũ không nên lặp',
    }, sources:[{id:'S1',source_type:'web',derived:false,title:'Vinamilk',url:'https://vinamilk.example'}], claims:[],
    metadata:{quality_policy_version:'report-quality-v2',evidence_policy_version:'company-boundary-v2',partner_identity:{conflicts:['Tên công ty trong chữ ký khác nhau'],affiliation_warnings:['Chưa xác minh quyền đại diện']}},
  };
  const html=context.chatReadableReport(report);
  for(const label of ['Quy mô và vận hành','Bối cảnh liên quan','Mục tiêu và câu hỏi chuẩn bị'])assert.ok(html.includes(label));
  assert.equal((html.match(/class="chat-reader-warning"/g)||[]).length,1);
  assert.ok(html.includes('Nội dung cũ không nên lặp'));
});

test('reader only displays fresh future structured availability slots',()=>{
  const context=harness();
  const checked=new Date(Date.now()-60*1000).toISOString();
  const future=new Date(Date.now()+60*60*1000).toISOString();
  const futureEnd=new Date(Date.now()+105*60*1000).toISOString();
  const past=new Date(Date.now()-60*60*1000).toISOString();
  const report={title:'Acme',executive_summary:'Summary',sections:{},sources:[],claims:[],metadata:{
    availability:{status:'available',checked_at:checked,timezone:'Asia/Ho_Chi_Minh',checked_sources:['Lịch local'],slots:[
      {label:'Hôm nay',window:'09:00–09:45',start:future,end:futureEnd},
      {label:'Đã qua',window:'08:00–08:45',start:past,end:future},
    ]},quality_policy_version:'report-quality-v2',
  }};
  const html=context.chatReadableReport(report);
  assert.ok(html.includes('Các lựa chọn lịch'));
  assert.ok(html.includes('09:00–09:45'));
  assert.ok(!html.includes('08:00–08:45'));
  assert.ok(html.includes('Asia/Ho_Chi_Minh')&&html.includes('Lịch local'));
});

test('reader rejects future checks and non-available calendar status',()=>{
  const context=harness();
  const future=new Date(Date.now()+60*60*1000).toISOString();
  const end=new Date(Date.now()+105*60*1000).toISOString();
  const report={title:'Acme',executive_summary:'Summary',sections:{},sources:[],claims:[],metadata:{availability:{
    status:'unknown',checked_at:new Date(Date.now()+1000).toISOString(),timezone:'Asia/Ho_Chi_Minh',checked_sources:['Lịch local'],slots:[{label:'Không được đề xuất',window:'10:00–10:45',start:future,end}],
  }}};
  const html=context.chatReadableReport(report);
  assert.ok(html.includes('Chưa có khung giờ còn hiệu lực để đề xuất.'));
  assert.ok(!html.includes('10:00–10:45'));
});

test('quality disclosure uses real metrics and marks legacy evaluations as unknown',()=>{
  const context=harness();
  const base={title:'Acme',executive_summary:'Summary',sections:{},sources:[],claims:[],metadata:{performance:{scope:'research_workflow',duration_seconds:42,cache_hit:true,stages:{research:{duration_seconds:31.1234,reused:false}}}}};
  const current=context.chatReadableReport({...base,metadata:{...base.metadata,quality_policy_version:'report-quality-v2'},evaluation:{quality_policy_version:'report-quality-v2',rubric_version:'report-quality-rubric-v8',schema_version:2,gate_status:'pass',release_allowed:true,metrics:{completeness:.98,source_count:12,unsupported_claims:0}}});
  assert.ok(current.includes('Chất lượng báo cáo')&&!current.includes('98%')&&current.includes('0.98')&&current.includes('42.00 giây'));
  assert.ok(current.includes('Tổng số nguồn (mọi loại)')&&current.includes('Thời gian workflow nghiên cứu')&&current.includes('31.12 giây'));
  assert.ok(current.includes('Đánh giá theo chuẩn hiện tại')&&!current.includes('Độ chính xác'));
  const mismatched=context.chatReadableReport({...base,metadata:{...base.metadata,quality_policy_version:'report-quality-v2'},evaluation:{quality_policy_version:'legacy',schema_version:2,metrics:{completeness:.98}}});
  assert.ok(mismatched.includes('Chưa đánh giá theo chuẩn mới'));
  const legacy=context.chatReadableReport({...base,evaluation:{release_allowed:true,metrics:{completeness:.98}}});
  assert.ok(legacy.includes('Chưa đánh giá theo chuẩn mới'));
  const unknown=context.chatReadableReport({...base,metadata:{quality_policy_version:'report-quality-v2'},evaluation:{quality_policy_version:'report-quality-v2',rubric_version:'report-quality-rubric-v8',schema_version:2,metrics:{freshness:.5,freshness_known_sources:0}}});
  assert.ok(unknown.includes('Độ mới của tin liên quan</span><b>Chưa xác định'));
  assert.ok(!unknown.includes('Độ mới của tin liên quan</span><b>50%'));
  const semantic=context.chatReadableReport({...base,metadata:{...base.metadata,quality_policy_version:'report-quality-v2'},evaluation:{quality_policy_version:'report-quality-v2',rubric_version:'report-quality-rubric-v8',schema_version:2,status_details:{semantic_review:'unavailable_or_incomplete'},metrics:{completeness:.8}}});
  assert.ok(semantic.includes('chưa đủ hoặc chưa khả dụng'));
});

test('reader blocks action controls until the release reference has the v2 quality policy',()=>{
  const context=harness();
  vm.runInContext("D={approvals:{items:[{id:'a',tool_name:'save_report_to_knowledge',status:'pending',arguments:{workspace_id:'ws-a',report_id:'r'}}]}}",context);
  const turn={reports:[{workspace_id:'ws-a',report_id:'r',title:'Draft',release_allowed:true,evidence_policy_version:'company-boundary-v2',quality_policy_version:'report-quality-v1',rubric_version:'report-quality-rubric-v8'}]};
  assert.ok(!context.chatReportActions(turn).includes('Import vào sổ tay'));
  turn.reports[0].quality_policy_version='report-quality-v2';
  turn.reports[0].rubric_version='report-quality-rubric-v8';
  assert.ok(context.chatReportActions(turn).includes('Import vào sổ tay'));
});

test('quality disclosure explains structured issues safely and rejects the previous rubric',()=>{
  const context=harness();
  const report={title:'Draft',sections:{},sources:[],claims:[],metadata:{quality_policy_version:'report-quality-v2'},evaluation:{
    quality_policy_version:'report-quality-v2',rubric_version:'report-quality-rubric-v8',schema_version:2,
    metrics:{unsupported_claims:1},findings:['opaque legacy finding'],
    issues:[{code:'claim_evidence',severity:'error',message:'Số liệu chưa khớp với nguồn <script>alert(1)</script>'}],
  }};
  const html=context.chatReadableReport(report);
  assert.ok(html.includes('Số liệu chưa khớp với nguồn &lt;script&gt;'));
  assert.ok(!html.includes('opaque legacy finding')&&!html.includes('<script>alert(1)</script>'));
  report.evaluation.rubric_version='report-quality-rubric-v3';
  assert.ok(context.chatReadableReport(report).includes('Cần đánh giá lại theo chuẩn hiện tại'));
});

test('compact view consolidates warnings and keeps diagnostics separate from readiness',()=>{
  const context=harness();
  const warning='Chưa xác minh quyền đại diện.';
  const report={report_id:'r',title:'Acme',executive_summary:'Summary',sections:{company_context:'Hidden raw section'},sources:[],claims:[],missing_information:[warning],metadata:{
    quality_policy_version:'report-quality-v2',evidence_policy_version:'company-boundary-v2',partner_identity:{affiliation_warnings:[warning]},
    reading_view:{version:'partner-brief-v2',blocks:[{key:'company_context',title:'Công ty và bối cảnh liên quan',text:'Unique company context'}],open_items:[warning]},
  },evaluation:{quality_policy_version:'report-quality-v2',rubric_version:'report-quality-rubric-v8',schema_version:2,release_allowed:true,
    metrics:{completeness:1,meeting_readiness:1,source_diversity:1,overall:.95,public_publisher_count:1},warnings:[warning],
    status_details:{readiness:{discovery:'ready_with_limits',pilot:'needs_confirmation',checklist:[{key:'contact_role',label:'Vai trò',state:'self_reported'},{key:'budget',label:'Ngân sách',state:'unknown'}]}}}};
  const html=context.chatReadableReport(report);
  assert.equal(html.split(warning).length-1,1);
  assert.ok(html.includes('Unique company context')&&!html.includes('Hidden raw section'));
  assert.ok(html.includes('Người gửi tự khai')&&html.includes('Ngân sách: Chưa biết'));
  assert.ok(html.includes('Đủ để khám phá nhu cầu')&&!html.includes('100%')&&!html.includes('95%'));
});

test('compact sources keep citation numbers while omitting unused pages',()=>{
  const context=harness();
  const report={title:'Acme',executive_summary:'Fact [W3]',sections:{company_context:'Fact [W3]'},sources:sources(4),claims:[],metadata:{
    reading_view:{version:'partner-brief-v2',blocks:[{key:'company_context',title:'Bối cảnh',text:'Fact [W3]'}],open_items:[]},
  }};
  const html=context.chatReadableReport(report);
  assert.ok(html.includes('<li value="3">'));
  assert.ok(html.includes('Nguồn công khai 3'));
  assert.ok(!html.includes('Nguồn công khai 1')&&!html.includes('Nguồn công khai 4'));
});

test('final gate failure is not presented as semantic approval and requested details stay unknown',()=>{
  const context=harness();
  const report={metadata:{quality_policy_version:'report-quality-v2',preparation_schema_version:2},evaluation:{
    quality_policy_version:'report-quality-v2',rubric_version:'report-quality-rubric-v8',schema_version:2,release_allowed:false,gate_status:'fail',
    metrics:{unsupported_claims:2},status_details:{semantic_review:'passed',readiness:{checklist:[
      {key:'security_requirements',label:'Yêu cầu bảo mật',answer_status:'requested',state:'unknown'},
    ]}},
  }};
  const html=context.chatQualityMarkup(report);
  assert.ok(html.includes('Chưa phát hành: còn 2 nhận định chưa đối chiếu được'));
  assert.ok(html.includes('Muốn trao đổi, chưa có câu trả lời cụ thể'));
  assert.ok(!html.includes('Đối chiếu nội dung: đã đạt'));
});

test('partial checklist preserves known document types and keeps technical metrics folded',()=>{
  const context=harness();
  const report={metadata:{quality_policy_version:'report-quality-v2',preparation_schema_version:3},evaluation:{
    quality_policy_version:'report-quality-v2',rubric_version:'report-quality-rubric-v8',schema_version:2,release_allowed:true,gate_status:'pass_with_warning',
    metrics:{source_coverage:1},status_details:{readiness:{discovery:'ready_with_limits',pilot:'needs_confirmation',checklist:[
      {key:'input_documents',label:'Tài liệu đầu vào',answer_status:'partial',state:'self_reported',value:'Hóa đơn PDF và biểu mẫu scan',remaining_gap:'Chưa có bộ mẫu',scope:'pilot'},
    ]}},
  }};
  const html=context.chatQualityMarkup(report);
  assert.ok(html.includes('Đủ thông tin để trao đổi ban đầu'));
  assert.ok(html.includes('Biết một phần')&&html.includes('Hóa đơn PDF')&&html.includes('Chưa có bộ mẫu'));
  assert.ok(html.indexOf('Chi tiết kiểm định và thời gian')<html.indexOf('pass_with_warning'));
  assert.ok(html.indexOf('Chi tiết kiểm định và thời gian')<html.indexOf('100%'));
  report.evaluation.rubric_version='report-quality-rubric-v6';
  assert.ok(context.chatQualityMarkup(report).includes('Cần đánh giá lại theo chuẩn hiện tại'));
});

test('calendar shows requested week and turn timing phases do not become an extra total',()=>{
  const context=harness();
  const html=context.chatAvailabilityMarkup({status:'unknown',slots:[],scheduling_window:{label:'Lịch trống 19/10–25/10/2026'}});
  assert.ok(html.includes('19/10–25/10/2026'));
  const timing=context.chatReportTimingMarkup('r',{scope:'backend_response',duration_seconds:98,phases:{lock_wait:1,session_setup:2,agent_response:95},inbox_phases:{classification:9,partner_reports:84}});
  assert.ok(timing.includes('98.00 giây')&&timing.includes('Chờ lượt xử lý')&&timing.includes('không cộng thêm vào tổng'));
});

test('report reader reuses persisted turn timing without summing phase or report durations',()=>{
  const context=harness();
  const turn=context.histItem({role:'assistant',content:'Done',meta:{reports:[{report_id:'one'},{report_id:'two'}],response_timing:{scope:'backend_response',duration_seconds:85.42}}});
  vm.runInContext(`CHAT.push(${JSON.stringify(turn)})`,context);
  const report={report_id:'one',title:'Acme',sections:{},sources:[],claims:[],metadata:{performance:{scope:'research_workflow',duration_seconds:39.29},collection_performance:{duration_seconds:46.13}}};
  let html=context.chatReadableReport(report);
  assert.ok(html.includes('toàn lượt chat: 85.42 giây'));
  report.report_id='two';
  assert.ok(context.chatReadableReport(report).includes('toàn lượt chat: 85.42 giây'));
  report.report_id='unknown';
  html=context.chatReadableReport(report);
  assert.ok(html.includes('Chưa đo được tổng thời gian'));
  assert.ok(!html.includes('toàn lượt chat: 85.42 giây'));
  report.report_id='one';
  vm.runInContext("CHAT.push({reports:[{report_id:'one'}],response_timing:{scope:'backend_response',duration_seconds:0.3}})",context);
  assert.ok(context.chatReadableReport(report).includes('Chưa đo được tổng thời gian'));
  assert.ok(context.chatReadableReport(report,{scope:'backend_response',duration_seconds:85.42}).includes('toàn lượt chat: 85.42 giây'));
  assert.ok(context.chatReportActions(turn).includes('data-response-seconds="85.42"'));
});

test('legacy snapshot is dated and flagged before prose without mutating its evidence or verdict',()=>{
  const context=harness();
  const report={report_id:'old',generated_at:'2026-10-17T07:21:41+00:00',executive_summary:'Company facts',sections:{},sources:[],claims:[],metadata:{quality_policy_version:'report-quality-v2'},evaluation:{quality_policy_version:'report-quality-v2',rubric_version:'report-quality-rubric-v7',schema_version:2,release_allowed:true,metrics:{unsupported_claims:1}}};
  const before=JSON.stringify(report),html=context.chatReadableReport(report);
  assert.ok(html.includes('14:21')&&html.includes('17/10/2026'));
  assert.ok(html.indexOf('Bản báo cáo cũ')<html.indexOf('Company facts'));
  assert.ok(html.includes('Kết quả kiểm định bên dưới thuộc phiên bản này'));
  assert.ok(!html.includes('Đủ điều kiện phát hành')&&!html.includes('Đánh giá theo chuẩn hiện tại'));
  assert.equal(JSON.stringify(report),before);
  report.generated_at='<img src=x onerror=alert(1)>';
  assert.ok(context.chatReportSnapshotMarkup(report).includes('Chưa xác định thời điểm lập'));
  assert.ok(!context.chatReportSnapshotMarkup(report).includes('<img'));
  report.evaluation.rubric_version='report-quality-rubric-v8';
  assert.ok(!context.chatReportSnapshotMarkup(report).includes('Bản báo cáo cũ'));
});

test('opening an old attachment retains its snapshot and offers an explicitly newer version',async()=>{
  const context=harness();
  const report={report_id:'old',title:'Old report',executive_summary:'Original prose',sections:{},sources:[],claims:[],metadata:{},evaluation:{rubric_version:'report-quality-rubric-v7'}};
  const requests=[];context.chatReportDetail=async(ws,id)=>{requests.push([ws,id]);return {report:{payload:report},versions:[{report_id:'newer'},{report_id:'old'}]};};
  let rendered;context.chatReportDialog=(title,body,footer)=>{rendered={title,body,footer};};
  const button={dataset:{ws:'ws-a',report:'old'},closest:()=>null};
  await context.chatOpenReport(button);
  assert.deepEqual(requests,[['ws-a','old']]);
  assert.ok(rendered.body.includes('Original prose')&&rendered.body.includes('data-report="newer"'));
  assert.ok(rendered.footer.includes('Tạo bản cập nhật')&&rendered.footer.includes('report=old'));
  assert.ok(!button.disabled);
});

function updateButton(){
  const status={innerHTML:'',textContent:''};
  return {dataset:{ws:'ws-a'},disabled:false,parentElement:{querySelector:()=>status},status};
}

test('refresh queues once and distinguishes paused worker, missing model and completed report',async()=>{
  const context=harness();
  let calls=0,resolve;
  context.postJSON=async(url,payload)=>{calls++;assert.equal(url,'/api/briefing');assert.equal(payload.op,'enqueue');assert.equal(payload.workspace_id,'ws-a');return new Promise(r=>{resolve=r;});};
  let button=updateButton();
  const pending=context.chatUpdateReport(button);
  await context.chatUpdateReport(button);
  assert.equal(calls,1);
  resolve({enabled:false,model_configured:true,worker_active:true,jobs:[{workspace_id:'ws-a',status:'queued'}]});await pending;
  assert.ok(button.status.innerHTML.includes('tạm dừng')&&!button.status.innerHTML.includes('đang tạo'));
  for(const [state,text] of [
    [{enabled:true,model_configured:false},'cần kết nối model'],
    [{enabled:true,model_configured:true,worker_active:false},'chờ worker'],
    [{enabled:true,model_configured:true,worker_active:true,jobs:[{workspace_id:'ws-a',status:'completed',report_id:'new-report'}]},'data-report="new-report"'],
    [{enabled:true,model_configured:true,worker_active:true,jobs:[{workspace_id:'ws-a',status:'completed',report_id:'obsolete'},{workspace_id:'ws-a',status:'running'}]},'Đã xếp hàng'],
  ]){
    context.postJSON=async()=>state;button=updateButton();await context.chatUpdateReport(button);
    assert.ok(button.status.innerHTML.includes(text));
    assert.ok(button.disabled);
  }
});

test('refresh failure allows retry and reports errors as text',async()=>{
  const context=harness(),button=updateButton();
  context.postJSON=async()=>({error:'<script>failed</script>'});
  await context.chatUpdateReport(button);
  assert.equal(button.disabled,false);
  assert.equal(button.status.textContent,'<script>failed</script>');
  assert.equal(button.status.innerHTML,'');
});

test('reader css keeps the wide modal and quality surfaces readable',()=>{
  const css=fs.readFileSync(path.join(__dirname,'../../pu/ops/static/notebook.css'),'utf8');
  assert.match(css,/chat-report-dialog[^}]+1320px/);
  for(const token of ['chat-reader-quality','chat-reader-slots','chat-reader-extra-sources'])assert.ok(css.includes(token));
});

