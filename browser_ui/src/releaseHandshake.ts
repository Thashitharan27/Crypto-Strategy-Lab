/** An authenticated mode and its server capabilities must agree. */
export function approvedConnectionMode(
  health: {status?: unknown; mode?: unknown},
  release: {execution?: unknown; configuration_editing?: unknown},
): "read-only" | "guarded" {
  if (health?.status !== "ok" || typeof release?.execution !== "boolean"
      || typeof release.configuration_editing !== "boolean") {
    throw new Error("Invalid release capability metadata");
  }
  if (health.mode === "read-only" && release.execution === false && release.configuration_editing === false) return "read-only";
  if (health.mode === "guarded" && release.execution === true && release.configuration_editing === true) return "guarded";
  throw new Error("API mode and release capabilities disagree");
}
