(()=>{
 const btn=document.getElementById('ftc-menu-toggle'),scrim=document.getElementById('ftc-sidebar-scrim');
 const mobile=()=>window.matchMedia('(max-width:760px)').matches;
 try{const preference=localStorage.getItem('critbot-sidebar');if((preference==='collapsed'||(preference===null&&document.body.classList.contains('cw-rail-pref')))&&!mobile())document.body.classList.add('rail-collapsed')}catch{if(document.body.classList.contains('cw-rail-pref')&&!mobile())document.body.classList.add('rail-collapsed')}
 const sync=()=>btn?.setAttribute('aria-expanded',String(mobile()?document.body.classList.contains('sidebar-open'):!document.body.classList.contains('rail-collapsed')));
 btn?.addEventListener('click',()=>{if(mobile())document.body.classList.toggle('sidebar-open');else{document.body.classList.toggle('rail-collapsed');try{localStorage.setItem('critbot-sidebar',document.body.classList.contains('rail-collapsed')?'collapsed':'expanded')}catch{}}sync()});
 scrim?.addEventListener('click',()=>{document.body.classList.remove('sidebar-open');sync()});
 window.addEventListener('keydown',e=>{if(e.key==='Escape'){document.body.classList.remove('sidebar-open');document.querySelectorAll('.ftc-bell[open]').forEach(x=>x.open=false);sync()}});
 window.addEventListener('resize',()=>{if(!mobile())document.body.classList.remove('sidebar-open');sync()});sync();
})();
