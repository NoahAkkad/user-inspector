# User Inspector

Inspect Prime and My Chips exports through a focused web interface for parsing, filtering, and CSV export.

User Inspector turns raw partner exports into a searchable table built around the fields people actually use: `user_id`, `app_id`, payout details, and source-specific context such as Prime postback fields.

## Why It Exists

Operations, support, and analyst workflows usually start with raw CSV or Excel files that are hard to inspect quickly. User Inspector reduces that friction by identifying the source format, extracting the relevant fields, and presenting a cleaner view for analysis.

## Key Features

- Supports both Prime and My Chips upload formats
- Extracts `user_id` and `app_id` for filtering
- Parses Prime postback fields including `offer_name`, `task_name`, and `status`
- Normalizes My Chips column variations into one display table
- Filters by exact `user_id` and optional `app_id`
- Exports the displayed result set as CSV

## Quick Start

1. Launch the app and upload a `.csv` or `.xlsx` file.
2. Let the app detect whether the file is Prime or My Chips.
3. Filter by `user_id` or `app_id` and review the resulting table.
4. Export the visible results as CSV if needed.

## Documentation

- Full product documentation: [DOCS.md](DOCS.md)
- Technical reference for maintainers: [Ruls.md](Ruls.md)