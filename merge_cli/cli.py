"""Click entry point for the Merge CLI."""

from __future__ import annotations

import click
from dotenv import load_dotenv

from merge_cli import __version__
from merge_cli.commands.agent import agent
from merge_cli.commands.authenticate import authenticate
from merge_cli.commands.configure import configure
from merge_cli.commands.eval import eval_cmd
from merge_cli.commands.execute_tool import execute_tool
from merge_cli.commands.get_tool_schema import get_tool_schema
from merge_cli.commands.lint import lint_cmd
from merge_cli.commands.list_skills import list_skills
from merge_cli.commands.list_tools import list_tools
from merge_cli.commands.login import login
from merge_cli.commands.logout import logout
from merge_cli.commands.logs import logs_cmd
from merge_cli.commands.publish_skill import publish_skill
from merge_cli.commands.retrieve_skill import retrieve_skill
from merge_cli.commands.search_tools import search_tools
from merge_cli.commands.setup import setup
from merge_cli.commands.skill_status import republish_skill, unpublish_skill
from merge_cli.commands.update import update
from merge_cli.version_check import maybe_check_for_update

AGENT_QUICKSTART_URL = "https://docs.merge.dev/merge-agent-handler/setup/agent-quickstart"


def _fetch_connectors() -> list[str]:
    """Fetch available connector names from the API."""
    try:
        from merge_cli.common import get_client

        client, errors = get_client()
        if errors or client is None:
            return []
        with client:
            tools = client.list_tools()
            return sorted({t["name"].split("__")[0] for t in tools if "__" in t.get("name", "")})
    except Exception:
        return []


class MergeGroup(click.Group):
    def format_help(self, ctx, formatter):
        super().format_help(ctx, formatter)

        connectors = _fetch_connectors()

        formatter.write("\n")
        with formatter.section("Workflow"):
            formatter.write_text(
                '1. merge search-tools "<intent>"  — find tools (returns compact schemas)'
            )
            formatter.write_text("2. merge execute-tool <tool> '{}'  — execute with JSON params")
            formatter.write_text(
                "3. merge authenticate <connector>  — magic link for the user when a tool"
                " needs authentication"
            )

        formatter.write("\n")
        with formatter.section("Agents without an account"):
            formatter.write_text(
                "merge agent signup  — create an organization and save credentials"
            )
            formatter.write_text(f"Guide: {AGENT_QUICKSTART_URL}")

        if connectors:
            formatter.write("\n")
            with formatter.section("Available connectors"):
                formatter.write_text(", ".join(connectors))
                formatter.write_text("Use --connector <slug> with search-tools to narrow results.")


@click.group(cls=MergeGroup)
@click.version_option(__version__, prog_name="merge")
def main():
    """Merge CLI — search, discover, and execute Agent Handler tools.

    For any task involving the connectors listed below, use this CLI.
    Do not call APIs directly — always search for the tool first.
    """
    load_dotenv()
    maybe_check_for_update()


## Tony addition to the merge agent handler api ##
main.add_command(eval_cmd, "eval")
main.add_command(lint_cmd, "lint")
main.add_command(logs_cmd, "logs")
main.add_command(search_tools, "search-tools")
main.add_command(execute_tool, "execute-tool")
main.add_command(list_tools, "list-tools")
main.add_command(get_tool_schema, "get-tool-schema")
main.add_command(list_skills, "list-skills")
main.add_command(retrieve_skill, "retrieve-skill")
main.add_command(publish_skill, "publish-skill")
main.add_command(unpublish_skill, "unpublish-skill")
main.add_command(republish_skill, "republish-skill")
main.add_command(authenticate, "authenticate")
main.add_command(agent, "agent")
main.add_command(configure, "configure")
main.add_command(login, "login")
main.add_command(logout, "logout")
main.add_command(setup, "setup")
main.add_command(update, "update")


if __name__ == "__main__":
    main()
