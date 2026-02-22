const baseUrl = import.meta.env.VITE_API_BASE_URL || "";

const defaultHeaders: Record<string, string> = {
  "Content-Type": "application/json",
};

const redirectToLogin = () => {
  if (typeof window !== "undefined") {
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
  created_at: string;
  updated_at: string;
};

export type PageListResponse = {
  items: PagePayload[];
  total: number;
  limit: number;
  offset: number;
};

export async function fetchPages(): Promise<PageListResponse> {
  return fetcher("/api/wiki/pages?limit=100");
}

export async function createPage(title: string, slug?: string): Promise<PagePayload> {
  return fetcher("/api/wiki/pages", {
    method: "POST",
    body: JSON.stringify({
      title,
      slug: slug || "",
      doc_json: { type: "doc", content: [] },
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
