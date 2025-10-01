(() => {
  const API_BASE = ""; // same-origin
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

  // ---------------- Tabs ----------------
  $$('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const key = btn.dataset.tab;
      $$('.tabpan').forEach(p => p.classList.remove('active'));
      $(`#tab-${key}`).classList.add('active');
    });
  });

  // ---------------- Avatar ----------------
  const avatarUrl = $('#avatarUrl');
  const charAvatar = $('#charAvatar');
  if (avatarUrl) {
    avatarUrl.addEventListener('input', () => {
      charAvatar.src = avatarUrl.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
      queueSave();
    });
  }

  // ---------------- Helpers / rules ----------------
  const modFromTotal = total => Math.floor((Number(total) - 10) / 2);
  const tens = lvl => Math.floor(lvl / 10);
  const f = n => Number.isFinite(n) ? n : 0;

  const CHAR_GROUPS = [
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
    { id:'1', label:'Excellence' }, // adds skill bonus
    { id:'3', label:'Blessing' },
    { id:'4', label:'Defense' },
    { id:'5', label:'Speed' },
    { id:'7', label:'Devastation' },
    { id:'8', label:'Clarity' },
    { id:'6', label:'Endurance' },
  ];

  const ALL_SKILLS = CHAR_GROUPS.flatMap(g => g.skills.map(s => ({...s, group:g.key})));

  // ---------------- Build Characteristics & Skills ----------------
  const charSkillContainer = $('#charSkillContainer');
  charSkillContainer.innerHTML = ""; // ensure clean mount

  CHAR_GROUPS.forEach(group => {
    const wrap = document.createElement('div');
    wrap.className = 'char-card';

    // header
    const head = document.createElement('div');
    head.className = 'rowline head';
    head.innerHTML = `
      <div class="h">${group.label}</div>
      <div class="mini">Invested</div>
      <div class="mini">Char Bonus</div>
      <div class="mini">[ Total | Char Mod ]</div>
    `;
    wrap.appendChild(head);

    // characteristic row
    const crow = document.createElement('div');
    crow.className = 'rowline';
    crow.innerHTML = `
      <div><span class="muted">Characteristic</span></div>
      <div><input class="input" type="number" min="0" max="16" value="0" data-c-invest="${group.investKey}"></div>
      <div><span class="mono" data-c-bonus="${group.key}">0</span></div>
      <div><span class="mono" data-c-total="${group.key}">4</span> | <span class="mono" data-c-mod="${group.key}">-3</span></div>
    `;
    wrap.appendChild(crow);

    // skills
    const shead = document.createElement('div');
    shead.className = 'rowline subhead';
    shead.innerHTML = `
      <div class="mini">—</div>
      <div class="mini">Invested</div>
      <div class="mini">Skill Bonus</div>
      <div class="mini">Base Value</div>
    `;
    wrap.appendChild(shead);

    group.skills.forEach(s => {
      const srow = document.createElement('div');
      srow.className = 'rowline';
      srow.innerHTML = `
        <div>— ${s.label}</div>
        <div><input class="input" type="number" min="0" max="8" value="0" data-s-invest="${s.key}" data-s-group="${group.key}"></div>
        <div><span class="mono" data-s-bonus="${s.key}">0</span></div>
        <div><span class="mono" data-s-base="${s.key}">0</span></div>
      `;
      wrap.appendChild(srow);
    });

    charSkillContainer.appendChild(wrap);
  });

  // ---------------- Intensities ----------------
  const tbodyInt = $('#intensityTable tbody');
  tbodyInt.innerHTML = "";
  INTENSITIES.forEach(nm => {
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
    tbodyInt.appendChild(tr);
  });

  // ---------------- Sublimations ----------------
  const subTableBody = $('#subTable tbody');
  const btnAddSub = $('#btnAddSub');

  function addSubRow(defaults = {type:'2', skill:'', tier:1}){
    const tr = document.createElement('tr');

    const typeSel = document.createElement('select');
    SUB_TYPES.forEach(t => {
      const o = document.createElement('option');
      o.value = t.id; o.textContent = t.label;
      if (defaults.type === t.id) o.selected = true;
      typeSel.appendChild(o);
    });

    const skillSel = document.createElement('select');
    const empty = document.createElement('option'); empty.value=''; empty.textContent='—';
    skillSel.appendChild(empty);
    ALL_SKILLS.forEach(s=>{
      const o = document.createElement('option');
      o.value=s.key; o.textContent=s.label;
      if (defaults.skill === s.key) o.selected = true;
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
    delBtn.addEventListener('click', () => { tr.remove(); recompute(); queueSave(); });

    function toggleSkill(){
      const needsSkill = typeSel.value === '1'; // Excellence
      skillSel.disabled = !needsSkill;
      skillSel.style.opacity = needsSkill ? 1 : .5;
    }

    typeSel.addEventListener('change', ()=>{ toggleSkill(); recompute(); queueSave(); });
    skillSel.addEventListener('change', ()=>{ recompute(); queueSave(); });
    tierInp.addEventListener('input', ()=>{ recompute(); queueSave(); });

    toggleSkill();

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

  btnAddSub.addEventListener('click', () => { addSubRow(); recompute(); queueSave(); });

  // seed
  addSubRow({ type:'1', skill:'accuracy', tier:3 });
  addSubRow({ type:'2', skill:'', tier:1 });

  // ---------------- Reads & Sets ----------------
  const setTxt = (sel, v) => { const el=$(sel); if (el) el.textContent=String(v); };
  const lvlInp = $('#c_level');
  const xpInp  = $('#c_xp');

  function readLevel(){
    let lvl = Number(lvlInp.value || 1);
    if (!lvl || lvl < 1){
      const xp = Number(xpInp.value||0);
      const n  = Math.floor((-1 + Math.sqrt(1 + 8*(xp/100)))/2);
      lvl = Math.min(n+1, 100);
    }
    return Math.min(Math.max(lvl,1),100);
  }

  function idIvFromBV(bv){
    if (bv <= 0) return ['—','—'];
    if (bv <= 7)  return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10',5];
    return ['1d12', 6];
  }

  function sumSubType(code){
    return Array.from(subTableBody.children).reduce((acc, tr) => {
      const { typeSel, tierInp } = tr._refs || {};
      return acc + ((typeSel && typeSel.value === code) ? Math.max(0, Number(tierInp.value||0)) : 0);
    }, 0);
  }

  // ---------------- Recompute ----------------
  function recompute(){
    const lvl = readLevel();
    lvlInp.value = String(lvl);

    // Excellence bonuses per-skill
    const excellence = {};
    let subUsed = 0;
    Array.from(subTableBody.children).forEach(tr=>{
      const { typeSel, skillSel, tierInp, slotsCell } = tr._refs || {};
      const tier = Math.max(0, Number(tierInp.value||0));
      slotsCell.textContent = String(tier);
      subUsed += tier;
      if (typeSel.value === '1' && skillSel.value){
        excellence[skillSel.value] = (excellence[skillSel.value]||0) + tier;
      }
    });

    // Characteristic totals & mods
    const charInvest = {};
    const charTotal  = {};
    const charMod    = {};  // d20-style mod used by skills
    CHAR_GROUPS.forEach(g => {
      const invested = Number($(`[data-c-invest="${g.investKey}"]`).value || 0);
      charInvest[g.key] = invested;

      const charBonus = 0; // external item/trait; for now 0
      const total     = invested + charBonus + 4; // base 4 on creation
      const cmod      = modFromTotal(total);

      $(`[data-c-bonus="${g.key}"]`).textContent = String(charBonus);
      $(`[data-c-total="${g.key}"]`).textContent = String(total);
      $(`[data-c-mod="${g.key}"]`).textContent   = String(cmod);

      charTotal[g.key] = total;
      charMod[g.key]   = cmod;
    });

    // Skill bases
    const skillInvest = {};
    CHAR_GROUPS.forEach(g => {
      g.skills.forEach(s => {
        const inv = Number($(`[data-s-invest="${s.key}"]`).value || 0);
        skillInvest[s.key] = inv;

        // Excellence bonus capped by invested points
        const exBonus = Math.min(excellence[s.key]||0, inv);
        const base = inv + exBonus + (charMod[g.key]||0);

        $(`[data-s-bonus="${s.key}"]`).textContent = String(exBonus);
        $(`[data-s-base="${s.key}"]`).textContent  = String(base);
      });
    });

    // Counters & caps
    const cp_used = Object.values(charInvest).reduce((a,b)=>a+b,0);
    const cp_max  = 22 + Math.floor((lvl-1)/9)*3;
    const sp_used = Object.values(skillInvest).reduce((a,b)=>a+b,0);
    const sp_max  = 40 + (lvl-1)*2;
    const skill_cap = (lvl>=50?8:lvl>=40?7:lvl>=30?6:lvl>=20?5:lvl>=10?4:3);

    setTxt('#cp_used', cp_used);
    setTxt('#cp_max',  cp_max);
    setTxt('#sp_used', sp_used);
    setTxt('#sp_max',  sp_max);
    setTxt('#skill_cap', skill_cap);
    setTxt('#char_cap', (lvl>=55?10:lvl>=46?9:lvl>=37?8:lvl>=28?7:lvl>=19?6:lvl>=10?5:4));

    // Sublimation slots / tier cap
    const mile_pre = Math.max(charMod.pre||0, 0);
    const sub_max  = (mile_pre*2) + Math.floor(lvl/10);
    const tier_cap = Math.ceil(lvl/25);
    setTxt('#sub_used', subUsed);
    setTxt('#sub_max', sub_max);
    setTxt('#sub_tier', tier_cap);

    // Derived resources
    const mile_bod = Math.max(charMod.bod||0,0);
    const mile_wil = Math.max(charMod.wil||0,0);
    const mile_mag = Math.max(charMod.mag||0,0);
    const mile_dex = Math.max(charMod.dex||0,0);
    const mile_ref = Math.max(charMod.ref||0,0);
    const mile_wis = Math.max(charMod.wis||0,0);

    const sub_def   = sumSubType('4'); // Defense +12 HP each
    const sub_end   = sumSubType('6'); // Endurance +2 EN each
    const sub_clr   = sumSubType('8'); // Clarity +1 FO each
    const sub_spd   = sumSubType('5'); // Speed +1 MO each
    const lvl5      = Math.floor((lvl-1)/5);

    const hp_max = 100 + (lvl-1) + 12*mile_bod + 6*mile_wil + 12*sub_def;
    const en_max = 5 + lvl5 + mile_wil + 2*mile_mag + 2*sub_end;
    const fo_max = 2 + lvl5 + mile_wil + mile_wis + 2*Math.max(charMod.pre||0,0) + sub_clr; // PRE milestone counts twice in your text; here we use +PRE_mile + Clarity
    const mo     = 4 + mile_dex + mile_ref + sub_spd;
    const et     = 1 + Math.floor((lvl-1)/9) + mile_mag;
    const cdc    = 6 + tens(lvl) + sumSubType('7');

    // TX & Enc
    const resistanceBV = Number($('[data-s-base="resistance"]').textContent||0);
    const alchemyBV    = Number($('[data-s-base="alchemy"]').textContent||0);
    const tx_max = resistanceBV + alchemyBV;

    const athleticsBV  = Number($('[data-s-base="athletics"]').textContent||0);
    const spiritBV     = Number($('[data-s-base="spirit"]').textContent||0);
    const enc_max = 10 + athleticsBV + spiritBV;

    // set resources & badges
    setResource('#hp_cur','#hp_max','#hp_bar',hp_max,hp_max);
    setResource('#sp_cur','#sp_max','#sp_bar',0,Math.floor(hp_max/10));
    setResource('#en_cur','#en_max','#en_bar',Math.min(5,en_max),en_max);
    setResource('#fo_cur','#fo_max','#fo_bar',Math.min(2,fo_max),fo_max);
    setResource('#tx_cur','#tx_max','#tx_bar',0,tx_max);
    setResource('#enc_cur','#enc_max','#enc_bar',0,enc_max);

    setTxt('#k_mo', mo);
    setTxt('#k_init', mo + Math.max(charMod.ref||0,0));
    setTxt('#k_et', et);
    setTxt('#k_cdc', cdc);

    // Intensities (base = invested + MAG mod; if invested==0, base=0)
    const magMod = charMod.mag || 0;
    const ivMap = {};
    INTENSITIES.forEach(nm => {
      const inv = Number($(`[data-i-invest="${nm}"]`).value || 0);
      const base = inv>0 ? inv + magMod : 0;
      const [ID, IV] = idIvFromBV(base);
      ivMap[nm] = Number(IV||0);
      $(`[data-i-mod="${nm}"]`).textContent  = String(magMod);
      $(`[data-i-base="${nm}"]`).textContent = String(base);
      $(`[data-i-id="${nm}"]`).textContent   = String(ID);
      $(`[data-i-iv="${nm}"]`).textContent   = String(IV||'—');
      $(`[data-i-rw="${nm}"]`).textContent   = "0"; // placeholder grid
    });

    // cap highlighting
    decorateCaps(skill_cap, sp_max, cp_max, sub_max, tier_cap);
  }

  function setResource(curSel, maxSel, barSel, cur, max){
    setTxt(maxSel, max);
    cur = Math.min(Math.max(cur, 0), Math.max(0,max));
    setTxt(curSel, cur);
    const pct = max>0 ? Math.round((cur/max)*100) : 0;
    $(barSel).style.width = `${pct}%`;
  }

  function decorateCaps(skillCap, spMax, cpMax, subMax, tierCap){
    // skills
    CHAR_GROUPS.forEach(g => g.skills.forEach(s => {
      const inp = $(`[data-s-invest="${s.key}"]`);
      const val = Number(inp.value||0);
      inp.style.borderColor = (val>skillCap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    }));
    // totals
    $('#sp_used').classList.toggle('danger', Number($('#sp_used').textContent)>spMax);
    $('#cp_used').classList.toggle('danger', Number($('#cp_used').textContent)>cpMax);
    // tiers
    Array.from(subTableBody.children).forEach(tr=>{
      const { tierInp } = tr._refs || {};
      const t = Number(tierInp.value||0);
      tierInp.style.borderColor = (t>tierCap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
  }

  // ---------------- Save-on-change ----------------
  let saveTimer = null;
  function queueSave(){
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveDraft, 300);
  }

  async function saveDraft(){
    try{
      const payload = collectPayload();
      await fetch(`${API_BASE}/characters/save`,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload),
      });
    }catch(e){
      // swallow for now; you can surface a toast if you want
      console.warn('save failed', e);
    }
  }

  function collectPayload(){
    const lvl = readLevel();
    const name = ($('#c_name').value || '').trim();
    const xp   = Number($('#c_xp').value || 0);
    const avatar = $('#avatarUrl').value || '';

    const invested_chars = {};
    CHAR_GROUPS.forEach(g=>{
      invested_chars[g.key] = Number($(`[data-c-invest="${g.investKey}"]`).value||0);
    });

    const invested_skills = {};
    CHAR_GROUPS.forEach(g=>g.skills.forEach(s=>{
      invested_skills[s.key] = Number($(`[data-s-invest="${s.key}"]`).value||0);
    }));

    const sublimations = Array.from(subTableBody.children).map(tr=>{
      const { typeSel, skillSel, tierInp } = tr._refs || {};
      return { type: typeSel.value, skill: (skillSel.value||null), tier: Number(tierInp.value||0) };
    });

    return {
      name, level:lvl, xp, avatar,
      invested_characteristics: invested_chars,
      invested_skills,
      sublimations
    };
  }

  // ---------------- Events ----------------
  ['#c_level','#c_xp','#c_name'].forEach(sel => $(sel).addEventListener('input', ()=>{ recompute(); queueSave(); }));
  $$('#charSkillContainer input').forEach(inp => inp.addEventListener('input', ()=>{ recompute(); queueSave(); }));
  $$('#intensityTable [data-i-invest]').forEach(inp => inp.addEventListener('input', ()=>{ recompute(); queueSave(); }));

  // first compute
  recompute();
})();
