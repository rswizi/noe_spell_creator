import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "prosemirror-state";
import { collectHeadings, gatherHeadingNodes, assignHeadingIds, HeadingItem } from "../utils/text";

const headingKey = new PluginKey("headingAnchors");

const HeadingAnchors = Extension.create({
  name: "headingAnchors",
  addStorage() {
    return {
      headings: [] as HeadingItem[],
    };
  },
  addProseMirrorPlugins() {
    const writeHeadings = (headings: HeadingItem[]) => {
      const extensionStorage =
        (this.editor?.storage as any)?.headingAnchors || (this.storage as any);
      if (extensionStorage && typeof extensionStorage === "object") {
        extensionStorage.headings = headings;
      }
    };
    return [
      new Plugin({
        key: headingKey,
        state: {
          init: (_, state) => {
            const headings = collectHeadings(state.doc);
            writeHeadings(headings);
            return headings;
          },
          apply: (_, __, ___, newState) => {
            const headings = collectHeadings(newState.doc);
            writeHeadings(headings);
            return headings;
          },
        },
        appendTransaction: (transactions, oldState, newState) => {
          let tr = newState.tr;
          let mutated = false;
          const headingNodes = gatherHeadingNodes(newState.doc);
          const assignments = assignHeadingIds(
            headingNodes.map((heading) => ({ text: heading.text, currentId: heading.id }))
          );
          headingNodes.forEach((heading, index) => {
            const assignment = assignments[index];
            if (!assignment.needsUpdate) {
              return;
            }
            const attrs = heading.node.attrs || {};
            tr = tr.setNodeMarkup(heading.pos, undefined, { ...attrs, id: assignment.id });
            mutated = true;
          });
          return mutated ? tr : undefined;
        },
      }),
    ];
  },
});

export default HeadingAnchors;
