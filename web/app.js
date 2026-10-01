const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function storedProfile(){try{return localStorage.getItem('domovoy-profile')}catch{return null}}
function rememberProfile(value){try{localStorage.setItem('domovoy-profile',value)}catch{}}
let profile = storedProfile() || 'anna';
if (!['anna','boris','manager','dispatcher'].includes(profile)) profile='anna';
let selected=null, tab='home', data=null, modalAction=null, toastTimer, modalAfterSave=null, modalBusy=false, detail=null, detailVersion=0;
let ticketFilter='all', ticketSearch='', queue=null, queueFilter='all', queueSearch='';
const residentCount = n => `${n} ${n%10===1&&n%100!==11?'житель':n%10>=2&&n%10<=4&&(n%100<12||n%100>14)?'жителя':'жителей'}`;
let appMode='demo', initData='', stateVersion=0, polling=false;
const drafts=new Map();
const draftKey=()=>`${profile}:${selected}`;
function saveDraft(){const input=$('#chatForm input');if(input)drafts.set(draftKey(),input.value)}
const manager=()=>data?.profile.role==='manager';
const categories={light:'Освещение',water:'Вода и отопление',clean:'Уборка',lift:'Лифт',door:'Двери и домофон',other:'Другое'};
const dateLabel=value=>{const d=new Date(value.replace(' ','T')+'Z');return Number.isNaN(d.getTime())?'':new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(d)};
const statuses={new:'Новая',work:'В работе',done:'Ждёт подтверждения',confirmed:'Решена'};
let incidentData=null,incidentFilter='active',incidentSearch='';
const titles={incidents:'Приватные обращения',home:'Мой подъезд',chat:'Соседи',tickets:'Заявки по дому',manage:'Управление домами',detail:'Заявка по дому',queue:'Очередь УК',notices:'Объявления дома',outages:'Аварии и отключения'};
const initials = id => name(id).slice(0,1);
const name = id => data?.profiles.find(p=>p.id===id)?.label || ({anna:'Анна',boris:'Борис',manager:'Мария · УК'}[id]||'Сосед');
function toast(text){$('#toast').textContent=text;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),4500)}
const requestClient=createDomovoyClient();
async function api(path,body){
 return requestClient(path,{body,identity:`${appMode}:${profile}`,headers:appMode==='demo'?{'X-Demo-Profile':profile}:{'X-Max-Init-Data':initData}});
}

async function refresh(){
 const version=++stateVersion;
 const result=await api('/api/state'+(selected?`?entrance_id=${selected}`:''));if(version!==stateVersion)return;data=result;profile=data.profile.id;selected=data.selected;if(tab==='incidents'){const privateResult=await api('/api/incidents');if(version!==stateVersion)return;incidentData=privateResult;}document.body.classList.remove("auth-pending");render();
}
function entrance(){return data.entrances.find(e=>e.id===selected)}
function buttons(){
 $('#incidentsNav').hidden=!data.training_incidents;$('#incidentsNav').textContent=data.dispatcher?'Учебный кабинет диспетчера':'Приватные обращения · учебный режим';
 $('#manageNav').hidden=!manager();$('#join').hidden=manager();
 $('#profile').hidden=appMode!=='demo';$('.profile-label').hidden=appMode!=='demo';
 $('#profile').value=profile;$('#profileHint').textContent=initials(profile);$('#profileHint').title=name(profile);
 $('#heading').textContent=titles[tab];$('#eyebrow').textContent=data.dispatcher?'УЧЕБНЫЙ КАБИНЕТ ДИСПЕТЧЕРА':manager()?'КАБИНЕТ УПРАВЛЯЮЩЕЙ КОМПАНИИ':'ВАШЕ МЕСТО В ГОРОДЕ';
 document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===(tab==='detail'?'tickets':tab==='queue'?'manage':['notices','outages'].includes(tab)?'home':tab)));
 $('#entrance').innerHTML=data.entrances.map(e=>`<option value="${e.id}" ${e.id===selected?'selected':''}>${esc(e.address)} · Подъезд ${e.number}</option>`).join('');
}
function statusButtons(t){
 let actions='';
 if(manager()&&['new','work'].includes(t.status))actions=`<button class="button light" data-status="${t.status==='new'?'work':'done'}" data-id="${t.id}">${t.status==='new'?'Взять в работу':'Отметить выполненной'}</button>`;
 if(t.author===profile&&t.status==='done')actions=`<button class="button primary" data-status="confirmed" data-id="${t.id}">Всё исправлено</button><button class="button light" data-status="work" data-reopen="true" data-id="${t.id}">Проблема осталась</button>`;
 return actions;
}
function ticketCard(t){
 const actions=statusButtons(t);
 return `<article class="card ticket-card"><div class="ticket"><span class="card-meta">ЗАЯВКА № ${String(t.id).padStart(3,'0')} · ${esc(categories[t.category]||categories.other)}</span><span class="status ${esc(t.status)}">${statuses[t.status]}</span></div><h3><button class="ticket-title" data-detail="${t.id}">${esc(t.title)}</button></h3><p>${esc(name(t.author))} · ${esc(dateLabel(t.created))}</p><div class="ticket-actions"><button class="text-button" data-detail="${t.id}">История и комментарии ↗</button>${actions}</div></article>`;
}
function ticketMatches(t){
 const match=ticketFilter==='all'||(ticketFilter==='mine'?t.author===profile:ticketFilter==='active'?['new','work'].includes(t.status):t.status===ticketFilter);
 return match&&`${t.id} ${t.title} ${t.details||''} ${categories[t.category]||''}`.toLocaleLowerCase('ru').includes(ticketSearch.toLocaleLowerCase('ru').trim());
}
function renderTicketList(){
 const filtered=data.tickets.filter(ticketMatches);
 $('#ticketList').innerHTML=filtered.map(ticketCard).join('')||'<div class="empty"><h3>Таких заявок пока нет</h3><p>Выберите другой фильтр или создайте новую заявку.</p></div>';
 $('#ticketCount').textContent=`Найдено: ${filtered.length}${data.stats.total>data.tickets.length?' · поиск среди последних 50 заявок':''}`;
 document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('active',b.dataset.filter===ticketFilter);b.setAttribute('aria-pressed',String(b.dataset.filter===ticketFilter))});
}
async function openTicket(id){
 const version=++detailVersion,who=profile,eid=selected,entering=tab!=='detail'||detail?.ticket.id!==id;
 const result=await api(`/api/ticket?id=${id}`);
 if(version!==detailVersion||who!==profile||eid!==selected)return;
 detail=result;tab='detail';render();if(entering)window.scrollTo(0,0);
}
async function openQueue(){
 const who=profile,version=++detailVersion;
 const result=await api('/api/queue');
 if(who!==profile||version!==detailVersion)return;
 queue=result;tab='queue';render();window.scrollTo(0,0);
}
function renderQueueList(){
 const people=new Map(queue.profiles.map(p=>[p.id,p.label]));
 const tickets=queue.tickets.filter(t=>(queueFilter==='all'||t.status===queueFilter)&&`${t.id} ${t.title} ${t.address} ${t.number}`.toLowerCase().includes(queueSearch.trim().toLowerCase()));
 $('#queueList').innerHTML=tickets.map(t=>`<article class="card queue-card"><div class="ticket"><span class="card-meta">№ ${t.id} · ${esc(categories[t.category]||categories.other)}</span><span class="status ${esc(t.status)}">${statuses[t.status]}</span></div><h3><button class="ticket-title" data-queue-ticket="${t.id}" data-eid="${t.entrance_id}">${esc(t.title)}</button></h3><p>${esc(t.address)} · Подъезд ${t.number}</p><p>${esc(people.get(t.author)||'Житель')} · ${esc(dateLabel(t.created))}</p><button class="text-button queue-open" data-queue-ticket="${t.id}" data-eid="${t.entrance_id}">Открыть обращение ↗</button></article>`).join('')||'<div class="empty"><h3>Всё спокойно</h3><p>Нет обращений с выбранными условиями.</p></div>';
 $('#queueCount').textContent=`Показано: ${tickets.length} · очередь содержит до 100 незакрытых заявок, новые — в начале`;
 document.querySelectorAll('[data-qfilter]').forEach(b=>{b.classList.toggle('active',b.dataset.qfilter===queueFilter);b.setAttribute('aria-pressed',String(b.dataset.qfilter===queueFilter))});
}
function renderQueue(){
 $('#content').innerHTML=`<div class="section-head"><h2>Все дома · одна очередь</h2><button class="button light" data-action="queue">Обновить</button></div><div class="queue-metrics">${[['new','Новых'],['work','В работе'],['done','Ждут жителя'],['confirmed','Решено']].map(([key,label])=>`<div><strong>${queue.counts[key]||0}</strong><span>${label}</span></div>`).join('')}</div><div class="ticket-tools"><label class="search-field"><span aria-hidden="true">⌕</span><input id="queueSearch" type="search" aria-label="Поиск по всем домам" placeholder="Номер заявки, адрес или проблема…" value="${esc(queueSearch)}"></label><div class="filter-row">${[['all','Все незакрытые'],['new','Новые'],['work','В работе'],['done','Ждут подтверждения']].map(([key,label])=>`<button class="filter-chip" data-qfilter="${key}" aria-pressed="false">${label}</button>`).join('')}</div><p class="list-count" id="queueCount" role="status"></p></div><div id="queueList"></div>`;
 renderQueueList();$('#queueSearch').addEventListener('input',ev=>{queueSearch=ev.target.value;renderQueueList()});
}
function renderDetail(){
 const t=detail.ticket, people=new Map(detail.profiles.map(p=>[p.id,p.label]));
 const eventText=e=>e.kind==='created'?'Создана заявка':e.kind==='comment'?'Комментарий':e.kind==='outage'?'Связь с общей аварией':`Статус: ${statuses[e.status]||e.status}`;
 const events=detail.events.length?detail.events.map(e=>`<li class="timeline-event ${e.kind==='comment'?'comment-event':''}"><span class="timeline-dot"></span><div><div class="event-top"><strong>${esc(eventText(e))}</strong><time>${esc(dateLabel(e.created))}</time></div><small>${esc(people.get(e.author)||'Житель')}</small>${e.text?`<p>${esc(e.text)}</p>`:''}</div></li>`).join(''):'<li class="empty">История начнётся со следующего изменения заявки.</li>';
 $('#content').innerHTML=`<button class="text-button back-button" data-action="back-tickets">← К списку заявок</button><article class="card detail-card"><div class="ticket"><span class="tag">${esc(categories[t.category]||categories.other)}</span><span class="status ${esc(t.status)}">${statuses[t.status]}</span></div><h2>${esc(t.title)}</h2><p class="detail-meta">№ ${t.id} · ${esc(people.get(t.author)||'Житель')} · ${esc(dateLabel(t.created))}</p>${t.details?`<p class="description">${esc(t.details)}</p>`:''}<div class="ticket-actions">${statusButtons(t)}${t.status!=='confirmed'&&(manager()||t.author===profile)?`<button class="button light" data-link-outage="${t.id}">${t.outage_id?'Изменить связь с аварией':'Связать с аварией'}</button>`:''}</div></article>${linkedOutageCard(detail.outage)}<div class="section-head"><h2>Как решается вопрос</h2><button class="text-button" data-detail="${t.id}">Обновить</button></div><ol class="timeline">${events}</ol><section class="card"><h3>Добавить комментарий</h3><p>Уточните проблему или расскажите о результате. Комментарий видят участники подъезда и УК.</p><form id="commentForm"><label class="sr-only" for="commentText">Комментарий к заявке</label><textarea id="commentText" name="text" placeholder="Например, свет всё ещё не горит на третьем этаже" maxlength="1500" required></textarea><button class="button primary" type="submit">Отправить комментарий</button></form></section>`;
 const key=`comment:${profile}:${t.id}`,f=$('#commentForm');f.elements.text.value=drafts.get(key)||'';f.elements.text.addEventListener('input',()=>drafts.set(key,f.elements.text.value));
 f.addEventListener('submit',async ev=>{ev.preventDefault();const button=f.querySelector('button'),text=f.elements.text.value,who=profile;button.disabled=true;try{await api('/api/ticket/comment',{entrance_id:t.entrance_id,id:t.id,text});if(drafts.get(key)===text)drafts.delete(key);if(f.elements.text.value===text)f.elements.text.value='';await updateViewAfterSave(async()=>{if(who===profile&&tab==='detail'&&detail.ticket.id===t.id)await openTicket(t.id)},'Комментарий добавлен')}catch(err){toast(err.message)}finally{button.disabled=false}});
}
const outageServices={water:'Вода',power:'Электричество',heating:'Отопление',other:'Другое'};
const outageStatuses={reported:'Сообщение опубликовано',work:'Идут работы',restored:'Восстановлено'};
function outageCard(o){
 return `<article class="card outage-card ${o.status==='restored'?'resolved':''}"><div class="ticket"><span class="tag">${esc(outageServices[o.service])}</span><span class="status ${o.status==='restored'?'confirmed':'work'}">${esc(outageStatuses[o.status])}</span></div><h3>${esc(o.title)}</h3><p>${esc(o.reason)}</p>${o.history[0]?.note!==o.reason?`<p class="outage-latest"><strong>Последнее обновление:</strong> ${esc(o.history[0]?.note)}</p>`:''}${o.status!=='restored'?`<div class="outage-forecast"><small>Ориентировочное восстановление · не гарантия</small><strong>${esc(o.forecast||'Срок уточняется')}</strong></div>`:''}<p class="outage-source">${esc(o.source)} · обновлено ${esc(dateLabel(o.updated))}</p><p>${o.houses.map(h=>esc(h.address)).join(' · ')}</p><details class="outage-history"><summary>История обновлений</summary>${o.history.map(h=>`<div><strong>${esc(outageStatuses[h.status])}</strong><time>${esc(dateLabel(h.created))}</time><p>${esc(h.note)}</p>${h.forecast?`<p>Прогноз на момент обновления: ${esc(h.forecast)}</p>`:''}</div>`).join('')}</details>${manager()&&o.status!=='restored'?`<button class="button light" data-outage-update="${o.id}">Обновить статус и срок</button>`:''}</article>`;
}
function newOutage(){
 const houses=[...new Map(data.entrances.map(e=>[e.house_id,e])).values()];
 modal('Сообщить об отключении',`<p class="modal-note">Сведения публикуются от УК в Домовом. ${data.demo?'В локальном демо уведомления в MAX не отправляются.':'Для участников выбранных домов будет поставлено уведомление в очередь бота.'}</p><label class="modal-field">Услуга<select name="service">${Object.entries(outageServices).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label>`+input('Заголовок','title','Например, отключение холодной воды',120)+textarea('Причина или что известно сейчас','reason','Если причина неизвестна, укажите, что она уточняется.')+'<label class="modal-field">Прогноз восстановления · необязательно<input name="forecast" maxlength="120" placeholder="Например, сегодня к 18:00"></label><fieldset class="house-choices"><legend>Затронутые дома</legend>'+houses.map(h=>`<label><input type="checkbox" name="house_ids" value="${h.house_id}" ${h.house_id===entrance()?.house_id?'checked':''}>${esc(h.address)}</label>`).join('')+'</fieldset>',form=>api('/api/outages',{title:form.get('title'),reason:form.get('reason'),service:form.get('service'),forecast:form.get('forecast'),house_ids:form.getAll('house_ids').map(Number)}),'Опубликовать');
}
function updateOutage(id){
 const o=data.outages.find(o=>o.id===id);if(!o)return;
 const options=o.status==='reported'?['reported','work','restored']:['work','restored'];
 modal('Обновление аварии',`<label class="modal-field">Статус<select name="status">${options.map(k=>`<option value="${k}" ${k===o.status?'selected':''}>${outageStatuses[k]}</option>`).join('')}</select></label>`+textarea('Что изменилось','note','Например, бригада приступила к замене участка трубы')+`<label class="modal-field">Новый прогноз восстановления<input name="forecast" maxlength="120" value="${esc(o.forecast)}" placeholder="Оставьте пустым, если срок уточняется"></label><p class="modal-note">При восстановлении прогноз снимается. История сохранится, жители получат новое сообщение.</p>`,form=>api('/api/outages/update',{id:o.id,version:o.version,...Object.fromEntries(form)}),'Сохранить обновление');
}
function noticeCard(n){
 const read=manager()?`<span class="read-note">Ознакомились ${n.read_count} из ${data.members.length} жителей</span>`:n.acknowledged?'<span class="read-note acknowledged">✓ Вы ознакомились</span>':`<button class="text-button" data-read="${n.id}">✓ Я ознакомился</button>`;
 return `<article class="card"><div class="card-meta"><span class="tag">Объявление УК</span><time>${esc(dateLabel(n.created))}</time></div><h3>${esc(n.title)}</h3><p>${esc(n.text)}</p><div class="notice-bottom">${read}</div></article>`;
}
function messageList(){return data.messages.map(m=>`<article class="bubble ${m.author===profile?'mine':''}"><strong>${esc(name(m.author))}</strong><p>${esc(m.text)}</p><time>${esc(dateLabel(m.created))}</time></article>`).join('')||'<div class="empty">Начните знакомство с соседями</div>'}
function render(){
 buttons();const e=entrance(), content=$('#content');
 if(tab==='incidents'){renderIncidents();return}
 if(tab==='queue'&&queue){renderQueue();return}
 if(tab==='detail'&&detail){renderDetail();return}
 if(!e&&tab!=='manage'){content.innerHTML=manager()?'<div class="empty">Добавьте первый дом в разделе «Управление».</div>':'<div class="empty">Пока нет доступных подъездов. Присоединитесь по приглашению УК.</div>';return}
 if(tab==='home'){
  const open=data.stats.open;
  content.innerHTML=`<section class="hero"><div class="hero-copy"><span class="pill">● ВАШ ДОМ НА СВЯЗИ</span><h2>Привет, ${esc(data.profile.name)}.</h2><p>Все вопросы вашего подъезда —<br>в одном уютном месте.</p></div><div class="buildings" aria-hidden="true"><div class="building">${'<i></i>'.repeat(12)}</div><div class="building">${'<i></i>'.repeat(18)}</div></div></section>
  <button class="outage-banner" data-action="outages"><span><strong>${data.outages.filter(o=>o.status!=='restored').length?'Есть сообщения об отключениях':'Вода, свет и отопление'}</strong><small>${data.outages.filter(o=>o.status!=='restored').length?'Причины, прогноз восстановления и обновления УК':'Посмотреть сведения об авариях вашего дома'}</small></span><span aria-hidden="true">↗</span></button><div class="metrics"><div class="metric"><span class="metric-icon">◌</span><div><strong>${data.members.length}</strong><small>жителей в подъезде</small></div></div><div class="metric"><span class="metric-icon">▤</span><div><strong>${open}</strong><small>открытых заявок</small></div></div><div class="metric"><span class="metric-icon">◎</span><div><strong>${data.notices.length}</strong><small>объявлений от УК</small></div></div></div>
  <div class="columns"><section><div class="section-head"><h2>Важно для подъезда</h2><button class="text-button" data-action="notices">Все ↗</button>${manager()?'<button class="text-button" data-action="notice">＋ Добавить</button>':''}</div>${data.notices.slice(0,3).map(noticeCard).join('')||'<div class="empty">Здесь появятся объявления вашей УК</div>'}</section>
  <section><div class="section-head"><h2>Рядом с вами</h2></div><article class="card community-card"><div class="avatars">${data.members.slice(0,8).map(p=>`<span class="small-avatar" title="${esc(p.name)}">${esc(initials(p.id))}</span>`).join('')||'<span class="small-avatar">＋</span>'}${data.members.length>8?`<span class="small-avatar" title="Ещё ${data.members.length-8} жителей">+${data.members.length-8}</span>`:''}</div><h3>Подъезд ${e.number} · свои люди</h3><p>Познакомьтесь с соседями, задайте вопрос или обсудите общие дела.</p><button class="button" data-action="chat">Открыть обсуждение ↗</button></article><div class="section-head"><h2>Заявки</h2><button class="text-button" data-action="ticket">＋ Создать</button></div>${data.tickets.slice(0,1).map(ticketCard).join('')||'<div class="empty">В подъезде пока нет заявок</div>'}</section></div>`;
 }else if(tab==='outages'){
  content.innerHTML=`<div class="section-head"><h2>Ваш дом · ${esc(e.address)}</h2><button class="button light" data-action="outages-refresh">Обновить</button></div>${manager()?'<button class="button primary" data-action="outage-new">＋ Сообщить об отключении</button>':''}<p class="modal-note">Сведения публикует УК. Прогноз может измениться — проверяйте время обновления. Показаны последние 30 карточек.</p>${data.outages.map(outageCard).join('')||'<div class="empty"><h3>Активных сообщений пока нет</h3><p>Это не подтверждение отсутствия аварии. Если у вас возникла проблема, оставьте заявку.</p><button class="button primary" data-action="ticket">Сообщить о проблеме</button></div>'}`;
 }else if(tab==='notices'){
  content.innerHTML=`<div class="section-head"><h2>Подъезд ${e.number}</h2>${manager()?'<button class="button primary" data-action="notice">＋ Объявление</button>':''}</div><p class="modal-note">Важные сообщения от вашей УК. Здесь показаны последние 30 объявлений.</p>${data.notices.map(noticeCard).join('')||'<div class="empty">Объявлений пока нет.</div>'}`;
 }else if(tab==='chat'){
  content.innerHTML=`<section class="chat-wrap"><div class="chat-heading"><strong>Подъезд ${e.number} · обсуждение</strong><small>${residentCount(data.members.length)} · сообщения видят участники подъезда и УК</small><small id="syncStatus" role="status">Обновляется автоматически каждые 5 секунд</small></div><div class="messages">${messageList()}</div><form class="chat-form" id="chatForm"><input name="text" aria-label="Сообщение соседям" placeholder="Написать соседям…" maxlength="1000" required autocomplete="off"><button class="button primary" type="submit" aria-label="Отправить сообщение">Отправить ↑</button></form></section>`;
  const messages=$('.messages');messages.scrollTop=messages.scrollHeight;
  $('#chatForm input').value=drafts.get(draftKey())||'';
  $('#chatForm input').addEventListener('input',saveDraft);
  $('#chatForm').addEventListener('submit',async ev=>{ev.preventDefault();const f=ev.currentTarget,b=f.querySelector('button');b.disabled=true;try{const key=draftKey(),eid=selected,text=f.elements.text.value;await api('/api/messages',{entrance_id:eid,text});if(drafts.get(key)===text)drafts.delete(key);if(f.elements.text.value===text)f.elements.text.value='';await updateViewAfterSave(async()=>{if(key===draftKey())await refresh()},'Сообщение отправлено');b.disabled=false}catch(err){toast(err.message);b.disabled=false}});
 }else if(tab==='tickets'){
  content.innerHTML=`<div class="section-head"><h2>Подъезд ${e.number}</h2><button class="button primary" data-action="ticket">＋ Новая заявка</button></div><div class="ticket-tools"><label class="search-field"><span aria-hidden="true">⌕</span><input id="ticketSearch" type="search" aria-label="Поиск заявки" placeholder="Номер, проблема или категория…" value="${esc(ticketSearch)}"></label><div class="filter-row" aria-label="Фильтры заявок">${[['all','Все'],['active','В работе и новые'],['done','Ждут подтверждения'],['confirmed','Решены'],['mine','Мои']].map(([key,label])=>`<button class="filter-chip" data-filter="${key}" aria-pressed="false">${label}</button>`).join('')}</div><p id="ticketCount" class="list-count" role="status"></p></div><div id="ticketList"></div>`;
  renderTicketList();$('#ticketSearch').addEventListener('input',ev=>{ticketSearch=ev.target.value;renderTicketList()});
 }else{
  const houses=new Map();data.entrances.forEach(e=>{if(!houses.has(e.house_id))houses.set(e.house_id,{name:e.name,address:e.address,entrances:[]});houses.get(e.house_id).entrances.push(e)});
  content.innerHTML=`<div class="section-head"><h2>Дома под управлением · ${houses.size}</h2><button class="button primary" data-action="house">＋ Добавить дом</button></div><button class="queue-banner" data-action="queue"><span><strong>Все обращения ваших домов</strong><small>Новые заявки, работы и результаты на проверке</small></span><span aria-hidden="true">↗</span></button><p class="modal-note">Создайте дом, укажите подъезды и передайте жителям код их подъезда. Обсуждение появится автоматически.</p>${[...houses.values()].map(h=>`<section class="manage-house"><h2>${esc(h.name)}</h2><p>${esc(h.address)}</p><div class="entrance-grid">${h.entrances.map(e=>`<article class="card entrance-card"><span class="tag">Отдельное обсуждение</span><h3>Подъезд ${e.number}</h3><p>Код приглашения</p><code class="code">${esc(e.code)}</code><div class="ticket-actions"><button class="button light" data-copy="${esc(e.code)}">Копировать код</button><button class="button light" data-open="${e.id}">Открыть</button><button class="text-button" data-rotate="${e.id}">Заменить код</button></div></article>`).join('')}</div></section>`).join('')}`;
 }
}
function modal(title,fields,action,label='Сохранить',afterSave=null){if(modalBusy)return;$('#modalTitle').textContent=title;$('#modalFields').innerHTML=fields;$('#formError').textContent='';$('#submitModal').textContent=label;$('#submitModal').hidden=!action;modalAction=action;modalAfterSave=afterSave;$('#modal').showModal()}
function input(label,name,placeholder,max=100){return `<label class="modal-field">${label}<input name="${name}" placeholder="${placeholder}" maxlength="${max}" required></label>`}
function textarea(label,name,placeholder,max=1000){return `<label class="modal-field">${label}<textarea name="${name}" placeholder="${placeholder}" maxlength="${max}" required></textarea></label>`}
function outageOptions(current=null){
 const options=data.outages.filter(o=>o.status!=='restored');
 if(current&&detail?.outage?.id===current&&!options.some(o=>o.id===current))options.unshift(detail.outage);
 return `<label class="modal-field">Связать с общей аварией · необязательно<select name="outage_id"><option value="">Без связи с аварией</option>${options.map(o=>`<option value="${o.id}" ${o.id===current?'selected':''}>№${o.id} · ${esc(o.title)}${o.status==='restored'?' · восстановлено, текущая связь':''}</option>`).join('')}</select></label><p class="modal-note">Выберите только аварию, которая относится к вашей проблеме. Сведения вводит УК. Создание заявки не подтверждает причину отключения.</p>`;
}
function linkedOutageCard(o){
 if(!o)return '';
 return `<section class="card outage-card"><span class="tag">Связанная авария № ${o.id}</span><h3>${esc(o.title)}</h3><p><strong>${esc(outageStatuses[o.status])}</strong></p><p>${esc(o.reason)}</p>${o.status!=='restored'?`<div class="outage-forecast"><small>Прогноз · не гарантия</small><strong>${esc(o.forecast||'Срок уточняется')}</strong></div>`:'<p>УК сообщила о восстановлении. Проверьте, решена ли именно ваша проблема: заявка автоматически не закрывается.</p>'}<p>${esc(o.source)} · ${esc(dateLabel(o.updated))}</p><button class="text-button" data-detail="${detail.ticket.id}">Обновить сведения ↻</button></section>`;
}
function linkTicketOutage(){
 const t=detail.ticket;
 modal('Связь заявки с общей аварией',outageOptions(t.outage_id)+'<p class="modal-note">В заявке будут видны причина, прогноз и текущий статус выбранной аварии. Изменение связи сохранится в истории.</p>',form=>api('/api/ticket/outage',{entrance_id:t.entrance_id,id:t.id,outage_id:form.get('outage_id')?Number(form.get('outage_id')):null}),'Сохранить связь',()=>openTicket(t.id));
}
function action(type){
 if(type==='incident-new'){newIncident();return}
 if(type==='incidents-refresh'){refresh().catch(e=>toast(e.message));return}
 if(type==='outage-new'){newOutage();return}
 if(type==='outages'||type==='outages-refresh'){tab='outages';refresh().catch(e=>toast(e.message));return}
 if(type==='queue'){openQueue().catch(e=>toast(e.message));return}
 if(type==='notices'){tab='notices';render();window.scrollTo(0,0);return}
 if(type==='back-tickets'){tab='tickets';render();return}
 if(type==='chat'){tab='chat';render();return}
 if(type==='ticket')modal('Что случилось в подъезде?',`<label class="modal-field">Категория<select name="category">${Object.entries(categories).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label>`+outageOptions()+input('Коротко о проблеме','title','Например, не горит лампа на третьем этаже',300)+'<label class="modal-field">Подробности <span class="optional">· необязательно</span><textarea name="details" placeholder="Где именно и когда заметили проблему?" maxlength="2000"></textarea></label><p class="modal-note">Заявку увидят соседи этого подъезда и УК. При непосредственной опасности звоните 112.</p>',form=>api('/api/tickets',{entrance_id:selected,...Object.fromEntries(form),outage_id:form.get('outage_id')?Number(form.get('outage_id')):null}),'Создать заявку',r=>openTicket(r.ticket_id));
 if(type==='notice')modal('Объявление от УК',`<label class="modal-field">Кому показать<select name="scope"><option value="entrance">Только подъезду ${entrance().number}</option><option value="house">Всем подъездам этого дома</option></select></label>`+input('Заголовок','title','Например, проверка освещения')+textarea('Текст объявления','text','Что важно знать жителям?',1500)+'<p class="modal-note">Объявление появится внутри приложения. Жители смогут отметить, что ознакомились.</p>',form=>api('/api/notices',{entrance_id:selected,...Object.fromEntries(form)}),'Опубликовать');
 if(type==='house')modal('Новый дом',input('Название','name','Например, Соседи у озера',80)+input('Адрес','address','Тестоград, Озёрная улица, 8',160)+'<label class="modal-field">Количество подъездов<input name="count" type="number" min="1" max="20" value="3" required></label><p class="modal-note">Для каждого подъезда появятся своё обсуждение, объявления и код приглашения.</p>',async form=>{const r=await api('/api/houses',Object.fromEntries(form));selected=r.entrance_id},'Создать дом');
}
$('#profile').value=profile;
async function changeContext(change){
 saveDraft();change();detail=null;queue=null;incidentData=null;detailVersion++;data=null;
 $('#modal').close();$('#content').textContent='Загружаем выбранный дом…';$('#content').setAttribute('aria-busy','true');
 $('#profile').disabled=true;$('#entrance').disabled=true;$('#join').disabled=true;$('#incidentsNav').disabled=true;
 try{await refresh();$('#refreshNotice').hidden=true}
 catch(err){toast(err.message);showRefreshError('Не удалось загрузить выбранный дом. Проверьте подключение и обновите данные.')}
 finally{$('#content').removeAttribute('aria-busy');$('#profile').disabled=false;$('#entrance').disabled=false;$('#join').disabled=!data;$('#incidentsNav').disabled=!data}
}
$('#profile').addEventListener('change',ev=>{const next=ev.target.value;changeContext(()=>{incidentSearch='';incidentFilter='active';profile=next;rememberProfile(profile);selected=null;if(['manage','detail','queue'].includes(tab))tab='home'})});
$('#entrance').addEventListener('change',ev=>{const next=Number(ev.target.value);changeContext(()=>{selected=next;if(['detail','queue'].includes(tab))tab='tickets'})});
$('#nav').addEventListener('click',ev=>{const b=ev.target.closest('[data-tab]');if(b&&data){detailVersion++;tab=b.dataset.tab;render();window.scrollTo(0,0)}});
$('#content').addEventListener('click',async ev=>{
 const b=ev.target.closest('button');if(!b)return;
 if(b.dataset.ifilter){incidentFilter=b.dataset.ifilter;renderIncidentList();return}
 if(b.dataset.linkOutage){linkTicketOutage();return}
 if(b.dataset.incidentUpdate){editIncident(Number(b.dataset.incidentUpdate),true);return}
 if(b.dataset.incidentComment){editIncident(Number(b.dataset.incidentComment),false);return}
 if(b.dataset.outageUpdate){updateOutage(Number(b.dataset.outageUpdate));return}
 if(b.dataset.read){b.disabled=true;try{await api('/api/notice/read',{entrance_id:selected,id:Number(b.dataset.read)});await updateViewAfterSave(refresh,'Отметка сохранена')}catch(e){toast(e.message);b.disabled=false}return}
 if(b.dataset.qfilter){queueFilter=b.dataset.qfilter;renderQueueList();return}
 if(b.dataset.queueTicket){b.disabled=true;try{selected=Number(b.dataset.eid);tab='tickets';await refresh();await openTicket(Number(b.dataset.queueTicket))}catch(e){toast(e.message)}finally{b.disabled=false}return}
 if(b.dataset.filter){ticketFilter=b.dataset.filter;renderTicketList();return}
 if(b.dataset.detail){b.disabled=true;try{await openTicket(Number(b.dataset.detail))}catch(e){toast(e.message)}finally{b.disabled=false}return}
 if(b.dataset.action){action(b.dataset.action);return}
 if(b.dataset.rotate){const eid=Number(b.dataset.rotate);modal('Заменить код приглашения?','<p class="modal-note">Старый код перестанет работать. Уже вступившие жители сохранят доступ. Новый код появится в карточке подъезда.</p>',()=>api('/api/invite/rotate',{entrance_id:eid}),'Заменить код');return}
 if(b.dataset.copy){try{await navigator.clipboard.writeText(b.dataset.copy);toast('Код скопирован')}catch{toast('Код приглашения: '+b.dataset.copy)}return}
 if(b.dataset.open){selected=Number(b.dataset.open);tab='chat';try{await refresh()}catch(e){toast(e.message)}return}
 if(b.dataset.status){
  const status=b.dataset.status,id=Number(b.dataset.id),eid=selected;
  const update=note=>api('/api/status',{entrance_id:eid,id,status,note});
  if(status==='done'||b.dataset.reopen){modal(b.dataset.reopen?'Что осталось исправить?':'Работа выполнена',`<label class="modal-field">${b.dataset.reopen?'Опишите, что не решено':'Что было сделано'}<textarea name="note" maxlength="1500" placeholder="Комментарий сохранится в истории заявки"></textarea></label><p class="modal-note">${b.dataset.reopen?'Заявка вернётся в работу УК.':'Житель сможет подтвердить результат или вернуть заявку в работу.'}</p>`,form=>update(form.get('note')),b.dataset.reopen?'Вернуть в работу':'Отметить выполненной');return}
  b.disabled=true;try{await update('');await updateViewAfterSave(async()=>{await refresh();if(tab==='detail'&&detail?.ticket.id===id)await openTicket(id)},'Статус обновлён')}catch(e){toast(e.message);b.disabled=false}
 }
});
$('#join').addEventListener('click',()=>modal('Присоединиться к подъезду',input('Код приглашения от УК','code','Например, PARK-01',40)+'<p class="modal-note">Код определяет ваш подъезд. Получите его у вашей управляющей компании.</p>',async form=>{const r=await api('/api/join',{code:form.get('code')});selected=r.entrance_id},'Присоединиться'));
$('#emergency').addEventListener('click',()=>modal('Экстренная помощь · 112','<p class="modal-note">При непосредственной опасности позвоните <strong>112</strong> с телефона. Приложение не вызывает службы и не передаёт им сообщения. Не ждите ответа в обсуждении подъезда.</p><a class="button primary full" href="tel:112">Перейти к набору 112</a>',null));
$('#emergencyMobile').addEventListener('click',()=>$('#emergency').click());
$('#profileHint').addEventListener('click',()=>$('#profile').focus());
$('#closeModal').addEventListener('click',()=>$('#modal').close());
$('#modal').addEventListener('cancel',ev=>{if(modalBusy)ev.preventDefault()});
$('#modalForm').addEventListener('submit',async ev=>{
 ev.preventDefault();if(!modalAction||modalBusy)return;
 const b=$('#submitModal'),afterSave=modalAfterSave,original=b.textContent;
 modalBusy=true;b.disabled=true;b.textContent='Сохраняем…';$('#closeModal').disabled=true;$('#formError').textContent='';
 let result;
 try{result=await modalAction(new FormData(ev.currentTarget))}
 catch(err){$('#formError').textContent=err.message;return}
 finally{modalBusy=false;b.disabled=false;b.textContent=original;$('#closeModal').disabled=false}
 $('#modal').close();
 await updateViewAfterSave(async()=>{await refresh();if(afterSave)await afterSave(result);else if(tab==='detail'&&detail)await openTicket(detail.ticket.id)},'Готово, изменения сохранены');
});
function showRefreshError(message='Изменения сохранены. Обновите экран, чтобы увидеть актуальные данные.'){ $('#refreshNotice span').textContent=message;$('#refreshNotice').hidden=false; }
async function updateViewAfterSave(update,message){
 try{await update();$('#refreshNotice').hidden=true;toast(message)}
 catch{toast('Изменения сохранены. Не удалось обновить экран — нажмите «Обновить данные».');showRefreshError()}
}
$('#refreshAll').addEventListener('click',async()=>{
 const b=$('#refreshAll');b.disabled=true;
 try{await refresh();if(tab==='detail'&&detail)await openTicket(detail.ticket.id);$('#refreshNotice').hidden=true;$('#join').disabled=false;$('#incidentsNav').disabled=false;toast('Данные обновлены')}
 catch(err){toast(err.message)}finally{b.disabled=false}
});
async function boot(){
 const config=await requestClient('/api/config');if(!['demo','max'].includes(config.mode))throw new Error('Сервер вернул неизвестный режим приложения');appMode=config.mode;
 if(appMode==='demo')$('.demo').textContent='ПРОТОТИП · Вымышленные жители · локальная демонстрация';
 if(appMode==='max'){
  $('.demo').textContent='Домовой · пилот · экстренные службы не подключены';
  $('#organization').textContent='Управляющая компания';$('#organizationHint').textContent='Связь через заявки в приложении';
  $('#profile').hidden=true;$('.profile-label').hidden=true;
  if(!window.WebApp)await new Promise((resolve,reject)=>{
   const script=document.createElement('script');
   const fail=()=>{clearTimeout(timer);script.remove();reject(new Error('Не удалось загрузить подключение MAX. Проверьте интернет и повторите попытку.'))};
   const timer=setTimeout(fail,15000);
   script.src='https://st.max.ru/js/max-web-app.js';script.onload=()=>{clearTimeout(timer);resolve()};script.onerror=fail;document.head.append(script);
  });
  initData=window.WebApp?.initData||'';
  if(!initData)throw new Error('Откройте приложение кнопкой в боте MAX');
  window.WebApp?.ready?.();
 }
 await refresh();
}
async function startApp(){
 try{await boot()}
 catch(err){$('#heading').textContent='Подключение к Домовому';$('#content').innerHTML=`<section class="card access-card"><span class="brand-icon">д.</span><h2>Не удалось открыть ваш дом</h2><p>${esc(err.message)}</p><button class="button primary" id="retryBoot">Повторить подключение</button>${appMode==='max'?'<p>Вход подтверждается аккаунтом MAX. Если в боте ещё нет кнопки приложения, привязка ссылки пока не завершена.</p><a class="button light" href="https://max.ru/t738_hakaton_max_bot">Перейти к боту ↗</a>':''}</section>`;$('#retryBoot').addEventListener('click',async ev=>{ev.target.disabled=true;await startApp()})}
}
startApp();

async function pollDiscussion(){
 if(polling||!data||tab!=='chat'||!selected||document.hidden||$('#modal').open)return;
 polling=true;const version=stateVersion,person=profile,eid=selected;
 try{
  const result=await api(`/api/state?entrance_id=${eid}`);
  if(version!==stateVersion||person!==profile||eid!==selected||tab!=='chat')return;
  const box=$('.messages');if(!box)return;
  const bottom=box.scrollHeight-box.clientHeight-box.scrollTop<60;
  const changed=JSON.stringify(data.messages)!==JSON.stringify(result.messages)||JSON.stringify(data.profiles)!==JSON.stringify(result.profiles);
  data=result;
  if(changed){const top=box.scrollTop;box.innerHTML=messageList();box.scrollTop=bottom?box.scrollHeight:top}
  $('.chat-heading small').textContent=`${residentCount(data.members.length)} · сообщения видят участники подъезда и УК`;
  $('#syncStatus').textContent='На связи · обновление каждые 5 секунд';
 }catch(err){if(version===stateVersion&&person===profile&&eid===selected&&tab==='chat'&&$('#syncStatus'))$('#syncStatus').textContent='Нет обновлений: '+err.message+' · повторим автоматически'}
 finally{polling=false}
}
setInterval(pollDiscussion,5000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollDiscussion()});

const incidentStatuses={saved:'Сохранено в учебной системе',review:'Учебный диспетчер изучает',clarify:'Нужно уточнение',closed:'Учебный разбор завершён'};
$('#incidentsNav').addEventListener('click',()=>{tab='incidents';incidentData=null;$('#content').textContent='Загружаем приватные обращения…';refresh().catch(e=>toast(e.message))});
function incidentCard(i){return `<article class="card incident-card"><div class="ticket"><span class="tag">Учебное № ${i.id}</span><span class="status ${i.status==='closed'?'confirmed':'work'}">${esc(incidentStatuses[i.status])}</span></div><h3>${esc(i.address)}</h3><p class="description">${esc(i.description)}</p><p>Обновлено ${esc(dateLabel(i.updated))}</p>${i.events.length>1?`<div class="incident-latest"><strong>${esc(i.events[i.events.length-1].actor)}</strong><p>${esc(i.events[i.events.length-1].note)}</p></div>`:''}<details class="outage-history"><summary>История и уточнения · ${i.events.length}</summary>${i.events.map(e=>`<div><strong>${esc(e.actor)} · ${esc(incidentStatuses[e.status])}</strong><time>${esc(dateLabel(e.created))}</time><p>${esc(e.note)}</p></div>`).join('')}</details>${i.status!=='closed'?`<div class="ticket-actions">${data.dispatcher?`<button class="button primary" data-incident-update="${i.id}">Изменить учебный статус</button>`:''}<button class="button light" data-incident-comment="${i.id}">Добавить уточнение</button></div>`:''}</article>`;}
function renderIncidentList(){
 const all=incidentData?.incidents||[];
 const rows=all.filter(i=>(incidentFilter==='all'||(incidentFilter==='active'?i.status!=='closed':i.status===incidentFilter))&&`${i.id} ${i.address} ${i.description}`.toLocaleLowerCase('ru').includes(incidentSearch.trim().toLocaleLowerCase('ru')));
 $('#incidentList').innerHTML=rows.map(incidentCard).join('')||'<div class="empty"><h3>Обращений с такими условиями нет</h3><p>Выберите другой статус или измените поиск.</p></div>';
 $('#incidentCount').textContent=`Найдено: ${rows.length} · поиск среди последних ${all.length} карточек (максимум 50)`;
 document.querySelectorAll('[data-ifilter]').forEach(b=>{b.classList.toggle('active',b.dataset.ifilter===incidentFilter);b.setAttribute('aria-pressed',String(b.dataset.ifilter===incidentFilter))});
}
function renderIncidents(){
 const counts=incidentData?.counts||{};
 $('#content').innerHTML=`<section class="card training-note"><span class="tag">УЧЕБНЫЙ СЦЕНАРИЙ</span><h2>${data.dispatcher?'Кабинет учебного диспетчера':'Личная связь с учебным диспетчером'}</h2><p>Покажите путь обращения и обратную связь на вымышленных данных. Сообщения не передаются в 112, полицию или МЧС.</p><p>При реальной опасности <a href="tel:112">позвоните 112</a>. Не ждите ответа здесь.</p>${data.demo?'<p>В локальном демо роли переключаются свободно. Не вводите личные данные.</p>':''}</section><div class="section-head"><h2>${data.dispatcher?'Очередь учебных обращений':'Мои учебные обращения'}</h2><button class="button light" data-action="incidents-refresh">Обновить</button></div><div class="queue-metrics">${[['saved','Новых'],['review','На разборе'],['clarify','Уточняются'],['closed','Завершено']].map(([key,label])=>`<div><strong>${counts[key]||0}</strong><span>${label}</span></div>`).join('')}</div>${!data.dispatcher?'<button class="button primary" data-action="incident-new">＋ Создать учебное обращение</button>':''}<p class="modal-note">Доступ: автор и учебный диспетчер. Соседи и роль УК чужие карточки не видят. Счётчики охватывают все доступные обращения; список обновляется вручную.</p><div class="ticket-tools"><label class="search-field"><span aria-hidden="true">⌕</span><input id="incidentSearch" type="search" aria-label="Поиск учебных обращений" placeholder="Номер, адрес или описание…" value="${esc(incidentSearch)}"></label><div class="filter-row">${[['active','Незавершённые'],['saved','Новые'],['review','На разборе'],['clarify','Уточнения'],['closed','Завершены'],['all','Все']].map(([k,v])=>`<button class="filter-chip" data-ifilter="${k}" aria-pressed="false">${v}</button>`).join('')}</div><p class="list-count" id="incidentCount" role="status"></p></div><div id="incidentList"></div>`;
 renderIncidentList();$('#incidentSearch').addEventListener('input',ev=>{incidentSearch=ev.target.value;renderIncidentList()});
}
function newIncident(){
 modal('Новое учебное обращение',input('Вымышленный адрес','address','Тестоград, Учебная улица, 1',240)+textarea('Что произошло · вымышленный сценарий','description','Опишите ситуацию для демонстрации',2000)+'<label class="training-ack"><input type="checkbox" name="training_ack" required> Понимаю: это учебное обращение, службы не вызываются.</label>',form=>api('/api/incidents',{address:form.get('address'),description:form.get('description'),training_ack:form.get('training_ack')==='on'}),'Сохранить учебное обращение');
}
function editIncident(id,statusChange){
 const item=incidentData?.incidents.find(i=>i.id===id);if(!item)return;
 modal(statusChange?'Учебный статус обращения':'Приватное уточнение',(statusChange?'<label class="modal-field">Учебный статус<select name="status">'+['review','clarify','closed'].map(k=>`<option value="${k}">${esc(incidentStatuses[k])}</option>`).join('')+'</select></label>':'')+textarea('Сообщение заявителю или диспетчеру','note','Уточните ситуацию или результат учебного разбора',1500)+'<p class="modal-note">Запись останется в истории. Это не подтверждение приёма или выезда экстренной службы.</p>',form=>api(statusChange?'/api/incidents/update':'/api/incidents/comment',{id:item.id,version:item.version,...Object.fromEntries(form)}),'Сохранить');
}
