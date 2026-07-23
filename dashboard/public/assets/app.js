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

const coverageWording={
 sufficient:'Sufficient — every tracked capability has a fresh or stale source behind it.',
 limited:'Limited — some capabilities have degraded, stale, or missing source coverage.',
 insufficient:'Insufficient — a required capability has no working source. This is a coverage gap, not an all-clear.'
};
fetch('data/source_status.json').then(r=>r.json()).then(status=>{
 const banner=document.querySelector('#coverage-banner');
 const overall=status.overall_status||'insufficient';
 banner.className=`notice cov-${esc(overall)}`;
 banner.innerHTML=`<strong>Overall coverage: ${esc(overall)}.</strong> ${esc(coverageWording[overall]||status.coverage_message||'')}<br>${esc(status.coverage_message||'')}<br><small>Generated at ${esc(status.generated_at||'unknown time')}. A source outage or gap is reported as a missing capability, never as zero events or an all-clear.</small>`;

 const capabilities=status.capabilities||[];
 document.querySelector('#capability-cards').innerHTML=capabilities.map(c=>`<article class="metric cov-${esc(c.status)}"><span>${esc(c.capability)}</span><strong>${esc(c.status)}</strong><small>${esc(c.gap_reason||'Covered by '+(c.supporting_sources||[]).join(', '))}</small></article>`).join('')||'<p>No tracked capabilities.</p>';

 const sources=status.sources||[];
 document.querySelector('#source-status-body').innerHTML=sources.map(s=>{
  const note=s.status==='error'?(s.last_error||'Error, no message recorded'):
    (s.status==='no_data'?'No successful retrieval recorded yet — this is a gap, not zero events.':
    (s.status==='disabled'?'Live collection is disabled for this source.':''));
  return `<tr class="src-${esc(s.status)}"><th>${esc(s.source_id)}</th><td><span class="badge src-badge-${esc(s.status)}">${esc(s.status)}</span></td><td>${esc(s.last_checked_at||'never')}</td><td>${esc(s.last_success_at||'never')}</td><td>${s.item_count===null||s.item_count===undefined?'—':esc(s.item_count)}</td><td>${s.required_for_publication?'Yes':'No'}</td><td>${esc(note)}</td></tr>`;
 }).join('')||'<tr><td colspan="7">No tracked sources.</td></tr>';
}).catch(err=>{
 const banner=document.querySelector('#coverage-banner');
 banner.className='notice cov-insufficient';
 banner.textContent='Source status data unavailable — treat coverage as insufficient until it loads.';
 console.error(err);
});
