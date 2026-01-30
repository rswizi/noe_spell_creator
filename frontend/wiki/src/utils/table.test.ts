import { describe, expect, it } from "vitest";
import { Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableHeader from "@tiptap/extension-table-header";
import TableCell from "@tiptap/extension-table-cell";

describe("table insertion", () => {
  it("creates a structured table with header row", () => {
    const editor = new Editor({
      editorProps: { attributes: {} },
      extensions: [
        StarterKit,
        Table.configure({ resizable: true }),
        TableRow,
        TableHeader,
        TableCell,
      ],
      content: "",
    });

    editor.chain().focus().insertTable({ rows: 2, cols: 3, withHeaderRow: true }).run();
    const doc = editor.getJSON();
    const table = doc.content?.find((node: any) => node.type === "table");
    expect(table).toBeDefined();
    expect(table.content).toHaveLength(3);
    expect(table.content[0].type).toBe("tableRow");
    expect(table.content[0].content.every((cell: any) => cell.type === "tableHeader")).toBe(true);
    editor.destroy();
  });
});
