from unittest import mock

import pytest
import requests_mock
from requests.exceptions import MissingSchema  # type: ignore

from dvcs import check_dvcs


class TestDoesStringContainJira:

    @pytest.mark.parametrize(
        "input,expected_return",
        [
            ("testing", None),
            (f'{check_dvcs._NO_JIRA_MARKER} other stuff', check_dvcs._NO_JIRA_MARKER),
            ('AAP-2222 other stuff', 'AAP-2222'),
            ('other stuff AAP-3333', 'AAP-3333'),
            ('other stuff AAP-4444 jira in the middle', 'AAP-4444'),
            ('a-hoopy-AAP-9999-frood', 'AAP-9999'),
            ('a-hoopy-aap-9999-frood', None),
            ('aap-9999 hey', None),
            ('Aap-9999 hey', None),
            ('AAP-9999 hey', 'AAP-9999'),
        ],
    )
    def test_does_string_contain_jira_function(self, input, expected_return):
        result = check_dvcs.does_string_contain_jira(input)
        assert result == expected_return


class TestGetPreviousCommentsUrls:

    def test_invalid_url(self):
        with pytest.raises(MissingSchema):
            check_dvcs.get_previous_comments_urls("www.example.com")

    def test_invalid_status_code(self):
        with pytest.raises(check_dvcs.CommandException):
            with requests_mock.Mocker() as m:
                m.register_uri('GET', 'https://example.com', status_code=404)
                check_dvcs.get_previous_comments_urls("https://example.com")

    @pytest.mark.parametrize(
        "json,expected_result",
        [
            ([], []),
            (
                [
                    {
                        "body": "This comment does not match",
                        "url": "https://example.com/1",
                    },
                ],
                [],
            ),
            (
                [
                    {
                        "body": f"{check_dvcs.comment_preamble} This comment should match",
                        "url": "https://example.com/1",
                    },
                ],
                ["https://example.com/1"],
            ),
        ],
    )
    def test_valid_json(self, json, expected_result):
        with requests_mock.Mocker() as m:
            m.register_uri('GET', 'https://example.com', status_code=200, json=json)
            response = check_dvcs.get_previous_comments_urls("https://example.com")
            assert response == expected_result


class TestDeletePreviousComments:

    def test_missing_header(self):
        with pytest.raises(check_dvcs.CommandException) as ce:
            check_dvcs.delete_previous_comments([])
        assert 'Auth header missing' in str(ce.value)

    def test_good_delete(self):
        base_url = 'https://example.com/'
        with requests_mock.Mocker() as m:
            m.register_uri('DELETE', f'{base_url}1', status_code=404)
            m.register_uri('DELETE', f'{base_url}2', status_code=204)
            check_dvcs.http_headers['Authorization'] = 'Bearer 1234'
            check_dvcs.delete_previous_comments([f'{base_url}1', f'{base_url}2'])

    def test_bad_deletes(self):
        base_url = 'https://example.com/'
        with requests_mock.Mocker() as m:
            m.register_uri('DELETE', f'{base_url}1', status_code=500)
            m.register_uri('DELETE', f'{base_url}2', status_code=201)
            m.register_uri('DELETE', f'{base_url}3', status_code=404)
            m.register_uri('DELETE', f'{base_url}4', status_code=204)
            with pytest.raises(check_dvcs.CommandException) as ce:
                check_dvcs.http_headers['Authorization'] = 'Bearer 1234'
                check_dvcs.delete_previous_comments(
                    [
                        f'{base_url}1',
                        f'{base_url}2',
                        f'{base_url}3',
                        f'{base_url}4',
                    ]
                )
            assert f'{base_url}1' in str(ce.value)
            assert f'{base_url}2' in str(ce.value)
            assert f'{base_url}3' not in str(ce.value)
            assert f'{base_url}4' not in str(ce.value)


class TestGitCommitJiraNumbers:

    def test_invalid_url(self):
        with pytest.raises(MissingSchema):
            check_dvcs.get_commit_jira_numbers("www.example.com")

    def test_invalid_status_code(self):
        with pytest.raises(check_dvcs.CommandException):
            with requests_mock.Mocker() as m:
                m.register_uri('GET', 'https://example.com', status_code=404)
                check_dvcs.get_commit_jira_numbers("https://example.com")

    @pytest.mark.parametrize(
        "json,expected_result",
        [
            ([], []),
            (
                [
                    {"commit": {"message": "This is wrong"}},
                ],
                [],
            ),
            (
                [
                    {"commit": {"message": f"{check_dvcs._NO_JIRA_MARKER} This has the no jira marker"}},
                ],
                [check_dvcs._NO_JIRA_MARKER],
            ),
            (
                [
                    {"commit": {"message": "AAP-1234 This has the jira marker"}},
                ],
                ['AAP-1234'],
            ),
            (
                [
                    {"commit": {"message": "ABC-0909 This has wrong jira marker format"}},
                ],
                [],
            ),
        ],
    )
    def test_json_return(self, json, expected_result):
        with requests_mock.Mocker() as m:
            m.register_uri('GET', 'https://example.com', status_code=200, json=json)
            response = check_dvcs.get_commit_jira_numbers("https://example.com")
            assert response == expected_result


class TestMain:

    @pytest.mark.parametrize(
        "json",
        [
            "{'bad': 'json',}",
            "",
        ],
    )
    def test_invalid_pull_input(self, capsys, json, monkeypatch):
        monkeypatch.setenv('PULL_REQUEST', json)
        with pytest.raises(SystemExit) as e:
            check_dvcs.main()
        output = capsys.readouterr()
        assert "Failed to load json from string" in output.out
        assert e.value.code == 255

    @pytest.mark.parametrize(
        "token",
        [
            None,
            "",
        ],
    )
    def test_github_invalid_token(self, capsys, token, monkeypatch):
        monkeypatch.setenv('PULL_REQUEST', "{}")
        if token:
            monkeypatch.setenv('GH_TOKEN', token)
        with pytest.raises(SystemExit) as e:
            check_dvcs.main()
        output = capsys.readouterr()
        assert "Did not get a github token, failing" in output.out
        assert e.value.code == 255

    def test_delete_previous_commit_fails(self, capsys, monkeypatch):
        monkeypatch.setenv('PULL_REQUEST', "{}")
        monkeypatch.setenv('GH_TOKEN', "asdf1234")
        with mock.patch('dvcs.check_dvcs.get_previous_comments_urls', side_effect=check_dvcs.CommandException("Failing on purpose")):
            with pytest.raises(SystemExit) as e:
                check_dvcs.main()
            output = capsys.readouterr()
            assert "Failed to delete one or more comments" in output.out
            assert e.value.code == 255

    def test_fail_to_get_commits(self, capsys, monkeypatch):
        """
        If we fail to get commits, don't bail out - we might have found a JIRA
        key in the PR title or branch name that we can use instead. But still
        report the failure to stdout.
        """
        monkeypatch.setenv('PULL_REQUEST', '{"title": "junk"}')
        monkeypatch.setenv('GH_TOKEN', "asdf1234")
        with mock.patch('dvcs.check_dvcs.get_previous_comments_urls', return_value=[]):
            with mock.patch('dvcs.check_dvcs.get_commit_jira_numbers', side_effect=check_dvcs.CommandException("Failing on purpose")):
                with mock.patch('dvcs.check_dvcs.requests.post'):
                    try:
                        check_dvcs.main()
                    except SystemExit:
                        pass  # We get to the end... This isn't what we're testing for.
                output = capsys.readouterr()
                assert "Failed to get commits" in output.out

    def test_failed_to_add_comment(self, capsys, monkeypatch):
        monkeypatch.setenv('PULL_REQUEST', '{"title": "junk", "_links": {"comments": {"href": "https://example.com"}}}')
        monkeypatch.setenv('GH_TOKEN', "asdf1234")
        with mock.patch('dvcs.check_dvcs.get_previous_comments_urls', return_value=[]):
            with mock.patch('dvcs.check_dvcs.get_commit_jira_numbers', return_value=[]):
                with mock.patch('dvcs.check_dvcs.does_pr_reference_ticket', return_value=True):
                    with requests_mock.Mocker() as m:
                        m.register_uri('POST', 'https://example.com', status_code=404)
                        with pytest.raises(SystemExit) as e:
                            check_dvcs.main()  # We don't raise an exception for this, we exit normally
                        output = capsys.readouterr()
                        assert "Failed to add new comment" in output.out
                        assert e.value.code == 0

    def test_failed_check(self, monkeypatch):
        monkeypatch.setenv('PULL_REQUEST', '{"title": "junk", "_links": {"comments": {"href": "https://example.com"}}}')
        monkeypatch.setenv('GH_TOKEN', "asdf1234")
        with mock.patch('dvcs.check_dvcs.get_previous_comments_urls', return_value=[]):
            with mock.patch('dvcs.check_dvcs.get_commit_jira_numbers', return_value=[]):
                with requests_mock.Mocker() as m:
                    m.register_uri('POST', 'https://example.com', status_code=201)
                    with pytest.raises(SystemExit) as e:
                        check_dvcs.main()
                    assert e.value.code == 255


class TestDoesPrReferenceTicket:

    @pytest.mark.parametrize(
        "pr_title_jira, possible_commit_jiras, source_branch_jira, expected_result",
        [
            (  # No key in PR title, commits and source branch both have NO_JIRA
                None,
                [f'{check_dvcs._NO_JIRA_MARKER}'],
                f'{check_dvcs._NO_JIRA_MARKER}',
                True,
            ),
            (  # Key in PR title, multiple in commits, key in branch name
                'AAP-1234',
                ['AAP-1235', 'AAP-1235'],
                'AAP-1234',
                True,
            ),
            (  # NO_JIRA in PR title, keys in commits and source branch
                f"{check_dvcs._NO_JIRA_MARKER}",
                ['AAP-1234'],
                'AAP-45657',
                True,
            ),
            (  # Key in PR title and commit, not in branch name
                "AAP-1234",
                [f'{check_dvcs._NO_JIRA_MARKER}'],
                None,
                True,
            ),
            (  # Source branch does not match jira PR
                "AAP-56788",
                ['AAP-1234', 'AAP-1234'],
                'AAP-1234',
                True,
            ),
            (  # Key in PR title and branch name, not in commit
                "AAP-1234",
                [],
                'AAP-1235',
                True,
            ),
            (  # Key only in PR title
                'AAP-9009',
                [],
                None,
                True,
            ),
            (  # Key only in commit
                None,
                ['AAP-93993'],
                None,
                True,
            ),
            (  # Key only in PR title
                None,
                [],
                'AAP-77888',
                True,
            ),
            (  # No key in PR title, branch name, or commit.
                None,
                [],
                None,
                False,
            ),
        ],
        ids=[
            "No key in PR title, commits and source branch both have NO_JIRA",
            "Key in PR title, multiple in commits, key in branch name",
            "NO_JIRA in PR title, keys in commits and source branch",
            "Key in PR title and commit, not in branch name",
            "Source branch does not match jira PR",
            "Key in PR title and branch name, not in commit",
            "Key only in PR title",
            "Key only in commit",
            "Key only in PR title",
            "No key in PR title, branch name, or commit.",
        ],
    )
    def test_does_pr_reference_ticket(self, pr_title_jira, possible_commit_jiras, source_branch_jira, expected_result):
        result = check_dvcs.does_pr_reference_ticket(pr_title_jira, possible_commit_jiras, source_branch_jira)
        assert result == expected_result
