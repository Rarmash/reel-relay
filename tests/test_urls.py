import pytest
from app.downloader import validate_instagram_url


@pytest.mark.parametrize("url", [
    "https://instagram.com/reel/abc/",
    "https://www.instagram.com/reels/abc/?x=1",
    "https://m.instagram.com/p/abc/",
])
def test_allowed_urls(url):
    assert validate_instagram_url(url) == url


@pytest.mark.parametrize("url", [
    "http://instagram.com/reel/a", "https://evil.example/reel/a",
    "https://instagram.com.evil.example/reel/a", "https://user@instagram.com/reel/a",
    "https://instagram.com/profile/a", "https://127.0.0.1/reel/a",
    "https://instagram.com:444/reel/a", "https://instagram.com@evil.example/reel/a",
])
def test_rejected_urls(url):
    with pytest.raises(ValueError): validate_instagram_url(url)
