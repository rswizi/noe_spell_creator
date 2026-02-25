import Suggestion from "@tiptap/suggestion";
import { Extension } from "@tiptap/core";
import { PluginKey } from "prosemirror-state";
import { parseInternalLink } from "../utils/text";

type SuggestionItem = {
  title: string;
  slug: string;
  fragment: string;
  id: string;
};

const InternalLinkSuggestion = Extension.create({
  name: "internalLinkSuggestion",
  addProseMirrorPlugins() {
    const internalLinkSuggestionKey = new PluginKey("internal-link-suggestion");
    return [
      Suggestion({
        pluginKey: internalLinkSuggestionKey,
        char: "[[",
        startOfLine: false,
        command: ({ editor, range, props }) => {
          const fragmentSuffix = props.fragment ? `#${props.fragment}` : "";
          const href = `/wiki/slug/${props.slug}${fragmentSuffix}`;
          editor
            .chain()
            .focus()
            .deleteRange(range)
            .insertContent(props.title)
            .extendMarkRange("link")
            .setLink({
              href,
              pageSlug: props.slug,
              pageId: props.id,
              fragment: props.fragment || undefined,
            })
            .run();
        },
        items: async ({ query }) => {
          const parsed = parseInternalLink(query);
          const search = parsed.query.trim();
          if (!search) {
            return [];
          }
          try {
            const response = await fetch(`/api/wiki/resolve?query=${encodeURIComponent(search)}`);
            if (!response.ok) {
              return [];
            }
            const results = await response.json();
            return (results || []).map((item: any) => ({
              title: item.title,
              slug: item.slug,
              id: item.id,
              fragment: parsed.fragment,
            }));
          } catch {
            return [];
          }
        },
        render: () => {
          let component: HTMLDivElement;

          return {
            onStart: (props) => {
              component = document.createElement("div");
              component.classList.add("slash-menu");
              props.items.forEach((item) => addItem(item, props));
              document.body.appendChild(component);
              setPosition(props);
            },
            onUpdate: (props) => {
              component.innerHTML = "";
              props.items.forEach((item) => addItem(item, props));
              setPosition(props);
            },
            onExit: () => {
              component?.remove();
            },
          };

          function addItem(item: any, props: any) {
            const button = document.createElement("button");
            button.textContent = item.title;
            button.onclick = () => {
              props.command(item);
            };
            component.appendChild(button);
          }

          function setPosition(props: any) {
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

export default InternalLinkSuggestion;
