const baseUrl = import.meta.env.VITE_API_BASE_URL || "";

const defaultHeaders: Record<string, string> = {
  "Content-Type": "application/json",
};

const redirectToLogin = () => {
  if (typeof window !== "undefined") {
    if (window.location.pathname.startsWith("/wiki/login")) {
      return;
    }
    window.location.assign("/wiki/login");
  }
};

async function fetcher(path: string, options: RequestInit = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      ...defaultHeaders,
      ...(options.headers || {}),
    },
    credentials: "include",
  });
  if (response.status === 401) {
    redirectToLogin();
    throw new Error("Unauthorized");
  }
  if (!response.ok) {
    let message = "";
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try {
        const data = await response.json();
        if (data && typeof data.detail === "string") {
          message = data.detail;
        } else if (data && typeof data.message === "string") {
          message = data.message;
        }
      } catch {
        message = "";
      }
    }
    if (!message) {
      message = await response.text();
    }
    throw new Error(message || response.statusText);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

export type PagePayload = {
  id: string;
  title: string;
  slug: string;
  doc_json: any;
  category_id: string;
  entity_type?: string | null;
  template_id?: string | null;
  fields: Record<string, any>;
  summary?: string | null;
  tags: string[];
  status: "draft" | "published" | "archived";
  acl_override?: boolean;
  acl?: { view_roles: string[]; edit_roles: string[] } | null;
  created_at: string;
  updated_at: string;
};

export type PageListResponse = {
  items: PagePayload[];
  total: number;
  limit: number;
  offset: number;
};

export type PageListParams = {
  query?: string;
  category_id?: string;
  entity_type?: string;
  status?: "draft" | "published" | "archived";
  tag?: string;
};

export async function fetchPages(params: PageListParams = {}): Promise<PageListResponse> {
  const query = new URLSearchParams({ limit: "100" });
  if (params.query) query.set("query", params.query);
  if (params.category_id) query.set("category_id", params.category_id);
  if (params.entity_type) query.set("entity_type", params.entity_type);
  if (params.status) query.set("status", params.status);
  if (params.tag) query.set("tag", params.tag);
  return fetcher(`/api/wiki/pages?${query.toString()}`);
}

export type CreatePagePayload = {
  title: string;
  slug?: string;
  category_id?: string;
  entity_type?: string;
  template_id?: string;
  fields?: Record<string, any>;
  summary?: string;
  tags?: string[];
  status?: "draft" | "published" | "archived";
  doc_json?: any;
};

export async function createPage(payload: CreatePagePayload): Promise<PagePayload> {
  return fetcher("/api/wiki/pages", {
    method: "POST",
    body: JSON.stringify({
      title: payload.title,
      slug: payload.slug || "",
      category_id: payload.category_id || "general",
      entity_type: payload.entity_type || null,
      template_id: payload.template_id || null,
      fields: payload.fields || {},
      summary: payload.summary || null,
      tags: payload.tags || [],
      status: payload.status || "draft",
      doc_json: payload.doc_json || { type: "doc", content: [] },
    }),
  });
}

export async function getPage(id: string): Promise<PagePayload> {
  return fetcher(`/api/wiki/pages/${id}`);
}

export async function getPageBySlug(slug: string): Promise<PagePayload> {
  return fetcher(`/api/wiki/pages/slug/${slug}`);
}

export async function updatePage(id: string, payload: Partial<PagePayload>): Promise<PagePayload> {
  return fetcher(`/api/wiki/pages/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function patchPageFields(id: string, fields: Record<string, any>): Promise<PagePayload> {
  return fetcher(`/api/wiki/pages/${id}/fields`, {
    method: "PATCH",
    body: JSON.stringify({ fields }),
  });
}

export async function updatePageAcl(
  id: string,
  payload: { acl_override: boolean; view_roles?: string[]; edit_roles?: string[] }
): Promise<PagePayload> {
  return fetcher(`/api/wiki/pages/${id}/acl`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deletePage(id: string): Promise<{ ok: boolean }> {
  return fetcher(`/api/wiki/pages/${id}`, { method: "DELETE" });
}

export type WikiCategory = {
  id: string;
  key: string;
  label: string;
  slug: string;
  icon?: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export async function fetchCategories(): Promise<WikiCategory[]> {
  return fetcher("/api/wiki/categories");
}

export async function createCategory(payload: {
  key: string;
  label: string;
  slug?: string;
  icon?: string | null;
  sort_order?: number;
}): Promise<WikiCategory> {
  return fetcher("/api/wiki/categories", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateCategory(
  id: string,
  payload: { label?: string; slug?: string; icon?: string | null; sort_order?: number }
): Promise<WikiCategory> {
  return fetcher(`/api/wiki/categories/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteCategory(id: string): Promise<{ ok: boolean }> {
  return fetcher(`/api/wiki/categories/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export type WikiTemplate = {
  id: string;
  key: string;
  label: string;
  description?: string | null;
  fields: Record<string, any>;
  created_at: string;
  updated_at: string;
};

export async function fetchTemplates(): Promise<WikiTemplate[]> {
  return fetcher("/api/wiki/templates");
}

export async function createTemplate(payload: {
  key: string;
  label: string;
  description?: string | null;
  fields?: Record<string, any>;
}): Promise<WikiTemplate> {
  return fetcher("/api/wiki/templates", {
    method: "POST",
    body: JSON.stringify({
      key: payload.key,
      label: payload.label,
      description: payload.description || null,
      fields: payload.fields || {},
    }),
  });
}

export async function updateTemplate(
  id: string,
  payload: { label?: string; description?: string | null; fields?: Record<string, any> }
): Promise<WikiTemplate> {
  return fetcher(`/api/wiki/templates/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteTemplate(id: string): Promise<{ ok: boolean }> {
  return fetcher(`/api/wiki/templates/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export type WikiIdentity = {
  username: string;
  role: string;
  wiki_role: "viewer" | "editor" | "admin";
};

export async function fetchWikiIdentity(): Promise<WikiIdentity> {
  return fetcher("/api/wiki/me");
}

export async function fetchBacklinks(id: string): Promise<any[]> {
  return fetcher(`/api/wiki/pages/${id}/backlinks`);
}

export async function fetchRelations(id: string): Promise<any[]> {
  return fetcher(`/api/wiki/pages/${id}/relations`);
}

export async function fetchPageContext(id: string): Promise<{
  page: PagePayload;
  links: any[];
  backlinks: any[];
  relations: any[];
  revisions: any[];
}> {
  return fetcher(`/api/wiki/pages/${id}/context`);
}

export async function rebuildPageLinks(id: string): Promise<{ ok: boolean; count: number }> {
  return fetcher(`/api/wiki/pages/${id}/links/rebuild`, { method: "POST" });
}

export async function createPageRevision(id: string): Promise<any> {
  return fetcher(`/api/wiki/pages/${id}/revisions`, { method: "POST" });
}

export async function fetchPageRevisions(id: string): Promise<any[]> {
  return fetcher(`/api/wiki/pages/${id}/revisions`);
}

export async function restorePageRevision(id: string, revisionId: string): Promise<PagePayload> {
  return fetcher(`/api/wiki/pages/${id}/revisions/${revisionId}/restore`, { method: "POST" });
}

export type AssetUploadResponse = {
  asset_id: string;
  url: string;
  mime: string;
  size: number;
  width?: number | null;
  height?: number | null;
  filename: string;
};

export async function uploadAsset(file: File): Promise<AssetUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${baseUrl}/api/assets/upload`, {
    method: "POST",
    body: form,
    credentials: "include",
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || response.statusText);
  }
  return response.json();
}
