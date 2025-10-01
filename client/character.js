(() => {
  // ====== CONFIG ======
  const API_BASE = ""; // same-origin FastAPI
  const token = localStorage.getItem("auth_token") || "";

  function authHeaders() {
    const h = { "Content-Type": "application/json" };
    if (token) h["Authorization"] = `Bearer ${token}`;
    return h;
  }

  const $  = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

  // Status pill
  const saveStatus = $('#saveStatus');
  const setStatus = (txt, cls="") => {
    if (!saveStatus) return;
    saveStatus.textContent = txt;
    saveStatus.className = `pill ${cls}`;
  };

  const getQuery = (k) => new URLSearchParams(location.search).get(k);

  // ====== DOM build (your original) ======
  // Tabs
  $$('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const key = btn.dataset.tab;
      $$('.tabpan').forEach(p => p.classList.remove('active'));
      $(`#tab-${key}`).classList.add('active');
    });
  });

  // Avatar
  const avatarUrl = $('#avatarUrl');
  const charAvatar = $('#charAvatar');
  avatarUrl.addEventListener('change', () => {
    charAvatar.src = avatarUrl.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
    triggerSave();
  });

  const CHAR_MAP = [
    { key:'ref', label:'Reflex (REF)', investKey:'REF', skills:[
      { key:'Technicity', label:'Technicity' },
      { key:'Dodge', label:'Dodge' },
      { key:'Tempo', label:'Tempo' },
      { key:'Reactivity', label:'Reactivity' },
    ]},
    { key:'dex', label:'Dexterity (DEX)', investKey:'DEX', skills:[
      { key:'Accuracy', label:'Accuracy' },
      { key:'Evasion', label:'Evasion' },
      { key:'Stealth', label:'Stealth' },
      { key:'Acrobatics', label:'Acrobatics' },
    ]},
    { key:'bod', label:'Body (BOD)', investKey:'BOD', skills:[
      { key:'Brutality', label:'Brutality' },
      { key:'Blocking', label:'Blocking' },
      { key:'Resistance', label:'Resistance' },
      { key:'Athletics', label:'Athletics' },
    ]},
    { key:'wil', label:'Willpower (WIL)', investKey:'WIL', skills:[
      { key:'Intimidation', label:'Intimidation' },
      { key:'Spirit', label:'Spirit' },
      { key:'Instinct', label:'Instinct' },
      { key:'Absorption', label:'Absorption' },
    ]},
    { key:'mag', label:'Magic (MAG)', investKey:'MAG', skills:[
      { key:'Aura', label:'Aura' },
      { key:'Incantation', label:'Incantation' },
      { key:'Enchantment', label:'Enchantment' },
      { key:'Restoration', label:'Restoration' },
      { key:'Potential', label:'Potential' },
    ]},
    { key:'pre', label:'Presence (PRE)', investKey:'PRE', skills:[
      { key:'Taming', label:'Taming' },
      { key:'Charm', label:'Charm' },
      { key:'Charisma', label:'Charisma' },
      { key:'Deception', label:'Deception' },
      { key:'Persuasion', label:'Persuasion' },
    ]},
    { key:'wis', label:'Wisdom (WIS)', investKey:'WIS', skills:[
      { key:'Survival', label:'Survival' },
      { key:'Education', label:'Education' },
      { key:'Perception', label:'Perception' },
      { key:'Psychology', label:'Psychology' },
      { key:'Investigation', label:'Investigation' },
    ]},
    { key:'tec', label:'Tech (TEC)', investKey:'TEC', skills:[
      { key:'Crafting', label:'Crafting' },
      { key:'Sleight of hand', label:'Sleight of hand' },
      { key:'Alchemy', label:'Alchemy' },
      { key:'Medicine', label:'Medicine' },
      { key:'Engineering', label:'Engineering' },
    ]},
  ];
  const INTENSITIES = ['Fire','Water','Earth','Wind','Lightning','Moon','Sun','Ki'];

  // Build editor (unchanged, except data keys standardized to match backend)
  const charSkillContainer = $('#charSkillContainer');
  CHAR_MAP.forEach(group => {
    const header = document.createElement('div');
    header.className = 'rowline';
    header.innerHTML = `
      <div class="h">${group.label}</div>
      <div class="mini">Invested</div>
      <div class="mini">Modifier</div>
      <div class="mini">[ Total | Mod ]</div>
    `;
    charSkillContainer.appendChild(header);

    const row = document.createElement('div');
    row.className = 'rowline';
    row.innerHTML = `
      <div><span class="muted">Characteristic</span></div>
      <div><input class="input" type="number" min="0" max="16" value="0" data-c-invest="${group.investKey}"></div>
      <div><span class="mono" data-c-mod="${group.key}">0</span></div>
      <div><span class="mono" data-c-total="${group.key}">4</span> | <span class="mono" data-c-totalmod="${group.key}">-3</span></div>
    `;
    charSkillContainer.appendChild(row);

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

  // Sublimations
  const SUB_TYPES = [
    { id:'2', label:'Lethality' },
    { id:'1', label:'Excellence' },
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
    delBtn.addEventListener('click', () => { tr.remove(); recompute(); triggerSave(); });

    function toggleSkill(){
      skillSel.disabled = (typeSel.value !== '1');
      skillSel.style.opacity = skillSel.disabled ? .5 : 1;
    }
    toggleSkill();

    typeSel.addEventListener('change', ()=>{ toggleSkill(); recompute(); triggerSave(); });
    skillSel.addEventListener('change', ()=>{ recompute(); triggerSave(); });
    tierInp.addEventListener('input', ()=>{ recompute(); triggerSave(); });
    delBtn.addEventListener('click', ()=>{ tr.remove(); recompute(); triggerSave(); });
    
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
    recompute();
  }
  // seed
  addSubRow();

  // ====== Local recompute (unchanged core, but we’ll later overwrite with server computed) ======
  const num = id => Number($(id).value || 0);
  const setTxt = (id, v) => { $(id).textContent = String(v); };

  const modFromScore = score => Math.floor(score/2 - 5);
  const scoreFromInvest = invest => 4 + invest;
  const milestoneCount = mod => Math.max(mod, 0);

  function levelFromXP(xp){
    const k = Math.floor((-1 + Math.sqrt(1 + 8*(xp/100)))/2);
    return Math.min(k+1, 100);
  }

  function idIvFromBV(bv){
    if (bv <= 0) return ['—','—'];
    if (bv <= 7) return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10', 5];
    if (bv >= 18) return ['1d12', 6];
    return ['—','—'];
  }

  function rwFor(name, ivMap){ return 0; }

  function readLevel(){
    const lvlInp = $('#c_level');
    const xpInp = $('#c_xp');
    let lvl = Number(lvlInp.value || 1);
    if (!lvl || lvl < 1){
      lvl = levelFromXP(Number(xpInp.value||0));
    }
    return Math.min(Math.max(lvl,1),100);
  }

  function sumSubType(code){
    return Array.from($('#subTable tbody').children).reduce((acc, tr) => {
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

  function decorateCaps(skillCap, charCap, spMax, cpMax, subMax, tierCap){
    CHAR_MAP.forEach(g => g.skills.forEach(s => {
      const inp = $(`[data-s-invest="${s.key}"]`);
      const val = Number(inp.value||0);
      inp.style.borderColor = (val>skillCap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    }));
    CHAR_MAP.forEach(g => {
      const inp = $(`[data-c-invest="${g.investKey}"]`);
      const sc = scoreFromInvest(Number(inp.value||0));
      inp.style.borderColor = (sc>20) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
    const spUsed = Number($('#sp_used').textContent||0);
    $('#sp_used').classList.toggle('danger', spUsed>spMax);
    const cpUsed = Number($('#cp_used').textContent||0);
    $('#cp_used').classList.toggle('danger', cpUsed>cpMax);
    const subUsed = Number($('#sub_used').textContent||0);
    $('#sub_used').classList.toggle('danger', subUsed>subMax);

    Array.from($('#subTable tbody').children).forEach(tr=>{
      const { tierInp } = tr._refs;
      const t = Number(tierInp.value||0);
      tierInp.style.borderColor = (t>tierCap) ? '#ef4444' : 'rgba(255,255,255,.1)';
    });
  }

  function recompute(){
    const lvl = readLevel();
    $('#c_level').value = String(lvl);

    const charInvest = {};
    const charMod = {};
    CHAR_MAP.forEach(g => {
      const invest = Number($(`[data-c-invest="${g.investKey}"]`).value || 0);
      charInvest[g.key] = invest;
      const score = scoreFromInvest(invest);
      const mod = modFromScore(score);
      charMod[g.key] = mod;
      $(`[data-c-total="${g.key}"]`).textContent = String(score);
      $(`[data-c-totalmod="${g.key}"]`).textContent = String(mod);
      $(`[data-c-mod="${g.key}"]`).textContent = String(mod);
    });

    const skillInvest = {};
    const excellenceMap = {};
    const subRows = Array.from(subTableBody.children);
    let subUsed = 0;
    let tierMax = 1;

    subRows.forEach(tr => {
      const { typeSel, skillSel, tierInp, slotsCell } = tr._refs;
      const tier = Math.max(0, Number(tierInp.value||0));
      slotsCell.textContent = String(tier);
      subUsed += tier;
      if (typeSel.value === '1' && skillSel.value){
        excellenceMap[skillSel.value] = (excellenceMap[skillSel.value]||0) + tier;
      }
      tierMax = Math.max(tierMax, tier);
    });

    CHAR_MAP.forEach(g => {
      g.skills.forEach(s => {
        const inv = Number($(`[data-s-invest="${s.key}"]`).value || 0);
        skillInvest[s.key] = inv;
        const bonus = Math.min(inv, excellenceMap[s.key] || 0);
        const base = inv + bonus + (charMod[g.key]||0);
        $(`[data-s-mod="${s.key}"]`).textContent = String(bonus);
        $(`[data-s-base="${s.key}"]`).textContent = String(base);
      });
    });

    const cp_used = Object.values(charInvest).reduce((a,b)=>a+b,0);
    const cp_max = 22 + Math.floor((lvl-1)/9)*3;
    const sp_used = Object.values(skillInvest).reduce((a,b)=>a+b,0);
    const sp_max  = 40 + (lvl-1)*2;
    const skill_cap = (lvl >= 50 ? 8 : lvl >= 40 ? 7 : lvl >= 30 ? 6 : lvl >= 20 ? 5 : lvl >= 10 ? 4 : 3);
    const char_cap = 10;

    setTxt('#cp_used', cp_used);
    setTxt('#cp_max', cp_max);
    setTxt('#sp_used', sp_used);
    setTxt('#sp_max', sp_max);
    setTxt('#skill_cap', skill_cap);
    setTxt('#char_cap', char_cap);

    const mile_pre = Math.max(charMod.pre || 0, 0);
    const sub_max = (mile_pre*2) + Math.floor(lvl/10);
    const tier_cap = Math.ceil(lvl/25);
    setTxt('#sub_used', subUsed);
    setTxt('#sub_max', sub_max);
    setTxt('#sub_tier', tier_cap);

    const lvl_up_count = Math.max(lvl-1, 0);
    const mile_bod = Math.max(charMod.bod || 0, 0);
    const mile_wil = Math.max(charMod.wil || 0, 0);
    const mile_mag = Math.max(charMod.mag || 0, 0);
    const mile_dex = Math.max(charMod.dex || 0, 0);
    const mile_ref = Math.max(charMod.ref || 0, 0);
    const mile_wis = Math.max(charMod.wis || 0, 0);

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

    const resistance = Number($('[data-s-base="Resistance"]')?.textContent||0);
    const alchemyBV  = Number($('[data-s-base="Alchemy"]')?.textContent||0);
    const tx_max = resistance + alchemyBV;
    setResource('#tx_cur','#tx_max','#tx_bar',0,tx_max);

    const athletics = Number($('[data-s-base="Athletics"]')?.textContent||0);
    const spiritBV  = Number($('[data-s-base="Spirit"]')?.textContent||0);
    const enc_max = 10 + (athletics*5) + (spiritBV*2);
    setResource('#enc_cur','#enc_max','#enc_bar',0,enc_max);

    setTxt('#k_mo', mo);
    setTxt('#k_init', mo + mile_ref);
    setTxt('#k_et', et);
    setTxt('#k_cdc', cdc);

    const magic_mod = charMod.mag || 0;
    const ivMap = {};
    INTENSITIES.forEach(nm => {
      const inv = Number($(`[data-i-invest="${nm}"]`).value || 0);
      const mod = magic_mod;
      const base = (inv>0 ? inv + mod : 0);
      const [ID, IV] = idIvFromBV(base);
      ivMap[nm] = Number(IV || 0);

      $(`[data-i-mod="${nm}"]`).textContent = String(mod);
      $(`[data-i-base="${nm}"]`).textContent = String(base);
      $(`[data-i-id="${nm}"]`).textContent = String(ID);
      $(`[data-i-iv="${nm}"]`).textContent = String(IV||'—');
    });
    INTENSITIES.forEach(nm => { $(`[data-i-rw="${nm}"]`).textContent = String(rwFor(nm, ivMap)); });

    decorateCaps(skill_cap, char_cap, sp_max, cp_max, sub_max, tier_cap);
  }

  // ====== API wiring ======
  const cidInput = $('#c_id');

  async function apiCreate(payload){
    const res = await fetch(`${API_BASE}/characters`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(payload)
    });
    const j = await res.json();
    if (!res.ok) throw new Error(j.message || j.error || res.statusText);
    return j;
  }
  async function apiGet(id){
    const res = await fetch(`${API_BASE}/characters/${encodeURIComponent(id)}`, {
      headers: authHeaders()
    });
    const j = await res.json();
    if (!res.ok) throw new Error(j.message || j.error || res.statusText);
    return j;
  }
  async function apiUpdate(id, payload){
    const res = await fetch(`${API_BASE}/characters/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify(payload)
    });
    const j = await res.json();
    if (!res.ok) throw new Error(j.message || j.error || res.statusText);
    return j;
  }

  function collectPayload(){
    const lvl = Number($('#c_level').value||1);
    const xp  = Number($('#c_xp').value||0);
    const useManual = !!$('#c_level').value;

    const characteristics = {};
    CHAR_MAP.forEach(g => {
      const v = Number($(`[data-c-invest="${g.investKey}"]`).value || 0);
      characteristics[g.investKey] = v;
    });

    const skills = {};
    CHAR_MAP.forEach(g => g.skills.forEach(s => {
      skills[s.key] = Number($(`[data-s-invest="${s.key}"]`).value || 0);
    }));
    INTENSITIES.forEach(nm => {
      skills[nm] = Number($(`[data-i-invest="${nm}"]`).value || 0);
    });

    const sublimations = Array.from(subTableBody.children).map(tr => {
      const { typeSel, skillSel, tierInp } = tr._refs;
      const map = { '1':'Excellence', '2':'Lethality', '3':'Blessing', '4':'Defense', '5':'Speed', '6':'Endurance', '7':'Devastation', '8':'Clarity' };
      return {
        type: map[typeSel.value] || 'Lethality',
        tier: Number(tierInp.value||0),
        skill: (typeSel.value === '1' ? (skillSel.value || null) : null)
      };
    });

    return {
      name: ($('#c_name').value || 'Unnamed').trim(),
      img: ($('#avatarUrl').value || '').trim(),
      xp_total: xp,
      level_manual: useManual ? lvl : null,
      characteristics,
      skills,
      sublimations,
      bio: {
        height: ($('#p_height').value||'').trim(),
        weight: ($('#p_weight').value||'').trim(),
        birthday: ($('#p_bday').value||'').trim(),
        backstory: ($('#p_backstory').value||'').trim(),
        notes: ($('#p_notes').value||'').trim(),
      }
    };
  }

  function applyServerComputed(payload){
    // payload: { status, character, computed }
    const c = payload?.computed;
    if (!c) return;

    // Derived resources
    const d = c.derived || {};
    const clamp = (v)=> Number.isFinite(v)?v:0;
    setResource('#hp_cur','#hp_max','#hp_bar', clamp(d.hp_max), clamp(d.hp_max));
    setResource('#sp_cur','#sp_max','#sp_bar', 0, Math.floor(clamp(d.hp_max)*0.1));
    setResource('#en_cur','#en_max','#en_bar', Math.min(5, clamp(d.en_max)), clamp(d.en_max));
    setResource('#fo_cur','#fo_max','#fo_bar', Math.min(2, clamp(d.fo_max)), clamp(d.fo_max));
    setResource('#tx_cur','#tx_max','#tx_bar', 0, clamp(d.tx_max));
    setResource('#enc_cur','#enc_max','#enc_bar', 0, clamp(d.encumbrance_max));

    // Badges (MO, Initiative, ET, Condition DC)
    setTxt('#k_mo', clamp(d.mo));
    setTxt('#k_init', clamp(d.mo) + (c.milestones?.REF || 0));
    setTxt('#k_et', clamp(d.et));
    setTxt('#k_cdc', clamp(d.condition_dc));

    // Caps / points (server truth)
    if (c.caps){
      setTxt('#skill_cap', c.caps.skill_cap);
      setTxt('#char_cap', c.caps.characteristic_cap);
    }
    const subs = c.sublimations || {};
    if (typeof subs.slots_used !== 'undefined') setTxt('#sub_used', subs.slots_used);
    if (typeof subs.slots_max !== 'undefined') setTxt('#sub_max', subs.slots_max);
  }

  // ====== Autosave wiring ======
  let saveTimer = null;
  function debounce(fn, ms=500){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a), ms); }; }
  const triggerSave = debounce(saveNow, 500);

  async function saveNow(){
    try {
      setStatus("Saving…");
      const payload = collectPayload();
      const existingId = (cidInput.value || "").trim();
      const resp = existingId ? await apiUpdate(existingId, payload)
                              : await apiCreate(payload);
      // keep id & apply computed values from server if any
      if (resp?.character?.id) cidInput.value = String(resp.character.id);
      if (resp?.computed) applyServerComputed(resp);
      setStatus("Saved", "good");
    } catch (e) {
      console.error(e);
      setStatus(`Save failed`, "danger");
    }
  }

  // Save on any user change
  const changeSelectors = [
    '#c_name','#c_level','#c_xp','#avatarUrl',
    '#p_height','#p_weight','#p_bday','#p_backstory','#p_notes'
  ];
  changeSelectors.forEach(sel => {
    const el = $(sel); if (el) el.addEventListener('input', ()=>{ recompute(); triggerSave(); });
  });

  // Characteristics & skills & intensities
  $$('#charSkillContainer input').forEach(inp =>
    inp.addEventListener('input', ()=>{ recompute(); triggerSave(); })
  );
  $$('#intensityTable [data-i-invest]').forEach(inp =>
    inp.addEventListener('input', ()=>{ recompute(); triggerSave(); })
  );

  // Sublimations: we already call recompute() inside row add/remove/change;
  // just ensure triggerSave() is also called in the same places.
  // (In addSubRow, after recompute(), also call triggerSave())

  // Load if id is in query (?id=123)
  document.addEventListener('DOMContentLoaded', async () => {
    const qid = new URLSearchParams(location.search).get('id');
    if (qid) {
      try {
        setStatus("Loading…");
        const resp = await apiGet(qid);
        cidInput.value = String(resp.character.id);
        // TODO: write a small hydrator to push server values into the inputs if needed
        // For now we rely on local inputs and deriveds.
        if (resp.computed) applyServerComputed(resp);
        setStatus("Loaded");
      } catch {
        setStatus("Load failed", "danger");
      }
    }
    recompute();
  });
})();