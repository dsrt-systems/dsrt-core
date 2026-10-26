"""
DSRT Core — API Router Registry

Only imports modules that actually exist on disk.
"""

from core.api.routers.agents import *          # noqa: F401,F403
from core.api.routers.arena import *           # noqa: F401,F403
from core.api.routers.artifacts import *       # noqa: F401,F403
from core.api.routers.auth import *            # noqa: F401,F403
from core.api.routers.capabilities import *    # noqa: F401,F403
from core.api.routers.credentials import *     # noqa: F401,F403
from core.api.routers.events import *          # noqa: F401,F403
from core.api.routers.executions import *      # noqa: F401,F403
from core.api.routers.memory import *          # noqa: F401,F403
from core.api.routers.orchestration import *   # noqa: F401,F403
from core.api.routers.providers import *       # noqa: F401,F403
from core.api.routers.tasks import *           # noqa: F401,F403
from core.api.routers.verification import *    # noqa: F401,F403
from core.api.routers.worlds import *          # noqa: F401,F403