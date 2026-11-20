(() => {
 const byId=id=>document.getElementById(id);
 const form=byId('ar-reward-form'); if(!form)return;
 const newBlock=byId('ar-new-reward'),existingBlock=byId('ar-existing-reward'),nameInput=byId('ar-achievement-name'),existingSelect=byId('ar-achievement');
 const refreshMode=()=>{const fresh=form.querySelector('input[name="reward_mode"]:checked')?.value==='new';newBlock.hidden=!fresh;existingBlock.hidden=fresh;nameInput.required=fresh;nameInput.disabled=!fresh;existingSelect.disabled=fresh;existingSelect.required=!fresh;};
 form.querySelectorAll('input[name="reward_mode"]').forEach(x=>x.addEventListener('change',refreshMode));refreshMode();
 const targets={messages:['How many counted messages?','One counted message per person per minute.'],voice:['How many voice minutes?','60 minutes = 1 hour in qualifying voice rooms.'],days:['How many active days?','Active days need not be consecutive.']};
 const refreshKind=()=>{const kind=form.querySelector('input[name="kind"]:checked')?.value||'messages';byId('ar-target-label').textContent=targets[kind][0];byId('ar-target-help').textContent=targets[kind][1];};
 form.querySelectorAll('input[name="kind"]').forEach(x=>x.addEventListener('change',refreshKind));refreshKind();
 const voiceAll=byId('voice-all');const refreshVoice=()=>byId('specific-voice-channels').hidden=voiceAll.checked;
 voiceAll?.addEventListener('change',refreshVoice);refreshVoice();
 function updateCount(id,target){const group=byId(id);if(!group)return;const n=group.querySelectorAll('input[type="checkbox"]:checked').length;byId(target).textContent=n+' selected';}
 for(const [id,target] of [['text-channels','ar-chat-count'],['voice-channels','ar-voice-count']]){
  const group=byId(id);if(!group)continue;
  group.addEventListener('change',()=>updateCount(id,target));updateCount(id,target);
 }
 document.querySelectorAll('[data-check-all],[data-uncheck-all]').forEach(btn=>btn.addEventListener('click',()=>{
  const group=byId(btn.dataset.checkAll||btn.dataset.uncheckAll);const value=!!btn.dataset.checkAll;
  group.querySelectorAll('input[type="checkbox"]').forEach(input=>{if(!input.closest('[hidden]'))input.checked=value;});
  updateCount(group.id,group.id==='text-channels'?'ar-chat-count':'ar-voice-count');
 }));
 document.querySelectorAll('[data-channel-search]').forEach(input=>input.addEventListener('input',()=>{
  const query=input.value.trim().toLowerCase();
  byId(input.dataset.channelSearch).querySelectorAll('[data-channel-name]').forEach(row=>row.hidden=!row.dataset.channelName.includes(query));
 }));
 document.querySelectorAll('.ar-edit-rule').forEach(button=>button.addEventListener('click',()=>{
  const type=form.querySelector(`input[name="kind"][value="${button.dataset.kind}"]`);if(type)type.checked=true;
  form.querySelector('input[name="reward_mode"][value="existing"]').checked=true;
  existingSelect.value=button.dataset.achievement;
  byId('ar-target').value=button.dataset.target;
  refreshKind();refreshMode();
  form.querySelector('[type="submit"]').textContent='Save reward goal';
  byId('ar-create').scrollIntoView({behavior:'smooth',block:'start'});
 }));
})();