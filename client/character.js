(() => {
  const $  = (s,e=document)=>e.querySelector(s);
  const $$ = (s,e=document)=>Array.from(e.querySelectorAll(s));
  const num = v => (v===''||v==null) ? 0 : Number(v);

  // ---------------- Tabs ----------------
  $$('.tab').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      $$('.tab').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      const key = btn.dataset.tab;
      $$('.tabpan').forEach(p=>p.classList.remove('active'));
      $(`#tab-${key}`).classList.add('active');
    });
  });

  // ---------------- Avatar ----------------
  const avatarUrl = $('#avatarUrl');
  const charAvatar = $('#charAvatar');
  avatarUrl.addEventListener('input', ()=>{
    charAvatar.src = avatarUrl.value || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
  });

  // ---------------- Static map (HTML is hard-coded) ----------------
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
  const INTENSITIES = ['Fire','Water','Earth','Wind','Lightning','Moon','Sun','Ki'];

  // ---------------- Sublimations ----------------
  const subBody = $('#subTable tbody');
  $('#btnAddSub').addEventListener('click', ()=> {
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
          <option value="technicity">Technicity</option>
          <option value="dodge">Dodge</option>
          <option value="tempo">Tempo</option>
          <option value="reactivity">Reactivity</option>
          <option value="accuracy">Accuracy</option>
          <option value="evasion">Evasion</option>
          <option value="stealth">Stealth</option>
          <option value="acrobatics">Acrobatics</option>
          <option value="brutality">Brutality</option>
          <option value="blocking">Blocking</option>
          <option value="resistance">Resistance</option>
          <option value="athletics">Athletics</option>
          <option value="intimidation">Intimidation</option>
          <option value="spirit">Spirit</option>
          <option value="instinct">Instinct</option>
          <option value="absorption">Absorption</option>
          <option value="aura">Aura</option>
          <option value="incantation">Incantation</option>
          <option value="enchantment">Enchantment</option>
          <option value="restoration">Restoration</option>
          <option value="potential">Potential</option>
          <option value="taming">Taming</option>
          <option value="charm">Charm</option>
          <option value="charisma">Charisma</option>
          <option value="deception">Deception</option>
          <option value="persuasion">Persuasion</option>
          <option value="survival">Survival</option>
          <option value="education">Education</option>
          <option value="perception">Perception</option>
          <option value="psychology">Psychology</option>
          <option value="investigation">Investigation</option>
          <option value="crafting">Crafting</option>
          <option value="soh">Sleight of hand</option>
          <option value="alchemy">Alchemy</option>
          <option value="medecine">Medicine</option>
          <option value="engineering">Engineering</option>
        </select>
      </td>
      <td><input class="input xs" type="number" min="0" max="4" value="1" data-sub-tier></td>
      <td class="right mono" data-sub-slots>1</td>
      <td><button class="btn ghost" data-sub-remove>Remove</button></td>
    `;
    subBody.appendChild(tr);
    wireSubRow(tr);
    recompute();
  });

  function wireSubRow(tr){
    const typeSel = $('[data-sub-type]', tr);
    const skillSel = $('[data-sub-skill]', tr);
    const tierInp = $('[data-sub-tier]', tr);
    const slotsCell = $('[data-sub-slots]', tr);
    const delBtn = $('[data-sub-remove]', tr);

    const toggle = ()=> {
      const isEx = typeSel.value === '1';
      skillSel.disabled = !isEx;
      skillSel.style.opacity = isEx ? '1' : '.5';
    };
    toggle();

    typeSel.addEventListener('change', ()=>{ toggle(); recompute(); });
    skillSel.addEventListener('change', ()=> recompute());
    tierInp.addEventListener('input', ()=> { slotsCell.textContent = String(num(tierInp.value)); recompute(); });
    delBtn.addEventListener('click', ()=> { tr.remove(); recompute(); });
  }
  // wire initial row
  wireSubRow(subBody.querySelector('tr'));

  // ---------------- Math helpers ----------------
  const scoreFromInvest = invest => 4 + invest;
  const milestoneFromScore = score => Math.floor(score/2 - 5); // "Milestone" (positive milestones are >=0)
  const idIvFromBV = (bv)=>{
    if (bv <= 0) return ['—','—'];
    if (bv <= 7)  return ['1d4', 2];
    if (bv <= 11) return ['1d6', 3];
    if (bv <= 15) return ['1d8', 4];
    if (bv <= 17) return ['1d10', 5];
    return ['1d12', 6];
  };

  // ---------------- Recompute ----------------
  function recompute(){
    const lvl = Math.max(1, num($('#c_level').value||1));

    // char milestones
    const charMil = {};
    GROUPS.forEach(g=>{
      const inv = num($(`[data-invest-input="${g.invest}"]`).value || 0);
      const score = scoreFromInvest(inv);
      const ms = milestoneFromScore(score);
      charMil[g.key] = ms;
      $(`[data-total="${g.key}"]`).textContent = String(score);
      $(`[data-milestone="${g.key}"]`).textContent = String(ms);
    });

    // sublimation slots & Excellence map
    let subUsed = 0;
    const exMap = {};
    $$('#subTable tbody tr').forEach(tr=>{
      const typeSel = $('[data-sub-type]', tr);
      const skillSel = $('[data-sub-skill]', tr);
      const tier = Math.max(0, num($('[data-sub-tier]', tr).value||0));
      subUsed += tier;
      if(typeSel.value === '1' && skillSel.value){
        exMap[skillSel.value] = (exMap[skillSel.value]||0) + tier;
      }
    });
    $('#sub_used').textContent = String(subUsed);

    // skills base: invested + min(excellence, invested) + char milestone
    GROUPS.forEach(g=>{
      g.skills.forEach(sk=>{
        const inv = num($(`[data-skill="${sk}"]`)?.value || 0);
        const ex  = Math.min(inv, exMap[sk] || 0);
        const base = inv + ex + (charMil[g.key]||0);
        $(`[data-base="${sk}"]`).textContent = String(base);
      });
    });

    // counters (front-end guidance)
    const skill_cap = (lvl >= 50 ? 8 : lvl >= 40 ? 7 : lvl >= 30 ? 6 : lvl >= 20 ? 5 : lvl >= 10 ? 4 : 3);
    const cp_max = 22 + Math.floor((lvl-1)/9)*3;
    const sp_max = 40 + (lvl-1)*2;
    const cp_used = GROUPS.reduce((a,g)=> a + num($(`[data-invest-input="${g.invest}"]`).value||0), 0);
    const sp_used = GROUPS.reduce((a,g)=> a + g.skills.reduce((aa,s)=> aa + num($(`[data-skill="${s}"]`).value||0), 0), 0);
    $('#skill_cap').textContent = String(skill_cap);
    $('#char_cap').textContent = '10';
    $('#cp_max').textContent = String(cp_max);
    $('#sp_max').textContent = String(sp_max);
    $('#cp_used').textContent = String(cp_used);
    $('#sp_used').textContent = String(sp_used);

    // badges
    const mile_ref = Math.max(charMil.ref||0,0);
    const mile_dex = Math.max(charMil.dex||0,0);
    const mile_mag = Math.max(charMil.mag||0,0);
    const mo = 4 + mile_ref + mile_dex + sumSubType('5');
    $('#k_mo').textContent = String(mo);
    $('#k_init').textContent = String(mo + Math.max(charMil.ref||0,0));
    $('#k_et').textContent = String(1 + Math.floor((lvl-1)/9) + mile_mag);
    $('#k_cdc').textContent = String(6 + Math.floor(lvl/10) + sumSubType('7'));

    // intensities
    const magic_mod = charMil.mag||0;
    INTENSITIES.forEach(nm=>{
      const inv = num($(`[data-i-invest="${nm}"]`).value || 0);
      const base = inv>0 ? inv + magic_mod : 0;
      const [ID, IV] = idIvFromBV(base);
      $(`[data-i-mod="${nm}"]`).textContent = String(magic_mod);
      $(`[data-i-base="${nm}"]`).textContent = String(base);
      $(`[data-i-id="${nm}"]`).textContent = String(ID);
      $(`[data-i-iv="${nm}"]`).textContent = String(IV||'—');
      $(`[data-i-rw="${nm}"]`).textContent = '0';
    });

    // resources bars (keep coherent widths)
    function setBar(curSel,maxSel,barSel){
      const cur = num($(curSel).textContent||0);
      const max = num($(maxSel).textContent||0);
      $(barSel).style.width = max>0 ? `${Math.round((cur/max)*100)}%` : '0%';
    }
    setBar('#hp_cur','#hp_max','#hp_bar');
    setBar('#sp_cur','#sp_max','#sp_bar');
    setBar('#en_cur','#en_max','#en_bar');
    setBar('#fo_cur','#fo_max','#fo_bar');
    setBar('#tx_cur','#tx_max','#tx_bar');
    setBar('#enc_cur','#enc_max','#enc_bar');
  }

  function sumSubType(code){
    return $$('#subTable tbody tr').reduce((acc,tr)=>{
      const typeSel = $('[data-sub-type]', tr);
      const tier = Math.max(0, num($('[data-sub-tier]', tr).value||0));
      return acc + (typeSel.value===code ? tier : 0);
    }, 0);
  }

  // events (inputs)
  ['#c_level','#c_xp','#c_name','#avatarUrl','#p_height','#p_weight','#p_bday','#p_backstory','#p_notes']
    .forEach(sel=> $(sel)?.addEventListener('input', recompute));

  $$('#subTable').forEach(t=> t.addEventListener('input',recompute));
  $$('#subTable').forEach(t=> t.addEventListener('change',recompute));

  GROUPS.forEach(g=>{
    $(`[data-invest-input="${g.invest}"]`).addEventListener('input', recompute);
    g.skills.forEach(sk=> $(`[data-skill="${sk}"]`).addEventListener('input', recompute));
  });

  INTENSITIES.forEach(nm=> $(`[data-i-invest="${nm}"]`).addEventListener('input',recompute));

  // initial compute
  recompute();
})();