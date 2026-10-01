/**
 * Make `localStorage` throw on every access, the way a browser with blocked site data or a
 * strict private mode does. Returns the function that puts the previous one back.
 *
 * The services read and write their preferences inside try/catch; this is what lets a spec
 * prove that a blocked store costs the preference and nothing else.
 */
export function blockLocalStorage(): () => void {
  const holder = globalThis as Record<string, unknown>;
  const own = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const refuse = () => {
    throw new DOMException('The operation is insecure.', 'SecurityError');
  };
  const blocked = {
    get length() {
      return 0;
    },
    getItem: refuse,
    setItem: refuse,
    removeItem: refuse,
    key: refuse,
    // the shared setup clears storage before every spec; that must not be what fails
    clear: () => undefined,
  };
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, writable: true, value: blocked });
  return () => {
    if (own) Object.defineProperty(globalThis, 'localStorage', own);
    else delete holder['localStorage'];
  };
}
