"""Kept for compatibility with 0.4: settings, projects and backends now live in `enlens_claims.home`."""
from ..home import *  # noqa: F401,F403
from ..home import (BACKEND_LABELS, DEFAULTS, backend_label, create_project, env_key, forget_key, home,  # noqa: F401
                    link_existing, list_projects, load_settings, make_backend, open_project, project_path,
                    remember_key, safe_name, save_settings, save_uploads, stored_key)
