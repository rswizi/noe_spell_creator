const API_BASE = "";

export function getToken() {
  return localStorage.getItem("auth_token") || "";
}

export function authHeaders() {
  const token = getToken();
  if (!token) {
    return {};
  }
  return {
    Authorization: `Bearer ${token}`,
    "X-Auth-Token": token,
  };
}

export async function api(path, options = {}) {
  const headers = {
    ...(options.headers || {}),
    ...authHeaders(),
  };
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
    headers,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { status: "error", message: await response.text() };
  if (!response.ok || payload.status === "error") {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload;
}

export async function fetchMe() {
  return api("/auth/me");
}

export async function fetchCharacters() {
  return api("/characters");
}

export async function createCharacter(name) {
  return api("/characters", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function fetchCharacter(id) {
  return api(`/characters/${encodeURIComponent(id)}`);
}

export async function updateCharacter(id, payload) {
  return api(`/characters/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteCharacter(id) {
  return api(`/characters/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function fetchArchetypes() {
  return api("/archetypes");
}

export async function fetchInventories() {
  return api("/inventories");
}

export async function fetchMySpellLists() {
  return api("/spell_lists/mine");
}

export async function uploadCharacterAvatar(id, file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`/characters/${encodeURIComponent(id)}/avatar`, {
    method: "POST",
    body: form,
    credentials: "include",
    headers: authHeaders(),
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { status: "error", message: await response.text() };
  if (!response.ok || payload.status === "error") {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload;
}

export async function fetchEconomyBootstrap() {
  return api("/economy-0-3-5/bootstrap");
}

export async function fetchEconomyEntities(q = "") {
  const query = q ? `?q=${encodeURIComponent(q)}` : "";
  return api(`/economy-0-3-5/entities${query}`);
}

export async function createEconomyEntity(payload) {
  return api("/economy-0-3-5/entities", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export async function updateEconomyEntity(entityId, payload) {
  return api(`/economy-0-3-5/entities/${encodeURIComponent(entityId)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export async function deleteEconomyEntity(entityId) {
  return api(`/economy-0-3-5/entities/${encodeURIComponent(entityId)}`, {
    method: "DELETE",
  });
}

export async function fetchEconomyServices(q = "") {
  const query = q ? `?q=${encodeURIComponent(q)}` : "";
  return api(`/economy-0-3-5/services${query}`);
}

export async function createEconomyService(payload) {
  return api("/economy-0-3-5/services", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export async function updateEconomyService(serviceId, payload) {
  return api(`/economy-0-3-5/services/${encodeURIComponent(serviceId)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export async function deleteEconomyService(serviceId) {
  return api(`/economy-0-3-5/services/${encodeURIComponent(serviceId)}`, {
    method: "DELETE",
  });
}

export async function fetchEconomyCatalog({ q = "", itemType = "all", limit = 200 } = {}) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (itemType) params.set("item_type", itemType);
  if (limit) params.set("limit", String(limit));
  const query = params.toString();
  return api(`/economy-0-3-5/catalog${query ? `?${query}` : ""}`);
}

export async function upsertEconomyItemMeta(sourceKind, sourceId, payload) {
  return api(`/economy-0-3-5/item-meta/${encodeURIComponent(sourceKind)}/${encodeURIComponent(sourceId)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export async function deleteEconomyItemMeta(sourceKind, sourceId) {
  return api(`/economy-0-3-5/item-meta/${encodeURIComponent(sourceKind)}/${encodeURIComponent(sourceId)}`, {
    method: "DELETE",
  });
}

export async function fetchItemWeapons({ q = "", scope = "all", limit = 300 } = {}) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (scope) params.set("scope", scope);
  if (limit) params.set("limit", String(limit));
  const query = params.toString();
  return api(`/items-0-3-5/weapons${query ? `?${query}` : ""}`);
}

export async function createItemWeapon(payload) {
  return api("/items-0-3-5/weapons", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export async function importItemWeapons(payload) {
  return api("/items-0-3-5/weapons/import", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}
