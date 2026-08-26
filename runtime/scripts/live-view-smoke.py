#!/usr/bin/env python3
"""Fast Runtime smoke test for the Gazebo headless live-view transport."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORLD = """<?xml version="1.0"?>
<sdf version="1.10">
  <world name="live_view_smoke">
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <light type="directional" name="sun">
      <pose>0 0 10 0 0 0</pose><direction>-0.5 0.5 -1</direction>
    </light>
    <model name="ground"><static>true</static><link name="link">
      <collision name="collision"><geometry><box><size>20 20 0.1</size></box></geometry></collision>
      <visual name="visual"><geometry><box><size>20 20 0.1</size></box></geometry></visual>
    </link></model>
    <model name="target"><static>true</static><pose>0 0 1 0 0 0</pose><link name="link">
      <visual name="visual"><geometry><box><size>1 1 2</size></box></geometry>
        <material><diffuse>1 0.1 0.1 1</diffuse></material>
      </visual>
    </link></model>
    <model name="camera"><static>true</static><pose>-6 -6 5 0 0.48 0.785398</pose><link name="link">
      <sensor name="live" type="camera"><always_on>true</always_on><update_rate>8</update_rate>
        <topic>/dronedream/live/smoke</topic><camera><image>
          <width>640</width><height>360</height><format>R8G8B8</format>
        </image><clip><near>0.1</near><far>100</far></clip></camera>
      </sensor>
    </link></model>
  </world>
</sdf>
"""


def main() -> int:
    system_packages = "/usr/lib/python3/dist-packages"
    if system_packages not in sys.path:
        sys.path.append(system_packages)
    from gz.msgs10.image_pb2 import Image
    from gz.transport13 import Node

    partition = f"dronedream_live_smoke_{os.getpid()}"
    os.environ["GZ_PARTITION"] = partition
    os.environ["GZ_IP"] = "127.0.0.1"
    with tempfile.TemporaryDirectory(prefix="dronedream-live-smoke-") as temporary:
        root = Path(temporary)
        world = root / "world.sdf"
        world.write_text(WORLD, encoding="utf-8")
        log = (root / "gazebo.log").open("w", encoding="utf-8")
        process = subprocess.Popen(
            ["gz", "sim", "-r", "-s", "--headless-rendering", str(world)],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        frames: list[tuple[int, int, int]] = []
        node = Node()

        def on_image(message) -> None:
            frames.append((int(message.width), int(message.height), len(message.data)))

        node.subscribe(Image, "/dronedream/live/smoke", on_image)
        deadline = time.monotonic() + 25
        try:
            while time.monotonic() < deadline and process.poll() is None and len(frames) < 3:
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                os.kill(-process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            log.close()
        if len(frames) < 3:
            print((root / "gazebo.log").read_text(encoding="utf-8", errors="replace")[-4000:])
            return 1
        width, height, byte_size = frames[-1]
        if (width, height) != (640, 360) or byte_size < width * height * 3:
            return 2
        print(f"DRONEDREAM_LIVE_VIEW_READY frames={len(frames)} size={width}x{height}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
