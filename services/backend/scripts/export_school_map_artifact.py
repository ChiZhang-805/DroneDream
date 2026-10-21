from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.autonomy.school_map_artifact import export_school_map_gazebo_artifact  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the content-addressed School Map Gazebo contract."
    )
    parser.add_argument("output_directory", type=Path)
    arguments = parser.parse_args()
    hashes = export_school_map_gazebo_artifact(arguments.output_directory.resolve())
    print(json.dumps({"files": hashes}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
