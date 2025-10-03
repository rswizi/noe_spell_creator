/* character.js – builds UI, computes deriveds, autosaves, and shows Sources drawers */
(() => {
  // ---------- utils ----------
  const $  = (sel, el=document) => el.querySelector(sel);
  const $$ = (sel, el=document) => Array.from(el.querySelectorAll(sel));
  const clamp = (v,min,max)=>Math.max(min,Math.min(max,v));
  const toInt = (v, def=0) => {
    if (v == null) return def;
    const s = String(v).replace(/[^\d-]/g,'');
    const n = parseInt(s,10);
    return Number.isFinite(n) ? n : def;
  };
  const debounce = (fn, ms=500) => { let t=null; return (...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),ms);} };

  // sanitize inputs to 0–2 digits, replace value (prevents “31” issue)
  function normalizeNumeric(inp, {min=0,max=99}={}) {
    let val = (inp.value||'').replace(/[^\d]/g,'');
    if (val.length > 2) val = val.slice(0,2);
    const n = clamp(toInt(val,0),min,max);
    inp.value = String(n);
    return n;
  }

  // ---------- constants ----------
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

  const SUB_TYPES = {
    EXCELLENCE:'1', LETHALITY:'2', BLESSING:'3', DEFENSE:'4',
    SPEED:'5', ENDURANCE:'6', DEVASTATION:'7', CLARITY:'8',
  };

  // ---------- rules ----------
  const scoreFromInvest = inv => 4 + inv;
  const milestoneSigned = score => Math.floor(score/2 - 5);         // may be negative
  const milestonePos    = score => Math.max(milestoneSigned(score),0);

  const skillCapFromLevel = lvl => (lvl>=50?8:lvl>=40?7:lvl>=30?6:lvl>=20?5:lvl>=10?4:3);
  const charCapFromLevel  = lvl => (lvl>=55?10:lvl>=46?9:lvl>=37?8:lvl>=28?7:lvl>=19?6:lvl>=10?5:4);
  const levelFromXP = xp => clamp(Math.floor((-1 + Math.sqrt(1 + 8*(xp/100)))/2)+1,1,100);

  function idIvFromBV(bv){
    if (bv <= 0) return ['—','—'];
    if (bv <= 7) return ['1d4',2];
    if (bv <= 11) return ['1d6',3];
    if (bv <= 15) return ['1d8',4];
    if (bv <= 17) return ['1d10',5];
    return ['1d12',6];
  }

  // ---------- UI builders ----------
  function buildCharSkillCards() {
    const host = document.getElementById('charSkillContainer');
    host.innerHTML = '';

    CHAR_MAP.forEach(group => {
      const card = document.createElement('div');
      card.className = 'stat-card';

      // helper: one row
      const makeRow = (displayName, investAttr, investMax, totalAttr, mileAttr, rowClass, sourceKey) => {
        const row = document.createElement('div');
        row.className = `stat-row ${rowClass}`;

        // clickable name (opens Sources)
        const nameEl = document.createElement('div');
        nameEl.className = 'stat-name clickable stat-click';
        nameEl.textContent = displayName;
        nameEl.dataset.sourceKey = sourceKey;
        row.appendChild(nameEl);

        // invested input (2-digit)
        const inv = document.createElement('input');
        inv.type = 'number';
        inv.min = '0';
        inv.max = String(investMax);
        inv.value = '0';
        inv.className = 'input numeric';
        inv.setAttribute(investAttr, ''); // attribute presence matters for selectors
        row.appendChild(inv);

        // right badges [Total] | [Milestone]
        const total = document.createElement('div');
        total.className = 'badge-col';
        total.setAttribute(totalAttr, '');
        total.textContent = '0';
        row.appendChild(total);

        const mile = document.createElement('div');
        mile.className = 'badge-col';
        mile.setAttribute(mileAttr, '');
        mile.textContent = '0';
        row.appendChild(mile);

        // sources drawer container
        const srcBox = document.createElement('div');
        srcBox.className = 'sources';
        row.appendChild(srcBox);

        // attach drawer (empty initially; recompute fills content)
        attachDrawer(row, () => []);

        card.appendChild(row);
      };

      // Characteristic row — use REAL name, attribute must be data-c-invest, totals data-c-total / data-c-mile
      makeRow(
        group.label,
        `data-c-invest=${group.investKey}`,   // attr presence only; value used by selector
        16,
        `data-c-total=${group.key}`,
        `data-c-mile=${group.key}`,
        'char-row',
        `c:${group.key}`
      );

      // Skills rows — data-s-invest / data-s-base, milestone column will show linked char milestone
      group.skills.forEach(s => {
        const row = document.createElement('div');
        row.className = 'stat-row skill-row';

        const nameEl = document.createElement('div');
        nameEl.className = 'stat-name clickable stat-click';
        nameEl.textContent = s.label;
        nameEl.dataset.sourceKey = `s:${s.key}`;
        row.appendChild(nameEl);

        const inv = document.createElement('input');
        inv.type = 'number';
        inv.min = '0';
        inv.max = '8';
        inv.value = '0';
        inv.className = 'input numeric';
        inv.setAttribute(`data-s-invest`, s.key);
        row.appendChild(inv);

        const base = document.createElement('div');
        base.className = 'badge-col';
        base.setAttribute(`data-s-base`, s.key);
        base.textContent = '0';
        row.appendChild(base);

        const mile = document.createElement('div');
        mile.className = 'badge-col';
        mile.setAttribute(`data-s-mile`, s.key);
        mile.textContent = '0';
        row.appendChild(mile);

        const srcBox = document.createElement('div');
        srcBox.className = 'sources';
        row.appendChild(srcBox);

        attachDrawer(row, () => []);
        card.appendChild(row);
      });

      host.appendChild(card);
    });
  }

  function buildIntensities(){
    const tbody = $('#intensityTable tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    INTENSITIES.forEach(nm=>{
      const tr = document.createElement('tr');
      tr.className = 'int-row';
      tr.innerHTML = `
        <td class="stat-click">${nm}</td>
        <td><input class="input num2" type="number" min="0" max="8" value="0" data-i-invest="${nm}"></td>
        <td class="mono" data-i-mod="${nm}">0</td>
        <td class="mono" data-i-base="${nm}">0</td>
        <td class="mono" data-i-id="${nm}">—</td>
        <td class="mono" data-i-iv="${nm}">—</td>
        <td class="mono right" data-i-rw="${nm}">0</td>
      `;
      tbody.appendChild(tr);
    });
  }

  // ---------- Sources drawers ----------
  function attachDrawer(row, getSources){
    const click = $('.stat-click', row) || row;
    const box = $('.sources', row);
    click.addEventListener('click', ()=>{
      row.classList.toggle('open');
      renderSources(box, getSources());
    });
  }
  function renderSources(box, entries){
    if (!box) return;
    box.innerHTML = '';
    if (!entries || !entries.length){
      const d = document.createElement('div');
      d.className='source-empty'; d.textContent='No modifiers yet.';
      box.appendChild(d); return;
    }
    entries.forEach(([name,val])=>{
      const line = document.createElement('div');
      line.className='source-line';
      const a=document.createElement('span'); a.textContent=name;
      const b=document.createElement('b'); b.textContent=(val>0?'+':'')+val;
      line.appendChild(a); line.appendChild(b);
      box.appendChild(line);
    });
  }

  // ---------- recompute ----------
  let charMilSignedCache = {}; // ref/dex/bod/…

  const sumTier = (subs, type) => subs.filter(s=>s.type===type).reduce((a,b)=>a+b.tier,0);

  function readLevel(){
    const l = $('#c_level'), x = $('#c_xp');
    let lvl = toInt(l?.value||1,1);
    if (!lvl) lvl = levelFromXP(toInt(x?.value||0,0));
    return clamp(lvl,1,100);
  }
  function readSublimations(){
    const rows = Array.from($('#subTable tbody')?.children||[]);
    return rows.map(tr=>{
      const type = tr._refs?.typeSel?.value || SUB_TYPES.LETHALITY;
      const skill= tr._refs?.skillSel?.value || '';
      const tier = clamp(toInt(tr._refs?.tierInp?.value||0,0),0,4);
      return {type, skill, tier};
    });
  }

  function setTxt(sel,val){ const n=$(sel); if(n) n.textContent=String(val); }
  function readInt(sel){ const n=$(sel); return n?toInt(n.textContent||0,0):0; }
  function setBadge(sel, val){ const n=$(sel); if(n) n.textContent=String(val); }
  function setBar(curSel,maxSel,barSel,cur,max){
    const c=$(curSel), m=$(maxSel), b=$(barSel);
    if (m) m.textContent=String(max);
    if (c) c.textContent=String(clamp(cur,0,max));
    if (b) b.style.width = (max>0 ? Math.round((cur/max)*100) : 0)+'%';
  }

  function decorateCaps(skillCap, charCap, spMax, cpMax, subMax, tierCap){
    // skills
    CHAR_MAP.forEach(g=>g.skills.forEach(s=>{
      const inp = $(`[data-s-invest="${s.key}"]`);
      if (!inp) return;
      inp.classList.toggle('over', toInt(inp.value,0)>skillCap);
    }));
    // characteristics total
    CHAR_MAP.forEach(g=>{
      const inp = $(`[data-c-invest="${g.investKey}"]`);
      if (!inp) return;
      const sc = scoreFromInvest(toInt(inp.value,0));
      inp.classList.toggle('over', sc>charCap);
    });
    // totals
    $('#sp_used')?.classList.toggle('danger', toInt($('#sp_used')?.textContent,0) > spMax);
    $('#cp_used')?.classList.toggle('danger', toInt($('#cp_used')?.textContent,0) > cpMax);
    $('#sub_used')?.classList.toggle('danger', toInt($('#sub_used')?.textContent,0) > subMax);
    // sub tier
    Array.from($('#subTable tbody')?.children||[]).forEach(tr=>{
      const t = toInt(tr._refs?.tierInp?.value||0,0);
      tr._refs?.tierInp?.classList.toggle('over', t>tierCap);
    });
  }

  function recompute(){
    // cache milestones (signed)
    const cache = {};
    CHAR_MAP.forEach(g=>{
      const invEl = $(`[data-c-invest="${g.investKey}"]`);
      if (!invEl) return;
      const inv = toInt(invEl.value||0,0);
      cache[g.key] = milestoneSigned(scoreFromInvest(inv));
    });
    charMilSignedCache = cache;

    const lvl = readLevel();
    $('#c_level').value = String(lvl);

    const skillCap = skillCapFromLevel(lvl);
    const charCap  = charCapFromLevel(lvl);
    setTxt('#skill_cap', skillCap);
    setTxt('#char_cap',  charCap);

    // Sublimations
    const subs = readSublimations();
    const subUsed = subs.reduce((a,s)=>a+s.tier,0);
    const mile_pre_pos = Math.max(charMilSignedCache['pre']||0,0);
    const subMax = mile_pre_pos*2 + Math.floor(lvl/10);
    const tierCap = Math.ceil(lvl/25);
    setTxt('#sub_used', subUsed); setTxt('#sub_max', subMax); setTxt('#sub_tier', tierCap);

    // Excellence (skill -> bonus)
    const excel = {};
    subs.forEach(s=>{
      if (s.type===SUB_TYPES.EXCELLENCE && s.skill){
        excel[s.skill]=(excel[s.skill]||0)+s.tier;
      }
    });

    // Characteristics totals + milestones (update UI)
    CHAR_MAP.forEach(g=>{
      const inp = $(`[data-c-invest="${g.investKey}"]`);
      if (!inp) return;
      normalizeNumeric(inp,{min:0,max:16});
      const score = scoreFromInvest(toInt(inp.value,0));
      setTxt(`[data-c-total="${g.key}"]`, score);
      setTxt(`[data-c-mile="${g.key}"]`, milestoneSigned(score));

      // characteristic drawer -> "No modifiers yet." for now
      const crow = inp.closest('.char-row');
      if (crow && !crow._charDrawer){
        attachDrawer(crow, ()=>[]);
        crow._charDrawer = true;
      }
    });

    // Skills bases
    let sp_used = 0;
    CHAR_MAP.forEach(g=>{
      g.skills.forEach(s=>{
        const inp = $(`[data-s-invest="${s.key}"]`);
        if (!inp) return;
        normalizeNumeric(inp,{min:0,max:8});
        const inv = toInt(inp.value,0);
        sp_used += inv;
        const bonus = Math.min(inv, excel[s.key]||0);
        const base  = inv + bonus + (charMilSignedCache[g.key]||0);
        setTxt(`[data-s-base="${s.key}"]`, base);
        setTxt(`[data-s-mile="${s.key}"]`, (charMilSignedCache[g.key]||0));

        // sources drawer for skill row
        const row = inp.closest('.skill-row');
        if (row && !row._skillDrawer){
          row._getSources = ()=> (bonus>0 ? [[`Sublimation: Excellence (${s.label})`, bonus]] : []);
          attachDrawer(row, ()=> row._getSources());
          row._skillDrawer = true;
        } else if (row && row._getSources){
          row._getSources = ()=> (bonus>0 ? [[`Sublimation: Excellence (${s.label})`, bonus]] : []);
          if (row.classList.contains('open')) {
            renderSources($('.sources', row), row._getSources());
          }
        }
      });
    });

    // Points/caps
    const cp_used = CHAR_MAP.reduce((a,g)=>a + toInt($(`[data-c-invest="${g.investKey}"]`)?.value||0,0), 0);
    const cp_max  = 22 + Math.floor((lvl-1)/9)*3;
    const sp_max  = 40 + (lvl-1)*2;
    setTxt('#cp_used',cp_used); setTxt('#cp_max',cp_max);
    setTxt('#sp_used',sp_used); setTxt('#sp_max',sp_max);

    // Derived
    const lvlUp = Math.max(lvl-1,0);
    const mile = k => Math.max(charMilSignedCache[k]||0,0);

    const tDefense   = sumTier(subs,SUB_TYPES.DEFENSE);
    const tSpeed     = sumTier(subs,SUB_TYPES.SPEED);
    const tClarity   = sumTier(subs,SUB_TYPES.CLARITY);
    const tEndurance = sumTier(subs,SUB_TYPES.ENDURANCE);
    const tDevas     = sumTier(subs,SUB_TYPES.DEVASTATION);

    const hp_max = 100 + lvlUp + 12*mile('bod') + 6*mile('wil') + 12*tDefense;
    const en_max = 5 + Math.floor(lvlUp/5) + 2*mile('wil') + 4*mile('mag') + 2*tEndurance;
    const fo_max = 2 + Math.floor(lvlUp/5) + mile('wil') + 2*mile('pre') + mile('wis') + tClarity;
    const mo     = 4 + mile('dex') + mile('ref') + tSpeed;
    const et     = 1 + Math.floor(lvlUp/9) + mile('mag');
    const cdc    = 6 + Math.floor(lvl/10) + tDevas;

    setBadge('#k_mo', mo);
    setBadge('#k_init', mo + mile('ref'));
    setBadge('#k_et', et);
    setBadge('#k_cdc', cdc);

    setBar('#hp_cur','#hp_max','#hp_bar', hp_max, hp_max);
    setBar('#sp_cur','#sp_max','#sp_bar', 0, Math.floor(hp_max*0.1));
    setBar('#en_cur','#en_max','#en_bar', Math.min(5,en_max), en_max);
    setBar('#fo_cur','#fo_max','#fo_bar', Math.min(2,fo_max), fo_max);

    const txMax = readInt('[data-s-base="resistance"]') + readInt('[data-s-base="alchemy"]');
    setBar('#tx_cur','#tx_max','#tx_bar', 0, txMax);

    const encMax = 10 + readInt('[data-s-base="athletics"]')*5 + readInt('[data-s-base="spirit"]')*2;
    setBar('#enc_cur','#enc_max','#enc_bar', 0, encMax);

    // Intensities (use MAG milestone signed)
    const magM = charMilSignedCache['mag']||0;
    INTENSITIES.forEach(nm=>{
      const inp = $(`[data-i-invest="${nm}"]`);
      if (!inp) return;
      normalizeNumeric(inp,{min:0,max:8});
      const inv = toInt(inp.value,0);
      const base = inv>0 ? inv + magM : 0;
      const [ID,IV] = idIvFromBV(base);
      setTxt(`[data-i-mod="${nm}"]`, magM);
      setTxt(`[data-i-base="${nm}"]`, base);
      setTxt(`[data-i-id="${nm}"]`, ID);
      setTxt(`[data-i-iv="${nm}"]`, IV==='—'?'—':String(IV));
      setTxt(`[data-i-rw="${nm}"]`, '0');

      const row = inp.closest('tr');
      if (row && !row._drawer){
        attachDrawer(row, ()=>[]);
        row._drawer = true;
      }
    });

    decorateCaps(skillCap,charCap,sp_max,cp_max,subMax,tierCap);
    triggerAutosave();
  }

  // ---------- Sublimations table ----------
  function addSubRow(defaults = {type:SUB_TYPES.EXCELLENCE, skill:'', tier:1}){
    const tb = $('#subTable tbody'); if (!tb) return;
    const tr=document.createElement('tr');

    const typeSel=document.createElement('select'); typeSel.className='input s';
    Object.values(SUB_TYPES).forEach(id=>{
      const o=document.createElement('option'); o.value=id; o.textContent=subLabel(id); typeSel.appendChild(o);
    });
    typeSel.value = defaults.type;

    const skillSel=document.createElement('select'); skillSel.className='input m';
    const empty=document.createElement('option'); empty.value=''; empty.textContent='—'; skillSel.appendChild(empty);
    CHAR_MAP.flatMap(g=>g.skills).forEach(s=>{ const o=document.createElement('option'); o.value=s.key; o.textContent=s.label; skillSel.appendChild(o); });
    skillSel.value = defaults.skill || '';

    const tierInp=document.createElement('input'); tierInp.type='number'; tierInp.min='0'; tierInp.max='4'; tierInp.value=String(clamp(defaults.tier,0,4)); tierInp.className='input xs';

    const slotsCell=document.createElement('td'); slotsCell.className='right mono'; slotsCell.textContent=String(clamp(defaults.tier,0,4));
    const delBtn=document.createElement('button'); delBtn.className='btn ghost'; delBtn.textContent='Remove';

    function togg(){ const ex=typeSel.value===SUB_TYPES.EXCELLENCE; skillSel.disabled=!ex; skillSel.style.opacity=ex?'1':'.5'; }
    togg();

    typeSel.addEventListener('change', ()=>{ togg(); recompute(); });
    skillSel.addEventListener('change', recompute);
    tierInp.addEventListener('input', ()=>{ const n=normalizeNumeric(tierInp,{min:0,max:4}); slotsCell.textContent=String(n); recompute(); });
    delBtn.addEventListener('click', ()=>{ tr.remove(); recompute(); });

    const td1=document.createElement('td'); td1.appendChild(typeSel);
    const td2=document.createElement('td'); td2.appendChild(skillSel);
    const td3=document.createElement('td'); td3.appendChild(tierInp);
    const td5=document.createElement('td'); td5.appendChild(delBtn);

    tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(slotsCell); tr.appendChild(td5);
    tr._refs={typeSel,skillSel,tierInp,slotsCell};
    tb.appendChild(tr);
  }
  function subLabel(id){
    switch(id){
      case SUB_TYPES.LETHALITY: return 'Lethality';
      case SUB_TYPES.EXCELLENCE:return 'Excellence';
      case SUB_TYPES.BLESSING:  return 'Blessing';
      case SUB_TYPES.DEFENSE:   return 'Defense';
      case SUB_TYPES.SPEED:     return 'Speed';
      case SUB_TYPES.ENDURANCE: return 'Endurance';
      case SUB_TYPES.DEVASTATION:return 'Devastation';
      case SUB_TYPES.CLARITY:   return 'Clarity';
      default: return 'Unknown';
    }
  }

  // ---------- save ----------
  const autosave = debounce(saveNow, 600);
  function triggerAutosave(){ autosave(collectPayload()); }
  function collectPayload(){
    const characteristics = {}, skills = {}, intensities = {};
    CHAR_MAP.forEach(g=>{ characteristics[g.key]=toInt($(`[data-c-invest="${g.investKey}"]`)?.value||0,0); });
    CHAR_MAP.forEach(g=>g.skills.forEach(s=>{ skills[s.key]=toInt($(`[data-s-invest="${s.key}"]`)?.value||0,0); }));
    INTENSITIES.forEach(nm=>{ intensities[nm]=toInt($(`[data-i-invest="${nm}"]`)?.value||0,0); });

    return {
      name: $('#c_name')?.value||'',
      level: readLevel(),
      xp: toInt($('#c_xp')?.value||0,0),
      avatarUrl: $('#avatarUrl')?.value||'',
      characteristics, skills, intensities,
      sublimations: Array.from($('#subTable tbody')?.children||[]).map(tr=>({
        type: tr._refs?.typeSel?.value, skill: tr._refs?.skillSel?.value, tier: toInt(tr._refs?.tierInp?.value||0,0)
      }))
    };
  }
  async function saveNow(payload){
    try{
      const res = await fetch('/api/characters/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if (!res.ok) throw new Error('Save failed');
      document.body.classList.add('saved'); setTimeout(()=>document.body.classList.remove('saved'), 400);
    }catch(e){ console.warn(e); }
  }

  // ---------- events ----------
  function bindEvents(){
    // avatar preview
    const avatarUrl = $('#avatarUrl'), charAvatar = $('#charAvatar');
    avatarUrl?.addEventListener('input', ()=>{ charAvatar.src = avatarUrl.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg'; triggerAutosave(); });

    // basic inputs
    ['#c_level','#c_xp','#c_name'].forEach(sel=>{
      const n=$(sel); if(!n) return;
      n.addEventListener('input', ()=>{
        if(sel!=='#c_name') normalizeNumeric(n,{min: sel==='#c_level'?1:0, max: 99});
        recompute();
      });
    });

    // Delegate inputs inside grids
    $('#charSkillContainer')?.addEventListener('input', e=>{
      const t = e.target;
      if (t.matches('[data-c-invest]')) normalizeNumeric(t,{min:0,max:16});
      if (t.matches('[data-s-invest]')) normalizeNumeric(t,{min:0,max:8});
      recompute();
    });
    $('#intensityTable')?.addEventListener('input', e=>{
      const t=e.target; if(t.matches('[data-i-invest]')) normalizeNumeric(t,{min:0,max:8}); recompute();
    });

    // tabs
    $$('.tab').forEach(btn=>{
      btn.addEventListener('click', ()=>{
        $$('.tab').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        const key = btn.dataset.tab;
        $$('.tabpan').forEach(p=>p.classList.remove('active'));
        $(`#tab-${key}`)?.classList.add('active');
      });
    });

    // add one sublimation row by default
    $('#btnAddSub')?.addEventListener('click', ()=>{ addSubRow({type:SUB_TYPES.EXCELLENCE,skill:'accuracy',tier:1}); recompute(); });
  }

  // ---------- init ----------
  function init(){
    buildCharSkillCards();
    buildIntensities();
    if (!$('#subTable tbody') || !$('#subTable tbody').children.length){
      addSubRow({type:SUB_TYPES.EXCELLENCE, skill:'accuracy', tier:2});
    }
    bindEvents();
    recompute();
  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();