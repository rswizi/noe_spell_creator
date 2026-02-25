import Image from "@tiptap/extension-image";
import { mergeAttributes } from "@tiptap/core";

const ExtendedImage = Image.extend({
  name: "extendedImage",
  addAttributes() {
    return {
      ...this.parent?.(),
      assetId: {
        default: null,
      },
      caption: {
        default: "",
      },
      alignment: {
        default: "center",
      },
      width: {
        default: null,
      },
      height: {
        default: null,
      },
    };
  },
  parseHTML() {
    return [{ tag: "figure.image-node" }];
  },
  renderHTML({ HTMLAttributes }) {
    const { caption, alignment, width, height, ...attrs } = HTMLAttributes;
    const toCssSize = (value: any): string => {
      if (value === null || value === undefined || value === "") {
        return "";
      }
      const raw = String(value).trim();
      if (!raw) {
        return "";
      }
      if (/^\d+(\.\d+)?$/.test(raw)) {
        return `${raw}px`;
      }
      return raw;
    };
    const styleParts: string[] = [];
    if (attrs.style) {
      styleParts.push(String(attrs.style));
    }
    const cssWidth = toCssSize(width);
    const cssHeight = toCssSize(height);
    if (cssWidth) {
      styleParts.push(`width:${cssWidth}`);
    }
    if (cssHeight) {
      styleParts.push(`height:${cssHeight}`);
    } else {
      styleParts.push("height:auto");
    }
    const content: any[] = [
      [
        "img",
        mergeAttributes(this.options.HTMLAttributes, {
          ...attrs,
          style: styleParts.join(";"),
        }),
      ],
    ];
    content.push(["span", { class: "image-resize-handle image-resize-handle--right", "data-handle": "right" }]);
    content.push(["span", { class: "image-resize-handle image-resize-handle--bottom", "data-handle": "bottom" }]);
    content.push(["span", { class: "image-resize-handle image-resize-handle--corner", "data-handle": "corner" }]);
    if (caption) {
      content.push(["figcaption", { class: "image-caption" }, caption]);
    }
    return [
      "figure",
      {
        class: `image-node image-node--${alignment}`,
      },
      ...content,
    ];
  },
});

export default ExtendedImage;
