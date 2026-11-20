"""One authoritative project root and database path for both processes."""
import os
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT.parent / '.env')
load_dotenv(ROOT / '.env')

def database_path():
    path = Path(os.environ.get('CRITBOT_DB', 'data/critbot.db')).expanduser()
    resolved = (path if path.is_absolute() else ROOT / path).resolve()
    # Preserve existing configs that still name the former root database.
    if resolved == (ROOT / 'critbot.db').resolve() and not resolved.exists():
        return (ROOT / 'data' / 'critbot.db').resolve()
    return resolved
