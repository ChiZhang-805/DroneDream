import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { GazeboLivePanel } from "../components/GazeboLivePanel";

describe("GazeboLivePanel", () => {
  it("does not render iframe when URL is empty", () => {
    const { container } = render(<GazeboLivePanel viewerUrl="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders iframe and warning text when URL is provided", () => {
    render(
      <GazeboLivePanel viewerUrl="https://example.com/vnc.html?autoconnect=1" />,
    );

    const frame = screen.getByTitle("Gazebo live view");
    expect(frame).toBeInTheDocument();
    const src = frame.getAttribute("src");
    expect(src).toBeTruthy();
    const parsed = new URL(src!);
    expect(parsed.origin).toBe("https://example.com");
    expect(parsed.pathname).toBe("/vnc.html");
    expect(parsed.searchParams.get("autoconnect")).toBe("1");
    expect(parsed.searchParams.get("resize")).toBe("scale");
    expect(parsed.searchParams.get("view_clip")).toBe("0");
    expect(
      screen.getByText(/optional and intended for Runpod demo\/debug mode/i),
    ).toBeInTheDocument();
  });
});
