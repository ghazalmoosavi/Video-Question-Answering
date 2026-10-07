import pytest
from app.youtube import extract_video_id, InvalidYouTubeURLError

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=30s",
    f"http://www.youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?t=10",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"https://www.youtube.com/live/{VID}",
    VID,
    f"  {VID}  ",
])
def test_extract_video_id_valid(url):
    assert extract_video_id(url) == VID


@pytest.mark.parametrize("bad", ["", "   ", "not a url", "https://example.com/watch?v=short", "https://youtube.com/watch"])
def test_extract_video_id_invalid(bad):
    with pytest.raises(InvalidYouTubeURLError):
        extract_video_id(bad)
