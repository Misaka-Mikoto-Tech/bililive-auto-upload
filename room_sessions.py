from __future__ import annotations

from requests import session
from session import Session, Video

# 可能出现连续同一个主播连续录两场，但上一场还未通过审核的情况，因此需要管理Session
class RoomSessions:
    room_id:int
    sessions:set[Session]
    active_session:Session
    max_session_id:int

    def __init__(self, room_id:int) -> None:
        self.room_id = room_id
        self.session = set()
        self.active_session = None
        self.max_session_id = 0
        
    def  get_active_session(self) -> Session:
            return self.active_session

    def add_session_and_active(self, session:Session):
        session.session_id = self.max_session_id
        session.room_sessions = self
        self.sessions.add(session)
        self.active_session = session
        self.max_session_id += 1

    def remove_session(self, session:Session):
        self.sessions.remove(session)
        if session == self.active_session:
            self.active_session = None
