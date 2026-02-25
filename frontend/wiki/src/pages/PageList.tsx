import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCategories, fetchPages, fetchWikiIdentity, WikiCategory } from "../utils/api";

type PageSummary = {
  id: string;
  title: string;
  slug: string;
  category_id: string;
  entity_type?: string | null;
  status: "draft" | "published" | "archived";
  updated_at: string;
};

const PageList: React.FC = () => {
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [categories, setCategories] = useState<WikiCategory[]>([]);
  const [identity, setIdentity] = useState<{ wiki_role: "viewer" | "editor" | "admin" } | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [entityTypeFilter, setEntityTypeFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const canEdit = identity?.wiki_role === "editor" || identity?.wiki_role === "admin";
  const isAdmin = identity?.wiki_role === "admin";

  const categoryLabel = (category: WikiCategory): string => {
    const seen = new Set<string>();
    let cursor: WikiCategory | undefined = category;
    const parts: string[] = [];
    while (cursor && !seen.has(cursor.id)) {
      seen.add(cursor.id);
      parts.unshift(cursor.label);
      cursor = categories.find((item) => item.id === cursor?.parent_id);
    }
    return parts.join(" / ");
  };

  useEffect(() => {
    let active = true;
    fetchPages({
      ...(categoryFilter ? { category_id: categoryFilter } : {}),
      ...(entityTypeFilter ? { entity_type: entityTypeFilter } : {}),
    })
      .then((payload) => {
        if (!active) {
          return;
        }
        setPages(payload.items);
        setError(null);
      })
      .catch((err) => {
        if (!active) {
          return;
        }
        setPages([]);
        setError(err instanceof Error ? err.message : "Failed to load pages");
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [categoryFilter, entityTypeFilter]);

  useEffect(() => {
    fetchCategories().then(setCategories).catch(() => setCategories([]));
    fetchWikiIdentity().then(setIdentity).catch(() => setIdentity(null));
  }, []);

  return (
    <div>
      <header>
        <h1>Wiki Pages</h1>
        <p>Autosaved TipTap docs powered by the new wiki API.</p>
        {canEdit && (
          <Link to="/new">
            <button>Create Page</button>
          </Link>
        )}
        {isAdmin && (
          <Link to="/admin" style={{ marginLeft: "8px" }}>
            <button>Wiki Admin</button>
          </Link>
        )}
        <div style={{ marginTop: "10px" }}>
          <label style={{ display: "inline-flex", gap: "8px", alignItems: "center" }}>
            Category
            <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
              <option value="">All</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {categoryLabel(category)}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "inline-flex", gap: "8px", alignItems: "center", marginLeft: "12px" }}>
            Entity Type
            <input value={entityTypeFilter} onChange={(event) => setEntityTypeFilter(event.target.value)} placeholder="character..." />
          </label>
        </div>
      </header>

      {loading ? (
        <p>Loading...</p>
      ) : error ? (
        <p style={{ color: "#ff7675" }}>{error}</p>
      ) : (
        <table className="page-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Slug</th>
              <th>Type</th>
              <th>Status</th>
              <th>Updated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pages.map((page) => (
              <tr key={page.id}>
                <td>{page.title}</td>
                <td>{page.slug}</td>
                <td>{page.entity_type || "-"}</td>
                <td>{page.status}</td>
                <td>{new Date(page.updated_at).toLocaleString()}</td>
                <td style={{ display: "flex", gap: "8px" }}>
                  <Link className="card-link" to={`/${page.id}`}>
                    View
                  </Link>
                  {canEdit && (
                    <Link className="card-link" to={`/${page.id}/edit`}>
                      Edit
                    </Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

export default PageList;
