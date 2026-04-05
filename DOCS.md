# User Inspector Documentation

User Inspector is a lightweight analysis interface for reviewing exported activity data from Prime and My Chips. It accepts spreadsheet uploads, detects the source format automatically, parses user identifiers, surfaces source-specific fields, and lets users export a cleaner result set.

This document is the main product documentation hub. It is intended for end users, operators, analysts, and future maintainers who need a clear explanation of what the product does and how to use it correctly.

## Introduction

### What the Product Does

User Inspector converts raw export files into a focused analysis view. Instead of working directly with inconsistent spreadsheet schemas, users upload a supported file and receive a normalized table designed for inspection.

The app performs four core tasks:

- reads CSV or Excel uploads
- detects whether the source is Prime or My Chips
- extracts `app_id` and `user_id` for analysis
- renders a source-aware result table that can be downloaded as CSV

### Who It Is For

User Inspector is best suited for:

- operations teams reviewing partner export files
- support teams investigating user-level records
- analysts validating reward and payout data
- maintainers who need a simple inspection tool without building a reporting pipeline

### Common Use Cases

- find a specific user in a Prime export
- check which app a user record belongs to
- review payout and reward data for a filtered subset
- inspect Prime postback values such as `status`, `offer_name`, and `task_name`
- compare records across My Chips exports using normalized display columns

## Getting Started

### 1. Upload Your File

The app accepts two file formats:

- `.csv`
- `.xlsx`

When a file is selected, the app shows the file name and file size, then loads the content into memory.

### 2. Select the Source

There is no manual source selector in the current UI. Source selection is automatic and based on the uploaded columns.

- Files with `Postback URL` are treated as Prime
- Files with `UserID` are treated as My Chips

From a user perspective, source selection is achieved by uploading the correct report.

### 3. Analyze the Data

Once the file is loaded successfully:

- the app parses identifiers
- invalid rows with missing identifiers are removed
- the result table is generated using the source-specific display format
- summary cards show total dataset size, matches, and match percentage

### 4. Filter the Result Set

Use the filter controls to narrow the dataset.

- `User ID` performs an exact match against `user_id`
- `App` filters by `app_id`
- both filters can be used together
- `Reset` returns to the full parsed dataset

### 5. Export the Output

The `Download Results (CSV)` action exports the visible table exactly as shown in the interface. It does not export every original raw column from the uploaded file.

## Data Sources

## Prime

### How Prime Works

Prime files are identified by the presence of the `Postback URL` column. The app parses this URL to extract user identifiers and selected query-string fields.

Prime processing uses two layers of data:

- source columns that already exist in the file, such as `App`, `Datetime`, `Reward`, `Payout`, and `Type`
- fields parsed from the `Postback URL`, such as `user`, `offer_name`, `task_name`, and `status`

### What Comes from Postback URL

The `Postback URL` query string is the source of the following parsed values:

- `user`
- `offer_name`
- `task_name`
- `status`

The `user` value is further split into:

- `app_id`
- `user_id`

### Prime Fields Explained

- `user`: a query parameter inside `Postback URL` that is expected to contain `app_id-user_id`
- `payout`: a value shown directly in the Prime file as `Payout`
- `reward`: a value shown directly in the Prime file as `Reward`
- `status`: a query parameter parsed from `Postback URL`, typically values such as `COMPLETED`
- `offer_name`: a query parameter parsed from `Postback URL`
- `task_name`: a query parameter parsed from `Postback URL`

### Prime Output Shape

Prime rows are displayed in this fixed order:

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

## My Chips

### How My Chips Differs

My Chips files are identified by the presence of the `UserID` column. Unlike Prime, My Chips does not use URL parsing. Instead, the app splits a single source identifier into two fields and maps several possible source column names into one display model.

### My Chips Field Behavior

- `UserID` is expected to follow the format `app_id-user_id`
- the app splits `UserID` once on the first hyphen
- the left side becomes `app_id`
- the right side becomes `user_id`

My Chips also supports flexible source naming for display columns such as:

- `DateTime`, `Datetime`, or `date`
- `Payout` or `payout`
- `Country` or `country`
- `EventName`, `event_name`, or `type`
- `AppName`, `app`, or `App`

### My Chips Output Shape

My Chips rows are displayed as:

- `user_id`
- `app_id`
- `DateTime`
- `Payout`
- `Country`
- `EventName`
- `AppName`

## Data Model

This section explains every output column used by the current application.

### `user_id`

Meaning:
The user-level identifier used for filtering and analysis.

Source:
- Prime: parsed from the `user` query parameter inside `Postback URL`
- My Chips: parsed from the `UserID` column after splitting on the first hyphen

### `app_id`

Meaning:
The application identifier associated with the user record.

Source:
- Prime: parsed from the `user` query parameter inside `Postback URL`
- My Chips: parsed from the `UserID` column after splitting on the first hyphen

### `Datetime`

Meaning:
The event date and time shown in Prime output.

Source:
- Prime: direct source column named `Datetime`

### `Reward`

Meaning:
The reward value associated with the Prime record.

Source:
- Prime: direct source column named `Reward`

### `Payout`

Meaning:
The payout amount associated with the record.

Source:
- Prime: direct source column named `Payout`
- My Chips: mapped from `Payout` or `payout`

### `status`

Meaning:
The current Prime status parsed from the postback query string.

Source:
- Prime: parsed from the `status` query parameter in `Postback URL`

### `Type`

Meaning:
The Prime event type.

Source:
- Prime: direct source column named `Type`

### `offer_name`

Meaning:
The Prime offer name associated with the row.

Source:
- Prime: parsed from the `offer_name` query parameter in `Postback URL`

### `task_name`

Meaning:
The Prime task name associated with the row.

Source:
- Prime: parsed from the `task_name` query parameter in `Postback URL`

### `Country`

Meaning:
The country value used in My Chips output.

Source:
- My Chips: mapped from `Country` or `country`

### `EventName`

Meaning:
The normalized event label used in My Chips output.

Source:
- My Chips: mapped from `EventName`, `event_name`, or `type`

### `AppName`

Meaning:
The normalized app name used in My Chips output.

Source:
- My Chips: mapped from `AppName`, `app`, or `App`

## Filtering and Analysis

### How Filtering Works

Filtering is applied to the parsed dataset, not the original raw upload view. That means the user filters against normalized identifiers already prepared by the source-specific loader.

### `user_id` Filtering Behavior

`user_id` filtering is exact match only.

Important implications:

- partial values do not match
- substring search is not supported
- fuzzy matching is not supported
- extra spaces are removed before comparison

### `app_id` Filtering Behavior

The `App` dropdown is populated from the parsed `app_id` values in the loaded dataset. Selecting a value filters rows where `app_id` exactly matches the chosen value.

### How Data Is Matched

The filter flow is straightforward:

1. start from the full parsed dataset
2. if a `user_id` query exists, keep only exact matches
3. if an `app_id` filter exists and is not `All`, keep only exact matches
4. render the remaining rows

## UI Overview

### Upload

The upload section is the first step in the interface. It accepts `.csv` and `.xlsx` files and displays the selected file name plus file size.

### Filters

The filter section includes:

- a text input for `User ID`
- a select box for `App`
- a `Search` button
- a `Reset` button

### Summary Cards

After filtering, the app shows three metrics:

- matching rows
- match percentage
- total dataset size

### Table

The table is rendered from a source-aware display DataFrame. It hides extra columns that are not part of the approved output model for the current source.

### Export

The export action downloads the visible table as CSV. The exported file name includes a timestamp so repeated downloads stay distinct.

## Examples

### Example Prime Row

Raw Prime context:

- `Postback URL`: `https://example.com/postback?user=42-264195&offer_name=Survey%20Wall&task_name=Install&status=COMPLETED`
- `App`: `Prime Rewards`
- `Datetime`: `2026-04-05 14:33:12`
- `Reward`: `1200`
- `Payout`: `3.50`
- `Type`: `Conversion`

Displayed result:

| App | user_id | app_id | Datetime | Reward | Payout | status | Type | offer_name | task_name |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prime Rewards | 264195 | 42 | 2026-04-05 14:33:12 | 1200 | 3.50 | COMPLETED | Conversion | Survey Wall | Install |

### Example My Chips Row

Raw My Chips context:

- `UserID`: `42-264195`
- `date`: `2026-04-05 14:33:12`
- `payout`: `3.50`
- `country`: `US`
- `event_name`: `install`
- `app`: `My Chips Rewards`

Displayed result:

| user_id | app_id | DateTime | Payout | Country | EventName | AppName |
| --- | --- | --- | --- | --- | --- | --- |
| 264195 | 42 | 2026-04-05 14:33:12 | 3.50 | US | install | My Chips Rewards |

### Example Filtered Output

Input filters:

- `User ID`: `264195`
- `App`: `42`

Result behavior:

- only rows with `user_id == 264195` remain
- if `App` is set to `42`, only rows with `app_id == 42` remain
- the summary cards update to reflect the remaining record count and match percentage

## Error Handling

### Missing Columns

If a file does not contain the required source identifier columns, the app cannot process it.

- Prime requires `Postback URL`
- My Chips requires `UserID`

If neither column exists, the app shows an unrecognized file format error.

### Invalid Files

If the selected file is not `.csv` or `.xlsx`, the app rejects it. If the file is corrupted or cannot be parsed by pandas, the app surfaces an error and clears the current session data.

### Parsing Failures

If row-level parsing does not produce valid identifiers:

- Prime rows with missing or invalid parsed identifiers are removed
- My Chips rows with invalid `UserID` structure are removed

If optional Prime fields such as `status`, `offer_name`, or `task_name` are missing, the app does not crash. It fills:

- `offer_name` with `—`
- `task_name` with `—`
- `status` with an empty string

## Best Practices

- Upload original exports instead of manually edited copies whenever possible.
- Keep column names unchanged before upload.
- For Prime, make sure `Postback URL` includes a valid `user` parameter formatted as `app_id-user_id`.
- For Prime, verify that optional query parameters like `status`, `offer_name`, and `task_name` are present if you expect to see them.
- For My Chips, make sure `UserID` uses the `app_id-user_id` pattern.
- Use exact `user_id` values for reliable filtering.
- Apply the `App` filter first when working with large datasets.
- Export only after you confirm the visible table matches the slice you want to save.

## Operational Notes

- The application works in memory, so very large files may feel slower.
- The current interface has no manual source toggle.
- Export output is based on the display table, not the full raw schema.

## Next Reference

For implementation details, parsing rules, and safe extension patterns, see [Ruls.md](Ruls.md).