import django
import logging
from django.core.management import call_command

logging.basicConfig(level=logging.DEBUG)
django.setup()
print("Django setup complete! Running makemigrations...")
call_command("makemigrations", "forensics", verbosity=3)
print("makemigrations complete!")
