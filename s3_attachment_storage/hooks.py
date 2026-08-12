import json
import logging
import os

_logger = logging.getLogger(__name__)


def run_bootstrap(env):
    """Create/update the fs.storage record that routes attachments to S3.

    Every field server_environment registers via _server_env_fields is
    actually a computed field backed by a shadow x_<field>_env_default
    field — writing only the plain field name doesn't reliably persist for
    all of them, so both are set here.
    """
    if env.get("fs.storage") is None:
        return

    bucket = os.environ.get("AWS_BUCKETNAME", "").strip()
    if not bucket:
        _logger.info("s3_attachment_storage: AWS_BUCKETNAME not set — skipping")
        return

    options_json = json.dumps({
        "key": "$AWS_ACCESS_KEY_ID",
        "secret": "$AWS_SECRET_ACCESS_KEY",
        "client_kwargs": {
            "endpoint_url": "$AWS_ENDPOINT_URL",
            "region_name": "$AWS_REGION",
        },
    })
    force_db_rules_json = '{"image/": 51200, "application/javascript": 0, "text/css": 0}'

    vals = {
        "name": "DigitalOcean Spaces",
        "code": "s3",
        "protocol": "s3",
        "x_protocol_env_default": "s3",
        "directory_path": bucket,
        "x_directory_path_env_default": bucket,
        "optimizes_directory_path": True,
        "x_optimizes_directory_path_env_default": True,
        "eval_options_from_env": True,
        "x_eval_options_from_env_env_default": True,
        "options": options_json,
        "x_options_env_default": options_json,
        "use_as_default_for_attachments": True,
        "x_use_as_default_for_attachments_env_default": True,
        "force_db_for_default_attachment_rules": force_db_rules_json,
        "x_force_db_for_default_attachment_rules_env_default": force_db_rules_json,
    }

    storage = env["fs.storage"].sudo().search([("code", "=", "s3")], limit=1)
    if storage:
        storage.sudo().write(vals)
        _logger.info("s3_attachment_storage: updated S3 attachment storage (bucket=%s)", bucket)
    else:
        env["fs.storage"].sudo().create(vals)
        _logger.info("s3_attachment_storage: created S3 attachment storage (bucket=%s)", bucket)

    # Some attachments (e.g. menu icons, language flags) are written by
    # Odoo's own XML data loader through a path that bypasses fs_attachment's
    # create() override, landing on local disk even with S3 active. Move
    # just those. Deliberately narrower than ir.attachment.force_storage():
    # that also sweeps up db_datas-stored attachments (small images/JS/CSS,
    # intentionally kept in Postgres per force_db_for_default_attachment_rules),
    # which would defeat the point of that setting.
    Attachment = env["ir.attachment"].sudo()
    stray = Attachment.search([
        ("store_fname", "!=", False),
        ("store_fname", "not like", "s3://%"),
        # ir.attachment's own _search() silently adds res_field=False to
        # any domain that doesn't mention res_field — without this, field
        # attachments (menu icons, language flags: exactly what needs
        # catching here) would be excluded.
        "|", ("res_field", "=", False), ("res_field", "!=", False),
    ])
    for att in stray:
        att._move_attachment_to_store()


def post_init_hook(env):
    run_bootstrap(env)
