import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from core.ghost import Ghost
ghost = Ghost("ghost")
ghost.unlock_with_key("ghost")
print(ghost.list_wiki_pages())
