import { describe, expect, it } from "vitest";
import { assignHeadingIds, parseInternalLink } from "./text";

describe("assignHeadingIds", () => {
  it("assigns incremental suffixes for duplicate headings", () => {
    const assignments = assignHeadingIds([
      { text: "Intro" },
      { text: "Intro" },
      { text: "Intro" },
    ]);
    expect(assignments.map((item) => item.id)).toEqual(["intro", "intro-2", "intro-3"]);
  });

  it("renames a heading when the text changes", () => {
    const assignments = assignHeadingIds([{ text: "Summary", currentId: "intro" }]);
    expect(assignments[0].id).toBe("summary");
    expect(assignments[0].needsUpdate).toBe(true);
  });

  it("keeps existing IDs when a new heading is inserted above", () => {
    const assignments = assignHeadingIds([
      { text: "Intro" },
      { text: "Intro", currentId: "intro" },
    ]);
    expect(assignments[0].id).toBe("intro-2");
    expect(assignments[1].id).toBe("intro");
    expect(assignments[1].needsUpdate).toBe(false);
  });
});

describe("parseInternalLink", () => {
  it("splits query and fragment correctly", () => {
    const result = parseInternalLink("[[Page Title#Section 2]]");
    expect(result).toEqual({ query: "Page Title", fragment: "Section 2" });
  });
});
