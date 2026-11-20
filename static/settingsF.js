(() => {
 const root=document.querySelector('#cbx-form');if(!root)return;
 const tabs=[...root.querySelectorAll('[data-cbx-tab]')],panels=[...root.querySelectorAll('[data-cbx-panel]')];
 const status=root.querySelector('#cbx-save-status');
 const preview=root.querySelector('#cbx-preview');
 function show(tab){tabs.forEach(b=>{const match=b.dataset.cbxTab===tab;b.classList.toggle('is-selected',match);b.setAttribute('aria-pressed',String(match))});panels.forEach(p=>p.hidden=p.dataset.cbxPanel!==tab)}
 tabs.forEach(b=>b.addEventListener('click',()=>show(b.dataset.cbxTab)));
 function refresh(){for(const attr of ['theme','density','hub_layout']){const value=root.querySelector(`[name="${attr}"]:checked`)?.value;if(value)preview.dataset[attr==='hub_layout'?'layout':attr]=value}status.textContent='Unsaved changes';status.classList.add('is-unsaved')}
 root.addEventListener('input',refresh);root.addEventListener('change',refresh);
 root.addEventListener('submit',()=>{const nav=root.querySelector('[name="compact_sidebar"]');try{localStorage.setItem('critbot-sidebar',nav.checked?'collapsed':'expanded')}catch{}});
 show('appearance');
})();
