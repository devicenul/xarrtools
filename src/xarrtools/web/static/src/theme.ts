/**
 * Theme management helpers for xarrtools (dark/light mode toggles and sync).
 */

export function initTheme(): void {
  const savedTheme = typeof localStorage !== "undefined" ? localStorage.getItem("xarrtools-theme") : null;
  const isLight = savedTheme === "light";
  if (typeof document !== "undefined" && document.body) {
    if (isLight) {
      document.body.classList.add("light-theme");
    } else {
      document.body.classList.remove("light-theme");
    }
  }
  // Defer UI updates slightly to ensure elements exist
  setTimeout(() => updateThemeToggleUI(isLight), 0);
}

export function updateThemeToggleUI(isLight: boolean): void {
  if (typeof document === "undefined") return;
  const themeBtn = document.getElementById("btn-theme-toggle");
  const logoImg = document.getElementById("app-logo") as HTMLImageElement | null;
  if (themeBtn) {
    themeBtn.textContent = isLight ? "🌙" : "☀️";
    const tip = isLight ? "Switch to Dark Theme" : "Switch to Light Theme";
    themeBtn.setAttribute("data-tooltip", tip);
    themeBtn.setAttribute("aria-label", tip);
    themeBtn.removeAttribute("title");
  }
  if (logoImg) {
    logoImg.src = isLight ? "/static/favicon_light.png" : "/static/favicon.png";
  }
}

export function toggleTheme(): void {
  if (typeof document === "undefined" || !document.body) return;
  const isLight = document.body.classList.toggle("light-theme");
  const themeStr = isLight ? "light" : "dark";
  if (typeof localStorage !== "undefined") {
    localStorage.setItem("xarrtools-theme", themeStr);
  }
  updateThemeToggleUI(isLight);

  // Synchronize select theme dropdown if open or loaded
  const selectTheme = document.getElementById("select-theme-mode") as HTMLSelectElement | null;
  if (selectTheme) {
    selectTheme.value = themeStr;
  }
}
