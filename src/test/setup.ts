/* eslint-disable @typescript-eslint/no-explicit-any */
// Vitest setup file.
// Tests use plain DOM/React assertions; add global matchers here if needed.

if (typeof window !== 'undefined') {
  if (!window.ResizeObserver) {
    window.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
  if (!window.requestAnimationFrame) {
    window.requestAnimationFrame = (cb: FrameRequestCallback) =>
      Number(setTimeout(cb, 0));
  }
  if (!window.cancelAnimationFrame) {
    window.cancelAnimationFrame = (id: number) => clearTimeout(id);
  }

  // Lightweight Charts canvas 2D context mock for JSDOM
  if (typeof HTMLCanvasElement !== 'undefined') {
    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      contextId: string,
      ...args: unknown[]
    ) {
      if (contextId === '2d') {
        return {
          canvas: this,
          clearRect: () => {},
          fillRect: () => {},
          strokeRect: () => {},
          fillText: () => {},
          strokeText: () => {},
          measureText: () => ({ width: 0, actualBoundingBoxAscent: 0, actualBoundingBoxDescent: 0 }),
          beginPath: () => {},
          closePath: () => {},
          moveTo: () => {},
          lineTo: () => {},
          bezierCurveTo: () => {},
          quadraticCurveTo: () => {},
          arc: () => {},
          arcTo: () => {},
          ellipse: () => {},
          rect: () => {},
          fill: () => {},
          stroke: () => {},
          save: () => {},
          restore: () => {},
          scale: () => {},
          rotate: () => {},
          translate: () => {},
          transform: () => {},
          setTransform: () => {},
          resetTransform: () => {},
          createLinearGradient: () => ({ addColorStop: () => {} }),
          createRadialGradient: () => ({ addColorStop: () => {} }),
          createPattern: () => null,
          drawImage: () => {},
          getImageData: () => ({ data: new Uint8ClampedArray(4), width: 1, height: 1 }),
          putImageData: () => {},
          setLineDash: () => {},
          getLineDash: () => [],
        } as unknown as CanvasRenderingContext2D;
      }
      return origGetContext ? origGetContext.apply(this, [contextId, ...args] as any) : null;
    } as any;
  }
}
