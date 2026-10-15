/** Read-only browser API client. Token is supplied at runtime, never persisted. */
export type Health = { status: string; mode: string };
export type Symbols = { symbols: string[] };

export async function getReadOnly<T>(path: string, token: string): Promise<T> {
  if (!/^\/api\/v1\/(?:health|capabilities|catalog\/symbols|catalog\/coverage|runs\/[A-Za-z0-9_-]{1,100}|configs\/[A-Za-z0-9_-]{1,100})(?:\?[A-Za-z0-9_=&%.-]*)?$/.test(path)) {
    throw new Error("Unsupported API path");
  }
  if (!token || /[\r\n]/.test(token)) throw new Error("Invalid local session token");
  const response = await fetch(path, {
    method: "GET",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  });
  if (!response.ok) throw new Error(`Local API returned HTTP ${response.status}`);
  return response.json() as Promise<T>;
}
