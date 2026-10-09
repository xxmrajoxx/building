import pytest

from estimator import pdf_takeoff
from estimator.ifc_takeoff import open_ifc, takeoff_ifc


def _row(df, contains, unit):
    rows = df[df["description"].str.contains(contains, regex=False) & (df["unit"] == unit)]
    assert len(rows) == 1, f"expected one {contains!r} {unit} row, got {len(rows)}"
    return rows.iloc[0]


def test_ifc_quantities_from_qto_and_geometry(sample_ifc):
    result = takeoff_ifc(open_ifc(sample_ifc))
    df = result.items
    # Qto path: 36 m perimeter x 2.7 m high
    assert _row(df, "Brick veneer", "m2")["quantity"] == pytest.approx(97.2)
    # Geometry path: (7.5 + 5.75) m x 2.7 m
    assert _row(df, "Stud partition", "m2")["quantity"] == pytest.approx(35.775, rel=1e-3)
    assert _row(df, "Ground slab", "m3")["quantity"] == pytest.approx(8.0, rel=1e-3)
    assert _row(df, "Ground slab", "m2")["quantity"] == pytest.approx(80.0, rel=1e-3)
    assert _row(df, "Reinforcement", "t")["quantity"] == pytest.approx(0.8, rel=1e-3)
    assert _row(df, "Roof", "m2")["trade"] == "Roofing"
    door = _row(df, "Internal hollow core door", "no")
    assert door["quantity"] == 3 and "820x2040" in door["description"]
    assert _row(df, "Aluminium window", "no")["quantity"] == 5
    assert result.gross_floor_area == pytest.approx(66.0)
    # Rooms are reported but not pre-selected, to avoid double counting finishes
    assert not df[df["ref"].str.startswith("IfcSpace")]["include"].any()


def test_ifc_split_by_storey_without_reo(sample_ifc):
    df = takeoff_ifc(open_ifc(sample_ifc), split_by_storey=True, include_reo=False).items
    assert not (df["trade"] == "Reinforcement").any()
    assert df[df["ref"].str.startswith("IfcWall")]["ref"].str.contains("Ground Floor").all()


def test_pdf_page_info(sample_pdf):
    info = pdf_takeoff.page_info(sample_pdf, 0)
    assert info["scales"] == [100]
    assert info["sheet_size"] == "A3"
    assert not info["looks_scanned"]


def test_pdf_linework_measured_at_scale(sample_pdf):
    groups, paths = pdf_takeoff.linework_groups(sample_pdf, 0, scale=100)
    by_colour = groups.set_index("colour")
    assert by_colour.loc["#000000", "length_m"] == pytest.approx(36.0, rel=1e-3)
    assert by_colour.loc["#cc0000", "length_m"] == pytest.approx(13.5, rel=1e-3)
    assert by_colour.loc["#d9d9d9", "area_m2"] == pytest.approx(80.0, rel=1e-3)
    assert all(g in paths for g in groups["group"])


def test_pdf_linework_scale_and_clip(sample_pdf):
    groups, _ = pdf_takeoff.linework_groups(sample_pdf, 0, scale=50)
    assert groups.set_index("colour").loc["#000000", "length_m"] == pytest.approx(18.0, rel=1e-3)
    # The plan sits in the left half of the sheet; clipping to the right half removes it
    clipped, _ = pdf_takeoff.linework_groups(sample_pdf, 0, scale=100, clip=(0.5, 0, 1, 1))
    assert clipped.empty


def test_detect_scales():
    assert pdf_takeoff.detect_scales("PLAN 1:100 @ A1  DETAIL 1 : 20  ratio 1:7") == [100, 20]


def test_render_page_with_highlight(sample_pdf):
    groups, paths = pdf_takeoff.linework_groups(sample_pdf, 0, scale=100)
    png = pdf_takeoff.render_page(sample_pdf, 0, zoom=0.5, highlight=paths[groups["group"][0]])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_schedule_extraction(sample_pdf):
    tables = pdf_takeoff.extract_tables(sample_pdf, 1)
    assert len(tables) == 1
    items = {i["description"]: i for i in pdf_takeoff.schedule_to_items(tables[0], 1)}
    assert items["Internal hollow core door 820x2040"]["quantity"] == 3
    assert items["Internal hollow core door 820x2040"]["trade"] == "Doors & Hardware"
    assert items["Aluminium window 1200x1200"]["trade"] == "Windows & Glazing"
    assert items["Aluminium sliding door 2400x2100"]["trade"] == "Windows & Glazing"
