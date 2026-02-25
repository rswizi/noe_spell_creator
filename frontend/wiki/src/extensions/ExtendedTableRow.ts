import TableRow from "@tiptap/extension-table-row";

const ExtendedTableRow = TableRow.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      rowHeight: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-row-height");
          if (!value) {
            return null;
          }
          const parsed = Number(value);
          return Number.isFinite(parsed) ? parsed : null;
        },
        renderHTML: (attributes) => {
          if (!attributes.rowHeight) {
            return {};
          }
          return {
            "data-row-height": String(attributes.rowHeight),
            style: `height:${attributes.rowHeight}px;`,
          };
        },
      },
    };
  },
});

export default ExtendedTableRow;
