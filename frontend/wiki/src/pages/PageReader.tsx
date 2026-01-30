import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Editor, EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import ExtendedLink from "../extensions/ExtendedLink";
import ExtendedImage from "../extensions/ExtendedImage";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import HorizontalRule from "@tiptap/extension-horizontal-rule";
import HeadingAnchors from "../extensions/HeadingAnchors";
import TableOfContents from "../extensions/TableOfContents";
import { getPage, getPageBySlug, PagePayload } from "../utils/api";

const ReadOnlyEditor: React.FC<{ content: any }> = ({ content }) => {
  const editor = useEditor({
    editable: false,
    content,
      extensions: [
        HeadingAnchors,
        TableOfContents,
        StarterKit,
        Table.configure({ resizable: true }),
        TableRow,
        TableHeader,
        TableCell,
        TableColumnResizing,
        Underline,
        ExtendedLink,
        ExtendedImage,
        TaskList,
        TaskItem,
        HorizontalRule,
      ],
  });

  return <EditorContent editor={editor} />;
};

const PageReader: React.FC = () => {
  const { id, slug } = useParams<{ id?: string; slug?: string }>();
  const [page, setPage] = useState<PagePayload | null>(null);

  useEffect(() => {
    if (id) {
      getPage(id).then(setPage);
      return;
    }
    if (slug) {
      getPageBySlug(slug).then(setPage);
      return;
    }
  }, [id, slug]);

  if (!page) {
    return <p>Loading…</p>;
  }

  return (
    <div>
      <h1>{page.title}</h1>
      <p style={{ fontSize: "13px", color: "#9ba5ff" }}>Last updated {new Date(page.updated_at).toLocaleString()}</p>
      <div className="editor-wrapper">
        <ReadOnlyEditor content={page.doc_json} />
      </div>
    </div>
  );
};

export default PageReader;
