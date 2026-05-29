# Thin re-export for backward compatibility.
# All digest logic (including leader election) now lives in digest.py

from digest import alternate_digest_job

__all__ = ["alternate_digest_job"]
