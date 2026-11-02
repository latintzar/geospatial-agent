# Local examples and cloud accounts

The map example uses retained results, MapLibre and OpenStreetMap. It runs independently of model, AWS and Google Maps credentials. [Run the example](AGENT-SETUP.md#run-the-map-example).

For an original full-matrix comparison, use [Retail Location Similarity](https://github.com/latintzar/retail-location-similarity). Its CLI reads the retained London results or a local Parquet matrix. Its optional downloader verifies the original London file before installation.

## Historical global builds

The geographic feature-building and propagation code remains in `backend/etl/`. The six historical launch entries print a local plan, including their former EC2 and on-demand options. Their complete original code is preserved with hashes in [Historical cloud scripts](historical/cloud-build-scripts.md).

Direct invocations of `backend/etl/global/build_global_matrix.py` and `backend/scripts/precompute_population_h3.py` also print a local plan. Select `--execute` deliberately to run the retained computation on your chosen infrastructure and data. The population script's `--upload` path uses the same verified account and transfer allowances described below; `--max-download-bytes` applies to WorldPop downloads.

Global matrix output completion remains unverified. Commissioning a new build means selecting the account, dataset, resource limits, storage retention and termination deadline. The original instance types, images, resource names and price estimates remain part of the historical record.

## WorldPop transfer

Connected file transfer uses AWS CLI, `requests` and the existing `rio-cogeo` conversion tool in your installation.

Inspect the transfer locally:

```sh
python backend/scripts/upload_worldpop_to_s3.py ESP --dry-run
```

Actual transfer uses your AWS CLI credentials and an explicitly selected account, bucket and region:

```sh
python backend/scripts/upload_worldpop_to_s3.py ESP \
  --upload \
  --bucket YOUR_BUCKET \
  --account-id YOUR_12_DIGIT_ACCOUNT_ID \
  --region YOUR_REGION \
  --max-download-bytes 100000000 \
  --max-upload-bytes 100000000
```

Replace the account fields and choose byte allowances for your selected files. The command checks the caller's account and expected bucket owner before downloading data. The example allows 100 MB of input files and 100 MB of conservative upload attempts. Failed upload attempts consume the same allowance as a full attempt. Streams stop before writing a chunk that exceeds the input allowance.

| Control | Scope | Default |
| --- | --- | --- |
| `--max-download-bytes` | Input-file bytes written during this run; archive expansion also respects this ceiling | Explicit value |
| `--max-upload-bytes` | Conservative total size of upload attempts | Explicit value |
| `--max-countries` | Countries selected for this run | 1 |
| `--max-files` | Upload attempts and archive members | 1,000 |
| `--max-aws-requests` | AWS CLI invocations, including ownership checks | 256 |

Each CLI invocation sets `AWS_MAX_ATTEMPTS=1`. Multipart transfers can involve several requests. These limits bound the run's resources; your account's pricing and retained objects determine ongoing charges. Set object retention and account budgets for your installation. [AWS CLI retry controls](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-retries.html) and [S3 expected bucket owner](https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadBucket.html) describe the underlying controls.

## Connected queries

Connect each selected backend tool with your own credentials and data. Before enabling an Athena adapter, select an owned workgroup and enforce its per-query data-scan cutoff. Athena cancels a query when it exceeds that cutoff; scanned data and partial result storage can still incur charges. Set result retention and incomplete-upload cleanup on the output bucket. Workgroup aggregate thresholds send notifications, so account-level operating limits remain part of commissioning. [Athena data usage controls](https://docs.aws.amazon.com/athena/latest/ug/workgroups-setting-control-limits-cloudwatch.html).

Validate the local cloud admission and quota checks with:

```sh
python -m unittest discover -s tests -p test_cloud_cost_guards.py
```

The tests replace AWS and provider modules with fixtures and exercise the default, help, former launch, account mismatch and transfer allowance paths.
