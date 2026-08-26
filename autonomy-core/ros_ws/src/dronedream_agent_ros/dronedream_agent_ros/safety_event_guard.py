"""Translate an authorized typed ROS safety event into the executor abort gate."""

from __future__ import annotations

import json
from pathlib import Path

import rclpy
from dronedream_agent_msgs.msg import SafetyEvent
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy


class SafetyEventGuard(Node):
    """Fail closed without giving a native plugin direct actuator authority."""

    _ALLOWED_ACTIONS = {"safe_hold_then_land", "emergency_land"}

    def __init__(self) -> None:
        super().__init__("dronedream_safety_event_guard")
        self.declare_parameter("contract_id", "")
        self.declare_parameter("abort_file", "")
        self.declare_parameter("safety_event_topic", "/dronedream/safety_event")
        self._contract_id = str(self.get_parameter("contract_id").value)
        abort_file = str(self.get_parameter("abort_file").value)
        if not self._contract_id or not abort_file:
            raise ValueError("contract_id and abort_file are required")
        self._abort_file = Path(abort_file)
        self._handled = False
        qos = QoSProfile(depth=20, reliability=ReliabilityPolicy.RELIABLE)
        self._subscription = self.create_subscription(
            SafetyEvent,
            str(self.get_parameter("safety_event_topic").value),
            self._on_safety_event,
            qos,
        )

    def _on_safety_event(self, message: SafetyEvent) -> None:
        if self._handled:
            return
        if message.contract_id != self._contract_id:
            self.get_logger().error("rejected safety event for a different mission contract")
            return
        if int(message.severity) < 3 or message.action not in self._ALLOWED_ACTIONS:
            self.get_logger().error("rejected unrecognized or insufficient-severity safety event")
            return
        payload = {
            "reason": "NATIVE_RUNTIME_SAFETY_EVENT",
            "world_paused": False,
            "contract_id": self._contract_id,
            "action": message.action,
            "severity": int(message.severity),
            "observation_sequence": int(message.observation_sequence),
            "issue_codes": list(message.issue_codes),
            "source": "dronedream_agent_ros.safety_event_guard",
        }
        self._abort_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._abort_file.with_suffix(self._abort_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self._abort_file)
        self._handled = True
        self.get_logger().fatal("authorized native safety event entered the executor abort gate")


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = SafetyEventGuard()
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, KeyboardInterrupt):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
