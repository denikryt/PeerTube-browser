/**
 * Minimal DOM helpers shared by vanilla page controllers.
 */

/** Return an element or throw the current fail-fast page bootstrap error. */
export function requireElement<T extends HTMLElement = HTMLElement>(id: string) {
  const element = document.getElementById(id) as T | null;
  if (!element) {
    throw new Error(`Missing element: ${id}`);
  }
  return element;
}
