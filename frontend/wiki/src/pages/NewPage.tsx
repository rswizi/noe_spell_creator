import React, { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createPage } from "../utils/api";

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
  const navigate = useNavigate();

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
      const page = await createPage(title, normalizedSlug);
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
        <button type="submit" disabled={saving}>
          {saving ? "Creating..." : "Create and edit"}
        </button>
      </form>
      {error && <p style={{ color: "#ff7675" }}>{error}</p>}
    </div>
  );
};

export default NewPage;
