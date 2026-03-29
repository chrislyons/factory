/* theme.js — theme constants, apply/get/set/cycle, persistence, cssVar() helper */

var THEME_KEY = "commandsheets-theme";
var THEME_ORDER = ["light", "dark", "ember"];

function getDefaultTheme() {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function getSavedTheme() {
  var saved = localStorage.getItem(THEME_KEY);
  return THEME_ORDER.includes(saved) ? saved : null;
}

function getCurrentTheme() {
  var current = document.documentElement.getAttribute("data-theme");
  return THEME_ORDER.includes(current) ? current : getDefaultTheme();
}

function applyTheme(theme, persist) {
  if (persist === undefined) persist = true;
  var nextTheme = THEME_ORDER.includes(theme) ? theme : getDefaultTheme();
  document.documentElement.setAttribute("data-theme", nextTheme);
  if (persist) {
    localStorage.setItem(THEME_KEY, nextTheme);
  }
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

(function initTheme() {
  applyTheme(getSavedTheme() || getDefaultTheme(), false);
})();
