import logging
import os

_logger = logging.getLogger(__name__)


def run_bootstrap(env):
    """Names the main company from the deploy's company fields.

    Only over Odoo's stock "My Company" and an empty email, so a later change in
    Settings stands.
    """
    company = env.ref("base.main_company", raise_if_not_found=False)
    if not company:
        return
    vals = {}
    name = os.environ.get("DEFAULT_COMPANY_NAME", "").strip()
    if name and company.name == "My Company":
        vals["name"] = name
    email = os.environ.get("DEFAULT_COMPANY_EMAIL", "").strip()
    if email and not company.email:
        vals["email"] = email
    if vals:
        company.write(vals)
        _logger.info("company_identity: set main company %s", sorted(vals))
