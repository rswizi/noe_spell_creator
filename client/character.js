(() => {
  // ------------------------------
  // Config
  // ------------------------------
  const API_BASE = ""; // change to "/api" if your backend serves under /api

  // ------------------------------
  // DOM helpers
  // ------------------------------
  const $  = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const setTxt = (sel, v) => { const n=$(sel); if(n) n.textContent=String(v); };
  const num = sel => Number($(sel)?.value || 0);

  // ------------------------------
  // Math helpers (declared as function for hoisting)
  // ------------------------------
  function modFromScore(score){ return Math.floor(score/2 - 5); }
  function scoreFromInvest(invest){ return 4 + invest; } // base 4 + invested
  function levelFromXP(xp){
    const k = Math.floor((-1 + Math.sqrt(1 + 8*(xp/100)))/2);
    return Math.min(k+1, 100);
  }
  function idIvFromBV(bv){
    if (bv <= 0) return ['—','—'];
    if (bv <= 7)  return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10', 5];
    return ['1d12', 6];
  }
  function rwFor(){ return 0; } // placeholder until you wire the full grid

  // ------------------------------
  // Data maps
  // ------------------------------
  const CHAR_MAP = [
    { key:'ref', label:'Reflex (REF)', investKey:'reflexp', skills:[
      { key:'technicity', label:'Technicity' },
      { key:'dodge', label:'Dodge' },
      { key:'tempo', label:'Tempo' },
      { key:'reactivity', label:'Reactivity' },
    ]},
    { key:'dex', label:'Dexterity (DEX)', investKey:'dexterityp', skills:[
      { key:'accuracy', label:'Accuracy' },
      { key:'evasion', label:'Evasion' },
      { key:'stealth', label:'Stealth' },
      { key:'acrobatics', label:'Acrobatics' },
    ]},
    { key:'bod', label:'Body (BOD)', investKey:'bodyp', skills:[
      { key:'brutality', label:'Brutality' },
      { key:'blocking', label:'Blocking' },
      { key:'resistance', label:'Resistance' },
      { key:'athletics', label:'Athletics' },
    ]},
    { key:'wil', label:'Willpower (WIL)', investKey:'willpowerp', skills:[
      { key:'intimidation', label:'Intimidation' },
      { key:'spirit', label:'Spirit' },
      { key:'instinct', label:'Instinct' },
      { key:'absorption', label:'Absorption' },
    ]},
    { key:'mag', label:'Magic (MAG)', investKey:'magicp', skills:[
      { key:'aura', label:'Aura' },
      { key:'incantation', label:'Incantation' },
      { key:'enchantment', label:'Enchantment' },
      { key:'restoration', label:'Restoration' },
      { key:'potential', label:'Potential' },
    ]},
    { key:'pre', label:'Presence (PRE)', investKey:'presencep', skills:[
      { key:'taming', label:'Taming' },
      { key:'charm', label:'Charm' },
      { key:'charisma', label:'Charisma' },
      { key:'deception', label:'Deception' },
      { key:'persuasion', label:'Persuasion' },
    ]},
    { key:'wis', label:'Wisdom (WIS)', investKey:'wisdomp', skills:[
      { key:'survival', label:'Survival' },
      { key:'education', label:'Education' },
      { key:'perception', label:'Perception' },
      { key:'psychology', label:'Psychology' },
      { key:'investigation', label:'Investigation' },
    ]},
    { key:'tec', label:'Tech (TEC)', investKey:'techp', skills:[
      { key:'crafting', label:'Crafting' },
      { key:'soh', label:'Sleight of hand' },
      { key:'alchemy', label:'Alchemy' },
      { key:'medecine', label:'Medicine' },
      { key:'engineering', label:'Engineering' },
    ]},
  ];
  const INTENSITIES = ['Fire','Water','Earth','Wind','Lightning','Moon','Sun','Ki'];

  // ------------------------------
  // Initial UI build (tabs + avatar)
  // ------------------------------
  $$('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const key = btn.dataset.tab;
      $$('.tabpan').forEach(p => p.classList.remove('active'));
      $(`#tab-${key}`).classList.add('active');
    });
  });

  const avatarUrl = $('#avatarUrl');
  const charAvatar = $('#charAvatar');
  avatarUrl.addEventListener('input', () => {
    charAvatar.src = avatarUrl.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
    scheduleSave();
  });

  // ------------------------------
  // Build Characteristics + Skills editor
  // ------------------------------
  const charSkillContainer = $('#charSkillContainer');
  CHAR_MAP.forEach(group => {
    const header = document.createElement('div');
    header.className = 'rowline';
    header.innerHTML = `
      <div class="h">${group.label}</div>
      <div class="mini">Invested</div>
      <div class="mini">Modifier</div>
      <div class="mini">[ Total | Mod ]`;
    charSkillContainer.appendChild(header);

    const row = document.createElement('div');
    row.className = 'rowline';
    row.innerHTML = `
      <div><span class="muted">Characteristic</span></div>
      <div><input class="input" type="number" min="0" max="16" value="0" data-c-invest="${group.investKey}"></div>
      <div><span class="mono" data-c-mod="${group.key}">0</span></div>
      <div><span class="mono" data-c-total="${group.key}">4</span> | <span class="mono" data-c-totalmod="${group.key}">-3</span></div>`;
    charSkillContainer.appendChild(row);

    group.skills.forEach(s => {
      const srow = document.createElement('div');
      srow.className = 'rowline';
      srow.innerHTML = `
        <div>— ${s.label}</div>
        <div><input class="input" type="number" min="0" max="8" value="0" data-s-invest="${s.key}"></div>
        <div><span class="mono" data-s-mod="${s.key}">0</span></div>
        <div><span class="mono" data-s-base="${s.key}">0</span></div>`;
      charSkillContainer.appendChild(srow);
    });
  });

  // ------------------------------
  // Intensities table
  // ------------------------------
  const tbodyInt = $('#intensityTable tbody');
  INTENSITIES.forEach(nm => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${nm}</td>
      <td><input class="input" type="number" min="0" max="8" value="0" data-i-invest="${nm}"></td>
      <td class="mono" data-i-mod="${nm}">0</td>
      <td class="mono" data-i-base="${nm}">0</td>
      <td class="mono" data-i-id="${nm}">—</td>
      <td class="mono" data-i-iv="${nm}">—</td>
      <td class="mono right" data-i-rw="${nm}">0</td>`;
    tbodyInt.appendChild(tr);
  });

  // ------------------------------
  // Sublimations
  // ------------------------------
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
  const ALL_SKILLS = CHAR_MAP.flatMap(g => g.skills).map(s => ({key:s.key, label:s.label}));
  const subTableBody = $('#subTable tbody');

  function addSubRow(defaults = {type:'2', skill:'', tier:1}){
    const tr = document.createElement('tr');

    const typeSel = document.createElement('select');
    SUB_TYPES.forEach(t => {
      const o = document.createElement('option');
      o.value = t.id; o.textContent = t.label;
      if(defaults.type === t.id) o.selected = true;
      typeSel.appendChild(o);
    });

    const skillSel = document.createElement('select');
    const empty = document.createElement('option'); empty.value=''; empty.textContent='—';
    skillSel.appendChild(empty);
    ALL_SKILLS.forEach(s=>{
      const o = document.createElement('option');
      o.value=s.key; o.textContent=s.label;
      if(defaults.skill === s.key) o.selected = true;
      skillSel.appendChild(o);
    });

    const tierInp = document.createElement('input');
    tierInp.type='number'; tierInp.min='0'; tierInp.max='4'; tierInp.value = defaults.tier;

    const slotsCell = document.createElement('td');
    slotsCell.className='right mono';
    slotsCell.textContent = String(defaults.tier);

    const delBtn = document.createElement('button');
    delBtn.className = 'btn ghost';
    delBtn.textContent = 'Remove';
    delBtn.addEventListener('click', () => { tr.remove(); recompute(); scheduleSave(); });

    function toggleSkill(){
      skillSel.disabled = (typeSel.value !== '1'); // Excellence only
      skillSel.style.opacity = skillSel.disabled ? .5 : 1;
    }
    toggleSkill();

    typeSel.addEventListener('change', ()=>{ toggleSkill(); recompute(); scheduleSave(); });
    skillSel.addEventListener('change', ()=>{ recompute(); scheduleSave(); });
    tierInp.addEventListener('input', ()=>{ slotsCell.textContent=tierInp.value; recompute(); scheduleSave(); });

    // compose row
    const td1 = document.createElement('td'); td1.appendChild(typeSel);
    const td2 = document.createElement('td'); td2.appendChild(skillSel);
    const td3 = document.createElement('td'); td3.appendChild(tierInp);
    const td5 = document.createElement('td'); td5.appendChild(delBtn);

    tr.appendChild(td1);
    tr.appendChild(td2);
    tr.appendChild(td3);
    tr.appendChild(slotsCell);
    tr.appendChild(td5);

    tr._refs = { typeSel, skillSel, tierInp, slotsCell };
    subTableBody.appendChild(tr);
  }
  $('#btnAddSub').addEventListener('click', () => { addSubRow(); recompute(); scheduleSave(); });

  // ------------------------------
  // Compute + caps + resources
  // ------------------------------
  function readLevel(){
    const lvlInp = $('#c_level');
    const xpInp = $('#c_xp');
    let lvl = Number(lvlInp.value || 1);
    if (!lvl || lvl < 1) lvl = levelFromXP(Number(xpInp.value||0));
    return Math.min(Math.max(lvl,1),100);
  }

  function sumSubType(code){
    return Array.from(subTableBody.children).reduce((acc, tr) => {
      const { typeSel, tierInp } = tr._refs;
      return acc + (typeSel.value === code ? Math.max(0,Number(tierInp.value||0)) : 0);
    }, 0);
  }

  function setResource(curSel, maxSel, barSel, cur, max){
    setTxt(maxSel, max);
    cur = Math.min(Math.max(cur, 0), Math.max(0,max));
    setTxt(curSel, cur);
    const pct = max>0 ? Math.round((cur/max)*100) : 0;
    $(barSel).style.width = `${pct}%`;
  }

  function decorateCaps(skillCap, spMax, cpMax, subMax, tierCap){
    // Skill caps
    CHAR_MAP.forEach(g => g.skills.forEach(s => {
      const inp = $(`[data-s-invest="${s.key}"]`);
      if (!inp) return;
      const val = Number(inp.value||0);
      inp.style.borderColor = (val>skillCap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    }));
    // Totals
    const spUsed = Number($('#sp_used').textContent||0);
    $('#sp_used').classList.toggle('danger', spUsed>spMax);
    const cpUsed = Number($('#cp_used').textContent||0);
    $('#cp_used').classList.toggle('danger', cpUsed>cpMax);
    const subUsed = Number($('#sub_used').textContent||0);
    $('#sub_used').classList.toggle('danger', subUsed>subMax);

    // Tier cap per row
    Array.from(subTableBody.children).forEach(tr=>{
      const { tierInp } = tr._refs;
      const t = Number(tierInp.value||0);
      tierInp.style.borderColor = (t>tierCap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
  }

  function recompute(){
    const lvl = readLevel();
    $('#c_level').value = String(lvl);

    // Characteristics
    const charInvest = {}, charScore = {}, charMod = {};
    CHAR_MAP.forEach(g => {
      const invest = Number($(`[data-c-invest="${g.investKey}"]`).value || 0);
      charInvest[g.key] = invest;
      const score = scoreFromInvest(invest);
      const mod = modFromScore(score);
      charScore[g.key] = score;
      charMod[g.key] = mod;
      $(`[data-c-total="${g.key}"]`).textContent = String(score);
      $(`[data-c-totalmod="${g.key}"]`).textContent = String(mod);
      $(`[data-c-mod="${g.key}"]`).textContent = String(mod);
    });

    // Sublimations
    const excellenceMap = {};
    const subRows = Array.from(subTableBody.children);
    let subUsed = 0;
    subRows.forEach(tr => {
      const { typeSel, skillSel, tierInp, slotsCell } = tr._refs;
      const tier = Math.max(0, Number(tierInp.value||0));
      slotsCell.textContent = String(tier);
      subUsed += tier;
      if (typeSel.value === '1' && skillSel.value){
        excellenceMap[skillSel.value] = (excellenceMap[skillSel.value]||0) + tier;
      }
    });

    // Skills
    const skillInvest = {};
    CHAR_MAP.forEach(g => {
      g.skills.forEach(s => {
        const inv = Number($(`[data-s-invest="${s.key}"]`).value || 0);
        skillInvest[s.key] = inv;
        const bonus = Math.min(inv, excellenceMap[s.key] || 0);
        const base = inv + bonus + charMod[g.key];
        $(`[data-s-mod="${s.key}"]`).textContent = String(bonus);
        $(`[data-s-base="${s.key}"]`).textContent = String(base);
      });
    });

    // Points & caps
    const cp_used = Object.values(charInvest).reduce((a,b)=>a+b,0);
    const sp_used = Object.values(skillInvest).reduce((a,b)=>a+b,0);
    const cp_max = 22 + Math.floor((lvl-1)/9)*3;
    const sp_max = 40 + (lvl-1)*2;
    const skill_cap = (lvl >= 50 ? 8 : lvl >= 40 ? 7 : lvl >= 30 ? 6 : lvl >= 20 ? 5 : lvl >= 10 ? 4 : 3);
    const sub_max = (Math.max(charMod.pre||0,0)*2) + Math.floor(lvl/10);
    const tier_cap = Math.ceil(lvl/25);

    setTxt('#cp_used', cp_used);
    setTxt('#sp_used', sp_used);
    setTxt('#cp_max', cp_max);
    setTxt('#sp_max', sp_max);
    setTxt('#skill_cap', skill_cap);
    setTxt('#sub_used', subUsed);
    setTxt('#sub_max', sub_max);
    setTxt('#sub_tier', tier_cap);
    decorateCaps(skill_cap, sp_max, cp_max, sub_max, tier_cap);

    // Derived resources
    const lvl_up_count = Math.max(lvl-1, 0);
    const mile_bod = Math.max(charMod.bod||0,0);
    const mile_wil = Math.max(charMod.wil||0,0);
    const mile_mag = Math.max(charMod.mag||0,0);
    const mile_dex = Math.max(charMod.dex||0,0);
    const mile_ref = Math.max(charMod.ref||0,0);
    const mile_wis = Math.max(charMod.wis||0,0);

    const sub_defense   = sumSubType('4');
    const sub_speed     = sumSubType('5');
    const sub_clarity   = sumSubType('8');
    const sub_endurance = sumSubType('6');

    const hp_max = 100 + lvl_up_count + (12*mile_bod) + (6*mile_wil) + (12*sub_defense);
    const en_max = 5 + Math.floor(lvl_up_count/5) + (2*mile_wil) + (4*mile_mag) + (2*sub_endurance);
    const fo_max = 2 + Math.floor(lvl_up_count/5) + (2*Math.max(charMod.pre,0)) + mile_wis + mile_wil + sub_clarity;
    const mo     = 4 + mile_dex + mile_ref + sub_speed;
    const et     = 1 + Math.floor(lvl_up_count/9) + mile_mag;
    const cdc    = 6 + Math.floor(lvl/10) + sumSubType('7');

    setResource('#hp_cur','#hp_max','#hp_bar',hp_max,hp_max);
    setResource('#sp_cur','#sp_max','#sp_bar',0,Math.floor(hp_max*0.1));
    setResource('#en_cur','#en_max','#en_bar',Math.min(5,en_max),en_max);
    setResource('#fo_cur','#fo_max','#fo_bar',Math.min(2,fo_max),fo_max);

    const resistanceBV = Number($('[data-s-base="resistance"]')?.textContent||0);
    const alchemyBV    = Number($('[data-s-base="alchemy"]')?.textContent||0);
    const tx_max = resistanceBV + alchemyBV;
    setResource('#tx_cur','#tx_max','#tx_bar',0,tx_max);

    const athletics = Number($('[data-s-base="athletics"]')?.textContent||0);
    const spiritBV  = Number($('[data-s-base="spirit"]')?.textContent||0);
    const enc_max = 10 + (athletics*5) + (spiritBV*2);
    setResource('#enc_cur','#enc_max','#enc_bar',0,enc_max);

    setTxt('#k_mo', mo);
    setTxt('#k_init', mo + mile_ref);
    setTxt('#k_et', et);
    setTxt('#k_cdc', cdc);

    // Intensities
    const magic_mod = charMod.mag || 0;
    const ivMap = {};
    INTENSITIES.forEach(nm => {
      const inv = Number($(`[data-i-invest="${nm}"]`).value || 0);
      const base = (inv>0 ? inv + magic_mod : 0);
      const [ID, IV] = idIvFromBV(base);
      ivMap[nm] = Number(IV || 0);

      $(`[data-i-mod="${nm}"]`).textContent = String(magic_mod);
      $(`[data-i-base="${nm}"]`).textContent = String(base);
      $(`[data-i-id="${nm}"]`).textContent = String(ID);
      $(`[data-i-iv="${nm}"]`).textContent = String(IV||'—');
    });
    INTENSITIES.forEach(nm => {
      $(`[data-i-rw="${nm}"]`).textContent = String(rwFor(nm, ivMap));
    });
  }

  // ------------------------------
  // Events & autosave
  // ------------------------------
  // Tabs/inputs listeners
  ['#c_level','#c_xp','#c_name','#p_height','#p_weight','#p_bday','#p_backstory','#p_notes']
    .forEach(sel => $(sel).addEventListener('input', () => { recompute(); scheduleSave(); }));
  $$('#charSkillContainer input').forEach(inp => inp.addEventListener('input', () => { recompute(); scheduleSave(); }));
  $$('#intensityTable [data-i-invest]').forEach(inp => inp.addEventListener('input', () => { recompute(); scheduleSave(); }));

  // Debounced save
  let pendingSave = null;
  function scheduleSave(){
    clearTimeout(pendingSave);
    pendingSave = setTimeout(saveCharacter, 300);
  }

  // ------------------------------
  // Backend I/O
  // ------------------------------
  let currentCharacter = null;

  function collectStateFromDOM(){
    // core profile
    const lvl = readLevel();
    const payload = {
      name: $('#c_name').value || '',
      level: lvl,
      xp: num('#c_xp'),
      avatarUrl: $('#avatarUrl').value || '',
      personal: {
        height: $('#p_height').value || '',
        weight: $('#p_weight').value || '',
        birthday: $('#p_bday').value || '',
        backstory: $('#p_backstory').value || '',
        notes: $('#p_notes').value || ''
      },
      invested: { characteristics:{}, skills:{}, intensities:{}, sublimations:[] }
    };

    // investments
    CHAR_MAP.forEach(g=>{
      const inv = Number($(`[data-c-invest="${g.investKey}"]`).value || 0);
      payload.invested.characteristics[g.key] = inv;
      g.skills.forEach(s=>{
        payload.invested.skills[s.key] = Number($(`[data-s-invest="${s.key}"]`).value || 0);
      });
    });
    INTENSITIES.forEach(nm=>{
      payload.invested.intensities[nm.toLowerCase()] = Number($(`[data-i-invest="${nm}"]`).value || 0);
    });
    // sublimations
    Array.from(subTableBody.children).forEach(tr=>{
      const {typeSel, skillSel, tierInp} = tr._refs;
      payload.invested.sublimations.push({
        type: typeSel.value,
        skill: skillSel.value || null,
        tier: Number(tierInp.value||0)
      });
    });

    return payload;
  }

  async function loadOrCreateCharacter(){
    try{
      const res = await fetch(`${API_BASE}/characters`, {
        headers: {
          'Content-Type':'application/json',
          'Authorization': `Bearer ${localStorage.getItem('auth_token') || ''}`
        }
      });
      let data = await res.json();
      const first = Array.isArray(data) ? data[0] : (data.characters?.[0] || data.character || null);

      if (first){
        currentCharacter = first;
        hydrate(first);
      } else {
        const created = await fetch(`${API_BASE}/characters`, {
          method: 'POST',
          headers: {
            'Content-Type':'application/json',
            'Authorization': `Bearer ${localStorage.getItem('auth_token') || ''}`
          },
          body: JSON.stringify({ name:'New Character', level:1, xp:0 })
        }).then(r=>r.json());
        currentCharacter = created.character || created;
      }
    }catch(e){
      console.warn('Load/create character failed:', e);
    }
  }

  function hydrate(ch){
    // Basic fields
    $('#c_name').value = ch.name || '';
    $('#c_level').value = ch.level || 1;
    $('#c_xp').value = ch.xp || 0;
    $('#avatarUrl').value = ch.avatarUrl || '';
    if (ch.avatarUrl) $('#charAvatar').src = ch.avatarUrl;

    // investments
    const inv = ch.invested || {};
    const c = inv.characteristics || {};
    CHAR_MAP.forEach(g=>{
      const v = Number(c[g.key] || 0);
      const node = $(`[data-c-invest="${g.investKey}"]`);
      if (node) node.value = v;
    });

    const s = inv.skills || {};
    CHAR_MAP.forEach(g=>g.skills.forEach(sk=>{
      const node = $(`[data-s-invest="${sk.key}"]`);
      if (node) node.value = Number(s[sk.key] || 0);
    }));

    const inten = inv.intensities || {};
    INTENSITIES.forEach(nm=>{
      const node = $(`[data-i-invest="${nm}"]`);
      if (node) node.value = Number(inten[nm.toLowerCase()] || 0);
    });

    // Sublimations
    subTableBody.innerHTML = '';
    const subs = inv.sublimations || [];
    if (subs.length === 0) addSubRow();
    else subs.forEach(sub => addSubRow({
      type: String(sub.type || '2'),
      skill: sub.skill || '',
      tier: Number(sub.tier || 0)
    }));

    // Personal
    const p = ch.personal || {};
    $('#p_height').value = p.height || '';
    $('#p_weight').value = p.weight || '';
    $('#p_bday').value = p.birthday || '';
    $('#p_backstory').value = p.backstory || '';
    $('#p_notes').value = p.notes || '';

    recompute();
  }

  async function saveCharacter(){
    try{
      const payload = collectStateFromDOM();
      const id = currentCharacter?.id;

      const res = await fetch(id ? `${API_BASE}/characters/${id}` : `${API_BASE}/characters`, {
        method: id ? 'PUT' : 'POST',
        headers: {
          'Content-Type':'application/json',
          'Authorization': `Bearer ${localStorage.getItem('auth_token') || ''}`
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!id && (data.character?.id || data.id)) {
        currentCharacter = data.character || data;
      }
    }catch(e){
      console.warn('Save failed:', e);
    }
  }

  // ------------------------------
  // Avatar reactive preview
  // ------------------------------
  $('#avatarUrl').addEventListener('change', () => {
    charAvatar.src = $('#avatarUrl').value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
  });

  // ------------------------------
  // Seed + first compute + load
  // ------------------------------
  addSubRow(); // safe now (helpers exist)
  recompute();
  loadOrCreateCharacter();
})();