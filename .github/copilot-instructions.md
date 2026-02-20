# Copilot Instructions for Optibreed

## Project Overview

**Optibreed** is a Flask web application for analyzing animal pedigrees and calculating inbreeding coefficients (IBC). It helps breeders optimize mating selections by computing genetic relationships and predicting offspring inbreeding levels. The app is tailored for Hungarian livestock data with multilingual UI support.

## Architecture & Data Flow

### Core Components

1. **Flask App Factory** ([app/**init**.py](app/__init__.py))
   - Creates Flask instance with in-memory session storage
   - Registers main blueprint and configures 16MB file upload limit
   - Sessions stored as UUID-keyed dicts containing pedigree data and calculator instances

2. **Pedigree Calculation Engine** ([app/pedigree/calculator.py](app/pedigree/calculator.py))
   - `PedigreeCalculator`: Main class managing inbreeding calculations
   - Pre-calculates all Meuwissen-Luo IBCs at initialization (fast batch compute)
   - Caches path-based calculations on-demand (slower but exact)
   - String-based composite animal IDs (format: `COUNTRYCODE + EARTAG`, e.g., `HU7019140314`)

3. **Analysis Algorithms** ([app/pedigree/analysis/analyzer.py](app/pedigree/analysis/analyzer.py))
   - **Meuwissen-Luo (Tabular)**: Fast O(n²) matrix-based algorithm for all animals
   - **Path-based (Traditional)**: Slower recursive algorithm using ancestor path enumeration
   - Both methods used strategically: tabular for pre-calc, path for validation

4. **Request Handling** ([app/routes.py](app/routes.py))
   - CSV upload → DataFrame transformation → PedigreeCalculator initialization
   - Streaming SSE responses for long-running calculations (real-time progress)
   - Mating simulation: calculates coancestry between sire/dam pairs

### Data Flow: CSV → Calculation → Results

```
CSV Upload
  ↓
Rename/Clean Columns (Hungarian → English)
  ↓
Composite ID Creation (country_code + ear_tag)
  ↓
Validation (missing parents detection)
  ↓
PedigreeCalculator Init (pre-calculate Meuwissen-Luo cache)
  ↓
Session Storage (UUID key)
  ↓
IBC Calculation / Coancestry Computation
  ↓
HTML Template Rendering
```

## Critical Conventions

### Animal ID Handling

- **Must be strings**, not integers (recent refactor from numeric IDs)
- Composite format: `country_code.strip() + ear_tag.strip()`
- Missing parent IDs stored as `None` (not empty strings)
- All calculator methods expect string IDs: `calculator.get_inbreeding_meuwissen(str(animal_id))`

### DataFrame Structure

Required columns in processed pedigree:

```python
['animal_id', 'sire_id', 'dam_id', 'gender', 'birth_year', 'species', 'breed', 'farm']
```

- `sire_id` and `dam_id` can be `None` for founders
- All string types (except numeric gender/birth_year)
- NaN values replaced with `None` before calculator init

### CSV Column Mapping (Hungarian → Internal)

| CSV Input                  | Internal Name | Notes                          |
| -------------------------- | ------------- | ------------------------------ |
| `fulszam`                  | `animal_id`   | Ear tag (part of composite ID) |
| `orszagkod`                | (part of ID)  | Country code                   |
| `apafulszam` / `apaorsko`  | `sire_id`     | Sire composite ID              |
| `anyafulsza` / `anyaorsko` | `dam_id`      | Dam composite ID               |
| `szuletesi_ev`             | `birth_year`  | -                              |
| `ivar_kod`                 | `gender`      | 1→'M', 2→'F'                   |
| `faj`                      | `species`     | -                              |
| `fajta`                    | `breed`       | -                              |
| `tenyeszet`                | `farm`        | -                              |

### Performance Optimization Patterns

1. **Caching Strategy**:
   - Meuwissen-Luo: Pre-calculated once during `PedigreeCalculator.__init__()` → O(1) lookups
   - Path-based: Lazy-calculated with memoization via `F_path_cache` dict

2. **Ancestor Finding**:
   - BFS using `df_map` dict lookup (faster than repeated DataFrame searches)
   - Early termination when ancestor found (don't explore beyond)

3. **Coancestry Calculation**:
   - Uses fast Meuwissen-Luo for ancestor F-values (not recursive path method)
   - Iterates common ancestors and all path combinations

### Streaming Responses

For `/calculate_ibcs`: Server-Sent Events (SSE) pattern

- Yields progress updates as `data: {json}\n\n`
- Frontend updates UI in real-time with JavaScript event listener
- Critical for UX with large pedigrees (1000+ animals)

## Development Workflow

### Setup

```bash
source .venv/bin/activate  # Linux/Mac: activate venv
pip install -r requirements.txt
```

### Running

```bash
python main.py  # Runs on http://localhost:8080 (debug=True)
# Or use devserver.sh script for preview integration
```

### Adding Features

1. **New Routes**: Add to `app/routes.py`, register in blueprint
2. **New Calculations**: Extend `analyzer.py` module (keep pure functions for testability)
3. **Data Validation**: Add rules to `app/pedigree/validation/validator.py`
4. **HTML/JS Changes**: Modify templates in `app/templates/` and `app/templates/pedigree/`

## Request/Response Patterns

### Upload & Processing (`/upload_and_process`)

**Input**: CSV file upload with Hungarian column names

**Output**: JSON response with:

- `records`: DataFrame as list of dicts
- `animal_count`: Total animals in pedigree
- `load_time`: Processing time in seconds
- `missing_parents`: Parent IDs not found in pedigree
- `session_id`: UUID for session management

**Key Logic**:

- NaN values converted to `None` (not empty strings)
- Composite IDs: combines `orszagkod` + `fulszam` columns
- Missing parents tracked but doesn't fail the upload

### IBC Calculation (`/calculate_ibcs`)

**Transport**: Server-Sent Events (SSE)
**Events**: `data: {animal_id, ibc_meuwissen, ibc_traditional, progress}` per animal, then `event: complete` with calculation_time

**Query Parameters**:

- `session_id`: Required, UUID from upload response
- `algorithm`: One of `meuwissen`, `traditional`, or `both`

### Mating Simulation & Export

- `/simulation_results`: Form data (session_id, sire_ids, dam_ids) → HTML results table
- `/pedigree/export_results`: POST JSON pairings → Excel file with Hungarian headers
- Gender inference: If missing, derived from dam/sire relationships (F/M/U)

## Environment & Configuration

**Key Settings**:

- `MAX_CONTENT_LENGTH`: 16MB (file upload limit)
- `SECRET_KEY`: Required in `.env` file
- Session storage: In-memory dict (non-persistent, cleared on restart)
- Port: 8080 (Flask debug=True)

**Dependencies** (see requirements.txt):

- Flask: Web framework & blueprint routing
- pandas/numpy: Data processing & matrix operations
- openpyxl: Excel export functionality

## Common Pitfalls

1. **Numeric vs String IDs**: Always convert to string when querying calculator—this was recently refactored from int/float
2. **Skipped Parent Validation**: The app detects missing parents but doesn't fail—always check `missing_parents` in response
3. **Session Cleanup**: In-memory sessions persist across requests; add TTL logic if deploying long-running instances
4. **Column Name Case**: Input CSV columns are lowercased and whitespace-stripped—account for variations in external data
5. **NaN Handling**: Use `.replace({np.nan: None})` before passing DataFrames to calculator
6. **Error Response Language**: All error messages returned to frontend are in Hungarian

## Testing Reference

- `calculate_single_ibc.py`: Standalone script for single-animal IBC calculation testing
- `generate_pedigree.py`: Creates synthetic test pedigrees (10 founders, multi-farm structure)
- Sample CSVs in `app/pedigree/`: `sample_data.csv`, `ped20.csv`, `new_sample_data.csv`
- Test with complex pedigrees: `complex_pedigree_100.csv`, `inbred_sample.csv`
