/* /static/js/character.js
 * Character Manager – complete, safe, debounced, and clickable “Sources” drawers.
 */

(() => {
  // ---------- utilities ----------
  const $  = (sel, el=document) => el.querySelector(sel);
  const $$ = (sel, el=document) => Array.from(el.querySelectorAll(sel));

  // numeric helpers
  const clamp = (v,min,max)=>Math.max(min,Math.min(max,v));
  const toInt = (v, def=0) => {
    if (v == null) return def;
    const s = String(v).replace(/[^\d-]/g,''); // keep minus for robustness
    const n = parseInt(s,10);
    return Number.isFinite(n) ? n : def;
  };

  // Enforce 0–2 digits, replace (not append)
  function sanitizeNumericInput(inp, {min=0, max=99}={}){
    let val = inp.value || '';
    // keep only digits
    val = val.replace(/[^\d]/g,'');
    if (val.length > 2) val = val.slice(0,2);
    const n = clamp(toInt(val,0), min, max);
    inp.value = String(n);
    return n;
  }

  // Debounce for autosave
  const debounce = (fn, ms=500) => {
    let t=null;
    return (...args)=>{ clearTimeout(t); t = setTimeout(()=>fn(...args), ms); };
  };

  // ---------- constants ----------
  const CHAR_MAP = [
    { key:'ref', label:'Reflex (REF)', investKey:'reflexp', skills:[
      { key:'technicity', label:'Technicity' },
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
    { key:'bod', label:'Body (BOD)', investKey:'bodyp', skills:[
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
    { key:'mag', label:'Magic (MAG)', investKey:'magicp', skills:[
      { key:'aura',        label:'Aura' },
      { key:'incantation', label:'Incantation' },
      { key:'enchantment', label:'Enchantment' },
      { key:'restoration', label:'Restoration' },
      { key:'potential',   label:'Potential' },
    ]},
    { key:'pre', label:'Presence (PRE)', investKey:'presencep', skills:[
      { key:'taming',      label:'Taming' },
      { key:'charm',       label:'Charm' },
      { key:'charisma',    label:'Charisma' },
      { key:'deception',   label:'Deception' },
      { key:'persuasion',  label:'Persuasion' },
    ]},
    { key:'wis', label:'Wisdom (WIS)', investKey:'wisdomp', skills:[
      { key:'survival',    label:'Survival' },
      { key:'education',   label:'Education' },
      { key:'perception',  label:'Perception' },
      { key:'psychology',  label:'Psychology' },
      { key:'investigation',label:'Investigation' },
    ]},
    { key:'tec', label:'Tech (TEC)', investKey:'techp', skills:[
      { key:'crafting',    label:'Crafting' },
      { key:'soh',         label:'Sleight of hand' },
      { key:'alchemy',     label:'Alchemy' },
      { key:'medecine',    label:'Medicine' },
      { key:'engineering', label:'Engineering' },
    ]},
  ];

  const INTENSITIES = ['Fire','Water','Earth','Wind','Lightning','Moon','Sun','Ki'];

  // Sublimation types (IDs keep your earlier mapping)
  const SUB_TYPES = {
    EXCELLENCE:'1',   // +tiers to a specific skill (bonus capped by invested)
    LETHALITY:'2',    // +2 neutral damage per tier (not in this sheet)
    BLESSING:'3',     // magic dice adders (not in this sheet)
    DEFENSE:'4',      // +12 HP per tier
    SPEED:'5',        // +1 MO per tier
    ENDURANCE:'6',    // +2 EN per tier
    DEVASTATION:'7',  // +1 Condition DC per tier
    CLARITY:'8',      // +1 FO per tier
  };

  // ---------- derived / rules ----------
  const scoreFromInvest = inv => 4 + inv;              // total characteristic score (mods currently external)
  const milestoneFromScore = score => Math.max(Math.floor(score/2 - 5), 0); // “Positive Milestone”
  const charScoreToMilestoneSigned = score => Math.floor(score/2 - 5); // signed value (for showing milestone column)

  const skillCapFromLevel = lvl =>
    (lvl >= 50 ? 8 : lvl >= 40 ? 7 : lvl >= 30 ? 6 : lvl >= 20 ? 5 : lvl >= 10 ? 4 : 3);

  const charCapFromLevel = lvl =>
    (lvl >= 55 ? 10 : lvl >= 46 ? 9 : lvl >= 37 ? 8 : lvl >= 28 ? 7 : lvl >= 19 ? 6 : lvl >= 10 ? 5 : 4);

  const levelFromXP = xp => {
    const k = Math.floor((-1 + Math.sqrt(1 + 8*(xp/100)))/2);
    return clamp(k+1, 1, 100);
  };

  function idIvFromBV(bv){
    if (bv <= 0) return ['—','—'];
    if (bv <= 7)  return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10',5];
    return ['1d12', 6]; // 18+
  }

  // ---------- DOM: build collapsible “Sources” drawers ----------
  function attachDrawer(container, title, getSourcesFn){
    const row = container;
    if (!row) return;
    // Clickable header: any element with `.stat-click` inside row
    const clickTarget = $('.stat-click', row) || row;
    const drawer = $('.sources', row);
    if (!drawer) return;

    clickTarget.addEventListener('click', () => {
      row.classList.toggle('open');
      renderSources(drawer, getSourcesFn());
    });
  }

  function renderSources(drawer, entries){
    drawer.innerHTML = '';
    if (!entries || entries.length === 0){
      const p = document.createElement('div');
      p.className='source-empty';
      p.textContent = 'No modifiers yet.';
      drawer.appendChild(p);
      return;
    }
    entries.forEach(([name, val])=>{
      const line = document.createElement('div');
      line.className='source-line';
      const a = document.createElement('span'); a.textContent = name;
      const b = document.createElement('b');   b.textContent = (val>0?'+':'')+val;
      line.appendChild(a); line.appendChild(b);
      drawer.appendChild(line);
    });
  }

  // ---------- State read/write ----------
  // We store “subRows” from the sublimation table; the rest is read from inputs using data- attributes
  function readLevel(){
    const l = $('#c_level');
    const x = $('#c_xp');
    let lvl = toInt(l?.value ?? 1,1);
    if (!lvl) lvl = levelFromXP(toInt(x?.value ?? 0,0));
    return clamp(lvl,1,100);
  }

  function readSublimations(){
    const rows = Array.from($('#subTable tbody')?.children ?? []);
    return rows.map(tr => {
      const type = tr._refs?.typeSel?.value || SUB_TYPES.LETHALITY;
      const skill= tr._refs?.skillSel?.value || '';
      const tier = clamp(toInt(tr._refs?.tierInp?.value||0,0), 0, 4);
      return {type, skill, tier};
    });
  }

  // ---------- Compute + Paint ----------
  function recompute(){
    const lvl = readLevel();
    if ($('#c_level')) $('#c_level').value = String(lvl);

    // caps & totals
    const skillCap = skillCapFromLevel(lvl);
    const charCap  = charCapFromLevel(lvl);
    setTxt('#skill_cap', skillCap);
    setTxt('#char_cap',  charCap);

    // sublimations
    const subs = readSublimations();
    const subSlotsUsed = subs.reduce((a,s)=>a+s.tier,0);
    const mile_pre_pos = Math.max(charMod('pre'), 0);
    const subSlotsMax  = (mile_pre_pos*2) + Math.floor(lvl/10);
    const tierCap      = Math.ceil(lvl/25);

    setTxt('#sub_used', subSlotsUsed);
    setTxt('#sub_max',  subSlotsMax);
    setTxt('#sub_tier', tierCap);

    // excellence map (skill -> bonus)
    const excellence = {};
    subs.forEach(s=>{
      if (s.type === SUB_TYPES.EXCELLENCE && s.skill){
        excellence[s.skill] = (excellence[s.skill]||0) + s.tier;
      }
    });

    // defense/speed/clarity/endurance/devastation tiers for derived
    const tDefense    = sumTier(subs, SUB_TYPES.DEFENSE);
    const tSpeed      = sumTier(subs, SUB_TYPES.SPEED);
    const tClarity    = sumTier(subs, SUB_TYPES.CLARITY);
    const tEndurance  = sumTier(subs, SUB_TYPES.ENDURANCE);
    const tDevast     = sumTier(subs, SUB_TYPES.DEVASTATION);

    // Characteristic invested (0..16)
    const cInvest = {};
    CHAR_MAP.forEach(g=>{
      const inp = $(`[data-c-invest="${g.investKey}"]`);
      if (!inp) return;
      const n = sanitizeNumericInput(inp,{min:0,max:16});
      cInvest[g.key] = n;
    });

    // Scores, milestones (signed display & positive)
    const cScore = {};
    const cMilSigned = {};
    const cMilPos = {};
    CHAR_MAP.forEach(g=>{
      const score = scoreFromInvest(cInvest[g.key]||0);
      cScore[g.key] = score;
      cMilSigned[g.key] = charScoreToMilestoneSigned(score);
      cMilPos[g.key]   = Math.max(cMilSigned[g.key], 0);
      // paint characteristic row numbers
      setTxt(`[data-c-total="${g.key}"]`, score);
      setTxt(`[data-c-mile="${g.key}"]`, cMilSigned[g.key]); // can be negative
    });

    // Skills invested (0..8) and base values
    let sp_used = 0;
    CHAR_MAP.forEach(g=>{
      g.skills.forEach(s=>{
        const inp = $(`[data-s-invest="${s.key}"]`);
        if (!inp) return;
        const n = sanitizeNumericInput(inp,{min:0,max:8});
        sp_used += n;
        const bonus = Math.min(n, excellence[s.key]||0); // Excellence cap by invested
        const base  = n + bonus + cMilSigned[g.key];     // Base = invested + excellenceBonus + Milestone (signed)
        setTxt(`[data-s-mod="${s.key}"]`, bonus);
        setTxt(`[data-s-base="${s.key}"]`, base);

        // Attach “Sources” drawer for skills
        const row = inp.closest('.skill-row');
        if (row && !row._drawerHooked){
          attachDrawer(row, s.label, () => {
            const list = [];
            if ((excellence[s.key]||0)>0) list.push([`Sublimation: Excellence (${s.label})`, Math.min(n, excellence[s.key]||0)]);
            return list;
          });
          row._drawerHooked = true;
        }
      });

      // “Sources” drawer for characteristic – currently only shows “No modifiers yet.”
      const charRow = $(`[data-c-invest="${g.investKey}"]`)?.closest('.char-row');
      if (charRow && !charRow._drawerHooked){
        attachDrawer(charRow, g.label, () => []);
        charRow._drawerHooked = true;
      }
    });

    // points/caps
    const cp_used = Object.values(cInvest).reduce((a,b)=>a+b,0);
    const cp_max  = 22 + Math.floor((lvl-1)/9)*3;
    const sp_max  = 40 + (lvl-1)*2;

    setTxt('#cp_used', cp_used);
    setTxt('#cp_max',  cp_max);
    setTxt('#sp_used', sp_used);
    setTxt('#sp_max',  sp_max);

    // Derived badges & resources
    const mile_bod = cMilPos['bod']||0;
    const mile_wil = cMilPos['wil']||0;
    const mile_mag = cMilPos['mag']||0;
    const mile_dex = cMilPos['dex']||0;
    const mile_ref = cMilPos['ref']||0;
    const mile_wis = cMilPos['wis']||0;
    const lvl_up_count = Math.max(lvl-1,0);

    const hp_max = 100 + lvl_up_count + 12*mile_bod + 6*mile_wil + 12*tDefense;
    const en_max = 5 + Math.floor(lvl_up_count/5) + 2*mile_wil + 4*mile_mag + 2*tEndurance;
    const fo_max = 2 + Math.floor(lvl_up_count/5) + mile_wil + (cMilPos['pre']||0)*2 + mile_wis + tClarity;
    const mo     = 4 + mile_dex + mile_ref + tSpeed;
    const et     = 1 + Math.floor(lvl_up_count/9) + mile_mag;
    const cdc    = 6 + Math.floor(lvl/10) + tDevast;

    setBadge('#k_mo', mo);
    setBadge('#k_init', mo + mile_ref);
    setBadge('#k_et', et);
    setBadge('#k_cdc', cdc);

    setBar('#hp_cur','#hp_max','#hp_bar', hp_max, hp_max);
    setBar('#sp_cur','#sp_max','#sp_bar', 0, Math.floor(hp_max*0.1));
    setBar('#en_cur','#en_max','#en_bar', Math.min(5,en_max), en_max);
    setBar('#fo_cur','#fo_max','#fo_bar', Math.min(2,fo_max), fo_max);

    // TX and Enc
    const resBV = readTextAsInt('[data-s-base="resistance"]');
    const alcBV = readTextAsInt('[data-s-base="alchemy"]');
    const txMax = resBV + alcBV;
    setBar('#tx_cur','#tx_max','#tx_bar', 0, txMax);

    const athBV = readTextAsInt('[data-s-base="athletics"]');
    const spiBV = readTextAsInt('[data-s-base="spirit"]');
    const encMax= 10 + (athBV*5) + (spiBV*2);
    setBar('#enc_cur','#enc_max','#enc_bar', 0, encMax);

    // Intensities based on MAG milestone (signed)
    const magMilSigned = cMilSigned['mag']||0;
    INTENSITIES.forEach(nm=>{
      const inp = $(`[data-i-invest="${nm}"]`);
      if (!inp) return;
      const inv = sanitizeNumericInput(inp,{min:0,max:8});
      const base = (inv>0 ? inv + magMilSigned : 0);
      const [ID, IV] = idIvFromBV(base);
      setTxt(`[data-i-mod="${nm}"]`, magMilSigned);
      setTxt(`[data-i-base="${nm}"]`, base);
      setTxt(`[data-i-id="${nm}"]`, ID);
      setTxt(`[data-i-iv="${nm}"]`, IV==='—' ? '—' : String(IV));
      setTxt(`[data-i-rw="${nm}"]`, '0'); // placeholder – wire your grid later

      // Drawer for intensities – show if any Excellence (unlikely) or future sources
      const row = inp.closest('.int-row');
      if (row && !row._drawerHooked){
        attachDrawer(row, nm, () => []);
        row._drawerHooked = true;
      }
    });

    // Visual cap guards
    decorateCaps(skillCap, charCap, sp_max, cp_max, subSlotsMax, tierCap);

    // persist
    triggerAutosave();
  }

  // ---------- Painting helpers ----------
  function setTxt(sel,val){ const n=$(sel); if(n) n.textContent=String(val); }
  function readTextAsInt(sel){ const n=$(sel); return n?toInt(n.textContent||0,0):0; }
  function setBadge(sel, val){ const n=$(sel); if(n) n.textContent=String(val); }
  function setBar(curSel,maxSel,barSel,cur,max){
    const c=$(curSel), m=$(maxSel), b=$(barSel);
    if (m) m.textContent=String(max);
    if (c) c.textContent=String(clamp(cur,0,max));
    if (b) b.style.width = (max>0 ? Math.round((cur/max)*100) : 0)+'%';
  }
  function decorateCaps(skillCap, charCap, spMax, cpMax, subMax, tierCap){
    // skill invests
    CHAR_MAP.forEach(g => g.skills.forEach(s=>{
      const inp = $(`[data-s-invest="${s.key}"]`);
      if (!inp) return;
      const val = toInt(inp.value,0);
      inp.classList.toggle('over', val>skillCap);
    }));
    // characteristics scores
    CHAR_MAP.forEach(g=>{
      const inp = $(`[data-c-invest="${g.investKey}"]`);
      if (!inp) return;
      const sc = scoreFromInvest(toInt(inp.value,0));
      inp.classList.toggle('over', sc>charCap);
    });
    // totals
    const spUsed = toInt($('#sp_used')?.textContent||0,0);
    $('#sp_used')?.classList.toggle('danger', spUsed>spMax);
    const cpUsed = toInt($('#cp_used')?.textContent||0,0);
    $('#cp_used')?.classList.toggle('danger', cpUsed>cpMax);
    const subUsed = toInt($('#sub_used')?.textContent||0,0);
    $('#sub_used')?.classList.toggle('danger', subUsed>subMax);

    // each sub row tier
    Array.from($('#subTable tbody')?.children||[]).forEach(tr=>{
      const t = toInt(tr._refs?.tierInp?.value||0,0);
      if (tr._refs?.tierInp) tr._refs.tierInp.classList.toggle('over', t>tierCap);
    });
  }

  // signed milestone from characteristic key
  function charMod(key){
    // find group by key mapping we used earlier
    // keys in cMilSigned map: ref/dex/bod/wil/mag/pre/wis/tec
    return charMilSignedCache[key] || 0;
  }

  // ---------- Sublimations table wiring ----------
  function sumTier(subs, type){ return subs.filter(s=>s.type===type).reduce((a,b)=>a+b.tier,0); }

  function addSubRow(defaults = {type:SUB_TYPES.LETHALITY, skill:'', tier:1}){
    const tb = $('#subTable tbody'); if (!tb) return;
    const tr = document.createElement('tr');

    // type select
    const typeSel = document.createElement('select'); typeSel.className='input s';
    Object.entries(SUB_TYPES).forEach(([name,id])=>{
      const o=document.createElement('option');
      o.value=id; o.textContent = prettySubLabel(id);
      typeSel.appendChild(o);
    });
    typeSel.value = defaults.type;

    // skill select
    const skillSel = document.createElement('select'); skillSel.className='input m';
    const empty = document.createElement('option'); empty.value=''; empty.textContent='—';
    skillSel.appendChild(empty);
    CHAR_MAP.flatMap(g=>g.skills).forEach(s=>{
      const o=document.createElement('option');
      o.value=s.key; o.textContent=s.label; skillSel.appendChild(o);
    });
    skillSel.value = defaults.skill || '';

    // tier
    const tierInp = document.createElement('input');
    tierInp.type='number'; tierInp.min='0'; tierInp.max='4'; tierInp.value=String(clamp(defaults.tier,0,4));
    tierInp.className='input xs';

    // slots cell
    const slotsCell = document.createElement('td'); slotsCell.className='right mono'; slotsCell.textContent=String(clamp(defaults.tier,0,4));

    // delete
    const delBtn = document.createElement('button'); delBtn.className='btn ghost'; delBtn.textContent='Remove';

    // skill enabled only for Excellence
    function toggleSkill(){
      const isEx = typeSel.value === SUB_TYPES.EXCELLENCE;
      skillSel.disabled = !isEx;
      skillSel.style.opacity = isEx ? '1' : '.5';
    }
    toggleSkill();

    // events
    typeSel.addEventListener('change', () => { toggleSkill(); recompute(); });
    skillSel.addEventListener('change', recompute);
    tierInp.addEventListener('input', () => {
      const n = sanitizeNumericInput(tierInp,{min:0,max:4});
      slotsCell.textContent = String(n);
      recompute();
    });
    delBtn.addEventListener('click', () => { tr.remove(); recompute(); });

    // compose
    const td1=document.createElement('td'); td1.appendChild(typeSel);
    const td2=document.createElement('td'); td2.appendChild(skillSel);
    const td3=document.createElement('td'); td3.appendChild(tierInp);
    const td5=document.createElement('td'); td5.appendChild(delBtn);

    tr.appendChild(td1);
    tr.appendChild(td2);
    tr.appendChild(td3);
    tr.appendChild(slotsCell);
    tr.appendChild(td5);

    tr._refs={typeSel,skillSel,tierInp,slotsCell};
    tb.appendChild(tr);
  }

  function prettySubLabel(id){
    switch(id){
      case SUB_TYPES.LETHALITY:   return 'Lethality';
      case SUB_TYPES.EXCELLENCE:  return 'Excellence';
      case SUB_TYPES.BLESSING:    return 'Blessing';
      case SUB_TYPES.DEFENSE:     return 'Defense';
      case SUB_TYPES.SPEED:       return 'Speed';
      case SUB_TYPES.DEVASTATION: return 'Devastation';
      case SUB_TYPES.CLARITY:     return 'Clarity';
      case SUB_TYPES.ENDURANCE:   return 'Endurance';
      default: return 'Unknown';
    }
  }

  // ---------- Save (debounced) ----------
  const autosave = debounce(saveNow, 600);
  function triggerAutosave(){ autosave(collectPayload()); }

  function collectPayload(){
    const lvl  = readLevel();
    const name = $('#c_name')?.value || '';
    const xp   = toInt($('#c_xp')?.value||0,0);
    const avatarUrl = $('#avatarUrl')?.value || '';

    // invests
    const characteristics = {};
    CHAR_MAP.forEach(g=>{
      const n = toInt($(`[data-c-invest="${g.investKey}"]`)?.value || 0, 0);
      characteristics[g.key] = n;
    });
    const skills = {};
    CHAR_MAP.forEach(g=>g.skills.forEach(s=>{
      const n = toInt($(`[data-s-invest="${s.key}"]`)?.value || 0, 0);
      skills[s.key] = n;
    }));

    const intensities = {};
    INTENSITIES.forEach(nm=>{
      intensities[nm] = toInt($(`[data-i-invest="${nm}"]`)?.value || 0, 0);
    });

    const sublimations = readSublimations();

    return {
      id: $('#characterId')?.value || null,
      name, level:lvl, xp, avatarUrl,
      characteristics, skills, intensities, sublimations,
      // send some derived so backend can validate, if you like
      summary: {
        sp_used: toInt($('#sp_used')?.textContent||0,0),
        cp_used: toInt($('#cp_used')?.textContent||0,0)
      }
    };
  }

  async function saveNow(payload){
    try{
      const res = await fetch('/api/characters/save', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`Save failed: ${res.status}`);
      // optionally show a tiny “saved” pulse
      document.body.classList.add('saved');
      setTimeout(()=>document.body.classList.remove('saved'), 500);
    }catch(err){
      // silent to console so the UI never breaks
      console.warn(err);
    }
  }

  // ---------- global cache for signed milestones (used by charMod) ----------
  let charMilSignedCache = {};

  // ---------- Wire up events ----------
  function bindEvents(){
    // avatar
    const avatarUrl = $('#avatarUrl');
    const charAvatar = $('#charAvatar');
    if (avatarUrl && charAvatar){
      avatarUrl.addEventListener('input', ()=>{
        charAvatar.src = avatarUrl.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
        triggerAutosave();
      });
    }

    // Level & XP
    ['#c_level','#c_xp','#c_name'].forEach(sel=>{
      const inp=$(sel); if(!inp) return;
      inp.addEventListener('input', ()=>{
        if (sel!=='#c_name') sanitizeNumericInput(inp,{min:(sel==='#c_level'?1:0),max:9999});
        recompute();
      });
    });

    // characteristics & skills & intensities
    $$('#charSkillContainer input').forEach(inp=>{
      inp.addEventListener('input', ()=>{
        sanitizeNumericInput(inp,{min:0,max: inp.dataset.cInvest ? 16 : 8});
        recompute();
      });
    });
    $$('#intensityTable [data-i-invest]').forEach(inp=>{
      inp.addEventListener('input', ()=>{
        sanitizeNumericInput(inp,{min:0,max:8});
        recompute();
      });
    });

    // Sublimations
    $('#btnAddSub')?.addEventListener('click', ()=>{
      addSubRow({type:SUB_TYPES.LETHALITY, skill:'', tier:1});
      recompute();
    });

    // Tabs (if present)
    $$('.tab').forEach(btn=>{
      btn.addEventListener('click', ()=>{
        $$('.tab').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        const key = btn.dataset.tab;
        $$('.tabpan').forEach(p=>p.classList.remove('active'));
        $(`#tab-${key}`)?.classList.add('active');
      });
    });
  }

  // ---------- init ----------
  function init(){
    // Ensure at least one sublimation row exists for UX
    if (!$('#subTable tbody')?.children.length){
      addSubRow({type:SUB_TYPES.EXCELLENCE, skill:'accuracy', tier:2});
    }
    bindEvents();
    recompute();
  }

  // Before recompute, keep milestone cache updated
  const _origRecompute = recompute;
  recompute = function(){
    // build signed milestones cache
    const cache = {};
    CHAR_MAP.forEach(g=>{
      const val = toInt($(`[data-c-invest="${g.investKey}"]`)?.value || 0, 0);
      cache[g.key] = charScoreToMilestoneSigned(scoreFromInvest(val));
    });
    charMilSignedCache = cache;
    _origRecompute();
  };

  // run
  if (document.readyState === 'complete' || document.readyState === 'interactive'){
    init();
  }else{
    document.addEventListener('DOMContentLoaded', init);
  }
})();