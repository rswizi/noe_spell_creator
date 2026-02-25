import React, { useEffect, useMemo, useState } from "react";
import {
  createCategory,
  createTemplate,
  deleteCategory,
  deleteTemplate,
  fetchCategories,
  fetchTemplates,
  fetchWikiIdentity,
  fetchWikiSettings,
  fetchWikiUsers,
  updateCategory,
  updateTemplate,
  updateWikiSettings,
  updateWikiUserRole,
  WikiCategory,
  WikiTemplate,
  WikiUserRole,
} from "../utils/api";

type BuilderType = "text" | "number" | "boolean" | "json" | "select";

type FieldBuilderRow = {
  id: string;
  key: string;
  label: string;
  type: BuilderType;
  defaultValue: string;
  options: string;
};

const newRow = (): FieldBuilderRow => ({
  id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  key: "",
  label: "",
  type: "text",
  defaultValue: "",
  options: "",
});

const parseValueByType = (raw: string, type: BuilderType): any => {
  if (type === "number") {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  if (type === "boolean") {
    return String(raw).trim().toLowerCase() === "true";
  }
  if (type === "json") {
    if (!String(raw).trim()) {
      return {};
    }
    try {
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }
  return raw;
};

const fieldsFromRows = (rows: FieldBuilderRow[]): Record<string, any> => {
  const out: Record<string, any> = {};
  rows.forEach((row) => {
    const key = row.key.trim();
    if (!key) {
      return;
    }
    const item: Record<string, any> = {
      type: row.type,
      default: parseValueByType(row.defaultValue, row.type),
    };
    if (row.label.trim()) {
      item.label = row.label.trim();
    }
    if (row.type === "select") {
      item.options = row.options
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
    }
    out[key] = item;
  });
  return out;
};

const rowsFromFields = (fields: Record<string, any>): FieldBuilderRow[] => {
  const rows: FieldBuilderRow[] = [];
  Object.entries(fields || {}).forEach(([key, value]) => {
    const defaultType: BuilderType =
      typeof value === "number" ? "number" : typeof value === "boolean" ? "boolean" : value && typeof value === "object" ? "json" : "text";
    const isDefinition =
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      ["text", "number", "boolean", "json", "select"].includes(String((value as Record<string, any>).type || ""));
    const type = isDefinition ? (String((value as Record<string, any>).type) as BuilderType) : defaultType;
    const defaultValue = isDefinition ? (value as Record<string, any>).default : value;
    rows.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      key,
      label: isDefinition ? String((value as Record<string, any>).label || "") : "",
      type,
      defaultValue: typeof defaultValue === "string" ? defaultValue : JSON.stringify(defaultValue ?? "", null, 2),
      options: isDefinition && Array.isArray((value as Record<string, any>).options) ? (value as Record<string, any>).options.join(", ") : "",
    });
  });
  return rows.length ? rows : [newRow()];
};

const WikiAdmin: React.FC = () => {
  const [role, setRole] = useState<string>("");
  const [roleLoading, setRoleLoading] = useState(true);
  const [categories, setCategories] = useState<WikiCategory[]>([]);
  const [templates, setTemplates] = useState<WikiTemplate[]>([]);
  const [wikiUsers, setWikiUsers] = useState<WikiUserRole[]>([]);
  const [editorAccessMode, setEditorAccessMode] = useState<"all" | "own">("all");
  const [catKey, setCatKey] = useState("");
  const [catLabel, setCatLabel] = useState("");
  const [catParentId, setCatParentId] = useState("");
  const [tplId, setTplId] = useState("");
  const [tplKey, setTplKey] = useState("");
  const [tplLabel, setTplLabel] = useState("");
  const [tplDescription, setTplDescription] = useState("");
  const [builderRows, setBuilderRows] = useState<FieldBuilderRow[]>([newRow()]);
  const [tplJsonText, setTplJsonText] = useState("{}");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const categoryById = useMemo(() => {
    const map: Record<string, WikiCategory> = {};
    categories.forEach((row) => {
      map[row.id] = row;
    });
    return map;
  }, [categories]);

  const resetTemplateForm = () => {
    setTplId("");
    setTplKey("");
    setTplLabel("");
    setTplDescription("");
    setBuilderRows([newRow()]);
    setTplJsonText("{}");
  };

  const loadTemplate = (template: WikiTemplate) => {
    setTplId(template.id);
    setTplKey(template.key);
    setTplLabel(template.label);
    setTplDescription(template.description || "");
    const rows = rowsFromFields(template.fields || {});
    setBuilderRows(rows);
    setTplJsonText(JSON.stringify(template.fields || {}, null, 2));
  };

  const generateJsonFromBuilder = () => {
    setTplJsonText(JSON.stringify(fieldsFromRows(builderRows), null, 2));
  };

  const loadBuilderFromJson = () => {
    try {
      const parsed = JSON.parse(tplJsonText || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Template JSON must be an object.");
      }
      setBuilderRows(rowsFromFields(parsed));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid template JSON");
    }
  };

  const reload = () => {
    fetchCategories().then(setCategories).catch(() => setCategories([]));
    fetchTemplates().then(setTemplates).catch(() => setTemplates([]));
    fetchWikiUsers().then(setWikiUsers).catch(() => setWikiUsers([]));
    fetchWikiSettings()
      .then((settings) => setEditorAccessMode(settings.editor_access_mode || "all"))
      .catch(() => setEditorAccessMode("all"));
  };

  useEffect(() => {
    fetchWikiIdentity()
      .then((me) => setRole(me.wiki_role))
      .catch(() => setRole(""))
      .finally(() => setRoleLoading(false));
    reload();
  }, []);

  if (roleLoading) {
    return <p>Loading...</p>;
  }

  if (role !== "admin") {
    return <p>Admin access required.</p>;
  }

  return (
    <div>
      <h1>Wiki Admin</h1>
      {error && <p style={{ color: "#ff7675" }}>{error}</p>}

      <section style={{ marginBottom: "18px" }}>
        <h2>Website Options</h2>
        <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px" }}>
          <label>Editor permissions</label>
          <select value={editorAccessMode} onChange={(event) => setEditorAccessMode(event.target.value as "all" | "own")}>
            <option value="all">Editors can edit any page</option>
            <option value="own">Editors can edit only their own or assigned pages</option>
          </select>
          <button
            onClick={async () => {
              try {
                setSaving("settings");
                setError(null);
                const updated = await updateWikiSettings({ editor_access_mode: editorAccessMode });
                setEditorAccessMode(updated.editor_access_mode);
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to save settings");
              } finally {
                setSaving(null);
              }
            }}
          >
            {saving === "settings" ? "Saving..." : "Save"}
          </button>
        </div>
      </section>

      <section style={{ marginBottom: "18px" }}>
        <h2>Wiki User Roles</h2>
        <table className="page-table">
          <thead>
            <tr>
              <th>User</th>
              <th>App Role</th>
              <th>Wiki Role</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {wikiUsers.map((user) => (
              <tr key={user.username}>
                <td>{user.username}</td>
                <td>{user.role}</td>
                <td>
                  <select
                    value={user.wiki_role}
                    onChange={(event) => {
                      const nextRole = event.target.value as "viewer" | "editor" | "admin";
                      setWikiUsers((rows) => rows.map((row) => (row.username === user.username ? { ...row, wiki_role: nextRole } : row)));
                    }}
                  >
                    <option value="viewer">viewer</option>
                    <option value="editor">editor</option>
                    <option value="admin">admin</option>
                  </select>
                </td>
                <td>
                  <button
                    onClick={async () => {
                      try {
                        setSaving(`user-${user.username}`);
                        setError(null);
                        const row = wikiUsers.find((item) => item.username === user.username);
                        if (!row) {
                          return;
                        }
                        await updateWikiUserRole(user.username, row.wiki_role);
                        reload();
                      } catch (err) {
                        setError(err instanceof Error ? err.message : "Role update failed");
                      } finally {
                        setSaving(null);
                      }
                    }}
                  >
                    {saving === `user-${user.username}` ? "Saving..." : "Save"}
                  </button>
                </td>
              </tr>
            ))}
            {!wikiUsers.length && (
              <tr>
                <td colSpan={4}>No users found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section style={{ marginBottom: "18px" }}>
        <h2>Categories / Subcategories</h2>
        <div style={{ display: "flex", gap: "8px", marginBottom: "8px", flexWrap: "wrap" }}>
          <input value={catKey} onChange={(event) => setCatKey(event.target.value)} placeholder="key" />
          <input value={catLabel} onChange={(event) => setCatLabel(event.target.value)} placeholder="label" />
          <select value={catParentId} onChange={(event) => setCatParentId(event.target.value)}>
            <option value="">No parent (top level)</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.label}
              </option>
            ))}
          </select>
          <button
            onClick={async () => {
              try {
                await createCategory({ key: catKey, label: catLabel, parent_id: catParentId || null });
                setCatKey("");
                setCatLabel("");
                setCatParentId("");
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
          {categories.map((category) => {
            const parentLabel = category.parent_id ? categoryById[category.parent_id]?.label || category.parent_id : "Top level";
            return (
              <li key={category.id}>
                {category.label} ({category.key}) - Parent: {parentLabel}{" "}
                <button
                  onClick={async () => {
                    const nextLabel = window.prompt("New category label", category.label);
                    if (nextLabel === null) {
                      return;
                    }
                    const nextParent = window.prompt("Parent category id (blank for top level)", category.parent_id || "");
                    if (nextParent === null) {
                      return;
                    }
                    try {
                      await updateCategory(category.id, { label: nextLabel, parent_id: nextParent.trim() || null });
                      reload();
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Category update failed");
                    }
                  }}
                >
                  Edit
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
            );
          })}
        </ul>
      </section>

      <section>
        <h2>Templates</h2>
        <div style={{ marginBottom: "10px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <input value={tplKey} onChange={(event) => setTplKey(event.target.value)} placeholder="key" disabled={Boolean(tplId)} />
          <input value={tplLabel} onChange={(event) => setTplLabel(event.target.value)} placeholder="label" />
          <input value={tplDescription} onChange={(event) => setTplDescription(event.target.value)} placeholder="description" />
          <button
            onClick={() => {
              generateJsonFromBuilder();
            }}
          >
            Build JSON
          </button>
          <button onClick={loadBuilderFromJson}>Load Builder From JSON</button>
          <button onClick={resetTemplateForm}>Clear Form</button>
        </div>

        <div style={{ marginBottom: "8px" }}>
          <h3 style={{ marginBottom: "6px" }}>Field Builder</h3>
          {builderRows.map((row) => (
            <div key={row.id} style={{ display: "flex", gap: "8px", marginBottom: "6px", flexWrap: "wrap" }}>
              <input
                value={row.key}
                onChange={(event) =>
                  setBuilderRows((items) => items.map((item) => (item.id === row.id ? { ...item, key: event.target.value } : item)))
                }
                placeholder="field key"
              />
              <input
                value={row.label}
                onChange={(event) =>
                  setBuilderRows((items) => items.map((item) => (item.id === row.id ? { ...item, label: event.target.value } : item)))
                }
                placeholder="field label"
              />
              <select
                value={row.type}
                onChange={(event) =>
                  setBuilderRows((items) =>
                    items.map((item) => (item.id === row.id ? { ...item, type: event.target.value as BuilderType } : item))
                  )
                }
              >
                <option value="text">text</option>
                <option value="number">number</option>
                <option value="boolean">boolean</option>
                <option value="json">json</option>
                <option value="select">select</option>
              </select>
              <input
                value={row.defaultValue}
                onChange={(event) =>
                  setBuilderRows((items) => items.map((item) => (item.id === row.id ? { ...item, defaultValue: event.target.value } : item)))
                }
                placeholder="default value"
              />
              {row.type === "select" && (
                <input
                  value={row.options}
                  onChange={(event) =>
                    setBuilderRows((items) => items.map((item) => (item.id === row.id ? { ...item, options: event.target.value } : item)))
                  }
                  placeholder="option1, option2"
                />
              )}
              <button onClick={() => setBuilderRows((items) => items.filter((item) => item.id !== row.id))}>Remove</button>
            </div>
          ))}
          <button onClick={() => setBuilderRows((items) => [...items, newRow()])}>Add Field</button>
        </div>

        <label style={{ display: "block", marginBottom: "6px" }}>Template JSON</label>
        <textarea
          value={tplJsonText}
          onChange={(event) => setTplJsonText(event.target.value)}
          rows={10}
          style={{ width: "100%", fontFamily: "monospace", marginBottom: "8px" }}
        />

        <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
          <button
            onClick={async () => {
              try {
                const parsed = JSON.parse(tplJsonText || "{}");
                if (tplId) {
                  await updateTemplate(tplId, { label: tplLabel, description: tplDescription || null, fields: parsed });
                } else {
                  await createTemplate({ key: tplKey, label: tplLabel, description: tplDescription || null, fields: parsed });
                }
                resetTemplateForm();
                reload();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Template save failed");
              }
            }}
          >
            {tplId ? "Update Template" : "Create Template"}
          </button>
        </div>

        <ul>
          {templates.map((template) => (
            <li key={template.id}>
              {template.label} ({template.key}){" "}
              <button onClick={() => loadTemplate(template)}>Load in editor</button>{" "}
              <button
                onClick={async () => {
                  try {
                    await deleteTemplate(template.id);
                    if (tplId === template.id) {
                      resetTemplateForm();
                    }
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
