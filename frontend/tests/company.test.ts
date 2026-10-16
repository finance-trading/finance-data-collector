import { beforeEach, describe, expect, it } from "vitest";

import {
  companyStatusLabel,
  createCompanyState,
  disclosureBody,
  initializeFullTextModal,
  readTicker,
} from "../src/pages/company";
import { markCurrentNav } from "../src/components/site-shell";

describe("company research state", () => {
  it("normalizes the ticker from the query string", () => {
    expect(readTicker(new URL("http://test/company.html?ticker=nvda"))).toBe("NVDA");
    expect(readTicker(new URL("http://test/company.html?ticker=%3Cscript%3E"))).toBeNull();
  });

  it("does not let stale evidence replace a newer filing", () => {
    const state = createCompanyState();
    state.selectFiling("old-accession");
    const stale = state.beginEvidence("old-accession");
    state.selectFiling("new-accession");

    expect(state.acceptEvidence(stale)).toBe(false);
    expect(state.acceptEvidence(state.beginEvidence("new-accession"))).toBe(true);
  });

  it("maps HTTP failures to explicit labels", () => {
    expect(companyStatusLabel(404)).toBe("Not found");
    expect(companyStatusLabel(409)).toBe("Unavailable");
    expect(companyStatusLabel(422)).toBe("Parse failed");
  });
});

const LONG_PROSE = "Net revenue was $30 billion for the year, an increase of $6 billion or 25 percent from the prior year.\n\n".repeat(30);

describe("disclosure full text", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="host"></div>
      <div id="full-text" class="full-text-modal" role="dialog" aria-hidden="true">
        <div class="full-text-header">
          <h3 id="full-text-title">Full text</h3>
          <button id="full-text-close" type="button">Close</button>
        </div>
        <article id="full-text-body"></article>
      </div>
    `;
    initializeFullTextModal();
  });

  it("keeps short prose inline without a full-text trigger", () => {
    const host = document.querySelector<HTMLElement>("#host")!;
    host.append(disclosureBody("Net revenue was $30 billion.", "Management discussion"));

    const copy = host.querySelector<HTMLElement>(".disclosure-copy")!;
    expect(copy.classList.contains("is-truncated")).toBe(false);
    expect(host.querySelector(".expand-text")).toBeNull();
    expect(copy.textContent).toBe("Net revenue was $30 billion.");
  });

  it("truncates long prose but keeps the full text reachable in the modal", () => {
    const host = document.querySelector<HTMLElement>("#host")!;
    host.append(disclosureBody(LONG_PROSE, "Management discussion"));

    const copy = host.querySelector<HTMLElement>(".disclosure-copy")!;
    expect(copy.classList.contains("is-truncated")).toBe(true);
    // The display is a short word-boundary cut; the parsed text is stashed
    // off-DOM so the trigger's own label cannot pollute it.
    expect(copy.textContent.length).toBeLessThan(LONG_PROSE.length / 2);
    expect(copy.getAttribute("data-full-text")).toBe(LONG_PROSE);

    host.querySelector<HTMLElement>(".expand-text")!.dispatchEvent(new Event("click"));
    const modal = document.querySelector<HTMLElement>("#full-text")!;
    expect(modal.classList.contains("is-open")).toBe(true);
    expect(modal.getAttribute("aria-hidden")).toBe("false");
    expect(modal.querySelector<HTMLElement>("#full-text-body")!.textContent).toBe(LONG_PROSE);
  });

  it("cuts the excerpt at a word boundary, not mid-token", () => {
    const host = document.querySelector<HTMLElement>("#host")!;
    host.append(disclosureBody(`alpha ${"word ".repeat(200)}`, "Management discussion"));

    // textContent = "alpha word …" + button label; the prose part ends on a
    // space + ellipsis, so the last whole word before the cut is intact.
    const copy = host.querySelector<HTMLElement>(".disclosure-copy")!;
    const shown = copy.textContent.replace(copy.querySelector(".expand-text")!.textContent ?? "", "");
    // Ends on the ellipsis; the cut sat on a word boundary, so the prose
    // part is "alpha" plus a whole number of complete "word"s.
    expect(shown.endsWith("…")).toBe(true);
    expect(shown.slice(0, -1)).toMatch(/^alpha( word)*$/);
  });

  it("clears the modal on close and lets Escape and backdrop clicks close it", () => {
    const host = document.querySelector<HTMLElement>("#host")!;
    host.append(disclosureBody(LONG_PROSE, "Management discussion"));
    const modal = document.querySelector<HTMLElement>("#full-text")!;
    const trigger = () => host.querySelector<HTMLElement>(".expand-text")!;
    const open = () => trigger().dispatchEvent(new Event("click"));

    open();
    document.querySelector<HTMLElement>("#full-text-close")!.dispatchEvent(new Event("click"));
    expect(modal.classList.contains("is-open")).toBe(false);
    expect(modal.getAttribute("aria-hidden")).toBe("true");
    expect(modal.querySelector<HTMLElement>("#full-text-body")!.textContent).toBe("");

    open();
    document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"}));
    expect(modal.classList.contains("is-open")).toBe(false);

    open();
    modal.dispatchEvent(new Event("click"));
    expect(modal.classList.contains("is-open")).toBe(false);
  });
});

describe("site shell", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <nav>
        <a data-nav href="http://test/index.html">AI companies</a>
        <a data-nav href="http://test/graph.html">Company graph</a>
      </nav>
    `;
  });

  it("marks only the current navigation destination", () => {
    markCurrentNav("/graph.html");

    expect(document.querySelector("[href='http://test/graph.html']")?.getAttribute("aria-current"))
      .toBe("page");
    expect(document.querySelector("[href='http://test/index.html']")?.hasAttribute("aria-current"))
      .toBe(false);
  });
});
