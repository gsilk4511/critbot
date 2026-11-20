(()=>{'use strict';
const tabs=[...document.querySelectorAll('[data-history-tab]')],panes=[...document.querySelectorAll('[data-history-pane]')];
tabs.forEach(tab=>tab.addEventListener('click',()=>{let target=tab.dataset.historyTab;tabs.forEach(x=>{let active=x.dataset.historyTab===target;x.classList.toggle('is-selected',active);x.setAttribute('aria-pressed',String(active));});panes.forEach(x=>{let active=x.dataset.historyPane===target;x.hidden=!active;x.classList.toggle('is-visible',active);});}));
document.querySelectorAll('.cb-release-search').forEach(input=>input.addEventListener('input',()=>{const q=input.value.trim().toLowerCase();const pane=input.closest('[data-history-pane]');pane.querySelectorAll('.cb-version-entry').forEach(entry=>{let text=entry.textContent.toLowerCase();entry.hidden=!!q&&!text.includes(q);if(q&&text.includes(q))entry.open=true;});}));
})();
