(() => {
  const $  = (s,e=document)=>e.querySelector(s);
  const $$ = (s,e=document)=>Array.from(e.querySelectorAll(s));
  const num = v => (v===''||v==null) ? 0 : Number(v);

  /* ---------- Tabs ---------- */
  $$('.tab').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      $$('.tab').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      const key = btn.dataset.tab;
      $$('.tabpan').forEach(p=>p.classList.remove('active'));
      $(`#tab-${key}`).classList.add('active');
    });
  });

  /* ---------- Avatar ---------- */
  const avatarUrl = $('#avatarUrl');
  const charAvatar = $('#charAvatar');
  avatarUrl?.addEventListener('input', ()=>{
    charAvatar.src = avatarUrl.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
    debounceSave();
  });

  /* ---------- Static map (HTML is hard-coded) ---------- */
  const GROUPS = [
    { key:'ref', invest:'reflexp',  skills:['technicity','dodge','tempo','reactivity'] },
    { key:'dex', invest:'dexterityp',skills:['accuracy','evasion','stealth','acrobatics'] },
    { key:'bod', invest:'bodyp',     skills:['brutality','blocking','resistance','athletics'] },
    { key:'wil', invest:'willpowerp',skills:['intimidation','spirit','instinct','absorption'] },
    { key:'mag', invest:'magicp',    skills:['aura','incantation','enchantment','restoration','potential'] },
    { key:'pre', invest:'presencep', skills:['taming','charm','charisma','deception','persuasion'] },
    { key:'wis', invest:'wisdomp',   skills:['survival','education','perception','psychology','investigation'] },
    { key:'tec', invest:'techp',     skills:['crafting','soh','alchemy','medecine','engineering'] },
  ];

  /* ---------- Sublimations ---------- */
  const subBody = $('#subTable tbody');
  $('#btnAddSub')?.addEventListener('click', ()=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>
        <select class="input" data-sub-type>
          <option value="2">Lethality</option>
          <option value="1">Excellence</option>
          <option value="3">Blessing</option>
          <option value="4">Defense</option>
          <option value="5">Speed</option>
          <option value="7">Devastation</option>
          <option value="8">Clarity</option>
          <option value="6">Endurance</option>
        </select>
      </td>
      <td>
        <select class="input" data-sub-skill disabled>
          <option value="">—</option>
          ${GROUPS.flatMap(g=>g.skills).map(k=>{
            // pretty labels
            const name = ({
              soh:'Sleight of hand', medecine:'Medicine'
            })[k] || k.charAt(0).toUpperCase()+k.slice(1);
            return `<option value="${k}">${name}</option>`;
          }).join('')}
        </select>
      </td>
      <td><input class="input" type="number" min="0" max="4" value="1" data-sub-tier></td>
      <td class="right mono" data-sub-slots>1</td>
      <td><button class="btn ghost" data-sub-remove>Remove</button></td>
    `;
    subBody.appendChild(tr);
    wireSubRow(tr);
    recompute(); debounceSave();
  });

  function wireSubRow(tr){
    const typeSel  = $('[data-sub-type]', tr);
    const skillSel = $('[data-sub-skill]', tr);
    const tierInp  = $('[data-sub-tier]', tr);
    const slots    = $('[data-sub-slots]', tr);
    const delBtn   = $('[data-sub-remove]', tr);

    const toggle = ()=>{
      const isEx = typeSel.value === '1';
      skillSel.disabled = !isEx;
      skillSel.style.opacity = isEx ? '1' : '.5';
    };
    toggle();

    typeSel.addEventListener('change', ()=>{ toggle(); recompute(); debounceSave(); });
    skillSel.addEventListener('change', ()=>{ recompute(); debounceSave(); });
    tierInp.addEventListener('input', ()=>{ slots.textContent = String(num(tierInp.value||0)); recompute(); debounceSave(); });
    delBtn.addEventListener('click', ()=>{ tr.remove(); recompute(); debounceSave(); });
  }
  // (no initial row; table can be empty and the app still works)

  /* ---------- Math helpers ---------- */
  const scoreFromInvest     = invest => 4 + invest;
  const milestoneFromScore  = score  => Math.floor(score/2 - 5); // this is “Milestone” value
  const tens                = lvl    => Math.floor(lvl/10);
  const floorDiv            = (n,d)  => Math.floor(n/d);

  /* ---------- Recompute ---------- */
  function recompute(){
    const lvl = Math.max(1, num($('#c_level')?.value || 1));

    // characteristic totals & milestones
    const charMil = {};
    GROUPS.forEach(g=>{
      const inv = num($(`[data-invest-input="${g.invest}"]`).value || 0);
      const score = scoreFromInvest(inv);
      const ms = milestoneFromScore(score);
      charMil[g.key] = ms;
      $(`[data-total="${g.key}"]`).textContent     = String(score);
      $(`[data-milestone="${g.key}"]`).textContent = String(ms);
    });

    // sublimations: slots & Excellence map
    let subUsed = 0;
    const exMap = {};
    $$('#subTable tbody tr').forEach(tr=>{
      const typeSel = $('[data-sub-type]', tr);
      const skillSel= $('[data-sub-skill]', tr);
      const tier    = Math.max(0, num($('[data-sub-tier]', tr).value||0));
      subUsed += tier;
      if(typeSel.value==='1' && skillSel.value){
        exMap[skillSel.value] = (exMap[skillSel.value]||0) + tier;
      }
    });
    $('#sub_used').textContent = String(subUsed);

    // compute skills base (invested + Excellence bonus + char milestone)
    GROUPS.forEach(g=>{
      g.skills.forEach(sk=>{
        const inv = num($(`[data-skill="${sk}"]`)?.value || 0);
        const ex  = Math.min(inv, exMap[sk] || 0); // bonus can’t exceed invested
        const base= inv + ex + Math.max(charMil[g.key]||0, 0); // only positive milestones add to base
        $(`[data-base="${sk}"]`).textContent = String(base);
      });
    });

    // caps & counters
    const skill_cap = (lvl >= 50 ? 8 : lvl >= 40 ? 7 : lvl >= 30 ? 6 : lvl >= 20 ? 5 : lvl >= 10 ? 4 : 3);
    const cp_max = 22 + floorDiv((lvl-1),9)*3;
    const sp_max = 40 + (lvl-1)*2;
    const cp_used= GROUPS.reduce((a,g)=> a + num($(`[data-invest-input="${g.invest}"]`).value||0), 0);
    const sp_used= GROUPS.reduce((a,g)=> a + g.skills.reduce((aa,s)=> aa + num($(`[data-skill="${s}"]`).value||0), 0), 0);
    $('#skill_cap').textContent = String(skill_cap);
    $('#char_cap').textContent  = '10';
    $('#cp_max').textContent    = String(cp_max);
    $('#sp_max').textContent    = String(sp_max);
    $('#cp_used').textContent   = String(cp_used);
    $('#sp_used').textContent   = String(sp_used);

    // badges (MO, Initiative, ET, Condition DC)
    const mile_ref = Math.max(charMil.ref||0,0);
    const mile_dex = Math.max(charMil.dex||0,0);
    const mile_mag = Math.max(charMil.mag||0,0);
    const mo = 4 + mile_ref + mile_dex + sumSubType('5');
    $('#k_mo').textContent   = String(mo);
    $('#k_init').textContent = String(mo + mile_ref);
    $('#k_et').textContent   = String(1 + floorDiv((lvl-1),9) + mile_mag);
    $('#k_cdc').textContent  = String(6 + tens(lvl) + sumSubType('7'));

    // resources
    const lvl_up = Math.max(lvl-1,0);
    const mile_bod = Math.max(charMil.bod||0,0);
    const mile_wil = Math.max(charMil.wil||0,0);
    const mile_pre = Math.max(charMil.pre||0,0);
    const clarity  = sumSubType('8');   // +1 FO per tier
    const endur    = sumSubType('6');   // +2 EN per tier
    const defSub   = sumSubType('4');   // +12 HP per tier

    const hp_max = 100 + lvl_up + (12*mile_bod) + (6*mile_wil) + (12*defSub);
    const en_max = 5 + floorDiv(lvl_up,5) + (2*mile_wil) + (4*mile_mag) + (2*endur);
    const fo_max = 2 + floorDiv(lvl_up,5) + mile_wil + mile_pre + clarity;

    setBar('#hp_cur','#hp_max','#hp_bar', hp_max,hp_max);
    setBar('#sp_cur','#sp_max','#sp_bar', 0, Math.floor(hp_max*0.1));
    setBar('#en_cur','#en_max','#en_bar', Math.min(5,en_max), en_max);
    setBar('#fo_cur','#fo_max','#fo_bar', Math.min(2,fo_max), fo_max);

    // TX and Encumbrance
    const resBV  = num($('[data-base="resistance"]').textContent||0);
    const alcBV  = num($('[data-base="alchemy"]').textContent||0);
    const tx_max = resBV + alcBV;
    setBar('#tx_cur','#tx_max','#tx_bar', 0, tx_max);

    const athBV  = num($('[data-base="athletics"]').textContent||0);
    const spiBV  = num($('[data-base="spirit"]').textContent||0);
    const encMax = 10 + (athBV*5) + (spiBV*2);
    setBar('#enc_cur','#enc_max','#enc_bar', 0, encMax);

    // sub limit & tier cap
    const sub_max = (mile_pre*2) + tens(lvl);
    const tierCap = Math.ceil(lvl/25);
    $('#sub_max').textContent  = String(sub_max);
    $('#sub_tier').textContent = String(tierCap);

    // visual warnings
    GROUPS.forEach(g=>{
      const invInp = $(`[data-invest-input="${g.invest}"]`);
      const total  = scoreFromInvest(num(invInp.value||0));
      invInp.style.borderColor = (total>20) ? '#ef4444' : 'rgba(255,255,255,.12)';
      g.skills.forEach(sk=>{
        const sInp = $(`[data-skill="${sk}"]`);
        const val  = num(sInp.value||0);
        sInp.style.borderColor = (val>skill_cap) ? '#ef4444' : 'rgba(255,255,255,.12)';
      });
    });

    // after computing, attempt save (debounced separately)
  }

  function setBar(curSel,maxSel,barSel, cur, max){
    $(maxSel).textContent = String(max);
    $(curSel).textContent = String(Math.min(cur,max));
    $(barSel).style.width = max>0 ? `${Math.round((Math.min(cur,max)/max)*100)}%` : '0%';
  }

  function sumSubType(code){
    return $$('#subTable tbody tr').reduce((acc,tr)=>{
      const typeSel = $('[data-sub-type]', tr);
      const tier = Math.max(0, num($('[data-sub-tier]', tr).value||0));
      return acc + (typeSel?.value===code ? tier : 0);
    }, 0);
  }

  /* ---------- Events ---------- */
  ['#c_level','#c_xp','#c_name','#p_height','#p_weight','#p_bday','#p_backstory','#p_notes']
    .forEach(sel => $(sel)?.addEventListener('input', ()=>{ recompute(); debounceSave(); }));

  GROUPS.forEach(g=>{
    $(`[data-invest-input="${g.invest}"]`)?.addEventListener('input', ()=>{ recompute(); debounceSave(); });
    g.skills.forEach(sk=> $(`[data-skill="${sk}"]`)?.addEventListener('input', ()=>{ recompute(); debounceSave(); }));
  });

  // initial compute
  recompute();

  /* ---------- Saving (safe & silent on errors) ---------- */
  let currentId = null;           // backend can set this later
  let saveTimer = null;

  function debounceSave(){
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveNow, 400);
  }

  function collectState(){
    const lvl = Math.max(1, num($('#c_level')?.value||1));
    const state = {
      name: $('#c_name')?.value || '',
      avatarUrl: $('#avatarUrl')?.value || '',
      level: lvl,
      xp: num($('#c_xp')?.value||0),
      invested: {},
      skills: {},
      sublimations: $$('#subTable tbody tr').map(tr=>{
        return {
          type: $('[data-sub-type]', tr)?.value || '',
          skill: $('[data-sub-skill]', tr)?.value || '',
          tier:  num($('[data-sub-tier]', tr)?.value || 0)
        };
      })
    };
    GROUPS.forEach(g=>{
      state.invested[g.invest] = num($(`[data-invest-input="${g.invest}"]`).value||0);
      g.skills.forEach(sk=>{
        state.skills[sk] = num($(`[data-skill="${sk}"]`).value||0);
      });
    });
    return state;
  }

  async function saveNow(){
    const payload = collectState();
    const url = currentId ? `/api/characters/${encodeURIComponent(currentId)}` : `/api/characters`;
    const method = currentId ? 'PATCH' : 'POST';

    try{
      const res = await fetch(url, {
        method,
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      if(!res.ok) throw new Error(res.statusText || 'Save failed');
      const data = await res.json().catch(()=>null);
      if(data && data.id) currentId = data.id;
    }catch(err){
      // Don’t crash the UI; just log.
      console.warn('Save error:', err?.message || err);
    }
  }
})();