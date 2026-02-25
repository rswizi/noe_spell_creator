import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Editor, EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Color from "@tiptap/extension-color";
import Highlight from "@tiptap/extension-highlight";
import TextAlign from "@tiptap/extension-text-align";
import TextStyle from "@tiptap/extension-text-style";
import Table from "@tiptap/extension-table";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import HeadingAnchors from "../extensions/HeadingAnchors";
import TableOfContents from "../extensions/TableOfContents";
import ExtendedLink from "../extensions/ExtendedLink";
import ExtendedImage from "../extensions/ExtendedImage";
import ExtendedTableRow from "../extensions/ExtendedTableRow";
import ExitListOnBackspace from "../extensions/ExitListOnBackspace";
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

type HeadingValue = "paragraph" | "h1" | "h2" | "h3" | "h4";
type ListValue = "none" | "bullet" | "ordered" | "checklist";
const PageEditor: React.FC = () => {
  type TableContextMenuState = {
    x: number;
    y: number;
    onTableCell: boolean;
    onLink: boolean;
    onImage: boolean;
  };
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
  const [textColor, setTextColor] = useState("#f5f7ff");
  const [highlightColor, setHighlightColor] = useState("#fff59d");
  const [tableContextMenu, setTableContextMenu] = useState<TableContextMenuState | null>(null);
  const [linkDialogOpen, setLinkDialogOpen] = useState(false);
  const [linkValue, setLinkValue] = useState("");

  const editor = useEditor({
    extensions: [
      HeadingAnchors,
      TableOfContents,
      StarterKit,
      TextStyle,
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      Color.configure({ types: ["textStyle"] }),
      Highlight.configure({ multicolor: true }),
      Table.configure({ resizable: true, lastColumnResizable: true, allowTableNodeSelection: true }),
      ExtendedTableRow,
      TableHeader,
      TableCell,
      ExtendedImage,
      Underline,
      ExtendedLink.configure({ openOnClick: false }),
      TaskList,
      TaskItem,
      ExitListOnBackspace,
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

  const getHeadingValue = (): HeadingValue => {
    if (!editor) {
      return "paragraph";
    }
    if (editor.isActive("heading", { level: 1 })) return "h1";
    if (editor.isActive("heading", { level: 2 })) return "h2";
    if (editor.isActive("heading", { level: 3 })) return "h3";
    if (editor.isActive("heading", { level: 4 })) return "h4";
    return "paragraph";
  };

  const applyHeadingValue = (value: HeadingValue) => {
    if (!editor) {
      return;
    }
    if (value === "paragraph") {
      editor.chain().focus().setParagraph().run();
      return;
    }
    const level = Number(value.replace("h", "")) as 1 | 2 | 3 | 4;
    editor.chain().focus().setHeading({ level }).run();
  };

  const getListValue = (): ListValue => {
    if (!editor) {
      return "none";
    }
    if (editor.isActive("taskList")) return "checklist";
    if (editor.isActive("orderedList")) return "ordered";
    if (editor.isActive("bulletList")) return "bullet";
    return "none";
  };

  const applyListValue = (value: ListValue) => {
    if (!editor) {
      return;
    }
    if (value === "none") {
      if (editor.isActive("taskList")) editor.chain().focus().toggleTaskList().run();
      else if (editor.isActive("orderedList")) editor.chain().focus().toggleOrderedList().run();
      else if (editor.isActive("bulletList")) editor.chain().focus().toggleBulletList().run();
      else editor.chain().focus().setParagraph().run();
      return;
    }
    if (value === "bullet") {
      if (editor.isActive("orderedList")) editor.chain().focus().toggleOrderedList().run();
      if (editor.isActive("taskList")) editor.chain().focus().toggleTaskList().run();
      if (!editor.isActive("bulletList")) editor.chain().focus().toggleBulletList().run();
      return;
    }
    if (value === "ordered") {
      if (editor.isActive("bulletList")) editor.chain().focus().toggleBulletList().run();
      if (editor.isActive("taskList")) editor.chain().focus().toggleTaskList().run();
      if (!editor.isActive("orderedList")) editor.chain().focus().toggleOrderedList().run();
      return;
    }
    if (editor.isActive("bulletList")) editor.chain().focus().toggleBulletList().run();
    if (editor.isActive("orderedList")) editor.chain().focus().toggleOrderedList().run();
    if (!editor.isActive("taskList")) editor.chain().focus().toggleTaskList().run();
  };

  const openLinkDialog = () => {
    if (!editor) {
      return;
    }
    const currentHref = (editor.getAttributes("link").href as string | undefined) || "";
    setLinkValue(currentHref);
    setLinkDialogOpen(true);
  };

  const closeLinkDialog = () => {
    setLinkDialogOpen(false);
    setLinkValue("");
  };

  const applyLink = () => {
    if (!editor) {
      closeLinkDialog();
      return;
    }
    const normalized = linkValue.trim();
    if (!normalized) {
      editor.chain().focus().unsetLink().run();
    } else {
      editor.chain().focus().extendMarkRange("link").setLink({ href: normalized }).run();
    }
    closeLinkDialog();
  };

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
          entity_type: entityType.trim() ? entityType.trim() : null,
          template_id: templateId || null,
          fields,
          status: pageStatus,
          summary: summary.trim() ? summary.trim() : null,
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
    if (!editor || !page) {
      return;
    }
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => {
      void autoSave();
    }, 900);
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [autoSave, categoryId, editor, entityType, fieldsText, page, pageStatus, slug, summary, tagsText, templateId, title]);

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

  useEffect(() => {
    if (!editor) {
      return;
    }
    const dom = editor.view.dom as HTMLElement;
    const onContextMenu = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      const cell = target?.closest("td,th");
      const imageNode = target?.closest("figure.image-node,img");
      event.preventDefault();
      if (imageNode) {
        try {
          const pos = editor.view.posAtDOM(imageNode, 0);
          editor.chain().focus().setNodeSelection(pos).run();
        } catch {
          editor.chain().focus().run();
        }
      } else if (cell) {
        try {
          const pos = editor.view.posAtDOM(cell, 0);
          editor.chain().focus().setTextSelection(pos + 1).run();
        } catch {
          editor.chain().focus().run();
        }
      } else {
        editor.chain().focus().run();
      }
      setTableContextMenu({
        x: event.clientX,
        y: event.clientY,
        onTableCell: Boolean(cell),
        onLink: editor.isActive("link"),
        onImage: Boolean(imageNode) || editor.isActive("extendedImage"),
      });
    };
    dom.addEventListener("contextmenu", onContextMenu);
    return () => {
      dom.removeEventListener("contextmenu", onContextMenu);
    };
  }, [editor]);

  useEffect(() => {
    if (!tableContextMenu) {
      return;
    }
    const close = () => setTableContextMenu(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        close();
      }
    };
    window.addEventListener("click", close);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [tableContextMenu]);

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

  const runTableAction = (action: (instance: Editor) => void) => {
    if (!editor) {
      return;
    }
    action(editor);
    setTableContextMenu(null);
  };

  const adjustRowHeight = (delta: number) => {
    if (!editor) {
      return;
    }
    const current = Number(editor.getAttributes("tableRow").rowHeight) || 40;
    const next = Math.max(24, Math.min(360, current + delta));
    editor.chain().focus().updateAttributes("tableRow", { rowHeight: next }).run();
    setTableContextMenu(null);
  };

  const setImageWidthPercent = (percent: number) => {
    if (!editor) {
      return;
    }
    const next = Math.max(10, Math.min(100, percent));
    editor.chain().focus().updateAttributes("extendedImage", { width: `${next}%` }).run();
    setTableContextMenu(null);
  };

  const adjustImageWidth = (delta: number) => {
    if (!editor) {
      return;
    }
    const raw = String(editor.getAttributes("extendedImage").width || "100%");
    const current = Number(raw.replace("%", "")) || 100;
    setImageWidthPercent(current + delta);
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
        <select
          className="toolbar-select"
          value={getHeadingValue()}
          onChange={(event) => applyHeadingValue(event.target.value as HeadingValue)}
          disabled={!editor}
        >
          <option value="paragraph">Paragraph</option>
          <option value="h1">H1</option>
          <option value="h2">H2</option>
          <option value="h3">H3</option>
          <option value="h4">H4</option>
        </select>
        <select
          className="toolbar-select"
          value={getListValue()}
          onChange={(event) => applyListValue(event.target.value as ListValue)}
          disabled={!editor}
        >
          <option value="none">No List</option>
          <option value="bullet">Bullet List</option>
          <option value="ordered">Numbered List</option>
          <option value="checklist">Checklist</option>
        </select>
        <button onClick={() => editor?.chain().focus().toggleBold().run()} disabled={!editor}>
          B
        </button>
        <button onClick={() => editor?.chain().focus().toggleItalic().run()} disabled={!editor}>
          I
        </button>
        <button onClick={() => editor?.chain().focus().toggleUnderline().run()} disabled={!editor}>
          U
        </button>
        <button onClick={() => editor?.chain().focus().toggleStrike().run()} disabled={!editor}>
          S
        </button>
        <button onClick={() => editor?.chain().focus().toggleBlockquote().run()} disabled={!editor}>
          Quote
        </button>
        <button onClick={() => editor?.chain().focus().toggleCodeBlock().run()} disabled={!editor}>
          {"</>"}
        </button>
        <button onClick={() => openLinkDialog()} disabled={!editor}>
          Link
        </button>
        <button onClick={() => editor?.chain().focus().unsetLink().run()} disabled={!editor}>
          Unlink
        </button>
        <button className="toolbar-icon-button" onClick={() => editor?.chain().focus().setTextAlign("left").run()} disabled={!editor} title="Align Left">
          <i className="fa-solid fa-align-left" aria-hidden="true" />
        </button>
        <button className="toolbar-icon-button" onClick={() => editor?.chain().focus().setTextAlign("center").run()} disabled={!editor} title="Align Center">
          <i className="fa-solid fa-align-center" aria-hidden="true" />
        </button>
        <button className="toolbar-icon-button" onClick={() => editor?.chain().focus().setTextAlign("right").run()} disabled={!editor} title="Align Right">
          <i className="fa-solid fa-align-right" aria-hidden="true" />
        </button>
        <button className="toolbar-icon-button" onClick={() => editor?.chain().focus().setTextAlign("justify").run()} disabled={!editor} title="Justify">
          <i className="fa-solid fa-align-justify" aria-hidden="true" />
        </button>
        <button className="toolbar-icon-button" onClick={() => editor?.chain().focus().undo().run()} disabled={!editor} title="Undo">
          <i className="fa-solid fa-rotate-left" aria-hidden="true" />
        </button>
        <button className="toolbar-icon-button" onClick={() => editor?.chain().focus().redo().run()} disabled={!editor} title="Redo">
          <i className="fa-solid fa-rotate-right" aria-hidden="true" />
        </button>
        <button onClick={() => editor?.chain().focus().insertTableOfContents().run()} disabled={!editor}>
          TOC
        </button>
        <label className="toolbar-color-control">
          Text
          <input type="color" value={textColor} onChange={(event) => setTextColor(event.target.value)} />
        </label>
        <button onClick={() => editor?.chain().focus().setColor(textColor).run()} disabled={!editor}>
          Apply Text
        </button>
        <button onClick={() => editor?.chain().focus().unsetColor().run()} disabled={!editor}>
          Clear Text
        </button>
        <label className="toolbar-color-control">
          Highlight
          <input type="color" value={highlightColor} onChange={(event) => setHighlightColor(event.target.value)} />
        </label>
        <button onClick={() => editor?.chain().focus().setHighlight({ color: highlightColor }).run()} disabled={!editor}>
          Apply Highlight
        </button>
        <button onClick={() => editor?.chain().focus().unsetHighlight().run()} disabled={!editor}>
          Clear Highlight
        </button>
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
      {tableContextMenu && editor && (
        <div
          className="editor-right-click-menu"
          style={{ top: `${tableContextMenu.y}px`, left: `${tableContextMenu.x}px` }}
          onClick={(event) => event.stopPropagation()}
        >
          <button onClick={() => runTableAction((instance) => instance.chain().focus().toggleBold().run())}>Bold</button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().toggleItalic().run())}>Italic</button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().toggleUnderline().run())}>Underline</button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().toggleStrike().run())}>Strikethrough</button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().setTextAlign("left").run())}>Align Left</button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().setTextAlign("center").run())}>Align Center</button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().setTextAlign("right").run())}>Align Right</button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().setTextAlign("justify").run())}>Justify</button>
          <button
            onClick={() => {
              setTableContextMenu(null);
              openLinkDialog();
            }}
          >
            {tableContextMenu.onLink ? "Edit Link" : "Add Link"}
          </button>
          {tableContextMenu.onLink && (
            <button onClick={() => runTableAction((instance) => instance.chain().focus().unsetLink().run())}>Remove Link</button>
          )}
          <button onClick={() => runTableAction((instance) => instance.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run())}>
            Insert Table (3x3)
          </button>
          <button
            onClick={() => {
              setTableContextMenu(null);
              openImagePicker();
            }}
          >
            Insert Image
          </button>
          {tableContextMenu.onImage && (
            <>
              <button onClick={() => setImageWidthPercent(25)}>Image Width 25%</button>
              <button onClick={() => setImageWidthPercent(50)}>Image Width 50%</button>
              <button onClick={() => setImageWidthPercent(75)}>Image Width 75%</button>
              <button onClick={() => setImageWidthPercent(100)}>Image Width 100%</button>
              <button onClick={() => adjustImageWidth(-10)}>Image Width -10%</button>
              <button onClick={() => adjustImageWidth(10)}>Image Width +10%</button>
            </>
          )}
          {tableContextMenu.onTableCell && (
            <>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().addRowBefore().run())}>
            Add Row Above
          </button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().addRowAfter().run())}>
            Add Row Below
          </button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().deleteRow().run())}>
            Delete Row
          </button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().addColumnBefore().run())}>
            Add Col Left
          </button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().addColumnAfter().run())}>
            Add Col Right
          </button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().deleteColumn().run())}>
            Delete Col
          </button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().toggleHeaderRow().run())}>
            Toggle Header
          </button>
          <button onClick={() => adjustRowHeight(-10)}>Row Height -10px</button>
          <button onClick={() => adjustRowHeight(10)}>Row Height +10px</button>
          <button onClick={() => runTableAction((instance) => instance.chain().focus().deleteTable().run())}>
            Delete Table
          </button>
            </>
          )}
        </div>
      )}
      {linkDialogOpen && (
        <div className="link-modal-backdrop" onClick={closeLinkDialog}>
          <div className="link-modal" onClick={(event) => event.stopPropagation()}>
            <h3>Set Hyperlink</h3>
            <input
              value={linkValue}
              onChange={(event) => setLinkValue(event.target.value)}
              placeholder="https://example.com"
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  applyLink();
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  closeLinkDialog();
                }
              }}
              autoFocus
            />
            <div className="link-modal-actions">
              <button onClick={closeLinkDialog}>Cancel</button>
              <button
                onClick={() => {
                  editor?.chain().focus().unsetLink().run();
                  closeLinkDialog();
                }}
              >
                Remove
              </button>
              <button onClick={applyLink}>Apply</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PageEditor;


