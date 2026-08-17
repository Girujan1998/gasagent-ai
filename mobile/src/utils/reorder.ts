// Moves the item at `fromIndex` to `toIndex`, shifting everything between
// them over by one — the same semantics as dragging a row out of a list
// and dropping it in a new slot. Extracted as a pure function so the
// actual reordering logic can be unit tested without simulating a drag
// gesture (PanResponder's gesture state isn't practical to fake in a
// component test).
export function moveInArray<T>(
  items: T[],
  fromIndex: number,
  toIndex: number,
): T[] {
  if (
    fromIndex === toIndex ||
    fromIndex < 0 ||
    toIndex < 0 ||
    fromIndex >= items.length ||
    toIndex >= items.length
  ) {
    return items;
  }
  const next = [...items];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}
