// One conversation: inbox questions and complete research reports live here.
function inboxChatView(){
  return `<div class="nb-root chat-main"><div class="chat-heading"><div><div class="nb-eyebrow">PU · TRỢ LÝ ĐỐI TÁC</div><h1>Trò chuyện</h1></div><div class="chat-heading-actions"><button class="nb-btn" onclick="toggleSessMenu(event)">Lịch sử</button><button class="nb-btn" onclick="newChat()">＋ Cuộc trò chuyện mới</button></div></div><div class="chatlog" id="main-chatlog" aria-label="Nội dung cuộc trò chuyện">${renderChatLog()}</div><form class="chat-main-composer" onsubmit="event.preventDefault();sendChat(document.getElementById('msg'))"><div><textarea id="msg" rows="2" aria-label="Tin nhắn cho PU" placeholder="Hỏi về lời mời hợp tác, công ty hoặc lịch hẹn…" onkeydown="if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendChat(this);}"></textarea><button type="button" data-chat-send aria-label="Gửi tin nhắn" onclick="chatComposerAction('msg')">${chatSendIcon()}</button></div><small>Gửi email, tạo sự kiện hoặc lưu tri thức cần anh duyệt trước.</small></form></div>`;
}
function chatStartInbox(){const input=document.getElementById('msg')||document.getElementById('dmsg');if(input){input.value='Hôm nay có email gì mới?';sendChat(input);}}
function chatUseSuggestion(button){
  const input=document.getElementById('msg')||document.getElementById('dmsg');
  if(input){input.value=button.dataset.prompt;input.focus();}
}
let chatApprovalStamp='';
function syncChatApprovals(){
  const stamp=JSON.stringify(((D&&D.approvals||{}).items||[]).map(a=>[a.id,a.status]));
  if(stamp!==chatApprovalStamp){chatApprovalStamp=stamp;if(CHAT.some(t=>(t.reports||[]).length))syncChatLogs();}
}
function chatValidationDetails(turn){
  const items=turn.inbox_validation||[];if(!items.length)return '';
  const labels={eligible:'Cần chú ý',excluded:'Đã gộp',uncertain:'Chưa đủ dữ kiện',existing:'Đang trao đổi'};
  return `<details class="chat-validation"><summary>Xem chi tiết lọc ${items.length} email</summary><div>${items.map(item=>`<div><b>${esc(item.subject||'(Không có tiêu đề)')}</b><span>${esc(labels[item.status]||item.status)} · ${esc(item.reason)}</span>${item.quote?`<blockquote>${esc(item.quote)}</blockquote>`:''}</div>`).join('')}</div></details>`;
}
function chatReportReleaseReady(ref){
  return Boolean(ref&&ref.release_allowed&&ref.evidence_policy_version==='company-boundary-v2'&&ref.quality_policy_version==='report-quality-v2'&&ref.rubric_version==='report-quality-rubric-v8');
}
function chatReportPolicyCurrent(report){
  const evaluation=report?.evaluation||{},metrics=evaluation.metrics;
  return (report?.metadata?.quality_policy_version||evaluation.quality_policy_version)==='report-quality-v2'&&evaluation.quality_policy_version==='report-quality-v2'&&evaluation.rubric_version==='report-quality-rubric-v8'&&evaluation.evaluated!==false&&Number(evaluation.schema_version)>=2&&metrics&&typeof metrics==='object'&&Object.keys(metrics).length>0;
}
function chatReportSnapshotMarkup(report){
  const stamp=report.generated_at,valid=typeof stamp==='string'&&Number.isFinite(Date.parse(stamp));
  const created=valid?`Lập lúc ${chatFormatDate(stamp,'Asia/Ho_Chi_Minh')} · giờ Việt Nam`:'Chưa xác định thời điểm lập báo cáo';
  return `<div class="chat-reader-snapshot"><p class="nb-muted">${esc(created)}</p>${!chatReportPolicyCurrent(report)?'<p class="nb-notice"><b>Bản báo cáo cũ — chưa đánh giá theo chuẩn hiện tại.</b> Kết quả kiểm định bên dưới thuộc phiên bản này. Cần tạo bản cập nhật trước khi duyệt lưu hoặc gửi.</p>':''}</div>`;
}
function chatReportActions(turn){
  const refs=turn.reports||[];if(!refs.length)return '';
  const actions=((D&&D.approvals||{}).items||[]);
  const responseSeconds=turn.response_timing?.scope==='backend_response'&&Number.isFinite(turn.response_timing.duration_seconds)?turn.response_timing.duration_seconds:'';
  return `<div class="chat-report-actions">${refs.map(ref=>{
    const matching=actions.filter(a=>a.arguments.workspace_id===ref.workspace_id&&a.arguments.report_id===ref.report_id);
    const releaseReady=chatReportReleaseReady(ref);
    return `<section class="chat-report-attachment"><span class="chat-source-icon">${nbIcon('file')}</span><div><b>${esc(ref.title||'Báo cáo nghiên cứu chi tiết')}</b><p>${releaseReady?'Báo cáo đầy đủ, kèm thông tin công ty và nguồn đối chiếu.':'Bản nháp cần xác minh thêm.'}</p><div class="chat-attachment-buttons"><button class="nb-btn" type="button" data-ws="${esc(ref.workspace_id)}" data-report="${esc(ref.report_id)}" data-response-seconds="${responseSeconds}" onclick="chatOpenReport(this)">Đọc báo cáo</button>${releaseReady?matching.map(a=>['pending','approved'].includes(a.status)?`<button class="nb-btn primary" onclick="chatReviewAction('${esc(a.id)}')">${a.tool_name==='forward_report_email'?'Đọc & duyệt gửi':'Import vào sổ tay'}</button>`:`<span class="nb-muted">${esc(({executed:'Đã thực hiện',rejected:'Đã từ chối',expired:'Đã hết hạn',failed:'Thực hiện lỗi'})[a.status]||a.status)}</span>`).join(''):''}</div><span data-report-error role="alert"></span></div></section>`;
  }).join('')}</div>`;
}
async function chatReportDetail(workspaceId,reportId){
  const response=await fetch(`/api/workspaces?id=${encodeURIComponent(workspaceId)}&report=${encodeURIComponent(reportId)}`);
  const detail=await response.json();if(detail.error)throw new Error(detail.error);return detail;
}
function chatFormatDate(value,timezone,includeTime=true){
  try{
    const options={timeZone:timezone||'Asia/Ho_Chi_Minh',day:'2-digit',month:'2-digit',year:'numeric'};
    if(includeTime){options.hour='2-digit';options.minute='2-digit';}
    return new Intl.DateTimeFormat('vi-VN',options).format(new Date(value));
  }catch{return String(value||'');}
}
function chatAvailabilityMarkup(availability){
  if(!availability||typeof availability!=='object')return '';
  const timezone=availability.timezone||'Asia/Ho_Chi_Minh';
  const checked=availability.checked_at?Date.parse(availability.checked_at):NaN;
  const now=Date.now();
  const age=now-checked;
  const fresh=Number.isFinite(checked)&&age>=0&&!availability.stale&&age<=15*60*1000;
  const checkedText=Number.isFinite(checked)?`Kiểm tra lúc ${esc(chatFormatDate(availability.checked_at,timezone))}`:'Chưa có thời điểm kiểm tra';
  const checkedSources=Array.isArray(availability.checked_sources)?availability.checked_sources.filter(Boolean):[];
  const scope=checkedSources.length?`Phạm vi: ${esc(checkedSources.join(' và '))}.`:'Chưa xác định nguồn lịch.';
  const warnings=Array.isArray(availability.warnings)?availability.warnings.filter(Boolean):[];
  const slots=Array.isArray(availability.slots)?availability.slots.filter(slot=>{
    if(!fresh||availability.status!=='available'||!slot||slot.stale||slot.past)return false;
    const start=Date.parse(slot.start),end=Date.parse(slot.end);
    return Number.isFinite(start)&&Number.isFinite(end)&&start>now&&end>now&&end>start;
  }):[];
  const staleCount=Array.isArray(availability.slots)?availability.slots.length-slots.length:0;
  const slotMarkup=slots.map(slot=>{
    const label=slot.label||slot.date||'Ngày chưa xác định';
    const window=slot.window||`${chatFormatDate(slot.start,timezone)}–${chatFormatDate(slot.end,timezone)}`;
    return `<li class="chat-reader-slot"><b>${esc(label)}</b><span>${esc(window)}</span></li>`;
  }).join('');
  const reason=!fresh?'Dữ liệu lịch đã cũ hoặc chưa có thời điểm kiểm tra; chưa đưa ra khung giờ để tránh đề xuất sai.':availability.status!=='available'?'Chưa thể xác nhận lịch trống từ nguồn lịch hiện có.':'';
  const windowLabel=availability.scheduling_window?.label||'Các lựa chọn lịch';
  return `<section class="chat-reader-section chat-reader-availability"><h3>${esc(windowLabel)}</h3><p class="chat-reader-availability-meta">${checkedText} · Múi giờ: ${esc(timezone)}. ${scope}</p>${reason?`<p class="chat-reader-availability-note">${esc(reason)}</p>`:''}${warnings.map(warning=>`<p class="chat-reader-availability-note">${esc(warning)}</p>`).join('')}${slots.length?`<ul class="chat-reader-slots">${slotMarkup}</ul><p class="chat-reader-availability-note">Đây là lịch trống của anh tại thời điểm kiểm tra; chưa xác nhận phía đối tác và chưa tạo sự kiện.</p>`:`<p class="chat-reader-availability-note">Chưa có khung giờ còn hiệu lực để đề xuất.</p>`}${staleCount>0&&fresh?`<p class="chat-reader-availability-note">Đã bỏ qua ${staleCount} khung giờ đã qua hoặc thiếu dữ liệu thời gian.</p>`:''}</section>`;
}
function chatQualityMarkup(report){
  const evaluation=report?.evaluation&&typeof report.evaluation==='object'?report.evaluation:{};
  const metrics=evaluation.metrics&&typeof evaluation.metrics==='object'?evaluation.metrics:{};
  const rubric=evaluation.rubric_version||'';
  const currentPolicy=chatReportPolicyCurrent(report);
  const metricLabels={
    source_coverage:'Bao phủ trích dẫn đã đối chiếu',
    freshness:'Độ mới của tin liên quan',unsupported_claims:'Nhận định chưa có nguồn',
    invalid_source_refs:'Nguồn không hợp lệ',contradictions:'Mâu thuẫn nguồn',source_count:'Tổng số nguồn (mọi loại)',
    public_source_count:'Số nguồn công khai',public_cited_source_count:'Số nguồn công khai được trích',
    public_publisher_count:'Publisher công khai (chưa chứng minh độc lập biên tập)',official_or_internal_sources:'Nguồn nội bộ hoặc được phân loại chính thức'
  };
  const metricRows=Object.entries(metricLabels).filter(([key])=>metrics[key]!==undefined||(['freshness','completeness'].includes(key)&&metrics[key]===null)).map(([key,label])=>{
    const value=metrics[key];
    const unknown=value===null||value===undefined||value==='unknown'||value==='unavailable'||metrics[`${key}_status`]==='unknown'||(key==='freshness'&&(metrics.freshness_unknown===true||metrics.freshness_known_sources===0));
    let formatted=unknown?'Chưa xác định':typeof value==='number'&&value>=0&&value<=1&&['completeness','source_coverage','source_diversity','freshness','overall','weighted_field_coverage','meeting_readiness'].includes(key)?`${Math.round(value*100)}%`:typeof value==='number'?String(value):String(value);
    return `<div class="chat-reader-quality-row"><span>${label}</span><b>${esc(formatted)}</b></div>`;
  }).join('');
  const gate=evaluation.gate_status||'';
  const verdict=!currentPolicy?'Chưa có kết luận theo chuẩn hiện tại':evaluation.release_allowed===true?'Đủ điều kiện phát hành':evaluation.release_allowed===false?`Chưa phát hành: ${metrics.unsupported_claims?`còn ${metrics.unsupported_claims} nhận định chưa đối chiếu được`:'còn điểm cần xử lý về bằng chứng'}`:'Chưa có kết luận';
  const semanticState=evaluation.status_details?.semantic_review||evaluation.semantic_review_status||evaluation.semantic_status||evaluation.judge?.status||'';
  const semanticLabels={passed:'Đối chiếu nội dung: đã đạt',failed:'Đối chiếu nội dung: không đạt',incomplete:'Đối chiếu nội dung: chưa đủ',unavailable:'Đối chiếu nội dung: chưa khả dụng',unavailable_or_incomplete:'Đối chiếu nội dung: chưa đủ hoặc chưa khả dụng'};
  const semanticText=semanticState==='passed'&&evaluation.release_allowed===false?'Bước AI đã chạy; báo cáo chưa vượt qua toàn bộ kiểm định':semanticLabels[semanticState]||'';
  const findings=Array.isArray(evaluation.issues)&&evaluation.issues.length?evaluation.issues.map(issue=>issue.message).filter(Boolean):Array.isArray(evaluation.findings)?evaluation.findings.filter(Boolean):[];
  const openItems=report.metadata?.reading_view?.open_items||[];
  const warnings=Array.isArray(evaluation.warnings)?evaluation.warnings.filter(item=>item&&!openItems.includes(item)):[];
  const readiness=evaluation.status_details?.readiness;
  const checklist=Array.isArray(readiness?.checklist)?readiness.checklist:[];
  const stateLabels={known:'Có dữ kiện hỗ trợ',self_reported:'Người gửi tự khai',unknown:'Chưa biết',conflicting:'Cần đối chiếu mâu thuẫn'};
  const checklistMarkup=checklist.length?`<ul>${checklist.map(item=>{
    const modern=report.metadata?.preparation_schema_version>=2;
    const answered=['provided','partial'].includes(item.answer_status);
    const state=modern&&item.answer_status==='partial'?`Biết một phần · ${stateLabels[item.state]||'Chưa biết'}`:modern&&item.answer_status==='requested'?'Muốn trao đổi, chưa có câu trả lời cụ thể':modern&&!answered?'Chưa biết':stateLabels[item.state]||'Chưa biết';
    const scope=modern&&answered&&!['identity','pilot'].includes(item.scope)?' (chỉ là bối cảnh hoặc lịch họp; chưa chốt cho pilot)':'';
    return `<li>${esc(item.label||item.key)}: ${esc(state)}${modern&&answered&&item.value?` — ${esc(item.value)}`:''}${item.answer_status==='partial'&&item.remaining_gap?`; cần làm rõ: ${esc(item.remaining_gap)}`:''}${esc(scope)}</li>`;
  }).join('')}</ul>`:'';
  const readinessMarkup=currentPolicy?`<p><b>Trao đổi ban đầu:</b> ${readiness?.discovery==='ready_with_limits'?'Đủ để khám phá nhu cầu, còn giới hạn cần xác minh.':'Chưa có đủ đánh giá chi tiết để xác nhận.'}</p><p><b>Pilot:</b> ${readiness?.pilot==='evidence_available_requires_approval'?'Đã có dữ kiện đầu vào, vẫn cần xác nhận và phê duyệt.':'Cần làm rõ phạm vi, dữ liệu và đầu mối quyết định.'}</p>${checklistMarkup}`:'';
  const diagnostics=Object.fromEntries(['completeness','source_diversity','overall','weighted_field_coverage','meeting_readiness'].filter(key=>metrics[key]!==undefined).map(key=>[key,metrics[key]]));
  const diagnosticsMarkup=Object.keys(diagnostics).length?`<details><summary>Chỉ số kỹ thuật theo rubric — không phải tỷ lệ chính xác hoặc đủ điều kiện triển khai</summary><pre>${esc(JSON.stringify(diagnostics,null,2))}</pre></details>`:'';
  const performance=report?.metadata?.performance&&typeof report.metadata.performance==='object'?report.metadata.performance:null;
  const performanceScope=performance?.scope||'';
  const formatSeconds=value=>Number.isFinite(value)?Number(value).toFixed(2):'';
  const durationSeconds=formatSeconds(performance?.duration_seconds);
  const duration=durationSeconds?`${performanceScope==='research_workflow'?'Thời gian workflow nghiên cứu':performanceScope==='end_to_end'?'Tổng thời gian tạo':'Thời gian xử lý'}: ${esc(durationSeconds)} giây.`:'';
  const collection=performance?.collection_performance&&typeof performance.collection_performance==='object'?performance.collection_performance:report?.metadata?.collection_performance&&typeof report.metadata.collection_performance==='object'?report.metadata.collection_performance:null;
  const collectionSeconds=formatSeconds(collection?.duration_seconds);
  const collectionDuration=collectionSeconds?`<p>Thời gian thu thập: ${esc(collectionSeconds)} giây.</p>`:'';
  const cache=performance&&performance.cache_hit!==undefined?` Cache: ${performance.cache_hit?'có sử dụng':'không sử dụng'}.`:'';
  const stages=performance?.stages&&typeof performance.stages==='object'?Object.entries(performance.stages).map(([name,value])=>{
    const seconds=typeof value==='number'?value:value?.duration_seconds;
    const reused=value?.reused;
    const stageSeconds=formatSeconds(seconds);
    return `<li>${esc(name)}${stageSeconds?` · ${esc(stageSeconds)} giây`:''}${reused?' · dùng lại kết quả':''}</li>`;
  }).join(''):'';
  const performanceMarkup=duration||collectionDuration||cache||stages?`<div class="chat-reader-performance"><b>Hiệu năng</b><p>${duration}${cache}</p>${collectionDuration}${stages?`<ul>${stages}</ul>`:''}</div>`:'';
  const qualityLabel=currentPolicy?'Đánh giá theo chuẩn hiện tại':rubric?'Cần đánh giá lại theo chuẩn hiện tại':'Chưa đánh giá theo chuẩn mới';
  const conclusion=currentPolicy&&evaluation.release_allowed&&readiness?.discovery==='ready_with_limits'?'Đủ thông tin để trao đổi ban đầu; còn điều kiện pilot cần làm rõ.':verdict;
  return `<section class="chat-reader-readiness"><p><b>${esc(conclusion)}</b></p></section><details class="chat-reader-quality"><summary>Chất lượng báo cáo</summary><div class="chat-reader-quality-body">${readinessMarkup}${findings.length?`<div><b>Điểm cần lưu ý</b><ul>${findings.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}<details class="chat-reader-technical"><summary>Chi tiết kiểm định và thời gian</summary><p class="chat-reader-quality-status"><b>${qualityLabel}</b>${gate?` · ${esc(gate)}`:''} · ${verdict}${semanticText?` · ${esc(semanticText)}`:''}</p>${metricRows?`<div class="chat-reader-quality-grid">${metricRows}</div>`:''}${warnings.length?`<div><b>Cảnh báo</b><ul>${warnings.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}${diagnosticsMarkup}${performanceMarkup}</details></div></details>`;
}
function chatReadableReport(report,responseTiming){
  const readingView=report.metadata?.reading_view;
  const compact=readingView?.version==='partner-brief-v2';
  const labels={
    company:'Đối tác là ai', contacts:'Người liên hệ', email_need:'Nhu cầu hợp tác',
    public_research:'Lĩnh vực và giải pháp', company_scale:'Quy mô và vận hành',
    business_context:'Bối cảnh liên quan', recent_updates:'Cập nhật công khai',
    meeting_preparation:'Mục tiêu và câu hỏi chuẩn bị', meeting_context:'Chuẩn bị cuộc gặp',
    risks_opportunities:'Cơ hội và điều cần làm rõ'
  };
  const identity=report.metadata?.partner_identity||{}, sources=(report.sources||[]).filter(s=>!s.derived);
  const sourceById=new Map(sources.map(source=>[String(source.id),source]));
  const normalizeUrl=url=>{
    try{
      const parsed=new URL(String(url||''));
      if(!['http:','https:'].includes(parsed.protocol)||!parsed.hostname)return '';
      parsed.protocol=parsed.protocol.toLowerCase();
      parsed.hostname=parsed.hostname.toLowerCase().replace(/^www\./,'');
      parsed.hash='';
      const kept=Array.from(parsed.searchParams.entries()).filter(([key])=>!(/^(?:utm_|gclid|fbclid)/i.test(key)));
      parsed.search=''; kept.sort((a,b)=>`${a[0]}=${a[1]}`.localeCompare(`${b[0]}=${b[1]}`)); kept.forEach(([key,value])=>parsed.searchParams.append(key,value));
      parsed.pathname=parsed.pathname.replace(/\/$/,'')||'/';
      return parsed.href;
    }catch{return '';}
  };
  const sourceUrl=source=>{
    try{const parsed=new URL(source?.url||'');return ['http:','https:'].includes(parsed.protocol)?parsed.href:'';}catch{return '';}
  };
  const citationPresentation=report.metadata?.citation_presentation;
  const presentationMap=citationPresentation&&typeof citationPresentation==='object'&&!Array.isArray(citationPresentation)
    ?(citationPresentation.sources||citationPresentation.by_source_id||citationPresentation):{};
  const presentationRows=[];
  if(Array.isArray(presentationMap))presentationMap.forEach((entry,index)=>{
    if(entry&&typeof entry==='object')presentationRows.push({id:entry.id||entry.source_id||String(index),...entry});
  });
  else Object.entries(presentationMap).forEach(([id,entry])=>{
    if(typeof entry==='number')presentationRows.push({id,number:entry});
    else if(entry&&typeof entry==='object')presentationRows.push({id,...entry});
  });
  const aliases=new Map();
  presentationRows.forEach(row=>{
    const ids=[row.id,row.source_id,...(Array.isArray(row.source_ids)?row.source_ids:[]),...(Array.isArray(row.aliases)?row.aliases:[])].filter(Boolean).map(String);
    ids.forEach(id=>aliases.set(id,String(row.id)));
  });
  const publicSources=[],urls=new Set(),sourceNumbersById=new Map(),sourceNumbersByUrl=new Map();
  const addPublic=(source,number)=>{
    const url=sourceUrl(source),normalized=normalizeUrl(url);
    if(!url||!normalized)return;
    let existing=publicSources.find(item=>normalizeUrl(sourceUrl(item))===normalized);
    if(!existing){existing=source;publicSources.push(source);}
    const highest=Array.from(sourceNumbersByUrl.values()).reduce((max,value)=>Math.max(max,Number(value)||0),0);
    const assigned=sourceNumbersByUrl.has(normalized)?sourceNumbersByUrl.get(normalized):Number.isFinite(Number(number))?Number(number):highest+1;
    sourceNumbersByUrl.set(normalized,assigned);
    sourceNumbersById.set(String(source.id),assigned);
    urls.add(normalized);
  };
  const presentationHasRows=presentationRows.some(row=>row.number!==undefined||row.citation_number!==undefined);
  if(presentationHasRows){
    const rowNumber=row=>row.number!==undefined?row.number:row.citation_number;
    presentationRows.sort((a,b)=>Number(rowNumber(a)??Infinity)-Number(rowNumber(b)??Infinity));
    presentationRows.forEach(row=>{
      const source=sourceById.get(String(row.id))||sourceById.get(aliases.get(String(row.id))||'');
      if(source&&row.public!==false&&sourceUrl(source))addPublic(source,rowNumber(row));
    });
  }
  for(const source of sources){
    const server=sourceById.get(String(source.id))&&presentationMap[String(source.id)];
    const serverPublic=server&&typeof server==='object'&&server.public===true;
    if((serverPublic||!presentationHasRows&&['web','news'].includes(source.source_type))&&sourceUrl(source)&&!urls.has(normalizeUrl(sourceUrl(source)))){
      addPublic(source,sourceNumbersById.get(String(source.id)));
    }
  }
  const sourceNumber=(source)=>sourceNumbersById.get(String(source?.id))||sourceNumbersByUrl.get(normalizeUrl(sourceUrl(source)))||null;
  const sourceLabel=source=>{
    if(!source)return 'Nguồn chưa xác minh';
    const type={email:'Email nội bộ',calendar:'Lịch đã kiểm tra',memory:'Lịch sử nội bộ',internal_knowledge:'Tri thức nội bộ'}[source.source_type];
    return type||'Nguồn nội bộ';
  };
  const citeSource=id=>{
    const source=sourceById.get(String(id));
    const url=sourceUrl(source), index=sourceNumber(source);
    return index?`[${index}](${url.replace(/\(/g,'%28').replace(/\)/g,'%29')})`:`[${sourceLabel(source)}]`;
  };
  const citationHtml=id=>{
    const source=sourceById.get(String(id));
    const url=sourceUrl(source), index=sourceNumber(source);
    return index?`<a class="chat-reader-citation" href="${esc(url)}" target="_blank" rel="noopener noreferrer">[${index}]</a>`:`<span class="chat-reader-citation chat-reader-citation-internal">${esc(sourceLabel(source))}</span>`;
  };
  const citeIds=Array.from(sourceById.keys()).sort((a,b)=>b.length-a.length).map(id=>id.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
  const citePattern=citeIds.length?new RegExp(`\\[(${citeIds.join('|')})\\]`,'g'):null;
  const prose=text=>{
    let value=String(text||'');
    if(citePattern)value=value.replace(citePattern,(_,id)=>citeSource(id));
    value=value.replace(/\]\((?:https?:\/\/[^)\s]+)\)\[/g,match=>match.replace(')[', ') ['));
    // Older payloads used S1/W1 even when the source record was dropped. Keep
    // those implementation ids out of the reader rather than exposing them.
    return renderMarkdown(value.replace(/\[((?:S|W|E|C|M)\d+)\]/g,'[Nguồn chưa xác minh]'));
  };
  const missingText=item=>{
    if(typeof item==='string')return prose(item);
    if(!item||typeof item!=='object')return '';
    const text=item.text||item.detail||item.reason||'';
    const refs=Array.isArray(item.source_ids)?item.source_ids.map(citationHtml).join(' '):'';
    return `${prose(text)}${refs?` <span class="chat-reader-evidence">${refs}</span>`:''}`;
  };
  const warningNotes=[];
  (identity.conflicts||[]).forEach(note=>warningNotes.push(['Danh tính công ty chưa thống nhất',note]));
  (identity.affiliation_warnings||[]).forEach(note=>warningNotes.push(['Quyền đại diện chưa được xác minh',note]));
  if(!report.metadata?.evidence_policy_version)warningNotes.push(['Kiểm tra cũ', 'Bản báo cáo được tạo trước chính sách kiểm tra danh tính mới. Cần xác minh lại trước khi sử dụng.']);
  const identityWarning=warningNotes.length?`<aside class="chat-reader-warning"><b>${esc(warningNotes[0][0])}</b>${compact?'':warningNotes.map((entry,index)=>`${index?`<b class="chat-reader-warning-label">${esc(entry[0])}</b>`:''}<p>${esc(entry[1])}</p>`).join('')}</aside>`:'';
  const sectionEntries=Object.entries(labels).filter(([key])=>report.sections?.[key]);
  const renderedSections=compact?readingView.blocks.map(block=>`<section class="chat-reader-section"><h3>${esc(block.title)}</h3>${prose(block.text)}</section>`).join(''):sectionEntries.map(([key,label])=>`<section class="chat-reader-section"><h3>${label}</h3>${prose(report.sections[key])}</section>`).join('');
  const availability=chatAvailabilityMarkup(report.metadata?.availability);
  const quality=chatQualityMarkup(report);
  const sourceItem=source=>{
    const url=sourceUrl(source);
    const date=source.published_at?`<small>${esc(source.published_at)}</small>`:'';
    return `<li value="${sourceNumbersById.get(String(source.id))||1}">${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(source.title||url)}</a>`:esc(source.title||sourceLabel(source))}${date}${source.metadata?.snippet_only?'<small>Chưa đọc được toàn văn — không dùng làm bằng chứng</small>':''}</li>`;
  };
  const citedText=[report.executive_summary,...Object.values(report.sections||{}),...(readingView?.open_items||[]),...(report.claims||[]).flatMap(claim=>[claim.text,...(claim.source_ids||[]).map(id=>`[${id}]`)]),...(report.metadata?.information_coverage||[]).flatMap(item=>[item.summary,...(item.source_ids||[]).map(id=>`[${id}]`)])].join('\n');
  const visibleSources=compact?publicSources.filter(source=>[...sourceNumbersById.entries()].some(([id,number])=>number===sourceNumbersById.get(source.id)&&citedText.includes(`[${id}]`))):publicSources;
  const primarySources=visibleSources.slice(0,8), extraSources=visibleSources.slice(8);
  const sourceSection=visibleSources.length?`<section class="chat-reader-section"><h3>Nguồn tham khảo</h3><p class="chat-reader-source-note">Các số trong báo cáo dẫn tới đúng trang nguồn.</p><ol>${primarySources.map(sourceItem).join('')}</ol>${extraSources.length?`<details class="chat-reader-extra-sources"><summary>Xem thêm ${extraSources.length} nguồn đã được trích dẫn</summary><ol start="9">${extraSources.map(sourceItem).join('')}</ol></details>`:''}</section>`:'';
  const contradictionItems=(report.contradictions||[]).map(item=>{
    const text=typeof item==='string'?item:item?.description||item?.text||'';
    const refs=typeof item==='object'&&Array.isArray(item.source_ids)?item.source_ids.map(citationHtml).join(' '):'';
    return `<li>${prose(text)}${refs?` <span class="chat-reader-evidence">${refs}</span>`:''}</li>`;
  }).join('');
  const contradictionSection=contradictionItems&&!compact?`<section class="chat-reader-section"><h3>Mâu thuẫn cần lưu ý</h3><ul>${contradictionItems}</ul></section>`:'';
  const claimDetails=(report.claims||[]).map(claim=>{
    const refs=(claim.source_ids||[]).filter(id=>!(claim.text||'').includes(`[${id}]`)).map(citationHtml).join(' ');
    return `<p>${prose(claim.text)}${refs?` <span class="chat-reader-evidence">${refs}</span>`:''}</p>`;
  }).join('');
  const provenance=sources.filter(source=>!publicSources.includes(source));
  const uniqueProvenance=compact?[...new Map(provenance.filter(source=>citedText.includes(`[${source.id}]`)).map(source=>[`${source.source_type}:${source.title}:${source.excerpt}`,source])).values()]:provenance;
  const provenanceDetails=uniqueProvenance.length?`<ul>${uniqueProvenance.map(source=>`<li>${esc(source.title||sourceLabel(source))}</li>`).join('')}</ul>`:'';
  const notes=compact?readingView.open_items||[]:report.missing_information||[];
  const timing=chatReportTimingMarkup(report.report_id,responseTiming);
  const body=`${chatReportSnapshotMarkup(report)}${timing}${identityWarning}<section class="chat-reader-summary">${prose(report.executive_summary||'Chưa đủ bằng chứng để tóm tắt.')}</section>${renderedSections}${notes.length?`<section class="chat-reader-section"><h3>Điểm chưa xác minh</h3><ul>${notes.map(item=>`<li>${missingText(item)}</li>`).join('')}</ul></section>`:''}${availability}${contradictionSection}${sourceSection}${quality}<details class="chat-validation"><summary>Đối chiếu dữ kiện và nguồn gốc tại thời điểm lập báo cáo</summary>${claimDetails}${provenanceDetails}</details>`;
  return `<article class="chat-reader-article">${body}</article>`;
}
function chatReportTimingMarkup(reportId,responseTiming){
  const turns=typeof CHAT!=='undefined'?CHAT.filter(item=>(item.reports||[]).some(ref=>ref.report_id===reportId)&&item.response_timing?.scope==='backend_response'):[];
  const timing=responseTiming?.scope==='backend_response'?responseTiming:turns.length===1?turns[0].response_timing:null;
  const seconds=timing?.duration_seconds;
  const phases=timing?.phases;
  const labels={lock_wait:'Chờ lượt xử lý',session_setup:'Chuẩn bị phiên',agent_response:'Xử lý yêu cầu'};
  const phaseDetails=phases?`<details class="chat-reader-technical"><summary>Chi tiết thời gian lượt chat</summary><ul>${Object.entries(phases).filter(([,v])=>Number.isFinite(v)&&v>=0).map(([k,v])=>`<li>${esc(labels[k]||k)}: ${v.toFixed(2)} giây</li>`).join('')}</ul>${timing.inbox_phases?`<p>Các bước bên trong xử lý yêu cầu (không cộng thêm vào tổng):</p><pre>${esc(JSON.stringify(timing.inbox_phases,null,2))}</pre>`:''}</details>`:'';
  return `<p class="chat-reader-source-note">${typeof seconds==='number'&&Number.isFinite(seconds)&&seconds>=0?`Thời gian xử lý toàn lượt chat: ${seconds.toFixed(2)} giây (backend, không gồm mạng và hiển thị).`:'Chưa đo được tổng thời gian xử lý lượt chat tương ứng.'}</p>${phaseDetails}`;
}
function chatReportDialog(title,body,footer){
  document.getElementById('chat-approval-dialog')?.remove();
  const dialog=document.createElement('dialog');dialog.className='nb-dialog chat-report-dialog';dialog.setAttribute('aria-label',title);dialog.id='chat-approval-dialog';
  dialog.innerHTML=`<div class="nb-dialog-head"><h2>${esc(title)}</h2><button aria-label="Đóng" onclick="document.getElementById('chat-approval-dialog').remove()">×</button></div><div class="nb-dialog-body">${body}<p id="chat-approval-error" role="alert"></p></div><div class="nb-dialog-foot"><span data-copy-status role="status" aria-live="polite"></span><button type="button" class="nb-btn" onclick="chatCopyReport(this)">Copy nội dung</button>${footer}</div>`;
  document.body.appendChild(dialog);dialog.showModal();return dialog;
}
async function chatCopyReport(button){
  const dialog=button.closest('dialog'),status=dialog.querySelector('[data-copy-status]');
  const content=dialog.querySelector('.chat-approval-content')||dialog.querySelector('.nb-dialog-body');
  const title=dialog.querySelector('h2').innerText;
  const links=[...new Set(Array.from(content.querySelectorAll('a[href]')).map(a=>a.getAttribute('href')).filter(url=>/^https?:\/\//i.test(url)))];
  const text=`${title}\n\n${content.innerText.trim()}${links.length?'\n\nLiên kết nguồn:\n'+links.join('\n'):''}`;
  button.disabled=true;status.textContent='';
  try{
    await navigator.clipboard.writeText(text);
    status.textContent='Đã copy nội dung.';
  }catch{
    status.textContent='Chưa copy được. Anh kiểm tra quyền clipboard của trình duyệt rồi thử lại nhé.';
  }finally{button.disabled=false;}
}
async function chatOpenReport(button){
  button.disabled=true;
  try{
    const detail=await chatReportDetail(button.dataset.ws,button.dataset.report);
    const report=detail.report.payload;
    const seconds=button.dataset.responseSeconds!==undefined&&button.dataset.responseSeconds!==''?Number(button.dataset.responseSeconds):NaN;
    const timing=Number.isFinite(seconds)&&seconds>=0?{scope:'backend_response',duration_seconds:seconds}:undefined;
    const url=`/api/workspace/export?id=${encodeURIComponent(button.dataset.ws)}&report=${encodeURIComponent(button.dataset.report)}&format=md`;
    const versions=detail.versions||[],index=versions.findIndex(v=>v.report_id===report.report_id);
    const newer=index>0?versions[0]:null;
    const newerMarkup=newer?`<p class="nb-notice">Đã có phiên bản mới hơn. <button class="nb-btn" data-ws="${esc(button.dataset.ws)}" data-report="${esc(newer.report_id)}" onclick="chatOpenReport(this)">Đọc phiên bản mới hơn</button></p>`:'';
    const update=!chatReportPolicyCurrent(report)?`<span data-report-update-status role="status"></span><button class="nb-btn" data-ws="${esc(button.dataset.ws)}" onclick="chatUpdateReport(this)">Tạo bản cập nhật</button>`:'';
    chatReportDialog(report.title,`${newerMarkup}${chatReportPolicyCurrent(report)&&report.evaluation?.release_allowed!==true?'<p class="nb-notice">Bản nháp cần xác minh thêm.</p>':''}<div class="chat-approval-content">${chatReadableReport(report,timing)}</div>`,`${update}<a class="nb-btn" href="${esc(url)}" download>Tải báo cáo</a><button class="nb-btn" onclick="document.getElementById('chat-approval-dialog').remove()">Đóng</button>`);
  }catch(e){const card=button.closest('.chat-report-attachment');const error=card?.querySelector('[data-report-error]')||document.getElementById('chat-approval-error');if(error)error.textContent=e.message;}
  finally{button.disabled=false;}
}
async function chatUpdateReport(button){
  if(button.disabled)return;
  const status=button.parentElement.querySelector('[data-report-update-status]');
  button.disabled=true;
  try{
    const result=await postJSON('/api/briefing',{op:'enqueue',workspace_id:button.dataset.ws});
    if(result.error)throw new Error(result.error);
    const jobs=(result.jobs||[]).filter(item=>item.workspace_id===button.dataset.ws);
    const job=jobs.find(item=>['queued','running','retrying'].includes(item.status))||jobs[0];
    let message='Đã xếp hàng tạo phiên bản mới.';
    if(job?.status==='completed')message='Phiên bản cập nhật đã hoàn tất.';
    else if(job?.status==='failed')throw new Error(job.error||'Chưa tạo được phiên bản mới.');
    else if(!result.enabled)message='Đã xếp hàng; tự động đang tạm dừng. Bật lại tại trang Hôm nay để xử lý.';
    else if(!result.model_configured)message='Đã xếp hàng; cần kết nối model để xử lý.';
    else if(!result.worker_active)message='Đã xếp hàng; đang chờ worker hoạt động.';
    const follow=job?.status==='completed'&&job.report_id?`<button class="nb-btn" data-ws="${esc(button.dataset.ws)}" data-report="${esc(job.report_id)}" onclick="chatOpenReport(this)">Đọc bản cập nhật</button>`:`<a href="#research/${encodeURIComponent(button.dataset.ws)}" onclick="document.getElementById('chat-approval-dialog').remove()">Theo dõi bản cập nhật</a>`;
    status.innerHTML=`${esc(message)} ${follow}`;
    button.textContent='Đã yêu cầu cập nhật';
  }catch(error){status.textContent=error.message;button.disabled=false;}
}
async function chatReviewAction(id){
  const action=((D&&D.approvals||{}).items||[]).find(a=>a.id===id);if(!action)return;
  const a=action.arguments;
  try{
    const detail=await chatReportDetail(a.workspace_id,a.report_id), report=detail.report.payload;
    const sending=action.tool_name==='forward_report_email';
    const body=`${a.recipient?`<p><b>Người nhận:</b> ${esc(a.recipient)}<br><b>Tiêu đề:</b> ${esc(a.subject)}</p><p>${esc(a.intro)}</p>`:'<p>Anh đang duyệt lưu toàn bộ báo cáo dưới đây, kèm các trích dẫn nguồn, vào sổ tay.</p>'}<div class="chat-approval-content">${chatReadableReport(report)}</div>`;
    chatReportDialog(sending?'Duyệt gửi báo cáo':'Import báo cáo vào sổ tay',body,`<button class="nb-btn" onclick="chatDecision('${esc(id)}','reject')">Từ chối</button><button class="nb-btn primary" onclick="chatDecision('${esc(id)}','approve_execute')">${sending?'Duyệt & gửi':'Duyệt & lưu'}</button>`);
  }catch(e){alert(e.message);}
}
async function chatDecision(id,op){
  const dialog=document.getElementById('chat-approval-dialog');if(!dialog)return;
  dialog.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{
    const result=await postJSON('/api/approvals',{id,op});
    if(result.error||result.result&&!result.result.ok)throw new Error(result.error||result.result.output);
    dialog.remove();await refresh();syncChatLogs();
  }catch(e){dialog.querySelector('#chat-approval-error').textContent=e.message;dialog.querySelectorAll('button').forEach(b=>b.disabled=false);}
}
VIEWS.chat=inboxChatView;
