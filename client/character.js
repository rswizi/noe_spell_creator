/* character.js — clean wiring to /characters with 2-col stats, correct milestones, Excellence, and debounced autosave */

(() => {
  // ---------- Tiny helpers ----------
  const $  = (sel, el=document) => el.querySelector(sel);
  const $$ = (sel, el=document) => Array.from(el.querySelectorAll(sel));
  const num = (v) => (v===''||v==null) ? 0 : Number(v);

  const cidInput   = $('#c_id');           // hidden input holding character id
  const saveStatus = $('#saveStatus');     // small pill to show status
  const setStatus  = (txt, kind='') => {
    if (!saveStatus) return;
    saveStatus.textContent = txt;
    saveStatus.classList.remove('good','danger');
    if (kind) saveStatus.classList.add(kind);
  };

  // ---------- Static maps (must match your HTML) ----------
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

  // ---------- Game math ----------
  const modFromScore = (score) => Math.floor(score/2 - 5);   // Milestone = characteristic modifier
  const scoreFromInv = (inv) => 4 + inv;

  // dice table (if you show ID/IV elsewhere)
  const idIvFromBV = (bv) => {
    if (bv <= 0) return ['—','—'];
    if (bv <= 7)  return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10', 5];
    return ['1d12', 6];
  };

  // ---------- Sublimation wiring ----------
  const SUB_TYPES = [
    { id:'2', label:'Lethality' },
    { id:'1', label:'Excellence' },  // needs a skill
    { id:'3', label:'Blessing' },
    { id:'4', label:'Defense' },
    { id:'5', label:'Speed' },
    { id:'7', label:'Devastation' },
    { id:'8', label:'Clarity' },
    { id:'6', label:'Endurance' },
  ];
  const SKILL_OPTIONS = GROUPS.flatMap(g => g.skills);

  const subBody = $('#subTable tbody');
  const btnAddSub = $('#btnAddSub');
  if (btnAddSub) btnAddSub.addEventListener('click', () => addSubRow());

  function addSubRow(defaults = { type:'2', skill:'', tier:1 }) {
    const tr = document.createElement('tr');

    // Type
    const typeSel = document.createElement('select');
    typeSel.className = 'input';
    SUB_TYPES.forEach(t => {
      const o = document.createElement('option');
      o.value = t.id; o.textContent = t.label;
      if (String(defaults.type) === t.id) o.selected = true;
      typeSel.appendChild(o);
    });

    // Skill (only enabled for Excellence)
    const skillSel = document.createElement('select');
    skillSel.className = 'input';
    const optEmpty = document.createElement('option'); optEmpty.value=''; optEmpty.textContent='—';
    skillSel.appendChild(optEmpty);
    SKILL_OPTIONS.forEach(k => {
      const o = document.createElement('option');
      o.value = k; o.textContent = k.charAt(0).toUpperCase()+k.slice(1);
      if (defaults.skill === k) o.selected = true;
      skillSel.appendChild(o);
    });

    const tierInp = document.createElement('input');
    tierInp.type = 'number'; tierInp.min = '0'; tierInp.max = '4';
    tierInp.className = 'input xs';
    tierInp.value = String(defaults.tier ?? 1);

    const slotsCell = document.createElement('td');
    slotsCell.className = 'right mono';
    slotsCell.textContent = String(defaults.tier ?? 1);

    const delBtn = document.createElement('button');
    delBtn.className = 'btn ghost'; delBtn.textContent = 'Remove';
    delBtn.addEventListener('click', () => { tr.remove(); recompute(); triggerSave(); });

    function toggleSkill(){
      const isEx = typeSel.value === '1';
      skillSel.disabled = !isEx;
      skillSel.style.opacity = isEx ? 1 : .5;
    }
    toggleSkill();

    typeSel.addEventListener('change', ()=>{ toggleSkill(); recompute(); triggerSave(); });
    skillSel.addEventListener('change', ()=>{ recompute(); triggerSave(); });
    tierInp.addEventListener('input',   ()=>{ slotsCell.textContent = String(num(tierInp.value)); recompute(); triggerSave(); });

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
    subBody.appendChild(tr);
    recompute();
  }
  // seed a row if table is empty
  if (subBody && !subBody.children.length) addSubRow();

  // ---------- Reading inputs ----------
  function readLevel() {
    const lvl = num($('#c_level')?.value || 1);
    const xp  = num($('#c_xp')?.value || 0);
    // Level is manual if present; (XP->level) left to backend for truth
    return Math.max(1, lvl || 1);
  }

  // ---------- Recompute (pure UI compute so the sheet feels alive) ----------
  function recompute(){
    const lvl = readLevel();

    // Collect characteristic investments + milestones
    const investC = {};
    const scoreC  = {};
    const mileC   = {};
    GROUPS.forEach(g => {
      const inv = num($(`[data-c-invest="${g.investKey}"]`)?.value || 0);
      investC[g.key] = inv;
      const score = scoreFromInv(inv);
      const ms    = modFromScore(score);
      scoreC[g.key] = score;
      mileC[g.key]  = ms;

      // Write milestones/total in the UI (characteristic row only)
      const tot = $(`[data-c-total="${g.key}"]`);
      const mil = $(`[data-c-milestone="${g.key}"]`);
      if (tot) tot.textContent = String(score);
      if (mil) mil.textContent = String(ms);
    });

    // Sublimations summary (we only need Excellence for UI math)
    const subRows = Array.from(subBody?.children || []);
    const excellenceBySkill = {};
    let subSlotsUsed = 0;
    subRows.forEach(tr => {
      const { typeSel, skillSel, tierInp } = tr._refs;
      const tier = Math.max(0, num(tierInp.value));
      subSlotsUsed += tier;
      if (typeSel.value === '1' && skillSel.value) {
        excellenceBySkill[skillSel.value] = (excellenceBySkill[skillSel.value] || 0) + tier;
      }
    });
    $('#sub_used') && ($('#sub_used').textContent = String(subSlotsUsed));

    // Skills base values
    GROUPS.forEach(g => {
      g.skills.forEach(sk => {
        const inv = num($(`[data-s-invest="${sk}"]`)?.value || 0);
        const exBonus = Math.min(inv, excellenceBySkill[sk] || 0); // Excellence cap = invested
        const base = inv + exBonus + (mileC[g.key] || 0);          // Milestone only from characteristic
        const baseNode = $(`[data-s-base="${sk}"]`);
        const modNode = $(`[data-s-mod="${sk}"]`);                  // show bonus from Excellence next to the skill
        if (baseNode) baseNode.textContent = String(base);
        if (modNode)  modNode.textContent  = String(exBonus);
      });
    });

    // Derived (HP/SP/EN/FO/TX/Enc/ET/Condition DC/etc.) are shown from server compute
    // after each save; here we just keep bars coherent if values exist:
    function setBar(curSel, maxSel, barSel){
      const cur = num($(curSel)?.textContent || 0);
      const max = num($(maxSel)?.textContent || 0);
      const pct = max>0 ? Math.round((cur/max)*100) : 0;
      const i = $(barSel); if (i) i.style.width = `${pct}%`;
    }
    setBar('#hp_cur', '#hp_max', '#hp_bar');
    setBar('#sp_cur', '#sp_max', '#sp_bar');
    setBar('#en_cur', '#en_max', '#en_bar');
    setBar('#fo_cur', '#fo_max', '#fo_bar');
    setBar('#tx_cur', '#tx_max', '#tx_bar');
    setBar('#enc_cur','#enc_max','#enc_bar');
  }

  // ---------- API (uses /characters as in main.py) ----------
  const API = {
    async create(payload){
      const r = await fetch('/characters', {
        method:'POST', headers:{'Content-Type':'application/json'},
        credentials:'include', body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
    async get(id){
      const r = await fetch(`/characters/${encodeURIComponent(id)}`, { credentials:'include' });
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
    async update(id, payload){
      const r = await fetch(`/characters/${encodeURIComponent(id)}`, {
        method:'PUT', headers:{'Content-Type':'application/json'},
        credentials:'include', body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    }
  };

  // ---------- Collect payload for save ----------
  function collectPayload(){
    const payload = {
      name: ($('#c_name')?.value || '').trim(),
      img:  ($('#avatarUrl')?.value || '').trim(),
      xp_total: num($('#c_xp')?.value || 0),
      level_manual: ($('#c_level')?.value === '' ? null : num($('#c_level')?.value)),
      characteristics: {},
      skills: {},
      sublimations: [],
      bio: {
        height: ($('#p_height')?.value || '').trim(),
        weight: ($('#p_weight')?.value || '').trim(),
        birthday: ($('#p_bday')?.value || '').trim(),
        backstory: ($('#p_backstory')?.value || '').trim(),
        notes: ($('#p_notes')?.value || '').trim(),
      }
    };

    GROUPS.forEach(g => {
      payload.characteristics[g.investKey] = num($(`[data-c-invest="${g.investKey}"]`)?.value || 0);
      g.skills.forEach(sk => {
        payload.skills[sk] = num($(`[data-s-invest="${sk}"]`)?.value || 0);
      });
    });

    // intensities (treated as skills on backend; if you store them separately, include here too)
    INTENSITIES.forEach(nm => {
      const k = nm.toLowerCase();
      const v = num($(`[data-i-invest="${nm}"]`)?.value || 0);
      if (!Number.isNaN(v)) payload.skills[k] = v;
    });

    // sublimations array
    Array.from(subBody?.children || []).forEach(tr => {
      const { typeSel, skillSel, tierInp } = tr._refs;
      const t = typeSel.value;
      const typeMap = { '1':'Excellence','2':'Lethality','3':'Blessing','4':'Defense','5':'Speed','6':'Endurance','7':'Devastation','8':'Clarity' };
      payload.sublimations.push({
        type: typeMap[t] || 'Lethality',
        tier: num(tierInp.value || 0),
        skill: (t === '1' && skillSel.value) ? skillSel.value : null
      });
    });

    return payload;
  }

  // ---------- Apply server-computed values back into UI ----------
  function applyComputed(resp){
    const c = resp?.computed; if (!c) return;
    // Derived badges
    $('#k_mo')     && ($('#k_mo').textContent     = String(c.derived.movement));
    $('#k_init')   && ($('#k_init').textContent   = String(c.derived.initiative));
    $('#k_et')     && ($('#k_et').textContent     = String(c.derived.et));
    $('#k_cdc')    && ($('#k_cdc').textContent    = String(c.derived.condition_dc));

    // Resources
    const setRes = (curSel,maxSel,barSel,cur,max) => {
      $(curSel).textContent = String(cur);
      $(maxSel).textContent = String(max);
      const i = $(barSel); if (i) i.style.width = max>0 ? `${Math.round((cur/max)*100)}%` : '0%';
    };
    setRes('#hp_cur','#hp_max','#hp_bar', c.derived.hp_current ?? c.derived.hp_max, c.derived.hp_max);
    setRes('#sp_cur','#sp_max','#sp_bar', c.derived.sp_current ?? c.derived.sp_max, c.derived.sp_max);
    setRes('#en_cur','#en_max','#en_bar', c.derived.en_current ?? c.derived.en_max, c.derived.en_max);
    setRes('#fo_cur','#fo_max','#fo_bar', c.derived.fo_current ?? c.derived.fo_max, c.derived.fo_max);
    setRes('#tx_cur','#tx_max','#tx_bar', c.derived.tx_current ?? c.derived.tx_max, c.derived.tx_max);
    setRes('#enc_cur','#enc_max','#enc_bar', c.derived.enc_current ?? c.derived.enc_max, c.derived.enc_max);

    // Characteristic [Total | Milestone] header numbers
    GROUPS.forEach(g => {
      const tot = $(`[data-c-total="${g.key}"]`);
      const mil = $(`[data-c-milestone="${g.key}"]`);
      if (tot) tot.textContent = String(c.totals[g.key] ?? scoreFromInv(num($(`[data-c-invest="${g.investKey}"]`)?.value || 0)));
      if (mil) mil.textContent = String(c.milestones[g.key] ?? modFromScore(scoreFromInv(num($(`[data-c-invest="${g.investKey}"]`)?.value || 0))));
    });

    // Sublimation slots
    $('#sub_max') && ($('#sub_max').textContent = String(c.sublimations.slots_max));
    $('#sub_used')&& ($('#sub_used').textContent = String(c.sublimations.slots_used));
  }

  // ---------- Autosave (debounced) ----------
  let saveTimer = null;
  function triggerSave(){
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveNow, 500);
  }

  async function saveNow(){
    try{
      setStatus('Saving…');
      const payload = collectPayload();
      const id = (cidInput?.value || '').trim();
      const resp = id ? await API.update(id, payload) : await API.create(payload);
      const newId = id || resp?.character?.id;
      if (newId && !cidInput.value) {
        cidInput.value = newId;
        const u = new URL(location.href); u.searchParams.set('id', newId);
        history.replaceState(null, '', u.toString());
      }
      applyComputed(resp);
      setStatus('Saved','good');
    }catch(err){
      console.error(err);
      setStatus('Error','danger');
    }
  }

  // ---------- Bind inputs (always recompute then autosave) ----------
  [
    '#c_name','#c_level','#c_xp','#avatarUrl',
    '#p_height','#p_weight','#p_bday','#p_backstory','#p_notes'
  ].forEach(sel => $(sel)?.addEventListener('input', () => { recompute(); triggerSave(); }));

  // characteristic/skill/intensity inputs
  $$('#charSkillContainer input').forEach(inp =>
    inp.addEventListener('input', () => { recompute(); triggerSave(); })
  );
  $$('#intensityTable [data-i-invest]').forEach(inp =>
    inp.addEventListener('input', () => { recompute(); triggerSave(); })
  );

  // Avatar preview
  $('#avatarUrl')?.addEventListener('change', () => {
    const url = $('#avatarUrl').value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
    $('#charAvatar').src = url;
  });

  // ---------- Boot: load if ?id= is present ----------
  (async function init(){
    setStatus('Ready');
    const qid = new URLSearchParams(location.search).get('id');
    if (qid){
      try{
        setStatus('Loading…');
        const resp = await API.get(qid);
        const doc  = resp.character;
        cidInput.value = doc.id || '';
        // hydrate a few basics (you can extend as needed)
        $('#c_name').value   = doc.name || '';
        $('#avatarUrl').value = doc.img || '';
        $('#charAvatar').src  = doc.img || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
        $('#c_xp').value     = Number(doc.xp_total || 0);
        $('#c_level').value  = doc.level_manual ?? '';
        // characteristics
        const ch = doc.characteristics || {};
        GROUPS.forEach(g => { $(`[data-c-invest="${g.investKey}"]`).value = ch[g.investKey] ?? 0; });
        // skills
        const sk = doc.skills || {};
        GROUPS.forEach(g => g.skills.forEach(k => { const n=$(`[data-s-invest="${k}"]`); if (n) n.value = sk[k] ?? 0; }));
        INTENSITIES.forEach(nm => { const k = nm.toLowerCase(); const n = $(`[data-i-invest="${nm}"]`); if (n) n.value = sk[k] ?? 0; });
        // sublimations
        subBody.innerHTML = '';
        (doc.sublimations || []).forEach(s => {
          const map = {Excellence:'1',Lethality:'2',Blessing:'3',Defense:'4',Speed:'5',Endurance:'6',Devastation:'7',Clarity:'8'};
          addSubRow({ type: map[s.type] || '2', skill: s.skill || '', tier: s.tier || 1 });
        });
        applyComputed(resp);
        setStatus('Loaded','good');
      }catch(e){
        console.warn(e);
        setStatus('Load failed','danger');
      }
    }
    recompute();
  })();

})();