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
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error(
      "Cannot reach montage API (Failed to fetch). Use http://localhost:3000 with `docker compose up -d` — not :5173."
    );
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

/** Quick check that /montage is proxied to a live API. */
export async function pingApi(): Promise<boolean> {
  try {
    const res = await fetch("/montage/create", { method: "OPTIONS" });
    // Any response from the proxy means the frontend server is up; 405/422 also fine.
    return res.status > 0;
  } catch {
    return false;
  }
}
