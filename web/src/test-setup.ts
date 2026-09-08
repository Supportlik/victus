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
