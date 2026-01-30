import { mergeAttributes } from "@tiptap/core";
import Link from "@tiptap/extension-link";

const ExtendedLink = Link.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      pageSlug: {
        default: null,
      },
      pageId: {
        default: null,
      },
      fragment: {
        default: null,
      },
    };
  },
  renderHTML({ HTMLAttributes }) {
    const { pageSlug, pageId, fragment, ...attrs } = HTMLAttributes;
    const dataAttrs: Record<string, string> = {};
    if (pageSlug) {
      dataAttrs["data-wiki-slug"] = pageSlug;
    }
    if (pageId) {
      dataAttrs["data-wiki-page-id"] = pageId;
    }
    if (fragment) {
      dataAttrs["data-wiki-fragment"] = fragment;
    }
    return ["a", mergeAttributes(this.options.HTMLAttributes, { ...attrs, ...dataAttrs }), 0];
  },
});

export default ExtendedLink;
