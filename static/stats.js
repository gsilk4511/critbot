'use strict';
(() => {
  const roster = JSON.parse(document.getElementById('stats-data').textContent);
  const metric = document.getElementById('stats-metric');
  const limit = document.getElementById('stats-limit');
  const profile = document.getElementById('stats-profile');
  const search = document.getElementById('stats-search');
  let selected = null, controller = null;
  const labels = {messages:'counted messages',voice_seconds:'voice minutes',days:'active days',points:'points',unlocks:'unlocks'};
  const format = (value, key) => key === 'voice_seconds' ? (value / 60).toLocaleString(undefined,{maximumFractionDigits:1}) : value.toLocaleString();
  const el = (tag, cls, text) => {const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;};
  function renderChart() {
    const key=metric.value;
    const sorted=[...roster].sort((a,b)=>b[key]-a[key] || a.display_name.localeCompare(b.display_name));
    const shown=limit.value==='all'?sorted:sorted.slice(0,Number(limit.value));
    const max=Math.max(0,...shown.map(m=>m[key]));
    const root=document.getElementById('stats-chart');root.replaceChildren();
    document.getElementById('chart-description').textContent=`${shown.length} members · ${labels[key]}`;
    if(!shown.length)root.append(el('p','stats-status','No members synced yet. Start Critbot and refresh after member sync.'));
    for(const m of shown){
      const row=el('button','stats-bar-row'+(selected===m.member_id?' selected':''));row.type='button';row.setAttribute('aria-pressed',String(selected===m.member_id));
      row.setAttribute('aria-label',`${m.display_name}: ${format(m[key],key)} ${labels[key]}. View member stats.`);
      row.append(el('span','stats-bar-name',m.display_name));
      const track=el('span','stats-bar-track');const fill=el('span','stats-bar-fill');fill.style.width=(max?m[key]/max*100:0)+'%';track.append(fill);row.append(track);
      row.append(el('span','stats-bar-value',format(m[key],key)));row.addEventListener('click',()=>selectMember(m));root.append(row);
    }
  }
  function renderRoster(){
    const q=search.value.trim().toLowerCase();const shown=roster.filter(m=>(m.display_name+' '+m.username).toLowerCase().includes(q));
    const root=document.getElementById('stats-roster');root.replaceChildren();
    document.getElementById('stats-roster-count').textContent=`${shown.length} of ${roster.length} members`;
    for(const m of shown){
      const row=el('button',selected===m.member_id?'selected':'');row.type='button';row.setAttribute('aria-pressed',String(selected===m.member_id));
      row.append(el('strong','',m.display_name),el('small','',m.username),el('small','',`${format(m.messages,'messages')} msgs · ${format(m.voice_seconds,'voice_seconds')} voice min · ${m.days} days`));
      row.addEventListener('click',()=>selectMember(m));root.append(row);
    }
    if(!shown.length)root.append(el('p','stats-status','No members match your search.'));
  }
  async function selectMember(m){
    selected=m.member_id;renderChart();renderRoster();
    if(controller)controller.abort();controller=new AbortController();const signal=controller.signal;
    profile.replaceChildren(el('p','stats-status',`Loading ${m.display_name}…`));
    try{
      const response=await fetch('/stats/member/'+encodeURIComponent(m.member_id),{signal,cache:'no-store'});
      if(!response.ok)throw new Error(response.status===404?'Member is no longer synced. Refresh the stats page.':'Could not load member stats. Try again.');
      const data=await response.json();if(signal.aborted)return;renderProfile(data);
    }catch(error){if(error.name!=='AbortError')profile.replaceChildren(el('p','stats-status stats-error',error.message));}
  }
  function renderProfile(data){
    profile.replaceChildren();
    const heading=el('div','stats-profile-title');heading.append(el('h2','',data.member.display_name),el('p','',data.member.username+' · Cumulative tracked stats'));profile.append(heading);const profileLink=el('a','small-cta','Open full member profile ↗');profileLink.href='/members/'+encodeURIComponent(data.member.member_id||selected);profileLink.style.marginBottom='14px';profile.append(profileLink);
    const grid=el('div','member-stat-grid');
    for(const [key,label] of Object.entries(labels)){const card=el('div');card.append(el('strong','',format(data.stats[key],key)),el('small','',label));grid.append(card);}profile.append(grid);
    profile.append(el('h3','','Achievement progress'));
    if(!data.progress.length)profile.append(el('p','subtitle','No automatic milestone rules are configured yet.'));
    for(const p of data.progress){
      const card=el('div','stats-milestone');const top=el('div','stats-milestone-top');top.append(el('strong','',`${/^achievement-icons\/[A-Z][0-9]{2}\.png$/.test(p.icon||'')?'🏅':p.icon} ${p.name}`),el('span','',p.percent+'%'));card.append(top);
      const track=el('div','stats-progress-track');track.setAttribute('role','progressbar');track.setAttribute('aria-label',p.name);track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax','100');track.setAttribute('aria-valuenow',p.percent);
      const fill=el('div','stats-progress-fill');fill.style.width=p.percent+'%';track.append(fill);card.append(track);
      const detail=el('div','stats-milestone-detail');detail.append(el('span','',`${p.current.toLocaleString(undefined,{maximumFractionDigits:p.kind==='voice'?1:0})} / ${p.target.toLocaleString()} ${p.unit}`),el('span','',p.state));card.append(detail);profile.append(card);
    }
    profile.append(el('h3','','Unlocked collection'));
    if (!data.collection?.length) profile.append(el('p','subtitle','No unlocked achievements yet.'));
    for (const award of data.collection || []) {
      const card=el('div','stats-milestone');
      const top=el('div','stats-milestone-top');const title=el('strong');
      if(/^achievement-icons\/[A-Z][0-9]{2}\.png$/.test(award.icon||'')){
        const img=el('img','ftc-ach-art');img.src='/static/'+award.icon;img.alt='';img.style.cssText='width:42px;height:42px;display:inline-block;vertical-align:middle;margin-right:8px';title.append(img);
      } else title.append(document.createTextNode((award.icon||'🏆')+' '));
      title.append(document.createTextNode(award.name));top.append(title,el('span','',`${award.points} pts`));card.append(top);
      const detail=el('div','stats-milestone-detail');detail.append(el('span','',award.rarity),el('span','',`Unlocked ${String(award.awarded_at).slice(0,10)}`));card.append(detail);profile.append(card);
    }
    profile.append(el('h3','','Recent active dates'));
    const dates=el('div','stats-day-list');for(const day of data.recent_days)dates.append(el('span','',day));profile.append(dates);
    if(!data.recent_days.length)profile.append(el('p','subtitle','No qualifying active days recorded.'));
    profile.append(el('p','stats-note','Latest 14 recorded Eastern dates. An active day is a qualifying message or at least one qualifying voice minute. These dates may not be consecutive.'));
  }
  metric.addEventListener('change',renderChart);limit.addEventListener('change',renderChart);search.addEventListener('input',renderRoster);
  document.getElementById('stats-refresh').addEventListener('click',()=>window.location.reload());renderChart();renderRoster();
  const linkedMember = new URLSearchParams(window.location.search).get('member');
  if (linkedMember) {
    const member = roster.find(m => m.member_id === linkedMember);
    if (member) selectMember(member);
  }
})();
