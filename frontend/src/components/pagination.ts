export interface PaginationModel {
  page: number;
  pageSize: number;
  total: number;
}

function pageButton(
  label: string,
  page: number,
  disabled: boolean,
  onPage: (page: number) => void,
): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.disabled = disabled;
  button.addEventListener("click", () => onPage(page));
  return button;
}

export function renderPagination(
  container: HTMLElement,
  model: PaginationModel,
  onPage: (page: number) => void,
): void {
  const pageCount = Math.max(1, Math.ceil(model.total / model.pageSize));
  const page = Math.min(Math.max(1, model.page), pageCount);
  const start = model.total === 0 ? 0 : (page - 1) * model.pageSize + 1;
  const end = Math.min(page * model.pageSize, model.total);

  const summary = document.createElement("span");
  summary.className = "pagination-summary";
  summary.textContent = `${start}–${end} of ${model.total}`;

  container.replaceChildren(
    pageButton("Previous", page - 1, page === 1, onPage),
    summary,
    pageButton("Next", page + 1, page === pageCount || model.total === 0, onPage),
  );
}
