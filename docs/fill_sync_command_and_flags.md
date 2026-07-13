## Release Back Filling Calendar
    python manage.py backfill_marvel_release_calendar \
  --start-date 2026-07-01 \
  --end-date 2026-07-15 \
  --verbose
## ReleaseSync Current Calendar
    python manage.py sync_marvel_release_calendar_ai --verbose

## Collection Back Filling Calendar
    python manage.py backfill_marvel_collection_calendar \
  --start-date 2026-07-01 \
  --end-date 2026-07-15 \
  --verbose

## Collection Current Calendar
    python manage.py sync_marvel_collection_calendar --verbose

## Updating Run Issue Dates
    python manage.py update_run_issue_dates --verbose

    python manage.py update_run_issue_dates --publisher Marvel
    python manage.py update_run_issue_dates --run-id 123 --verbose
    python manage.py update_run_issue_dates --clear-empty


## DC sync

# Fast direct one-shot dry-run
python manage.py sync_dc_comics \
  --detail-url "https://www.dc.com/graphic-novels/lex-luthor-diabolical-genius" \
  --dry-run \
  --verbose

# Direct run/series-map dry-run
python manage.py sync_dc_comics \
  --detail-url "https://www.dc.com/comics/poison-ivy-2022/poison-ivy-2022-46" \
  --dry-run \
  --verbose

# Direct run/series-map write
python manage.py sync_dc_comics \
  --detail-url "https://www.dc.com/comics/poison-ivy-2022/poison-ivy-2022-46" \
  --verbose

# Browse page dry-run
python manage.py sync_dc_comics \
  --page 1 \
  --page-count 1 \
  --dry-run \
  --verbose

# Browse page write
python manage.py sync_dc_comics \
  --page 1 \
  --page-count 1 \
  --verbose

# Browse page write, but skip related graphic novels / volumes
python manage.py sync_dc_comics \
  --page 1 \
  --page-count 1 \
  --no-related-graphic-novels \
  --verbose

# Headed browser debug
python manage.py sync_dc_comics \
  --detail-url "https://www.dc.com/comics/poison-ivy-2022/poison-ivy-2022-46" \
  --dry-run \
  --verbose \
  --headed

# Longer timeout debug
python manage.py sync_dc_comics \
  --page 1 \
  --page-count 1 \
  --dry-run \
  --verbose \
  --timeout 60000