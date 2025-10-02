(() => {
  const API_BASE = ""; // same-origin
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

  // ----- Tabs -----
  $$('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const key = btn.dataset.tab;
      $$('.tabpan').forEach(p => p.classList.remove('active'));
      $(`#tab-${key}`).classList.add('active');
    });
  });

  // ----- Avatar -----
  const avatarUrl = $('#avatarUrl');
  const charAvatar = $('#charAvatar');
  if (avatarUrl) {
    avatarUrl.addEventListener('input', () => {
      charAvatar.src = avatarUrl.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
      queueSave();
    });
  }

  // ===== Rules / helpers =====
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const milestoneFromTotal = total => Math.floor((Number(total) - 10) / 2);
  const levelFromXP = xp => Math.min(Math.floor((-1 + Math.sqrt(1 + 8 * (xp / 100))) / 2) + 1, 100);
  const tens = lvl => Math.floor(lvl / 10);

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
    { id:'1', label:'Excellence' }, // +1 per tier to chosen skill; capped by Invested
    { id:'3', label:'Blessing' },
    { id:'4', label:'Defense' },
    { id:'5', label:'Speed' },
    { id:'7', label:'Devastation' },
    { id:'8', label:'Clarity' },
    { id:'6', label:'Endurance' },
  ];

  const ALL_SKILLS = CHAR_GROUPS.flatMap(g => g.skills.map(s => ({...s, group:g.key})));

  // ===== Build UI: Characteristics & Skills =====
  const charSkillContainer = $('#charSkillContainer');
  charSkillContainer.innerHTML = "";

  CHAR_GROUPS.forEach(group => {
    const card = document.createElement('div');
    card.className = 'char-card';

    // header
    const head = document.createElement('div');
    head.className = 'rowline head';
    head.innerHTML = `
      <div class="h">${group.label}</div>
      <div class="mini">Invested</div>
      <div class="mini">Modifier</div>
      <div class="mini">[ Total | Milestone ]</div>
    `;
    card.appendChild(head);

    // characteristic row (invest + modifier input)
    const crow = document.createElement('div');
    crow.className = 'rowline';
    crow.innerHTML = `
      <div><span class="muted">Characteristic</span></div>
      <div><input class="input" type="number" min="0" max="16" value="0" data-c-invest="${group.investKey}"></div>
      <div><input class="input" type="number" min="-10" max="10" value="0" data-c-modifier="${group.key}"></div>
      <div><span class="mono" data-c-total="${group.key}">4</span> | <span class="mono" data-c-mile="${group.key}">-3</span></div>
    `;
    card.appendChild(crow);

    // skills header
    const shead = document.createElement('div');
    shead.className = 'rowline subhead';
    shead.innerHTML = `
      <div class="mini">—</div>
      <div class="mini">Invested</div>
      <div class="mini">Modifier</div>
      <div class="mini">Base Value</div>
    `;
    card.appendChild(shead);

    // skills rows
    group.skills.forEach(s => {
      const srow = document.createElement('div');
      srow.className = 'rowline';
      srow.innerHTML = `
        <div>— ${s.label}</div>
        <div><input class="input" type="number" min="0" max="8" value="0" data-s-invest="${s.key}" data-s-group="${group.key}"></div>
        <div><input class="input" type="number" min="0" max="0" value="0" data-s-mod="${s.key}"></div>
        <div>
          <span class="mono" data-s-base="${s.key}">0</span>
          <span class="mini" data-s-bonus-note="${s.key}" style="margin-left:6px;opacity:.7">(bonus 0)</span>
        </div>
      `;
      card.appendChild(srow);
    });

    charSkillContainer.appendChild(card);
  });

  // ===== Intensities table =====
  const tbodyInt = $('#intensityTable tbody');
  tbodyInt.innerHTML = "";
  INTENSITIES.forEach(nm => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${nm}</td>
      <td><input class="input" type="number" min="0" max="8" value="0" data-i-invest="${nm}"></td>
      <td><input class="input" type="number" min="0" max="0" value="0" data-i-mod="${nm}"></td>
      <td class="mono" data-i-base="${nm}">0</td>
      <td class="mono" data-i-id="${nm}">—</td>
      <td class="mono" data-i-iv="${nm}">—</td>
      <td class="mono right" data-i-rw="${nm}">0</td>
    `;
    tbodyInt.appendChild(tr);
  });

  // ===== Sublimations =====
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
      const needsSkill = typeSel.value === '1'; // Excellence only
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
  // seed example
  addSubRow({ type:'1', skill:'accuracy', tier:2 });

  // ===== Reads / Sets =====
  const setTxt = (sel, v) => { const el=$(sel); if (el) el.textContent=String(v); };
  const lvlInp = $('#c_level'), xpInp = $('#c_xp');

  const idIvFromBV = (bv) => {
    if (bv <= 0) return ['—','—'];
    if (bv <= 7)  return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10',5];
    return ['1d12', 6];
  };

  function readLevel(){
    let lvl = Number(lvlInp.value || 1);
    if (!lvl || lvl < 1) lvl = levelFromXP(Number(xpInp.value||0));
    return clamp(lvl, 1, 100);
  }

  // ===== Recompute =====
  function recompute(){
    const lvl = readLevel();
    lvlInp.value = String(lvl);

    // --- Excellence map
    const ex = {}; // skill -> tiers
    let subUsed = 0;
    Array.from(subTableBody.children).forEach(tr=>{
      const { typeSel, skillSel, tierInp, slotsCell } = tr._refs || {};
      const tier = Math.max(0, Number(tierInp.value||0));
      slotsCell.textContent = String(tier);
      subUsed += tier;
      if (typeSel.value === '1' && skillSel.value){
        ex[skillSel.value] = (ex[skillSel.value]||0) + tier;
      }
    });

    // --- Characteristics: totals, milestones
    const charInvest = {};
    const charModExternal = {};
    const charMilestone   = {};
    CHAR_GROUPS.forEach(g => {
      const inv = Number($(`[data-c-invest="${g.investKey}"]`).value || 0);
      charInvest[g.key] = inv;

      const modInputEl = $(`[data-c-modifier="${g.key}"]`);
      const modVal = clamp(Number(modInputEl.value||0), -10, 10);
      modInputEl.value = String(modVal);
      charModExternal[g.key] = modVal;

      const total = 4 + inv + modVal;               // base 4 + invested + external modifier
      const mile  = milestoneFromTotal(total);      // Milestone added to skills
      $(`[data-c-total="${g.key}"]`).textContent = String(total);
      $(`[data-c-mile="${g.key}"]`).textContent  = String(mile);

      charMilestone[g.key] = mile;
    });

    // --- Skills: base values with caps
    const skillInvest = {};
    const skillModExternal = {};
    CHAR_GROUPS.forEach(g => {
      g.skills.forEach(s => {
        const inv = Number($(`[data-s-invest="${s.key}"]`).value || 0);
        skillInvest[s.key] = inv;

        const modEl = $(`[data-s-mod="${s.key}"]`);
        const exTiers = ex[s.key] || 0;
        modEl.max = Math.max(0, inv - exTiers);      // external mod cap so (mod + ex) ≤ invested
        const rawMod = clamp(Number(modEl.value||0), 0, Number(modEl.max));
        modEl.value = String(rawMod);
        skillModExternal[s.key] = rawMod;

        const appliedBonus = Math.min(inv, rawMod + exTiers);
        const base = inv + appliedBonus + (charMilestone[g.key] || 0);

        $(`[data-s-base="${s.key}"]`).textContent = String(base);
        $(`[data-s-bonus-note="${s.key}"]`).textContent = `(bonus ${appliedBonus})`;
      });
    });

    // --- Counters & caps
    const cp_used = Object.values(charInvest).reduce((a,b)=>a+b,0);
    const cp_max  = 22 + Math.floor((lvl-1)/9)*3;
    const sp_used = Object.values(skillInvest).reduce((a,b)=>a+b,0);
    const sp_max  = 40 + (lvl-1)*2;
    const skill_cap = (lvl>=50?8:lvl>=40?7:lvl>=30?6:lvl>=20?5:lvl>=10?4:3);
    const char_cap  = (lvl>=55?10:lvl>=46?9:lvl>=37?8:lvl>=28?7:lvl>=19?6:lvl>=10?5:4);

    setTxt('#cp_used', cp_used); setTxt('#cp_max', cp_max);
    setTxt('#sp_used', sp_used); setTxt('#sp_max', sp_max);
    setTxt('#skill_cap', skill_cap); setTxt('#char_cap', char_cap);

    // --- Sublimation slots / tier cap
    const mile_pre_pos = Math.max(charMilestone.pre || 0, 0); // Positive Milestones only
    const sub_max  = (mile_pre_pos*2) + Math.floor(lvl/10);
    const tier_cap = Math.ceil(lvl/25);
    setTxt('#sub_used', subUsed); setTxt('#sub_max', sub_max); setTxt('#sub_tier', tier_cap);

    // --- Derived resources (use Positive Milestones)
    const mile_bod_pos = Math.max(charMilestone.bod||0,0);
    const mile_wil_pos = Math.max(charMilestone.wil||0,0);
    const mile_mag_pos = Math.max(charMilestone.mag||0,0);
    const mile_dex_pos = Math.max(charMilestone.dex||0,0);
    const mile_ref_pos = Math.max(charMilestone.ref||0,0);
    const mile_wis_pos = Math.max(charMilestone.wis||0,0);

    const sub_def   = sumSubType('4'); // Defense +12 HP
    const sub_end   = sumSubType('6'); // Endurance +2 EN
    const sub_clr   = sumSubType('8'); // Clarity +1 FO
    const sub_spd   = sumSubType('5'); // Speed +1 MO

    const hp_max = 100 + (lvl-1) + 12*mile_bod_pos + 6*mile_wil_pos + 12*sub_def;
    const en_max = 5 + Math.floor((lvl-1)/5) + mile_wil_pos + 2*mile_mag_pos + 2*sub_end;
    const fo_max = 2 + Math.floor((lvl-1)/5) + mile_wil_pos + mile_wis_pos + (Math.max(charMilestone.pre||0,0)) + sub_clr;
    const mo     = 4 + mile_dex_pos + mile_ref_pos + sub_spd;
    const et     = 1 + Math.floor((lvl-1)/9) + mile_mag_pos;
    const cdc    = 6 + tens(lvl) + sumSubType('7');

    // --- Skills used by TX / Enc
    const resistanceBV = Number($('[data-s-base="resistance"]').textContent||0);
    const alchemyBV    = Number($('[data-s-base="alchemy"]').textContent||0);
    const tx_max = resistanceBV + alchemyBV;

    const athleticsBV  = Number($('[data-s-base="athletics"]').textContent||0);
    const spiritBV     = Number($('[data-s-base="spirit"]').textContent||0);
    const enc_max = 10 + athleticsBV + spiritBV;

    // Set resources & badges
    setResource('#hp_cur','#hp_max','#hp_bar',hp_max,hp_max);
    setResource('#sp_cur','#sp_max','#sp_bar',0,Math.floor(hp_max/10));
    setResource('#en_cur','#en_max','#en_bar',Math.min(5,en_max),en_max);
    setResource('#fo_cur','#fo_max','#fo_bar',Math.min(2,fo_max),fo_max);
    setResource('#tx_cur','#tx_max','#tx_bar',0,tx_max);
    setResource('#enc_cur','#enc_max','#enc_bar',0,enc_max);

    setTxt('#k_mo', mo);
    setTxt('#k_init', mo + mile_ref_pos);
    setTxt('#k_et', et);
    setTxt('#k_cdc', cdc);

    // --- Intensities as skills (linked to MAG milestone)
    const mag_mile = charMilestone.mag || 0;
    INTENSITIES.forEach(nm => {
      const inv = Number($(`[data-i-invest="${nm}"]`).value || 0);
      const modEl = $(`[data-i-mod="${nm}"]`);
      modEl.max = Math.max(0, inv); // cap: ≤ Invested
      const rawMod = clamp(Number(modEl.value||0), 0, Number(modEl.max));
      modEl.value = String(rawMod);

      // if invested == 0 => base = 0 (specialist rule not modeled here)
      const applied = Math.min(inv, rawMod); // no Excellence on intensities (by design)
      const base = inv > 0 ? inv + applied + mag_mile : 0;
      const [ID, IV] = idIvFromBV(base);

      $(`[data-i-base="${nm}"]`).textContent = String(base);
      $(`[data-i-id="${nm}"]`).textContent = String(ID);
      $(`[data-i-iv="${nm}"]`).textContent = String(IV||'—');
      $(`[data-i-rw="${nm}"]`).textContent = "0";
    });

    // Highlights
    decorateCaps(skill_cap, sp_max, cp_max, sub_max, tier_cap);
  }

  function setResource(curSel, maxSel, barSel, cur, max){
    setTxt(maxSel, max);
    cur = clamp(cur, 0, Math.max(0,max));
    setTxt(curSel, cur);
    const pct = max>0 ? Math.round((cur/max)*100) : 0;
    $(barSel).style.width = `${pct}%`;
  }

  function sumSubType(code){
    return Array.from(subTableBody.children).reduce((acc, tr) => {
      const { typeSel, tierInp } = tr._refs || {};
      return acc + ((typeSel && typeSel.value === code) ? Math.max(0, Number(tierInp.value||0)) : 0);
    }, 0);
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

  // ===== Save on change =====
  let saveTimer=null;
  function queueSave(){ clearTimeout(saveTimer); saveTimer = setTimeout(saveDraft, 300); }

  function collectPayload(){
    const lvl = readLevel();
    const name = ($('#c_name').value || '').trim();
    const xp   = Number($('#c_xp').value || 0);
    const avatar = $('#avatarUrl')?.value || '';

    const invested_characteristics = {};
    const characteristic_modifiers = {};
    CHAR_GROUPS.forEach(g=>{
      invested_characteristics[g.key] = Number($(`[data-c-invest="${g.investKey}"]`).value||0);
      characteristic_modifiers[g.key] = Number($(`[data-c-modifier="${g.key}"]`).value||0);
    });

    const invested_skills = {};
    const skill_modifiers = {};
    CHAR_GROUPS.forEach(g=>g.skills.forEach(s=>{
      invested_skills[s.key] = Number($(`[data-s-invest="${s.key}"]`).value||0);
      skill_modifiers[s.key] = Number($(`[data-s-mod="${s.key}"]`).value||0);
    }));

    const intensities_invested = {};
    const intensities_modifiers = {};
    INTENSITIES.forEach(nm=>{
      intensities_invested[nm] = Number($(`[data-i-invest="${nm}"]`).value||0);
      intensities_modifiers[nm] = Number($(`[data-i-mod="${nm}"]`).value||0);
    });

    const sublimations = Array.from(subTableBody.children).map(tr=>{
      const { typeSel, skillSel, tierInp } = tr._refs || {};
      return { type: typeSel.value, skill: (skillSel.value||null), tier: Number(tierInp.value||0) };
    });

    return {
      name, level:lvl, xp, avatar,
      invested_characteristics,
      characteristic_modifiers,
      invested_skills,
      skill_modifiers,
      intensities_invested,
      intensities_modifiers,
      sublimations
    };
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
      console.warn('save failed', e);
    }
  }

  // ===== Events =====
  ['#c_level','#c_xp','#c_name'].forEach(sel => $(sel).addEventListener('input', ()=>{ recompute(); queueSave(); }));
  $$('#charSkillContainer input').forEach(inp => inp.addEventListener('input', ()=>{ recompute(); queueSave(); }));
  $$('#intensityTable input').forEach(inp => inp.addEventListener('input', ()=>{ recompute(); queueSave(); }));

  // Initial compute
  recompute();
})();