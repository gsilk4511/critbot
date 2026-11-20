(()=>{'use strict';
const tabs=[...document.querySelectorAll('.cb126-tabs [data-family]')];
const panes=[...document.querySelectorAll('.cb126-pane')];
for(const tab of tabs)tab.addEventListener('click',()=>{
  const f=tab.dataset.family;
  for(const t of tabs){const on=t.dataset.family===f;t.classList.toggle('selected',on);t.setAttribute('aria-pressed',String(on));}
  for(const p of panes)p.hidden=p.dataset.releaseFamily!==f;
});
for(const pane of panes){const field=pane.querySelector('.cb126-search');
  field?.addEventListener('input',()=>{const q=field.value.trim().toLocaleLowerCase();
    for(const entry of pane.querySelectorAll('.cb126-item'))entry.hidden=!!q&&!entry.textContent.toLocaleLowerCase().includes(q);
  });
}
})();
