(() => {
  "use strict";

  const API_URL = "/api/v1/companies";
  const form = document.querySelector("#company-search-form");
  const input = document.querySelector("#company-search");
  const directory = document.querySelector("#company-directory tbody");
  const state = document.querySelector("#directory-state");
  const companyTotal = document.querySelector("#company-total");
  const filingTotal = document.querySelector("#filing-total");

  let companies = [];
  let filteredCompanies = [];
  let loadFailed = false;

  const normalize = value => value.trim().toLocaleLowerCase();

  const formatDate = value => {
    if (!value) return "No filing date";
    return new Intl.DateTimeFormat("en", {
      month: "short",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(`${value}T00:00:00Z`));
  };

  const statusLabel = status => ({
    success: "Parsed",
    failed: "Parse failed",
    unavailable: "Unavailable",
    pending: "Pending",
    running: "Parsing",
  })[status] || status || "Unavailable";

  const companyHref = ticker =>
    `company.html?ticker=${encodeURIComponent(ticker)}`;

  const clearDirectory = () => {
    while (directory.firstChild) directory.firstChild.remove();
  };

  const makeCell = (label, className = "") => {
    const cell = document.createElement("td");
    cell.dataset.label = label;
    if (className) cell.className = className;
    return cell;
  };

  const renderCompany = company => {
    const row = document.createElement("tr");

    const companyCell = makeCell("Company", "company-cell");
    const identityLink = document.createElement("a");
    identityLink.className = "company-identity";
    identityLink.href = companyHref(company.ticker);
    const ticker = document.createElement("strong");
    ticker.textContent = company.ticker;
    const name = document.createElement("span");
    name.textContent = company.name;
    identityLink.append(ticker, name);
    companyCell.appendChild(identityLink);

    const dateCell = makeCell("Latest filing", "date-cell");
    dateCell.textContent = formatDate(company.latest_filing_date);

    const statusCell = makeCell("Parse status");
    const badge = document.createElement("span");
    badge.className = `parse-status status-${company.latest_filing_status || "unavailable"}`;
    badge.textContent = statusLabel(company.latest_filing_status);
    statusCell.appendChild(badge);

    const countCell = makeCell("Filings", "number-column");
    countCell.textContent = new Intl.NumberFormat("en").format(company.filing_count);

    const actionCell = makeCell("Action", "action-cell");
    const action = document.createElement("a");
    action.href = companyHref(company.ticker);
    action.setAttribute("aria-label", `Open ${company.ticker} research`);
    action.textContent = "Open";
    actionCell.appendChild(action);

    row.append(companyCell, dateCell, statusCell, countCell, actionCell);
    directory.appendChild(row);
  };

  const render = query => {
    const needle = normalize(query);
    filteredCompanies = needle
      ? companies.filter(company =>
          normalize(company.ticker).includes(needle) ||
          normalize(company.name).includes(needle))
      : companies;

    clearDirectory();
    filteredCompanies.forEach(renderCompany);

    if (loadFailed) return;
    if (!filteredCompanies.length) {
      state.textContent = `No companies match “${query.trim()}”. Try a ticker or another company name.`;
      state.classList.add("is-visible");
      return;
    }

    state.textContent = needle
      ? `${filteredCompanies.length} ${filteredCompanies.length === 1 ? "company" : "companies"} match “${query.trim()}”.`
      : `${companies.length} companies are available for research.`;
    state.classList.toggle("is-visible", Boolean(needle));
  };

  const loadCompanies = async () => {
    state.textContent = "Reading the filing index…";
    state.classList.add("is-visible");
    try {
      const response = await fetch(API_URL);
      if (!response.ok) throw new Error(`Directory request returned ${response.status}`);
      const payload = await response.json();
      companies = payload.companies || [];
      companyTotal.textContent = new Intl.NumberFormat("en").format(payload.total || 0);
      filingTotal.textContent = new Intl.NumberFormat("en").format(
        companies.reduce((total, company) => total + company.filing_count, 0),
      );
      render(input.value);
    } catch (error) {
      loadFailed = true;
      clearDirectory();
      companyTotal.textContent = "—";
      filingTotal.textContent = "—";
      state.textContent = "The company directory could not be loaded. Check that the read service is running, then reload this page.";
      state.classList.add("is-visible", "is-error");
      console.error(error);
    }
  };

  input.addEventListener("input", () => render(input.value));

  form.addEventListener("submit", event => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) {
      input.focus();
      state.textContent = "Enter a ticker or company name to open its research workspace.";
      state.classList.add("is-visible");
      return;
    }

    const exactTicker = companies.find(
      company => normalize(company.ticker) === normalize(query),
    );
    const company = exactTicker || filteredCompanies[0];
    if (!company) {
      render(query);
      return;
    }
    window.location.assign(companyHref(company.ticker));
  });

  loadCompanies();
})();
