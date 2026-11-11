
const token='__LOCAL_TOKEN__';
const $=s=>document.querySelector(s),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stages=['未开始','等待资料','处理中','待复核','待签字','待申报','已完成'],filings=['未提交','已提交','已接受','被退回','不适用'];
let assigneeNames=[];let config={},rows=[],current=null,tab='表格与核对',timer,creatingPerson=null,edited=false;
async function api(path,data){let r;try{r=await fetch(path,{method:data?'POST':'GET',headers:{'X-Local-Token':token,'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined})}catch{throw Error('无法连接服务器，请确认报税服务已启动后再刷新。未保存内容仍保留在页面中。')}if(r.status===401){location.replace('/login');throw Error('请重新登录')}const value=await r.json();if(!r.ok)throw Error(value.error||'请求失败');return value}
function message(s){$('#message').textContent=s;$('#message').classList.remove('hidden');clearTimeout(timer);timer=setTimeout(()=>$('#message').classList.add('hidden'),6500)}
function canLeave(){return !edited||confirm('有尚未保存的修改，确定离开吗？')}
function permit(){document.querySelectorAll('.admin-only').forEach(el=>el.classList.toggle('hidden',config.user?.role!=='admin'));document.querySelectorAll('[data-write]').forEach(el=>el.disabled=config.user?.role==='viewer');if(config.user?.role==='viewer')document.querySelectorAll('#edit-form input,#edit-form textarea,#edit-form select').forEach(el=>el.disabled=true)}
function payment(r){const balance=Number(r.fee)-Number(r.paid);return Number(r.fee)===0?'未登记应收':balance<=0?'已付':Number(r.paid)>0?'部分付款':'未付'}
function materials(r){const items=r.intake||[],missing=items.filter(x=>x.state==='missing').length,received=items.filter(x=>x.state==='received').length;return `<details><summary>${items.length?`已收 ${received} · 待收 ${missing}`:'尚未登记'}</summary><ul class="bullets">${items.map(x=>`<li><a href="/?id=${r.id}&tab=${encodeURIComponent('资料清单')}">${esc(x.label)}</a> · ${esc({missing:'待收',received:'已收（核对另计）',not_applicable:'不适用'}[x.state])}</li>`).join('')||'<li>进入客户登记应交资料</li>'}</ul></details>`}
function cells(r,withName=true){return `${withName?`<td><button class="name" data-open="${r.id}">${esc(r.alias)}</button><div class="muted">${esc(r.email||r.phone||'未填联系方式')}</div></td>`:''}<td>${r.tax_year}</td><td><span class="badge">${esc(r.stage)}</span><div class="muted">${esc(r.assignee||'未分配')}</div></td><td>${esc(r.due_date||'未设置')}<div class="muted">目标 ${esc(r.target_date||'未设置')}</div></td><td>${materials(r)}</td><td><span class="badge ${payment(r)==='未付'?'warning':''}">${payment(r)}</span><div class="money muted">应收 ${esc(r.fee)} / 已收 ${esc(r.paid)}</div></td><td><button data-open="${r.id}">进入</button></td>`}
function render(){const q=$('#search').value.trim().toLowerCase(),year=$('#year').value,stage=$('#stage').value;const filtered=rows.filter(r=>(!year||String(r.tax_year)===year)&&(!stage||r.stage===stage)&&(!q||[r.alias,r.email,r.phone,r.assignee].join(' ').toLowerCase().includes(q)));const unique=new Set(filtered.map(r=>r.contact_id)).size;$('#metrics').innerHTML=[[unique,'客户'],[filtered.filter(r=>r.intake.some(i=>i.state==='missing')).length,'年度待收资料'],[filtered.filter(r=>r.stage==='待复核').length,'年度待复核'],[filtered.filter(r=>Number(r.fee)>Number(r.paid)).length,'年度服务费未结清']].map(([n,label])=>`<div class="card"><strong>${n}</strong><span class="muted">${label}</span></div>`).join('');
if(year)$('#rows').innerHTML=filtered.map(r=>`<tr>${cells(r)}</tr>`).join('');else{const groups=new Map();for(const r of filtered){if(!groups.has(r.contact_id))groups.set(r.contact_id,[]);groups.get(r.contact_id).push(r)}$('#rows').innerHTML=[...groups.values()].map(list=>`<tr><td><strong>${esc(list[0].alias)}</strong><div class="muted">${esc(list[0].email||list[0].phone)}</div></td><td colspan="6"><details><summary>${list.length} 个年度 · 最新 ${list[0].tax_year}</summary><div class="tablewrap"><table><tbody>${list.map(r=>`<tr>${cells(r,false)}</tr>`).join('')}</tbody></table></div></details></td></tr>`).join('')}
if(!filtered.length)$('#rows').innerHTML='<tr><td colspan="7" class="empty">没有匹配客户。可新建客户，或调整筛选。</td></tr>';document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>{tab='表格与核对';openClient(Number(b.dataset.open)).catch(e=>message(e.message))});permit()}
async function load(){const old=$('#year').value;rows=await api('/api/crm');const years=[...new Set(rows.map(r=>r.tax_year))].sort((a,b)=>b-a);$('#year').innerHTML='<option value="">全部年度（展开历史）</option>'+years.map(y=>`<option>${y}</option>`).join('');$('#year').value=years.includes(Number(old))?old:years[0]||'';render()}
function field(key,label,type='text'){return `<div class="field"><label for="f-${key}">${label}</label><input id="f-${key}" name="${key}" type="${type}" ${['fee','paid'].includes(key)?'step="0.01" min="0"':''} value="${esc(current[key])}" maxlength="2000"></div>`}
function select(key,label,values){return `<div class="field"><label>${label}</label><select name="${key}">${values.map(v=>`<option ${current[key]===v?'selected':''}>${esc(v)}</option>`).join('')}</select></div>`}
function assigneeSelect(){const names=[...new Set([...assigneeNames,current.assignee].filter(Boolean))];return `<div class="field"><label for="f-assignee">负责人</label><select id="f-assignee" name="assignee"><option value="">未分配</option>${names.map(n=>`<option value="${esc(n)}" ${current.assignee===n?'selected':''}>${esc(n)}</option>`).join('')}</select><button type="button" id="add-assignee-inline" data-write style="margin-top:7px">＋ 新增负责人</button></div>`}
function workLink(){return '/workspace?client_id='+current.id}
function renderDetail(){const c=current;$('#title').textContent=c.alias+' · '+c.tax_year;$('#detail-sub').textContent=c.stage+' · '+(c.assignee||'未分配负责人');$('#review').href='/?id='+c.id+'&tab='+encodeURIComponent('表格与核对');const tabs=['概况','资料清单','文件与路径','表格与核对','收费记录','操作历史'];$('#tabs').innerHTML=tabs.map(t=>`<button data-tab="${t}" class="${tab===t?'active':''}">${t}</button>`).join('');let html='';
if(tab==='概况')html=`<form id="edit-form" class="panel"><div class="grid"><section><h2>长期客户信息</h2>${field('alias','客户名称 / 代号')}${field('email','邮箱','email')}${field('phone','联系电话')}</section><section><h2>年度工作进度</h2>${select('stage','工作阶段',stages)}${assigneeSelect()}${select('filing','申报状态（人工跟踪）',filings)}${field('target_date','内部完成目标','date')}${field('due_date','申报截止日期','date')}</section></div><div class="field"><label>年度备注 / 下一步</label><textarea name="notes" rows="3" maxlength="2000">${esc(c.notes)}</textarea></div><button class="primary" data-write>保存概况</button></form>`;
if(tab==='文件与路径')html=`<form id="edit-form" class="panel"><h2>年度文件位置</h2>${field('source_path','原始资料文件夹')}<button type="button" id="preview-saved-folder">读取文件清单</button><div id="saved-folder-preview" class="muted" role="status"></div>${field('return_path','税表文件夹')}${field('proseries_path','ProSeries 客户报税文件路径')}<p class="notice">保存路径不会复制或备份外部文件，也不会打开 ProSeries。可复制路径到文件资源管理器；已上传 PDF 可在下方打开。</p><button class="primary" data-write>保存路径</button></form><section class="panel" style="margin-top:18px"><h2>文件与资料关联</h2><p id="folder-status" class="notice">${c.folder_job?`文件夹导入：${esc(c.folder_job.status)} · ${c.folder_job.progress} / ${c.folder_job.total} 份${JSON.parse(c.folder_job.errors||'[]').length?' · 有文件失败，请重试并查看历史':''}`:'保存文件夹路径后，可扫描并识别资料'}</p><button id="scan-folder" data-write>扫描文件夹并识别资料</button><div class="bar"><button id="add-link" data-write>＋ 登记文件关联</button><a class="action" href="${workLink()}">上传 PDF / 读取文件</a></div>${linksHtml()}${c.documents.map(d=>`<div class="row"><strong>${esc(d.filename)}</strong> <span class="badge">${d.role==='source'?'原始资料':'税表对照'}</span><p>${d.page_count} 页 · ${esc(d.status)} · ${esc((c.document_forms?.[String(d.id)]||[]).join(" / ")||"尚未分类或非收入资料")}</p><a target="_blank" rel="noopener" href="${docUrl(d.id)}">打开 PDF</a> · <a href="/?id=${c.id}&tab=${encodeURIComponent("表格与核对")}&document_id=${d.id}">查看表格与原件</a></div>`).join('')||'<p class="muted">尚无上传文件。</p>'}</section>`;
if(tab==='资料清单')html=`<section class="panel"><div class="bar"><h2>已识别税表</h2><button id="identified-refresh">刷新资料清单</button><button id="scan-folder" data-write>扫描文件夹并识别资料</button></div><div id="identified-forms" role="region" aria-label="已识别税表"></div><div id="document-review" role="region" aria-label="金额与原件" hidden></div></section>`+`<section class="panel"><h2>应交资料</h2><div class="bar"><a class="action" href="${workLink()}&section=intake">登记 / 修改应交资料</a><button id="add-link" data-write>＋ 关联文件或页面</button></div>${c.intake.map(i=>`<div class="row"><strong>${esc(i.label)}</strong> <span class="badge">${esc({missing:'待收',received:'已收',not_applicable:'不适用'}[i.state])}</span><p class="muted">${esc(i.notes)}</p>${i.document_id?`<a target="_blank" rel="noopener" href="${docUrl(i.document_id)}">打开已关联 PDF</a>`:''}${c.links.filter(l=>l.intake_id===i.id).map(l=>`<p>${linkItem(l)}</p>`).join('')}</div>`).join('')||'<p class="empty">尚未登记应交资料。</p>'}<p class="notice">已收表示收集状态；是否核对通过请进入表格核对查看。</p></section>`;
if(tab==='表格与核对'||tab==='文件与路径')html=`<section class="panel"><div class="bar"><h2>资料与原件核对</h2><a class="action" href="${workLink()}">打开编辑工作台</a><button id="review-refresh">刷新识别结果</button></div><div id="document-review" role="region" aria-label="资料与原件核对"></div></section>`+html;
if(tab==='收费记录')html=`<form id="edit-form" class="panel"><h2>服务费收费</h2><p class="muted">${payment(c)} · 余额 ${(Number(c.fee)-Number(c.paid)).toFixed(2)}</p><div class="grid">${field('fee','应收服务费','number')}${field('paid','已收服务费','number')}${field('payment_due','付款到期日','date')}</div><p class="notice">此处记录服务费汇总，不表示客户税款已缴纳。每次保存会记入操作历史。</p><button class="primary" data-write>保存收费信息</button></form>`;
if(tab==='操作历史')html=`<section class="panel"><h2>CRM 修改历史</h2>${c.history.map(h=>`<div class="row"><strong>${esc(h.event)}</strong><p class="muted">${esc(h.actor)} · ${esc(new Date(h.created).toLocaleString())}</p><details><summary>查看保存内容</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(JSON.parse(h.after_json),null,2))}</pre></details></div>`).join('')||'<p class="empty">暂无 CRM 修改。</p>'}<p class="muted">原始字段修改历史保留在年度核对工作台；管理员可查看服务器操作记录。</p></section>`;
$('#content').innerHTML=html;if($('#identified-forms')){loadIdentifiedForms();$('#identified-refresh').onclick=loadIdentifiedForms}else if($('#document-review')){loadDocumentReview();$('#review-refresh').onclick=()=>loadDocumentReview()}document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{if(!canLeave())return;edited=false;tab=b.dataset.tab;renderDetail()});if($('#edit-form')){$('#edit-form').oninput=()=>edited=true;$('#edit-form').onsubmit=save}if($('#preview-saved-folder'))bindFolderPreview($('#edit-form [name=source_path]'),$('#saved-folder-preview'),$('#preview-saved-folder'),true);if($('#scan-folder'))$('#scan-folder').onclick=async()=>{if(edited){message('请先保存文件夹路径');return}try{const r=await api('/api/crm/scan-folder',{client_id:current.id});message('已扫描 '+r.files+' 份资料，正在后台导入识别');current=await api('/api/crm?id='+current.id);renderDetail()}catch(e){message(e.message)}};if($('#add-link'))$('#add-link').onclick=showLink;if($('#add-assignee-inline'))$('#add-assignee-inline').onclick=()=>showAssignees();permit()}
let reviewSelection={client:null,document:null,page:null};
let reviewRequest=0;

function filingDestination(type, year){
    const destinations={
        'W-2': year===2025?'Form 1040 第 1a 行（工资）、第 25a 行（联邦预扣）':'Form 1040 工资及联邦预扣',
        '1099-INT':'Form 1040 利息；适用时列入 Schedule B Part I',
        '1099-DIV':'Form 1040 股息；适用时列入 Schedule B Part II，资本利得分配另行核对',
        '1099-B':'Schedule D；按交易情况核对是否需要 Form 8949',
        'SSA-1099':'Form 1040 社会保障福利',
        '1040-reference':'Form 1040 对照税表'
    };
    return destinations[type]||(type.startsWith('Schedule ')?'已识别的申报附表':'待确认申报位置');
}

async function loadIdentifiedForms(){
    const panel=$('#identified-forms'), client=current;
    panel.textContent='正在读取已识别税表…';
    try{
        const data=await api('/api/workspace?client_id='+client.id);
        if(!panel.isConnected)return;
        const groups=new Map();
        function add(documentId,type,pageId,pageNumber,hasAmounts=false){
            const key=documentId+':'+type;
            if(!groups.has(key))groups.set(key,{documentId,type,pages:new Map(),firstPage:pageId,hasAmounts:false});
            const group=groups.get(key);
            group.pages.set(pageId,pageNumber);
            if(hasAmounts&&!group.hasAmounts)group.firstPage=pageId;
            group.hasAmounts||=hasAmounts;
        }
        for(const record of data.records){
            if(record.status==='excluded'||record.disposition==='excluded')continue;
            const hasAmounts=Object.values(record.values||{}).some(value=>value!=null&&value!=='');
            add(record.document_id,record.form_type,record.page_id,record.page_number,hasAmounts);
        }
        for(const page of data.pages){
            if(page.schedule&&page.disposition!=='excluded')add(page.document_id,page.schedule,page.id,page.page_number);
        }
        const documents=new Map(data.documents.map(doc=>[doc.id,doc]));
        const forms=[...groups.values()];
        const recognized=new Set(forms.map(form=>form.documentId));
        panel.innerHTML=forms.length?`<div style="overflow-x:auto"><table class="review-fields"><thead><tr><th>资料类型</th><th>来源文件</th><th>联邦申报参考</th><th>核对</th></tr></thead><tbody>${forms.map((form,index)=>{
            const label=form.type==='1040-reference'?'Form 1040':form.type;
            return `<tr><td><strong>${esc(label)}</strong></td><td>${esc(documents.get(form.documentId)?.filename)}<br><small>${form.pages.size} 页</small></td><td>${esc(filingDestination(form.type,Number(client.tax_year)))}</td><td><button type="button" data-form-review="${index}">${form.hasAmounts?'金额与原件':'查看原件'}</button></td></tr>`;
        }).join('')}</tbody></table></div>`:'<p class="muted">暂无已识别税表。</p>';
        const other=data.documents.filter(doc=>!recognized.has(doc.id));
        if(other.length)panel.innerHTML+=`<details><summary>未识别为税表的文件（${other.length}）</summary><ul>${other.map(doc=>`<li><a href="/api/crm/document?client_id=${client.id}&document_id=${doc.id}" target="_blank" rel="noopener">${esc(doc.filename)}</a> · ${doc.status==='processing'?'正在识别':doc.status==='error'?'识别失败':'无税表识别结果'}</li>`).join('')}</ul></details>`;
        for(const button of panel.querySelectorAll('[data-form-review]')){
            button.onclick=async()=>{
                const form=forms[Number(button.dataset.formReview)];
                reviewSelection={client:client.id,document:form.documentId,page:form.firstPage};
                const preview=$('#document-review');
                preview.hidden=false;
                await loadDocumentReview(data);
                if(preview.isConnected)preview.scrollIntoView({block:'nearest'});
            };
        }
    }catch(error){if(panel.isConnected)panel.textContent=error.message}
}

async function loadDocumentReview(workspace=null){
    const panel=$('#document-review'),clientId=current.id,request=++reviewRequest;
    panel.textContent='正在读取资料…';
    try{
        const data=workspace||await api('/api/workspace?client_id='+clientId);
        if(!panel.isConnected||request!==reviewRequest)return;
        if(!data.documents.length){
            panel.textContent='暂无导入资料。请在「文件与路径」中扫描文件夹。';
            return;
        }
        if(reviewSelection.client!==clientId)reviewSelection={client:clientId};
        panel.innerHTML='<div class="bar"><label>文件 <select id="review-document"></select></label><label>原件页 <select id="review-page"></select></label></div><div class="review-grid"><div id="review-values"></div><figure id="review-original" class="review-preview"></figure></div>';
        const documents=panel.querySelector('#review-document'),pages=panel.querySelector('#review-page');
        const values=panel.querySelector('#review-values'),original=panel.querySelector('#review-original');
        const recordsByPage=new Map();
        for(const record of data.records){
            if(!recordsByPage.has(record.page_id))recordsByPage.set(record.page_id,[]);
            recordsByPage.get(record.page_id).push(record);
        }
        const pageTypes=page=>[...new Set([page.schedule,...(recordsByPage.get(page.id)||[]).map(r=>r.form_type==='1040-reference'?'Form 1040':r.form_type)].filter(Boolean))];
        for(const doc of data.documents){
            const types=[...new Set(data.pages.filter(p=>p.document_id===doc.id).flatMap(pageTypes))];
            documents.add(new Option(doc.filename+(types.length?' · '+types.join(' / '):''),doc.id));
        }
        const hasAmounts=record=>Object.values(record.values||{}).some(value=>value!=null&&value!=='');
        const eligible=data.records.filter(r=>r.status!=='excluded'&&r.disposition!=='excluded'&&hasAmounts(r));
        const preferred=eligible.find(r=>r.form_type==='W-2')||eligible[0];
        if(data.documents.some(d=>d.id===reviewSelection.document)){
            documents.value=reviewSelection.document;
        }else if(preferred){
            documents.value=preferred.document_id;
            reviewSelection.page=preferred.page_id;
        }

        function showPage(){
            const page=data.pages.find(p=>p.id===Number(pages.value));
            const doc=data.documents.find(d=>d.id===Number(documents.value));
            reviewSelection={client:clientId,document:doc.id,page:page?.id};
            if(!page){
                values.textContent=doc.status==='processing'?'正在识别此文件，请稍后刷新。':'此文件尚无可核对的页面。';
                original.innerHTML=`<a href="/api/crm/document?client_id=${clientId}&document_id=${doc.id}" target="_blank" rel="noopener">打开原文件</a>`;
                return;
            }
            const records=recordsByPage.get(page.id)||[];
            const types=pageTypes(page);
            values.innerHTML=`<h3>${esc(types.join(' / ')||'未识别表格')} · 第 ${page.page_number} 页</h3>`+
                (records.length?records.map(record=>{
                    const fields=config.fields[record.form_type]||[];
                    const status=record.disposition==='excluded'?'页面已排除':({reviewed:'已核对',pending:'待核对',excluded:'已排除'}[record.status]||'待核对');
                    return `<h4>${esc(record.form_type==='1040-reference'?'Form 1040':record.form_type)} · ${status}</h4><table class="review-fields"><thead><tr><th>字段</th><th>金额</th></tr></thead><tbody>${fields.map(([key,label])=>`<tr><td>${esc(label)}</td><td>${esc(record.values?.[key]??'未提取')}</td></tr>`).join('')}</tbody></table>`;
                }).join(''):`<p class="muted">${page.schedule?'已识别附表标题，金额请对照原页。':'此页暂无结构化金额。'}</p>`);
            const url='/api/pages/'+page.id+'/image';
            original.innerHTML=`<figcaption><a href="${url}" target="_blank" rel="noopener">查看大图 · 第 ${page.page_number} 页</a></figcaption><img src="${url}" alt="原文件第 ${page.page_number} 页">`;
        }
        function showDocument(){
            const docPages=data.pages.filter(p=>p.document_id===Number(documents.value));
            pages.replaceChildren();
            for(const page of docPages)pages.add(new Option('第 '+page.page_number+' 页'+(pageTypes(page).length?' · '+pageTypes(page).join(' / '):''),page.id));
            const selected=docPages.find(p=>p.id===reviewSelection.page)||docPages.find(p=>pageTypes(p).length)||docPages[0];
            if(selected)pages.value=selected.id;
            pages.disabled=!selected;
            showPage();
        }
        documents.onchange=showDocument;
        pages.onchange=showPage;
        showDocument();
    }catch(error){if(panel.isConnected&&request===reviewRequest)panel.textContent=error.message}
}

function docUrl(id){return `/api/crm/document?client_id=${current.id}&document_id=${id}`}
function linkItem(l){return `${esc(l.label)} · ${esc({source:'原始资料',return:'税表',proseries:'ProSeries'}[l.kind])}${l.document_id?` · <a target="_blank" rel="noopener" href="${docUrl(l.document_id)}${l.page_number?'#page='+l.page_number:''}">打开 PDF${l.page_number?' 第 '+l.page_number+' 页':''}</a>`:''}${l.path?`<br><span class="path">${esc(l.path)}</span>`:''}`}
function linksHtml(){return current.links.map(l=>`<div class="row">${linkItem(l)}</div>`).join('')}
async function openClient(id){if(!canLeave())return;const value=await api('/api/crm?id='+id);current=value;edited=false;$('#overview').classList.add('hidden');$('#detail').classList.remove('hidden');history.replaceState(null,'','/?id='+id+'&tab='+encodeURIComponent(tab));renderDetail()}
async function save(e){e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{await api('/api/crm/save',{client_id:current.id,revision:current.revision,contact_revision:current.contact_revision,...Object.fromEntries(new FormData(e.target))});edited=false;current=await api('/api/crm?id='+current.id);renderDetail();message('已保存')}catch(x){message(x.message);button.disabled=false}}
function showLink(){const f=$('#link-form');f.reset();f.elements.intake_id.innerHTML='<option value="">不关联资料项目</option>'+current.intake.map(i=>`<option value="${i.id}">${esc(i.label)}</option>`).join('');f.elements.document_id.innerHTML='<option value="">仅登记外部路径</option>'+current.documents.map(d=>`<option value="${d.id}">${esc(d.filename)}</option>`).join('');$('#link-dialog').showModal()}
$('#link-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/crm/link',{client_id:current.id,...Object.fromEntries(new FormData(e.target))});$('#link-dialog').close();current=await api('/api/crm?id='+current.id);renderDetail();message('文件关联已保存')}catch(x){message(x.message)}};
function createDialog(person=null){creatingPerson=person;$('#create-form').reset();$('#name-field').classList.toggle('hidden',!!person);$('#create-form').elements.name.required=false;$('#folder-field').classList.toggle('hidden',!!person);$('#create-progress').textContent='';$('#folder-preview').innerHTML='';$('#preview-folder').classList.toggle('hidden',!!person);$('#create-title').textContent=person?'为此客户新增年度':'新建客户与年度工作区';if(person)$('#create-form').elements.tax_year.value=current.tax_year+1;$('#create-dialog').showModal()}
function bindFolderPreview(input, output, button, initial=false){
    let version=0, timer, lastPath='';
    async function read(){
        const path=input.value.trim(), request=++version;
        lastPath=path;
        if(!path){output.textContent='请填写资料文件夹路径';return}
        output.textContent='正在读取文件清单…';
        try{
            const result=await api('/api/crm/preview-folder',{source_path:path});
            if(request!==version||!output.isConnected)return;
            output.innerHTML=result.files.length
                ? '<p>发现 '+result.files.length+' 份资料</p><ul>'+result.files.map(file=>`<li>${esc(file.name)} · ${esc(file.type)}</li>`).join('')+'</ul>'
                : '<p>当前文件夹没有找到可读取的 PDF 或图片。</p>';
        }catch(error){if(request===version&&output.isConnected)output.textContent=error.message}
    }
    function schedule(){clearTimeout(timer);++version;timer=setTimeout(read,450)}
    input.oninput=schedule;
    input.onchange=()=>{if(input.value.trim()!==lastPath)schedule()};
    button.onclick=()=>{clearTimeout(timer);read()};
    if(initial&&input.value.trim())read();
}
bindFolderPreview($('#create-source-path'),$('#folder-preview'),$('#preview-folder'));
$('#new').onclick=()=>createDialog();$('#add-year').onclick=()=>createDialog(current.contact_id);
$('#create-form').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');const values=Object.fromEntries(new FormData(e.target));if(!creatingPerson&&!values.name.trim()&&!values.source_path.trim()){message('客户姓名和资料文件夹路径至少填写一项');return}b.disabled=true;$('#create-progress').textContent=!values.name.trim()&&values.source_path.trim()?'正在本机读取资料姓名，请稍候…':'正在创建…';try{const r=await api('/api/crm/create',{...Object.fromEntries(new FormData(e.target)),contact_id:creatingPerson});$('#create-dialog').close();tab='表格与核对';await openClient(r.id);message(r.existing?'该文件夹已建档，已打开现有客户':'客户已创建'+(r.name?'：'+r.name:''))}catch(x){$('#create-progress').textContent=x.message;message(x.message)}finally{b.disabled=false}};
async function home(){if(!canLeave())return;edited=false;current=null;history.replaceState(null,'','/');$('#detail').classList.add('hidden');$('#overview').classList.remove('hidden');await load()}
$('#home').onclick=$('#back').onclick=()=>home().catch(e=>message(e.message));$('#reload').onclick=()=>load().catch(e=>message(e.message));$('#search').oninput=$('#year').onchange=$('#stage').onchange=render;
$('#logout').onclick=async()=>{if(!canLeave())return;try{await api('/api/logout',{});edited=false;location.replace('/login')}catch(e){message(e.message)}};
async function showAssignees(){try{const people=await api('/api/crm/assignees');assigneeNames=people.map(x=>x.name);$('#assignees-list').innerHTML=people.map(x=>`<div>${esc(x.name)}</div>`).join('')||'<p>尚未添加负责人</p>';$('#assignees-dialog').showModal()}catch(e){message(e.message)}}
$('#manage-assignees').onclick=showAssignees;$('#assignee-form').onsubmit=async e=>{e.preventDefault();try{const person=await api('/api/crm/assignees',Object.fromEntries(new FormData(e.target)));assigneeNames=(await api('/api/crm/assignees')).map(x=>x.name);const select=$('#f-assignee');if(select){const option=document.createElement('option');option.value=person.name;option.textContent=person.name;if(![...select.options].some(x=>x.value===person.name))select.add(option);select.value=person.name;edited=true}e.target.reset();$('#assignees-dialog').close();message('已添加负责人'+(select?'并选中，请保存概况':'，可在客户概况中选择'))}catch(x){message(x.message)}};
let deletionPreview=null;
async function previewDeletion(){deletionPreview=null;$('#delete-confirm').disabled=true;$('#delete-name').value='';try{deletionPreview=await api('/api/crm/delete-preview?id='+current.id+'&scope='+$('#delete-scope').value);$('#delete-impact').textContent=deletionPreview.alias+' · 税年 '+deletionPreview.years.join('、')+' · '+deletionPreview.document_count+' 份上传文件。'+(deletionPreview.busy?'正在识别，暂不能删除。':'');$('#delete-confirm').disabled=deletionPreview.busy}catch(e){$('#delete-impact').textContent=e.message}}
$('#delete-client').onclick=async()=>{if(!canLeave())return;$('#delete-scope').value='year';$('#delete-dialog').showModal();await previewDeletion()};$('#delete-scope').onchange=previewDeletion;
$('#delete-form').onsubmit=async e=>{e.preventDefault();if(!deletionPreview)return;$('#delete-confirm').disabled=true;try{await api('/api/crm/delete',{...deletionPreview,confirmed_name:$('#delete-name').value});$('#delete-dialog').close();edited=false;await home();message('已移入回收站，可以恢复')}catch(x){message(x.message);$('#delete-confirm').disabled=false}};
async function showTrash(){try{const items=await api('/api/crm/trash');$('#trash-list').innerHTML=items.map(x=>`<div class="row"><strong>${esc(x.name)}</strong><p>税年 ${esc(x.years.join('、'))} · ${esc(x.actor)} · ${esc(new Date(x.deleted_at).toLocaleString())}</p><button data-restore="${esc(x.batch)}">恢复</button></div>`).join('')||'<p class="empty">回收站为空</p>';document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await api('/api/crm/restore',{batch:b.dataset.restore});await showTrash();await load();message('已恢复客户资料')}catch(e){message(e.message);b.disabled=false}});$('#trash-dialog').showModal()}catch(e){message(e.message)}}
$('#trash-open').onclick=showTrash;
$('#password').onclick=()=>$('#password-dialog').showModal();$('#password-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/password',Object.fromEntries(new FormData(e.target)));edited=false;location.replace('/login')}catch(x){message(x.message)}};
setInterval(async()=>{if(!current||edited||!['文件与路径','表格与核对','资料清单'].includes(tab))return;if(!['queued','running'].includes(current.folder_job?.status)&&!current.documents.some(d=>d.status==='processing'))return;try{const fresh=await api('/api/crm?id='+current.id);if(edited||!current||fresh.id!==current.id)return;current=fresh;renderDetail()}catch{}},5000);
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());window.onbeforeunload=e=>{if(edited){e.preventDefault();e.returnValue=''}};
(async()=>{try{config=await api('/api/config');assigneeNames=(await api('/api/crm/assignees')).map(x=>x.name);$('#account').textContent=config.user.username+' · '+({admin:'管理员',editor:'编辑员工',viewer:'只读员工'}[config.user.role]);$('#admin').classList.toggle('hidden',config.user.role!=='admin');$('#stage').innerHTML+='<option>'+stages.join('</option><option>')+'</option>';await load();const p=new URLSearchParams(location.search);if(p.get('id')){tab=['概况','资料清单','文件与路径','表格与核对','收费记录','操作历史'].includes(p.get('tab'))?p.get('tab'):'表格与核对';if(p.get('document_id'))reviewSelection={client:Number(p.get('id')),document:Number(p.get('document_id'))};await openClient(Number(p.get('id')))}permit()}catch(e){message(e.message)}})();
