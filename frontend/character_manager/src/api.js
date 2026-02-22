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
