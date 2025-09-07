const API_BASE = import.meta?.env?.VITE_API_BASE || ""; // same-origin by default

export async function listPages({ q, status = "published", limit = 20, page = 1 } = {}) {
  const params = new URLSearchParams({ status, limit, page });
  if (q) params.set("q", q);
  const res = await fetch(`${API_BASE}/api/wiki/pages?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch pages");
  return res.json();
}

export async function getPage(slug) {
  const res = await fetch(`${API_BASE}/api/wiki/pages/${encodeURIComponent(slug)}`);
  if (!res.ok) throw new Error("Page not found");
  return res.json();
}

export async function categoriesTree() {
  const res = await fetch(`${API_BASE}/api/wiki/categories/tree`);
  if (!res.ok) throw new Error("Failed to fetch categories");
  return res.json();
}

export async function popularTags(limit = 50) {
  const res = await fetch(`${API_BASE}/api/wiki/tags?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch tags");
  return res.json();
}