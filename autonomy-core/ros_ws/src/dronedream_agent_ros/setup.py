from setuptools import find_packages, setup

package_name = "dronedream_agent_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=("test",)),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="DroneDream",
    maintainer_email="engineering@dronedream.local",
    description="ROS 2 runtime nodes for the DroneDream flight-agent core",
    license="MIT",
    entry_points={
        "console_scripts": [
            "gazebo_pose_observer = dronedream_agent_ros.gazebo_pose_observer:main",
            "safety_event_guard = dronedream_agent_ros.safety_event_guard:main",
        ],
    },
)
