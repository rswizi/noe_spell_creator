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
