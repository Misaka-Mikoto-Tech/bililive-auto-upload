from __future__ import annotations

from requests import session
from session import Session, Video

class RoomSessions:
    room_id:int
    sessions:dict[int,Session]
    active_session:Session

    def __init__(self, room_id:int) -> None:
        self.room_id = room_id
        self.session = dict()
        self.active_session = None
        
    def  get_active_session(self) -> Session:
            return self.active_session

    def add_session_and_active(self, session:Session):
        session.room_sessions = self
        self.sessions.add(session)
        self.active_session = session

    def remove_session(self, session:Session):
        self.sessions.remove(session)
        if session == self.active_session:
            self.active_session = None

# 可能出现连续同一个主播连续录两场，但上一场还未通过审核的情况，因此需要管理Session
class SessionManager:
    all_sessions:dict[int, Session] # [session_id, Session]
    recording_session_of_room:dict[int, Session] # 当前正在录制的 Session, [room_id, Session]
    __max_session_id:int

    def __init__(self) -> None:
        self.all_sessions = dict()
        self.recording_session_of_room = dict()
        self.__max_session_id = 1

    def add_session(self, session:Session):
        session.session_id = self.__max_session_id
        session.session_manager = self
        self.__max_session_id += 1
        self.all_sessions[session.session_id] = session
        self.recording_session_of_room[session.room_id] = session

    def remove_session(self, session:Session):
        self.all_sessions.pop(session.session_id, None)
        if self.recording_session_of_room[session.room_id] == session:
            self.recording_session_of_room.pop(session.room_id, None)

    def get_recording_session(self, room_id:int):
        return self.recording_session_of_room.get(room_id)
            
