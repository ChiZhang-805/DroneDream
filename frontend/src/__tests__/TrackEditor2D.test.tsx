import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TrackEditor2D } from "../components/TrackEditor2D";
import { I18nProvider } from "../i18n/I18nProvider";
import type { TrackPoint } from "../types/api";

const INITIAL_POINTS: TrackPoint[] = [
  { x: 0, y: 0, z: 3 },
  { x: 4, y: 1, z: 4 },
  { x: 6, y: 3, z: 5 },
];

function EditorHarness() {
  const [points, setPoints] = useState(INITIAL_POINTS);
  return (
    <I18nProvider>
      <TrackEditor2D
        points={points}
        defaultAltitude={3}
        onChange={setPoints}
        dataPanelAction={<button type="button">JSON import / export</button>}
      />
      <output data-testid="track-state">{JSON.stringify(points)}</output>
    </I18nProvider>
  );
}

function renderEditor() {
  return render(<EditorHarness />);
}

describe("TrackEditor2D", () => {
  let originalScrollTo: PropertyDescriptor | undefined;

  beforeEach(() => {
    originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
    window.localStorage.setItem("drone-dream:locale", "en");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalScrollTo) {
      Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
    } else {
      delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTo;
    }
  });

  it("uses accessible icon actions and confirms before clearing every waypoint", () => {
    renderEditor();

    const add = screen.getByRole("button", { name: "Add waypoint" });
    expect(add).not.toHaveTextContent("Add waypoint");
    fireEvent.click(add);
    expect(screen.getAllByRole("button", { name: /Remove waypoint \d+/ })).toHaveLength(4);

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getAllByRole("button", { name: /Remove waypoint \d+/ })).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: "Clear all waypoints" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Clear every waypoint?");
    expect(screen.getAllByRole("button", { name: /Remove waypoint \d+/ })).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Cancel clearing waypoints" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear all waypoints" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm clear all waypoints" }));
    expect(screen.queryByRole("button", { name: /Remove waypoint \d+/ })).not.toBeInTheDocument();
    expect(screen.getByText("No waypoints")).toBeVisible();
  });

  it("exposes a visual pane beside one independently scrollable data pane", () => {
    renderEditor();

    const workspace = screen.getByTestId("track-editor-workspace");
    const visualPane = screen.getByTestId("track-editor-visual-pane");
    const dataPane = screen.getByTestId("track-waypoint-table-scroll");
    const dataAction = screen.getByTestId("track-editor-data-action");
      const viewSwitcher = screen.getByRole("group", { name: "Track view" });

    expect(workspace).toContainElement(visualPane);
    expect(workspace).toContainElement(dataPane);
    expect(workspace).toContainElement(dataAction);
    expect(viewSwitcher.closest(".track-editor-toolbar")).not.toBeNull();
    expect(visualPane).not.toContainElement(viewSwitcher);
    expect(dataAction).toHaveTextContent("JSON import / export");
  });

  it("cycles through XY, XZ, YZ and interactive 3D views and edits Z by dragging", () => {
    renderEditor();

    expect(screen.getByRole("group", { name: "XY view flight track editor" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next view" }));
    const xzCanvas = screen.getByRole("group", { name: "XZ view flight track editor" });
    expect(xzCanvas).toBeVisible();

    vi.spyOn(xzCanvas, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      right: 640,
      bottom: 360,
      left: 0,
      width: 640,
      height: 360,
      toJSON: () => ({}),
    });
    fireEvent.pointerDown(screen.getByTestId("track-waypoint-2"), {
      pointerId: 1,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(xzCanvas, { pointerId: 1, clientX: 320, clientY: 100 });
    fireEvent.pointerUp(xzCanvas, { pointerId: 1 });
    const updated = JSON.parse(screen.getByTestId("track-state").textContent ?? "[]") as TrackPoint[];
    expect(updated[1].z).not.toBe(4);

    fireEvent.click(screen.getByRole("button", { name: "Next view" }));
    expect(screen.getByRole("group", { name: "YZ view flight track editor" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next view" }));
    const threeDimensionalCanvas = screen.getByRole("group", {
      name: "3D view flight track editor",
    });
    expect(threeDimensionalCanvas).toBeVisible();
    expect(threeDimensionalCanvas.querySelectorAll(".track-3d-axis")).toHaveLength(3);
    const firstWaypoint = screen.getByTestId("track-waypoint-1");
    const initialTransform = firstWaypoint.getAttribute("transform");
    fireEvent.pointerDown(threeDimensionalCanvas, {
      pointerId: 7,
      clientX: 180,
      clientY: 150,
    });
    fireEvent.pointerMove(threeDimensionalCanvas, {
      pointerId: 7,
      clientX: 260,
      clientY: 110,
    });
    fireEvent.pointerUp(threeDimensionalCanvas, { pointerId: 7 });
    expect(firstWaypoint.getAttribute("transform")).not.toBe(initialTransform);
    const rotatedTransform = firstWaypoint.getAttribute("transform");
    fireEvent.wheel(threeDimensionalCanvas, { deltaY: -120 });
    expect(firstWaypoint.getAttribute("transform")).not.toBe(rotatedTransform);

    fireEvent.click(screen.getByRole("button", { name: "Previous view" }));
    expect(screen.getByRole("group", { name: "YZ view flight track editor" })).toBeVisible();
  });

  it("adds grid columns for a long 3D track instead of stretching fixed cells", () => {
    const longTrack: TrackPoint[] = Array.from({ length: 17 }, (_value, index) => ({
      x: index * 2,
      y: index % 4 === 0 ? 3 : index % 4 === 2 ? -3 : 0,
      z: 2 + (index % 3) * 2,
    }));
    render(
      <I18nProvider>
        <TrackEditor2D points={longTrack} defaultAltitude={3} onChange={() => undefined} />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Previous view" }));

    const canvas = screen.getByRole("group", { name: "3D view flight track editor" });
    const xGridLines = canvas.querySelectorAll('[data-grid-axis="x"]');
    const yGridLines = canvas.querySelectorAll('[data-grid-axis="y"]');
    expect(xGridLines.length).toBeGreaterThan(yGridLines.length);
    expect(xGridLines.length).toBeGreaterThan(6);
  });

  it("clamps planar dragging to the visible plot using stable drag-start bounds", () => {
    renderEditor();

    const canvas = screen.getByRole("group", { name: "XY view flight track editor" });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      right: 640,
      bottom: 360,
      left: 0,
      width: 640,
      height: 360,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(screen.getByTestId("track-waypoint-1"), {
      pointerId: 1,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 5_000, clientY: -5_000 });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 5_000, clientY: -5_000 });
    fireEvent.pointerUp(canvas, { pointerId: 1 });

    const updated = JSON.parse(screen.getByTestId("track-state").textContent ?? "[]") as TrackPoint[];
    expect(updated[0]).toMatchObject({ x: 8, y: 7 });
  });

  it("scrolls to and highlights a clicked graphical waypoint and mirrors table selection", () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      writable: true,
      value: scrollTo,
    });
    renderEditor();

    fireEvent.click(screen.getByTestId("track-waypoint-3"));
    const thirdRow = screen.getByLabelText("Waypoint 3 X").closest("tr");
    expect(thirdRow).toHaveClass("track-waypoint-row-selected");
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: "smooth" }));
    expect(screen.getByTestId("track-waypoint-3")).toHaveAttribute("aria-pressed", "true");

    const firstRow = screen.getByLabelText("Waypoint 1 Y").closest("tr");
    expect(firstRow).not.toBeNull();
    fireEvent.click(firstRow!);
    expect(firstRow).toHaveClass("track-waypoint-row-selected");
    expect(screen.getByTestId("track-waypoint-1")).toHaveClass("track-waypoint-selected");
    expect(screen.getByTestId("track-waypoint-3")).not.toHaveClass("track-waypoint-selected");
  });

  it("keeps the editor controls and view labels fully localized in Chinese", () => {
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
    renderEditor();

    expect(screen.getByRole("button", { name: "添加航点" })).toBeVisible();
    expect(screen.getByRole("button", { name: "清空全部航点" })).toBeVisible();
    expect(screen.getByRole("group", { name: "XY 视图航迹编辑器" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Z（米）" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Add waypoint" })).not.toBeInTheDocument();
  });
});
