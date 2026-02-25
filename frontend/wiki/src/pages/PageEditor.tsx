import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Editor, EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import HeadingAnchors from "../extensions/HeadingAnchors";
import TableOfContents from "../extensions/TableOfContents";
import ExtendedLink from "../extensions/ExtendedLink";
import ExtendedImage from "../extensions/ExtendedImage";
import TablePicker from "../components/TablePicker";
import {
  createPageRevision,
  deletePage,
  fetchCategories,
  fetchPageRevisions,
  fetchTemplates,
  fetchWikiIdentity,
  getPage,
  rebuildPageLinks,
  restorePageRevision,
  PagePayload,
  updatePage,
  updatePageAcl,
  uploadAsset,
  WikiCategory,
  WikiTemplate,
} from "../utils/api";

const toolbarActions = [
  { label: "H1", action: (editor: Editor) => editor.chain().focus().toggleHeading({ level: 1 }).run() },
  { label: "H2", action: (editor: Editor) => editor.chain().focus().toggleHeading({ level: 2 }).run() },
  { label: "H3", action: (editor: Editor) => editor.chain().focus().toggleHeading({ level: 3 }).run() },
  { label: "B", action: (editor: Editor) => editor.chain().focus().toggleBold().run() },
  { label: "I", action: (editor: Editor) => editor.chain().focus().toggleItalic().run() },
  { label: "U", action: (editor: Editor) => editor.chain().focus().toggleUnderline().run() },
  { label: "S", action: (editor: Editor) => editor.chain().focus().toggleStrike().run() },
  { label: "• List", action: (editor: Editor) => editor.chain().focus().toggleBulletList().run() },
  { label: "1. List", action: (editor: Editor) => editor.chain().focus().toggleOrderedList().run() },
  { label: "Checklist", action: (editor: Editor) => editor.chain().focus().toggleTaskList().run() },
  { label: "Quote", action: (editor: Editor) => editor.chain().focus().toggleBlockquote().run() },
  { label: "</>", action: (editor: Editor) => editor.chain().focus().toggleCodeBlock().run() },
  { label: "Link", action: (editor: Editor) => editor.chain().focus().extendMarkRange("link").setLink({ href: prompt("Enter link URL") || "" }).run() },
  { label: "Undo", action: (editor: Editor) => editor.chain().focus().undo().run() },
  { label: "Redo", action: (editor: Editor) => editor.chain().focus().redo().run() },
  { label: "TOC", action: (editor: Editor) => editor.chain().focus().insertTableOfContents().run() },
];


const PageEditor: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [page, setPage] = useState<PagePayload | null>(null);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [categoryId, setCategoryId] = useState("general");
  const [entityType, setEntityType] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [pageStatus, setPageStatus] = useState<"draft" | "published" | "archived">("draft");
  const [summary, setSummary] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [categories, setCategories] = useState<WikiCategory[]>([]);
  const [templates, setTemplates] = useState<WikiTemplate[]>([]);
  const [fieldsText, setFieldsText] = useState("{}");
  const [identity, setIdentity] = useState<{ wiki_role: "viewer" | "editor" | "admin" } | null>(null);
  const [aclOverride, setAclOverride] = useState(false);
  const [aclViewRoles, setAclViewRoles] = useState("viewer,editor,admin");
  const [aclEditRoles, setAclEditRoles] = useState("editor,admin");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [revisions, setRevisions] = useState<any[]>([]);

  const editor = useEditor({
    extensions: [
      HeadingAnchors,
      TableOfContents,
      StarterKit,
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      ExtendedImage,
      Underline,
      ExtendedLink.configure({ openOnClick: false }),
      TaskList,
      TaskItem,
    ],
    editable: true,
    content: "",
  });

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const docRef = useRef<string>("");
  const metaRef = useRef({
    title: "",
    slug: "",
    category_id: "general",
    entity_type: "",
    template_id: "",
    status: "draft" as "draft" | "published" | "archived",
    summary: "",
    tags_text: "",
    fields_text: "{}",
  });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const parseFieldsJson = useCallback((): Record<string, any> | null => {
    const raw = (fieldsText || "").trim() || "{}";
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setFieldError("Fields JSON must be an object.");
        return null;
      }
      setFieldError(null);
      return parsed;
    } catch {
      setFieldError("Invalid JSON in fields.");
      return null;
    }
  }, [fieldsText]);

  const handleImageFile = useCallback(
    async (file: File) => {
      if (!editor) {
        return;
      }
      try {
        setImageError(null);
        const asset = await uploadAsset(file);
        editor
          .chain()
          .focus()
          .setImage({
            src: asset.url,
            assetId: asset.asset_id,
            width: asset.width || undefined,
            height: asset.height || undefined,
            caption: "",
            alignment: "center",
            alt: file.name,
          })
          .run();
      } catch (err) {
        console.error("Image upload failed", err);
        setImageError(err instanceof Error ? err.message : "Upload failed");
      }
    },
    [editor]
  );

  const autoSave = useCallback(
    async (force: boolean = false) => {
      if (!editor || !page) {
        return;
      }
      const doc = editor.getJSON();
      const newHash = JSON.stringify(doc);
      const metaChanged =
        title !== metaRef.current.title ||
        slug !== metaRef.current.slug ||
        categoryId !== metaRef.current.category_id ||
        entityType !== metaRef.current.entity_type ||
        templateId !== metaRef.current.template_id ||
        pageStatus !== metaRef.current.status ||
        summary !== metaRef.current.summary ||
        tagsText !== metaRef.current.tags_text ||
        fieldsText !== metaRef.current.fields_text;
      if (!force && newHash === docRef.current && !metaChanged) {
        return;
      }
      const fields = parseFieldsJson();
      if (fields === null) {
        setStatus("error");
        return;
      }
      setStatus("saving");
      try {
        const updated = await updatePage(page.id, {
          doc_json: doc,
          title,
          slug,
          category_id: categoryId,
          entity_type: entityType || undefined,
          template_id: templateId || undefined,
          fields,
          status: pageStatus,
          summary,
          tags: tagsText
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
        });
        docRef.current = JSON.stringify(editor.getJSON());
        metaRef.current = {
          title: updated.title,
          slug: updated.slug,
          category_id: updated.category_id || "general",
          entity_type: updated.entity_type || "",
          template_id: updated.template_id || "",
          status: updated.status || "draft",
          summary: updated.summary || "",
          tags_text: (updated.tags || []).join(", "),
          fields_text: JSON.stringify(updated.fields || {}, null, 2),
        };
        setStatus("saved");
      } catch (err) {
        setStatus("error");
      }
    },
    [categoryId, editor, entityType, fieldsText, page, pageStatus, parseFieldsJson, slug, summary, tagsText, templateId, title]
  );

  useEffect(() => {
    fetchCategories().then(setCategories).catch(() => setCategories([]));
    fetchTemplates().then(setTemplates).catch(() => setTemplates([]));
    fetchWikiIdentity().then(setIdentity).catch(() => setIdentity(null));
  }, []);

  const reloadRevisions = useCallback(
    (pageId: string) => {
      fetchPageRevisions(pageId).then(setRevisions).catch(() => setRevisions([]));
    },
    []
  );

  useEffect(() => {
    if (!id) {
      return;
    }
    getPage(id)
      .then((data) => {
        setPage(data);
        setTitle(data.title);
        setSlug(data.slug);
        setCategoryId(data.category_id || "general");
        setEntityType(data.entity_type || "");
        setTemplateId(data.template_id || "");
        setPageStatus(data.status || "draft");
        setSummary(data.summary || "");
        setTagsText((data.tags || []).join(", "));
        setFieldsText(JSON.stringify(data.fields || {}, null, 2));
        setAclOverride(Boolean(data.acl_override));
        setAclViewRoles((data.acl?.view_roles || ["viewer", "editor", "admin"]).join(","));
        setAclEditRoles((data.acl?.edit_roles || ["editor", "admin"]).join(","));
        editor?.commands.setContent(data.doc_json || { type: "doc", content: [] });
        docRef.current = JSON.stringify(data.doc_json);
        metaRef.current = {
          title: data.title,
          slug: data.slug,
          category_id: data.category_id || "general",
          entity_type: data.entity_type || "",
          template_id: data.template_id || "",
          status: data.status || "draft",
          summary: data.summary || "",
          tags_text: (data.tags || []).join(", "),
          fields_text: JSON.stringify(data.fields || {}, null, 2),
        };
        reloadRevisions(data.id);
      })
      .catch(() => {
        navigate("/");
      });
  }, [id, editor, navigate, reloadRevisions]);

  useEffect(() => {
    if (!editor) {
      return;
    }
    const handler = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => autoSave(), 1200);
    };
    editor.on("update", handler);
    return () => {
      editor.off("update", handler);
      timerRef.current && clearTimeout(timerRef.current);
    };
  }, [editor, autoSave]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        autoSave(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [autoSave]);

  useEffect(() => {
    if (!editor) {
      return;
    }
    const dom = editor.view.dom as HTMLElement;
    const onDrop = (event: DragEvent) => {
      const file = event.dataTransfer?.files?.[0];
      if (file && file.type.startsWith("image/")) {
        event.preventDefault();
        void handleImageFile(file);
      }
    };
    const onPaste = (event: ClipboardEvent) => {
      const items = event.clipboardData?.items;
      if (!items) {
        return;
      }
      for (const item of Array.from(items)) {
        if (item.kind !== "file") {
          continue;
        }
        const file = item.getAsFile();
        if (file && file.type.startsWith("image/")) {
          event.preventDefault();
          void handleImageFile(file);
          break;
        }
      }
    };
    dom.addEventListener("drop", onDrop);
    dom.addEventListener("paste", onPaste);
    return () => {
      dom.removeEventListener("drop", onDrop);
      dom.removeEventListener("paste", onPaste);
    };
  }, [editor, handleImageFile]);

  if (!page) {
    return <p>Loading editor…</p>;
  }

  const openImagePicker = () => fileInputRef.current?.click();
  const isAdmin = identity?.wiki_role === "admin";

  const saveAcl = async () => {
    if (!page || !isAdmin) {
      return;
    }
    try {
      const viewRoles = aclViewRoles
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const editRoles = aclEditRoles
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const updated = await updatePageAcl(page.id, {
        acl_override: aclOverride,
        view_roles: viewRoles,
        edit_roles: editRoles,
      });
      setAclOverride(Boolean(updated.acl_override));
      setAclViewRoles((updated.acl?.view_roles || []).join(","));
      setAclEditRoles((updated.acl?.edit_roles || []).join(","));
    } catch (err) {
      setStatus("error");
    }
  };

  const deleteCurrentPage = async () => {
    if (!page) {
      return;
    }
    if (!window.confirm("Delete this page? This cannot be undone.")) {
      return;
    }
    try {
      await deletePage(page.id);
      navigate("/");
    } catch (err) {
      setStatus("error");
    }
  };

  const saveRevision = async () => {
    if (!page) {
      return;
    }
    try {
      await createPageRevision(page.id);
      reloadRevisions(page.id);
    } catch (err) {
      setStatus("error");
    }
  };

  const rebuildLinks = async () => {
    if (!page) {
      return;
    }
    try {
      await rebuildPageLinks(page.id);
    } catch (err) {
      setStatus("error");
    }
  };

  const restoreRevision = async (revisionId: string) => {
    if (!page) {
      return;
    }
    try {
      const restored = await restorePageRevision(page.id, revisionId);
      setTitle(restored.title);
      setSlug(restored.slug);
      setCategoryId(restored.category_id || "general");
      setEntityType(restored.entity_type || "");
      setTemplateId(restored.template_id || "");
      setPageStatus(restored.status || "draft");
      setSummary(restored.summary || "");
      setTagsText((restored.tags || []).join(", "));
      setFieldsText(JSON.stringify(restored.fields || {}, null, 2));
      editor?.commands.setContent(restored.doc_json || { type: "doc", content: [] });
      reloadRevisions(page.id);
    } catch (err) {
      setStatus("error");
    }
  };

  return (
    <div>
      <header>
        <h1>Editing {title}</h1>
        <div className="status-pill">
          {status === "saving" && "Saving…"}
          {status === "saved" && "Saved"}
          {status === "idle" && "Idle"}
          {status === "error" && "Save error"}
        </div>
      </header>

      <div style={{ display: "flex", gap: "12px", marginBottom: "16px" }}>
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Title" />
        <input value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="Slug" />
        <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
          {(categories.length
            ? categories
            : [{ id: "general", key: "general", label: "General", slug: "general", sort_order: 0, created_at: "", updated_at: "" }]
          ).map((category) => (
            <option key={category.id} value={category.id}>
              {category.label}
            </option>
          ))}
        </select>
        <select value={pageStatus} onChange={(event) => setPageStatus(event.target.value as "draft" | "published" | "archived")}>
          <option value="draft">draft</option>
          <option value="published">published</option>
          <option value="archived">archived</option>
        </select>
      </div>
      <div style={{ display: "flex", gap: "12px", marginBottom: "16px" }}>
        <input value={entityType} onChange={(event) => setEntityType(event.target.value)} placeholder="Entity type" />
        <select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
          <option value="">No template</option>
          {templates.map((tpl) => (
            <option key={tpl.id} value={tpl.id}>
              {tpl.label}
            </option>
          ))}
        </select>
        <input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="Summary" />
        <input value={tagsText} onChange={(event) => setTagsText(event.target.value)} placeholder="Tags (comma-separated)" />
      </div>
      <div style={{ marginBottom: "16px" }}>
        <label style={{ display: "block", marginBottom: "6px" }}>Entity fields (JSON object)</label>
        <textarea
          value={fieldsText}
          onChange={(event) => setFieldsText(event.target.value)}
          rows={6}
          style={{ width: "100%", fontFamily: "monospace" }}
        />
        {fieldError && <div className="error-text">{fieldError}</div>}
      </div>
      {isAdmin && (
        <div style={{ display: "flex", gap: "12px", marginBottom: "16px", alignItems: "center" }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <input type="checkbox" checked={aclOverride} onChange={(event) => setAclOverride(event.target.checked)} />
            ACL override
          </label>
          <input value={aclViewRoles} onChange={(event) => setAclViewRoles(event.target.value)} placeholder="view roles csv" />
          <input value={aclEditRoles} onChange={(event) => setAclEditRoles(event.target.value)} placeholder="edit roles csv" />
          <button onClick={saveAcl}>Save ACL</button>
        </div>
      )}
      <div style={{ marginBottom: "16px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
        <button onClick={saveRevision}>Snapshot Revision</button>
        <button onClick={rebuildLinks}>Rebuild Links</button>
        <button onClick={deleteCurrentPage} style={{ background: "#632f2f" }}>
          Delete Page
        </button>
      </div>
      <div style={{ marginBottom: "16px" }}>
        <h3 style={{ marginBottom: "8px" }}>Revisions</h3>
        {revisions.length ? (
          <ul style={{ margin: 0, paddingLeft: "18px" }}>
            {revisions.map((rev) => (
              <li key={rev.id} style={{ marginBottom: "6px" }}>
                <span style={{ marginRight: "8px" }}>{new Date(rev.created_at).toLocaleString()}</span>
                <button onClick={() => restoreRevision(rev.id)}>Restore</button>
              </li>
            ))}
          </ul>
        ) : (
          <p>No revisions yet.</p>
        )}
      </div>

      <div className="toolbar">
        {toolbarActions.map((action) => (
          <button
            key={action.label}
            onClick={() => editor && action.action(editor)}
            disabled={!editor}
          >
            {action.label}
          </button>
        ))}
        <button onClick={openImagePicker} disabled={!editor}>
          Image
        </button>
        <TablePicker editor={editor} />
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          style={{ display: "none" }}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) {
              handleImageFile(file);
            }
            event.target.value = "";
          }}
        />
      </div>
      {imageError && <div className="error-text">{imageError}</div>}

      <div className="editor-wrapper">
        <EditorContent editor={editor} />
        
        
      </div>
    </div>
  );
};

export default PageEditor;

