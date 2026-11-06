"""Tests for PayGate Module 4 dataset verification."""

import json
from pathlib import Path

import pytest

from backend.generator.config import load_config
from backend.generator.generate import generate_dataset
from backend.validation.dataset_checks import (
    validate_dataset,
    verify_reproducibility,
)
from scripts.validate_data import main


@pytest.fixture(scope="module")
def generated_starter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("paygate-validation") / "starter"
    generate_dataset(
        config=load_config(environment={}),
        employee_count=200,
        output_dir=output,
    )
    return output


def test_starter_dataset_passes_all_verification_checks(
    generated_starter: Path,
) -> None:
    report = validate_dataset(generated_starter, expected_size="starter")

    assert report.passed
    assert report.employee_count == 200
    assert report.label_count is not None and report.label_count > 0
    assert report.transaction_count is not None and report.transaction_count > 0
    assert all(check.passed for check in report.checks)


def test_checksum_mismatch_is_a_clear_failure_and_nonzero_exit(
    generated_starter: Path,
) -> None:
    manifest_path = generated_starter / "manifest.json"
    original = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(original)
    manifest["sha256"]["paygate.db"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        report = validate_dataset(generated_starter)
        checksum_check = next(
            check for check in report.checks if check.name == "manifest SHA-256 checksums"
        )
        assert not report.passed
        assert not checksum_check.passed
        assert "SHA-256 mismatch for paygate.db" in checksum_check.detail
        assert main([str(generated_starter), "--no-report"]) == 1
    finally:
        manifest_path.write_text(original, encoding="utf-8")


def test_reproducibility_check_generates_twice_and_compares_checksums() -> None:
    report = verify_reproducibility(seed=20261022, employee_count=200)

    assert report.passed
    assert report.seed == 20261022
    assert report.employee_count == 200
    assert "identical" in report.detail
    assert "paygate.db" in report.checksums
    assert "ground_truth/labels.csv" in report.checksums


def test_missing_dataset_manifest_fails() -> None:
    report = validate_dataset(Path("does-not-exist"))

    assert not report.passed
    assert report.checks[0].name == "manifest file"
    assert "cannot read" in report.checks[0].detail
