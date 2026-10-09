"""Headless smoke tests of the Streamlit app."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from estimator.ifc_takeoff import open_ifc, takeoff_ifc
from estimator.models import clean_takeoff

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_starts_empty():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "Tender Estimator"


def test_app_prices_a_takeoff(sample_ifc):
    items = takeoff_ifc(open_ifc(sample_ifc)).items
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["takeoff"] = clean_takeoff(items[items["include"]].drop(columns="include"))
    at.session_state["takeoff_version"] = 1
    at.run()
    assert not at.exception

    [b for b in at.button if b.label == "Auto-match rates"][0].click().run()
    assert not at.exception
    assert (at.session_state["takeoff"]["rate_code"] != "").all()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Tender price (inc GST)"].startswith("$")
    assert metrics["Tender price (inc GST)"] != "$0"


class _FakeUpload:
    def __init__(self, data: bytes, name: str):
        self._data, self.name, self.file_id = data, name, name

    def getvalue(self) -> bytes:
        return self._data


def test_upload_tabs_render(sample_ifc, sample_pdf, monkeypatch):
    """AppTest can't upload files, so stub the uploader to return the samples."""
    import streamlit as st

    uploads = {"ifc_upload": _FakeUpload(sample_ifc, "house.ifc"), "pdf_upload": _FakeUpload(sample_pdf, "plans.pdf")}
    real = st.file_uploader
    monkeypatch.setattr(st, "file_uploader", lambda *a, key=None, **k: uploads.get(key) or real(*a, key=key, **k))

    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    add = [b for b in at.button if b.label.startswith("Add ") and "selected" in b.label][0]
    add.click().run()
    assert not at.exception
    assert len(at.session_state["takeoff"]) > 5
    # Linework table and schedule tool rendered for page 1
    assert any("length (m)" in str(df.value.columns.tolist()) or "length_m" in df.value.columns for df in at.dataframe)
