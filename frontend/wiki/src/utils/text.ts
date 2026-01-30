import { Node as ProseMirrorNode } from "@tiptap/core";

export type HeadingItem = {
  id: string;
  level: number;
  text: string;
  pos: number;
};

export type HeadingNodeInfo = HeadingItem & {
  node: ProseMirrorNode;
};

export type HeadingInput = {
  text: string;
  currentId?: string;
};

export type HeadingAssignment = {
  base: string;
  id: string;
  needsUpdate: boolean;
};

const HEADING_ID_RE = /^(.*?)(?:-(\d+))?$/;

export function slugifyHeading(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)+/g, "")
    .slice(0, 60);
}

export function parseHeadingId(id?: string): { base: string; index: number } | null {
  if (!id) {
    return null;
  }
  const match = HEADING_ID_RE.exec(id);
  if (!match) {
    return null;
  }
  const base = match[1] || "heading";
  const index = match[2] ? Number.parseInt(match[2], 10) : 1;
  return { base, index };
}

export function assignHeadingIds(headings: HeadingInput[]): HeadingAssignment[] {
  const counters: Record<string, number> = {};
  const metas = headings.map((heading) => {
    const base = slugifyHeading(heading.text) || "heading";
    const parsed = parseHeadingId(heading.currentId);
    if (parsed && parsed.base === base) {
      counters[base] = Math.max(counters[base] ?? 0, parsed.index);
      return { base, hasValidId: true };
    }
    return { base, hasValidId: false };
  });

  return metas.map((meta, index) => {
    if (meta.hasValidId) {
      return { base: meta.base, id: headings[index].currentId || meta.base, needsUpdate: false };
    }
    const nextIndex = (counters[meta.base] ?? 0) + 1;
    counters[meta.base] = nextIndex;
    const id = nextIndex === 1 ? meta.base : `${meta.base}-${nextIndex}`;
    return { base: meta.base, id, needsUpdate: true };
  });
}

export function gatherHeadingNodes(doc: ProseMirrorNode): HeadingNodeInfo[] {
  const headings: HeadingNodeInfo[] = [];
  doc.descendants((node, pos) => {
    if (node.type.name !== "heading") {
      return;
    }
    const text = node.textContent.trim();
    if (!text) {
      return;
    }
    const base = slugifyHeading(text) || "heading";
    const id = node.attrs.id || base;
    headings.push({ node, pos, id, level: node.attrs.level, text });
  });
  return headings;
}

export function collectHeadings(doc: ProseMirrorNode): HeadingItem[] {
  return gatherHeadingNodes(doc).map(({ id, level, text, pos }) => ({ id, level, text, pos }));
}

export function parseInternalLink(input: string): { query: string; fragment: string } {
  const trimmed = input.replace(/^\[\[/, "");
  const [query, fragment = ""] = trimmed.split("#");
  return { query, fragment };
}
