"""Exercise cloud admission and transfer bounds without a provider connection."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = [
    'backend/etl/global/scripts/launch_global_build.sh',
    'backend/scripts/launch_ec2_workers.py',
    'backend/scripts/launch_matrix_build.sh',
    'backend/scripts/launch_matrix_builder.sh',
    'scripts/launch_london_build.sh',
    'backend/scripts/precompute_global.sh',
]
UPLOAD = ROOT / 'backend/scripts/upload_worldpop_to_s3.py'
POPULATION_UPLOAD = ROOT / 'backend/scripts/population_upload.py'


def uploader():
    specification = spec_from_file_location('worldpop_fixture', UPLOAD)
    module = module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class CloudLaunchAdmission(unittest.TestCase):
    def invoke(self, path, arguments, *, account='111111111111'):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            capture = directory / 'provider-calls'
            fake = directory / 'aws'
            fake.write_text('#!/bin/sh\nprintf "aws-called\\n" >> "$AWS_CAPTURE"\nprintf "%s\\n" "$FIXTURE_ACCOUNT"\nexit 0\n')
            fake.chmod(0o700)
            trap = 'import os\nfrom pathlib import Path\nPath(os.environ["AWS_CAPTURE"]).write_text("provider-imported")\nraise RuntimeError("Unexpected provider import")\n'
            (directory / 'requests.py').write_text(trap)
            (directory / 'boto3.py').write_text(trap)
            environment = {
                'PATH': str(directory) + os.pathsep + os.defpath,
                'PYTHONPATH': str(directory),
                'AWS_CAPTURE': str(capture),
                'FIXTURE_ACCOUNT': account,
                'AWS_ACCESS_KEY_ID': 'fixture-key',
                'AWS_SECRET_ACCESS_KEY': 'fixture-secret',
                'AWS_REGION': 'us-east-1',
            }
            command = [sys.executable if str(path).endswith('.py') else '/bin/bash', str(path), *arguments]
            result = subprocess.run(command, input='y\n', text=True,
                                    capture_output=True, env=environment, cwd=ROOT, timeout=5)
            calls = capture.read_text() if capture.exists() else ''
            return result, calls

    def test_all_launch_entries_plan_locally_with_configured_credentials(self):
        for path in LAUNCHERS:
            for arguments in [[], ['--dry-run'], ['--help'], ['-h']]:
                with self.subTest(path=path, arguments=arguments):
                    result, calls = self.invoke(ROOT / path, arguments)
                    self.assertEqual(calls, '')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('local plan only', result.stdout)

    def test_legacy_and_unexpected_provisioning_commands_fail_closed(self):
        arguments_list = [
            ['--on-demand'], ['--spot'], ['--launch'], ['--execute'],
            ['--instances', '10'], ['ec2', '10'], ['local'], ['upload'],
            ['--key-name', 'fixture'], ['--security-group', 'fixture'],
            ['--dry-run', '--on-demand'], ['--help', '--execute'],
            ['--unknown'], ['--region', 'us-east-1'], ['paris', '1,2,3,4'],
        ]
        for path in LAUNCHERS:
            for arguments in arguments_list:
                with self.subTest(path=path, arguments=arguments):
                    result, calls = self.invoke(ROOT / path, arguments)
                    self.assertEqual(calls, '')
                    self.assertEqual(result.returncode, 64, result.stdout + result.stderr)

    def test_upload_default_help_and_dry_run_resolve_everything_locally(self):
        for arguments in [[], ['--help'], ['--all'], ['--priority'], ['ESP'],
                          ['--all', '--dry-run'], ['--all', '--upload', '--dry-run']]:
            with self.subTest(arguments=arguments):
                result, calls = self.invoke(UPLOAD, arguments)
                self.assertEqual(calls, '')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_inner_matrix_and_population_defaults_precede_heavy_imports(self):
        for path in ['backend/etl/global/build_global_matrix.py', 'backend/scripts/precompute_population_h3.py']:
            for arguments in [[], ['--help'], ['--dry-run'], ['--all'], ['--test-mode'],
                              ['--execute', '--dry-run']]:
                with self.subTest(path=path, arguments=arguments):
                    result, calls = self.invoke(ROOT / path, arguments)
                    self.assertEqual(calls, '')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('local plan only', result.stdout)

    def test_population_upload_requires_an_owned_explicit_configuration(self):
        for path in [POPULATION_UPLOAD, ROOT / 'backend/scripts/precompute_population_h3.py']:
            result, calls = self.invoke(path, ['--upload'])
            self.assertEqual(calls, '')
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        for arguments in [[], ['--help'], ['--upload', '--dry-run']]:
            result, calls = self.invoke(POPULATION_UPLOAD, arguments)
            self.assertEqual(calls, '')
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_incomplete_or_invalid_upload_configuration_precedes_provider_access(self):
        for arguments in [['--upload'], ['ESP', '--upload'],
                          ['ESP', '--upload', '--bucket', 'fixture-owned'],
                          ['ESP', '--upload', '--bucket', 'fixture-owned', '--account-id', 'bad']]:
            with self.subTest(arguments=arguments):
                result, calls = self.invoke(UPLOAD, arguments)
                self.assertEqual(calls, '')
                self.assertEqual(result.returncode, 2)

    def test_account_mismatch_stops_before_data_access(self):
        result, calls = self.invoke(UPLOAD, [
            'ESP', '--upload', '--bucket', 'fixture-owned', '--account-id', '222222222222',
            '--region', 'us-east-1', '--max-download-bytes', '1000', '--max-upload-bytes', '1000',
        ])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(calls, 'aws-called\n')
        self.assertIn('Select credentials for the account', result.stderr)


class TransferBounds(unittest.TestCase):
    def setUp(self):
        self.module = uploader()
        self.module.S3_BUCKET = 'fixture-owned'
        self.module.AWS_ACCOUNT_ID = '222222222222'
        self.module.AWS_REGION = 'us-east-1'

    def test_account_and_bucket_owner_are_verified_before_transfer(self):
        good = subprocess.CompletedProcess([], 0, stdout='222222222222\n', stderr='')
        with mock.patch.object(self.module.subprocess, 'run', return_value=good) as run:
            self.module.verify_cloud_owner()
        self.assertTrue(self.module._account_verified)
        self.assertEqual(run.call_count, 2)
        self.assertIn('--expected-bucket-owner', run.call_args_list[1].args[0])
        self.assertEqual(run.call_args.kwargs['env']['AWS_MAX_ATTEMPTS'], '1')

    def test_bucket_mismatch_stays_unverified(self):
        account = subprocess.CompletedProcess([], 0, stdout='222222222222\n', stderr='')
        denied = subprocess.CompletedProcess([], 1, stdout='', stderr='fixture denied')
        with mock.patch.object(self.module.subprocess, 'run', side_effect=[account, denied]):
            with self.assertRaises(RuntimeError):
                self.module.verify_cloud_owner()
        self.assertFalse(self.module._account_verified)

    def test_cli_request_limit_precedes_next_provider_invocation(self):
        self.module._account_verified = True
        self.module.MAX_AWS_CALLS = 1
        good = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        with mock.patch.object(self.module.subprocess, 'run', return_value=good) as run:
            self.module._aws(['s3', 'ls', 's3://fixture-owned'])
            with self.assertRaises(ValueError):
                self.module._aws(['s3', 'ls', 's3://fixture-owned'])
        self.assertEqual(run.call_count, 1)

    def test_unverified_transfer_stops_before_provider_invocation(self):
        with mock.patch.object(self.module.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                self.module._aws(['s3', 'ls', 's3://fixture-owned'])
            run.assert_not_called()

    def test_known_country_scope_stops_before_account_access(self):
        arguments = ['uploader', 'ESP', 'FRA', '--upload', '--bucket', 'fixture-owned',
                     '--account-id', '222222222222', '--region', 'us-east-1',
                     '--max-download-bytes', '1000', '--max-upload-bytes', '1000']
        with mock.patch.object(sys, 'argv', arguments), mock.patch.object(self.module, 'verify_cloud_owner') as verify:
            with self.assertRaises(SystemExit) as stopped:
                self.module.main()
            self.assertEqual(stopped.exception.code, 2)
            verify.assert_not_called()

    def test_download_upload_and_file_counts_fail_at_allowance(self):
        allowance = self.module.TransferAllowance(10, 10, 1)
        allowance.download(6)
        with self.assertRaises(ValueError):
            allowance.download(5)
        allowance.upload(6)
        with self.assertRaises(ValueError):
            allowance.upload(1)
        self.assertEqual((allowance.downloaded, allowance.uploaded, allowance.files), (6, 6, 1))

    def test_oversized_file_stops_before_upload_invocation(self):
        self.module._allowance = self.module.TransferAllowance(10, 10)
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'sample'; file.write_bytes(b'x' * 11)
            with mock.patch.object(self.module, '_aws') as aws:
                self.assertFalse(self.module.upload_to_s3(file, 's3://fixture-owned/sample'))
                aws.assert_not_called()

    def test_failed_upload_consumes_conservative_allowance(self):
        self.module._allowance = self.module.TransferAllowance(10, 10)
        failed = subprocess.CompletedProcess([], 1, stdout='', stderr='fixture failure')
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'sample'; file.write_bytes(b'x' * 8)
            with mock.patch.object(self.module, '_aws', return_value=failed) as aws:
                self.assertFalse(self.module.upload_to_s3(file, 's3://fixture-owned/sample'))
                self.assertFalse(self.module.upload_to_s3(file, 's3://fixture-owned/sample'))
                self.assertEqual(aws.call_count, 1)
        self.assertEqual(self.module._allowance.uploaded, 8)

    def test_missing_length_stream_stops_before_writing_over_allowance(self):
        self.module._account_verified = True
        self.module._allowance = self.module.TransferAllowance(10, 10)
        response = types.SimpleNamespace(headers={}, raise_for_status=lambda: None,
                                         iter_content=lambda chunk_size: iter([b'123456', b'123456']))
        requests = types.SimpleNamespace(get=lambda *a, **kw: response)
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'sample'
            with mock.patch.dict(sys.modules, {'requests': requests}):
                self.assertFalse(self.module.download_file('https://fixture.invalid/file', file))
            self.assertEqual(file.read_bytes(), b'123456')

    def test_archive_expansion_is_bounded_before_extraction(self):
        self.module._allowance = self.module.TransferAllowance(512, 1000)
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'fixture.zip'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as file:
                file.writestr('oversized.tif', b'x' * 600)
            def download(url, destination, description):
                destination.write_bytes(archive.read_bytes())
                return True
            with mock.patch.object(self.module, 'check_s3_exists', return_value=False), mock.patch.object(self.module, 'download_file', side_effect=download):
                with self.assertRaises(ValueError):
                    self.module.process_country_agesex('ESP')

    def test_configured_country_transfer_reaches_existing_converter_path(self):
        arguments = ['uploader', 'ESP', '--upload', '--bucket', 'fixture-owned',
                     '--account-id', '222222222222', '--region', 'us-east-1',
                     '--max-download-bytes', '1000', '--max-upload-bytes', '1000']
        with mock.patch.object(sys, 'argv', arguments), mock.patch.object(self.module, 'verify_cloud_owner'), mock.patch.object(self.module, 'process_country_population', return_value=True) as process:
            self.assertEqual(self.module.main(), 0)
            process.assert_called_once_with('ESP', self.module.DEFAULT_YEAR, False)

    def test_country_metadata_failure_preserves_the_selected_transfer_scope(self):
        requests = types.SimpleNamespace(get=mock.Mock(side_effect=RuntimeError('fixture failure')))
        with mock.patch.dict(sys.modules, {'requests': requests}):
            with self.assertRaises(RuntimeError):
                self.module.get_all_countries()


if __name__ == '__main__':
    unittest.main()
