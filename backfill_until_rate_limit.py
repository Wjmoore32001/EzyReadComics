import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


LOOP_DELAY_SECONDS = 2
RATE_LIMIT_WAIT_SECONDS = 70 * 60

RATE_LIMIT_TEXT_PATTERNS = [
    "too many requests",
    "rate limit",
    "rate-limit",
    "ratelimit",
    "429",
    "quota exceeded",
    "api limit",
]


def main():
    project_root = Path(__file__).resolve().parent

    print("EzyReadComics Backfill Until Rate Limit Runner")
    print("----------------------------------------------")
    print()
    print("This will repeatedly run:")
    print()
    print("    python manage.py backfill_issues")
    print()
    print("It waits 2 seconds between successful runs.")
    print("When a rate-limit error is detected, it waits 1 hour and 10 minutes.")
    print("Press Ctrl+C to stop.")
    print()

    while True:
        run_until_rate_limited(project_root)
        wait_after_rate_limit()


def run_until_rate_limited(project_root):
    run_number = 1

    while True:
        print()
        print("============================================================")
        print(f"Backfill run #{run_number}")
        print(f"Started: {format_time(datetime.now())}")
        print("============================================================")
        print()

        result = run_backfill_command(project_root)

        if result["rate_limited"]:
            print()
            print("============================================================")
            print("Rate-limit response detected.")
            print(f"Detected at: {format_time(datetime.now())}")
            print("============================================================")
            print()
            return

        if result["return_code"] != 0:
            print()
            print("============================================================")
            print("Backfill command failed, but it did not look like a rate-limit error.")
            print("Stopping so a real bug does not get repeated forever.")
            print(f"Exit code: {result['return_code']}")
            print("============================================================")
            print()
            sys.exit(result["return_code"])

        print()
        print("============================================================")
        print(f"Backfill run #{run_number} finished successfully.")
        print(f"Waiting {LOOP_DELAY_SECONDS} seconds before the next run.")
        print("============================================================")
        print()

        run_number += 1
        sleep_or_stop(LOOP_DELAY_SECONDS)


def run_backfill_command(project_root):
    command = [
        sys.executable,
        "manage.py",
        "backfill_issues",
    ]

    process = subprocess.Popen(
        command,
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output_lines = []

    try:
        for line in process.stdout:
            print(line, end="")
            output_lines.append(line)
    except KeyboardInterrupt:
        process.terminate()
        stop_runner()

    return_code = process.wait()
    combined_output = "".join(output_lines)

    return {
        "return_code": return_code,
        "rate_limited": looks_like_rate_limit(combined_output),
    }


def looks_like_rate_limit(output):
    normalized_output = output.lower()

    return any(
        pattern in normalized_output
        for pattern in RATE_LIMIT_TEXT_PATTERNS
    )


def wait_after_rate_limit():
    next_start = datetime.now() + timedelta(seconds=RATE_LIMIT_WAIT_SECONDS)

    print(f"Waiting 1 hour and 10 minutes before restarting backfill loop.")
    print(f"Next start: {format_time(next_start)}")
    print()

    sleep_or_stop(RATE_LIMIT_WAIT_SECONDS)


def sleep_or_stop(seconds):
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        stop_runner()


def stop_runner():
    print()
    print("Runner stopped.")
    sys.exit(0)


def format_time(value):
    return value.strftime("%Y-%m-%d %I:%M:%S %p")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_runner()