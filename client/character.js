/* Character Manager — 2-col stats, correct milestones, Excellence works, debounced autosave to /characters */

(() => {
  const $  = (s,e=document)=>e.querySelector(s);
  const $$ = (s,e=document)=>Array.from(e.querySelectorAll(s));
  const num = v => (v===''||v==null) ? 0 : Number(v);

  const saveStatus = $('#saveStatus');
  const setStatus = (t,kind='')=>{
    if(!saveStatus) return;
    saveStatus.textContent=t;
    saveStatus.classList.remove('good','danger');
    if(kind) saveStatus.classList.add(kind);
  };

  // ---------- Data model ----------
  const GROUPS = [
    { key:'ref', label:'Reflex (REF)',    investKey:'reflexp',    skills:[
      {key:'technicity',label:'Technicity'},
      {key:'dodge',label:'Dodge'},
      {key:'tempo',label:'Tempo'},
      {key:'reactivity',label:'Reactivity'},
    ]},
    { key:'dex', label:'Dexterity (DEX)', investKey:'dexterityp', skills:[
      {key:'accuracy',label:'Accuracy'},
      {key:'evasion',label:'Evasion'},
      {key:'stealth',label:'Stealth'},
      {key:'acrobatics',label:'Acrobatics'},
    ]},
    { key:'bod', label:'Body (BOD)',      investKey:'bodyp',      skills:[
      {key:'brutality',label:'Brutality'},
      {key:'blocking',label:'Blocking'},
      {key:'resistance',label:'Resistance'},
      {key:'athletics',label:'Athletics'},
    ]},
    { key:'wil', label:'Willpower (WIL)', investKey:'willpowerp', skills:[
      {key:'intimidation',label:'Intimidation'},
      {key:'spirit',label:'Spirit'},
      {key:'instinct',label:'Instinct'},
      {key:'absorption',label:'Absorption'},
    ]},
    { key:'mag', label:'Magic (MAG)',     investKey:'magicp',     skills:[
      {key:'aura',label:'Aura'},
      {key:'incantation',label:'Incantation'},
      {key:'enchantment',label:'Enchantment'},
      {key:'restoration',label:'Restoration'},
      {key:'potential',label:'Potential'},
    ]},
    { key:'pre', label:'Presence (PRE)',  investKey:'presencep',  skills:[
      {key:'taming',label:'Taming'},
      {key:'charm',label:'Charm'},
      {key:'charisma',label:'Charisma'},
      {key:'deception',label:'Deception'},
      {key:'persuasion',label:'Persuasion'},
    ]},
    { key:'wis', label:'Wisdom (WIS)',    investKey:'wisdomp',    skills:[
      {key:'survival',label:'Survival'},
      {key:'education',label:'Education'},
      {key:'perception',label:'Perception'},
      {key:'psychology',label:'Psychology'},
      {key:'investigation',label:'Investigation'},
    ]},
    { key:'tec', label:'Tech (TEC)',      investKey:'techp',      skills:[
      {key:'crafting',label:'Crafting'},
      {key:'soh',label:'Sleight of hand'},
      {key:'alchemy',label:'Alchemy'},
      {key:'medecine',label:'Medicine'},
      {key:'engineering',label:'Engineering'},
    ]},
  ];
  const INTENSITIES = ['Fire','Water','Earth','Wind','Lightning','Moon','Sun','Ki'];

  // ---------- Math helpers ----------
  const modFromScore = score => Math.floor(score/2 - 5);   // Milestone = characteristic modifier
  const scoreFromInvest = invest => 4 + invest;
  const tens = lvl => Math.floor(lvl/10);

  // ---------- Build UI (2-column) ----------
  const charSkillContainer = $('#charSkillContainer');

  function buildCharCards(){
    charSkillContainer.innerHTML = '';
    GROUPS.forEach(g => {
      const card = document.createElement('div');
      card.className = 'char-card';

      card.innerHTML = `
        <div class="char-head">
          <div class="char-name">${g.label}</div>
          <div class="char-metrics">[ <span>Total</span> | <span>Milestone</span> ]</div>
          <div class="char-metrics"><b data-c-total="${g.key}">4</b> | <b data-c-milestone="${g.key}">-3</b></div>
        </div>

        <div class="char-invest">
          <div class="muted">Characteristic</div>
          <input class="input" type="number" min="0" max="16" value="0" data-c-invest="${g.investKey}">
          <span class="badge mono">Milestone: <b data-c-milestone="${g.key}">-3</b></span>
        </div>

        <div class="skills" data-skill-group="${g.key}">
          ${g.skills.map(s=>`
            <div class="skill-row">
              <div class="skill-name">— ${s.label}</div>
              <input class="input" type="number" min="0" max="8" value="0" data-s-invest="${s.key}">
              <div class="skill-base mono" data-s-base="${s.key}">0</div>
            </div>
          `).join('')}
        </div>
      `;
      charSkillContainer.appendChild(card);
    });
  }

  function buildIntensityTable(){
    const tbody = $('#intensityTable tbody'); tbody.innerHTML = '';
    INTENSITIES.forEach(nm=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${nm}</td>
        <td><input class="input" type="number" min="0" max="8" value="0" data-i-invest="${nm}"></td>
        <td class="mono" data-i-mod="${nm}">0</td>
        <td class="mono" data-i-base="${nm}">0</td>
        <td class="mono" data-i-id="${nm}">—</td>
        <td class="mono" data-i-iv="${nm}">—</td>
        <td class="mono right" data-i-rw="${nm}">0</td>
      `;
      tbody.appendChild(tr);
    });
  }

  buildCharCards();
  buildIntensityTable();

  // ---------- Sublimations ----------
  const SUB_TYPES = [
    { id:'2', label:'Lethality' },
    { id:'1', label:'Excellence' }, // needs skill
    { id:'3', label:'Blessing' },
    { id:'4', label:'Defense' },
    { id:'5', label:'Speed' },
    { id:'7', label:'Devastation' },
    { id:'8', label:'Clarity' },
    { id:'6', label:'Endurance' },
  ];
  const ALL_SKILLS = GROUPS.flatMap(g => g.skills).map(s => ({key:s.key,label:s.label}));
  const subBody = $('#subTable tbody');

  function addSubRow(defaults={type:'2',skill:'',tier:1}){
    const tr=document.createElement('tr');

    const typeSel=document.createElement('select'); typeSel.className='input';
    SUB_TYPES.forEach(t=>{ const o=document.createElement('option'); o.value=t.id; o.textContent=t.label; if(String(defaults.type)===t.id) o.selected=true; typeSel.appendChild(o); });

    const skillSel=document.createElement('select'); skillSel.className='input';
    const o0=document.createElement('option'); o0.value=''; o0.textContent='—'; skillSel.appendChild(o0);
    ALL_SKILLS.forEach(s=>{ const o=document.createElement('option'); o.value=s.key; o.textContent=s.label; if(defaults.skill===s.key) o.selected=true; skillSel.appendChild(o); });

    const tierInp=document.createElement('input'); tierInp.type='number'; tierInp.min='0'; tierInp.max='4'; tierInp.value=String(defaults.tier||1); tierInp.className='input xs';

    const slotsCell=document.createElement('td'); slotsCell.className='right mono'; slotsCell.textContent=String(defaults.tier||1);

    const delBtn=document.createElement('button'); delBtn.className='btn ghost'; delBtn.textContent='Remove';
    delBtn.addEventListener('click',()=>{ tr.remove(); recompute(); triggerSave(); });

    function toggleSkill(){ const ex=(typeSel.value==='1'); skillSel.disabled=!ex; skillSel.style.opacity=ex?1:.5; }
    toggleSkill();

    typeSel.addEventListener('change',()=>{ toggleSkill(); recompute(); triggerSave(); });
    skillSel.addEventListener('change',()=>{ recompute(); triggerSave(); });
    tierInp.addEventListener('input',()=>{ slotsCell.textContent=String(num(tierInp.value)); recompute(); triggerSave(); });

    const td1=document.createElement('td'); td1.appendChild(typeSel);
    const td2=document.createElement('td'); td2.appendChild(skillSel);
    const td3=document.createElement('td'); td3.appendChild(tierInp);
    const td5=document.createElement('td'); td5.appendChild(delBtn);

    tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(slotsCell); tr.appendChild(td5);
    tr._refs={typeSel,skillSel,tierInp,slotsCell};
    subBody.appendChild(tr);
  }
  if(!subBody.children.length) addSubRow();

  // ---------- Recompute ----------
  const modScore  = s => Math.floor(s/2 - 5);
  const scoreFrom = inv => 4 + inv;

  function readLevel(){
    const lvl=num($('#c_level')?.value||1);
    const xp =num($('#c_xp')?.value||0);
    return Math.max(1,lvl||1);
  }

  function idIvFromBV(bv){
    if (bv <= 0) return ['—','—'];
    if (bv <= 7)  return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10', 5];
    return ['1d12', 6];
  }

  function recompute(){
    const lvl = readLevel();

    // Characteristics totals + milestones
    const charMilestone = {};
    GROUPS.forEach(g=>{
      const inv=num($(`[data-c-invest="${g.investKey}"]`).value||0);
      const score=scoreFrom(inv);
      const ms=modScore(score);
      charMilestone[g.key]=ms;
      $(`[data-c-total="${g.key}"]`).textContent = String(score);
      $(`[data-c-milestone="${g.key}"]`).textContent = String(ms);
    });

    // Sublimation Excellence map
    const exMap={}; let subSlots=0;
    Array.from(subBody.children).forEach(tr=>{
      const {typeSel,skillSel,tierInp}=tr._refs;
      const tier=Math.max(0,num(tierInp.value||0));
      subSlots += tier;
      if(typeSel.value==='1' && skillSel.value){
        exMap[skillSel.value]=(exMap[skillSel.value]||0)+tier;
      }
    });
    $('#sub_used').textContent = String(subSlots);

    // Skills base: invested + Excellence(min(invested, tiers)) + characteristic milestone
    GROUPS.forEach(g=>{
      g.skills.forEach(s=>{
        const inv=num($(`[data-s-invest="${s.key}"]`).value||0);
        const ex = Math.min(inv, exMap[s.key]||0);
        const base = inv + ex + (charMilestone[g.key]||0);
        $(`[data-s-base="${s.key}"]`).textContent = String(base);
      });
    });

    // Simple caps/counters (front-end guidance; backend is truth)
    const skill_cap = (lvl >= 50 ? 8 : lvl >= 40 ? 7 : lvl >= 30 ? 6 : lvl >= 20 ? 5 : lvl >= 10 ? 4 : 3);
    const cp_max = 22 + Math.floor((lvl-1)/9)*3;
    const sp_max = 40 + (lvl-1)*2;
    const cp_used = GROUPS.reduce((a,g)=>a+num($(`[data-c-invest="${g.investKey}"]`).value||0),0);
    const sp_used = GROUPS.reduce((a,g)=>a+g.skills.reduce((aa,s)=>aa+num($(`[data-s-invest="${s.key}"]`).value||0),0),0);
    $('#skill_cap').textContent=String(skill_cap);
    $('#char_cap').textContent='10';
    $('#cp_max').textContent=String(cp_max);
    $('#sp_max').textContent=String(sp_max);
    $('#cp_used').textContent=String(cp_used);
    $('#sp_used').textContent=String(sp_used);

    // Derived badges (quick client mirrors)
    const mile_ref = Math.max(charMilestone.ref||0,0);
    const mile_dex = Math.max(charMilestone.dex||0,0);
    const mile_mag = Math.max(charMilestone.mag||0,0);
    const mo = 4 + mile_ref + mile_dex + (sumSubType('5')); // +Speed tiers
    $('#k_mo').textContent = String(mo);
    $('#k_init').textContent = String(mo + Math.max(charMilestone.ref||0,0));
    $('#k_et').textContent = String(1 + Math.floor((lvl-1)/9) + mile_mag);
    $('#k_cdc').textContent = String(6 + Math.floor(lvl/10) + sumSubType('7'));

    // Intensities quick math
    const magic_mod = charMilestone.mag||0;
    INTENSITIES.forEach(nm=>{
      const inv=num($(`[data-i-invest="${nm}"]`).value||0);
      const base=(inv>0? inv + magic_mod : 0);
      const [ID,IV]=idIvFromBV(base);
      $(`[data-i-mod="${nm}"]`).textContent = String(magic_mod);
      $(`[data-i-base="${nm}"]`).textContent = String(base);
      $(`[data-i-id="${nm}"]`).textContent = String(ID);
      $(`[data-i-iv="${nm}"]`).textContent = String(IV||'—');
      $(`[data-i-rw="${nm}"]`).textContent = '0';
    });

    // Bars keep width coherent if numbers present
    function setBar(curSel,maxSel,barSel){
      const cur=num($(curSel)?.textContent||0);
      const max=num($(maxSel)?.textContent||0);
      const pct=max>0?Math.round((cur/max)*100):0;
      $(barSel).style.width=`${pct}%`;
    }
    setBar('#hp_cur','#hp_max','#hp_bar');
    setBar('#sp_cur','#sp_max','#sp_bar');
    setBar('#en_cur','#en_max','#en_bar');
    setBar('#fo_cur','#fo_max','#fo_bar');
    setBar('#tx_cur','#tx_max','#tx_bar');
    setBar('#enc_cur','#enc_max','#enc_bar');
  }

  function sumSubType(code){
    return Array.from(subBody.children).reduce((acc,tr)=>{
      const {typeSel,tierInp}=tr._refs; return acc + (typeSel.value===code? Math.max(0,num(tierInp.value||0)):0);
    },0);
  }

  // ---------- API ----------
  const API = {
    async create(payload){
      const r=await fetch('/characters',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify(payload)});
      if(!r.ok) throw new Error(await r.text()); return r.json();
    },
    async get(id){
      const r=await fetch(`/characters/${encodeURIComponent(id)}`,{credentials:'include'});
      if(!r.ok) throw new Error(await r.text()); return r.json();
    },
    async update(id,payload){
      const r=await fetch(`/characters/${encodeURIComponent(id)}`,{method:'PUT',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify(payload)});
      if(!r.ok) throw new Error(await r.text()); return r.json();
    }
  };

  // ---------- Collect payload ----------
  function collectPayload(){
    const payload={
      name: ($('#c_name')?.value||'').trim(),
      img:  ($('#avatarUrl')?.value||'').trim(),
      xp_total: num($('#c_xp')?.value||0),
      level_manual: ($('#c_level')?.value===''? null : num($('#c_level')?.value)),
      characteristics:{}, skills:{}, sublimations:[],
      bio:{
        height:($('#p_height')?.value||'').trim(),
        weight:($('#p_weight')?.value||'').trim(),
        birthday:($('#p_bday')?.value||'').trim(),
        backstory:($('#p_backstory')?.value||'').trim(),
        notes:($('#p_notes')?.value||'').trim(),
      }
    };
    GROUPS.forEach(g=>{
      payload.characteristics[g.investKey]=num($(`[data-c-invest="${g.investKey}"]`)?.value||0);
      g.skills.forEach(s=> payload.skills[s.key]=num($(`[data-s-invest="${s.key}"]`)?.value||0) );
    });
    INTENSITIES.forEach(nm=>{
      const v=num($(`[data-i-invest="${nm}"]`)?.value||0);
      payload.skills[nm.toLowerCase()]=v;
    });
    Array.from(subBody.children).forEach(tr=>{
      const {typeSel,skillSel,tierInp}=tr._refs;
      const m = { '1':'Excellence','2':'Lethality','3':'Blessing','4':'Defense','5':'Speed','6':'Endurance','7':'Devastation','8':'Clarity' };
      payload.sublimations.push({
        type: m[typeSel.value]||'Lethality',
        tier: num(tierInp.value||0),
        skill: (typeSel.value==='1' && skillSel.value) ? skillSel.value : null
      });
    });
    return payload;
  }

  // ---------- Apply computed back from server ----------
  function applyComputed(resp){
    const c=resp?.computed; if(!c) return;
    $('#k_mo').textContent   = String(c.derived.movement);
    $('#k_init').textContent = String(c.derived.initiative);
    $('#k_et').textContent   = String(c.derived.et);
    $('#k_cdc').textContent  = String(c.derived.condition_dc);

    function setRes(curSel,maxSel,barSel,cur,max){
      $(curSel).textContent=String(cur); $(maxSel).textContent=String(max);
      $(barSel).style.width = max>0?`${Math.round((cur/max)*100)}%`:'0%';
    }
    setRes('#hp_cur','#hp_max','#hp_bar', c.derived.hp_current ?? c.derived.hp_max, c.derived.hp_max);
    setRes('#sp_cur','#sp_max','#sp_bar', c.derived.sp_current ?? c.derived.sp_max, c.derived.sp_max);
    setRes('#en_cur','#en_max','#en_bar', c.derived.en_current ?? c.derived.en_max, c.derived.en_max);
    setRes('#fo_cur','#fo_max','#fo_bar', c.derived.fo_current ?? c.derived.fo_max, c.derived.fo_max);
    setRes('#tx_cur','#tx_max','#tx_bar', c.derived.tx_current ?? c.derived.tx_max, c.derived.tx_max);
    setRes('#enc_cur','#enc_max','#enc_bar', c.derived.enc_current ?? c.derived.enc_max, c.derived.enc_max);

    // Slots
    $('#sub_max').textContent  = String(c.sublimations.slots_max);
    $('#sub_used').textContent = String(c.sublimations.slots_used);
  }

  // ---------- Autosave ----------
  const cidInput = $('#c_id');
  let saveTimer=null;
  function triggerSave(){ if(saveTimer) clearTimeout(saveTimer); saveTimer=setTimeout(saveNow, 500); }

  async function saveNow(){
    try{
      setStatus('Saving…');
      const payload=collectPayload();
      const id=cidInput.value?.trim();
      const resp=id? await API.update(id,payload) : await API.create(payload);
      const newId=id || resp?.character?.id;
      if(newId && !cidInput.value){
        cidInput.value=newId;
        const u=new URL(location.href); u.searchParams.set('id',newId); history.replaceState(null,'',u.toString());
      }
      applyComputed(resp);
      setStatus('Saved','good');
    }catch(e){
      console.error(e);
      setStatus('Error','danger');
    }
  }

  // ---------- Bindings ----------
  // generic inputs
  ['#c_name','#c_level','#c_xp','#avatarUrl','#p_height','#p_weight','#p_bday','#p_backstory','#p_notes']
    .forEach(sel=> $(sel)?.addEventListener('input', ()=>{ if(sel==='#avatarUrl'){ const u=$('#avatarUrl').value||'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg'; $('#charAvatar').src=u; } recompute(); triggerSave(); }));

  // char + skills + intensities
  $$('#charSkillContainer input').forEach(el=> el.addEventListener('input', ()=>{ recompute(); triggerSave(); }));
  $$('#intensityTable [data-i-invest]').forEach(el=> el.addEventListener('input', ()=>{ recompute(); triggerSave(); }));

  // add sub row
  $('#btnAddSub')?.addEventListener('click', ()=> addSubRow({type:'2',tier:1}) );

  // ---------- Load (if ?id=) ----------
  (async function init(){
    setStatus('Ready');
    const qid=new URLSearchParams(location.search).get('id');
    if(qid){
      try{
        setStatus('Loading…');
        const resp=await API.get(qid);
        const doc=resp.character||{};
        cidInput.value=doc.id||'';
        $('#c_name').value=doc.name||'';
        $('#avatarUrl').value=doc.img||'';
        $('#charAvatar').src=doc.img||'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
        $('#c_xp').value=Number(doc.xp_total||0);
        $('#c_level').value=(doc.level_manual ?? 1);

        // characteristics
        const ch=doc.characteristics||{};
        GROUPS.forEach(g=>{ const el=$(`[data-c-invest="${g.investKey}"]`); if(el) el.value=ch[g.investKey]??0; });

        // skills
        const sk=doc.skills||{};
        GROUPS.forEach(g=> g.skills.forEach(s=>{ const el=$(`[data-s-invest="${s.key}"]`); if(el) el.value=sk[s.key]??0; }));
        INTENSITIES.forEach(nm=>{ const el=$(`[data-i-invest="${nm}"]`); if(el) el.value=sk[nm.toLowerCase()]??0; });

        // sublimations
        subBody.innerHTML='';
        (doc.sublimations||[]).forEach(s=>{
          const map={Excellence:'1',Lethality:'2',Blessing:'3',Defense:'4',Speed:'5',Endurance:'6',Devastation:'7',Clarity:'8'};
          addSubRow({type:map[s.type]||'2', skill:s.skill||'', tier:s.tier||1});
        });

        applyComputed(resp);
        setStatus('Loaded','good');
      }catch(e){ console.warn(e); setStatus('Load failed','danger'); }
    }
    recompute();
  })();
})();