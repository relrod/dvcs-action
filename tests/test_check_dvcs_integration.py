import json
import pytest

from dvcs import check_dvcs


NO_JIRA_FIXTURE = {
    "title": "NO_JIRA test",
    "_links": {
        "commits": {
            "href": "https://api.github.com/repos/ansible/django-ansible-base/pulls/707/commits",
        }
    }
}

JIRA_KEY_FIXTURE = {
    "title": "AAP-41963 test",
    "_links": {
        "commits": {
            "href": "https://api.github.com/repos/ansible/django-ansible-base/pulls/707/commits",
        }
    }
}

@pytest.mark.parametrize(
    'json,allow_no_jira,jira_from_title,should_match',
    [
        (NO_JIRA_FIXTURE, True, "NO_JIRA", True),
        (NO_JIRA_FIXTURE, False, "None", False),
        (JIRA_KEY_FIXTURE, True, "AAP-41963", True),
        (JIRA_KEY_FIXTURE, False, "AAP-41963", True),
    ]
)
def test_allow_no_jira_flag(json, allow_no_jira, jira_from_title, should_match, monkeypatch, capsys):
    args = ["--dry-run"]
    if allow_no_jira:
        args.append("--allow-no-jira")
    monkeypatch.setenv("PULL_REQUEST", json.dumps(json))
    rc = check_dvcs.main(args)
    captured = capsys.readouterr()
    assert rc == (0 if should_match else 1)
    assert f"JIRA from title: {jira_from_title}" in captured.out
