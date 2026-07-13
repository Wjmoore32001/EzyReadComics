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