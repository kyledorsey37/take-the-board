#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

    if (
        len(sys.argv) > 1
        and sys.argv[1] == "runserver"
        # Django's autoreloader invokes this entry point twice. Migrate in the
        # parent process only; the child inherits the already-checked schema.
        and os.environ.get("RUN_MAIN") != "true"
    ):
        import django
        from django.conf import settings
        from django.core.management import call_command

        django.setup()
        if settings.TAKEBOARD_AUTO_MIGRATE_ON_RUNSERVER:
            call_command("migrate", interactive=False)

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
