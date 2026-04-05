# Ruls

This document is the technical reference for User Inspector. It is written for engineers who need to understand the current architecture, preserve source-specific behavior, and extend the system without introducing regressions.

## 1. Architecture Overview

User Inspector is a single-file Streamlit application backed by pandas-based in-memory processing.

Project files with runtime importance:

- `app.py`: application entry point, parsing logic, UI, filtering, display shaping, and export
- `requirements.txt`: runtime dependencies
- `app.spec`: PyInstaller bundle configuration

The system has no backend service, database, or external API integration. All behavior is local to the running Streamlit process.

### Execution Flow

1. `main()` initializes page configuration and session state.
2. The upload section accepts a `.csv` or `.xlsx` file.
3. pandas reads the file into a DataFrame.
4. The app determines the source using required columns.
5. The relevant loader transforms the raw DataFrame.
6. The parsed DataFrame is stored in session state.
7. Search controls operate on the parsed dataset.
8. `get_display_df()` builds the final rendered table.
9. `render_results()` displays metrics, the table, and CSV export.

### Session State Model

Current session keys:

- `original_df`: full parsed dataset after source-specific transformation
- `filtered_df`: current filtered dataset
- `file_loaded`: boolean used to avoid unnecessary reloads
- `current_file_name`: used to detect file changes across uploads

## 2. Parsing System

The parsing system is split into two loaders and must remain source-specific.

- Prime uses `extract_user_info()` and `load_prime()`
- My Chips uses `extract_ids()` and `load_my_chips()`

Prime parsing is query-string based. My Chips parsing is identifier-splitting based. They are not interchangeable and should not be merged into a single generic parser.

### Prime Postback URL Parsing

Prime files are identified by the presence of `Postback URL`.

The exact parsing sequence in `extract_user_info(postback_url)` is:

1. cast the value to string
2. call `urlparse(str(postback_url))`
3. call `parse_qs(parsed.query)`
4. read the query parameters from `params`

This parsing pattern is intentionally consistent and should be preserved.

### Extraction of `offer_name`, `task_name`, and `status`

These fields are extracted exactly as follows:

- `offer_name = clean_value(params.get("offer_name", [""])[0])`
- `task_name = clean_value(params.get("task_name", [""])[0])`
- `status = clean_value(params.get("status", [""])[0])`

This is the current contract for Prime query-string extraction.

Do not replace it with:

- regex parsing
- manual string splitting of the full URL
- a second field-specific parser

If a new Prime query-string field is needed, the correct extension point is this same pattern.

### Parsing of `user`

`user` is handled separately from the optional descriptive fields.

Current behavior:

- `raw_user = params.get("user", [""])[0]`
- strip whitespace
- if `-` exists, split once into `app_id` and `user_id`
- otherwise keep `user_id = raw_user` and leave `app_id` empty

Because filtering depends on `app_id` and `user_id`, any changes here have broad downstream effects.

### Value Cleanup Rules

`clean_value()` performs lightweight normalization for optional extracted string fields.

Behavior:

- returns `None` if input is `None`
- strips whitespace
- returns `None` for empty strings
- returns `None` for the string `none`, case-insensitive
- otherwise returns the cleaned string

This function is currently applied to Prime fields such as `offer_name`, `task_name`, and `status`.

## 3. Data Transformation

### Prime Transformation

`load_prime(df)` performs the following transformation pipeline:

1. validate that `Postback URL` exists
2. copy the incoming DataFrame
3. apply `extract_user_info()` to each row in `Postback URL`
4. convert extracted dictionaries into columns with `.apply(pd.Series)`
5. concatenate parsed columns back onto the original DataFrame
6. normalize `app_id` and `user_id` using `normalize_id_columns()`
7. drop rows where either identifier is empty or the string `None`
8. fill missing `offer_name` with `—`
9. fill missing `task_name` with `—`
10. fill missing `status` with `""`

### My Chips Transformation

`load_my_chips(df)` performs the following transformation pipeline:

1. validate that `UserID` exists
2. copy the incoming DataFrame
3. apply `extract_ids()` to `UserID`
4. assign the two returned values to `app_id` and `user_id`
5. normalize both identifier columns
6. drop rows where either identifier is empty or the string `None`

### Column Mapping System

My Chips uses fallback mapping in `get_display_df()` instead of relying on a single fixed raw schema.

Current target mappings:

- `DateTime`: `DateTime`, `Datetime`, `date`
- `Payout`: `Payout`, `payout`
- `Country`: `Country`, `country`
- `EventName`: `EventName`, `event_name`, `type`
- `AppName`: `AppName`, `app`, `App`

The first matching source column is selected by `get_column(df, possible_names)`.

## 4. Source Separation

Prime and My Chips must remain separate because they represent different input models and different transformation contracts.

### Why Separation Matters

- Prime depends on query-string parsing from `Postback URL`
- My Chips depends on splitting `UserID`
- Prime output includes parsed URL fields
- My Chips output depends on fallback column-name mapping
- Prime and My Chips do not share the same raw schema guarantees

### Internal Handling

Source detection currently happens in `main()`:

- if `Postback URL` exists, call `load_prime(df_raw)`
- else if `UserID` exists, call `load_my_chips(df_raw)`
- else show an unrecognized file format error

This source boundary should remain explicit.

## 5. Column Rendering System

Column rendering is centralized in `get_display_df()`.

### Prime Rendering

Prime uses a fixed ordered list:

- `App`
- `user_id`
- `app_id`
- `Datetime`
- `Reward`
- `Payout`
- `status`
- `Type`
- `offer_name`
- `task_name`

Rendering behavior:

- keep only columns that appear in the approved list and exist in the DataFrame
- reindex to the full list
- fill missing columns with empty strings

This guarantees stable order for Prime output.

### My Chips Rendering

My Chips rendering builds a new DataFrame using normalized target keys:

- `user_id`
- `app_id`
- `DateTime`
- `Payout`
- `Country`
- `EventName`
- `AppName`

If a mapped source column is missing, the app inserts an empty output column instead of failing.

## 6. Constraints

These rules should be treated as hard constraints unless there is an intentional redesign.

- Do not break Prime parsing based on `Postback URL`.
- Do not replace the current `parse_qs` extraction pattern for Prime URL fields without a clear migration reason.
- Do not merge Prime and My Chips parsing paths into one generic loader.
- Do not change Prime column order casually.
- Do not change My Chips mapping behavior without considering backward compatibility for variant source schemas.
- Do not remove identifier normalization.
- Do not change exact-match filtering behavior unless product requirements explicitly change.
- Do not make the display table diverge from the export table without documenting that change.

## 7. Dependencies

### Runtime Dependencies

- `streamlit`: web UI framework, page lifecycle, widgets, dataframe rendering, download button, session state
- `pandas`: file loading, DataFrame transformation, filtering, concatenation, CSV serialization
- `openpyxl`: required Excel engine for `.xlsx` uploads
- `numpy`: transitive support dependency for pandas operations in the runtime environment
- `pillow`: runtime dependency often required by Streamlit packaging and UI support, even though it is not directly imported in `app.py`

### Standard Library Usage

- `urllib.parse`: `urlparse` and `parse_qs` for Prime query-string parsing
- `typing`: `List` and `Dict` type hints
- `datetime`: timestamp generation for download file names

### Packaging

- `app.spec`: PyInstaller specification used to build a bundled app from `app.py`

## 8. Extensibility Guide

### How to Add a New Prime Column

If the field comes from the postback query string:

1. extract it in `extract_user_info()` with the same `params.get("field_name", [""])[0]` pattern
2. apply `clean_value()` if the field should treat blank values as missing
3. return it in the extracted dictionary
4. fill missing values in `load_prime()` if the display needs a stable fallback
5. insert the new field into the Prime `visible_columns` list at the exact intended position

### How to Parse a New Field Safely

Preferred approach:

- reuse existing helpers
- preserve the current source boundary
- keep parsing changes local to the relevant loader

Avoid:

- introducing source-specific conditionals into unrelated display code
- renaming existing output fields unnecessarily
- bypassing `clean_value()` for optional Prime string fields if you want consistent blank handling

### How to Add a New Data Source

Recommended approach:

1. create a dedicated loader function
2. define a clear source detection rule in `main()`
3. keep source-specific parsing isolated to that loader
4. add a separate display branch in `get_display_df()` or a more formal source typing mechanism
5. update docs and examples after the new source is validated

## 9. Known Limitations

- Only `.csv` and `.xlsx` inputs are supported.
- Source detection depends on exact required column names.
- The current UI has no manual source selector.
- Prime rows are removed if the parsed identifiers are invalid.
- My Chips rows are removed if `UserID` does not contain a hyphen-separated identifier pair.
- Prime only parses a small fixed set of query-string fields: `offer_name`, `task_name`, and `status`.
- Filtering is exact-match only.
- The entire app operates in memory, which can make very large files slower to process.
- The architecture is intentionally simple but concentrated in one file, which limits modularity.

## 10. Developer Guidance Summary

The system is simple, but the contracts are specific.

- Preserve source separation.
- Preserve Prime query-string parsing patterns.
- Treat `user_id` and `app_id` as core platform fields.
- Treat `get_display_df()` as the final contract for what users see and export.
- Extend the system by adding local, source-specific logic rather than global branching.