#!/usr/bin/env python3
"""Print the retained cloud-build plan; provisioning is owner-commissioned."""
import sys


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if arguments not in ([], ["--help"], ["-h"], ["--dry-run"]):
        print("This entry prints a local plan. Use --dry-run or --help; review docs/historical/cloud-build-scripts.md.", file=sys.stderr)
        return 64
    print("Geospatial cloud build: local plan only.")
    print("Original processing algorithms remain in backend/etl/.")
    print("Historical cloud configuration: docs/historical/cloud-build-scripts.md")
    print("Cloud execution requires an owner-reviewed account, dataset, scan allowance, storage limit and termination policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
