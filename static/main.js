'use strict';
(() => {
 const $=id=>document.getElementById(id), dialog=$('achievement-dialog');
 const achievements=JSON.parse($('achievement-data').textContent),state=JSON.parse($('member-state').textContent);
 const storageKey='critbot-main-workspace-v015';let saved={};
 try { saved=JSON.parse(sessionStorage.getItem(storageKey)||'{}'); } catch (_) {}
 let member=null,action='award',selected=new Set(),busy=false,reviewing=false,revision=0,polling=false;
 const queries={award:saved.awardQuery||'',revoke:saved.revokeQuery||''};
 const textNode=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 $('ach-search').value=saved.achievementSearch||'';$('member-search').value=saved.memberSearch||'';$('ach-rarity').value=saved.rarity||'';$('ach-category').value=saved.category||'';
 function persist(){
   const data={achievementSearch:$('ach-search').value,memberSearch:$('member-search').value,rarity:$('ach-rarity').value,category:$('ach-category').value,
     awardQuery:queries.award,revokeQuery:queries.revoke,member:member||saved.member,action,open:dialog.open,selected:[...selected]};
   try { sessionStorage.setItem(storageKey,JSON.stringify(data)); } catch (_) {}
 }
 const filterList=(input,list,count,empty,selector,extra)=>{
   const apply=()=>{let visible=0;const rows=[...$(list).querySelectorAll(selector)],term=$(input).value.trim().toLowerCase();
     for(const row of rows){row.hidden=!(row.dataset.search.includes(term)&&(!extra||!$(extra).value||row.dataset.rarity===$(extra).value)&&(list!=='ach-list'||!$('ach-category').value||row.dataset.category===$('ach-category').value));if(!row.hidden)visible++;}
     $(count).textContent=`${visible} of ${rows.length} shown`;$(empty).hidden=visible>0||rows.length===0;persist();};
   $(input).addEventListener('input',apply);if(extra)$(extra).addEventListener('change',apply);apply();
 };
 filterList('ach-search','ach-list','ach-count','ach-empty','.ach-row','ach-rarity');
 $('ach-category').addEventListener('change',()=>{$('ach-search').dispatchEvent(new Event('input'));});
 filterList('member-search','member-list','member-count','member-empty','.member-row');
 function eligibility(a){
   const own=new Set(state.owned[member?.id]||[]),waiting=state.waiting[member?.id]||{};
   const pendingAward=new Set(waiting.award||[]),pendingRevoke=new Set(waiting.revoke||[]);
   if(pendingAward.has(a.id))return {allowed:false,label:'Award queued',show:true};
   if(pendingRevoke.has(a.id))return {allowed:false,label:'Revoke queued',show:true};
   if(action==='award')return {allowed:!own.has(a.id),label:own.has(a.id)?'Already unlocked':'Available',show:true};
   return {allowed:own.has(a.id),label:'Unlocked',show:own.has(a.id)};
 }
 function feedback(message,kind='success'){$('picker-feedback').hidden=false;$('picker-feedback').textContent=message;$('picker-feedback').dataset.kind=kind;}
 function showReview(open){reviewing=open;$('picker-choose').hidden=open;$('picker-review').hidden=!open;if(open)renderReview();}
 function renderReview(){
   const names=achievements.filter(a=>selected.has(a.id));
   $('review-title').textContent=action==='award'?'Confirm awards':'Confirm revocations';
   $('review-description').textContent=`${action==='award'?'Add':'Revoke'} ${names.length} achievement${names.length===1?'':'s'} ${action==='award'?'for':'from'} ${member.name}?`;
   $('review-list').replaceChildren(...names.map(a=>textNode('li','',`${a.name} · ${a.points} points`)));
   $('review-confirm').textContent=busy?'Queuing…':`Confirm ${action==='award'?'awards':'revocations'}`;$('review-confirm').disabled=busy||!names.length;
   $('review-back').disabled=busy;
 }
 function render(){
   if(!member)return;
   for(const id of [...selected]){const a=achievements.find(a=>a.id===id);if(!a||!eligibility(a).allowed)selected.delete(id);}
   const term=$('picker-search').value.trim().toLowerCase(),target=$('picker-options'),scroll=target.scrollTop,focused=document.activeElement?.dataset.achievement;
   const matches=achievements.filter(a=>eligibility(a).show&&(a.name+' '+a.description).toLowerCase().includes(term));target.replaceChildren();
   for(const a of matches){
     const status=eligibility(a),row=textNode('label','picker-option'+(selected.has(a.id)?' selected':'')+(!status.allowed?' unavailable':''));
     const cb=document.createElement('input');cb.type='checkbox';cb.dataset.achievement=String(a.id);cb.checked=selected.has(a.id);cb.disabled=busy||!status.allowed;cb.setAttribute('aria-label',a.name);
     cb.addEventListener('change',()=>{if(cb.checked)selected.add(a.id);else selected.delete(a.id);render();persist();});
     const detail=textNode('span','picker-option-text');detail.append(textNode('strong','',a.name),textNode('small','',`${a.category || 'Guild feat'} · ${a.rarity} · ${a.points} points · ${status.label}`));
     const symbol=textNode('span','list-icon');
     if (/^achievement-icons\/[A-Z][0-9]{2}\.png$/.test(a.icon||'')) {
       const img=document.createElement('img'); img.className='ftc-ach-art'; img.alt=''; img.src='/static/'+a.icon;symbol.append(img);
     } else symbol.textContent=a.icon||'🏆';
     row.append(cb,symbol,detail);target.append(row);
   }
   if(focused){const cb=target.querySelector(`input[data-achievement="${focused}"]`);if(cb&&!cb.disabled)cb.focus({preventScroll:true});}
   target.scrollTop=scroll;$('picker-empty').hidden=matches.length>0;
   $('picker-selection').textContent=selected.size?`${selected.size} achievement${selected.size===1?'':'s'} selected`:'Select one or several achievements';
   $('picker-submit').disabled=busy||selected.size===0;
   for(const mode of ['award','revoke']){const button=$('mode-'+mode);button.classList.toggle('active',mode===action);button.setAttribute('aria-pressed',String(mode===action));button.disabled=busy;}
   $('picker-search').disabled=busy;$('picker-clear-search').disabled=busy;
   if(reviewing){if(!selected.size&&!busy){showReview(false);feedback('That selection is no longer eligible. Choose another achievement.','warning');}else renderReview();}
 }
 function applyState(id,value){state.owned[id]=value.owned||[];state.waiting[id]=value.waiting||{};if(member?.id===id)render();}
 async function refreshState(){
   if(!dialog.open||!member||busy||polling)return;
   polling=true;const id=member.id,version=revision;
   try{const response=await fetch('/api/member-state/'+encodeURIComponent(id),{cache:'no-store'});if(response.ok){const data=await response.json();if(version===revision&&member?.id===id){applyState(id,data.state);persist();}}}
   catch (_) {} finally {polling=false;}
 }
 function markMember(){for(const row of document.querySelectorAll('.member-row'))row.classList.toggle('member-current',!!member&&row.querySelector('[data-member]')?.dataset.member===member.id);}
 function openMember(button,restore=false){
   if(busy)return;revision++;
   member={id:button.dataset.member,name:button.dataset.name};action=button.dataset.action;
   selected=restore?new Set((saved.selected||[]).filter(id=>Number.isInteger(id))):new Set();
   $('picker-member-name').textContent=member.name;$('picker-search').value=queries[action];$('picker-feedback').hidden=true;showReview(false);markMember();render();
   if(!dialog.open)dialog.showModal();persist();refreshState();$('picker-search').focus();
 }
 for(const button of document.querySelectorAll('[data-member][data-action]'))button.addEventListener('click',()=>openMember(button));
 for(const mode of ['award','revoke'])$('mode-'+mode).addEventListener('click',()=>{if(busy||action===mode)return;action=mode;selected.clear();$('picker-search').value=queries[mode];showReview(false);render();persist();});
 $('picker-search').addEventListener('input',()=>{queries[action]=$('picker-search').value;render();persist();});
 $('picker-clear-search').addEventListener('click',()=>{$('picker-search').value='';queries[action]='';render();persist();$('picker-search').focus();});
 $('picker-close').addEventListener('click',()=>{if(!busy)dialog.close();});
 dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});dialog.addEventListener('close',persist);
 $('member-action-form').addEventListener('submit',event=>{event.preventDefault();if(selected.size&&!busy){showReview(true);$('review-confirm').focus();}});
 $('review-back').addEventListener('click',()=>{showReview(false);$('picker-submit').focus();});
 $('review-confirm').addEventListener('click',async()=>{
   if(busy||!member||!selected.size)return;const id=member.id,type=action,ids=[...selected];busy=true;revision++;render();
   try{
     const response=await fetch('/api/member-actions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member_id:id,action:type,achievement_ids:ids})});
     const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not queue these changes.');
     if(data.state)applyState(id,data.state);
     if(member.id===id){for(const aid of ids)selected.delete(aid);showReview(false);const count=data.queued.length,skipped=data.skipped.length;
       feedback(`${count} ${type==='award'?'award':'revocation'}${count===1?'':'s'} queued for ${member.name}.${skipped?` ${skipped} skipped because their status changed.`:''} Keep selecting to manage more achievements.`,count?'success':'warning');}
   }catch(error){showReview(false);feedback(error.message+' Your selection is retained; check queued badges before retrying.','error');}
   finally{busy=false;render();persist();refreshState();}
 });
 setInterval(refreshState,5000);
 if(saved.member){const button=[...document.querySelectorAll('[data-member][data-action]')].find(b=>b.dataset.member===saved.member.id&&b.dataset.action===(saved.action||'award'));if(button){member=saved.member;markMember();if(saved.open)openMember(button,true);}}
})();
