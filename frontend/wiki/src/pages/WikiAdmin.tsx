import React, { useEffect, useState } from "react";
import {
  createCategory,
  createTemplate,
  deleteCategory,
  deleteTemplate,
  fetchCategories,
  fetchTemplates,
  fetchWikiIdentity,
  updateCategory,
  updateTemplate,
  WikiCategory,
  WikiTemplate,
} from "../utils/api";

const WikiAdmin: React.FC = () => {
  const [role, setRole] = useState<string>("");
  const [categories, setCategories] = useState<WikiCategory[]>([]);
  const [templates, setTemplates] = useState<WikiTemplate[]>([]);
  const [catKey, setCatKey] = useState("");
  const [catLabel, setCatLabel] = useState("");
  const [tplKey, setTplKey] = useState("");
  const [tplLabel, setTplLabel] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    fetchCategories().then(setCategories).catch(() => setCategories([]));
    fetchTemplates().then(setTemplates).catch(() => setTemplates([]));
  };

  useEffect(() => {
    fetchWikiIdentity().then((me) => setRole(me.wiki_role)).catch(() => setRole(""));
    reload();
  }, []);

  if (role && role !== "admin") {
    return <p>Admin access required.</p>;
  }

  return (
    <div>
      <h1>Wiki Admin</h1>
      {error && <p style={{ color: "#ff7675" }}>{error}</p>}

      <section style={{ marginBottom: "18px" }}>
        <h2>Categories</h2>
        <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
          <input value={catKey} onChange={(event) => setCatKey(event.target.value)} placeholder="key" />
          <input value={catLabel} onChange={(event) => setCatLabel(event.target.value)} placeholder="label" />
          <button
            onClick={async () => {
              try {
                await createCategory({ key: catKey, label: catLabel });
                setCatKey("");
                setCatLabel("");
                reload();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Category creation failed");
              }
            }}
          >
            Add
          </button>
        </div>
        <ul>
          {categories.map((category) => (
            <li key={category.id}>
              {category.label} ({category.key}){" "}
              <button
                onClick={async () => {
                  const next = window.prompt("New category label", category.label);
                  if (next === null) {
                    return;
                  }
                  try {
                    await updateCategory(category.id, { label: next });
                    reload();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Category update failed");
                  }
                }}
              >
                Rename
              </button>{" "}
              {category.id !== "general" && (
                <button
                  onClick={async () => {
                    try {
                      await deleteCategory(category.id);
                      reload();
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Category delete failed");
                    }
                  }}
                >
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Templates</h2>
        <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
          <input value={tplKey} onChange={(event) => setTplKey(event.target.value)} placeholder="key" />
          <input value={tplLabel} onChange={(event) => setTplLabel(event.target.value)} placeholder="label" />
          <button
            onClick={async () => {
              try {
                await createTemplate({ key: tplKey, label: tplLabel, fields: {} });
                setTplKey("");
                setTplLabel("");
                reload();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Template creation failed");
              }
            }}
          >
            Add
          </button>
        </div>
        <ul>
          {templates.map((template) => (
            <li key={template.id}>
              {template.label} ({template.key}){" "}
              <button
                onClick={async () => {
                  const nextLabel = window.prompt("Template label", template.label);
                  if (nextLabel === null) {
                    return;
                  }
                  const nextFieldsRaw = window.prompt("Template fields JSON", JSON.stringify(template.fields || {}, null, 2));
                  if (nextFieldsRaw === null) {
                    return;
                  }
                  try {
                    const parsed = JSON.parse(nextFieldsRaw);
                    await updateTemplate(template.id, { label: nextLabel, fields: parsed });
                    reload();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Template update failed");
                  }
                }}
              >
                Edit
              </button>{" "}
              <button
                onClick={async () => {
                  try {
                    await deleteTemplate(template.id);
                    reload();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Template delete failed");
                  }
                }}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
};

export default WikiAdmin;
