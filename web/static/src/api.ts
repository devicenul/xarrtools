import { ArchiveBatchItem, ArchiveBatchResponse } from "./types.js";

/**
 * Batched archive API call to POST /api/archive/batch.
 */
export async function archiveBatch(
  items: ArchiveBatchItem[],
  archive: boolean = true
): Promise<ArchiveBatchResponse> {
  const response = await fetch("/api/archive/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      archive,
      items
    })
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return (await response.json()) as ArchiveBatchResponse;
}
