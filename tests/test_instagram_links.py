"""Instagram link shapes: every form the app and the site produce must parse.

A rejected link ends as «не понял ссылку» in the chat, so the recognizer is the first thing
a user hits. Instagram is generous with formats, the parser has to be too.
"""

import pytest

from core import instagram


@pytest.mark.parametrize(
    "url, expected",
    [
        # plain post
        ("https://www.instagram.com/p/DaevwwljDpJ/", ("p", "DaevwwljDpJ")),
        ("https://instagram.com/p/DaevwwljDpJ", ("p", "DaevwwljDpJ")),
        ("https://m.instagram.com/p/DaevwwljDpJ/?igsh=abc", ("p", "DaevwwljDpJ")),
        # reels, all spellings
        ("https://www.instagram.com/reel/DerTqtETnvX/", ("reel", "DerTqtETnvX")),
        ("https://www.instagram.com/reels/DerTqtETnvX/", ("reel", "DerTqtETnvX")),
        ("https://www.instagram.com/reel/DerTqtETnvX/?igsh=MTE", ("reel", "DerTqtETnvX")),
        # handle in front of the kind, the form the site shows in a browser
        ("https://www.instagram.com/ilya_frolov4/reel/DerTqtETnvX/", ("reel", "DerTqtETnvX")),
        # app share link, the token is resolved later
        ("https://www.instagram.com/share/reel/BAO123xyz/", ("reel", "BAO123xyz")),
        # old ig.tv
        ("https://www.instagram.com/tv/BxYzAbC123/", ("tv", "BxYzAbC123")),
        # short domain
        ("https://instagr.am/p/DaevwwljDpJ/", ("p", "DaevwwljDpJ")),
        # no protocol at all, as people often paste it
        ("instagram.com/reel/DerTqtETnvX/", ("reel", "DerTqtETnvX")),
    ],
)
def test_post_links_parse(url, expected):
    assert instagram._parse_shortcode(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/p/abc",
        "https://www.instagram.com/",
        "https://www.instagram.com/ilya_frolov4/",
        "https://www.instagram.com/reels/audio/2256000000000000/",
        "https://www.instagram.com/explore/tags/moscow/",
        "",
    ],
)
def test_non_post_links_are_rejected(url):
    assert instagram._parse_shortcode(url) is None


def test_share_links_are_marked_for_resolution():
    assert instagram._looks_shared("https://www.instagram.com/share/reel/BAO123xyz/")
    assert instagram._looks_shared("https://www.instagram.com/share/p/BAO123xyz")
    assert not instagram._looks_shared("https://www.instagram.com/reel/DerTqtETnvX/")


def test_unrecognized_link_is_reported_without_going_to_the_network(monkeypatch):
    calls = []
    monkeypatch.setattr(instagram.httpx, "get", lambda *a, **k: calls.append(a))
    body, shortcode, kind, err = instagram._embed_body("https://www.instagram.com/ilya_frolov4/")
    assert err == "Не похоже на ссылку Instagram"
    assert not calls, "a link that is not a post must not cost a request"
