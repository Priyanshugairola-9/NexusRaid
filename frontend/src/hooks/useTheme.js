import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "nexusraid-theme";

function initialTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

// Light/dark theme saved in localStorage. index.html applies the saved theme
// before React starts, so there is no flash of the wrong theme on refresh.
export function useTheme() {
  const [theme, setTheme] = useState(initialTheme);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* private mode: theme still works for this visit */
    }
  }, [theme]);
  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return { theme, toggle };
}

// Chart libraries need real colour values, so read the CSS variables of the current theme.
export function useChartColors(theme) {
  const [colors, setColors] = useState(() => readColors());
  useEffect(() => setColors(readColors()), [theme]);
  return colors;
}

function readColors() {
  const style = getComputedStyle(document.documentElement);
  const get = (name) => style.getPropertyValue(name).trim();
  return {
    ink: get("--ink"), muted: get("--muted"), line: get("--line"), surface: get("--surface"),
    accent: get("--chart-1"), second: get("--chart-2"), third: get("--chart-3"), fourth: get("--chart-4"),
    crit: get("--crit"), warn: get("--warn"),
  };
}
