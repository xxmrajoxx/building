import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "samples"))

import make_samples  # noqa: E402


@pytest.fixture(scope="session")
def sample_ifc(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("ifc") / "house.ifc"
    make_samples.make_ifc(path)
    return path.read_bytes()


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("pdf") / "plans.pdf"
    make_samples.make_pdf(path)
    return path.read_bytes()
