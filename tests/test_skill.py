from pathlib import Path

import sphinx_lens

SKILL_PATH = Path(sphinx_lens.__file__).parent / ".agents" / "skills" / "sphinx-lens"


def test_library_skill_is_bundled() -> None:
    assert (SKILL_PATH / "SKILL.md").is_file()
    assert (SKILL_PATH / "references" / "querying.md").is_file()
    assert (SKILL_PATH / "agents" / "openai.yaml").is_file()
