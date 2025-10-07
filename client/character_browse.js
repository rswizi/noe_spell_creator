(() => {
  const $  = (s,el=document)=>el.querySelector(s);
  const $$ = (s,el=document)=>Array.from(el.querySelectorAll(s));

  const grid = $('#grid');
  const empty = $('#empty');
  const q = $('#q');
  const chkAll = $('#chkAll');

  const token = localStorage.getItem('token') || '';
  const role  = localStorage.getItem('role')  || 'user';

  if (role !== 'admin' && role !== 'moderator') {
    chkAll.closest('label').style.display = 'none';
  }

  async function api(path, opts={}) {
    opts.headers = Object.assign({
      'content-type':'application/json',
      'authorization': token ? `Bearer ${token}` : ''
    }, opts.headers||{});
    const res = await fetch(path, opts);
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt || `${res.status}`);
    }
    return res.json();
  }

  function card(c) {
    const div = document.createElement('div');
    div.className = 'card';
    const img = document.createElement('img');
    img.className = 'avatar';
    img.src = c.avatar || 'https://assets.forge-vtt.com/bazaar/core/icons/svg/mystery-man.svg';
    const body = document.createElement('div');
    body.className = 'row';
    const t = document.createElement('div');
    t.className = 'title';
    t.textContent = c.name || 'Unnamed';
    const meta = document.createElement('div');
    meta.className = 'muted';
    meta.textContent = `${c.owner} · ${c.id}`;
    const actions = document.createElement('div');
    actions.className = 'inline';
    const openBtn = document.createElement('button');
    openBtn.className = 'btn';
    openBtn.textContent = 'Open';
    openBtn.onclick = () => {
      // go to editor with id in query
      location.href = `/character.html?id=${encodeURIComponent(c.id)}`;
    };
    const delBtn = document.createElement('button');
    delBtn.className = 'btn ghost';
    delBtn.textContent = 'Delete';
    delBtn.onclick = async () => {
      if (!confirm(`Delete '${c.name}'?`)) return;
      await api(`/characters/${c.id}`, { method:'DELETE' });
      load(); // refresh
    };
    actions.append(openBtn, delBtn);

    body.append(t, meta, actions);
    div.append(img, body);
    return div;
  }

  async function load() {
    let url = '/characters';
    if ((role === 'admin' || role === 'moderator') && chkAll.checked) {
      url = '/admin/characters';
    }
    const data = await api(url);
    const items = (data.items || []).filter(it => {
      const needle = (q.value || '').trim().toLowerCase();
      return !needle || (it.name||'').toLowerCase().includes(needle);
    });
    grid.innerHTML = '';
    items.forEach(it => grid.appendChild(card(it)));
    empty.style.display = items.length ? 'none' : 'block';
  }

  // Create a blank character then navigate to it
  async function createNew() {
    const name = prompt('Character name?', 'New Character');
    if (!name) return;
    const body = {
      name,
      avatar: '',
      payload: {} // we’ll let the editor fill this out
    };
    const res = await api('/characters', { method:'POST', body: JSON.stringify(body) });
    const id = res.id || (res.character && res.character.id);
    location.href = `/character.html?id=${encodeURIComponent(id)}`;
  }

  // Wire UI
  $('#btnNew').addEventListener('click', createNew);
  $('#btnRefresh').addEventListener('click', load);
  q.addEventListener('input', load);
  chkAll.addEventListener('change', load);

  // Initial
  load();
})();