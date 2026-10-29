async function readDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
    if (body.detail != null) return JSON.stringify(body.detail);
  } catch {
    return res.statusText;
  }
  return res.statusText;
}

export async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}
