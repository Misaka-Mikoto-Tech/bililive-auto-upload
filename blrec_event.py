
from session import Session


class BlrecEvent:
    @staticmethod
    def get_room_id(json:str): # blrec 的事件数据 room_id 字段的位置不统一
        if json["data"].get("room_info") is not None:
            return json["data"]["room_info"]["room_id"]
        else:
            return json["data"]["room_id"]

    @staticmethod
    def update_room_info(json:str, session:Session):
        if json["data"]["room_info"] is not None: # RoomChangeEvent, RecordingStartedEvent,RecordingFinishedEvent 等
            session.uid = json["data"]["room_info"]["uid"]
            session.room_title = json["data"]["room_info"]["title"]

        if json["data"]["user_info"] is not None: # LiveBeganEvent, LiveEndedEvent, RoomChangeEvent
            session.room_name = json["data"]["user_info"]["name"]