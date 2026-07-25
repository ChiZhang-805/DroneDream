import { apiClient, ApiClientError } from "../../api/client";
import type { Job } from "../../types/api";

const HISTORY_PAGE_SIZE = 200;
const HISTORY_MAX_PAGES = 50;

export async function fetchAllHistoryJobs(): Promise<Job[]> {
  const jobs: Job[] = [];
  const seenIds = new Set<string>();

  for (let page = 1; page <= HISTORY_MAX_PAGES; page += 1) {
    const response = await apiClient.listJobs({ page, page_size: HISTORY_PAGE_SIZE });
    let added = 0;
    for (const job of response.items) {
      if (seenIds.has(job.id)) continue;
      seenIds.add(job.id);
      jobs.push(job);
      added += 1;
    }
    if (jobs.length >= response.total) return jobs;
    if (response.items.length === 0 || added === 0) {
      throw new ApiClientError(
        "INVALID_PAGINATION",
        "The job history endpoint stopped before returning every job.",
        null,
        502,
      );
    }
  }

  throw new ApiClientError(
    "INVALID_PAGINATION",
    "The job history endpoint exceeded the supported pagination limit.",
    null,
    502,
  );
}
