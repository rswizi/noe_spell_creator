import React, { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createPage } from "../utils/api";

const NewPage: React.FC = () => {
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const page = await createPage(title, slug);
      navigate(`/${page.id}/edit`);
    } catch (err) {
      setError("Unable to create page.");
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
            onChange={(event) => setTitle(event.target.value)}
            placeholder="My awesome chapter"
            required
          />
        </label>
        <label>
          Slug
          <input
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            placeholder="my-awesome-chapter"
            required
          />
        </label>
        <button type="submit" disabled={saving}>
          {saving ? "Creating…" : "Create and edit"}
        </button>
      </form>
      {error && <p style={{ color: "#ff7675" }}>{error}</p>}
    </div>
  );
};

export default NewPage;
