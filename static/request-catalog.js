/* CritBot Rev G — full-catalog request browser, intentionally no client-side result cap. */
(()=>{'use strict';
const form=document.getElementById('ftc-new-order');if(!form)return;
const $=(id)=>document.getElementById(id);
const kind=$('ftc-order-kind'),prof=$('ftc-order-profession'),zone=$('ftc-zone-search'),faction=$('ftc-faction-filter');
const profBox=$('ftc-profession-box'),zoneBox=$('ftc-zone-box'),factionBox=$('ftc-faction-box');
const browser=$('ftc-catalog-panel'),search=$('ftc-catalog-search'),results=$('ftc-catalog-results'),preview=$('ftc-catalog-preview');
const key=$('ftc-order-catalog-key'),title=$('ftc-order-title'),qty=$('ftc-order-quantity'),qtyBox=$('ftc-order-quantity-label');
const requestQuest=$('cw-request-quest-meta'),requestCraft=$('cw-request-craft-meta');
const selectedButtons=[...document.querySelectorAll('[data-cc-kind]')];
// Define the element factory BEFORE tooltip creation. Earlier builds threw a
// temporal-dead-zone ReferenceError here and the entire Request Studio froze.
const make=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e};
const iconEmoji={Alchemy:'⚗',Blacksmithing:'⚒',Enchanting:'✧',Engineering:'⚙',Leatherworking:'◈',Tailoring:'🧵',Cooking:'♨','First Aid':'✚',Mining:'⛏',Fishing:'♧',Herbalism:'❀'};
const gameIconPattern=/^(?:\/static\/item-icons\/[a-z0-9_]+\.jpg|https:\/\/wow\.zamimg\.com\/images\/wow\/icons\/large\/[a-z0-9_]+\.jpg)$/;
const fallbackIconPattern=/^\/static\/item-fallbacks\/[a-z]+\.png$/;
const defaultFallback='/static/item-fallbacks/misc.png';
const qualities={0:'poor',1:'common',2:'uncommon',3:'rare',4:'epic',5:'legendary'};
function qualityClass(item){const q=item?.quality;if(q===null||q===undefined||q==='')return 'quality-unknown';const n=Number(q);return Number.isInteger(n)&&n>=0&&n<=5?'quality-'+qualities[n]:'quality-unknown'}
function iconEl(item,cls='cc-item-icon'){
 const holder=make('span',undefined,cls),url=item?.icon_url, fallback=fallbackIconPattern.test(item?.icon_fallback_url||'')?item.icon_fallback_url:defaultFallback;
 if(item?.kind==='quest'){
  holder.classList.add('cc-quest-icon');holder.textContent='!';return holder;
 }
 // The question-mark is WoW's real unknown-item indicator, NOT a guessed item icon.
 const pic=document.createElement('img');
 pic.src=typeof url==='string'&&gameIconPattern.test(url)?url:fallback;
 pic.alt=item?.icon_verified?'Verified WoW item icon':'Category illustration — exact item icon not available';pic.loading='lazy';
 if(!item?.icon_verified){holder.classList.add('cc-icon-unresolved');holder.title='Exact item art is not in the available Forever cache'};
 pic.addEventListener('error',()=>{
  if(!pic.src.endsWith(fallback)){pic.src=fallback;holder.classList.add('cc-icon-unresolved');return}
  pic.remove();holder.classList.add('cc-item-icon-missing');holder.append(make('span','◆'));
 });
 holder.append(pic);return holder;
}
const tooltip=make('div',undefined,'cc-wow-tooltip');tooltip.setAttribute('role','tooltip');tooltip.hidden=true;document.getElementById('cw-new-order').append(tooltip);
function tooltipMove(e){
 const x=Number.isFinite(e?.clientX)?e.clientX:Math.round(window.innerWidth/2);
 const y=Number.isFinite(e?.clientY)?e.clientY:Math.round(window.innerHeight/2);
 const rect=tooltip.getBoundingClientRect(),padding=12;
 const targetX=x+24+rect.width>window.innerWidth-padding?x-rect.width-20:x+24;
 const targetY=y+18+rect.height>window.innerHeight-padding?y-rect.height-12:y+18;
 tooltip.style.left=Math.max(padding,Math.min(targetX,window.innerWidth-rect.width-padding))+'px';
 tooltip.style.top=Math.max(padding,Math.min(targetY,window.innerHeight-rect.height-padding))+'px';
}
function detailLine(label,value){const d=make('div',undefined,'cc-wow-line');d.append(make('span',label),make('strong',value));return d}
function nativeLine(line){
 const text=String(line||'').trim();const p=make('p',text,'cc-native-line');
 if(/^\s*(Equip:|Use:|Chance on hit:)/i.test(text))p.classList.add('cc-native-effect');
 if(/^\s*Requires\s/i.test(text))p.classList.add('cc-native-requires');
 if(/^[\u201c"].+[\u201d"]$/.test(text))p.classList.add('cc-native-flavor');
 return p;
}
function tooltipShow(item,e){
 if(!item)return;
 tooltip.replaceChildren();tooltip.className='cc-wow-tooltip '+qualityClass(item)+' tip-'+(item.kind||'item');
 const isQuest=item.kind==='quest',isMaterial=item.kind==='material',wow=item.wow_tooltip||{};
 const header=make('div',undefined,'cc-tooltip-heading');
 header.append(iconEl(item,'cc-item-icon cc-tip-hero-icon'));
 const titleWrap=make('div',undefined,'cc-title-group');
 titleWrap.append(make('strong',item.name||'Unknown item','cc-tip-name'));
 titleWrap.append(make('span',isQuest?'QUEST':isMaterial?'MATERIAL':(item.profession?item.profession.toUpperCase()+' RECIPE':'CRAFTABLE ITEM'),'cc-tip-category'));
 header.append(titleWrap);tooltip.append(header);
 const body=make('div',undefined,'cc-tooltip-content');tooltip.append(body);
 if(isQuest){
  body.append(detailLine('Level',item.quest_level||'Unverified'));
  body.append(detailLine('Quest giver',item.quest_giver||'Not in source data'));
  body.append(detailLine('Zone',item.zone||'Not in source data'));
  if(item.objectives)body.append(make('p',item.objectives,'cc-tip-objective'));
  if(item.requirements)body.append(make('p',item.requirements,'cc-tip-need'));
 }else{
  const rawLines=Array.isArray(wow.lines)?wow.lines:[];
  if(item.item_level && !rawLines.some(x=>/^item level\b/i.test(String(x).trim())))body.append(make('div','Item Level '+item.item_level,'cc-tip-itemlevel'));
  // Native lines are extracted from the Forever item cache's tooltipHtml; no fake stats.
  let visible=0;
  rawLines.forEach((line,i)=>{
   if(typeof line!=='string')return;
   if(i===0&&line.trim().toLowerCase()===String(item.name||'').trim().toLowerCase())return;
   if(visible++>22)return;
   body.append(nativeLine(line));
  });
  if(!rawLines.length){
   if(item.item_description)body.append(make('p','“'+item.item_description+'”','cc-native-line cc-native-flavor'));
   if(!isMaterial){
    body.append(make('p',(item.item_made?'Creates '+item.item_made+'. ':'')+'Profession: '+(item.profession||'Unknown'),'cc-tip-summary'));

   }
   body.append(make('p','Full in-game item stats and description have not been verified for this item.','cc-tip-unverified'));
  }
  if(!isMaterial && item.skill_range)body.append(make('p','Crafting skill: '+item.skill_range,'cc-tip-skill'));
  if(item.item_id)body.append(make('p','Item ID: '+item.item_id,'cc-tip-id'));
  if(!item.icon_verified)body.append(make('p','Exact icon not identified in the available Forever item cache.','cc-tip-unverified'));
  if(item.reagents?.length){
   const reagents=make('section',undefined,'cc-tip-reagents');reagents.append(make('strong','Reagents','cc-tip-reagents-title'));
   for(const reagent of item.reagents){
    const row=make('div',undefined,'cc-tip-reagent');row.append(iconEl(reagent,'cc-item-icon cc-item-icon-small'),make('span',reagent.qty+' × '+reagent.name));reagents.append(row);
   }
   body.append(reagents);
  }
 }
 tooltip.append(make('small',isQuest?'ForeverGuide quest record · Availability unverified':'Forever item cache where available · In-game data may change','cc-tip-source'));
 tooltip.hidden=false;tooltipMove(e);
}
function attachTooltip(el,item){
 el.addEventListener('mouseenter',e=>tooltipShow(item,e));
 el.addEventListener('mousemove',tooltipMove);
 el.addEventListener('mouseleave',()=>{tooltip.hidden=true});
 el.addEventListener('focus',()=>{const r=el.getBoundingClientRect();tooltipShow(item,{clientX:r.right,clientY:r.top})});
 el.addEventListener('blur',()=>{tooltip.hidden=true});
}
window.addEventListener('keydown',e=>{if(e.key==='Escape')tooltip.hidden=true});
const editorDialog=document.getElementById('cw-new-order');if(editorDialog)editorDialog.addEventListener('close',()=>tooltip.hidden=true);

let current=null,requestNumber=0,debounceId=0,page=1,lastPages=1;
const displayText=(v)=>String(v ?? 'Not confirmed');
const entryId=(v)=>v?(v.catalog_key||'material:'+v.name):'';
function row(label,text){const d=make('div',undefined,'cc-fact');d.append(make('span',label),make('strong',displayText(text)));return d;}
function blank(message,detail){preview.replaceChildren(make('div','⌕','cc-empty-icon'),make('strong',message),make('p',detail));}
function inspect(item){
  preview.replaceChildren(make('span',item.kind==='quest'?'QUEST INFORMATION':item.kind==='material'?'MATERIAL INFORMATION':'CRAFTING INFORMATION','cc-preview-label'));
  const itemHead=make('div',undefined,'cc-selected-item '+qualityClass(item));itemHead.append(iconEl(item),make('h3',item.name));preview.append(itemHead);attachTooltip(itemHead,item);
  const badge=make('span',item.kind==='quest'?(item.faction||'Unknown faction'):(item.profession||'Unclassified'),'cc-preview-pill');preview.append(badge);
  if(item.kind!=='quest' && item.item_description){preview.append(make('p','“'+item.item_description+'”','cc-preview-flavor'))}
  const list=make('div',undefined,'cc-facts');
  if(item.kind==='quest'){
    list.append(row('Quest ID',item.quest_id||item.catalog_key?.split(':')[1]||'Unverified'),row('Starts with',item.quest_giver||'Quest giver not recorded'),row('Location',item.zone||'Zone not recorded'),row('Quest level',item.quest_level||'Not recorded'),row('Objectives',item.objectives||'See your in-game quest log'),row('Prerequisites',item.requirements||'Not recorded'));
  }else if(item.kind==='material'){
    list.append(row('Used by professions',item.profession||'Not specified'),row('Recipes using it',item.recipe_uses||0),row('How to obtain','Gather, trade, or ask a guildmate. Game source unverified.'));
  }else{
    list.append(row('Profession',item.profession),row('Recipe spell ID',item.recipe_spell_id||'Not recorded'),row('Output item ID',item.output_item_id||'Service / not recorded'),row('Produces',item.item_made||item.name),row('Skill thresholds',item.skill_range||'Not confirmed'),row('Ingredients',item.materials||'Not recorded'),row('Recipe source',item.recipe_type||'Not confirmed'));
  }
  preview.append(list);
  if(item.reagents?.length){const box=make('div',undefined,'cc-reagent-grid');box.append(make('strong','Materials needed · hover for detail'));
   item.reagents.forEach(x=>{const chip=make('div',undefined,'cc-reagent');chip.append(iconEl(x,'cc-item-icon cc-item-icon-small'),make('span',x.qty+' × '+x.name));
    chip.tabIndex=0;attachTooltip(chip,{...x,kind:'material',name:x.name,profession:item.profession});box.append(chip)});preview.append(box)}
  const bottom=make('div',undefined,'cc-evidence');
  bottom.append(make('span',(item.data_status||'Source data incomplete')+' · Check current game requirements.'));
  if(item.source_url && /^https:\/\//.test(item.source_url)){
    const a=make('a','Source ↗');a.href=item.source_url;a.target='_blank';a.rel='noopener noreferrer';bottom.append(a);
  }
  preview.append(bottom);
  const b=make('button','Use this '+(item.kind==='quest'?'quest':item.kind==='material'?'material':'recipe')+' ✓','cc-use-entry');b.type='button';b.addEventListener('click',()=>select(item));preview.append(b);
}
function select(item){current=item;key.value=item.kind==='material'?'':item.catalog_key;title.value=item.item_made||item.name;inspect(item);
  [...results.querySelectorAll('.cc-result')].forEach(el=>{let yes=el.dataset.key===entryId(item);el.classList.toggle('selected',yes);el.setAttribute('aria-selected',String(yes))});
}
function showResult(item){
  const btn=make('button',undefined,'cc-result '+qualityClass(item));btn.type='button';btn.dataset.key=entryId(item);
  const heading=make('span',undefined,'cc-result-title');heading.append(make('strong',item.name));
  if(item.new_in_forever)heading.append(make('span','Forever','cc-new'));
  const info=make('span',undefined,'cc-result-info');btn.append(iconEl(item),info);info.append(heading);
  const meta=item.kind==='quest'?[item.quest_level?'Lv '+item.quest_level:null,item.zone||null].filter(Boolean).join(' · '):item.kind==='material'?[item.profession||'Other','Used in '+(item.recipe_uses||0)+' recipes'].join(' · '):[item.profession||'Other',item.skill_range||'Skill unknown'].join(' · ');
  info.append(make('span',meta,'cc-result-meta'));
  const foot=item.kind==='quest'?(item.quest_giver||'Giver not verified'):item.kind==='material'?'A reagent used in guild crafting':(item.materials||'Ingredients not listed');
  info.append(make('small',foot,'cc-result-context'));
  btn.classList.toggle('selected',entryId(current)===entryId(item));btn.setAttribute('aria-selected',String(entryId(current)===entryId(item)));
  btn.addEventListener('click',()=>{tooltip.hidden=true;select(item)});
  attachTooltip(btn,item);
  return btn;
}
function drawPage(body){
  results.replaceChildren();
  for(const item of body.records||[])results.append(showResult(item));
  if(!(body.records||[]).length)results.append(make('div','No matching entries. Try a shorter search or use a custom title.','cc-empty-results'));
  page=body.page||1;lastPages=body.pages||1;
  $('cw-catalog-page').textContent=`${page.toLocaleString()} / ${lastPages.toLocaleString()}`;
  $('cw-catalog-prev').disabled=page<=1;$('cw-catalog-next').disabled=page>=lastPages;
  $('ftc-catalog-count').textContent=`${(body.total||0).toLocaleString()} matches`;
  $('cc-source-note').textContent=`${(body.total_available||0).toLocaleString()} imported ${kind.value==='Quest Help'?'quest':kind.value==='Materials'?'material':'recipe'} records · Game-data catalog; live content and quest eligibility still require verification.`;
}
async function load(goToPage=1){
 if(!['Quest Help','Crafting','Materials'].includes(kind.value))return;
 const sequence=++requestNumber;page=Math.max(1,goToPage);
 results.replaceChildren(make('div','Searching the catalog…','cc-empty-results'));$('ftc-catalog-count').textContent='Searching…';
 const params=new URLSearchParams({kind:kind.value==='Quest Help'?'quest':kind.value==='Materials'?'material':'craft',q:search.value.trim(),profession:prof.value,zone:zone.value.trim(),faction:faction.value,page:String(page)});
 try{
  const res=await fetch('/hub/catalog/search?'+params,{credentials:'same-origin',headers:{Accept:'application/json'}});
  if(!res.ok)throw new Error(`Server returned ${res.status}`);
  const body=await res.json();if(sequence!==requestNumber)return;
  drawPage(body);
 }catch(err){if(sequence!==requestNumber)return;
  $('ftc-catalog-count').textContent='Search unavailable';results.replaceChildren(make('div','Catalog unavailable. You can still enter a custom request.','cc-empty-results'));console.error('CritBot catalog:',err)}
}
function debounce(){clearTimeout(debounceId);debounceId=setTimeout(()=>load(1),180)}
function updateKind(){
 const type=kind.value,isQuest=type==='Quest Help',isCraft=type==='Crafting',isMaterial=type==='Materials',usesCatalog=isQuest||isCraft||isMaterial;
 selectedButtons.forEach(b=>{const yes=b.dataset.ccKind===type;b.classList.toggle('selected',yes);b.setAttribute('aria-pressed',String(yes))});
 browser.hidden=!usesCatalog;profBox.hidden=!(isCraft||isMaterial);zoneBox.hidden=!isQuest;factionBox.hidden=!isQuest;
 qtyBox.hidden=isQuest||type==='Help';requestQuest.hidden=!isQuest;requestCraft.hidden=!isCraft;
 search.value='';prof.value='';zone.value='';faction.value='all';current=null;key.value='';title.value='';qty.value='1';
 $('cc-results-label').textContent=isQuest?'QUESTS FOR THE HORDE':isCraft?'CRAFTABLE ITEMS':isMaterial?'RECIPE MATERIALS':'YOUR REQUEST';
 $('ftc-catalog-heading').textContent=isQuest?'QUEST LIBRARY':isCraft?'PROFESSION LIBRARY':isMaterial?'MATERIAL LIBRARY':'';
 $('ftc-catalog-coverage').textContent=isQuest?'Search by quest name, giver, zone, and objective.':isMaterial?'Find recipe reagents by name or profession.':'Select a profession, then search by item or ingredient.';
 search.placeholder=isQuest?'Quest, NPC, zone, objective…':isMaterial?'Cloth, bars, gems, herbs…':'Recipe, crafted item, reagents…';
 title.placeholder=isQuest?'e.g. The Book of Ur':isCraft?'e.g. Woolen Bag':isMaterial?'e.g. Wool Cloth':'What do you need help with?';
 blank(usesCatalog?`Choose ${isQuest?'a quest':'an item'}`:'Write a custom request',usesCatalog?'Search by name or use the profession and zone filters.':'You can request help even when it is not in a game database.');
 if(usesCatalog)load();else requestNumber++;
}
selectedButtons.forEach(b=>b.addEventListener('click',()=>{kind.value=b.dataset.ccKind;kind.dispatchEvent(new Event('change',{bubbles:true}))}));
kind.addEventListener('change',updateKind);search.addEventListener('input',debounce);zone.addEventListener('input',debounce);prof.addEventListener('change',()=>load(1));faction.addEventListener('change',()=>load(1));
$('cw-catalog-prev').addEventListener('click',()=>{if(page>1)load(page-1)});$('cw-catalog-next').addEventListener('click',()=>{if(page<lastPages)load(page+1)});
title.addEventListener('input',()=>{if(current&&title.value!==(current.item_made||current.name)){
 current=null;key.value='';[...results.querySelectorAll('.cc-result')].forEach(b=>{b.classList.remove('selected');b.setAttribute('aria-selected','false')});
 blank('Custom request','The title was edited, so no game entry will be linked. You can still post it.');
}});
updateKind();
})();
