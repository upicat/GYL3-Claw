"""Import all executor modules to trigger plugin registration."""
from app.executor import shell  # noqa: F401
from app.executor import script  # noqa: F401
from app.executor import rag  # noqa: F401
from app.executor import web_search_executor  # noqa: F401
from app.executor import url_executor  # noqa: F401
