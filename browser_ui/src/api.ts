/** Read-only browser API client. Token is supplied at runtime, never persisted. */
export type Health = { status: string; mode: string };
export type Symbols = { symbols: string[] };

export async function getReadOnly<T>(path: string, token: string): Promise<T> {
  if (!path.startsWith("/api/v1/") || path.includes("..")) {
    throw new Error("Unsupported API path");
  }
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
