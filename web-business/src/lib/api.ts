export const CAIRN_API_URL =
  process.env.CAIRN_API_URL ?? 'http://localhost:8765';

export const CAIRN_API_KEY =
  process.env.CAIRN_API_KEY ?? 'claw-dev-key-change-in-production';

export const PHLOE_API_URL =
  process.env.PHLOE_API_URL ?? 'https://phloe.co.uk';

export const PHLOE_TENANT_SLUG =
  process.env.PHLOE_TENANT_SLUG ?? 'nbne';

/**
 * Fetch wrapper for Cairn API requests.
 * Automatically prepends CAIRN_API_URL and injects the X-API-Key header.
 */
export async function cairnFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const url = `${CAIRN_API_URL}${path}`;
  const headers = new Headers(options.headers);
  headers.set('X-API-Key', CAIRN_API_KEY);
  return fetch(url, { ...options, headers });
}

/**
 * Fetch wrapper for Phloe API requests.
 * Automatically prepends PHLOE_API_URL and injects the X-Tenant-Slug header.
 */
export async function phloeFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const url = `${PHLOE_API_URL}${path}`;
  const headers = new Headers(options.headers);
  headers.set('X-Tenant-Slug', PHLOE_TENANT_SLUG);
  return fetch(url, { ...options, headers });
}
