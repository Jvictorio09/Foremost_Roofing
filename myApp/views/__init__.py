"""View package. Re-exports every view so ``urls.py`` can keep using
``views.<name>``."""
from .auth_views import *        # noqa: F401,F403
from .masters import *           # noqa: F401,F403
from .sales import *             # noqa: F401,F403
from .manufacturing import *     # noqa: F401,F403
from .inventory import *         # noqa: F401,F403
from .production import *         # noqa: F401,F403
from .logistics import *         # noqa: F401,F403
from .reports import *           # noqa: F401,F403
from .rbac_admin import *        # noqa: F401,F403
from .documents import *         # noqa: F401,F403
from .ai_views import *          # noqa: F401,F403
