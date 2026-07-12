import json
import os

from django.core.management.base import BaseCommand, CommandError
from openai import OpenAI


DEFAULT_MODEL = "gpt-5.5"


RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "string",
            "description": "Short summary of what was searched and how complete the result appears to be.",
        },
        "limitations": {
            "type": "array",
            "description": "Important caveats, uncertainty, missing sources, blocked pages, or reasons the list may be incomplete.",
            "items": {
                "type": "string",
            },
        },
        "runs": {
            "type": "array",
            "description": "Current Marvel comic runs that appear to be ongoing or have a confirmed upcoming issue.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {
                        "type": "string",
                    },
                    "start_year": {
                        "type": ["string", "null"],
                    },
                    "publisher": {
                        "type": "string",
                    },
                    "status": {
                        "type": "string",
                        "description": "Use ongoing, upcoming, uncertain, or excluded.",
                    },
                    "latest_confirmed_issue_number": {
                        "type": ["string", "null"],
                    },
                    "latest_confirmed_issue_title": {
                        "type": ["string", "null"],
                    },
                    "latest_confirmed_issue_release_date": {
                        "type": ["string", "null"],
                        "description": "Use YYYY-MM-DD if known, otherwise null.",
                    },
                    "next_confirmed_issue_number": {
                        "type": ["string", "null"],
                    },
                    "next_confirmed_issue_title": {
                        "type": ["string", "null"],
                    },
                    "next_confirmed_issue_release_date": {
                        "type": ["string", "null"],
                        "description": "Use YYYY-MM-DD if known, otherwise null.",
                    },
                    "primary_source_url": {
                        "type": ["string", "null"],
                    },
                    "supporting_source_urls": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Short explanation of why this appears to be an ongoing/current run.",
                    },
                    "confidence": {
                        "type": "string",
                        "description": "Use high, medium, or low.",
                    },
                },
                "required": [
                    "title",
                    "start_year",
                    "publisher",
                    "status",
                    "latest_confirmed_issue_number",
                    "latest_confirmed_issue_title",
                    "latest_confirmed_issue_release_date",
                    "next_confirmed_issue_number",
                    "next_confirmed_issue_title",
                    "next_confirmed_issue_release_date",
                    "primary_source_url",
                    "supporting_source_urls",
                    "evidence",
                    "confidence",
                ],
            },
        },
    },
    "required": [
        "summary",
        "limitations",
        "runs",
    ],
}


class Command(BaseCommand):
    help = (
        "Probe whether OpenAI web search can find current ongoing Marvel runs. "
        "This command prints results only and writes nothing to the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            default=os.getenv("OPENAI_MARVEL_PROBE_MODEL", DEFAULT_MODEL),
            help=f"OpenAI model to use. Default: {DEFAULT_MODEL}",
        )
        parser.add_argument(
            "--search-context",
            choices=["low", "medium", "high"],
            default="high",
            help="How much search context to give the model. Default: high",
        )
        parser.add_argument(
            "--marvel-only",
            action="store_true",
            help="Restrict web search to marvel.com only.",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print the raw JSON response text after the formatted terminal output.",
        )

    def handle(self, *args, **options):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise CommandError(
                "OPENAI_API_KEY is not set. Add it to your .env file before running this command."
            )

        model = options["model"]
        search_context = options["search_context"]
        marvel_only = options["marvel_only"]
        print_raw = options["raw"]

        web_search_tool = {
            "type": "web_search",
            "search_context_size": search_context,
        }

        if marvel_only:
            web_search_tool["filters"] = {
                "allowed_domains": [
                    "marvel.com",
                ],
            }

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Marvel ongoing run AI probe"))
        self.stdout.write("Mode: OpenAI web-search validation")
        self.stdout.write("Database writes: none")
        self.stdout.write("Comic Vine calls: none")
        self.stdout.write(f"Model: {model}")
        self.stdout.write(f"Search context: {search_context}")
        self.stdout.write(f"Marvel.com only: {'yes' if marvel_only else 'no'}")
        self.stdout.write("")

        prompt = self.build_prompt(marvel_only=marvel_only)

        client = OpenAI(api_key=api_key)

        try:
            response = client.responses.create(
                model=model,
                reasoning={
                    "effort": "low",
                },
                tools=[
                    web_search_tool,
                ],
                tool_choice="required",
                include=[
                    "web_search_call.action.sources",
                ],
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are helping validate a comic catalog updater. "
                            "Be careful, source-grounded, and explicit about uncertainty. "
                            "Do not invent comic runs. If a run cannot be verified from web sources, leave it out or mark it uncertain."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "marvel_ongoing_run_probe",
                        "strict": True,
                        "schema": RESULT_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI request failed: {exc}") from exc

        output_text = response.output_text

        try:
            data = json.loads(output_text)
        except json.JSONDecodeError as exc:
            self.stdout.write(self.style.ERROR("The model did not return valid JSON."))
            self.stdout.write("")
            self.stdout.write(output_text)
            raise CommandError(f"Could not parse model output as JSON: {exc}") from exc

        self.print_probe_result(data)

        if print_raw:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Raw JSON"))
            self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))

    def build_prompt(self, marvel_only):
        source_instruction = (
            "Use Marvel.com only."
            if marvel_only
            else (
                "Prioritize Marvel.com as the main source. "
                "If Marvel.com is incomplete or unavailable, use other reliable comic release sources, "
                "such as publisher listings, distributor listings, or established comics databases/news sites. "
                "Do not use Reddit, random blogs, or unsupported fan guesses as confirmation."
            )
        )

        return f"""
Find current Marvel comic runs that appear to be ongoing right now.

Definition for this probe:
- Publisher must be Marvel or a Marvel imprint/property currently published by Marvel.
- A run means a numbered comic series with issues.
- Include ongoing series with a confirmed upcoming issue.
- Include newly announced/upcoming series if issue #1 has a confirmed future release date.
- Exclude collected editions, trade paperbacks, omnibuses, hardcovers, facsimiles, reprints, variant covers, posters, art books, and toys.
- Exclude one-shots unless there is clear evidence it is part of a numbered continuing series.
- Exclude old completed runs unless there is a confirmed new upcoming issue for that same current series.
- If unsure whether something is a run or a collected edition, mark confidence low or leave it out.

What to find for each run:
- title
- start year if clear
- latest confirmed issue if clear
- next confirmed issue if clear
- next release date if clear
- source URLs
- short evidence
- confidence

{source_instruction}

Return the result as structured data only.
""".strip()

    def print_probe_result(self, data):
        runs = data.get("runs", [])
        limitations = data.get("limitations", [])

        self.stdout.write(self.style.SUCCESS("Probe complete."))
        self.stdout.write("")
        self.stdout.write("Summary:")
        self.stdout.write(data.get("summary", "No summary returned."))
        self.stdout.write("")
        self.stdout.write(f"Runs returned: {len(runs)}")
        self.stdout.write("")

        if limitations:
            self.stdout.write("Limitations:")
            for limitation in limitations:
                self.stdout.write(f"  - {limitation}")
            self.stdout.write("")

        if not runs:
            self.stdout.write(self.style.WARNING("No runs returned."))
            return

        self.stdout.write("Runs:")
        self.stdout.write("")

        for index, run in enumerate(runs, start=1):
            title = run.get("title") or "Unknown title"
            start_year = run.get("start_year") or "unknown year"
            status = run.get("status") or "unknown"
            confidence = run.get("confidence") or "unknown"

            self.stdout.write(f"{index}. {title} ({start_year})")
            self.stdout.write(f"   Status: {status}")
            self.stdout.write(f"   Confidence: {confidence}")

            latest_number = run.get("latest_confirmed_issue_number")
            latest_title = run.get("latest_confirmed_issue_title")
            latest_date = run.get("latest_confirmed_issue_release_date")

            if latest_number or latest_title or latest_date:
                self.stdout.write(
                    "   Latest confirmed issue: "
                    f"{latest_number or '?'}"
                    f"{f' — {latest_title}' if latest_title else ''}"
                    f"{f' — {latest_date}' if latest_date else ''}"
                )

            next_number = run.get("next_confirmed_issue_number")
            next_title = run.get("next_confirmed_issue_title")
            next_date = run.get("next_confirmed_issue_release_date")

            if next_number or next_title or next_date:
                self.stdout.write(
                    "   Next confirmed issue: "
                    f"{next_number or '?'}"
                    f"{f' — {next_title}' if next_title else ''}"
                    f"{f' — {next_date}' if next_date else ''}"
                )

            primary_source_url = run.get("primary_source_url")

            if primary_source_url:
                self.stdout.write(f"   Primary source: {primary_source_url}")

            supporting_source_urls = run.get("supporting_source_urls") or []

            for source_url in supporting_source_urls[:3]:
                self.stdout.write(f"   Supporting source: {source_url}")

            evidence = run.get("evidence")

            if evidence:
                self.stdout.write(f"   Evidence: {evidence}")

            self.stdout.write("")