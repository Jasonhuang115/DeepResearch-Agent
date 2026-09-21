from agent_service.runtime.system_prompt import build_system_prompt, detect_reply_language, load_prompt_fragments
from agent_service.tools import default_registry


def test_prompt_fragment_order_and_tags() -> None:
    names = [f.section_name for f in load_prompt_fragments()]
    assert names == ["role", "primitives", "security"]
    text = build_system_prompt(conversation_id="conv_1", run_id="run_1", reply_language="Chinese")
    assert text.index("<role>") < text.index("<primitives>") < text.index("<security>")
    assert "<skills>" not in text
    assert '"conversation_id": "conv_1"' in text
    assert '"run_id": "run_1"' in text
    assert "<language>" in text
    assert "Chinese" in text
    assert "web_search" in text
    assert "web_fetch" in text
    assert "Read" in text
    assert "Write" in text
    assert "Edit" in text
    assert "Glob" in text
    assert "Grep" in text
    assert "Bash" in text
    assert "not evidence" in text
    assert "source_id" in text
    assert "attachments/" in text
    assert "sources/index.json" in text
    assert "tool-output/" in text
    assert "**Not implemented.**" not in text


def test_detect_reply_language() -> None:
    assert detect_reply_language("什么是固态电池") == "Chinese"
    assert detect_reply_language("What is a solid-state battery?") == "English"


def test_default_registry_tools() -> None:
    names = default_registry().names()
    assert names == ["web_search", "web_fetch", "Read", "Write", "Edit", "Glob", "Grep", "Bash"]
