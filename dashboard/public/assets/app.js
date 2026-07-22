const areaOrder=['warehouse','logistics','transport','import_export','inventory','cost','capacity','service','business_continuity'];
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
fetch('data/current_events.json').then(r=>r.json()).then(data=>{
 const events=data.events||[];
 document.querySelector('#freshness').textContent=`ข้อมูลตัวอย่าง: ${data.generated_at||'ไม่ทราบเวลา'}`;
 document.querySelector('#active-count').textContent=events.filter(e=>e.lifecycle_stage!=='Closed').length;
 document.querySelector('#thai-count').textContent=events.filter(e=>['medium','high'].includes(e.thailand_relevance)).length;
 document.querySelector('#noimpact-count').textContent=events.filter(e=>e.publication_status==='No material impact detected').length;
 const list=document.querySelector('#event-list');
 list.innerHTML=events.map(e=>`<article class="event"><div class="meta"><span class="badge">${esc(e.publication_status)}</span><span>${esc(e.lifecycle_stage)}</span><span>Thailand: ${esc(e.thailand_relevance)}</span><span>Evidence scope: ${esc(e.scope_supported)}</span></div><h3>${esc(e.title)}</h3><p>${esc(e.verified_facts?.[0]||'No verified summary')}</p><p><strong>Known limitation:</strong> ${esc(e.known_limitations?.[0]||'None recorded')}</p><p><a href="${esc(e.evidence?.[0]?.source_url)}" rel="noopener" target="_blank">Primary source</a></p></article>`).join('')||'<p>No reviewed events.</p>';
 document.querySelector('#impact-body').innerHTML=events.map(e=>{const m=Object.fromEntries((e.impact_assessments||[]).map(i=>[i.area,i]));return `<tr><th>${esc(e.title)}</th>${areaOrder.map(a=>`<td class="sev-${esc(m[a]?.severity||'none')}">${esc(m[a]?.severity||'—')}<br><small>${esc(m[a]?.status||'')}</small></td>`).join('')}</tr>`}).join('');
}).catch(err=>{document.querySelector('#freshness').textContent='Dashboard data unavailable';console.error(err)});
