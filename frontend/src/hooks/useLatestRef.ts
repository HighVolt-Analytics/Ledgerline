import { useRef } from "react";

/** Always-current ref for a value, so callbacks can stay out of hook dependency arrays. */
export function useLatestRef<T>(value: T) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}
