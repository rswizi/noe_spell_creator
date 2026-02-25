import Suggestion from "@tiptap/suggestion";
import { Editor } from "@tiptap/react";
import { Extension } from "@tiptap/core";
import { PluginKey } from "prosemirror-state";

type SlashItem = {
  title: string;
  command: (editor: Editor) => void;
};

const items: SlashItem[] = [
  {
    title: "Heading 1",
    command: (editor) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
  },
  {
    title: "Heading 2",
    command: (editor) => editor.chain().focus().toggleHeading({ level: 2 }).run(),
  },
  {
    title: "Heading 3",
    command: (editor) => editor.chain().focus().toggleHeading({ level: 3 }).run(),
  },
  {
    title: "Bullet list",
    command: (editor) => editor.chain().focus().toggleBulletList().run(),
  },
  {
    title: "Numbered list",
    command: (editor) => editor.chain().focus().toggleOrderedList().run(),
  },
  {
    title: "Checklist",
    command: (editor) => editor.chain().focus().toggleTaskList().run(),
  },
  {
    title: "Quote",
    command: (editor) => editor.chain().focus().toggleBlockquote().run(),
  },
  {
    title: "Code block",
    command: (editor) => editor.chain().focus().toggleCodeBlock().run(),
  },
  {
    title: "Divider",
    command: (editor) => editor.chain().focus().setHorizontalRule().run(),
  },
  {
    title: "Table of Contents",
    command: (editor) => editor.chain().focus().insertTableOfContents().run(),
  },
];

const slashPluginKey = new PluginKey("slash-command");

const SlashCommand = Extension.create({
  name: "slashCommand",
  addOptions() {
    return {
      suggestion: {
        char: "/",
        command: ({ editor, range, props }: any) => {
          props.command(editor);
          editor.commands.focus();
        },
      },
    };
  },
  addProseMirrorPlugins() {
    return [
      Suggestion({
        editor: this.editor,
        char: "/",
        pluginKey: slashPluginKey,
        command: ({ editor, range, props }) => {
          editor.chain().focus().deleteRange(range).run();
          props.command(editor);
        },
        items: ({ query }) => {
          const normalized = query.toLowerCase();
          return items
            .filter((item) => item.title.toLowerCase().includes(normalized))
            .map((item) => ({
              title: item.title,
              command: item.command,
            }));
        },
        render: () => {
          let component: HTMLDivElement;

          return {
            onStart: (props) => {
              component = document.createElement("div");
              component.classList.add("slash-menu");
              updateList(props);
              document.body.appendChild(component);
              setPosition(props);
            },
            onUpdate: (props) => {
              updateList(props);
              setPosition(props);
            },
            onKeyDown: (props) => {
              if (props.event.key === "Escape") {
                component?.remove();
                return true;
              }
              return false;
            },
            onExit: () => {
              component?.remove();
            },
          };

          function updateList(props: any) {
            if (!component) {
              return;
            }
            component.innerHTML = "";
            props.items.forEach((item: any) => {
              const button = document.createElement("button");
              button.textContent = item.title;
              button.onclick = () => {
                props.command(item);
              };
              component.appendChild(button);
            });
          }

          function setPosition(props: any) {
            if (!component) {
              return;
            }
            const rect = typeof props.clientRect === "function" ? props.clientRect() : null;
            if (!rect) {
              return;
            }
            const { left, top } = rect;
            component.style.left = `${left}px`;
            component.style.top = `${top + 24}px`;
          }
        },
      }),
    ];
  },
});

export default SlashCommand;
