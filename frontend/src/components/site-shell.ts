export function markCurrentNav(pathname: string): void {
  document.querySelectorAll<HTMLAnchorElement>("[data-nav]").forEach((anchor) => {
    const current = new URL(anchor.href).pathname === pathname;
    if (current) anchor.setAttribute("aria-current", "page");
    else anchor.removeAttribute("aria-current");
  });
}
