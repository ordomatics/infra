from odoo.api import Environment
from odoo import SUPERUSER_ID


def migrate(cr, version):
    """Re-point the storage at AWS_BUCKETNAME.

    run_bootstrap only ever ran from post_init_hook, which fires on install
    and never again — so a deployment kept whatever directory_path it was
    first created with, whatever the env var later said. That matters now the
    path carries a per-deployment folder rather than just a bucket.
    """
    env = Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.s3_attachment_storage.hooks import run_bootstrap
    run_bootstrap(env)
