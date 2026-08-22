{
    "name": "S3 Attachment Storage Bootstrap",
    "version": "1.1.0",
    "category": "Technical",
    "summary": "Configures fs_attachment_s3 as the default attachment storage from AWS_* env vars",
    "description": """
S3 Attachment Storage Bootstrap
================================

Creates (or updates) the ``fs.storage`` record that routes attachments to
S3-compatible object storage, reading connection details from the pod's own
env vars rather than requiring manual setup per deployment:

- ``AWS_BUCKETNAME`` — bucket name
- ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_ENDPOINT_URL`` /
  ``AWS_REGION`` — referenced live via fs_storage's env-var substitution,
  never written to the database

Without this, attachments silently fall back to the pod's local filesystem,
which is wiped on every restart.
    """,
    "author": "Ordomatics",
    "license": "LGPL-3",
    "depends": ["base", "fs_attachment_s3"],
    "installable": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}
