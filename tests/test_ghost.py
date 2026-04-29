import pytest
import tempfile
from core.ghost import Ghost

def test_ghost_creation_and_unlock():
    with tempfile.TemporaryDirectory() as tmp:
        # Create new Ghost
        g = Ghost.create(tmp, "TestGhost", "password123")
        assert g is not None
        assert g.path.exists()
        assert (g.path / "identity" / "salt.bin").exists()
        
        # Unlock the Ghost
        g2 = Ghost.unlock(tmp, "password123")
        assert g2 is not None
        assert g2._fernet is not None

def test_ghost_unlock_wrong_password():
    with tempfile.TemporaryDirectory() as tmp:
        Ghost.create(tmp, "TestGhost", "password123")
        
        with pytest.raises(Exception):
            Ghost.unlock(tmp, "wrongpassword")

def test_wiki_page_read_write():
    with tempfile.TemporaryDirectory() as tmp:
        g = Ghost.create(tmp, "TestGhost", "pass")
        
        # Write a page
        g.write_wiki_page("concepts/test-page", "This is a test content.")
        
        # Check if it exists
        assert g.wiki_page_exists("concepts/test-page") is True
        
        # Read the page
        content = g.read_wiki_page("concepts/test-page")
        assert content == "This is a test content."
        
        # List pages
        pages = g.list_wiki_pages()
        assert "concepts/test-page" in pages
        
        # Delete page
        g.delete_wiki_page("concepts/test-page")
        assert g.wiki_page_exists("concepts/test-page") is False
        assert "concepts/test-page" not in g.list_wiki_pages()
