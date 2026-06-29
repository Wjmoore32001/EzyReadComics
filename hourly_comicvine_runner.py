import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


RUN_INTERVAL_SECONDS = 70 * 60


COMMANDS = {
    "1": {
        "label": "Normal sync",
        "description": "Runs sync_comics every 1 hour and 10 minutes. Best for staying current and hydrating/updating data.",
        "manage_command": "sync_comics",
    },
    "2": {
        "label": "Historical backfill",
        "description": "Runs backfill_issues every 1 hour and 10 minutes. Best for pulling older issue records.",
        "manage_command": "backfill_issues",
    },
}


def main():
    project_root = Path(__file__).resolve().parent

    selected_command = ask_for_command()

    print()
    print(f"Selected: {selected_command['label']}")
    print(selected_command["description"])
    print()
    print("Press Ctrl+C to stop the runner.")
    print()

    while True:
        started_at = datetime.now()
        run_manage_command(
            project_root=project_root,
            manage_command=selected_command["manage_command"],
        )

        finished_at = datetime.now()
        next_run_at = finished_at + timedelta(seconds=RUN_INTERVAL_SECONDS)

        print()
        print(f"Run started:  {format_time(started_at)}")
        print(f"Run finished: {format_time(finished_at)}")
        print(f"Next run:     {format_time(next_run_at)}")
        print()

        wait_for_next_run()


def ask_for_command():
    print("EzyReadComics Comic Vine Runner")
    print("-------------------------------")
    print()

    for option_number, command in COMMANDS.items():
        print(f"{option_number}. {command['label']}")
        print(f"   {command['description']}")
        print()

    while True:
        choice = input("Choose 1 or 2: ").strip()

        if choice in COMMANDS:
            return COMMANDS[choice]

        print("Invalid choice. Enter 1 or 2.")
        print()


def run_manage_command(project_root, manage_command):
    command = [
        sys.executable,
        "manage.py",
        manage_command,
    ]

    print("------------------------------------------------------------")
    print(f"Starting: python manage.py {manage_command}")
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