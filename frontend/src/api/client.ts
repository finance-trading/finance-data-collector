export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(`API request returned ${status}`);
    this.name = "ApiError";
  }
}

export async function apiGet<T>(
  path: string,
  params: URLSearchParams = new URLSearchParams(),
  signal?: AbortSignal,
): Promise<T> {
  const query = params.size ? `?${params.toString()}` : "";
  const response = await fetch(`${path}${query}`, {signal});
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T>(
  path: string,
  init?: { body?: unknown; signal?: AbortSignal },
): Promise<T> {
  const hasBody = init?.body !== undefined;
  const response = await fetch(path, {
    method: "POST",
    signal: init?.signal,
    headers: hasBody ? {"Content-Type": "application/json"} : {},
    body: hasBody ? JSON.stringify(init.body) : undefined,
  });
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}
