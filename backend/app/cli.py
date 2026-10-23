"""Admin command line.

Create the first admin (prompts for the password):
    poetry run python -m app.cli create-admin --email you@company.com --name "Your Name"
"""

import argparse
import asyncio
import getpass
import sys

from pydantic import ValidationError

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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin", help="Create an admin user")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    args = parser.parse_args()

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
