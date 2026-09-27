export type DataStateKind = "loading" | "ready" | "empty" | "error";

export function renderDataState(
  element: HTMLElement,
  kind: DataStateKind,
  message: string,
  onRetry?: () => void,
): void {
  element.replaceChildren();
  element.classList.toggle("is-visible", kind !== "ready");
  element.classList.toggle("is-error", kind === "error");
  element.dataset.state = kind;

  const text = document.createElement("span");
  text.textContent = message;
  element.append(text);

  if (kind === "error" && onRetry) {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", onRetry);
    element.append(retry);
  }
}
