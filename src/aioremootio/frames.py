# Copyright 2021 Gergö Gabor Ilyes-Veisz
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from abc import ABC, abstractmethod
from typing import Optional, Any, NoReturn
from .enums import ErrorType, ActionType, State, EventType, KeyType, DeviceType, FrameType
from .models import Key


def retrieve_frame_type(frame: Any) -> FrameType:
    result: Optional[FrameType] = None

    if type(frame) is dict and "type" in frame:
        result = FrameType(frame["type"])

    return result


def ensure_frame_type(frame: dict, frame_type: FrameType) -> NoReturn:
    assert frame["type"] == frame_type.value


class AbstractFrame(ABC):
    pass


class AbstractJSONHolderFrame(ABC):

    @property
    @abstractmethod
    def json(self) -> dict:
        return {}


class AbstractUptimeHolderFrame(ABC):
    __uptime: int

    def __init__(self, uptime: int):
        self.__uptime = uptime

    @property
    def uptime(self) -> int:
        return self.__uptime


class AbstractStateHolderFrame(ABC):
    __state: State

    def __init__(self, state: State):
        self.__state = state

    @property
    def state(self):
        return self.__state


class AuthFrame(AbstractFrame, AbstractJSONHolderFrame):

    @property
    def json(self) -> dict:
        return { "type": "AUTH" }


class PingFrame(AbstractFrame, AbstractJSONHolderFrame):

    @property
    def json(self) -> dict:
        return { "type": "PING" }


class HelloFrame(AbstractFrame, AbstractJSONHolderFrame):

    @property
    def json(self) -> dict:
        return { "type": "HELLO" }


class ServerHelloFrame(AbstractFrame):
    __api_version: int
    __serial_number: Optional[str]
    __device_type: Optional[DeviceType]

    def __init__(self, frame: dict):
        self.__api_version = frame["apiVersion"]
        self.__serial_number = None
        self.__device_type = None

        if "serialNumber" in frame:
            self.__serial_number = frame["serialNumber"]

        if "remootioVersion" in frame:
            self.__device_type = DeviceType(frame["remootioVersion"])

    @property
    def api_version(self) -> int:
        return self.__api_version

    @property
    def serial_number(self) -> Optional[str]:
        return self.__serial_number

    @property
    def device_type(self) -> Optional[DeviceType]:
        return self.__device_type


class ErrorFrame(AbstractFrame):
    __error_type: ErrorType

    def __init__(self, error_type: ErrorType):
        self.__error_type = error_type

    @property
    def error_type(self) -> ErrorType:
        return self.__error_type


class ChallengeFrame(AbstractFrame):
    __session_key: str
    __initial_action_id: int

    def __init__(self, frame: dict):
        self.__session_key = frame["challenge"]["sessionKey"]
        self.__initial_action_id = frame["challenge"]["initialActionId"]

    @property
    def session_key(self) -> str:
        return self.__session_key

    @property
    def initial_action_id(self) -> int:
        return self.__initial_action_id


class AbstractActionFrame(AbstractFrame):
    __action_id: int
    __action_type: ActionType

    def __init__(self, action_id: int, action_type: ActionType):
        self.__action_id = action_id
        self.__action_type = action_type

    @property
    def action_id(self) -> int:
        return self.__action_id

    @property
    def action_type(self) -> ActionType:
        return self.__action_type


class ActionRequestFrame(AbstractActionFrame, AbstractJSONHolderFrame):
    def __init__(self, action_id: int, action_type: ActionType):
        super(ActionRequestFrame, self).__init__(action_id, action_type)

    @property
    def json(self) -> dict:
        return {
            "action": {
                "id": self.action_id,
                "type": self.action_type.value
            }
        }


class ActionResponseFrame(AbstractActionFrame, AbstractStateHolderFrame, AbstractUptimeHolderFrame):
    __success: bool
    __relay_triggered: bool
    __error_code: str

    def __init__(self, frame: dict):
        AbstractActionFrame.__init__(self, frame["response"]["id"], ActionType(frame["response"]["type"]))
        AbstractStateHolderFrame.__init__(self, State(frame["response"]["state"]))
        AbstractUptimeHolderFrame.__init__(self, frame["response"]["t100ms"] * 100 / 1000)
        self.__success = str(frame["response"]["success"]).lower() == "true"
        self.__relay_triggered = str(frame["response"]["relayTriggered"]).lower() == "true"
        self.__error_code = frame["response"]["errorCode"]

    @property
    def success(self) -> bool:
        return self.__success


class EventFrame(AbstractFrame, AbstractStateHolderFrame, AbstractUptimeHolderFrame):
    __event_type: EventType
    __key: Optional[Key]

    def __init__(self, frame: dict):
        AbstractStateHolderFrame.__init__(self, State(frame["event"]["state"]))
        AbstractUptimeHolderFrame.__init__(self, frame["event"]["t100ms"] * 100 / 1000)
        self.__event_type = EventType(frame["event"]["type"])
        self.__key = None

        if "data" in frame:
            if "keyType" in frame["data"] and "keyNr" in frame["data"]:
                self.__key = Key(KeyType(frame["data"]["keyType"]), frame["data"]["keyNr"])

    @property
    def event_type(self) -> EventType:
        return self.__event_type

    @property
    def key(self) -> Optional[Key]:
        return self.__key


class EncryptedFrame(AbstractFrame, AbstractJSONHolderFrame):
    __json: Optional[dict]
    __data: Optional[dict]
    __iv: str
    __payload: Optional[str]
    __mac: str

    def __init__(self, json: dict):
        self.__json = json
        self.__data = self.json["data"]
        self.__iv = self.data["iv"]
        self.__payload = self.data["payload"]
        self.__mac = self.json["mac"]

    def __init(self, iv: str, payload: str, mac: str):
        self.__json = None
        self.__data = None
        self.__iv = iv
        self.__payload = payload
        self.__mac = mac

        self.__data = {
            "iv": self.iv,
            "payload": self.payload
        }

        self.__json = {
            "type": "ENCRYPTED",
            "data": self.data,
            "mac": self.mac
        }

    @property
    def json(self) -> dict:
        return self.__json

    @property
    def data(self) -> dict:
        return self.__data

    @property
    def iv(self) -> str:
        return self.__iv

    @property
    def payload(self) -> str:
        return self.__payload

    @property
    def mac(self) -> str:
        return self.__mac
