import pytest
from unittest.mock import MagicMock
from core.session import Session

def test_session_add_messages():
    ghost = MagicMock()
    session = Session(ghost)
    
    session.add("user", "Hello")
    session.add("assistant", "Hi there!")
    
    assert len(session.messages) == 2
    assert session.messages[0]["role"] == "user"
    assert session.messages[1]["role"] == "assistant"

def test_extraction_tracking():
    ghost = MagicMock()
    session = Session(ghost)
    
    session.add("user", "msg 1")
    unextracted = session.get_unextracted()
    assert len(unextracted) == 1
    
    session.mark_extracted()
    assert len(session.get_unextracted()) == 0
    
    session.add("user", "msg 2")
    assert len(session.get_unextracted()) == 1
    assert session.get_unextracted()[0]["content"] == "msg 2"

def test_llm_format():
    ghost = MagicMock()
    session = Session(ghost)
    session.add("user", "Hello")
    
    llm_msgs = session.to_llm_format()
    assert "ts" not in llm_msgs[0]
    assert llm_msgs[0]["role"] == "user"
