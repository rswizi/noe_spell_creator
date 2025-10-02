(() => {
  const API_BASE = "";
  const $ = (s, el=document) => el.querySelector(s);
  const $$ = (s, el=document) => Array.from(el.querySelectorAll(s));

  // ---- helpers
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const milestoneFromTotal = total => Math.floor((Number(total) - 10) / 2);
  const tens = lvl => Math.floor(lvl/10);
  const levelFromXP = xp => Math.min(Math.floor((-1 + Math.sqrt(1 + 8*(xp/100)))/2)+1, 100);
  const idIvFromBV = bv => (bv<=0?['—','—']:bv<=7?['1d4',2]:bv<=11?['1d6',3]:bv<=15?['1d8',4]:bv<=17?['1d10',5]:['1d12',6]);

  function replaceOnType(inp){
    inp.addEventListener('focus', ()=>inp.select());
    inp.addEventListener('keydown', ()=>{ if(!inp._touched){ inp.select(); inp._touched=true; } });
  }

  // Tabs
  $$('.tab').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      $$('.tab').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      const key = btn.dataset.tab;
      $$('.tabpan').forEach(p=>p.classList.remove('active'));
      $(`#tab-${key}`).classList.add('active');
    });
  });

  // Avatar
  const avatarUrl = $('#avatarUrl');
  const charAvatar = $('#charAvatar');
  if (avatarUrl){
    avatarUrl.addEventListener('input', ()=>{ charAvatar.src = avatarUrl.value || charAvatar.src; queueSave(); });
  }

  // Data maps
  const GROUPS = [
    { key:'ref', label:'Reflex (REF)',    investKey:'reflexp',    skills:[
      { key:'technicity',  label:'Technicity' },
      { key:'dodge',       label:'Dodge' },
      { key:'tempo',       label:'Tempo' },
      { key:'reactivity',  label:'Reactivity' },
    ]},
    { key:'dex', label:'Dexterity (DEX)', investKey:'dexterityp', skills:[
      { key:'accuracy',    label:'Accuracy' },
      { key:'evasion',     label:'Evasion' },
      { key:'stealth',     label:'Stealth' },
      { key:'acrobatics',  label:'Acrobatics' },
    ]},
    { key:'bod', label:'Body (BOD)',      investKey:'bodyp',      skills:[
      { key:'brutality',   label:'Brutality' },
      { key:'blocking',    label:'Blocking' },
      { key:'resistance',  label:'Resistance' },
      { key:'athletics',   label:'Athletics' },
    ]},
    { key:'wil', label:'Willpower (WIL)', investKey:'willpowerp', skills:[
      { key:'intimidation',label:'Intimidation' },
      { key:'spirit',      label:'Spirit' },
      { key:'instinct',    label:'Instinct' },
      { key:'absorption',  label:'Absorption' },
    ]},
    { key:'mag', label:'Magic (MAG)',     investKey:'magicp',     skills:[
      { key:'aura',        label:'Aura' },
      { key:'incantation', label:'Incantation' },
      { key:'enchantment', label:'Enchantment' },
      { key:'restoration', label:'Restoration' },
      { key:'potential',   label:'Potential' },
    ]},
    { key:'pre', label:'Presence (PRE)',  investKey:'presencep',  skills:[
      { key:'taming',      label:'Taming' },
      { key:'charm',       label:'Charm' },
      { key:'charisma',    label:'Charisma' },
      { key:'deception',   label:'Deception' },
      { key:'persuasion',  label:'Persuasion' },
    ]},
    { key:'wis', label:'Wisdom (WIS)',    investKey:'wisdomp',    skills:[
      { key:'survival',    label:'Survival' },
      { key:'education',   label:'Education' },
      { key:'perception',  label:'Perception' },
      { key:'psychology',  label:'Psychology' },
      { key:'investigation',label:'Investigation' },
    ]},
    { key:'tec', label:'Tech (TEC)',      investKey:'techp',      skills:[
      { key:'crafting',    label:'Crafting' },
      { key:'soh',         label:'Sleight of hand' },
      { key:'alchemy',     label:'Alchemy' },
      { key:'medecine',    label:'Medicine' },
      { key:'engineering', label:'Engineering' },
    ]},
  ];
  const INTENSITIES = ['Fire','Water','Earth','Wind','Lightning','Moon','Sun','Ki'];
  const SUB_TYPES = [
    { id:'2', label:'Lethality' },
    { id:'1', label:'Excellence' }, // per-tier skill bonus, capped by invested
    { id:'3', label:'Blessing' },
    { id:'4', label:'Defense' },
    { id:'5', label:'Speed' },
    { id:'7', label:'Devastation' },
    { id:'8', label:'Clarity' },
    { id:'6', label:'Endurance' },
  ];
  const ALL_SKILLS = GROUPS.flatMap(g => g.skills.map(s => ({...s, group:g.key})));

  // ---------- Build Characteristics & Skills with hidden mod panels
  const container = $('#charSkillContainer'); container.innerHTML = '';
  GROUPS.forEach(g=>{
    const card = document.createElement('div');
    card.className = 'char-card';
    const head = document.createElement('div');
    head.className = 'rowline head';
    head.innerHTML = `
      <div>${g.label}</div>
      <div class="mini">Invested</div>
      <div class="mini">[ Total | Milestone ]</div>
    `;
    card.appendChild(head);

    // Characteristic row
    const crow = document.createElement('div');
    crow.className = 'rowline';
    crow.innerHTML = `
      <div class="toggle" data-toggle="c-${g.key}"><i></i><span class="muted">Characteristic</span></div>
      <div><input class="input" type="number" min="0" max="16" value="0" data-c-invest="${g.investKey}"></div>
      <div><span class="mono" data-c-total="${g.key}">4</span> | <span class="mono" data-c-mile="${g.key}">-3</span></div>
    `;
    card.appendChild(crow);

    // Characteristic mod-source panel
    const cpanel = document.createElement('div');
    cpanel.className = 'mod-panel';
    cpanel.dataset.cMods = g.key;
    cpanel.innerHTML = `
      <table>
        <thead><tr><th>Source</th><th class="right">Modifier</th></tr></thead>
        <tbody data-c-modsrc="${g.key}"><tr><td class="muted">No modifiers yet</td><td class="right">0</td></tr></tbody>
      </table>
    `;
    card.appendChild(cpanel);

    // Subhead
    const subhead = document.createElement('div');
    subhead.className = 'rowline subhead';
    subhead.innerHTML = `<div>—</div><div>Invested</div><div>Base Value</div>`;
    card.appendChild(subhead);

    // Skills
    g.skills.forEach(s=>{
      const srow = document.createElement('div');
      srow.className = 'rowline';
      srow.innerHTML = `
        <div class="toggle" data-toggle="s-${s.key}"><i></i>— ${s.label}</div>
        <div><input class="input" type="number" min="0" max="8" value="0" data-s-invest="${s.key}" data-s-group="${g.key}"></div>
        <div><span class="mono" data-s-base="${s.key}">0</span><span class="small-hint" data-s-bonus-note="${s.key}">(bonus 0)</span></div>
      `;
      card.appendChild(srow);

      const spanel = document.createElement('div');
      spanel.className = 'mod-panel';
      spanel.dataset.sMods = s.key;
      spanel.innerHTML = `
        <table>
          <thead><tr><th>Source</th><th class="right">Modifier</th></tr></thead>
          <tbody data-s-modsrc="${s.key}"><tr><td class="muted">No modifiers yet</td><td class="right">0</td></tr></tbody>
        </table>
      `;
      card.appendChild(spanel);
    });

    container.appendChild(card);
  });

  // Toggle handlers (open/close)
  container.addEventListener('click', (e)=>{
    const t = e.target.closest('.toggle'); if(!t) return;
    const id = t.dataset.toggle;
    let panel = null;
    if (id?.startsWith('c-')){
      const key = id.slice(2);
      panel = container.querySelector(`.mod-panel[data-c-mods="${key}"]`);
    } else if (id?.startsWith('s-')){
      const key = id.slice(2);
      panel = container.querySelector(`.mod-panel[data-s-mods="${key}"]`);
    }
    if (panel){
      const open = !panel.classList.contains('open');
      container.querySelectorAll('.toggle').forEach(el=>el.classList.remove('open'));
      container.querySelectorAll('.mod-panel').forEach(p=>p.classList.remove('open'));
      if (open){ panel.classList.add('open'); t.classList.add('open'); }
    }
  });

  // ---------- Intensities
  const tbodyInt = $('#intensityTable tbody'); if (tbodyInt){ tbodyInt.innerHTML = ''; }
  INTENSITIES.forEach(nm=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${nm}</td>
      <td><input class="input" type="number" min="0" max="8" value="0" data-i-invest="${nm}"></td>
      <td class="mono" data-i-base="${nm}">0</td>
      <td class="mono" data-i-id="${nm}">—</td>
      <td class="mono" data-i-iv="${nm}">—</td>
      <td class="mono right" data-i-rw="${nm}">0</td>
    `;
    tbodyInt.appendChild(tr);
  });

  // ---------- Sublimations
  const subBody = $('#subTable tbody');
  const btnAddSub = $('#btnAddSub');
  function addSubRow(def={type:'1',skill:'accuracy',tier:2}){
    const tr = document.createElement('tr');
    const typeSel = document.createElement('select');
    SUB_TYPES.forEach(t=>{ const o=document.createElement('option'); o.value=t.id;o.textContent=t.label; if(def.type===t.id) o.selected=true; typeSel.appendChild(o); });
    const skillSel = document.createElement('select');
    const blank = document.createElement('option'); blank.value=''; blank.textContent='—'; skillSel.appendChild(blank);
    ALL_SKILLS.forEach(s=>{ const o=document.createElement('option'); o.value=s.key; o.textContent=s.label; if(def.skill===s.key) o.selected=true; skillSel.appendChild(o); });
    const tierInp = document.createElement('input'); tierInp.type='number'; tierInp.min='0'; tierInp.max='4'; tierInp.value=def.tier;
    const slotsCell = document.createElement('td'); slotsCell.className='right mono'; slotsCell.textContent=String(def.tier);
    const delBtn = document.createElement('button'); delBtn.className='btn ghost'; delBtn.textContent='Remove';
    delBtn.addEventListener('click', ()=>{ tr.remove(); recompute(); queueSave(); });

    function toggleSkill(){
      const needs = typeSel.value==='1'; // Excellence
      skillSel.disabled = !needs; skillSel.style.opacity = needs?1:.5;
    }
    typeSel.addEventListener('change', ()=>{ toggleSkill(); recompute(); queueSave(); });
    skillSel.addEventListener('change', ()=>{ recompute(); queueSave(); });
    tierInp.addEventListener('input', ()=>{ slotsCell.textContent=tierInp.value; recompute(); queueSave(); });

    const td1=document.createElement('td'); td1.appendChild(typeSel);
    const td2=document.createElement('td'); td2.appendChild(skillSel);
    const td3=document.createElement('td'); td3.appendChild(tierInp);
    const td5=document.createElement('td'); td5.appendChild(delBtn);

    tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(slotsCell); tr.appendChild(td5);
    tr._refs = { typeSel, skillSel, tierInp, slotsCell };
    subBody.appendChild(tr);
    toggleSkill();
  }
  btnAddSub?.addEventListener('click', ()=>{ addSubRow({type:'2', skill:'', tier:1}); recompute(); queueSave(); });
  addSubRow(); // seed one Excellence row

  // ---- small utils
  function setTxt(sel, v){ const el=$(sel); if(el) el.textContent=String(v); }
  function setResource(curSel, maxSel, barSel, cur, max){
    setTxt(maxSel, max);
    cur = clamp(cur, 0, Math.max(0,max));
    setTxt(curSel, cur);
    const pct = max>0 ? Math.round((cur/max)*100) : 0;
    $(barSel).style.width = `${pct}%`;
  }
  function readLevel(){
    const lvlInp = $('#c_level'), xpInp = $('#c_xp');
    let lvl = Number(lvlInp.value||1);
    if (!lvl || lvl<1) lvl = levelFromXP(Number(xpInp.value||0));
    return clamp(lvl,1,100);
  }
  function sumSubType(code){
    return Array.from(subBody.children).reduce((acc,tr)=>{
      const { typeSel, tierInp } = tr._refs || {};
      return acc + ((typeSel && typeSel.value===code) ? Math.max(0,Number(tierInp.value||0)) : 0);
    },0);
  }

  // ---------- recompute
  function recompute(){
    const lvl = readLevel(); const lvlUp = Math.max(lvl-1,0);
    $('#c_level').value = String(lvl);

    // Excellence tiers per skill
    const exTiers = {};
    let subUsed = 0;
    Array.from(subBody.children).forEach(tr=>{
      const { typeSel, skillSel, tierInp, slotsCell } = tr._refs || {};
      const t = Math.max(0,Number(tierInp.value||0));
      subUsed += t; slotsCell.textContent = String(t);
      if (typeSel.value==='1' && skillSel.value){
        exTiers[skillSel.value] = (exTiers[skillSel.value]||0) + t;
      }
    });

    // Characteristics
    const cInv={}, cMile={};
    GROUPS.forEach(g=>{
      const inv = Number($(`[data-c-invest="${g.investKey}"]`).value||0);
      cInv[g.key]=inv;
      const total = 4 + inv;      // no manual char modifiers yet
      const mile  = milestoneFromTotal(total);
      cMile[g.key]=mile;
      $(`[data-c-total="${g.key}"]`).textContent = String(total);
      $(`[data-c-mile="${g.key}"]`).textContent  = String(mile);

      // Char mod sources (empty for now; ready for future)
      const tbody = $(`[data-c-modsrc="${g.key}"]`);
      tbody.innerHTML = `<tr><td class="muted">No modifiers yet</td><td class="right">0</td></tr>`;
    });

    // Skills
    const sInv={};
    GROUPS.forEach(g=>{
      g.skills.forEach(s=>{
        const inv = Number($(`[data-s-invest="${s.key}"]`).value||0);
        sInv[s.key]=inv;
        const tiers = exTiers[s.key]||0;
        const exBonus = Math.min(inv, tiers); // excellence capped by invested
        const base  = inv + exBonus + (cMile[g.key]||0);
        $(`[data-s-base="${s.key}"]`).textContent = String(base);
        $(`[data-s-bonus-note="${s.key}"]`).textContent = `(bonus ${exBonus})`;

        // Populate skill mod panel (sources)
        const tbody = $(`[data-s-modsrc="${s.key}"]`);
        if (exBonus>0){
          tbody.innerHTML = `
            <tr><td>Sublimation • Excellence (Tier ${tiers})</td><td class="right">+${exBonus}</td></tr>
          `;
        } else {
          tbody.innerHTML = `<tr><td class="muted">No modifiers yet</td><td class="right">0</td></tr>`;
        }
      });
    });

    // Totals & caps
    const cp_used = Object.values(cInv).reduce((a,b)=>a+b,0);
    const cp_max  = 22 + Math.floor(lvlUp/9)*3;
    const sp_used = Object.values(sInv).reduce((a,b)=>a+b,0);
    const sp_max  = 40 + lvlUp*2;
    const skill_cap = (lvl>=50?8:lvl>=40?7:lvl>=30?6:lvl>=20?5:lvl>=10?4:3);
    const char_cap  = (lvl>=55?10:lvl>=46?9:lvl>=37?8:lvl>=28?7:lvl>=19?6:lvl>=10?5:4);
    setTxt('#cp_used', cp_used); setTxt('#cp_max', cp_max);
    setTxt('#sp_used', sp_used); setTxt('#sp_max', sp_max);
    setTxt('#skill_cap', skill_cap); setTxt('#char_cap', char_cap);

    // Sublimation slots/tier cap
    const sub_max = (Math.max(cMile.pre||0,0)*2) + Math.floor(lvl/10);
    const tier_cap = Math.ceil(lvl/25);
    setTxt('#sub_used', subUsed); setTxt('#sub_max', sub_max); setTxt('#sub_tier', tier_cap);

    // Resources (positive milestones only)
    const pos = k => Math.max(cMile[k]||0,0);
    const hp_max = 100 + lvlUp + 12*pos('bod') + 6*pos('wil') + 12*sumSubType('4');
    const en_max = 5 + Math.floor(lvlUp/5) + pos('wil') + 2*pos('mag') + 2*sumSubType('6');
    const fo_max = 2 + Math.floor(lvlUp/5) + pos('wil') + pos('wis') + pos('pre') + sumSubType('8');
    const mo     = 4 + pos('dex') + pos('ref') + sumSubType('5');
    const et     = 1 + Math.floor(lvlUp/9) + pos('mag');
    const cdc    = 6 + tens(lvl) + sumSubType('7');

    const resBV  = Number($('[data-s-base="resistance"]').textContent||0);
    const alcBV  = Number($('[data-s-base="alchemy"]').textContent||0);
    const tx_max = resBV + alcBV;
    const athBV  = Number($('[data-s-base="athletics"]').textContent||0);
    const spiBV  = Number($('[data-s-base="spirit"]').textContent||0);
    const enc_max= 10 + athBV + spiBV;

    setResource('#hp_cur','#hp_max','#hp_bar',hp_max,hp_max);
    setResource('#sp_cur','#sp_max','#sp_bar',0,Math.floor(hp_max/10));
    setResource('#en_cur','#en_max','#en_bar',Math.min(5,en_max),en_max);
    setResource('#fo_cur','#fo_max','#fo_bar',Math.min(2,fo_max),fo_max);
    setResource('#tx_cur','#tx_max','#tx_bar',0,tx_max);
    setResource('#enc_cur','#enc_max','#enc_bar',0,enc_max);

    setTxt('#k_mo', mo);
    setTxt('#k_init', mo + pos('ref'));
    setTxt('#k_et', et);
    setTxt('#k_cdc', cdc);

    // Intensities: base = invested + MAG milestone (if invested > 0)
    const magMile = cMile.mag || 0;
    INTENSITIES.forEach(nm=>{
      const inv = Number($(`[data-i-invest="${nm}"]`).value||0);
      const base = inv>0 ? inv + magMile : 0;
      const [ID,IV] = idIvFromBV(base);
      $(`[data-i-base="${nm}"]`).textContent = String(base);
      $(`[data-i-id="${nm}"]`).textContent = String(ID);
      $(`[data-i-iv="${nm}"]`).textContent = String(IV||'—');
      $(`[data-i-rw="${nm}"]`).textContent = "0";
    });

    // visual caps
    GROUPS.forEach(g=>g.skills.forEach(s=>{
      const inp = $(`[data-s-invest="${s.key}"]`);
      const val = Number(inp.value||0);
      inp.style.borderColor = (val>skill_cap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    }));
    $('#sp_used').classList.toggle('danger', Number($('#sp_used').textContent)>sp_max);
    $('#cp_used').classList.toggle('danger', Number($('#cp_used').textContent)>cp_max);
    Array.from(subBody.children).forEach(tr=>{
      const t = Number(tr._refs?.tierInp.value||0);
      tr._refs.tierInp.style.borderColor = (t>tier_cap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
  }

  // ---- save on change
  let saveTimer=null;
  function queueSave(){ clearTimeout(saveTimer); saveTimer=setTimeout(saveDraft,300); }
  function collectPayload(){
    const lvl = readLevel();
    const payload = {
      name: ($('#c_name').value||'').trim(),
      level: lvl,
      xp: Number($('#c_xp').value||0),
      avatar: $('#avatarUrl')?.value || '',
      invested_characteristics: {},
      invested_skills: {},
      intensities_invested: {},
      sublimations: Array.from($('#subTable tbody').children).map(tr=>{
        const { typeSel, skillSel, tierInp } = tr._refs || {};
        return { type:typeSel.value, skill:(skillSel.value||null), tier:Number(tierInp.value||0) };
      })
    };
    GROUPS.forEach(g=>{ payload.invested_characteristics[g.key] = Number($(`[data-c-invest="${g.investKey}"]`).value||0); });
    GROUPS.forEach(g=>g.skills.forEach(s=>{ payload.invested_skills[s.key] = Number($(`[data-s-invest="${s.key}"]`).value||0); }));
    INTENSITIES.forEach(nm=>{ payload.intensities_invested[nm] = Number($(`[data-i-invest="${nm}"]`).value||0); });
    return payload;
  }
  async function saveDraft(){ try{
    await fetch(`${API_BASE}/characters/save`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collectPayload())});
  }catch(e){ console.warn('save failed',e); } }

  // ---- events
  ['#c_level','#c_xp','#c_name','#avatarUrl'].forEach(sel=>{
    const el=$(sel); if(!el) return;
    replaceOnType(el);
    el.addEventListener('input', ()=>{ recompute(); queueSave(); });
  });
  // numeric inputs
  const attachNumeric = () => {
    $$('#charSkillContainer input, #intensityTable input').forEach(inp=>{
      replaceOnType(inp);
      inp.addEventListener('input', ()=>{ recompute(); queueSave(); });
    });
  };
  attachNumeric();

  // initial compute
  recompute();
})();