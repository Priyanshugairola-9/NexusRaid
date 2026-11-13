import { useEffect, useState } from "react";

// Tiny hash router: "#/datasets/3/results" -> { path: "/datasets/3/results", parts: [...] }.
// Hash URLs work on any static host without server rewrite rules and survive a refresh.
function read() {
  const path = window.location.hash.replace(/^#/, "") || "/";
  return { path, parts: path.split("/").filter(Boolean) };
}

export function useRoute() {
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => {
      setRoute(read());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function navigate(path) {
  window.location.hash = path;
}
