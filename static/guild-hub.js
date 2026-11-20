(()=>{
'use strict';
const wizard=document.getElementById('hub-wizard');
if(!wizard)return;
const steps=[...wizard.querySelectorAll('.hub-step')];
const dots=[...wizard.querySelectorAll('.hub-progress i')];
const label=document.getElementById('wizard-step-label');
const toon=document.getElementById('hub-character');
const cls=document.getElementById('hub-class');
let step=0;
function show(n){step=Math.max(0,Math.min(2,n));steps.forEach((s,i)=>s.hidden=i!==step);dots.forEach((d,i)=>d.classList.toggle('active',i<=step));label.textContent=`0${step+1} / 03`;if(step===2){
 const checked=[...wizard.querySelectorAll('input[name="interests"]:checked')].map(e=>e.value);
 const summary=document.getElementById('hub-picked-interests');summary.replaceChildren();
 (checked.length?checked:['Everything']).forEach(s=>{const tag=document.createElement('span');tag.textContent=s;summary.append(tag)});
 document.getElementById('hub-character-summary').textContent=toon.value.trim()?`${toon.value.trim()} · ${cls.value||'Choose a class'}`:'Character: add later';
}}
wizard.querySelectorAll('[data-next]').forEach(btn=>btn.addEventListener('click',()=>{
 if(step===1&&toon.value.trim()&&!cls.value){cls.setCustomValidity('Choose a class or skip character entry.');cls.reportValidity();return;}
 if(step===1&&toon.value.trim().length===1){toon.setCustomValidity('Use at least two characters.');toon.reportValidity();return;}
 cls.setCustomValidity('');toon.setCustomValidity('');show(step+1);
}));
wizard.querySelectorAll('[data-back]').forEach(btn=>btn.addEventListener('click',()=>show(step-1)));
const skip=document.getElementById('hub-skip-character');if(skip)skip.addEventListener('click',()=>{toon.value='';cls.value='';show(2)});
show(0);
})();
