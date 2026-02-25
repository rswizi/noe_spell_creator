import React, { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createPage, fetchCategories, fetchTemplates, WikiCategory, WikiTemplate } from "../utils/api";

const slugify = (value: string): string =>
  value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");

const NewPage: React.FC = () => {
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [categories, setCategories] = useState<WikiCategory[]>([]);
  const [templates, setTemplates] = useState<WikiTemplate[]>([]);
  const [categoryId, setCategoryId] = useState("general");
  const [entityType, setEntityType] = useState("");
  const [templateId, setTemplateId] = useState("");
  const navigate = useNavigate();

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

  React.useEffect(() => {
    fetchCategories()
      .then((rows) => {
        setCategories(rows);
        if (rows.some((row) => row.id === "general")) {
          setCategoryId("general");
        } else if (rows[0]?.id) {
          setCategoryId(rows[0].id);
        }
      })
      .catch(() => setCategories([]));
    fetchTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, []);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const normalizedSlug = slugify(slug || title);
    if (!normalizedSlug) {
      setError("Please provide a valid title or slug.");
      setSaving(false);
      return;
    }
    try {
      const page = await createPage({
        title,
        slug: normalizedSlug,
        category_id: categoryId || "general",
        entity_type: entityType || undefined,
        template_id: templateId || undefined,
      });
      navigate(`/${page.id}/edit`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create page.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h1>Create Wiki Page</h1>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        <label>
          Title
          <input
            value={title}
            onChange={(event) => {
              const nextTitle = event.target.value;
              setTitle(nextTitle);
              if (!slugTouched) {
                setSlug(slugify(nextTitle));
              }
            }}
            placeholder="My awesome chapter"
            required
          />
        </label>
        <label>
          Slug
          <input
            value={slug}
            onChange={(event) => {
              setSlugTouched(true);
              setSlug(slugify(event.target.value));
            }}
            placeholder="my-awesome-chapter"
          />
        </label>
        <label>
          Category
          <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            {(categories.length
              ? categories
              : [{ id: "general", key: "general", label: "General", slug: "general", sort_order: 0, created_at: "", updated_at: "" }]
            ).map((category) => (
              <option key={category.id} value={category.id}>
                {categoryLabel(category)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Entity Type
          <input value={entityType} onChange={(event) => setEntityType(event.target.value)} placeholder="character, location, item..." />
        </label>
        <label>
          Template
          <select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
            <option value="">None</option>
            {templates.map((tpl) => (
              <option key={tpl.id} value={tpl.id}>
                {tpl.label}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={saving}>
          {saving ? "Creating..." : "Create and edit"}
        </button>
      </form>
      {error && <p style={{ color: "#ff7675" }}>{error}</p>}
    </div>
  );
};

export default NewPage;
