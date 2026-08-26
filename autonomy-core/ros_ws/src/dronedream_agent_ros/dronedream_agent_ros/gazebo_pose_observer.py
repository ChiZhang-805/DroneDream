"""Preserve Gazebo entity identity while publishing typed ROS observations."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import rclpy
from dronedream_agent_msgs.msg import MissionObservation
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.transport13 import Node as GazeboNode
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data


@dataclass(frozen=True)
class EntityPose:
    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float


class GazeboPoseObserver(Node):
    """Read raw Pose_V names, then publish schema-stable MissionObservation."""

    def __init__(self) -> None:
        super().__init__("dronedream_gazebo_pose_observer")
        self.declare_parameter("gazebo_pose_topic", "/world/school_map_world/dynamic_pose/info")
        self.declare_parameter("entity_name", "my_drone")
        self.declare_parameter("contract_id", "")
        self.declare_parameter("segment_id", "")
        self.declare_parameter("publish_hz", 20.0)
        self._gazebo_topic = self.get_parameter("gazebo_pose_topic").value
        self._entity_name = self.get_parameter("entity_name").value
        self._contract_id = self.get_parameter("contract_id").value
        self._segment_id = self.get_parameter("segment_id").value
        publish_hz = float(self.get_parameter("publish_hz").value)
        if not 1.0 <= publish_hz <= 100.0:
            raise ValueError("publish_hz must be between 1 and 100")

        self._lock = threading.Lock()
        self._latest: EntityPose | None = None
        self._sequence = 0
        self._publisher = self.create_publisher(
            MissionObservation, "/dronedream/mission_observation", qos_profile_sensor_data
        )
        self._gazebo = GazeboNode()
        self._gazebo.subscribe(Pose_V, self._gazebo_topic, self._on_gazebo_pose)
        self._timer = self.create_timer(1.0 / publish_hz, self._publish_latest)
        self.get_logger().info(
            f"observing Gazebo entity {self._entity_name!r} on {self._gazebo_topic}"
        )

    def _on_gazebo_pose(self, message: Pose_V) -> None:
        for pose in message.pose:
            if pose.name != self._entity_name:
                continue
            value = EntityPose(
                x=pose.position.x,
                y=pose.position.y,
                z=pose.position.z,
                qx=pose.orientation.x,
                qy=pose.orientation.y,
                qz=pose.orientation.z,
                qw=pose.orientation.w,
            )
            with self._lock:
                self._latest = value
            return

    def _publish_latest(self) -> None:
        with self._lock:
            pose = self._latest
        if pose is None:
            return
        self._sequence += 1
        now = self.get_clock().now().to_msg()
        message = MissionObservation()
        message.header.stamp = now
        message.header.frame_id = "map_enu"
        message.contract_id = self._contract_id
        message.segment_id = self._segment_id
        message.sequence = self._sequence
        message.simulator_time = now
        message.pose_enu.position.x = pose.x
        message.pose_enu.position.y = pose.y
        message.pose_enu.position.z = pose.z
        message.pose_enu.orientation.x = pose.qx
        message.pose_enu.orientation.y = pose.qy
        message.pose_enu.orientation.z = pose.qz
        message.pose_enu.orientation.w = pose.qw
        message.battery_available = False
        message.clearance_available = False
        message.collision_monitor_available = False
        message.localization_ok = True
        message.link_ok = True
        message.geofence_ok = False
        message.target_reached = False
        message.deviation_code = "UNASSESSED"
        message.source_topic = self._gazebo_topic
        self._publisher.publish(message)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = GazeboPoseObserver()
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, KeyboardInterrupt):
        pass
    except Exception:
        # Process-group shutdown can invalidate the ROS context while the
        # executor is rebuilding its wait set.  Suppress only that cleanup
        # race; a live-context runtime failure must still surface.
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
