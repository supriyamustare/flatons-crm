"""Admin command line.

Create the first admin (prompts for the password):
    poetry run python -m app.cli create-admin --email you@company.com --name "Your Name"

Demo data for training and testing (prompts for the demo users' password):
    poetry run python -m app.cli seed-demo [--leads 60] [--allow-production]
    poetry run python -m app.cli remove-demo [--allow-production]
"""

import argparse
import asyncio
import getpass
import sys

from pydantic import ValidationError

from app import demo
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models.user import Role
from app.schemas.user import UserCreate
from app.services import users as users_service
from app.services.audit import log_audit


async def create_admin(email: str, name: str, password: str) -> int:
    data = UserCreate(email=email, full_name=name, role=Role.admin, password=password)
    async with SessionLocal() as db:
        user = await users_service.create_user(
            db, email=data.email, full_name=data.full_name, role=Role.admin, password=data.password
        )
        log_audit(
            db,
            action="user.create",
            entity_type="user",
            entity_id=user.id,
            details={"email": user.email, "role": "admin", "via": "cli"},
        )
        await db.commit()
        return user.id


async def _with_session(fn, **kwargs):
    try:
        async with SessionLocal() as db:
            result = await fn(db, **kwargs)
            await db.commit()
            return result
    finally:
        await engine.dispose()


def _guard_production(allow: bool) -> None:
    if get_settings().is_production and not allow:
        sys.exit(
            "This server is in production mode. Demo data is clearly marked and can be removed,\n"
            "but add --allow-production if you really want it here."
        )


def _ask_password(prompt: str) -> str:
    password = getpass.getpass(prompt)
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords don't match")
    if len(password) < 8:
        sys.exit("Use at least 8 characters")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin", help="Create an admin user")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p = sub.add_parser("seed-demo", help="Add clearly-marked demo data")
    p.add_argument("--leads", type=int, default=60)
    p.add_argument("--allow-production", action="store_true")
    p = sub.add_parser("remove-demo", help="Remove all demo data")
    p.add_argument("--allow-production", action="store_true")
    args = parser.parse_args()

    if args.command == "seed-demo":
        _guard_production(args.allow_production)
        password = _ask_password("Password for the demo users (min 8 characters): ")
        try:
            counts = asyncio.run(_with_session(demo.seed_demo, password=password, leads=args.leads))
        except demo.DemoDataError as exc:
            sys.exit(str(exc))
        print("Demo data added:", ", ".join(f"{v} {k}" for k, v in counts.items()))
        print(
            f"Sign in as e.g. ravi.kumar{demo.DEMO_DOMAIN} (executive), "
            f"meera.shah{demo.DEMO_DOMAIN} (manager), farah.khan{demo.DEMO_DOMAIN} (documents)"
        )
        return
    if args.command == "remove-demo":
        _guard_production(args.allow_production)
        removed = asyncio.run(_with_session(demo.remove_demo))
        print("Demo data removed:", ", ".join(f"{v} {k}" for k, v in removed.items()))
        return

    password = getpass.getpass("Password (min 8 characters): ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords don't match")

    async def run() -> int:
        try:
            return await create_admin(args.email, args.name, password)
        finally:
            await engine.dispose()

    try:
        user_id = asyncio.run(run())
    except ValidationError as exc:
        sys.exit(f"Invalid input:\n{exc}")
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"Admin created (id {user_id}): {args.email.lower()}")


if __name__ == "__main__":
    main()
