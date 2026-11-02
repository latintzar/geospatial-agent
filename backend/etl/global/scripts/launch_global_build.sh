#!/usr/bin/env bash
# The historical cloud launcher is retained as documentation, not a deployment.
set -eu

case "${1-}" in
    ''|--dry-run|--help|-h)
        if [ "$#" -gt 1 ]; then
            printf '%s\n' 'Usage: launch_global_build.sh [--dry-run|--help]' >&2
            exit 64
        fi
        printf '%s\n' \
            'Geospatial cloud build: local plan only.' \
            'The hosted example uses retained results and local computation.' \
            'The original ETL algorithms remain in backend/etl/global/.' \
            'Historical cloud configuration: docs/historical/cloud-build-scripts.md' \
            'Cloud execution requires an owner-reviewed account, dataset, scan allowance, storage limit and termination policy.'
        ;;
    *)
        printf '%s\n' \
            'This entry prints a local plan.' \
            'Use --dry-run or --help; review docs/historical/cloud-build-scripts.md for the historical configuration.' >&2
        exit 64
        ;;
esac
