"""Run a single scheduled job manually: python -m app.scheduler.run --job process_due_sequence_steps"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.scheduler.jobs import JOB_REGISTRY


async def _main(job_name: str) -> int:
    fn = JOB_REGISTRY.get(job_name)
    if fn is None:
        print(f"Unknown job: {job_name}")
        print("Available:", ", ".join(sorted(JOB_REGISTRY.keys())))
        return 1
    result = await fn()
    print(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agency CRM scheduled job once")
    parser.add_argument("--job", required=True, help="Job name from JOB_REGISTRY")
    args = parser.parse_args()
    return asyncio.run(_main(args.job))


if __name__ == "__main__":
    raise SystemExit(main())
