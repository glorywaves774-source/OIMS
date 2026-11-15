"""Operator commands: ``flask --app wsgi oims <command>``."""
import os

import click

from app.extensions import db


def register_cli(app):
    @app.cli.group("oims")
    def oims():
        """OIMS administration commands."""

    @oims.command("create-superadmin")
    @click.option("--email", envvar="OIMS_SUPERADMIN_EMAIL", required=True,
                  help="Defaults to OIMS_SUPERADMIN_EMAIL")
    @click.option("--name", envvar="OIMS_SUPERADMIN_NAME", default="HOLIDO Super Admin")
    def create_superadmin(email, name):
        """Create the first HOLIDO Super Admin from environment variables.

        The password is read from OIMS_SUPERADMIN_PASSWORD (or prompted) and must be
        changed at first sign-in. Refuses to run if a Super Admin already exists.
        """
        from app import audit
        from app.models import PlatformRole, User
        from app.security import password_problems

        if User.query.filter_by(platform_role=PlatformRole.SUPER_ADMIN).first():
            raise click.ClickException("A Super Admin already exists. Use the platform console to add administrators.")
        password = os.environ.get("OIMS_SUPERADMIN_PASSWORD") or click.prompt(
            "Initial password", hide_input=True, confirmation_prompt=True)
        email = email.strip().lower()
        problems = password_problems(password, email=email)
        if problems:
            raise click.ClickException("Password rejected: " + " ".join(problems))
        user = User.query.filter_by(email=email).first() or User(email=email, full_name=name)
        user.full_name = user.full_name or name
        user.platform_role = PlatformRole.SUPER_ADMIN
        user.is_enabled = True
        user.set_password(password)
        user.must_change_password = True
        db.session.add(user)
        db.session.flush()
        audit.record("platform.superadmin_created", f"Super Admin {email} created via CLI", entity=user, actor=user)
        db.session.commit()
        click.echo(f"Super Admin {email} created. They must change the password at first sign-in.")
        click.echo("Remove OIMS_SUPERADMIN_PASSWORD from the environment now.")

    @oims.command("sync-roles")
    def sync_roles():
        """Grant newly added catalog permissions to every organization's system roles."""
        from app.models import Organization
        from app.rbac import seed_default_roles

        count = 0
        for org in Organization.query.filter(Organization.status != Organization.PENDING).all():
            seed_default_roles(org)
            count += 1
        db.session.commit()
        click.echo(f"System roles synchronized for {count} organization(s).")
