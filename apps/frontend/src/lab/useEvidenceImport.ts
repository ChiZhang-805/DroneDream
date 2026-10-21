import { useEffect, useRef, useState } from "react";

import { readEvidenceFile } from "./evidenceInput";

/** Latest-selection ownership for local files and asynchronous digest verification. */
export function useEvidenceImport<T>(
  maximumBytes: number,
  parse: (fileName: string, source: string) => T | Promise<T>,
) {
  const generation = useRef(0);
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => () => { generation.current += 1; }, []);

  /** Clearing a preview also cancels delivery of an already-running file/hash operation. */
  function reset() {
    generation.current += 1;
    setValue(null);
    setError(null);
    setLoading(false);
  }

  async function importFile(file: File) {
    const ticket = ++generation.current;
    setValue(null);
    setError(null);
    setLoading(true);
    try {
      const source = await readEvidenceFile(file, maximumBytes);
      if (ticket !== generation.current) return;
      const result = await parse(file.name, source);
      if (ticket !== generation.current) return;
      setValue(() => result);
    } catch (caught) {
      if (ticket === generation.current) setError(() => caught);
    } finally {
      if (ticket === generation.current) setLoading(false);
    }
  }
  return { value, error, loading, importFile, reset };
}
