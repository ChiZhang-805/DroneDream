import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InlineMissionMap } from "./InlineMissionMap";

describe("InlineMissionMap", () => {
  it("projects a round trip onto the map and places the aircraft from live telemetry", () => {
    const { container } = render(<InlineMissionMap
      chinese
      routePositions={[
        { x: -41, y: -83, z: 1.5 },
        { x: -41, y: -83, z: 35 },
        { x: 0, y: -5, z: 35 },
        { x: 43, y: 55, z: 2 },
        { x: 0, y: -5, z: 35 },
        { x: -41, y: -83, z: 1.5 },
      ]}
      telemetry={{
        schema_version: "dronedream.live-telemetry.v1",
        mode: "simulation",
        coordinate_frame: "gazebo-enu",
        east_m: 4,
        north_m: 12,
        up_m: 18,
        updated_at_unix_ms: 1,
      }}
      bounds={{ x: 500, y: 500, z: 35 }}
      previewUrl="/asset-previews/maps/kumpula-campus-orthophoto.jpg"
    />);

    expect(screen.getByRole("img", { name: "二维任务地图" })).toBeVisible();
    expect(screen.getByText("起点 / 返航")).toBeVisible();
    expect(screen.getByText("中转点")).toBeVisible();
    expect(screen.getByText("终点")).toBeVisible();
    expect(screen.getByText("无人机")).toBeVisible();
    expect(container.querySelector(".autonomy-inline-map-route")?.getAttribute("points"))
      .toBe("-41,83 0,5 43,-55 0,5 -41,83");
    expect(container.querySelector(".autonomy-inline-map-aircraft")?.getAttribute("transform"))
      .toBe("translate(4 -12)");
  });

  it("uses the last point as the destination for a one-way route", () => {
    render(<InlineMissionMap
      chinese={false}
      routePositions={[{ x: 1, y: 2, z: 1 }, { x: 40, y: 60, z: 9 }]}
      telemetry={null}
      bounds={{ x: 100, y: 100, z: 20 }}
      previewUrl={null}
    />);

    expect(screen.getByText("Start")).toBeVisible();
    expect(screen.getByText("Destination")).toBeVisible();
    expect(screen.queryByText("Waypoint")).toBeNull();
    expect(screen.queryByText("Aircraft")).toBeNull();
  });
});
