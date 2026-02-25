import { Extension } from "@tiptap/core";

const ExitListOnBackspace = Extension.create({
  name: "exitListOnBackspace",
  addKeyboardShortcuts() {
    return {
      Backspace: () => {
        const { selection } = this.editor.state;
        if (!selection.empty) {
          return false;
        }
        const { $from } = selection;
        const parent = $from.parent;
        if (parent.textContent.length > 0) {
          return false;
        }
        if (parent.type.name === "listItem") {
          return this.editor.commands.liftListItem("listItem");
        }
        if (parent.type.name === "taskItem") {
          return this.editor.commands.liftListItem("taskItem");
        }
        return false;
      },
    };
  },
});

export default ExitListOnBackspace;
