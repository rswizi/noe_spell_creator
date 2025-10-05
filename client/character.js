/* character.js — wired to /characters endpoints with autosave (debounced) */

(() => {
  // ---------- Tiny DOM helpers ----------
  const $  = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const num = v => (v===''||v==null) ? 0 : Number(v);

  // ---------- API ----------
  const API = {
    async createCharacter(payload) {
      const r = await fetch('/characters', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload),
        credentials: 'include',
      });
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
    async getCharacter(id) {
      const r = await fetch(`/characters/${encodeURIComponent(id)}`, { credentials: 'include' });
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
    async patchCharacter(id, delta) {
      const r = await fetch(`/characters/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(delta),
        credentials: 'include',
      });
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
  };

  // ---------- Global state ----------
  let CHARACTER_ID = null;       // set after first save or load
  let SAVE_TIMER   = null;       // debounce timer
  const SAVE_DELAY = 350;

  // ---------- Game math helpers ----------
  const modFromScore  = score => Math.floor(score/2 - 5);   // d20-like
  const scoreFromInv  = invest => 4 + invest;               // base 4 + invested
  const tens          = lvl => Math.floor(lvl / 10);
  const miles         = m => Math.max(m, 0);                // positive milestones only

  // Intensity Dice / IV from Base Value
  function idIvFromBV(bv){
    if (bv <= 0) return ['—','—'];
    if (bv <= 7)  return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10', 5];
    return ['1d12', 6];
  }

  // ---------- Static maps (must match your HTML data-… keys) ----------
  const GROUPS = [
    { key:'ref', label:'Reflex',    investKey:'reflexp',    skills:['technicity','dodge','tempo','reactivity'] },
    { key:'dex', label:'Dexterity', investKey:'dexterityp', skills:['accuracy','evasion','stealth','acrobatics'] },
    { key:'bod', label:'Body',      investKey:'bodyp',      skills:['brutality','blocking','resistance','athletics'] },
    { key:'wil', label:'Willpower', investKey:'willpowerp', skills:['intimidation','spirit','instinct','absorption'] },
    { key:'mag', label:'Magic',     investKey:'magicp',     skills:['aura','incantation','enchantment','restoration','potential'] },
    { key:'pre', label:'Presence',  investKey:'presencep',  skills:['taming','charm','charisma','deception','persuasion'] },
    { key:'wis', label:'Wisdom',    investKey:'wisdomp',    skills:['survival','education','perception','psychology','investigation'] },
    { key:'tec', label:'Tech',      investKey:'techp',      skills:['crafting','soh','alchemy','medecine','engineering'] },
  ];
  const INTENSITIES = ['Fire','Water','Earth','Wind','Lightning','Moon','Sun','Ki'];

  // ---------- Sublimation helpers ----------
  function readSublimationsFromUI(){
    const rows = $('#subTable tbody') ? Array.from($('#subTable tbody').children) : [];
    return rows.map(tr => {
      const type  = tr._refs?.typeSel?.value || '';
      const skill = tr._refs?.skillSel?.value || '';
      const tier  = num(tr._refs?.tierInp?.value || 0);
      return { type, skill, tier };
    });
  }
  function sumSublimation(typeCode){
    return readSublimationsFromUI()
      .filter(s => s.type === typeCode)
      .reduce((a,b)=>a + Math.max(0, b.tier), 0);
  }

  // ---------- Serialization ----------
  function readCharacteristicsFromUI(){
    const out = {};
    GROUPS.forEach(g => {
      const inv = num($(`[data-c-invest="${g.investKey}"]`)?.value || 0);
      const mod = 0; // external char modifier (from traits/etc) — locked to 0 for now
      out[g.key] = { invest: inv, modifier: mod };
    });
    return out;
  }

  function readSkillsFromUI(){
    const out = {};
    GROUPS.forEach(g => {
      g.skills.forEach(s => {
        const inv = num($(`[data-s-invest="${s}"]`)?.value || 0);
        // Skill modifier currently comes only from Excellence sublimation (capped to invest)
        const excel = readSublimationsFromUI().filter(x=>x.type==='1' && x.skill===s)
                         .reduce((a,b)=>a + Math.max(0,b.tier), 0);
        const bonus = Math.min(inv, excel);
        out[s] = { invest: inv, modifier: bonus };
      });
    });
    // Intensities read as skills too (invest, mod = magic milestone)
    INTENSITIES.forEach(nm => {
      const inv = num($(`[data-i-invest="${nm}"]`)?.value || 0);
      out[`intensity_${nm}`] = { invest: inv, modifier: 0 }; // actual mod added via linked char mod (MAG)
    });
    return out;
  }

  function readPersonal(){
    return {
      height:   $('#p_height')?.value || '',
      weight:   $('#p_weight')?.value || '',
      birthday: $('#p_bday')?.value   || '',
      backstory:$('#p_backstory')?.value || '',
      notes:    $('#p_notes')?.value  || '',
    };
  }

  function serializeCharacter(){
    const name   = $('#c_name')?.value || '';
    const level  = num($('#c_level')?.value || 1);
    const xp     = num($('#c_xp')?.value || 0);
    const avatar_url = $('#avatarUrl')?.value || '';

    return {
      name, level, xp, avatar_url,
      // current resources (UI currently derived-only; keep at zero unless you track currents)
      hp: 0, sp: 0, en: 0, fo: 0, tx: 0, enc: 0,
      characteristics: readCharacteristicsFromUI(),
      skills:          readSkillsFromUI(),
      intensities:     INTENSITIES.reduce((acc,nm) => {
                         acc[nm] = { invest: num($(`[data-i-invest="${nm}"]`)?.value || 0) };
                         return acc;
                       }, {}),
      sublimations:    readSublimationsFromUI(),
      ...readPersonal(),
    };
  }

  // ---------- Debounced save ----------
  function scheduleSave(deltaProducer){
    if (SAVE_TIMER) clearTimeout(SAVE_TIMER);
    SAVE_TIMER = setTimeout(async () => {
      try {
        const delta = typeof deltaProducer === 'function' ? deltaProducer() : deltaProducer;
        if (!CHARACTER_ID) {
          // first save: create with the whole doc
          const created = await API.createCharacter(serializeCharacter());
          CHARACTER_ID = created.character.id;
        } else {
          await API.patchCharacter(CHARACTER_ID, delta);
        }
      } catch (err) {
        console.error('Save failed', err);
      }
    }, SAVE_DELAY);
  }

  // ---------- Recompute view (derived) ----------
  function recompute(){
    const lvl  = Math.min(Math.max(num($('#c_level')?.value || 1),1), 100);
    $('#c_level') && ($('#c_level').value = String(lvl));

    // char scores & milestones
    const cInv = readCharacteristicsFromUI();
    const cScore = {};
    const cMod   = {};
    Object.entries(cInv).forEach(([k, o]) => {
      const score = scoreFromInv(o.invest + num(o.modifier||0)); // characteristic modifier applies to score
      cScore[k] = score;
      cMod[k]   = modFromScore(score); // Milestone (char mod to skills)
      // write UI totals if present
      $(`[data-c-total="${k}"]`)    && ($(`[data-c-total="${k}"]`).textContent = String(score));
      $(`[data-c-milestone="${k}"]`)&& ($(`[data-c-milestone="${k}"]`).textContent = String(cMod[k]));
    });

    // Sublimation buckets
    const sub_defense   = sumSublimation('4'); // +12 HP / tier
    const sub_speed     = sumSublimation('5'); // +1 MO / tier
    const sub_clarity   = sumSublimation('8'); // +1 FO / tier
    const sub_endurance = sumSublimation('6'); // +2 EN / tier
    const sub_devast    = sumSublimation('7'); // + Condition DC per tier

    // skills base values (invest + skill modifier + linked char milestone)
    GROUPS.forEach(g => {
      g.skills.forEach(s => {
        const inv   = num($(`[data-s-invest="${s}"]`)?.value || 0);
        const excel = readSublimationsFromUI().filter(x=>x.type==='1' && x.skill===s)
                         .reduce((a,b)=>a + Math.max(0,b.tier), 0);
        const sMod  = Math.min(inv, excel); // capped to invest
        const base  = inv + sMod + cMod[g.key];
        $(`[data-s-mod="${s}"]`)   && ($(`[data-s-mod="${s}"]`).textContent  = String(sMod));
        $(`[data-s-base="${s}"]`)  && ($(`[data-s-base="${s}"]`).textContent = String(base));
      });
    });

    // intensities base values = invest + MAG milestone (only if invest>0)
    const magMil = cMod.mag ?? cMod['mag'] ?? 0;
    INTENSITIES.forEach(nm => {
      const inv = num($(`[data-i-invest="${nm}"]`)?.value || 0);
      const base = inv > 0 ? inv + magMil : 0;
      const [ID, IV] = idIvFromBV(base);
      $(`[data-i-mod="${nm}"]`)  && ($(`[data-i-mod="${nm}"]`).textContent  = String(magMil));
      $(`[data-i-base="${nm}"]`) && ($(`[data-i-base="${nm}"]`).textContent = String(base));
      $(`[data-i-id="${nm}"]`)   && ($(`[data-i-id="${nm}"]`).textContent   = String(ID));
      $(`[data-i-iv="${nm}"]`)   && ($(`[data-i-iv="${nm}"]`).textContent   = String(IV==='—'? '—' : IV));
    });

    // points & caps
    const lvl_up_count = Math.max(lvl-1,0);
    const cp_used = Object.values(cInv).reduce((a,b)=>a + num(b.invest||0), 0);
    const cp_max  = 22 + Math.floor(lvl_up_count/9)*3;
    const skillInv = readSkillsFromUI();
    // only real skills (not intensity_* internal keys) for SP spent
    const sp_used = Object.entries(skillInv)
      .filter(([k]) => !k.startsWith('intensity_'))
      .reduce((a,[,v]) => a + num(v.invest||0), 0);
    const sp_max  = 40 + lvl_up_count*2;
    const skill_cap = (lvl >= 50 ? 8 : lvl >= 40 ? 7 : lvl >= 30 ? 6 : lvl >= 20 ? 5 : lvl >= 10 ? 4 : 3);

    $('#cp_used') && ($('#cp_used').textContent = String(cp_used));
    $('#cp_max')  && ($('#cp_max').textContent  = String(cp_max));
    $('#sp_used') && ($('#sp_used').textContent = String(sp_used));
    $('#sp_max')  && ($('#sp_max').textContent  = String(sp_max));
    $('#skill_cap') && ($('#skill_cap').textContent = String(skill_cap));

    // Sublimation slots cap
    const mile_pre = miles(cMod.pre ?? cMod['pre'] ?? 0);
    const sub_max  = (mile_pre*2) + tens(lvl);
    const tier_cap = Math.ceil(lvl/25);
    const sub_used = readSublimationsFromUI().reduce((a,b)=>a + Math.max(0, b.tier), 0);
    $('#sub_max') && ($('#sub_max').textContent = String(sub_max));
    $('#sub_used')&& ($('#sub_used').textContent= String(sub_used));
    $('#sub_tier')&& ($('#sub_tier').textContent= String(tier_cap));

    // Resources (max)
    const mile_bod = miles(cMod.bod ?? cMod['bod'] ?? 0);
    const mile_wil = miles(cMod.wil ?? cMod['wil'] ?? 0);
    const mile_mag = miles(magMil);
    const mile_dex = miles(cMod.dex ?? cMod['dex'] ?? 0);
    const mile_ref = miles(cMod.ref ?? cMod['ref'] ?? 0);
    const mile_wis = miles(cMod.wis ?? cMod['wis'] ?? 0);

    const hp_max = 100 + lvl_up_count + (12*mile_bod) + (6*mile_wil) + (12*sub_defense);
    const en_max = 5 + Math.floor(lvl_up_count/5) + (2*mile_wil) + (4*mile_mag) + (2*sub_endurance);
    const fo_max = 2 + Math.floor(lvl_up_count/5) + (2*mile_pre) + mile_wis + mile_wil + sub_clarity;
    const mo     = 4 + mile_dex + mile_ref + sub_speed;
    const et     = 1 + Math.floor(lvl_up_count/9) + mile_mag;
    const cdc    = 6 + tens(lvl) + sub_devast;

    setBar('#hp_cur','#hp_max','#hp_bar', hp_max, hp_max);
    setBar('#sp_cur','#sp_max','#sp_bar', 0, Math.floor(hp_max*0.1));
    setBar('#en_cur','#en_max','#en_bar', Math.min(5,en_max), en_max);
    setBar('#fo_cur','#fo_max','#fo_bar', Math.min(2,fo_max), fo_max);

    // TX & Enc caps (need base values of Resistance / Alchemy / Athletics / Spirit)
    const baseR = textNum($('[data-s-base="resistance"]'));
    const baseA = textNum($('[data-s-base="alchemy"]'));
    const tx_max = baseR + baseA;
    setBar('#tx_cur','#tx_max','#tx_bar', 0, tx_max);

    const baseAth = textNum($('[data-s-base="athletics"]'));
    const baseSpi = textNum($('[data-s-base="spirit"]'));
    const enc_max = 10 + (baseAth*5) + (baseSpi*2);
    setBar('#enc_cur','#enc_max','#enc_bar', 0, enc_max);

    // header badges
    $('#k_mo')   && ($('#k_mo').textContent   = String(mo));
    $('#k_init') && ($('#k_init').textContent = String(mo + mile_ref));
    $('#k_et')   && ($('#k_et').textContent   = String(et));
    $('#k_cdc')  && ($('#k_cdc').textContent  = String(cdc));
  }

  function textNum(el){ return el ? num(el.textContent || 0) : 0; }

  function setBar(curSel, maxSel, barSel, cur, max){
    const curEl = $(curSel), maxEl = $(maxSel), barEl = $(barSel);
    if (maxEl) maxEl.textContent = String(max);
    if (curEl) curEl.textContent = String(Math.min(cur, max));
    if (barEl) barEl.style.width = (max>0 ? Math.round((cur/max)*100) : 0) + '%';
  }

  // ---------- Hydration ----------
  function hydrateUI(doc){
    $('#c_name')   && ($('#c_name').value = doc.name || '');
    $('#c_level')  && ($('#c_level').value = String(doc.level || 1));
    $('#c_xp')     && ($('#c_xp').value    = String(doc.xp || 0));
    $('#avatarUrl')&& ($('#avatarUrl').value = doc.avatar_url || '');
    $('#charAvatar')&&($('#charAvatar').src = doc.avatar_url || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg');

    // characteristics
    if (doc.characteristics){
      GROUPS.forEach(g=>{
        const inv = doc.characteristics[g.key]?.invest ?? 0;
        const inp = $(`[data-c-invest="${g.investKey}"]`);
        if (inp) inp.value = String(inv);
      });
    }
    // skills
    if (doc.skills){
      GROUPS.forEach(g=>{
        g.skills.forEach(s=>{
          const inv = doc.skills[s]?.invest ?? 0;
          const inp = $(`[data-s-invest="${s}"]`);
          if (inp) inp.value = String(inv);
        });
      });
    }
    // intensities
    if (doc.intensities){
      INTENSITIES.forEach(nm=>{
        const inv = doc.intensities[nm]?.invest ?? 0;
        const inp = $(`[data-i-invest="${nm}"]`);
        if (inp) inp.value = String(inv);
      });
    }
    // sublimations
    if (Array.isArray(doc.sublimations) && $('#subTable tbody')){
      const tbody = $('#subTable tbody');
      tbody.innerHTML = '';
      doc.sublimations.forEach(s => addSubRow(s));
    } else if ($('#subTable tbody') && $('#subTable tbody').children.length === 0) {
      addSubRow({type:'2', skill:'', tier:1}); // seed
    }

    // personal
    $('#p_height')   && ($('#p_height').value   = doc.height   || '');
    $('#p_weight')   && ($('#p_weight').value   = doc.weight   || '');
    $('#p_bday')     && ($('#p_bday').value     = doc.birthday || '');
    $('#p_backstory')&& ($('#p_backstory').value= doc.backstory|| '');
    $('#p_notes')    && ($('#p_notes').value    = doc.notes    || '');

    recompute();
  }

  // ---------- Sublimation table UI ----------
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
  const ALL_SKILLS = GROUPS.flatMap(g => g.skills).map(k => ({key:k, label:k.charAt(0).toUpperCase()+k.slice(1)}));

  function addSubRow(defaults = {type:'2', skill:'', tier:1}){
    const tbody = $('#subTable tbody');
    if (!tbody) return;

    const tr = document.createElement('tr');

    const typeSel = document.createElement('select');
    typeSel.className = 'input';
    SUB_TYPES.forEach(t => {
      const o = document.createElement('option');
      o.value = t.id; o.textContent = t.label;
      if (defaults.type === t.id) o.selected = true;
      typeSel.appendChild(o);
    });

    const skillSel = document.createElement('select');
    skillSel.className = 'input';
    const empty = document.createElement('option');
    empty.value=''; empty.textContent='—';
    skillSel.appendChild(empty);
    ALL_SKILLS.forEach(s=>{
      const o = document.createElement('option');
      o.value = s.key; o.textContent = s.label;
      if (defaults.skill === s.key) o.selected = true;
      skillSel.appendChild(o);
    });

    const tierInp = document.createElement('input');
    tierInp.type='number'; tierInp.min='0'; tierInp.max='4'; tierInp.value = String(defaults.tier);
    tierInp.className='input';

    const slotsCell = document.createElement('td');
    slotsCell.className='right mono';
    slotsCell.textContent = String(Math.max(0, num(tierInp.value)));

    const delBtn = document.createElement('button');
    delBtn.className='btn ghost';
    delBtn.textContent='Remove';
    delBtn.addEventListener('click', ()=>{
      tr.remove();
      recompute();
      scheduleSave(()=>({ sublimations: readSublimationsFromUI() }));
    });

    function toggleSkill(){
      const disabled = (typeSel.value !== '1'); // Excellence only
      skillSel.disabled = disabled;
      skillSel.style.opacity = disabled ? .5 : 1;
    }
    toggleSkill();

    typeSel.addEventListener('change', ()=>{
      toggleSkill(); recompute();
      scheduleSave(()=>({ sublimations: readSublimationsFromUI() }));
    });
    skillSel.addEventListener('change', ()=>{
      scheduleSave(()=>({ sublimations: readSublimationsFromUI() }));
    });
    tierInp.addEventListener('input', ()=>{
      slotsCell.textContent = String(Math.max(0, num(tierInp.value)));
      recompute();
      scheduleSave(()=>({ sublimations: readSublimationsFromUI() }));
    });

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
    tbody.appendChild(tr);
    recompute();
  }

  $('#btnAddSub') && $('#btnAddSub').addEventListener('click', ()=> addSubRow());

  // ---------- Wire inputs → recompute + save ----------
  function bindInputs(){
    // Header + personal
    ['#c_name','#c_level','#c_xp','#avatarUrl','#p_height','#p_weight','#p_bday','#p_backstory','#p_notes']
      .forEach(sel => {
        const el = $(sel);
        if (!el) return;
        el.addEventListener('input', ()=>{
          if (sel==='#avatarUrl' && $('#charAvatar')) {
            $('#charAvatar').src = el.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
          }
          recompute();
          const keyMap = {
            '#c_name':'name','#c_level':'level','#c_xp':'xp','#avatarUrl':'avatar_url',
            '#p_height':'height','#p_weight':'weight','#p_bday':'birthday','#p_backstory':'backstory','#p_notes':'notes'
          };
          const k = keyMap[sel];
          scheduleSave(()=>({ [k]: el.type==='number' ? num(el.value||0) : el.value }));
        });
      });

    // Characteristics and skills
    $$('#charSkillContainer input').forEach(inp => {
      inp.addEventListener('input', ()=>{
        // normalize number inputs so replacement doesn't append digits
        if (inp.type === 'number') {
          const v = inp.value;
          inp.value = String(v === '' ? '' : num(v)); // coerce but allow empty
        }
        recompute();
        scheduleSave(serializeCharacter);
      });
    });

    // Intensities
    $$('#intensityTable [data-i-invest]').forEach(inp => {
      inp.addEventListener('input', ()=>{
        if (inp.type === 'number') inp.value = String(inp.value==='' ? '' : num(inp.value));
        recompute();
        scheduleSave(serializeCharacter);
      });
    });
  }

  // ---------- Boot ----------
  (async function init(){
    bindInputs();

    // seed one sublimation row if none present
    if ($('#subTable tbody') && $('#subTable tbody').children.length === 0) {
      addSubRow({type:'2', skill:'', tier:1});
    }

    // load if ?id=…
    const url = new URL(location.href);
    const id  = url.searchParams.get('id');
    if (id) {
      try {
        const { character } = await API.getCharacter(id);
        CHARACTER_ID = character.id;
        hydrateUI(character);
      } catch (e) {
        console.error('Failed to load character', e);
      }
    } else {
      // new character; will be created on first change
      recompute();
    }
  })();
})();