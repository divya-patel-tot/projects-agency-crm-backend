#!/usr/bin/env python3
"""Fail fast when Strawberry cannot resolve GraphQL field return types.

Run after any schema change:
    python scripts/verify_graphql_schema.py
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from app.graphql.schema import schema  # noqa: F401 — builds the schema
        from app.main import create_app

        create_app()
    except Exception as exc:
        print(f"GraphQL schema verification failed: {exc}", file=sys.stderr)
        return 1

    print("GraphQL schema OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
