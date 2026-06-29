import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


RUN_INTERVAL_SECONDS = 70 * 60

COMMAND_SEQUENCE = [
    {
        "label": "Normal sync",
        "description": "Runs sync_comics to stay current and hydrate/update known data.",
        "manage_command": "sync_comics",
    },
    {
        "label": "Historical backfill",
        "description": "Runs backfill_issues to pull older issue records.",
        "manage_command": "backfill_issues",
    },
]


def main():
    project_root = Path(__file__).resolve().parent
    next_command_index = 0

    print("EzyReadComics Alternating Comic Vine Runner")
    print("------------------------------------------")
    print()
    print("Runs sync_comics first, then backfill_issues, then repeats.")
    print("Waits 1 hour and 10 minutes after each command finishes.")
    print("Press Ctrl+C to stop the runner.")
    print()

    while True:
        selected_command = COMMAND_SEQUENCE[next_command_index]

        started_at = datetime.now()
        run_manage_command(
            project_root=project_root,
            manage_command=selected_command["manage_command"],
            label=selected_command["label"],
            description=selected_command["description"],
        )

        finished_at = datetime.now()

        next_command_index = get_next_command_index(next_command_index)
        next_command = COMMAND_SEQUENCE[next_command_index]
        next_run_at = finished_at + timedelta(seconds=RUN_INTERVAL_SECONDS)

        print()
        print(f"Run started:  {format_time(started_at)}")
        print(f"Run finished: {format_time(finished_at)}")
        print(f"Next command: {next_command['label']} - python manage.py {next_command['manage_command']}")
        print(f"Next run:     {format_time(next_run_at)}")
        print()

        wait_for_next_run()


def get_next_command_index(current_index):
    return (current_index + 1) % len(COMMAND_SEQUENCE)


def run_manage_command(project_root, manage_command, label, description):
    command = [
        sys.executable,
        "manage.py",
        manage_command,
    ]

    print("------------------------------------------------------------")
    print(f"Starting: {label}")
    print(description)
    print(f"Command:  python manage.py {manage_command}")
    print(f"Time:     {format_time(datetime.now())}")
    print("------------------------------------------------------------")
    print()

    result = subprocess.run(
        command,
        cwd=project_root,
    )

    print()
    print("------------------------------------------------------------")

    if result.returncode == 0:
        print(f"Finished successfully: python manage.py {manage_command}")
    else:
        print(f"Command failed with exit code {result.returncode}: python manage.py {manage_command}")

    print("------------------------------------------------------------")


def wait_for_next_run():
    try:
        time.sleep(RUN_INTERVAL_SECONDS)
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