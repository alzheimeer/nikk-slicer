import { useCallback, useEffect, useRef, useState } from 'react';

interface UseSessionHistoryOptions<T> {
  currentSnapshot: T;
  onApplySnapshot: (snapshot: T) => void;
  maxSteps?: number;
  debounceMs?: number;
}

export function useSessionHistory<T>({
  currentSnapshot,
  onApplySnapshot,
  maxSteps = 80,
  debounceMs = 280,
}: UseSessionHistoryOptions<T>) {
  const [past, setPast] = useState<string[]>([]);
  const [future, setFuture] = useState<string[]>([]);

  const serializedCurrent = JSON.stringify(currentSnapshot);
  const lastCommittedRef = useRef<string>(serializedCurrent);
  const isApplyingRef = useRef<boolean>(false);
  const applyTimerRef = useRef<number | null>(null);
  const onApplyRef = useRef(onApplySnapshot);
  onApplyRef.current = onApplySnapshot;

  useEffect(() => {
    if (isApplyingRef.current) {
      lastCommittedRef.current = serializedCurrent;
      return;
    }
    if (serializedCurrent === lastCommittedRef.current) {
      return;
    }

    const prevCommitted = lastCommittedRef.current;
    const timer = window.setTimeout(() => {
      if (isApplyingRef.current) return;
      if (serializedCurrent === lastCommittedRef.current) return;
      setPast((prev) => {
        const next = [...prev, prevCommitted];
        return next.length > maxSteps ? next.slice(next.length - maxSteps) : next;
      });
      setFuture([]);
      lastCommittedRef.current = serializedCurrent;
    }, debounceMs);

    return () => {
      window.clearTimeout(timer);
    };
  }, [serializedCurrent, maxSteps, debounceMs]);

  const applySerialized = useCallback((rawJson: string) => {
    try {
      const parsed = JSON.parse(rawJson) as T;
      if (applyTimerRef.current !== null) {
        window.clearTimeout(applyTimerRef.current);
      }
      isApplyingRef.current = true;
      lastCommittedRef.current = rawJson;
      onApplyRef.current(parsed);
      applyTimerRef.current = window.setTimeout(() => {
        isApplyingRef.current = false;
        applyTimerRef.current = null;
      }, 60);
    } catch {
      isApplyingRef.current = false;
    }
  }, []);

  const undo = useCallback((): boolean => {
    if (past.length === 0) return false;
    const target = past[past.length - 1];
    setPast((prev) => prev.slice(0, -1));
    setFuture((prev) => {
      const next = [...prev, serializedCurrent];
      return next.length > maxSteps ? next.slice(next.length - maxSteps) : next;
    });
    applySerialized(target);
    return true;
  }, [past, serializedCurrent, maxSteps, applySerialized]);

  const redo = useCallback((): boolean => {
    if (future.length === 0) return false;
    const target = future[future.length - 1];
    setFuture((prev) => prev.slice(0, -1));
    setPast((prev) => {
      const next = [...prev, serializedCurrent];
      return next.length > maxSteps ? next.slice(next.length - maxSteps) : next;
    });
    applySerialized(target);
    return true;
  }, [future, serializedCurrent, maxSteps, applySerialized]);

  const resetHistory = useCallback(() => {
    setPast([]);
    setFuture([]);
    lastCommittedRef.current = serializedCurrent;
  }, [serializedCurrent]);

  return {
    canUndo: past.length > 0,
    canRedo: future.length > 0,
    undoCount: past.length,
    redoCount: future.length,
    undo,
    redo,
    resetHistory,
  };
}
