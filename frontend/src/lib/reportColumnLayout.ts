export type ReportColumnConfig = {
  columns: string[];
};

export type ReportPreviewRowLike = {
  cells: string[];
  emphasize?: boolean;
};

export function applyColumnLayout<T extends ReportPreviewRowLike>(
  columns: string[],
  rows: T[],
  keys: string[]
): { columns: string[]; rows: T[] } {
  const indexByName = new Map(columns.map((name, index) => [name, index]));
  const indices: number[] = [];
  const seen = new Set<string>();
  for (const raw of keys) {
    const key = raw.trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const index = indexByName.get(key);
    if (index !== undefined) indices.push(index);
  }
  if (indices.length === 0) {
    return { columns, rows };
  }
  return {
    columns: indices.map((index) => columns[index]),
    rows: rows.map((row) => ({
      ...row,
      cells: indices.map((index) => row.cells[index] ?? ""),
    })),
  };
}

export function insertKeyInCatalogOrder(
  visible: string[],
  key: string,
  catalog: string[]
): string[] {
  if (visible.includes(key)) return visible;
  const next = [...visible, key];
  const catalogVisible = catalog.filter((name) => next.includes(name));
  const extras = next.filter((name) => !catalog.includes(name));
  return [...catalogVisible, ...extras];
}

export function moveVisibleKey(visible: string[], index: number, delta: number): string[] {
  const next = [...visible];
  const target = index + delta;
  if (index < 0 || index >= next.length || target < 0 || target >= next.length) {
    return visible;
  }
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item);
  return next;
}
