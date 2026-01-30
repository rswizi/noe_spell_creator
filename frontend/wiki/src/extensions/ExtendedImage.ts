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
    return [
      "figure",
      {
        class: `image-node image-node--${alignment}`,
      },
      [
        "img",
        mergeAttributes(this.options.HTMLAttributes, {
          ...attrs,
          width: width || null,
          height: height || null,
        }),
      ],
      caption ? ["figcaption", { class: "image-caption" }, caption] : [],
    ];
  },
});

export default ExtendedImage;
