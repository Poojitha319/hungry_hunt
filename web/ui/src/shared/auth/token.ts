const KEY = "hh_token";

export function captureToken(): void {
  const url = new URL(window.location.href);
  const t = url.searchParams.get("t");
  if (!t) return;
  window.localStorage.setItem(KEY, t);
  url.searchParams.delete("t");
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
}

export function getToken(): string | null {
  return window.localStorage.getItem(KEY);
}
