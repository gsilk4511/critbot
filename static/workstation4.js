/* CritBot Dev D · second-monitor workspace interactions. No third-party JS. */
(()=>{'use strict';
const $=(s,root=document)=>root.querySelector(s), $$=(s,root=document)=>Array.from(root.querySelectorAll(s));
const buttons=$$('[data-dialog]');
buttons.forEach(btn=>btn.addEventListener('click',()=>{
 const d=document.getElementById(btn.dataset.dialog);if(!d)return;
 if(btn.dataset.type){const kind=$('#cw-kind',d)||$('#ftc-order-kind',d);if(kind){kind.value=btn.dataset.type;kind.dispatchEvent(new Event('change',{bubbles:true}));}}
 d.showModal();
}));
$$('dialog.cw-dialog').forEach(d=>{
 $$('[data-close-dialog]',d).forEach(b=>b.addEventListener('click',()=>d.close()));
 d.addEventListener('click',e=>{if(e.target===d)d.close()});
});
// Render paginated search results without a scrolling viewport. A pager keeps every record accessible.
function pager(rootId, prevId, nextId, labelId, pageSize=4, filter){
 const root=document.getElementById(rootId);if(!root)return null;
 const prev=document.getElementById(prevId),next=document.getElementById(nextId),label=document.getElementById(labelId);
 let page=0;
 function draw(reset=false){if(reset)page=0;
  const all=$$(':scope > article',root),matches=all.filter(n=>!filter||filter(n));
  const pages=Math.max(1,Math.ceil(matches.length/pageSize));page=Math.min(page,pages-1);
  all.forEach(n=>{n.hidden=true});matches.forEach((n,i)=>n.hidden=!(i>=page*pageSize&&i<(page+1)*pageSize));
  if(label)label.textContent=`${page+1} / ${pages}${matches.length?` · ${matches.length}`:''}`;
  if(prev)prev.disabled=page<=0;if(next)next.disabled=page>=pages-1;
 }
 prev?.addEventListener('click',()=>{page=Math.max(0,page-1);draw()});next?.addEventListener('click',()=>{page++;draw()});draw();return draw;
}
const orderSearch=$('#cw-order-search'), orderType=$('#cw-order-filter');
const openOrders=pager('cw-open-list','cw-open-prev','cw-open-next','cw-open-page',3,n=>(!orderSearch?.value||n.textContent.toLowerCase().includes(orderSearch.value.trim().toLowerCase()))&&(!orderType||orderType.value==='All'||n.dataset.type===orderType.value));
orderSearch?.addEventListener('input',()=>openOrders?.(true));orderType?.addEventListener('change',()=>openOrders?.(true));
pager('cw-mine-list','cw-mine-prev','cw-mine-next','cw-mine-page',3);
const dungeonSearch=$('#cw-group-search');const groupDraw=pager('cw-dungeon-list','cw-dungeon-prev','cw-dungeon-next','cw-dungeon-page',4,n=>!dungeonSearch.value||n.textContent.toLowerCase().includes(dungeonSearch.value.toLowerCase()));dungeonSearch?.addEventListener('input',()=>groupDraw?.(true));
const eventSearch=$('#cw-event-search'),eventType=$('#cw-event-type');let chosenDate='';
const eventDraw=pager('cw-event-list','cw-event-prev','cw-event-next','cw-event-page',4,n=>(!eventSearch.value||n.textContent.toLowerCase().includes(eventSearch.value.toLowerCase()))&&(eventType.value==='all'||n.dataset.type===eventType.value)&&(!chosenDate||n.dataset.date===chosenDate));
eventSearch?.addEventListener('input',()=>eventDraw?.(true));eventType?.addEventListener('change',()=>eventDraw?.(true));
$$('.cw-calendar-day').forEach(day=>day.addEventListener('click',()=>{chosenDate=chosenDate===day.dataset.date?'':day.dataset.date;$$('.cw-calendar-day').forEach(el=>el.classList.toggle('selected',el.dataset.date===chosenDate));const label=$('#cw-date-selected');if(label)label.textContent=chosenDate||'All upcoming dates';eventDraw?.(true)}));
$('#cw-date-clear')?.addEventListener('click',()=>{chosenDate='';$$('.cw-calendar-day').forEach(el=>el.classList.remove('selected'));$('#cw-date-selected').textContent='All upcoming dates';eventDraw?.(true)});
// A compact quest/item lookup for Quick Post on the Guild Hub.
const quickForm=$('#cw-quick-form');
if(quickForm){
 const kind=$('#cw-kind'),quest=$('#cw-quest-fields'),craft=$('#cw-craft-fields'),key=$('#cw-catalog-key'),title=$('#cw-title'),qQty=$('#cw-quantity'),displayQty=$('#cw-display-quantity');
 let seq=0,debounceId;
 function typeChange(){const questMode=kind.value==='Quest Help',craftMode=kind.value==='Crafting';quest.hidden=!questMode;craft.hidden=!craftMode;key.value='';title.value='';qQty.value='1';if(displayQty)displayQty.value='1';if(questMode)load('quest');if(craftMode)load('craft')}
 function resultRows(target,rows,type){target.replaceChildren();if(!rows.length){const p=document.createElement('p');p.textContent='Nothing found. Type a custom title below.';target.append(p);return}
  for(const row of rows.slice(0,5)){const b=document.createElement('button');b.type='button';b.className='cw-result';const line=document.createElement('strong');line.textContent=row.item_made||row.name;const small=document.createElement('small');small.textContent=type==='quest'?[row.zone||'Zone unknown','Giver: '+(row.quest_giver||'Unverified')].join(' · '):[row.profession||'Profession unknown',(row.materials||'Materials unverified').slice(0,65)].join(' · ');b.append(line,small);b.addEventListener('click',()=>{title.value=row.item_made||row.name;key.value=row.catalog_key;$$('.cw-result',target).forEach(x=>x.classList.remove('selected'));b.classList.add('selected')});target.append(b)}
 }
 async function load(type){const target=$(type==='quest'?'#cw-quest-results':'#cw-craft-results');if(!target)return;const n=++seq,search=$(type==='quest'?'#cw-quest-search':'#cw-craft-search'),profession=$('#cw-profession');target.textContent='Searching the catalog…';const params=new URLSearchParams({kind:type,q:search?.value||'',profession:type==='craft'?(profession?.value||''):''});
  try{const response=await fetch('/hub/catalog/search?'+params,{credentials:'same-origin'});if(!response.ok)throw new Error('Catalog unavailable');const data=await response.json();if(seq!==n||kind.value!==(type==='quest'?'Quest Help':'Crafting'))return;resultRows(target,data.records||[],type)}catch{if(seq===n)target.textContent='Catalog currently unavailable. You can enter a custom title.'}
 }
 kind.addEventListener('change',typeChange);
 for(const [id,type] of [['cw-quest-search','quest'],['cw-craft-search','craft']])$('#'+id)?.addEventListener('input',()=>{clearTimeout(debounceId);debounceId=setTimeout(()=>load(type),180)});
 $('#cw-profession')?.addEventListener('change',()=>load('craft'));
 displayQty?.addEventListener('input',()=>{qQty.value=displayQty.value||'1'});
 title.addEventListener('input',()=>{key.value=''});
 typeChange();
}
// Class-role picker for instant dungeon joins. Server remains the authority.
const roles={Warrior:['Tank','DPS'],Paladin:['Tank','Healer','DPS'],Hunter:['DPS'],Rogue:['DPS'],Priest:['Healer','DPS'],Shaman:['Healer','DPS'],Mage:['DPS'],Warlock:['DPS'],Druid:['Tank','Healer','DPS']};
$$('.cw-group-form').forEach(form=>{
 const char=$('.cw-join-character',form),classSelect=$('.cw-join-class',form),manual=$('.cw-manual-character',form),role=$('.cw-join-role',form);
 const original=$$('option',role).map(o=>({name:o.value,label:o.textContent}));
 function sync(){const saved=char.selectedOptions[0];const isSaved=!!char.value;manual.hidden=isSaved;const cls=isSaved?saved.dataset.class:classSelect.value;const allowed=roles[cls]||['Tank','Healer','DPS'];let first='';role.replaceChildren();original.filter(o=>allowed.includes(o.name)).forEach(o=>{const n=document.createElement('option');n.value=o.name;n.textContent=o.label;role.append(n);if(!first)first=o.name});if(!first){const n=document.createElement('option');n.textContent='No available role for this class';n.value='';role.append(n)} }
 char.addEventListener('change',sync);classSelect.addEventListener('change',sync);sync();
});
// Settings mini-preview is instantaneous; saving is always explicit.
const settings=$('#cw-settings-form');if(settings){const preview=$('#cw-mini-preview'),theme=$('#cw-theme-select'),density=$('#cw-density-select');function update(){preview.dataset.theme=theme.value;preview.dataset.density=density.value}theme.addEventListener('change',update);density.addEventListener('change',update);settings.addEventListener('submit',()=>{try{localStorage.setItem('critbot-sidebar',settings.querySelector('[name=compact_sidebar]').checked?'collapsed':'expanded')}catch{}});update()}
// Directory pagination; hundreds of members are searchable without page scroll.
const directorySearch=$('#profile-search'),directoryFilter=$('#profile-filter'),directoryGrid=$('#member-profile-grid');
if(directoryGrid){const tiles=$$('.member-tile-v101',directoryGrid);let page=0;const prev=$('#cw-directory-prev'),next=$('#cw-directory-next'),out=$('#cw-directory-page');function draw(reset=false){if(reset)page=0;const q=(directorySearch?.value||'').toLowerCase().trim(),f=directoryFilter?.value||'all';const matches=tiles.filter(t=>t.dataset.search.includes(q)&&(f==='all'||(f==='customized'&&t.dataset.customized==='true')||(f==='featured'&&Number(t.dataset.awards)>0)||(f==='blank'&&t.dataset.customized!=='true')));const pages=Math.max(1,Math.ceil(matches.length/8));page=Math.min(page,pages-1);tiles.forEach(el=>el.hidden=true);matches.forEach((el,i)=>{el.hidden=i<page*8||i>=(page+1)*8});if(out)out.textContent=`${page+1} / ${pages} · ${matches.length} members`;if(prev)prev.disabled=!page;if(next)next.disabled=page>=pages-1;$('#member-empty-search').hidden=!!matches.length}prev?.addEventListener('click',()=>{page--;draw()});next?.addEventListener('click',()=>{page++;draw()});directorySearch?.addEventListener('input',()=>draw(true));directoryFilter?.addEventListener('change',()=>draw(true));draw()}
// Profile Studio: persistent preview beside collapsible controls. No duplicate forms.
const studio=$('.ftc-profile-editor .profile-studio-layout');
if(studio){
 const root=$('.profile-studio-main',studio),preview=$('.studio-live-preview-wrap',root),identity=$('#personal-details',root),appearance=$('#personal-style',root),trophies=$('#achievement-showcase',root),form=$('#appearance-form',root);
 const dock=document.createElement('aside');dock.className='cw-studio-preview-dock';dock.innerHTML='<div class="cw-preview-head"><span>✦ LIVE MEMBER PAGE</span><small>Everything updates before you publish.</small></div>';if(preview)dock.append(preview);studio.append(dock);
 const switcher=document.createElement('nav');switcher.className='cw-studio-switcher';switcher.setAttribute('aria-label','Profile editor sections');switcher.innerHTML='<button type="button" data-panel="personal-style">Appearance</button><button type="button" data-panel="personal-details">About me</button><button type="button" data-panel="achievement-showcase">Achievements</button>';root.prepend(switcher);
 function show(name){identity.hidden=name!=='personal-details';appearance.hidden=name!=='personal-style';trophies.hidden=name!=='achievement-showcase';$$('[data-panel]',switcher).forEach(b=>{b.classList.toggle('selected',b.dataset.panel===name);b.setAttribute('aria-pressed',String(b.dataset.panel===name))});}
 $$('[data-panel]',switcher).forEach(b=>b.addEventListener('click',()=>show(b.dataset.panel)));show('personal-style');
 // Organize all appearance controls by function; only one expanded section is needed at a time.
 const pSection=$('#studio-portrait-picker',appearance),bGrid=$('.studio-banner-grid',appearance),tGrid=$('.studio-theme-grid',appearance),advanced=$('.studio-advanced-details',appearance);
 function accordion(name,nodes,open=false){const d=document.createElement('details');d.className='cw-studio-accordion';d.open=open;const summary=document.createElement('summary');summary.textContent=name;d.append(summary);const wrap=document.createElement('div');wrap.className='cw-studio-accordion-content';nodes.filter(Boolean).forEach(n=>wrap.append(n));d.append(wrap);appearance.append(d);d.addEventListener('toggle',()=>{if(d.open)$$('.cw-studio-accordion',appearance).forEach(o=>{if(o!==d)o.open=false})});return d}
 // Keep tagline on the main editor, directly above the compact control sections.
 const small=$$('.studio-subtitle',appearance),moreTheme=$$('.studio-emblem-details',appearance),trophyPicker=$('.studio-theme-grid',appearance);
 accordion('Portrait & emblem',[pSection],true);
 accordion('Backdrop & banner',[bGrid]);accordion('Color theme',[tGrid,...moreTheme]);accordion('Advanced layout, lighting & frames',[advanced]);
 small.forEach(e=>e.remove());
 const submit=document.createElement('button');submit.type='submit';submit.className='cw-action cw-publish';submit.textContent='Publish profile changes ✓';appearance.append(submit);
 // Portraits are navigated in pages, not a 57-option scrolling catalog.
 const picker=$('#studio-portrait-grid',appearance),search=$('#studio-portrait-search',appearance),filter=$('#studio-portrait-filter',appearance);if(picker){const bar=document.createElement('div');bar.className='cw-page-pager';bar.innerHTML='<button type="button">←</button><span>1 / 1</span><button type="button">→</button>';picker.after(bar);const [prev,label,next]=bar.children;let page=0;function paginate(reset=false){if(reset)page=0;const options=$$('.studio-portrait-option',picker).filter(n=>{const i=n.querySelector('input'),q=(search?.value||'').trim().toLowerCase(),group=filter?.value||'all';return (!q||n.dataset.name.includes(q))&&(group==='all'||n.dataset.group===group||i.value==='none')});const pages=Math.max(1,Math.ceil(options.length/8));page=Math.min(page,pages-1);$$('.studio-portrait-option',picker).forEach(n=>n.hidden=true);options.forEach((n,i)=>{n.hidden=!(i>=page*8&&i<(page+1)*8)});label.textContent=`${page+1} / ${pages}`;prev.disabled=!page;next.disabled=page>=pages-1;}
 prev.addEventListener('click',()=>{page--;paginate()});next.addEventListener('click',()=>{page++;paginate()});search?.addEventListener('input',()=>paginate(true));filter?.addEventListener('change',()=>paginate(true));setTimeout(()=>paginate(),80);}
}
})();
