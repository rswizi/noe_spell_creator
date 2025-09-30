(() => {
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
  avatarUrl.addEventListener('change', () => {
    charAvatar.src = avatarUrl.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
  });

  // ----- Base Data Model -----
  // Characteristics and their linked skills
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

  const INTENSITIES = [
    'Fire','Water','Earth','Wind','Lightning','Moon','Sun','Ki'
  ];

  // Build the Characteristics + Skills editor
  const charSkillContainer = $('#charSkillContainer');
  CHAR_MAP.forEach(group => {
    // group header row
    const header = document.createElement('div');
    header.className = 'rowline';
    header.innerHTML = `
      <div class="h">${group.label}</div>
      <div class="mini">Invested</div>
      <div class="mini">Modifier</div>
      <div class="mini">[ Total | Mod ]</div>
    `;
    charSkillContainer.appendChild(header);

    // characteristic row (investable)
    const row = document.createElement('div');
    row.className = 'rowline';
    row.innerHTML = `
      <div><span class="muted">Characteristic</span></div>
      <div><input class="input" type="number" min="0" max="16" value="0" data-c-invest="${group.investKey}"></div>
      <div><span class="mono" data-c-mod="${group.key}">0</span></div>
      <div><span class="mono" data-c-total="${group.key}">4</span> | <span class="mono" data-c-totalmod="${group.key}">-3</span></div>
    `;
    charSkillContainer.appendChild(row);

    // linked skills
    group.skills.forEach(s => {
      const srow = document.createElement('div');
      srow.className = 'rowline';
      srow.innerHTML = `
        <div>— ${s.label}</div>
        <div><input class="input" type="number" min="0" max="8" value="0" data-s-invest="${s.key}"></div>
        <div><span class="mono" data-s-mod="${s.key}">0</span></div>
        <div><span class="mono" data-s-base="${s.key}">0</span></div>
      `;
      charSkillContainer.appendChild(srow);
    });
  });

  // Build Intensities table
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
      <td class="mono right" data-i-rw="${nm}">0</td>
    `;
    tbodyInt.appendChild(tr);
  });

  // ----- Sublimations -----
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
  const btnAddSub = $('#btnAddSub');
  btnAddSub.addEventListener('click', () => addSubRow());

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
    delBtn.addEventListener('click', () => { tr.remove(); recompute(); });

    function toggleSkill(){
      skillSel.disabled = (typeSel.value !== '1'); // Excellence only
      skillSel.style.opacity = skillSel.disabled ? .5 : 1;
    }
    toggleSkill();

    typeSel.addEventListener('change', ()=>{ toggleSkill(); recompute(); });
    skillSel.addEventListener('change', recompute);
    tierInp.addEventListener('input', recompute);

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

    // store refs for recompute
    tr._refs = { typeSel, skillSel, tierInp, slotsCell };
    subTableBody.appendChild(tr);
    recompute();
  }

  // seed with one row
  addSubRow();

  // ----- Reads / Derived Helpers -----
  const num = id => Number($(id).value || 0);
  const setTxt = (id, v) => { $(id).textContent = String(v); };

  const modFromScore = score => Math.floor(score/2 - 5); // d20-like
  const scoreFromInvest = invest => 4 + invest;          // base 4 + invested (modifiers later)
  const milestoneCount = mod => Math.max(mod, 0);
  const tens = lvl => Math.floor(lvl/10);

  // Level from XP (closed-form from your sheet)
  function levelFromXP(xp){
    const k = Math.floor((-1 + Math.sqrt(1 + 8*(xp/100)))/2);
    return Math.min(k+1, 100);
  }

  // ID / IV table for intensities given Base Value
  function idIvFromBV(bv){
    if (bv <= 0) return ['—','—'];
    if (bv <= 7) return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10', 5];
    if (bv >= 18) return ['1d12', 6];
    return ['—','—'];
  }

  // Simple resistance/weakness derivation shell (we'll refine rules later)
  function rwFor(name, ivMap){
    // placeholder linear combo (uses your grid idea later):
    // keep zero until we wire exact grid math—UI shows a value that can go negative
    return 0 + (ivMap[name]||0)*0;
  }

  function readLevel(){
    const lvlInp = $('#c_level');
    const xpInp = $('#c_xp');
    let lvl = Number(lvlInp.value || 1);
    if (!lvl || lvl < 1){
      // derive from XP if level field empty/zero
      lvl = levelFromXP(Number(xpInp.value||0));
    }
    return Math.min(Math.max(lvl,1),100);
  }

  // ----- Recompute everything -----
  function recompute(){
    const lvl = readLevel();
    $('#c_level').value = String(lvl); // normalize

    // ---- Characteristics (mods & totals)
    const charInvest = {};
    const charScore = {};
    const charMod = {};

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

    // ---- Skills (base values)
    const skillInvest = {};
    const excellenceMap = {}; // skill -> bonus from Excellence tiers
    // collect sublimation Excellence bonuses
    const subRows = Array.from(subTableBody.children);
    let subUsed = 0;
    let tierMax = 1;

    subRows.forEach(tr => {
      const { typeSel, skillSel, tierInp, slotsCell } = tr._refs;
      const tier = Math.max(0, Number(tierInp.value||0));
      slotsCell.textContent = String(tier);
      subUsed += tier;
      if (typeSel.value === '1' && skillSel.value){ // Excellence
        excellenceMap[skillSel.value] = (excellenceMap[skillSel.value]||0) + tier;
      }
      tierMax = Math.max(tierMax, tier);
    });

    // skill base = invested + min(excellenceBonus, invested), capped later by skill cap
    CHAR_MAP.forEach(g => {
      g.skills.forEach(s => {
        const inv = Number($(`[data-s-invest="${s.key}"]`).value || 0);
        skillInvest[s.key] = inv;
        const bonus = Math.min(inv, excellenceMap[s.key] || 0);
        const base = inv + bonus + charMod[g.key]; // add linked characteristic mod
        $(`[data-s-mod="${s.key}"]`).textContent = String(bonus); // shows mod source (Excellence)
        $(`[data-s-base="${s.key}"]`).textContent = String(base);
      });
    });

    // ---- Points & Caps
    const cp_used = Object.values(charInvest).reduce((a,b)=>a+b,0);
    const cp_max = 22 + Math.floor((lvl-1)/9)*3; // from your hidden "cp_tot"
    const sp_used = Object.values(skillInvest).reduce((a,b)=>a+b,0);
    const sp_max  = 40 + (lvl-1)*2;              // from your hidden "sp_tot"
    const skill_cap = (lvl >= 50 ? 8 : lvl >= 40 ? 7 : lvl >= 30 ? 6 : lvl >= 20 ? 5 : lvl >= 10 ? 4 : 3);
    const char_cap = 10; // per spec (1–10) (score is 4+invest; invest cap UI is handled by min/max)

    setTxt('#cp_used', cp_used);
    setTxt('#cp_max', cp_max);
    setTxt('#sp_used', sp_used);
    setTxt('#sp_max', sp_max);
    setTxt('#skill_cap', skill_cap);
    setTxt('#char_cap', char_cap);

    // ---- Sublimation slots / tier cap
    const mile_pre = Math.max(charMod.pre || 0, 0);
    const sub_max = (mile_pre*2) + Math.floor(lvl/10);
    const tier_cap = Math.ceil(lvl/25);
    setTxt('#sub_used', subUsed);
    setTxt('#sub_max', sub_max);
    setTxt('#sub_tier', tier_cap);

    // ---- Derived core: HP/EN/FO/MO/ET/SP/TX caps
    const lvl_up_count = Math.max(lvl-1, 0);
    const mile_bod = Math.max(charMod.bod || 0, 0);
    const mile_wil = Math.max(charMod.wil || 0, 0);
    const mile_mag = Math.max(charMod.mag || 0, 0);
    const mile_dex = Math.max(charMod.dex || 0, 0);
    const mile_ref = Math.max(charMod.ref || 0, 0);
    const mile_wis = Math.max(charMod.wis || 0, 0);

    const sub_defense   = sumSubType('4'); // +12 HP per tier
    const sub_speed     = sumSubType('5'); // +1 MO per tier
    const sub_clarity   = sumSubType('8'); // +1 FO per, +? EN per (Endurance adds EN)
    const sub_endurance = sumSubType('6'); // +2 EN per tier

    const hp_max = 100 + lvl_up_count + (12*mile_bod) + (6*mile_wil) + (12*sub_defense);
    const en_max = 5 + Math.floor(lvl_up_count/5) + (2*mile_wil) + (4*mile_mag) + (2*sub_endurance);
    const fo_max = 2 + Math.floor(lvl_up_count/5) + (2*Math.max(charMod.pre,0)) + mile_wis + mile_wil + sub_clarity;
    const mo     = 4 + mile_dex + mile_ref + sub_speed;
    const et     = 1 + Math.floor(lvl_up_count/9) + mile_mag; // craftomancy alt later
    const cdc    = 6 + Math.floor(lvl/10) + sumSubType('7');  // + Devastation per tier

    setResource('#hp_cur','#hp_max','#hp_bar',hp_max,hp_max);
    setResource('#sp_cur','#sp_max','#sp_bar',0,Math.floor(hp_max*0.1)); // SP cap: 10% HP
    setResource('#en_cur','#en_max','#en_bar',Math.min(5,en_max),en_max);
    setResource('#fo_cur','#fo_max','#fo_bar',Math.min(2,fo_max),fo_max);

    // TX
    const resistance = Number($('[data-s-base="resistance"]')?.textContent||0);
    const alchemyBV  = Number($('[data-s-base="alchemy"]')?.textContent||0);
    const tx_max = resistance + alchemyBV;
    setResource('#tx_cur','#tx_max','#tx_bar',0,tx_max);

    // Enc
    const athletics = Number($('[data-s-base="athletics"]')?.textContent||0);
    const spiritBV  = Number($('[data-s-base="spirit"]')?.textContent||0);
    const enc_max = 10 + (athletics*5) + (spiritBV*2);
    setResource('#enc_cur','#enc_max','#enc_bar',0,enc_max);

    // Badges
    setTxt('#k_mo', mo);
    setTxt('#k_init', mo + mile_ref);
    setTxt('#k_et', et);
    setTxt('#k_cdc', cdc);

    // ---- Intensities: compute BV = invest + magic_mod (plus Excellence if you ever allow it here)
    const magic_mod = charMod.mag || 0;
    const ivMap = {};
    INTENSITIES.forEach(nm => {
      const inv = Number($(`[data-i-invest="${nm}"]`).value || 0);
      const mod = magic_mod; // char mod
      const base = (inv>0 ? inv + mod : 0); // specialist rule handled later when we add “primary nature”
      const [ID, IV] = idIvFromBV(base);
      ivMap[nm] = Number(IV || 0);

      $(`[data-i-mod="${nm}"]`).textContent = String(mod);
      $(`[data-i-base="${nm}"]`).textContent = String(base);
      $(`[data-i-id="${nm}"]`).textContent = String(ID);
      $(`[data-i-iv="${nm}"]`).textContent = String(IV||'—');
    });
    // Resistance/Weakness placeholder (wire the full grid later)
    INTENSITIES.forEach(nm => {
      $(`[data-i-rw="${nm}"]`).textContent = String(rwFor(nm, ivMap));
    });

    // ---- Enforce caps visually (warnings)
    decorateCaps(skill_cap, char_cap, sp_max, cp_max, sub_max, tier_cap);
  }

  function sumSubType(code){
    return Array.from($('#subTable tbody').children).reduce((acc, tr) => {
      const { typeSel, tierInp } = tr._refs;
      return acc + (typeSel.value === code ? Math.max(0,Number(tierInp.value||0)) : 0);
    }, 0);
  }

  function setResource(curSel, maxSel, barSel, cur, max){
    setTxt(maxSel, max);
    // keep current <= max
    cur = Math.min(Math.max(cur, 0), Math.max(0,max));
    setTxt(curSel, cur);
    const pct = max>0 ? Math.round((cur/max)*100) : 0;
    $(barSel).style.width = `${pct}%`;
  }

  function decorateCaps(skillCap, charCap, spMax, cpMax, subMax, tierCap){
    // highlight overflows
    // Skills
    CHAR_MAP.forEach(g => g.skills.forEach(s => {
      const inp = $(`[data-s-invest="${s.key}"]`);
      const val = Number(inp.value||0);
      inp.style.borderColor = (val>skillCap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    }));
    // Characteristics (invest cap 16 by UI; total cap 20 -> invest 16 is fine)
    CHAR_MAP.forEach(g => {
      const inp = $(`[data-c-invest="${g.investKey}"]`);
      const sc = scoreFromInvest(Number(inp.value||0));
      inp.style.borderColor = (sc>4+16 || sc>20) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
    // Totals
    const spUsed = Number($('#sp_used').textContent||0);
    $('#sp_used').classList.toggle('danger', spUsed>spMax);
    const cpUsed = Number($('#cp_used').textContent||0);
    $('#cp_used').classList.toggle('danger', cpUsed>cpMax);
    const subUsed = Number($('#sub_used').textContent||0);
    $('#sub_used').classList.toggle('danger', subUsed>subMax);

    // Tier cap per row
    Array.from($('#subTable tbody').children).forEach(tr=>{
      const { tierInp } = tr._refs;
      const t = Number(tierInp.value||0);
      tierInp.style.borderColor = (t>tierCap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
  }

  // ----- Events -----
  // Recompute on inputs
  ['#c_level','#c_xp','#c_name','#p_height','#p_weight','#p_bday','#p_backstory','#p_notes']
    .forEach(sel => $(sel).addEventListener('input', recompute));
  // Characteristics & skills
  $$('#charSkillContainer input').forEach(inp => inp.addEventListener('input', recompute));
  // Intensities
  $$('#intensityTable [data-i-invest]').forEach(inp => inp.addEventListener('input', recompute));

  // Initial compute
  recompute();
})();