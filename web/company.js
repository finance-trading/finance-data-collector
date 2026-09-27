(() => {
  "use strict";

  const API_COMPANIES = "/api/v1/companies/";
  const FILINGS_SUFFIX = "/filings";
  const API_FILINGS = "/api/v1/filings/";
  const STATEMENTS_SUFFIX = "/statements?statement_type=";
  const FACTS_SUFFIX = "/facts";
  const SECTION_SUFFIX = "/sections/";
  const TABLES_SUFFIX = "/tables";
  const EVIDENCE_SUFFIX = "/evidence/";

  const STATE_LABELS = {
    not_found: "Not found",
    unavailable: "Unavailable",
    unsupported: "Unsupported",
    failed: "Parse failed",
  };

  const statementRequests = [
    { type: "IncomeStatement", panelId: "income-statement" },
    { type: "BalanceSheet", panelId: "balance-sheet" },
    { type: "CashFlowStatement", panelId: "cash-flow" },
  ];

  const pageState = {
    ticker: "",
    filings: [],
    selectedAccession: "",
    requestSequence: 0,
  };

  class ApiError extends Error {
    constructor(response, payload) {
      const detail = payload && payload.detail ? payload.detail : {};
      super(detail.message || `Request failed with status ${response.status}`);
      this.name = "ApiError";
      this.statusCode = response.status;
      this.state = detail.status || "unavailable";
      this.diagnostics = detail.diagnostics || {};
    }
  }

  const byId = (id) => document.getElementById(id);

  function textElement(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value == null || value === "" ? "—" : String(value);
    return node;
  }

  function replaceChildren(target, ...children) {
    target.replaceChildren(...children);
    return target;
  }

  function formatDate(value) {
    if (!value) return "—";
    const parsed = new Date(`${value}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(parsed);
  }

  function displayState(status) {
    const normalized = String(status || "unavailable").toLowerCase();
    if (normalized === "not_found") return STATE_LABELS.not_found;
    if (normalized === "failed") return STATE_LABELS.failed;
    if (normalized === "unsupported") return STATE_LABELS.unsupported;
    if (normalized === "success" || normalized === "parsed") return "Parsed";
    return STATE_LABELS.unavailable;
  }

  function stateClass(status) {
    const normalized = String(status || "unavailable").toLowerCase();
    if (normalized === "not_found") return "not-found";
    if (normalized === "failed") return "failed";
    if (normalized === "unsupported") return "unsupported";
    if (normalized === "success" || normalized === "parsed") return "success";
    return "unavailable";
  }

  function statusMessage(error, context) {
    if (error instanceof ApiError) {
      const label = displayState(error.state);
      return {
        label,
        className: stateClass(error.state),
        text: `${label}: ${error.message}`,
      };
    }
    return {
      label: STATE_LABELS.unavailable,
      className: "unavailable",
      text: `${STATE_LABELS.unavailable}: ${context} could not be loaded.`,
    };
  }

  function stateNode(message, className = "") {
    const node = textElement("p", `state-message ${className}`.trim(), message);
    node.setAttribute("role", className === "failed" ? "alert" : "status");
    return node;
  }

  async function apiGet(path) {
    const response = await fetch(path, {
      headers: { Accept: "application/json" },
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    if (!response.ok) throw new ApiError(response, payload);
    return payload;
  }

  function setCompanyFailure(error) {
    const message = statusMessage(error, "Company record");
    byId("company-name").textContent = "Company unavailable";
    byId("company-identity").textContent = message.text;
    const status = byId("company-status");
    status.textContent = message.label;
    status.className = `status status-${message.className}`;
    replaceChildren(byId("filings"), stateNode(message.text, message.className));
  }

  function renderCompany(company) {
    document.title = `${company.ticker} filings | Finance Data Collector`;
    byId("company-name").textContent = company.name;
    byId("company-identity").textContent = [
      company.ticker,
      `CIK ${company.cik}`,
      company.sic ? `SIC ${company.sic}` : "SIC unavailable",
    ].join("  /  ");
    byId("filing-count").textContent = `${company.filing_count} filings`;
    const status = byId("company-status");
    const label = displayState(company.latest_filing_status);
    status.textContent = label;
    status.className = `status status-${stateClass(company.latest_filing_status)}`;
  }

  function filingButton(filing) {
    const button = document.createElement("button");
    button.className = "filing-choice";
    button.type = "button";
    button.dataset.accession = filing.accession;
    button.setAttribute(
      "aria-label",
      `${filing.form} filed ${formatDate(filing.filing_date)}, ${displayState(filing.status)}`,
    );
    if (filing.accession === pageState.selectedAccession) {
      button.setAttribute("aria-current", "true");
    }

    button.append(
      textElement("span", "filing-form", filing.form),
      textElement("span", `filing-state ${stateClass(filing.status)}`, displayState(filing.status)),
      textElement("span", "filing-date", formatDate(filing.filing_date)),
      textElement("span", "filing-accession", filing.accession),
    );
    button.addEventListener("click", () => selectFiling(filing));
    return button;
  }

  function renderFilings(filings) {
    pageState.filings = filings;
    const navigation = byId("filings");
    if (!filings.length) {
      replaceChildren(
        navigation,
        stateNode(`${STATE_LABELS.unavailable}: no filings match this filter.`, "unavailable"),
      );
      return;
    }
    replaceChildren(navigation, ...filings.map(filingButton));
  }

  function updateSelectedSummary(filing) {
    byId("filing-kicker").textContent = `${filing.form} filing`;
    byId("filing-title").textContent =
      filing.report_date ? `Period ended ${formatDate(filing.report_date)}` : "Filing details";
    byId("selected-accession").textContent = filing.accession;
    byId("selected-filing-date").textContent = formatDate(filing.filing_date);
    byId("selected-report-date").textContent = formatDate(filing.report_date);
    byId("selected-status").textContent = displayState(filing.status);
    renderFilings(pageState.filings);
  }

  function updateFilingDetail(detail) {
    byId("filing-kicker").textContent = `${detail.form}${detail.is_amended ? "/A" : ""} filing`;
    byId("filing-title").textContent = detail.report_date
      ? `Period ended ${formatDate(detail.report_date)}`
      : "Filing details";
    byId("selected-filing-date").textContent = formatDate(detail.filing_date);
    byId("selected-report-date").textContent = formatDate(detail.report_date);
    byId("selected-status").textContent = displayState(detail.parse.status);

    const sourceLink = byId("sec-filing-link");
    if (detail.sec_url) {
      sourceLink.href = detail.sec_url;
      sourceLink.classList.remove("is-hidden");
    } else {
      sourceLink.classList.add("is-hidden");
      sourceLink.removeAttribute("href");
    }
  }

  function evidenceButton(evidence, label = "View evidence") {
    const button = textElement("button", "evidence-button", label);
    button.type = "button";
    if (!evidence || !evidence.evidence_id) {
      button.disabled = true;
      button.textContent = STATE_LABELS.unavailable;
      return button;
    }
    button.addEventListener("click", () => openEvidence(evidence));
    return button;
  }

  function evidenceDefinition(term, value) {
    const wrapper = document.createElement("div");
    wrapper.append(
      textElement("dt", "", term),
      textElement("dd", "", value || STATE_LABELS.unavailable),
    );
    return wrapper;
  }

  function renderEvidence(evidence) {
    const record = document.createElement("article");
    record.className = "evidence-record";
    record.append(
      textElement("h3", "", evidence.locator_value || "Filing source"),
      textElement("p", "filing-accession", evidence.accession),
    );

    const details = document.createElement("dl");
    details.append(
      evidenceDefinition("Locator type", evidence.locator_type),
      evidenceDefinition("Artifact", evidence.relative_path),
      evidenceDefinition("Content SHA-256", evidence.content_sha256),
    );
    record.append(details);

    if (evidence.excerpt) {
      record.append(textElement("blockquote", "evidence-excerpt", evidence.excerpt));
    } else {
      record.append(stateNode(`${STATE_LABELS.unavailable}: no excerpt was stored.`, "unavailable"));
    }

    if (evidence.accession_url) {
      const link = textElement("a", "source-link", "Open exact SEC source");
      link.href = evidence.accession_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      record.append(link);
    }
    replaceChildren(byId("evidence-content"), record);
  }

  async function openEvidence(embeddedEvidence) {
    const requestSequence = pageState.requestSequence;
    const selectionIsCurrent = () => (
      requestSequence === pageState.requestSequence
      && pageState.selectedAccession === embeddedEvidence.accession
    );
    renderEvidence(embeddedEvidence);
    byId("evidence").scrollIntoView({ behavior: "smooth", block: "start" });
    const accession = encodeURIComponent(embeddedEvidence.accession);
    const evidenceId = encodeURIComponent(embeddedEvidence.evidence_id);
    try {
      const evidence = await apiGet(
        `${API_FILINGS}${accession}${EVIDENCE_SUFFIX}${evidenceId}`,
      );
      if (selectionIsCurrent()) {
        renderEvidence(evidence);
      }
    } catch (error) {
      if (!selectionIsCurrent()) return;
      const message = statusMessage(error, "Evidence");
      replaceChildren(
        byId("evidence-content"),
        stateNode(message.text, message.className),
      );
    }
  }

  function reportedValue(item) {
    const value = item.value_numeric ?? item.value_text;
    if (value == null || value === "") return STATE_LABELS.unavailable;
    return item.unit ? `${value} ${item.unit}` : String(value);
  }

  function renderFacts(result) {
    const chart = byId("fact-chart");
    const facts = result.facts || [];
    if (!facts.length) {
      replaceChildren(
        chart,
        stateNode(`${STATE_LABELS.unavailable}: no facts were returned.`, "unavailable"),
      );
      return;
    }

    const visible = facts.slice(0, 8);
    const magnitudes = visible.map((fact) => Math.abs(Number(fact.value_numeric)) || 0);
    const maximum = Math.max(...magnitudes, 1);
    const rows = visible.map((fact, index) => {
      const row = document.createElement("div");
      row.className = "fact-row";
      const label = fact.label || fact.concept;
      const period = [formatDate(fact.end_date), fact.period_type]
        .filter((part) => part && part !== "—")
        .join(" / ");
      const track = document.createElement("span");
      track.className = "period-track";
      track.setAttribute("aria-hidden", "true");
      const bar = document.createElement("span");
      bar.className = "period-bar";
      bar.style.width = `${Math.max(3, (magnitudes[index] / maximum) * 100)}%`;
      track.append(bar);
      row.append(
        textElement("span", "fact-label", label),
        track,
        textElement("span", "fact-period", period || STATE_LABELS.unavailable),
        textElement("span", "fact-value", reportedValue(fact)),
        evidenceButton(fact.evidence, "Source"),
      );
      return row;
    });
    replaceChildren(chart, ...rows);
  }

  function renderFactsError(error) {
    const message = statusMessage(error, "Reported facts");
    replaceChildren(
      byId("fact-chart"),
      stateNode(message.text, message.className),
    );
  }

  function statementStateRow(message, className) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.append(stateNode(message, className));
    row.append(cell);
    return row;
  }

  function renderStatement(panelId, result) {
    const body = byId(panelId).querySelector("tbody");
    const lines = result.lines || [];
    if (!lines.length) {
      replaceChildren(
        body,
        statementStateRow(
          `${STATE_LABELS.unavailable}: no statement lines were returned.`,
          "unavailable",
        ),
      );
      return;
    }

    const rows = lines.map((line) => {
      const row = document.createElement("tr");
      const labelCell = document.createElement("td");
      const label = textElement("span", "line-label", line.label || line.concept);
      label.style.setProperty("--depth", String(Math.min(Math.max(line.depth || 0, 0), 6)));
      const period = [formatDate(line.end_date), line.period_type]
        .filter((part) => part && part !== "—")
        .join(" / ");
      labelCell.append(
        label,
        textElement(
          "span",
          "line-period-mobile",
          `Period: ${period || STATE_LABELS.unavailable}`,
        ),
      );
      const evidenceCell = document.createElement("td");
      evidenceCell.append(evidenceButton(line.evidence, "Source"));
      row.append(
        labelCell,
        textElement("td", "", period || STATE_LABELS.unavailable),
        textElement("td", "", reportedValue(line)),
        evidenceCell,
      );
      return row;
    });
    replaceChildren(body, ...rows);
  }

  function renderStatementError(panelId, error) {
    const message = statusMessage(error, "Statement");
    const body = byId(panelId).querySelector("tbody");
    replaceChildren(body, statementStateRow(message.text, message.className));
  }

  function renderSection(section) {
    const article = byId("section-result");
    const heading = textElement("h4", "", section.heading || "Management discussion");
    heading.id = "section-title";
    const copy = textElement(
      "p",
      "disclosure-copy",
      section.text || `${STATE_LABELS.unavailable}: section text is empty.`,
    );
    article.replaceChildren(heading, copy, evidenceButton(section.evidence, "View section source"));
  }

  function renderSectionError(error) {
    const message = statusMessage(error, "Management discussion");
    const article = byId("section-result");
    const heading = textElement("h4", "", "Management discussion");
    heading.id = "section-title";
    article.replaceChildren(heading, stateNode(message.text, message.className));
  }

  function tableDescription(table) {
    const rows = Array.isArray(table.rows) ? table.rows.length : 0;
    const columns = Array.isArray(table.columns) ? table.columns.length : 0;
    const confidence = table.confidence == null ? "confidence unavailable" :
      `confidence ${table.confidence}`;
    return `${rows} rows, ${columns} columns, ${confidence}`;
  }

  function renderTables(result) {
    const article = byId("table-result");
    const heading = textElement("h4", "", "Extracted tables");
    heading.id = "table-title";
    const tables = result.tables || [];
    if (!tables.length) {
      article.replaceChildren(
        heading,
        stateNode(`${STATE_LABELS.unavailable}: no tables were returned.`, "unavailable"),
      );
      return;
    }
    const list = document.createElement("div");
    for (const table of tables) {
      const entry = document.createElement("section");
      entry.append(
        textElement("h4", "", table.caption || table.table_type),
        textElement("p", "table-summary", tableDescription(table)),
        evidenceButton(table.evidence, "View table source"),
      );
      list.append(entry);
    }
    article.replaceChildren(heading, list);
  }

  function renderTablesError(error) {
    const message = statusMessage(error, "Extracted tables");
    const article = byId("table-result");
    const heading = textElement("h4", "", "Extracted tables");
    heading.id = "table-title";
    article.replaceChildren(heading, stateNode(message.text, message.className));
  }

  function resetWorkspaceLoading() {
    replaceChildren(byId("fact-chart"), stateNode("Loading reported facts…"));
    for (const request of statementRequests) {
      const body = byId(request.panelId).querySelector("tbody");
      replaceChildren(body, statementStateRow("Loading statement…", ""));
    }
    const section = byId("section-result");
    const sectionHeading = textElement("h4", "", "Management discussion");
    sectionHeading.id = "section-title";
    section.replaceChildren(sectionHeading, stateNode("Loading section…"));
    const table = byId("table-result");
    const tableHeading = textElement("h4", "", "Extracted tables");
    tableHeading.id = "table-title";
    table.replaceChildren(tableHeading, stateNode("Loading tables…"));
    replaceChildren(
      byId("evidence-content"),
      textElement(
        "p",
        "evidence-empty",
        "Choose a source link beside a reported value to inspect its exact filing locator, excerpt, and content hash.",
      ),
    );
  }

  async function selectFiling(filing) {
    pageState.selectedAccession = filing.accession;
    const sequence = ++pageState.requestSequence;
    updateSelectedSummary(filing);
    resetWorkspaceLoading();
    const accession = encodeURIComponent(filing.accession);
    const base = `${API_FILINGS}${accession}`;

    const detailPromise = apiGet(base);
    const factsPromise = apiGet(`${base}${FACTS_SUFFIX}`);
    const sectionPromise = apiGet(`${base}${SECTION_SUFFIX}md_and_a`);
    const tablesPromise = apiGet(`${base}${TABLES_SUFFIX}`);
    const statements = statementRequests.map((request) => ({
      ...request,
      promise: apiGet(
        `${base}${STATEMENTS_SUFFIX}${encodeURIComponent(request.type)}`,
      ),
    }));

    const settled = await Promise.allSettled([
      detailPromise,
      factsPromise,
      sectionPromise,
      tablesPromise,
      ...statements.map((request) => request.promise),
    ]);
    if (sequence !== pageState.requestSequence) return;

    const [detail, facts, section, tables, ...statementResults] = settled;
    if (detail.status === "fulfilled") updateFilingDetail(detail.value);
    else {
      const message = statusMessage(detail.reason, "Filing details");
      byId("selected-status").textContent = message.label;
      byId("sec-filing-link").classList.add("is-hidden");
    }

    if (facts.status === "fulfilled") renderFacts(facts.value);
    else renderFactsError(facts.reason);
    if (section.status === "fulfilled") renderSection(section.value);
    else renderSectionError(section.reason);
    if (tables.status === "fulfilled") renderTables(tables.value);
    else renderTablesError(tables.reason);

    statementResults.forEach((result, index) => {
      const request = statements[index];
      if (result.status === "fulfilled") renderStatement(request.panelId, result.value);
      else renderStatementError(request.panelId, result.reason);
    });
  }

  async function loadFilings(form = "") {
    const ticker = encodeURIComponent(pageState.ticker);
    const query = form ? `?form=${encodeURIComponent(form)}` : "";
    try {
      const result = await apiGet(`${API_COMPANIES}${ticker}${FILINGS_SUFFIX}${query}`);
      renderFilings(result.filings || []);
      if (result.filings && result.filings.length) {
        const current = result.filings.find(
          (filing) => filing.accession === pageState.selectedAccession,
        );
        await selectFiling(current || result.filings[0]);
      }
    } catch (error) {
      const message = statusMessage(error, "Filings");
      replaceChildren(
        byId("filings"),
        stateNode(message.text, message.className),
      );
    }
  }

  function activateTab(tab) {
    const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
    for (const candidate of tabs) {
      const selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      byId(candidate.dataset.panel).hidden = !selected;
    }
    tab.focus();
  }

  function initializeTabs() {
    const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => activateTab(tab));
      tab.addEventListener("keydown", (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        let target = index;
        if (event.key === "ArrowLeft") target = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
        if (event.key === "Home") target = 0;
        if (event.key === "End") target = tabs.length - 1;
        activateTab(tabs[target]);
      });
    });
  }

  async function initializePage() {
    initializeTabs();
    const ticker = new URLSearchParams(window.location.search).get("ticker");
    if (!ticker || !/^[A-Za-z0-9.-]{1,10}$/.test(ticker)) {
      setCompanyFailure(
        new ApiError(
          { status: 400 },
          { detail: { status: "unavailable", message: "Add a valid ticker query parameter." } },
        ),
      );
      return;
    }

    pageState.ticker = ticker.toUpperCase();
    byId("form-filter").addEventListener("change", (event) => {
      loadFilings(event.target.value);
    });

    try {
      const company = await apiGet(
        `${API_COMPANIES}${encodeURIComponent(pageState.ticker)}`,
      );
      renderCompany(company);
      await loadFilings();
    } catch (error) {
      setCompanyFailure(error);
    }
  }

  initializePage();
})();
