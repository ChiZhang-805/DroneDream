/** Resource bounds for local evidence previews; these checks grant no authority. */
type EvidenceError = new (message: string) => Error;

/** Bound depth before any recursive schema/hash operation; reject non-JSON graphs. */
export function validateEvidenceTree(
  value: unknown,
  ErrorType: EvidenceError,
  forbiddenField?: RegExp,
): void {
  let remaining = 65_536;
  function visit(child: unknown, depth: number): void {
    if (depth > 32 || --remaining < 0) {
      throw new ErrorType("Evidence nesting or element count exceeds the safe limit.");
    }
    if (child === null || typeof child === "string" || typeof child === "boolean") return;
    if (typeof child === "number" && Number.isFinite(child)) return;
    if (!child || typeof child !== "object") {
      throw new ErrorType("Evidence must contain only finite JSON values.");
    }
    if (Array.isArray(child)) {
      // Iteration includes holes as undefined; map() would silently skip them.
      for (const item of child) visit(item, depth + 1);
      return;
    }
    const prototype = Object.getPrototypeOf(child);
    if (prototype !== Object.prototype && prototype !== null) {
      throw new ErrorType("Evidence must contain plain JSON objects.");
    }
    for (const [key, item] of Object.entries(child)) {
      if (forbiddenField?.test(key)) {
        throw new ErrorType("Sensitive field is not allowed in evidence.");
      }
      visit(item, depth + 1);
    }
  }
  visit(value, 0);
}

/** Check browser File size before allocating its text, then check the actual UTF-8 bytes. */
export async function readEvidenceFile(file: File, maximumBytes: number): Promise<string> {
  if (!Number.isSafeInteger(maximumBytes) || maximumBytes <= 0
    || !Number.isSafeInteger(file.size) || file.size <= 0 || file.size > maximumBytes) {
    throw new Error("Evidence is empty or exceeds the import size limit.");
  }
  const source = await file.text();
  if (typeof source !== "string" || source.length === 0 || source.length > maximumBytes
    || new TextEncoder().encode(source).byteLength > maximumBytes) {
    throw new Error("Evidence is empty or exceeds the import size limit.");
  }
  return source;
}
