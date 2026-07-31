from dataclasses import dataclass
from typing import Optional


@dataclass
class Driver:
    name: str
    iracing_id: int
    discord_id: Optional[str] = None
    enabled: bool = True


@dataclass
class LiveState:
    series: str = ""
    track: str = ""
    session_type: str = ""
    flag: str = ""
    field_size: Optional[int] = None
    subsession_id: Optional[int] = None
    lap: int = 0
    last_lap_time: float = 0.0
    pos: Optional[int] = None
    prev_pos: Optional[int] = None
    incidents: int = 0
    posted_joined: bool = False
    posted_green: bool = False
    posted_checkered: bool = False
    posted_qualify: bool = False
    last_posted_lap: int = -1
    qualify_best: float = 0.0

    def begin_new_session(
        self,
        *,
        series: Optional[str] = None,
        track: Optional[str] = None,
        subsession_id: Optional[int] = None,
    ) -> None:
        """Reset reporting flags for a new session, optionally preserving identity fields."""
        self.series = self.series if series is None else series
        self.track = self.track if track is None else track
        self.subsession_id = self.subsession_id if subsession_id is None else subsession_id
        self.session_type = ""
        self.flag = ""
        self.field_size = None
        self.lap = 0
        self.last_lap_time = 0.0
        self.pos = None
        self.prev_pos = None
        self.incidents = 0
        self.posted_joined = False
        self.posted_green = False
        self.posted_checkered = False
        self.posted_qualify = False
        self.last_posted_lap = -1
        self.qualify_best = 0.0
