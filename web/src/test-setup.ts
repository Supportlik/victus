// Vitest setup: jsdom lacks ResizeObserver, which ECharts needs to mount a chart host.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver = ResizeObserverStub;
}

// jsdom also has no canvas, so ECharts' painter would throw while clearing its layer.
// A no-op 2D context is enough: the specs assert markup, never pixels.
// jsdom defines getContext but returns null and logs 'not implemented', so replace it outright.
if (typeof HTMLCanvasElement !== 'undefined') {
  const context = new Proxy(
    {
      canvas: null,
      measureText: () => ({ width: 0 }),
      createLinearGradient: () => ({ addColorStop: () => undefined }),
      createRadialGradient: () => ({ addColorStop: () => undefined }),
      createPattern: () => null,
      getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    } as Record<string, unknown>,
    {
      get: (target, prop) =>
        prop in target ? target[prop as string] : () => undefined,
      set: () => true,
    },
  );
  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
    configurable: true,
    value: () => context,
  });
}

// Node 26 ships its own global localStorage, unusable unless the process was started with
// --localstorage-file; reading it throws or yields undefined, and it shadows the one jsdom
// installs. Since the specs only need somewhere to put a few keys, install a plain
// in-memory Storage whenever the ambient one cannot be read.
function usable(name: 'localStorage' | 'sessionStorage'): boolean {
  try {
    const store = (globalThis as Record<string, unknown>)[name] as Storage | undefined;
    if (!store) return false;
    store.setItem('__probe__', '1');
    store.removeItem('__probe__');
    return true;
  } catch {
    return false;
  }
}

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    key: (i: number) => Array.from(map.keys())[i] ?? null,
    removeItem: (k: string) => void map.delete(k),
    setItem: (k: string, v: string) => void map.set(k, String(v)),
  } as Storage;
}

for (const name of ['localStorage', 'sessionStorage'] as const) {
  if (usable(name)) continue;
  const value = memoryStorage();
  try {
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  } catch {
    // a non-configurable global cannot be redefined; a plain assignment still wins in jsdom
    (globalThis as Record<string, unknown>)[name] = value;
  }
}
