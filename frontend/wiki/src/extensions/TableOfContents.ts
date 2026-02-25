import { Node, mergeAttributes } from "@tiptap/core";
import { Plugin, PluginKey } from "prosemirror-state";
import { collectHeadings, HeadingItem } from "../utils/text";

const tocKey = new PluginKey("tableOfContents");

const renderTocItems = (items: HeadingItem[]) => {
  if (!items.length) {
    return [["li", {}, "Add headings to generate links"]];
  }
  return items.map((item) => [
    "li",
    { style: "margin-bottom:4px;font-size:13px;" },
    [
      "a",
      {
        href: `#${item.id}`,
        style: "color:#a9b2ff;text-decoration:none;",
      },
      `${"  ".repeat(item.level - 1)}${item.text}`,
    ],
  ]);
};

const TableOfContents = Node.create({
  name: "tableOfContents",
  group: "block",
  atom: true,
  addAttributes() {
    return {
      items: {
        default: [] as HeadingItem[],
      },
    };
  },
  parseHTML() {
    return [{ tag: "div[data-type='table-of-contents']" }];
  },
  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes({ class: "toc-block", "data-type": "table-of-contents" }, HTMLAttributes),
      [
        "strong",
        { style: "display:block;margin-bottom:8px;font-size:14px;color:#a9b2ff;" },
        "Table of Contents",
      ],
      ["ul", { style: "padding-left:16px" }, ...renderTocItems(HTMLAttributes.items || [])],
    ];
  },
  addCommands() {
    return {
      insertTableOfContents:
        () =>
        ({ commands }) => {
          return commands.insertContent({
            type: this.name,
            attrs: { items: [] },
          });
        },
    };
  },
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: tocKey,
        appendTransaction: (transactions, oldState, newState) => {
          let tr = newState.tr;
          let mutated = false;
          newState.doc.descendants((node, pos) => {
            if (node.type.name !== "tableOfContents") {
              return;
            }
            const headings = collectHeadings(newState.doc);
            const items = headings.map((item) => ({
              id: item.id,
              level: item.level,
              text: item.text,
            }));
            const attrs = node.attrs || {};
            const needsUpdate = JSON.stringify(attrs.items) !== JSON.stringify(items);
            if (needsUpdate) {
              tr = tr.setNodeMarkup(pos, undefined, { ...attrs, items });
              mutated = true;
            }
          });
          return mutated ? tr : undefined;
        },
      }),
    ];
  },
});

export default TableOfContents;
