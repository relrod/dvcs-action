#!/usr/bin/env python

import argparse
import json
import re
from os import getenv
from sys import argv, exit
from typing import Optional

import requests

_NO_JIRA_MARKER = "NO_JIRA"
_AAP_RE = "AAP-[0-9]+"
comment_preamble = "DVCS PR Check Results:"
http_headers = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class CommandException(Exception):
    pass


def get_previous_comments_urls(comments_url) -> list[str]:
    # Load the existing comments
    print("Getting comments ... ", end="")
    comments = requests.get(comments_url)
    print(comments.status_code)
    if comments.status_code != 200:
        raise CommandException("Failed to get existing comments!")

    response = []
    for comment in comments.json():
        print(f"Checking if {comment['body']} starts with {comment_preamble} ... ", end="")
        if comment["body"].startswith(comment_preamble):
            response.append(comment["url"])
            print("Good!")
        else:
            print("Failed")

    return response


def delete_previous_comments(comments_urls: list[str]) -> None:
    if 'Authorization' not in http_headers:
        raise CommandException("Auth header missing, can't delete old comments!")

    comments_that_failed_to_delete = []
    for url in comments_urls:
        print("Deleting old comment ... ", end="")
        response = requests.delete(url, headers=http_headers)
        print(response.status_code)
        if response.status_code not in [204, 404]:
            comments_that_failed_to_delete.append(url)

    if len(comments_that_failed_to_delete) > 0:
        raise CommandException('\n'.join(comments_that_failed_to_delete))


def does_string_contain_jira(string_to_match: str) -> Optional[str]:
    pr_title_re = re.compile(f"({_AAP_RE}|{_NO_JIRA_MARKER})")
    matches = pr_title_re.search(string_to_match)
    print(f"Checking if {string_to_match} contains our RE ... ", end="")
    if not matches:
        print("Failed!")
        return None
    else:
        print("Good!")
    return matches.groups()[0]


def get_commit_jira_numbers(commit_url: str) -> list[str]:
    print("Getting commits ... ", end="")
    commits = requests.get(commit_url)
    print(commits.status_code)
    if commits.status_code != 200:
        raise CommandException("Failed to get commits!")
    comment_re = re.compile(rf"({_AAP_RE}|{_NO_JIRA_MARKER})")
    possible_jiras = []
    for commit in commits.json():
        # TODO: How to check if this is a merge commit or a regular comment?
        matches = comment_re.search(commit["commit"]["message"])
        print(f"Checking if {commit['commit']['message']} has a JIRA number in it ... ", end="")
        if matches:
            print(f"Good: {matches.groups()[0]}")
            possible_jiras.append(matches.groups()[0])
        else:
            print("None detected")

    return possible_jiras


def does_pr_reference_ticket(
    pr_title_jira: Optional[str],
    possible_commit_jiras: list[str],
    source_branch_jira: Optional[str],
) -> bool:
    """
    Does the PR reference at least one JIRA ticket?

    Although it seems to be sparsely documented, the JIRA "DVCS" plugin expects
    *at least one* of the following:

    - A ticket key (AAP-nnnnnn) in the PR title
    - A ticket key in the branch name
    - A ticket key in a commit message in the set of commits in the PR

    It seems there is no notion of conflict handling: If multiple different
    ticket keys are found, it will simply attach the PR to all referenced
    tickets.
    """

    print("")
    print("Checking validity based on the following:")
    print(f"JIRA from title: {pr_title_jira}")
    print(f"JIRA from source branch: {source_branch_jira}")
    print(f"JIRAS from commits: {', '.join(possible_commit_jiras)}")
    print("")

    # PR title or source branch is truthy means we found a regex match on the
    # ticket key
    # A non-empty possible_commit_jiras means at least one commit matched
    return any([pr_title_jira, source_branch_jira, possible_commit_jiras])


def main(args=[]):
    dry_run = False

    parser = argparse.ArgumentParser(
        description="A tool for checking if a PR matches the DVCS rules.\n\n"
        "This program requires the body of the pull request as an environment variable PULL_REQUEST.\n"
        "To generate this you can do a curl command line: export PULL_REQUEST=$(curl https://api.github.com/repos/ansible/dvcs-action/pulls/8)",
        add_help=True,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument('--dry-run', action='store_true', help='Add debug messages and do not attempt to write to the PR')
    args = parser.parse_args(args)
    if hasattr(args, 'dry_run'):
        dry_run = args.dry_run

    # Get and validate the data from the environment (the GitHub action should pass this in)
    try:
        pull_request = json.loads(getenv("PULL_REQUEST", {}))
    except json.JSONDecodeError as jde:
        print(f"Failed to load json from string: {jde}")
        exit(255)

    print(f"Running DVCS v3 in dry-run={dry_run}")

    if not dry_run:
        GITHUB_TOKEN = getenv("GH_TOKEN")
        if not GITHUB_TOKEN:
            print("Did not get a github token, failing!")
            exit(255)
        print("Added authentication to headers")
        http_headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    pull_urls = pull_request.get("_links", {})
    comments_url = pull_request.get("_links", {}).get("comments", {}).get("href")

    if not dry_run:
        try:
            delete_previous_comments(get_previous_comments_urls(comments_url))
        except CommandException as ce:
            print("Failed to delete one or more comments:")
            print(ce)
            exit(255)

    # Check the PR title
    pr_title_jira = does_string_contain_jira(pull_request.get("title"))

    # Check the PR commits
    try:
        possible_commit_jiras = get_commit_jira_numbers(pull_urls.get("commits", {}).get("href"))
    except CommandException as ce:
        # Don't fail out in this case, if we already found a JIRA key, we might
        # not even care about commits here.
        print(f"Failed to get commits: {ce}")
        possible_commit_jiras = []

    # Check the PR source branch
    source_branch_jira = does_string_contain_jira(pull_request.get("head", {}).get("ref", ""))

    pr_is_valid = does_pr_reference_ticket(pr_title_jira, possible_commit_jiras, source_branch_jira)

    new_comment_body = comment_preamble
    if pr_is_valid:
        new_comment_body += "\n\nPR appears valid (JIRA key(s) found)"
    else:
        new_comment_body += "\n\nCould not find JIRA key(s) in PR title, branch name, or commit messages"

    # Post the new comment
    if not dry_run:
        print("Creating new comment ... ", end="")
        response = requests.post(comments_url, json={"body": new_comment_body}, headers=http_headers)
        print(response.status_code)
        if response.status_code != 201:
            print("Failed to add new comment")

    exit(0 if pr_is_valid else 255)


if __name__ == '__main__':
    main(argv[1:])
