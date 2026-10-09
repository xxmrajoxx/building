"""Tender estimator prototype - Streamlit UI.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from estimator import ai_takeoff, export, pdf_takeoff, project_io
from estimator.estimate import EstimateSettings, build_lines, possible_duplicates, summarise
from estimator.ifc_takeoff import open_ifc, takeoff_ifc
from estimator.models import TRADES, UNITS, append_items, clean_takeoff, empty_takeoff, new_item
from estimator.rates import (
    CUSTOM_RATES, DEFAULT_RATES, auto_match, clean_rates, load_location_factors, load_rates, save_rates,
    with_unit_rates,
)

st.set_page_config(page_title="Tender Estimator", page_icon="🏗️", layout="wide")

ss = st.session_state
LOCATIONS = load_location_factors()


# ---------------------------------------------------------------- state

def init_state() -> None:
    ss.setdefault("takeoff", empty_takeoff())
    ss.setdefault("takeoff_version", 0)
    ss.setdefault("rates", load_rates())
    ss.setdefault("rates_version", 0)
    defaults = EstimateSettings()
    for key, value in {
        "p_name": "", "p_client": "", "p_address": "", "p_date": "", "p_gfa": 0.0,
        "s_location": defaults.location, "s_factor": LOCATIONS.get(defaults.location, 1.0),
        "s_prelims": defaults.preliminaries_pct, "s_contingency": defaults.contingency_pct,
        "s_escalation": defaults.escalation_pct, "s_overhead": defaults.overhead_pct,
        "s_profit": defaults.profit_pct, "s_gst": defaults.gst_pct,
    }.items():
        ss.setdefault(key, value)


def current_takeoff() -> pd.DataFrame:
    """The takeoff including any edits made in the grid this session."""
    return ss.get("takeoff_edited", ss.takeoff)


def set_takeoff(df: pd.DataFrame) -> None:
    # Replacing the grid's data needs a fresh widget key, otherwise Streamlit
    # re-applies the old grid's pending edits to the new rows.
    ss.takeoff = clean_takeoff(df)
    ss.pop("takeoff_edited", None)
    ss.takeoff_version += 1


def add_to_takeoff(items: list[dict]) -> None:
    if not items:
        st.toast("Nothing selected to add.")
        return
    set_takeoff(append_items(current_takeoff(), items))
    st.toast(f"Added {len(items)} item(s) to the takeoff.", icon="✅")


def current_rates() -> pd.DataFrame:
    return ss.get("rates_edited", ss.rates)


def set_rates(df: pd.DataFrame) -> None:
    ss.rates = clean_rates(df)
    ss.pop("rates_edited", None)
    ss.rates_version += 1


def project_info() -> dict:
    return {"name": ss.p_name, "client": ss.p_client, "address": ss.p_address,
            "tender_date": ss.p_date, "gfa_m2": ss.p_gfa}


def settings() -> EstimateSettings:
    return EstimateSettings(
        location=ss.s_location, location_factor=ss.s_factor, preliminaries_pct=ss.s_prelims,
        contingency_pct=ss.s_contingency, escalation_pct=ss.s_escalation, overhead_pct=ss.s_overhead,
        profit_pct=ss.s_profit, gst_pct=ss.s_gst,
    )


def on_location_change() -> None:
    ss.s_factor = LOCATIONS.get(ss.s_location, 1.0)


def on_project_upload() -> None:
    upload = ss.get("project_upload")
    if upload is None:
        return
    try:
        project, s, takeoff = project_io.load_project(upload.getvalue())
    except (ValueError, KeyError) as e:
        ss.load_error = f"Could not load project: {e}"
        return
    ss.p_name, ss.p_client = project.get("name", ""), project.get("client", "")
    ss.p_address, ss.p_date = project.get("address", ""), project.get("tender_date", "")
    ss.p_gfa = float(project.get("gfa_m2", 0.0) or 0.0)
    ss.s_location = s.location if s.location in LOCATIONS else "Sydney"
    ss.s_factor, ss.s_prelims, ss.s_contingency = s.location_factor, s.preliminaries_pct, s.contingency_pct
    ss.s_escalation, ss.s_overhead, ss.s_profit, ss.s_gst = s.escalation_pct, s.overhead_pct, s.profit_pct, s.gst_pct
    set_takeoff(takeoff)
    ss.load_error = None


def money(x: float) -> str:
    return f"${x:,.0f}"


# ---------------------------------------------------------------- cached work

@st.cache_data(show_spinner="Reading IFC model...", max_entries=4)
def cached_ifc(data: bytes, split: bool, reo: bool):
    return takeoff_ifc(open_ifc(data), split_by_storey=split, include_reo=reo)


@st.cache_data(max_entries=8)
def cached_page_count(pdf: bytes) -> int:
    return pdf_takeoff.page_count(pdf)


@st.cache_data(max_entries=64)
def cached_page_info(pdf: bytes, page: int) -> dict:
    return pdf_takeoff.page_info(pdf, page)


@st.cache_data(show_spinner="Measuring linework...", max_entries=32)
def cached_linework(pdf: bytes, page: int, scale: float, clip: tuple, min_len: float):
    return pdf_takeoff.linework_groups(pdf, page, scale, clip=clip, min_length_m=min_len)


@st.cache_data(show_spinner="Reading tables...", max_entries=32)
def cached_tables(pdf: bytes, page: int) -> list[pd.DataFrame]:
    return pdf_takeoff.extract_tables(pdf, page)


# ---------------------------------------------------------------- sidebar

def sidebar() -> None:
    with st.sidebar:
        st.header("Project")
        st.text_input("Project name", key="p_name")
        st.text_input("Client", key="p_client")
        st.text_input("Site address", key="p_address")
        st.text_input("Tender due date", key="p_date", placeholder="e.g. 30/11/2026")
        st.number_input("Gross floor area (m²)", min_value=0.0, step=10.0, key="p_gfa",
                        help="Used for the $/m² rate on the Estimate tab.")

        st.header("Pricing")
        st.selectbox("Location", list(LOCATIONS), key="s_location", on_change=on_location_change)
        st.number_input("Location factor", min_value=0.5, max_value=2.0, step=0.01, key="s_factor",
                        help="Multiplies all rates. Defaults are indicative only.")
        c1, c2 = st.columns(2)
        c1.number_input("Prelims %", 0.0, 50.0, step=0.5, key="s_prelims")
        c2.number_input("Contingency %", 0.0, 50.0, step=0.5, key="s_contingency")
        c1.number_input("Escalation %", 0.0, 50.0, step=0.5, key="s_escalation")
        c2.number_input("Overheads %", 0.0, 50.0, step=0.5, key="s_overhead")
        c1.number_input("Profit %", 0.0, 50.0, step=0.5, key="s_profit")
        c2.number_input("GST %", 0.0, 20.0, step=0.5, key="s_gst")

        st.header("Save / load")
        st.download_button(
            "Save project (.json)",
            project_io.dump_project(project_info(), settings(), current_takeoff()),
            file_name=f"{(ss.p_name or 'project').strip().replace(' ', '_')}.json",
            mime="application/json", width="stretch",
        )
        st.file_uploader("Load project", type=["json"], key="project_upload", on_change=on_project_upload)
        if ss.get("load_error"):
            st.error(ss.load_error)


# ---------------------------------------------------------------- IFC tab

def ifc_tab() -> None:
    st.subheader("Quantities from a BIM model")
    st.caption(
        "Upload an IFC export (Revit, ArchiCAD, Tekla and others). Quantities come from the model's base quantities "
        "where exported, otherwise from the element geometry. Tick the rows to bring into the takeoff."
    )
    up = st.file_uploader("IFC model", type=["ifc"], key="ifc_upload")
    c1, c2 = st.columns(2)
    split = c1.checkbox("Split quantities by storey", value=False)
    reo = c2.checkbox("Add reinforcement allowances (kg/m³ of concrete)", value=True)
    if up is None:
        return
    try:
        result = cached_ifc(up.getvalue(), split, reo)
    except Exception as e:  # malformed IFC files raise a variety of errors
        st.error(f"Could not read this IFC file: {e}")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Schema", result.schema)
    m2.metric("Storeys", len(result.storeys))
    m3.metric("Elements measured", sum(result.element_counts.values()))
    m4.metric("Room floor area", f"{result.gross_floor_area:,.1f} m²")
    for w in result.warnings:
        st.warning(w)
    with st.expander("Element counts by IFC class"):
        st.dataframe(pd.DataFrame(result.element_counts.items(), columns=["IFC class", "count"]), hide_index=True)
    if result.gross_floor_area:
        st.button("Use room floor area as project GFA", on_click=lambda: ss.update(p_gfa=float(result.gross_floor_area)))

    edited = st.data_editor(
        result.items,
        hide_index=True, width="stretch", key=f"ifc_editor_{up.file_id}_{split}_{reo}",
        disabled=["unit", "quantity", "source", "ref", "confidence", "id", "rate_code", "notes"],
        column_order=["include", "trade", "description", "unit", "quantity", "confidence", "ref"],
        column_config={
            "include": st.column_config.CheckboxColumn("Add", width="small"),
            "trade": st.column_config.SelectboxColumn("Trade", options=TRADES),
            "description": st.column_config.TextColumn("Description", width="large"),
            "quantity": st.column_config.NumberColumn("Qty", format="%.2f"),
        },
    )
    selected = edited[edited["include"]].drop(columns="include")
    st.button(
        f"Add {len(selected)} selected item(s) to takeoff", type="primary",
        on_click=add_to_takeoff, args=(selected.to_dict("records"),),
    )


# ---------------------------------------------------------------- PDF tab

def pdf_tab() -> None:
    st.subheader("Quantities from PDF drawings")
    up = st.file_uploader("Drawing set (PDF)", type=["pdf"], key="pdf_upload")
    if up is None:
        st.caption(
            "Vector PDFs exported from CAD can be measured by line colour and weight. Schedules are read from "
            "ruled tables. Scanned drawings need the AI-assisted takeoff or manual entry."
        )
        return
    pdf = up.getvalue()
    try:
        n_pages = cached_page_count(pdf)
    except Exception as e:
        st.error(f"Could not open this PDF: {e}")
        return

    top = st.columns([1, 1, 3])
    page = int(top[0].number_input("Page", 1, n_pages, 1, key=f"pdf_page_{up.file_id}")) - 1
    zoom = top[1].select_slider("Preview zoom", [0.75, 1.0, 1.5, 2.0, 3.0], value=1.5)
    info = cached_page_info(pdf, page)
    scale_txt = ", ".join(f"1:{s}" for s in info["scales"]) or "none found"
    top[2].markdown(
        f"**Sheet** {info['sheet_size']} · **Scales in text** {scale_txt} · **Vector paths** {info['vector_paths']:,}"
    )
    if info["looks_scanned"]:
        st.warning("This page looks scanned (no vector linework or text). Use the AI-assisted takeoff or manual entry.")

    left, right = st.columns([3, 2], gap="large")
    highlight = None
    with right:
        t_line, t_sched, t_ai, t_manual = st.tabs(["Measure linework", "Schedules", "AI-assisted", "Manual entry"])
        with t_line:
            highlight = linework_tool(pdf, page, info)
        with t_sched:
            schedule_tool(pdf, page)
        with t_ai:
            ai_tool(pdf, page, n_pages)
        with t_manual:
            manual_tool(page)
    with left:
        st.image(pdf_takeoff.render_page(pdf, page, zoom, highlight=highlight), width="stretch")


def linework_tool(pdf: bytes, page: int, info: dict):
    c1, c2 = st.columns(2)
    default_scale = float(info["scales"][0]) if info["scales"] else 100.0
    scale = c1.number_input("Drawing scale 1:", min_value=1.0, value=default_scale, step=10.0,
                            key=f"scale_{page}_{default_scale}",
                            help="Check against a known dimension before trusting the numbers.")
    min_len = c2.number_input("Hide groups shorter than (m)", 0.0, value=1.0, step=1.0)
    with st.expander("Measure region (exclude title block and legend)"):
        xr = st.slider("Horizontal extent (%)", 0, 100, (0, 100), key=f"xr_{page}")
        yr = st.slider("Vertical extent (%)", 0, 100, (0, 100), key=f"yr_{page}")
    clip = (xr[0] / 100, yr[0] / 100, xr[1] / 100, yr[1] / 100)
    groups, paths = cached_linework(pdf, page, scale, clip, min_len)
    if groups.empty:
        st.info("No vector linework found on this page.")
        return None

    st.caption("Select a group to highlight it on the drawing.")
    event = st.dataframe(
        groups.drop(columns="group"), hide_index=True, width="stretch", height=240,
        on_select="rerun", selection_mode="single-row", key=f"groups_{page}_{scale}_{clip}",
        column_config={"length_m": st.column_config.NumberColumn("length (m)", format="%.2f"),
                       "area_m2": st.column_config.NumberColumn("area (m²)", format="%.2f")},
    )
    rows = event.selection.rows
    if not rows:
        return None
    g = groups.iloc[rows[0]]
    is_stroke = g["kind"] == "stroke"
    base = float(g["length_m"] if is_stroke else g["area_m2"])

    with st.form(f"line_add_{page}_{g['group']}"):
        st.markdown(f"**Selected:** {g['kind']} {g['colour']} · " +
                    (f"{base:,.2f} m" if is_stroke else f"{base:,.2f} m²"))
        if is_stroke:
            mode = st.radio("Measure as", ["Length (m)", "Wall area: length × height (m²)"], horizontal=True)
            halve = st.checkbox("Double-line walls: halve the length",
                                help="Walls drawn as two lines (one per face) measure about twice the centreline.")
            height = st.number_input("Height (m)", 0.0, value=2.7, step=0.1)
        else:
            mode = st.radio("Measure as", ["Area (m²)", "Volume: area × depth (m³)"], horizontal=True)
            halve = False
            height = st.number_input("Depth / thickness (m)", 0.0, value=0.1, step=0.05)
        trade = st.selectbox("Trade", TRADES, index=TRADES.index("Masonry" if is_stroke else "Concrete"))
        desc = st.text_input("Description", placeholder="e.g. Brick veneer external wall 110mm")
        if st.form_submit_button("Add to takeoff", type="primary"):
            length = base / 2 if halve else base
            if mode.startswith("Length"):
                unit, qty = "m", length
            elif mode.startswith("Wall area"):
                unit, qty = "m2", length * height
            elif mode.startswith("Area"):
                unit, qty = "m2", base
            else:
                unit, qty = "m3", base * height
            note = f"{g['kind']} {g['colour']} w{g['line_weight']}" + (" halved" if halve else "")
            add_to_takeoff([new_item(
                trade, desc or f"Measured {g['kind']} {g['colour']}", unit, qty, source="PDF linework",
                ref=f"PDF p.{page + 1} @1:{scale:g}", confidence="medium", notes=note,
            )])
    return paths.get(g["group"])


def schedule_tool(pdf: bytes, page: int) -> None:
    tables = cached_tables(pdf, page)
    if not tables:
        st.info("No ruled tables found on this page. Schedules drawn without grid lines may need manual entry.")
        return
    for i, table in enumerate(tables):
        st.markdown(f"**Table {i + 1}** ({len(table)} rows)")
        st.dataframe(table, hide_index=True, width="stretch")
        items = pdf_takeoff.schedule_to_items(table, page, i)
        if items:
            st.dataframe(pd.DataFrame(items)[["trade", "description", "unit", "quantity"]], hide_index=True,
                         width="stretch")
            st.button(f"Add {len(items)} item(s) from table {i + 1}", key=f"sched_add_{page}_{i}",
                      on_click=add_to_takeoff, args=(items,))
        else:
            st.caption("Couldn't identify type/description columns in this table; enter these manually.")


def ai_tool(pdf: bytes, page: int, n_pages: int) -> None:
    st.caption(
        "Claude reads the selected pages and proposes a takeoff, with the measurement basis for each item. "
        "Treat it as a first pass to check. Each run is a paid API call."
    )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.info("Set the ANTHROPIC_API_KEY environment variable before starting the app to enable this (see README).")
    pages = st.multiselect("Pages", list(range(1, n_pages + 1)), default=[page + 1], key=f"ai_pages_{n_pages}")
    instructions = st.text_area(
        "Instructions (optional)",
        placeholder="e.g. Measure external walls, slab and roof only. Walls are 230mm brick veneer. Ceiling height 2.7m.",
    )
    effort = st.select_slider("Effort", ["low", "medium", "high", "xhigh"], value="high",
                              help="Higher effort is slower and costs more, but is more thorough.")
    if st.button("Run AI takeoff", type="primary"):
        with st.spinner("Claude is reading the drawings (this can take a few minutes)..."):
            try:
                ss.ai_result = ai_takeoff.ai_takeoff(pdf, [p - 1 for p in pages], instructions, effort)
            except ai_takeoff.AITakeoffError as e:
                st.error(str(e))
                return

    result = ss.get("ai_result")
    if not result:
        return
    st.markdown(f"**Summary:** {result['summary']}")
    st.markdown(f"**Scale:** {result['scale_notes']}")
    if result["assumptions"]:
        with st.expander(f"Assumptions and gaps ({len(result['assumptions'])})", expanded=True):
            for a in result["assumptions"]:
                st.markdown(f"- {a}")
    df = pd.DataFrame(result["items"])
    if df.empty:
        st.info("No items were returned.")
        return
    df.insert(0, "include", df["confidence"] != "low")
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key=f"ai_editor_{id(result)}",
        column_order=["include", "trade", "description", "unit", "quantity", "confidence", "notes", "ref"],
        column_config={
            "include": st.column_config.CheckboxColumn("Add", width="small"),
            "trade": st.column_config.SelectboxColumn("Trade", options=TRADES),
            "unit": st.column_config.SelectboxColumn("Unit", options=UNITS),
            "notes": st.column_config.TextColumn("Basis", width="large"),
        },
    )
    sel = edited[edited["include"]].drop(columns="include")
    st.caption(f"Tokens: {result['usage']['input_tokens']:,} in / {result['usage']['output_tokens']:,} out. "
               "Low-confidence items are unticked by default.")
    st.button(f"Add {len(sel)} item(s) to takeoff", key="ai_add", on_click=add_to_takeoff,
              args=(sel.to_dict("records"),))


def manual_tool(page: int) -> None:
    with st.form("manual_entry", clear_on_submit=True):
        trade = st.selectbox("Trade", TRADES)
        desc = st.text_input("Description")
        c1, c2 = st.columns(2)
        qty = c1.number_input("Quantity", 0.0, step=1.0)
        unit = c2.selectbox("Unit", UNITS, index=UNITS.index("m2"))
        ref = st.text_input("Reference", value=f"PDF p.{page + 1}")
        notes = st.text_input("Notes / measurement basis")
        if st.form_submit_button("Add to takeoff", type="primary"):
            if not desc or qty <= 0:
                st.error("Enter a description and a quantity above zero.")
            else:
                add_to_takeoff([new_item(trade, desc, unit, qty, source="Manual", ref=ref, notes=notes)])


# ---------------------------------------------------------------- takeoff tab

def takeoff_tab() -> None:
    st.subheader("Takeoff and rate assignment")
    rates = current_rates()
    rate_lookup = {r["code"]: r for _, r in with_unit_rates(rates).iterrows()}

    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    if c1.button("Auto-match rates", type="primary", help="Assigns rates to rows without one."):
        set_takeoff(auto_match(current_takeoff(), rates))
        st.rerun()
    if c2.button("Re-match all rows"):
        set_takeoff(auto_match(current_takeoff(), rates, overwrite=True))
        st.rerun()
    if c3.button("Clear takeoff"):
        set_takeoff(empty_takeoff())
        st.rerun()

    if ss.takeoff.empty and "takeoff_edited" not in ss:
        st.info("The takeoff is empty. Add quantities from the BIM or PDF tabs, or add rows directly below.")

    def fmt_rate(code):
        r = rate_lookup.get(code)
        return f"{code} · {r['description'][:45]} (${r['unit_rate']:,.2f}/{r['unit']})" if r is not None else (code or "")

    edited = st.data_editor(
        ss.takeoff,
        key=f"takeoff_editor_{ss.takeoff_version}",
        num_rows="dynamic", hide_index=True, width="stretch", height=480,
        column_order=["trade", "description", "unit", "quantity", "rate_code", "source", "confidence", "ref", "notes"],
        column_config={
            "trade": st.column_config.SelectboxColumn("Trade", options=TRADES, required=True),
            "description": st.column_config.TextColumn("Description", width="large", required=True),
            "unit": st.column_config.SelectboxColumn("Unit", options=UNITS, required=True, width="small"),
            "quantity": st.column_config.NumberColumn("Qty", format="%.2f", min_value=0.0),
            "rate_code": st.column_config.SelectboxColumn(
                "Rate", options=[""] + list(rate_lookup), format_func=fmt_rate, width="large"),
            "source": st.column_config.TextColumn("Source", disabled=True),
            "confidence": st.column_config.SelectboxColumn("Confidence", options=["high", "medium", "low"]),
            "ref": st.column_config.TextColumn("Reference"),
            "notes": st.column_config.TextColumn("Notes"),
        },
    )
    ss.takeoff_edited = clean_takeoff(edited)

    df = ss.takeoff_edited
    if not df.empty:
        unassigned = int((df["rate_code"] == "").sum())
        mismatched = sum(
            1 for _, r in df.iterrows()
            if r["rate_code"] in rate_lookup and rate_lookup[r["rate_code"]]["unit"] != r["unit"]
        )
        low = int((df["confidence"] == "low").sum())
        st.caption(f"{len(df)} rows · {unassigned} without a rate · {mismatched} with a unit mismatch · "
                   f"{low} low-confidence")


# ---------------------------------------------------------------- estimate tab

def estimate_tab() -> None:
    st.subheader("Tender estimate")
    s = settings()
    takeoff = current_takeoff()
    if takeoff.empty:
        st.info("Nothing to price yet.")
        return
    lines = build_lines(takeoff, current_rates(), s.location_factor)
    summary = summarise(lines, s)

    m = st.columns(4)
    m[0].metric("Direct trade costs", money(summary["direct"]))
    m[1].metric("Tender price (ex GST)", money(summary["total_ex_gst"]))
    m[2].metric("Tender price (inc GST)", money(summary["total_inc_gst"]))
    m[3].metric("Rate per m² GFA (ex GST)", money(summary["total_ex_gst"] / ss.p_gfa) if ss.p_gfa else "set GFA")

    if summary["unpriced_count"]:
        st.warning(f"{summary['unpriced_count']} item(s) are not priced and are excluded from the total. "
                   "Assign rates on the Takeoff tab.")
        st.dataframe(lines[~lines["priced"]][["trade", "description", "unit", "quantity", "issue"]],
                     hide_index=True, width="stretch")
    dups = possible_duplicates(takeoff)
    if not dups.empty:
        st.warning("Possible double counting: the same rate, unit and quantity appears from more than one source.")
        st.dataframe(dups[["trade", "description", "unit", "quantity", "rate_code", "source"]], hide_index=True,
                     width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**By trade**")
        st.dataframe(summary["by_trade"], hide_index=True, width="stretch",
                     column_config={"amount": st.column_config.NumberColumn("Amount", format="dollar")})
    with c2:
        st.markdown("**Markups**")
        st.dataframe(summary["cascade"], hide_index=True, width="stretch",
                     column_config={"amount": st.column_config.NumberColumn("Amount", format="dollar")})

    st.markdown("**Bill of quantities**")
    st.dataframe(
        lines[["trade", "description", "unit", "quantity", "rate", "amount", "rate_code", "source", "ref"]],
        hide_index=True, width="stretch",
        column_config={
            "quantity": st.column_config.NumberColumn("Qty", format="%.2f"),
            "rate": st.column_config.NumberColumn("Rate", format="dollar"),
            "amount": st.column_config.NumberColumn("Amount", format="dollar"),
        },
    )
    name = (ss.p_name or "estimate").strip().replace(" ", "_")
    d1, d2, _ = st.columns([1, 1, 3])
    d1.download_button(
        "Download tender workbook (.xlsx)", export.to_excel(project_info(), s, lines, takeoff),
        file_name=f"{name}_estimate.xlsx", type="primary",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    d2.download_button("Download BoQ (.csv)", lines.to_csv(index=False), file_name=f"{name}_boq.csv", mime="text/csv")


# ---------------------------------------------------------------- rates tab

def rates_tab() -> None:
    st.subheader("Rate library")
    st.warning(
        "The bundled rates are indicative placeholders for testing the workflow, not current market rates. "
        "Replace them with your own rates, supplier prices and subcontractor quotes before pricing a tender.",
        icon="⚠️",
    )
    source = "your saved library" if CUSTOM_RATES.exists() else "the bundled sample library"
    st.caption(f"Loaded from {source}. Unit rate = material × (1 + waste%) + labour + plant, before location factor.")

    edited = st.data_editor(
        ss.rates, key=f"rates_editor_{ss.rates_version}", num_rows="dynamic", hide_index=True,
        width="stretch", height=480,
        column_config={
            "trade": st.column_config.SelectboxColumn("Trade", options=TRADES),
            "unit": st.column_config.SelectboxColumn("Unit", options=UNITS),
            "material": st.column_config.NumberColumn("Material $", format="%.2f"),
            "labour": st.column_config.NumberColumn("Labour $", format="%.2f"),
            "plant": st.column_config.NumberColumn("Plant $", format="%.2f"),
            "waste_pct": st.column_config.NumberColumn("Waste %", format="%.1f"),
            "keywords": st.column_config.TextColumn("Match keywords", help="Words used to auto-match takeoff items."),
            "ifc_class": st.column_config.TextColumn("IFC classes", help="Semicolon-separated, e.g. IfcWall;IfcSlab"),
        },
    )
    ss.rates_edited = clean_rates(edited)

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Save as my rate library", type="primary"):
        save_rates(ss.rates_edited)
        st.toast(f"Saved to {CUSTOM_RATES.name}", icon="💾")
    if c2.button("Reset to bundled sample rates"):
        if CUSTOM_RATES.exists():
            CUSTOM_RATES.unlink()
        set_rates(load_rates(DEFAULT_RATES))
        st.rerun()
    c3.download_button("Download rates (.csv)", ss.rates_edited.to_csv(index=False), file_name="rates.csv")
    imported = c4.file_uploader("Import rates CSV", type=["csv"], label_visibility="collapsed")
    if imported is not None and ss.get("imported_rates_id") != imported.file_id:
        try:
            set_rates(clean_rates(pd.read_csv(imported, dtype=str)))
            ss.imported_rates_id = imported.file_id
            st.rerun()
        except Exception as e:
            st.error(f"Could not import rates: {e}")


# ---------------------------------------------------------------- main

def main() -> None:
    init_state()
    sidebar()
    st.title("Tender Estimator")
    st.caption("Prototype · quantity takeoff from BIM and PDF drawings → priced BoQ → tender price (AUD)")
    tabs = st.tabs(["① BIM model (IFC)", "② PDF drawings", "③ Takeoff & rates", "④ Estimate", "Rate library"])
    with tabs[0]:
        ifc_tab()
    with tabs[1]:
        pdf_tab()
    with tabs[2]:
        takeoff_tab()
    with tabs[3]:
        estimate_tab()
    with tabs[4]:
        rates_tab()


main()
