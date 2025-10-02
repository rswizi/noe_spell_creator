(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

  // ---------- Tabs ----------
  $$('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const key = btn.dataset.tab;
      $$('.tabpan').forEach(p => p.classList.remove('active'));
      $(`#tab-${key}`).classList.add('active');
    });
  });

  // ---------- Avatar ----------
  $('#avatarUrl').addEventListener('input', () => {
    $('#charAvatar').src = $('#avatarUrl').value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
    queueSave();
  });

  // ---------- Data model ----------
  // Characteristics + skills map
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

  // ---------- Build UI ----------
  const charSkillContainer = $('#charSkillContainer');

  function buildCharCards(){
    charSkillContainer.innerHTML = '';
    CHAR_MAP.forEach(group => {
      const card = document.createElement('div');
      card.className = 'char-card';

      // header
      const h = document.createElement('div');
      h.className = 'card-h';
      h.innerHTML = `
        <div>${group.label}</div>
        <div class="mini">[ Total | Milestone ]</div>
      `;
      card.appendChild(h);

      const rows = document.createElement('div');
      rows.className = 'rows';

      // Characteristic row
      const crow = rowLine('Characteristic', {
        invested: {attr:`data-c-invest="${group.investKey}"`, min:0, max:16},
        milestone: {attr:`data-c-mil="${group.key}"`},
        total:     {attr:`data-c-total="${group.key}"`},
        openableId:`csrc-${group.key}`
      });
      rows.appendChild(crow);

      // Skills
      group.skills.forEach(s=>{
        const srow = rowLine('— '+s.label, {
          invested: {attr:`data-s-invest="${s.key}"`, min:0, max:8},
          milestone:{attr:`data-s-mil="${s.key}"`}, // excellence bonus (not editable)
          total:    {attr:`data-s-base="${s.key}"`},
          openableId:`ssrc-${s.key}`,
          miniRight:'(bonus <span class="mono" data-s-bonus="'+s.key+'">0</span>)'
        });
        rows.appendChild(srow);
      });

      card.appendChild(rows);
      charSkillContainer.appendChild(card);
    });
  }

  function rowLine(label, opts){
    const wrap = document.createElement('div');
    wrap.className='rowline';
    wrap.innerHTML = `
      <div>
        <button class="btn ghost" data-toggle="${opts.openableId}" style="padding:6px 8px;font-size:12px">${label}</button>
        ${opts.miniRight? `<span class="mini" style="margin-left:8px">${opts.miniRight}</span>`:''}
      </div>
      <div><input class="input" type="number" ${opts.invested.attr} min="${opts.invested.min}" max="${opts.invested.max}" value="0"></div>
      <div class="mono"><span ${opts.milestone.attr}>0</span> | <span ${opts.total.attr}>4</span></div>
      <div class="src" id="${opts.openableId}">
        <table><tbody ${opts.openableId.startsWith('csrc')?`data-c-modsrc="${opts.openableId}"`:`data-s-modsrc="${opts.openableId}"`}></tbody></table>
      </div>
    `;
    // toggle
    wrap.querySelector(`[data-toggle="${opts.openableId}"]`).addEventListener('click', ()=>{
      wrap.classList.toggle('open');
    });
    return wrap;
  }

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
  const ALL_SKILLS = CHAR_MAP.flatMap(g=>g.skills).map(s=>({key:s.key, label:s.label}));
  const subTableBody = $('#subTable tbody');

  $('#btnAddSub').addEventListener('click', ()=> addSubRow());

  function addSubRow(defaults = {type:'2', skill:'', tier:1}){
    const tr = document.createElement('tr');

    const typeSel = document.createElement('select');
    SUB_TYPES.forEach(t=>{
      const o = document.createElement('option');
      o.value=t.id; o.textContent=t.label;
      if(defaults.type===t.id) o.selected=true;
      typeSel.appendChild(o);
    });

    const skillSel = document.createElement('select');
    const empty = document.createElement('option');
    empty.value=''; empty.textContent='—';
    skillSel.appendChild(empty);
    ALL_SKILLS.forEach(s=>{
      const o = document.createElement('option'); o.value=s.key; o.textContent=s.label;
      if(defaults.skill===s.key) o.selected=true;
      skillSel.appendChild(o);
    });

    const tierInp = document.createElement('input');
    tierInp.type='number'; tierInp.min='0'; tierInp.max='4'; tierInp.value=defaults.tier;

    const slotsCell = document.createElement('td');
    slotsCell.className='right mono';
    slotsCell.textContent = String(defaults.tier);

    const delBtn = document.createElement('button');
    delBtn.className='btn ghost';
    delBtn.textContent='Remove';
    delBtn.addEventListener('click', ()=>{ tr.remove(); recompute(); queueSave(); });

    function toggleSkill(){
      skillSel.disabled = (typeSel.value!=='1');
      skillSel.style.opacity = skillSel.disabled ? .5 : 1;
    }
    toggleSkill();

    typeSel.addEventListener('change', ()=>{ toggleSkill(); recompute(); queueSave(); });
    skillSel.addEventListener('change', ()=>{ recompute(); queueSave(); });
    tierInp.addEventListener('input', ()=>{ slotsCell.textContent = tierInp.value; recompute(); queueSave(); });

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
  // seed one row
  addSubRow({type:'1', skill:'accuracy', tier:2});

  // ---------- Intensities ----------
  const tbodyInt = $('#intensityTable tbody');
  INTENSITIES.forEach(nm=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${nm}</td>
      <td><input class="input" type="number" min="0" max="8" value="0" data-i-invest="${nm}"></td>
      <td class="mono" data-i-mil="${nm}">0</td>
      <td class="mono" data-i-base="${nm}">0</td>
      <td class="mono" data-i-id="${nm}">—</td>
      <td class="mono" data-i-iv="${nm}">—</td>
      <td class="mono right" data-i-rw="${nm}">0</td>
    `;
    tbodyInt.appendChild(tr);
  });

  // ---------- Helpers ----------
  const setTxt = (sel, v) => { $(sel).textContent = String(v); };
  const modFromScore = score => Math.floor(score/2 - 5);
  const scoreFromInvest = invest => 4 + invest;
  const milestoneCount = v => Math.max(modFromScore(v), 0); // positive milestones only
  const levelFromXP = xp => Math.min(Math.floor((-1 + Math.sqrt(1 + 8*(xp/100)))/2)+1, 100);

  function idIvFromBV(bv){
    if (bv <= 0) return ['—','—'];
    if (bv <= 7)  return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10',5];
    return ['1d12',6];
  }

  function replaceOnType(inp){
    inp.addEventListener('focus', ()=>{ inp.select?.(); inp.dataset.touched="0"; });
    inp.addEventListener('beforeinput', (ev)=>{
      if (inp.dataset.touched!=="1"){
        if (ev.inputType?.startsWith('insert')) inp.select?.();
        inp.dataset.touched="1";
      }
    });
  }

  function attachNumeric(){
    $$('#charSkillContainer input[type="number"], #intensityTable input[type="number"]').forEach(inp=>{
      replaceOnType(inp);
      inp.setAttribute('inputmode','numeric');
      inp.setAttribute('pattern','[0-9]*');
      inp.addEventListener('input', ()=>{ recompute(); queueSave(); });
    });
    $$('#subTable tbody input[type="number"]').forEach(inp=>{
      replaceOnType(inp);
      inp.setAttribute('inputmode','numeric');
      inp.setAttribute('pattern','[0-9]*');
    });
  }

  // ---------- Compute ----------
  function readLevel(){
    const lvlInp = $('#c_level');
    const xpInp = $('#c_xp');
    let lvl = Number(lvlInp.value || 1);
    if (!lvl || lvl < 1){
      lvl = levelFromXP(Number(xpInp.value||0));
      $('#c_level').value = String(lvl);
    }
    return Math.min(Math.max(lvl,1),100);
  }

  function sumSubType(code){
    return Array.from($('#subTable tbody').children).reduce((acc, tr) => {
      const { typeSel, tierInp } = tr._refs;
      return acc + (typeSel.value === code ? Math.max(0,Number(tierInp.value||0)) : 0);
    }, 0);
  }

  function collectExcellenceBonuses(){
    // skillKey -> tier sum
    const map = {};
    Array.from($('#subTable tbody').children).forEach(tr=>{
      const { typeSel, skillSel, tierInp } = tr._refs;
      if (typeSel.value==='1' && skillSel.value){
        map[skillSel.value] = (map[skillSel.value]||0) + Math.max(0,Number(tierInp.value||0));
      }
    });
    return map;
  }

  function addSourcesTo(tableSel, rows){
    const tbody = $(`[${tableSel}]`);
    if (!tbody) return;
    tbody.innerHTML = '';
    rows.forEach(r=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${r.name}</td><td class="right mono">${r.val>0?`+${r.val}`:r.val}</td>`;
      tbody.appendChild(tr);
    });
  }

  function recompute(){
    const lvl = readLevel();

    // Characteristic investments -> scores -> milestones
    const charInvest = {};
    const charScore  = {};
    const charMil    = {};
    CHAR_MAP.forEach(g=>{
      const inv = Number($(`[data-c-invest="${g.investKey}"]`).value||0);
      const score = scoreFromInvest(inv);
      const mil = milestoneCount(score);
      charInvest[g.key]=inv; charScore[g.key]=score; charMil[g.key]=mil;
      $(`[data-c-total="${g.key}"]`).textContent = String(score);
      $(`[data-c-mil="${g.key}"]`).textContent   = String(mil);
      // sources for characteristic (none yet, reserved)
      addSourcesTo(`data-c-modsrc="csrc-${g.key}"`, []);
    });

    // Sublimation bookkeeping
    const sub_defense   = sumSubType('4'); // +12 HP per tier
    const sub_speed     = sumSubType('5'); // +1 MO per
    const sub_clarity   = sumSubType('8'); // +1 FO per
    const sub_endurance = sumSubType('6'); // +2 EN per
    const sub_devast    = sumSubType('7'); // +Condition DC per tier

    const excellence = collectExcellenceBonuses(); // skill -> tiers

    // Skills
    const skillInvest = {};
    CHAR_MAP.forEach(g=>{
      g.skills.forEach(s=>{
        const inv = Number($(`[data-s-invest="${s.key}"]`).value || 0);
        const bonus = Math.min(inv, excellence[s.key]||0); // Excellence cannot exceed invested
        const base = inv + bonus + (charMil[g.key]||0);
        skillInvest[s.key]=inv;
        $(`[data-s-bonus="${s.key}"]`).textContent = String(bonus);
        $(`[data-s-mil="${s.key}"]`).textContent   = String(charMil[g.key]||0);
        $(`[data-s-base="${s.key}"]`).textContent  = String(base);
        addSourcesTo(`data-s-modsrc="ssrc-${s.key}"`,
          bonus>0 ? [{name:`Sublimation • Excellence (Tier ${excellence[s.key]})`, val:+bonus}] : []
        );
      });
    });

    // Points & Caps
    const cp_used = Object.values(charInvest).reduce((a,b)=>a+b,0);
    const cp_max  = 22 + Math.floor((lvl-1)/9)*3;
    const sp_used = Object.values(skillInvest).reduce((a,b)=>a+b,0);
    const sp_max  = 40 + (lvl-1)*2;
    const skill_cap = (lvl >= 50 ? 8 : lvl >= 40 ? 7 : lvl >= 30 ? 6 : lvl >= 20 ? 5 : lvl >= 10 ? 4 : 3);
    const char_cap  = (lvl >= 55 ? 10 : lvl >= 46 ? 9 : lvl >= 37 ? 8 : lvl >= 28 ? 7 : lvl >= 19 ? 6 : lvl >= 10 ? 5 : 4);

    setTxt('#cp_used', cp_used);
    setTxt('#cp_max', cp_max);
    setTxt('#sp_used', sp_used);
    setTxt('#sp_max', sp_max);
    setTxt('#skill_cap', skill_cap);
    setTxt('#char_cap', char_cap);

    // Sublimation caps
    const mile_pre = Math.max(charMil.pre||0,0);
    const sub_max  = (mile_pre*2) + Math.floor(lvl/10);
    const tier_cap = Math.ceil(lvl/25);
    const sub_used = Array.from(subTableBody.children).reduce((acc, tr)=>acc+Number(tr._refs.tierInp.value||0),0);
    setTxt('#sub_used', sub_used);
    setTxt('#sub_max', sub_max);
    setTxt('#sub_tier', tier_cap);

    // Derived resources
    const lvl_up = Math.max(lvl-1,0);
    const hp_max = 100 + lvl_up + 12*(charMil.bod||0) + 6*(charMil.wil||0) + 12*sub_defense;
    const en_max = 5   + Math.floor(lvl_up/5) + (charMil.wil||0) + 2*(charMil.mag||0) + 2*sub_endurance;
    const fo_max = 2   + Math.floor(lvl_up/5) + (charMil.wil||0) + (charMil.pre||0) + sub_clarity;
    const mo     = 4   + (charMil.dex||0) + (charMil.ref||0) + sub_speed;
    const et     = 1   + Math.floor(lvl/10) + (charMil.mag||0);
    const cdc    = 6   + Math.floor(lvl/10) + sub_devast;

    setResource('#hp_cur','#hp_max','#hp_bar',hp_max,hp_max);
    setResource('#sp_cur','#sp_max','#sp_bar',0,Math.floor(hp_max*0.1));
    setResource('#en_cur','#en_max','#en_bar',Math.min(5,en_max),en_max);
    setResource('#fo_cur','#fo_max','#fo_bar',Math.min(2,fo_max),fo_max);

    const resistanceBV = Number($('[data-s-base="resistance"]')?.textContent||0);
    const alchemyBV    = Number($('[data-s-base="alchemy"]')?.textContent||0);
    setResource('#tx_cur','#tx_max','#tx_bar',0,resistanceBV+alchemyBV);

    const athleticsBV  = Number($('[data-s-base="athletics"]')?.textContent||0);
    const spiritBV     = Number($('[data-s-base="spirit"]')?.textContent||0);
    setResource('#enc_cur','#enc_max','#enc_bar',0,10 + athleticsBV*5 + spiritBV*2);

    setTxt('#k_mo', mo);
    setTxt('#k_init', mo + (charMil.ref||0));
    setTxt('#k_et', et);
    setTxt('#k_cdc', cdc);

    // Intensities (based on MAG milestone)
    const magMil = charMil.mag||0;
    const ivMap = {};
    INTENSITIES.forEach(nm=>{
      const inv = Number($(`[data-i-invest="${nm}"]`).value||0);
      const mil = magMil;
      const base = (inv>0 ? inv + mil : 0);
      const [ID, IV] = idIvFromBV(base);
      ivMap[nm] = Number(IV||0);

      $(`[data-i-mil="${nm}"]`).textContent  = String(mil);
      $(`[data-i-base="${nm}"]`).textContent = String(base);
      $(`[data-i-id="${nm}"]`).textContent   = String(ID);
      $(`[data-i-iv="${nm}"]`).textContent   = String(IV||'—');
      $(`[data-i-rw="${nm}"]`).textContent   = '0'; // placeholder grid
    });

    // Visual warnings
    $$('#charSkillContainer [data-s-invest]').forEach(inp=>{
      const val = Number(inp.value||0);
      inp.style.borderColor = (val>skill_cap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
    $$('#charSkillContainer [data-c-invest]').forEach(inp=>{
      const sc = scoreFromInvest(Number(inp.value||0));
      inp.style.borderColor = (sc>4+16 || sc>20) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
    $('#sp_used').classList.toggle('danger', sp_used>sp_max);
    $('#cp_used').classList.toggle('danger', cp_used>cp_max);
    $('#sub_used').classList.toggle('danger', sub_used>sub_max);
    Array.from(subTableBody.children).forEach(tr=>{
      const t = Number(tr._refs.tierInp.value||0);
      tr._refs.tierInp.style.borderColor = (t>tier_cap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
  }

  function setResource(curSel, maxSel, barSel, cur, max){
    setTxt(maxSel, max);
    cur = Math.min(Math.max(cur,0), Math.max(0,max));
    setTxt(curSel, cur);
    const pct = max>0 ? Math.round((cur/max)*100) : 0;
    $(barSel).style.width = `${pct}%`;
  }

  // ---------- Autosave ----------
  const CHARACTER_ID = 'demo-1'; // swap for real id when integrating

  async function saveToServer(payload){
    try{
      await fetch(`/api/character/${CHARACTER_ID}`, {
        method:'PUT',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
    }catch(e){
      // best-effort fallback to localStorage
      localStorage.setItem('character_autosave', JSON.stringify(payload));
    }
  }

  async function loadFromServer(){
    try{
      const r = await fetch(`/api/character/${CHARACTER_ID}`);
      if (r.ok){
        return await r.json();
      }
    }catch(e){}
    const raw = localStorage.getItem('character_autosave');
    return raw ? JSON.parse(raw) : null;
  }

  function readState(){
    const state = {
      id: CHARACTER_ID,
      avatar: $('#avatarUrl').value || '',
      name: $('#c_name').value || '',
      level: Number($('#c_level').value||1),
      xp: Number($('#c_xp').value||0),
      charInvest: {},
      skillInvest: {},
      intensities: {},
      sublimations: [],
      personal: {
        height: $('#p_height').value||'',
        weight: $('#p_weight').value||'',
        bday:   $('#p_bday').value||'',
        backstory: $('#p_backstory').value||'',
        notes:     $('#p_notes').value||'',
      }
    };
    CHAR_MAP.forEach(g=>{
      state.charInvest[g.key] = Number($(`[data-c-invest="${g.investKey}"]`).value||0);
      g.skills.forEach(s=>{
        state.skillInvest[s.key] = Number($(`[data-s-invest="${s.key}"]`).value||0);
      });
    });
    INTENSITIES.forEach(nm=>{
      state.intensities[nm] = Number($(`[data-i-invest="${nm}"]`).value||0);
    });
    Array.from(subTableBody.children).forEach(tr=>{
      const {typeSel,skillSel,tierInp} = tr._refs;
      state.sublimations.push({type:typeSel.value, skill:skillSel.value, tier:Number(tierInp.value||0)});
    });
    return state;
  }

  function writeState(s){
    if(!s) return;
    $('#avatarUrl').value = s.avatar||'';
    $('#charAvatar').src = s.avatar||'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
    $('#c_name').value = s.name||'';
    $('#c_level').value = s.level||1;
    $('#c_xp').value = s.xp||0;
    if (s.personal){
      $('#p_height').value = s.personal.height||'';
      $('#p_weight').value = s.personal.weight||'';
      $('#p_bday').value   = s.personal.bday||'';
      $('#p_backstory').value = s.personal.backstory||'';
      $('#p_notes').value     = s.personal.notes||'';
    }
    // investments
    CHAR_MAP.forEach(g=>{
      const v = s.charInvest?.[g.key] ?? 0;
      $(`[data-c-invest="${g.investKey}"]`).value = v;
      g.skills.forEach(sk=>{
        const sv = s.skillInvest?.[sk.key] ?? 0;
        $(`[data-s-invest="${sk.key}"]`).value = sv;
      });
    });
    INTENSITIES.forEach(nm=>{
      $(`[data-i-invest="${nm}"]`).value = s.intensities?.[nm] ?? 0;
    });
    // sublimations
    subTableBody.innerHTML='';
    (s.sublimations||[]).forEach(x=> addSubRow(x));
  }

  let saveTimer = null;
  function queueSave(){
    const payload = readState();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(()=> saveToServer(payload), 350);
  }

  // ---------- Events ----------
  ['#c_level','#c_xp','#c_name','#p_height','#p_weight','#p_bday','#p_backstory','#p_notes','#avatarUrl']
    .forEach(sel => $(sel).addEventListener('input', ()=>{ recompute(); queueSave(); }));

  // ---------- Init ----------
  buildCharCards();
  attachNumeric();
  (async ()=>{
    const s = await loadFromServer();
    if (s) writeState(s);
    recompute();
  })();
})();