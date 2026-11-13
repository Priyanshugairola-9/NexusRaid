import { useCallback, useEffect, useRef, useState } from "react";

// Loads data and tracks loading/error state. reload() fetches again.
export function useAsync(loader, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const active = useRef(true);
  const run = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await loader();
      if (active.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (active.current) setState({ data: null, error, loading: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    active.current = true;
    run();
    return () => {
      active.current = false;
    };
  }, [run]);
  return { ...state, reload: run };
}
