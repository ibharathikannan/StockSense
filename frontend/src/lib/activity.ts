// Tiny store counting pending work. api.ts calls begin/end around every fetch (and
// <PageLoader> does while mounted); <LoadingOverlay> subscribes so anything the
// user waits on shows one shared loading animation, without each page wiring it up.

let pending = 0;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

export function beginActivity() {
  pending += 1;
  emit();
}

export function endActivity() {
  pending = Math.max(0, pending - 1);
  emit();
}

export function subscribeActivity(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export const getPendingCount = () => pending;
