import os
import django
import sys

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from forensics.models import AnalysisLog

def print_logs():
    logs = AnalysisLog.objects.all().order_by('-timestamp')[:10]
    print(f"--- Last 10 Analysis Logs ---")
    for log in logs:
        print(f"[{log.timestamp}] [{log.log_type}] Case {log.case.id}: {log.message}")

if __name__ == "__main__":
    try:
        print_logs()
    except Exception as e:
        print(f"Error reading logs: {e}")
