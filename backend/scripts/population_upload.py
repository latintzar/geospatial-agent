"""Upload an explicitly selected local population dataset with owned limits."""
import argparse
from pathlib import Path
import subprocess
import sys

if __package__:
    from . import upload_worldpop_to_s3 as transfer
else:
    import upload_worldpop_to_s3 as transfer


def upload_directory(directory, *, bucket, prefix):
    """Reuse verified transfer admission and byte/file accounting."""
    root = Path(directory).resolve(strict=True)
    files = sorted(root.rglob('*.parquet'))
    if not root.is_dir() or not files:
        raise ValueError('Choose a local directory containing Parquet files.')
    if transfer._allowance is None:
        raise RuntimeError('Configure the selected account and transfer allowance first.')
    if len(files) > transfer._allowance.max_files:
        raise ValueError('The selected files exceed --max-files.')
    if sum(f.stat().st_size for f in files) > transfer._allowance.upload_limit:
        raise ValueError('The selected files exceed --max-upload-bytes.')
    for file in files:
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError('Choose regular files inside the selected output directory.')
    for file in files:
        key = '/'.join(part for part in [prefix.strip('/'), file.relative_to(root).as_posix()] if part)
        if not transfer.upload_to_s3(file, 's3://' + bucket + '/' + key):
            return 1
    return 0


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upload', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('./data/population_h3'))
    parser.add_argument('--bucket')
    parser.add_argument('--account-id')
    parser.add_argument('--region')
    parser.add_argument('--prefix', default='h3_res8')
    parser.add_argument('--max-upload-bytes', type=int)
    parser.add_argument('--max-files', type=int, default=1000)
    parser.add_argument('--max-aws-requests', type=int, default=256)
    args = parser.parse_args(arguments)
    if not args.upload or args.dry_run:
        print('Population transfer: local plan only. See docs/CLOUD-COSTS.md.')
        return 0
    try:
        transfer.configure_cloud_transfer(bucket=args.bucket, account_id=args.account_id,
                                          region=args.region, download_bytes=1,
                                          upload_bytes=args.max_upload_bytes, max_files=args.max_files,
                                          max_aws_requests=args.max_aws_requests)
        return upload_directory(args.output, bucket=args.bucket, prefix=args.prefix)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        parser.error(str(error))


if __name__ == '__main__':
    raise SystemExit(main())
