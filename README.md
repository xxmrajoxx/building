# Tender Estimator (prototype)

A local web app for Australian building contractors that turns BIM models and PDF drawings into a
priced bill of quantities (BoQ) and a tender price.

```
IFC model ─┐
           ├─► takeoff (quantities) ─► rate matching ─► BoQ + markups ─► tender price ─► Excel
PDF set ───┘
```

> **Prototype.** The bundled rates in `data/rates_au.csv` and the location factors are indicative
> placeholders for testing the workflow, not market rates. Every quantity and rate must be checked by an
> estimator before anything is submitted.

## Setup (Windows)

Requires Python 3.10+ (developed on 3.13).

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe samples\make_samples.py      # optional: sample IFC + PDF to try
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Then open http://localhost:8501.

### Example drawing set

`samples\make_example_drawings.py` generates `samples\example_drawing_set.pdf`, six A3 tender sheets for a
15 × 10 m house: a cover, a floor plan with double-line walls, a roof plan, a slab and footing plan,
schedules, and a scanned copy of the plan. It prints an answer key so you can check the app's
measurements. For example, external walls measure 98.00 m as drawn (49.00 m halved), the slab is
150 m², and the roof is 181.44 m².

In PyCharm, set the project interpreter to `.venv\Scripts\python.exe` and create a run configuration
with module `streamlit` and parameters `run app.py`.

### Optional: AI-assisted PDF takeoff

The **AI-assisted** tool on the PDF tab sends the selected drawing pages to Claude (`claude-opus-5-5`),
which returns proposed quantities. Each item comes with its measurement basis and a confidence level.
It needs an Anthropic API key:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Each run is a paid API call, and the drawings are sent to Anthropic's API. Everything else runs fully
locally.

## Workflow

1. **Sidebar:** set the project details, location (applies a location factor), and the preliminaries,
   contingency, escalation, overheads, profit and GST percentages.
2. **① BIM model (IFC):** upload an IFC export. Quantities are grouped by element class, type and material:
   wall areas, concrete volumes, steel tonnage, door and window counts, and so on. The app uses the model's
   `Qto_*` base quantities where they were exported, and otherwise measures the element geometry.
   Reinforcement allowances (kg/m³) are added to concrete optionally. Tick the rows you want and add
   them to the takeoff.
3. **② PDF drawings:**
   - **Measure linework:** for vector PDFs exported from CAD. Paths are grouped by colour and line
     weight, and lengths and filled areas are converted to real metres at the drawing scale (auto-detected
     from "1:100" text). Select a group to highlight it on the sheet, then add it as a length, a wall area
     (length × height) or a volume (area × depth). Restrict the region to exclude title blocks.
   - **Schedules:** door, window and finish schedules drawn as ruled tables become counted items.
   - **AI-assisted:** see above. This is the main route for scanned drawings.
   - **Manual entry:** for anything else.
4. **③ Takeoff & rates:** edit any row, then use **Auto-match rates** to assign a rate to each row by unit,
   keywords, trade and IFC class. Override any match from the dropdown.
5. **④ Estimate:** the priced BoQ, trade summary and markups, with $/m² GFA. The tab warns about
   unpriced rows and likely double counting (for example, doors taken from both the IFC model and the
   PDF schedule). Download the **tender workbook** (.xlsx). In the workbook, amounts and totals are live
   formulas, so you can adjust rates and percentages in Excel.
6. **Rate library:** edit rates (material, labour, plant and waste %), then save them as your own library
   in `data/rates_custom.csv`, which git ignores. You can also import or export a CSV.

Use **Save project** and **Load project** in the sidebar to keep your work as a JSON file.

## Project layout

```
app.py                     Streamlit UI
estimator/
  models.py                takeoff schema, trades, units
  ifc_takeoff.py           IFC quantity extraction (IfcOpenShell)
  pdf_takeoff.py           PDF linework measurement, schedules, rendering (PyMuPDF, pdfplumber)
  ai_takeoff.py            optional Claude-based drawing takeoff
  rates.py                 rate library and auto-matching
  estimate.py              pricing and the markup cascade
  export.py                Excel tender workbook
  project_io.py            project save/load
data/
  rates_au.csv             sample rate library (indicative only)
  location_factors.csv     indicative regional factors
samples/make_samples.py    generates a sample IFC model and PDF drawing set
tests/                     pytest suite (run: .venv\Scripts\python.exe -m pytest)
```

## Known limitations

- **PDF linework** measures what is drawn. Walls drawn as two lines measure about twice their centreline
  (use the "halve" option), and hatching, dimensions and furniture all show up as groups. Always check one
  known dimension against the scale.
- **IFC quantities** are only as good as the model. Check for missing Qto exports, overlapping elements,
  and elements modelled with the wrong class.
- **Rate matching** is keyword-based. Review every assigned rate.
- Not yet included: measurement to AIQS/ASMM rules in detail, deductions for openings in PDF wall
  areas, revision comparison, subcontractor quote comparison, or multi-user storage.
