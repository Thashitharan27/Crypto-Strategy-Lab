/** Read-only browser API client. Token is supplied at runtime, never persisted. */
export type Health = { status: string; mode: string };
export type Symbols = { symbols: string[] };

export async function getReadOnly<T>(path: string, token: string): Promise<T> {
  if (!/^\/api\/v1\/(?:health|capabilities|release\/capabilities|catalog\/symbols|catalog\/coverage|portfolio\/candidates|runs\/[A-Za-z0-9_-]{1,100}|configs\/[A-Za-z0-9_-]{1,100})(?:\?[A-Za-z0-9_=&%.-]*)?$/.test(path)) {
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


/** Explicit user-triggered session creation only; never use for research execution. */
export async function openVerifiedVisualizer(runId: string, token: string): Promise<string> {
  if (!/^[A-Za-z0-9_-]{1,100}$/.test(runId) || !token || /[\r\n]/.test(token)) {
    throw new Error("Invalid run ID or session token");
  }
  const response = await fetch(`/api/v1/visualizer/sessions/${runId}`, {
    method: "POST",
    headers: {Authorization: `Bearer ${token}`},
    credentials: "omit",
    cache: "no-store",
    redirect: "error",
  });
  if (!response.ok) throw new Error("Verified visualizer session unavailable");
  const data: unknown = await response.json();
  if (!data || typeof data !== "object" || !("url" in data)) throw new Error("Invalid session response");
  const url = (data as {url: unknown}).url;
  if (typeof url !== "string" || !/^http:\/\/127\.0\.0\.1:\d{1,5}\/session\/[A-Za-z0-9_-]+\/$/.test(url)) {
    throw new Error("Unexpected visualizer session URL");
  }
  return url;
}
