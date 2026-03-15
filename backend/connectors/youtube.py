"""YouTube Connector — play videos and music through browser automation.

Handles:
  - Video/music playback ("play dance monkey", "play lofi beats")
  - YouTube search ("search youtube for cooking tutorials")
  - Ad handling (Skip Ad button detection)
  - Playback verification (video playing, title matches)
"""

from __future__ import annotations

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillMode
from backend.connectors.executors import youtube_play_video, youtube_search


class YouTubeConnector(BaseConnector):
    """YouTube — play videos, music, and search content."""

    name = "youtube"
    description = "YouTube — play videos, play music, search for content"
    icon = "▶"
    category = "media"

    def _setup(self) -> None:
        self._register_play_video()
        self._register_search()

    def _register_play_video(self) -> None:
        self.register_skill(Skill(
            name="play_video",
            description="Play a video or song on YouTube. Navigates to YouTube, searches, finds the best result (preferring official/music videos), clicks to play, and handles ads.",
            connector=self.name,
            mode=SkillMode.DETERMINISTIC,
            start_url="https://www.youtube.com",
            executor=youtube_play_video,
            browser_template=(
                "Go to youtube.com. Search for '{query}'. "
                "Click the first official or music video result. "
                "If a 'Skip Ad' or 'Skip Ads' button appears, click it. "
                "Verify the video is playing."
            ),
            params=[
                SkillParam(
                    name="query",
                    description="What to play — song name, video title, artist, or search query",
                ),
            ],
            tags=["youtube", "video", "play", "music", "song", "watch", "stream", "media", "listen", "audio"],
            examples=[
                "play dance monkey",
                "play lofi beats on youtube",
                "play shape of you by ed sheeran",
                "watch never gonna give you up",
                "play some jazz music",
                "play cooking tutorial",
            ],
        ))

    def _register_search(self) -> None:
        self.register_skill(Skill(
            name="search_video",
            description="Search YouTube for videos without auto-playing. Returns search results page for browsing.",
            connector=self.name,
            mode=SkillMode.DETERMINISTIC,
            start_url="https://www.youtube.com",
            executor=youtube_search,
            browser_template=(
                "Go to youtube.com. Search for '{query}'. "
                "Read the search results and report what you find."
            ),
            params=[
                SkillParam(
                    name="query",
                    description="Search query for YouTube",
                ),
            ],
            tags=["youtube", "search", "find", "video", "browse"],
            examples=[
                "search youtube for python tutorials",
                "find videos about machine learning",
            ],
        ))
