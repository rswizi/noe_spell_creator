import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Color from "@tiptap/extension-color";
import Highlight from "@tiptap/extension-highlight";
import TextAlign from "@tiptap/extension-text-align";
import TextStyle from "@tiptap/extension-text-style";
import ExtendedLink from "../extensions/ExtendedLink";
import ExtendedImage from "../extensions/ExtendedImage";
import Table from "@tiptap/extension-table";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import HeadingAnchors from "../extensions/HeadingAnchors";
import TableOfContents from "../extensions/TableOfContents";
import ExtendedTableRow from "../extensions/ExtendedTableRow";
import { fetchPageContext, getPage, getPageBySlug, PagePayload } from "../utils/api";

const ReadOnlyEditor: React.FC<{ content: any }> = ({ content }) => {
  const editor = useEditor({
    editable: false,
    content,
    extensions: [
      HeadingAnchors,
      TableOfContents,
      StarterKit,
      TextStyle,
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      Color.configure({ types: ["textStyle"] }),
      Highlight.configure({ multicolor: true }),
      Table.configure({ resizable: true }),
      ExtendedTableRow,
      TableHeader,
      TableCell,
      Underline,
      ExtendedLink,
      ExtendedImage,
      TaskList,
      TaskItem,
    ],
  });

  return <EditorContent editor={editor} />;
};

const PageReader: React.FC = () => {
  const { id, slug } = useParams<{ id?: string; slug?: string }>();
  const [page, setPage] = useState<PagePayload | null>(null);
  const [backlinks, setBacklinks] = useState<any[]>([]);
  const [relations, setRelations] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id) {
      getPage(id)
        .then((payload) => {
          setPage(payload);
          setError(null);
        })
        .catch((err) => setError(err instanceof Error ? err.message : "Failed to load page"));
      return;
    }
    if (slug) {
      getPageBySlug(slug)
        .then((payload) => {
          setPage(payload);
          setError(null);
        })
        .catch((err) => setError(err instanceof Error ? err.message : "Failed to load page"));
      return;
    }
  }, [id, slug]);

  useEffect(() => {
    if (!page?.id) {
      return;
    }
    fetchPageContext(page.id)
      .then((context) => {
        setBacklinks(context.backlinks || []);
        setRelations(context.relations || []);
      })
      .catch(() => {
        setBacklinks([]);
        setRelations([]);
      });
  }, [page?.id]);

  if (error) {
    return <p style={{ color: "#ff7675" }}>{error}</p>;
  }

  if (!page) {
    return <p>Loading...</p>;
  }

  return (
    <div>
      <h1>{page.title}</h1>
      <p style={{ fontSize: "13px", color: "#9ba5ff" }}>Last updated {new Date(page.updated_at).toLocaleString()}</p>
      <p style={{ fontSize: "13px", color: "#9ba5ff" }}>
        {page.category_id} {page.entity_type ? `- ${page.entity_type}` : ""} {page.status ? `- ${page.status}` : ""}
      </p>
      <div className="editor-wrapper">
        <ReadOnlyEditor content={page.doc_json} />
      </div>
      <div style={{ marginTop: "16px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
        <div>
          <h3>Backlinks</h3>
          {backlinks.length ? (
            <ul>
              {backlinks.map((row) => (
                <li key={row.id || `${row.from_page_id}-${row.to_page_id}`}>{row.from_page?.title || row.from_page_id}</li>
              ))}
            </ul>
          ) : (
            <p>No backlinks.</p>
          )}
        </div>
        <div>
          <h3>Relations</h3>
          {relations.length ? (
            <ul>
              {relations.map((row) => (
                <li key={row.id || `${row.from_page_id}-${row.to_page_id}-${row.relation_type}`}>
                  {row.relation_type}: {row.from_page?.title || row.from_page_id} -&gt; {row.to_page?.title || row.to_page_id}
                </li>
              ))}
            </ul>
          ) : (
            <p>No relations.</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default PageReader;
