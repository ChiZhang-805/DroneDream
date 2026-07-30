export function lastLineOccupancy(paragraph: HTMLParagraphElement): number {
  const range = document.createRange();
  const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
  const lineFragments: DOMRect[] = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!(node.textContent ?? "").trim()) continue;
    range.selectNodeContents(node);
    lineFragments.push(
      ...Array.from(range.getClientRects()).filter((rect) => rect.width > 0),
    );
  }
  if (lineFragments.length === 0 || paragraph.clientWidth <= 0) return 1;
  const lastTop = Math.max(...lineFragments.map((rect) => rect.top));
  const lastLine = lineFragments.filter((rect) => Math.abs(rect.top - lastTop) < 1);
  const left = Math.min(...lastLine.map((rect) => rect.left));
  const right = Math.max(...lastLine.map((rect) => rect.right));
  return (right - left) / paragraph.clientWidth;
}

export function renderedLineCount(paragraph: HTMLParagraphElement): number {
  const range = document.createRange();
  const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
  const lineTops: number[] = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!(node.textContent ?? "").trim()) continue;
    range.selectNodeContents(node);
    for (const rect of Array.from(range.getClientRects())) {
      if (rect.width <= 0 || rect.height <= 0) continue;
      if (!lineTops.some((top) => Math.abs(top - rect.top) < 1)) {
        lineTops.push(rect.top);
      }
    }
  }
  return lineTops.length;
}
