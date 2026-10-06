"""Tests for merge publish-skill command."""

from __future__ import annotations

import base64
import io
import json
import zipfile

from merge_cli.commands.publish_skill import build_bundle, publish_skill

SKILL_MD = "---\nname: Expense Report\ndescription: File one.\n---\nSteps."

MCP_PUBLISH_SUCCESS = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "skill": {
                            "slug": "expense-report",
                            "name": "Expense Report",
                            "version": 1,
                            "created": True,
                        }
                    }
                ),
            }
        ],
        "isError": False,
    },
}

MCP_PUBLISH_ERROR = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": "invalid_params",
                        "message": "SKILL.md must start with YAML frontmatter.",
                    }
                ),
            }
        ],
        "isError": True,
    },
}


def _write_skill_dir(tmp_path, extra: dict[str, str] | None = None):
    skill_dir = tmp_path / "expense-report"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(SKILL_MD)
    for relpath, content in (extra or {}).items():
        target = skill_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return skill_dir


def _bundle_files(arguments: dict) -> dict[str, bytes]:
    archive = base64.b64decode(arguments["bundle_base64"])
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def test_publishing_a_single_file_sends_skill_md(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments, tmp_path
):
    setup_mcp_mocks(httpx_mock, MCP_PUBLISH_SUCCESS)
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(SKILL_MD)

    result = runner.invoke(publish_skill, [str(skill_md)])

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["status"] == "success"
    assert call_arguments(httpx_mock) == {"skill_md": SKILL_MD, "action": "publish"}


def test_publishing_a_directory_sends_a_bundle(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments, tmp_path
):
    setup_mcp_mocks(httpx_mock, MCP_PUBLISH_SUCCESS)
    skill_dir = _write_skill_dir(tmp_path, {"references/policy.md": "the policy"})

    result = runner.invoke(publish_skill, [str(skill_dir)])

    assert result.exit_code == 0
    files = _bundle_files(call_arguments(httpx_mock))
    assert files["SKILL.md"].decode() == SKILL_MD
    assert files["references/policy.md"].decode() == "the policy"


def test_a_bundle_omits_junk_files(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments, tmp_path
):
    """Editor and VCS droppings would eat into the server's file-count cap."""
    setup_mcp_mocks(httpx_mock, MCP_PUBLISH_SUCCESS)
    skill_dir = _write_skill_dir(
        tmp_path,
        {
            ".DS_Store": "junk",
            "__pycache__/x.pyc": "junk",
            "scripts/run.sh": "echo hi",
        },
    )

    result = runner.invoke(publish_skill, [str(skill_dir)])

    assert result.exit_code == 0
    files = _bundle_files(call_arguments(httpx_mock))
    assert set(files) == {"SKILL.md", "scripts/run.sh"}


def test_a_directory_without_skill_md_fails_before_any_request(
    runner, env_vars, httpx_mock, tmp_path
):
    empty = tmp_path / "no-skill"
    empty.mkdir()
    (empty / "notes.md").write_text("nope")

    result = runner.invoke(publish_skill, [str(empty)])

    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["status"] == "error"
    assert "SKILL.md" in output["message"]
    assert httpx_mock.get_requests() == []


def test_publish_skill_forwards_the_optional_overrides(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments, tmp_path
):
    setup_mcp_mocks(httpx_mock, MCP_PUBLISH_SUCCESS)
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(SKILL_MD)

    result = runner.invoke(
        publish_skill,
        [
            str(skill_md),
            "--slug",
            "expense-report",
            "--name",
            "Expenses",
            "--description",
            "Updated",
            "--release-notes",
            "Clarified step 2",
        ],
    )

    assert result.exit_code == 0
    assert call_arguments(httpx_mock) == {
        "skill_md": SKILL_MD,
        "slug": "expense-report",
        "name": "Expenses",
        "description": "Updated",
        "release_notes": "Clarified step 2",
        "action": "publish",
    }


def test_publish_skill_tool_error_exits_nonzero(
    runner, env_vars, httpx_mock, setup_mcp_mocks, tmp_path
):
    setup_mcp_mocks(httpx_mock, MCP_PUBLISH_ERROR)
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("no frontmatter")

    result = runner.invoke(publish_skill, [str(skill_md)])

    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["status"] == "error"


def test_publish_skill_requires_a_path(runner, env_vars):
    result = runner.invoke(publish_skill, [])

    assert result.exit_code != 0


def test_publish_skill_rejects_a_missing_path(runner, env_vars, tmp_path):
    result = runner.invoke(publish_skill, [str(tmp_path / "nothing-here")])

    assert result.exit_code != 0


def test_publish_skill_sends_the_chosen_action(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments, tmp_path
):
    setup_mcp_mocks(httpx_mock, MCP_PUBLISH_SUCCESS)
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(SKILL_MD)

    result = runner.invoke(publish_skill, [str(skill_md), "--action", "draft"])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock)["action"] == "draft"


def test_publish_skill_sends_scope_as_access_scope(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments, tmp_path
):
    """The CLI flag is --scope; the tool argument is access_scope."""
    setup_mcp_mocks(httpx_mock, MCP_PUBLISH_SUCCESS)
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(SKILL_MD)

    result = runner.invoke(publish_skill, [str(skill_md), "--action", "submit", "--scope", "org"])

    assert result.exit_code == 0
    arguments = call_arguments(httpx_mock)
    assert arguments["action"] == "submit"
    assert arguments["access_scope"] == "org"


def test_publish_skill_omits_scope_when_unset(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments, tmp_path
):
    """Omitted, never sent as null — the server defaults to personal, which is
    what the flagless call has always meant."""
    setup_mcp_mocks(httpx_mock, MCP_PUBLISH_SUCCESS)
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(SKILL_MD)

    result = runner.invoke(publish_skill, [str(skill_md)])

    assert result.exit_code == 0
    assert "access_scope" not in call_arguments(httpx_mock)


def test_publish_skill_rejects_an_unknown_action(runner, env_vars, httpx_mock, tmp_path):
    """click refuses before any network call, so a typo costs no round trip."""
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(SKILL_MD)

    result = runner.invoke(publish_skill, [str(skill_md), "--action", "ship"])

    assert result.exit_code == 2
    assert httpx_mock.get_requests() == []


def test_publish_skill_rejects_an_unknown_scope(runner, env_vars, httpx_mock, tmp_path):
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(SKILL_MD)

    result = runner.invoke(publish_skill, [str(skill_md), "--scope", "team"])

    assert result.exit_code == 2
    assert httpx_mock.get_requests() == []


def test_a_bundle_skips_symlinks_pointing_outside_the_directory(tmp_path):
    """A link named like an ordinary file must not pull in its target.

    The skip-list only sees the link's own name, so a dot-prefixed secret is no
    longer protected once something inside the directory points at it.
    """
    outside = tmp_path / "secrets"
    outside.mkdir()
    (outside / ".env").write_text("AWS_SECRET=hunter2\n")
    skill_dir = _write_skill_dir(tmp_path, {})
    (skill_dir / "notes.md").symlink_to(outside / ".env")

    files = _bundle_files({"bundle_base64": base64.b64encode(build_bundle(skill_dir)).decode()})

    assert set(files) == {"SKILL.md"}


def test_a_bundle_skips_a_symlinked_directory(tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "notes.md").write_text("not mine")
    skill_dir = _write_skill_dir(tmp_path, {})
    (skill_dir / "linked").symlink_to(outside, target_is_directory=True)

    files = _bundle_files({"bundle_base64": base64.b64encode(build_bundle(skill_dir)).decode()})

    assert set(files) == {"SKILL.md"}


def test_a_bundle_keeps_real_files_next_to_a_skipped_symlink(tmp_path):
    """Skipping links must not cost the caller their actual content."""
    outside = tmp_path / "secrets"
    outside.mkdir()
    (outside / ".env").write_text("AWS_SECRET=hunter2\n")
    skill_dir = _write_skill_dir(tmp_path, {"references/policy.md": "the policy"})
    (skill_dir / "notes.md").symlink_to(outside / ".env")

    files = _bundle_files({"bundle_base64": base64.b64encode(build_bundle(skill_dir)).decode()})

    assert set(files) == {"SKILL.md", "references/policy.md"}


def test_publishing_a_file_reads_it_as_utf8(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments, tmp_path
):
    """Read explicitly as UTF-8: the platform default would mojibake this
    silently on a machine whose locale encoding is not UTF-8.
    """
    setup_mcp_mocks(httpx_mock, MCP_PUBLISH_SUCCESS)
    body = "---\nname: Caf\u00e9\ndescription: An em\u2014dash.\n---\nBody\n"
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(body, encoding="utf-8")

    result = runner.invoke(publish_skill, [str(skill_md)])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock)["skill_md"] == body
