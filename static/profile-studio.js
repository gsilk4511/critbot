// CritBot 1.01 profile studio. All updates occur locally; server validates and saves.
(() => {
  const form = document.getElementById('appearance-form');
  if (!form) return;
  const preview = document.getElementById('studio-live-preview');
  const cover = document.getElementById('studio-preview-cover');
  const awards = document.getElementById('studio-preview-awards');
  const checks = [...form.querySelectorAll('input[name="featured"]')];
  const selected = name => form.querySelector(`input[name="${name}"]:checked`)?.value || '';
  const getText = name => form.querySelector(`[name="${name}"]`)?.value.trim() || '';
  const setClasses = (node, prefix, choice) => {
    if (!node) return;
    [...node.classList].filter(cls => cls.startsWith(prefix)).forEach(cls => node.classList.remove(cls));
    if (choice) node.classList.add(prefix + choice);
  };
  function update() {
    const ids = ['theme','layout','frame_style','art_filter','typography','avatar_style','trophy_density'];
    const prefixes = ['p-theme-','p-layout-','p-frame-','p-filter-','p-type-','p-avatar-','p-density-'];
    ids.forEach((id,index)=>setClasses(preview,prefixes[index],selected(id)));
    setClasses(cover,'p-banner-',selected('banner'));
    const rankStyle=form.querySelector('[name=rank_style]')?.value || 'banner';
    setClasses(preview,'p-rank-',rankStyle);
    const picture=form.querySelector('input[name="portrait"]:checked');
    const portraitNode=document.getElementById('studio-preview-portrait');
    const initialNode=document.getElementById('studio-preview-initial');
    if(picture?.value && picture.value!=='none' && picture.dataset.src){
      portraitNode.src=picture.dataset.src; portraitNode.hidden=false; if(initialNode) initialNode.hidden=true;
    } else {
      portraitNode.removeAttribute('src'); portraitNode.hidden=true; if(initialNode) initialNode.hidden=false;
    }
    const emblem=form.querySelector('input[name="portrait_emblem"]:checked');
    const emblemImg=emblem?.closest('label')?.querySelector('img');
    const emblemNode=document.getElementById('studio-preview-emblem');
    if(emblemImg){emblemNode.src=emblemImg.src; emblemNode.hidden=false;}
    else {emblemNode.removeAttribute('src');emblemNode.hidden=true;}
    preview.dataset.awardView = selected('award_view');
    const tagline=document.getElementById('studio-preview-tagline');
    tagline.textContent=getText('tagline')||'Your story, your legend.';
    document.getElementById('studio-preview-caption').textContent=getText('showcase_caption')||'A few moments worth putting on display.';
    let checked=checks.filter(cb=>cb.checked);
    checks.forEach(cb=>cb.disabled = !cb.checked && checked.length >= 3);
    awards.replaceChildren();
    const featured=checked.length?checked:checks.slice(0,2);
    if (!featured.length) {
      [['✦','Guild achievement','uncommon'],['★','Another victory','epic']].forEach(([icon,name,rarity])=>appendAward(icon,name,rarity));
    } else {
      featured.forEach(cb=>{
        const parent=cb.closest('.studio-award-choice');
        appendAward(parent?.dataset.awardIcon||'✦',parent?.dataset.awardName||'Achievement',parent?.dataset.awardRarity||'common');
      });
    }
  }
  function appendAward(icon,name,rarity){
    const item=document.createElement('span');
    item.className='studio-preview-award preview-rarity-'+rarity;
    const badge=document.createElement('span');
    if (/^achievement-icons\/[A-Z][0-9]{2}\.png$/.test(icon)) {
      const img=document.createElement('img');img.className='ftc-ach-art';img.src='/static/'+icon;img.alt='';badge.append(img);
    } else badge.textContent=icon;
    const text=document.createElement('b');text.textContent=name;
    item.append(badge,text);awards.append(item);
  }
  const portraitGrid=document.getElementById('studio-portrait-grid');
  const portraitOptions=[...portraitGrid.querySelectorAll('.studio-portrait-option')];
  const portraitSearch=document.getElementById('studio-portrait-search');
  const portraitCategory=document.getElementById('studio-portrait-filter');
  const showAllBtn=document.getElementById('studio-portrait-more');
  let showingAll=false;
  function filterPortraits(){
    if(document.body.classList.contains('ftc-profile-editor'))return; // Dev D pager owns visibility.
    const q=portraitSearch.value.trim().toLowerCase(), category=portraitCategory.value;
    const matches=portraitOptions.filter(label=>(category==='all'||label.dataset.group===category || label.querySelector('input').value==='none')
      &&(!q || label.dataset.name.includes(q) || label.querySelector('input').value==='none'));
    let shown=0;
    for(const label of portraitOptions){
      const isSelected=!!label.querySelector('input:checked');
      const visible=matches.includes(label) && (showingAll||shown<15||isSelected);
      label.hidden=!visible;
      if(visible)shown++;
    }
    showAllBtn.hidden=showingAll||matches.length<=16;
  }
  portraitSearch.addEventListener('input',()=>{showingAll=true;filterPortraits();});
  portraitCategory.addEventListener('change',()=>{showingAll=false;filterPortraits();});
  showAllBtn.addEventListener('click',()=>{showingAll=true;filterPortraits();});
  document.getElementById('studio-portrait-random').addEventListener('click',()=>{
    const pool=portraitOptions.filter(el=>el.querySelector('input').value!=='none' && (portraitCategory.value==='all'||el.dataset.group===portraitCategory.value));
    if(!pool.length)return;
    const target=pool[Math.floor(Math.random()*pool.length)].querySelector('input');
    target.checked=true; showingAll=true;filterPortraits();update();
  });
  filterPortraits();
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  update();
})();
