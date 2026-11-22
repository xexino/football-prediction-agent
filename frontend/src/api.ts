// API client. In static mode (GitHub Pages snapshot) endpoints map to data/<name>.json.
let staticMode: boolean | null = null;

async function detectStatic(): Promise<boolean> {
  if (staticMode !== null) return staticMode;
  try {
    const r = await fetch("static-mode.json", { cache: "no-store" });
    staticMode = r.ok && (await r.json()).static === true;
  } catch {
    staticMode = false;
  }
  return staticMode;
}

export async function api<T = any>(path: string): Promise<T> {
  const isStatic = await detectStatic();
  const url = isStatic ? `data/${path.split("?")[0].replace(/^\//, "")}.json` : `api/${path.replace(/^\//, "")}`;
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} (${url})`);
  return r.json();
}

export const isStaticMode = () => staticMode === true;
