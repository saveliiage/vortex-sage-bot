"""Story links: URL parsing, cookie jar parsing and the media entry picker.

All of it is offline — the point is that a story link reaches the story path and that a
missing Instagram session is reported as such, never as a generic download failure.
"""

from core import instagram


def test_story_target_reads_handle_and_media_id():
    url = (
        "https://www.instagram.com/stories/ilya_frolov4/4019984829780954506"
        "?utm_source=ig_story_item_share&vrfl=MXVmM3pwcGU2anl2MA=="
    )
    assert instagram.story_target(url) == ("ilya_frolov4", "4019984829780954506", "")


def test_story_target_whole_profile_and_highlights():
    assert instagram.story_target("https://www.instagram.com/stories/nasa/") == ("nasa", "", "")
    assert instagram.story_target(
        "https://www.instagram.com/stories/highlights/17913000000000000/"
    ) == ("", "", "17913000000000000")


def test_story_target_ignores_posts_and_other_sites():
    assert instagram.story_target("https://www.instagram.com/p/DaevwwljDpJ/") is None
    assert instagram.story_target("https://www.youtube.com/stories/abc/123") is None
    assert instagram.story_target("") is None


def test_ig_jar_keeps_instagram_cookies_only(monkeypatch, tmp_path):
    jar_file = tmp_path / "instagram.txt"
    jar_file.write_text(
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\tSECRET1\n"
        ".instagram.com\tTRUE\t/\tTRUE\t9999999999\tds_user_id\t42\n"
        ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tSID\tOTHER\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(instagram, "IG_COOKIES_FILE", str(jar_file))
    jar = instagram._ig_jar()
    assert jar.get("sessionid") == "SECRET1"
    assert jar.get("ds_user_id") == "42"
    assert "SID" not in jar


def test_story_media_refuses_without_a_session(monkeypatch, tmp_path):
    monkeypatch.setattr(instagram, "IG_COOKIES_FILE", str(tmp_path / "missing.txt"))
    result = instagram._story_media("ilya_frolov4", "4019984829780954506", "")
    assert result == {"success": False, "error": instagram.STORY_NEEDS_LOGIN}


def test_story_buckets_reads_both_response_shapes():
    items = [{"pk": 1}, {"pk": 2}]
    dict_shape = {"reels": {"123": {"items": items}}}
    list_shape = {"reels_media": [{"items": items}]}
    assert len(instagram._story_buckets(dict_shape)) == 2
    assert len(instagram._story_buckets(list_shape)) == 2
    assert instagram._story_buckets({}) == []


def test_story_entry_prefers_the_biggest_media():
    video_item = {
        "pk": 555,
        "video_versions": [
            {"width": 480, "height": 854, "url": "small.mp4"},
            {"width": 1080, "height": 1920, "url": "big.mp4"},
        ],
        "image_versions2": {"candidates": [{"width": 1080, "height": 1920, "url": "cover.jpg"}]},
    }
    entry = instagram._story_entry(video_item)
    assert entry is not None
    assert (entry["type"], entry["url"], entry["thumb"], entry["id"]) == (
        "video", "big.mp4", "cover.jpg", "555"
    )

    photo_item = {
        "pk": 777,
        "image_versions2": {"candidates": [
            {"width": 320, "height": 568, "url": "small.jpg"},
            {"width": 1080, "height": 1920, "url": "big.jpg"},
        ]},
    }
    photo = instagram._story_entry(photo_item)
    assert photo is not None
    assert (photo["type"], photo["url"]) == ("photo", "big.jpg")

    assert instagram._story_entry({"pk": 1}) is None
