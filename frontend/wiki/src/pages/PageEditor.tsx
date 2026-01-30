import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Editor, EditorContent, FloatingMenu, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TableColumnResizing from "@tiptap/extension-table-column-resizing";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import BubbleMenu from "@tiptap/extension-bubble-menu";
import HorizontalRule from "@tiptap/extension-horizontal-rule";
import SlashCommand from "../extensions/SlashCommand";
import HeadingAnchors from "../extensions/HeadingAnchors";
import TableOfContents from "../extensions/TableOfContents";
import InternalLinkSuggestion from "../extensions/InternalLinkSuggestion";
import ExtendedLink from "../extensions/ExtendedLink";
import ExtendedImage from "../extensions/ExtendedImage";
import TablePicker from "../components/TablePicker";
import { getPage, updatePage, PagePayload, uploadAsset } from "../utils/api";

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

  const editor = useEditor({
    extensions: [
      HeadingAnchors,
      TableOfContents,
      StarterKit,
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      TableColumnResizing.configure({ handleWidth: 6 }),
      ExtendedImage,
      Underline,
      ExtendedLink.configure({ openOnClick: false }),
      TaskList,
      TaskItem,
      InternalLinkSuggestion,
      BubbleMenu.configure({
        component: ({ editor }) => (
          <div className="bubble-menu">
            <button onClick={() => editor.chain().focus().toggleBold().run()}>B</button>
            <button onClick={() => editor.chain().focus().toggleItalic().run()}>I</button>
            <button onClick={() => editor.chain().focus().setLink({ href: prompt("URL") || "" }).run()}>Link</button>
          </div>
        ),
      }),
      SlashCommand,
      HorizontalRule,
    ],
    editable: true,
    content: "",
  });

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const docRef = useRef<string>("");
  const metaRef = useRef({ title: "", slug: "" });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      const metaChanged = title !== metaRef.current.title || slug !== metaRef.current.slug;
      if (!force && newHash === docRef.current && !metaChanged) {
        return;
      }
      setStatus("saving");
      try {
        const updated = await updatePage(page.id, {
          doc_json: doc,
          title,
          slug,
        });
        docRef.current = JSON.stringify(editor.getJSON());
        metaRef.current = { title: updated.title, slug: updated.slug };
        setStatus("saved");
      } catch (err) {
        setStatus("error");
      }
    },
    [editor, page, title, slug]
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
        editor?.commands.setContent(data.doc_json || { type: "doc", content: [] });
        docRef.current = JSON.stringify(data.doc_json);
      })
      .catch(() => {
        navigate("/wiki");
      });
  }, [id, editor, navigate]);

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
        {editor && (
          <FloatingMenu
            editor={editor}
            tippyOptions={{ duration: 120 }}
            shouldShow={({ editor }) => editor.isActive("table")}
          >
            <div className="table-context-menu">
              <button onClick={() => editor.chain().focus().addRowBefore().run()}>Row ↑</button>
              <button onClick={() => editor.chain().focus().addRowAfter().run()}>Row ↓</button>
              <button onClick={() => editor.chain().focus().addColumnBefore().run()}>Col ←</button>
              <button onClick={() => editor.chain().focus().addColumnAfter().run()}>Col →</button>
              <button onClick={() => editor.chain().focus().deleteColumn().run()}>Remove Col</button>
              <button onClick={() => editor.chain().focus().toggleHeaderRow().run()}>Header</button>
              <button onClick={() => editor.chain().focus().deleteTable().run()}>Delete</button>
            </div>
          </FloatingMenu>
        )}
        {editor && (
          <FloatingMenu
            editor={editor}
            tippyOptions={{ duration: 120 }}
            shouldShow={({ editor }) => editor.isActive("extendedImage")}
          >
            <div className="image-context-menu">
              <button
                onClick={() => {
                  const current = editor.getAttributes("extendedImage").caption || "";
                  const caption = prompt("Caption", current);
                  if (caption !== null) {
                    editor.chain().focus().updateAttributes("extendedImage", { caption }).run();
                  }
                }}
              >
                Caption
              </button>
              <button onClick={() => editor.chain().focus().updateAttributes("extendedImage", { width: "100%" }).run()}>
                Full
              </button>
              <button onClick={() => editor.chain().focus().updateAttributes("extendedImage", { width: "50%" }).run()}>
                Half
              </button>
              <button onClick={() => editor.chain().focus().updateAttributes("extendedImage", { alignment: "left" }).run()}>
                Left
              </button>
              <button
                onClick={() =>
                  editor.chain().focus().updateAttributes("extendedImage", { alignment: "center" }).run()
                }
              >
                Center
              </button>
              <button onClick={() => editor.chain().focus().updateAttributes("extendedImage", { alignment: "right" }).run()}>
                Right
              </button>
            </div>
          </FloatingMenu>
        )}
      </div>
    </div>
  );
};

export default PageEditor;
