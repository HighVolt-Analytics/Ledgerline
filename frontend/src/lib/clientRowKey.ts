/** Stable React list keys for editable rows — never sent to the API. */
export function newClientRowKey(prefix = "row"): string {
  return `${prefix}-${crypto.randomUUID()}`;
}
