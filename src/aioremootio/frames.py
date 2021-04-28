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
from .enums import ErrorType, ActionType, State, EventType, KeyType, DeviceType, FrameType, ErrorCode, EventSource
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

    def __init__(self, json: dict):
        ensure_frame_type(json, FrameType.SERVER_HELLO)

        self.__api_version = json["apiVersion"]
        self.__serial_number = None
        self.__device_type = None

        if "serialNumber" in json:
            self.__serial_number = json["serialNumber"]

        if "remootioVersion" in json:
            self.__device_type = DeviceType(json["remootioVersion"])

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

    def __init__(self, error_type: ErrorType = None, json: dict = None):
        if error_type is not None and json is None:
            self.__error_type = error_type
        elif error_type is None and json is not None:
            ensure_frame_type(json, FrameType.ERROR)

            self.__error_type = ErrorType(json["errorMessage"])
        else:
            raise RuntimeError("Unable to instantiate ErrorFrame based on the passed data.")

    @property
    def error_type(self) -> ErrorType:
        return self.__error_type


class ChallengeFrame(AbstractFrame, AbstractJSONHolderFrame):
    __json: dict
    __session_key: str
    __initial_action_id: int

    def __init__(self, json: dict):
        ensure_frame_type(json, FrameType.CHALLENGE)

        self.__json = json
        self.__session_key = json["challenge"]["sessionKey"]
        self.__initial_action_id = json["challenge"]["initialActionId"]

    @property
    def session_key(self) -> str:
        return self.__session_key

    @property
    def initial_action_id(self) -> int:
        return self.__initial_action_id

    @property
    def json(self) -> dict:
        return self.__json


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


class ActionResponseFrame(AbstractActionFrame, AbstractStateHolderFrame, AbstractUptimeHolderFrame,
                          AbstractJSONHolderFrame):
    __json: dict
    __success: bool
    __relay_triggered: bool
    __error_code: Optional[ErrorCode]

    def __init__(self, json: dict):
        AbstractActionFrame.__init__(self, json["response"]["id"], ActionType(json["response"]["type"]))
        AbstractStateHolderFrame.__init__(self, State(json["response"]["state"]))
        AbstractUptimeHolderFrame.__init__(self, json["response"]["t100ms"] * 100 / 1000)
        self.__json = json
        self.__success = str(json["response"]["success"]).lower() == "true"
        self.__relay_triggered = str(json["response"]["relayTriggered"]).lower() == "true"
        self.__error_code = None
        if not self.success and "errorCode" in json["response"] and len(json["response"]["errorCode"]) > 0:
            self.__error_code = ErrorCode(json["response"]["errorCode"])

    @property
    def success(self) -> bool:
        return self.__success

    @property
    def relay_triggered(self) -> bool:
        return self.__relay_triggered

    @property
    def error_code(self) -> Optional[ErrorCode]:
        return self.__error_code

    @property
    def json(self) -> dict:
        return self.__json


class EventFrame(AbstractFrame, AbstractStateHolderFrame, AbstractUptimeHolderFrame, AbstractJSONHolderFrame):
    __json: dict
    __event_source: Optional[EventSource]
    __event_type: EventType
    __key: Optional[Key]

    def __init__(self, json: dict):
        AbstractStateHolderFrame.__init__(self, State(json["event"]["state"]))
        AbstractUptimeHolderFrame.__init__(self, json["event"]["t100ms"] * 100 / 1000)
        self.__json = json
        self.__event_source = None
        self.__event_type = EventType(json["event"]["type"])
        self.__key = None

        if "data" in json["event"]:
            if "keyType" in json["event"]["data"] and "keyNr" in json["event"]["data"]:
                self.__key = Key(KeyType(json["event"]["data"]["keyType"]), json["event"]["data"]["keyNr"])

            if "via" in json["event"]["data"]:
                self.__event_source = EventSource(json["event"]["data"]["via"])

    @property
    def event_source(self) -> Optional[EventSource]:
        return self.__event_source

    @property
    def event_type(self) -> EventType:
        return self.__event_type

    @property
    def key(self) -> Optional[Key]:
        return self.__key

    @property
    def json(self) -> dict:
        return self.__json


class EncryptedFrame(AbstractFrame, AbstractJSONHolderFrame):
    __json: Optional[dict]
    __data: Optional[dict]
    __iv: str
    __payload: Optional[str]
    __mac: str

    def __init__(self, json: dict = None, iv: str = None, payload: str = None, mac: str = None):
        if json is not None and iv is None and payload is None and mac is None:
            ensure_frame_type(json, FrameType.ENCRYPTED)

            self.__json = json
            self.__data = self.json["data"]
            self.__iv = self.data["iv"]
            self.__payload = self.data["payload"]
            self.__mac = self.json["mac"]
        elif json is None and iv is not None and payload is not None and mac is not None:
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
        else:
            raise RuntimeError("Unable to instantiate EncryptedFrame based on the passed data.")

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
