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

from enum import Enum


class State(Enum):
    """
    Enumeration of possible states of the client (``aioremootio.RemootioClient``).
    """

    CLOSED = "closed"
    OPEN = "open"
    CLOSING = "closing"
    OPENING = "opening"
    NO_SENSOR_INSTALLED = "no sensor"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value):
        return State.UNKNOWN


class ErrorType(Enum):
    JSON_ERROR = "json error"
    INPUT_ERROR = "input error"
    INTERNAL_ERROR = "internal error"
    CONNECTION_TIMEOUT = "connection timeout"
    AUTHENTICATION_TIMEOUT = "authentication timeout"
    AUTHENTICATION_ERROR = "authentication error"
    ALREADY_AUTHENTICATED = "already authenticated"
    UNKNOWN = "unknown error"

    @classmethod
    def _missing_(cls, value):
        return ErrorType.UNKNOWN


class ActionType(Enum):
    QUERY = "QUERY"
    TRIGGER = "TRIGGER"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    UNSUPPORTED = "UNSUPPORTED"

    @classmethod
    def _missing_(cls, value):
        return ActionType.UNSUPPORTED


class EventType(Enum):
    """
    Enumeration of possible kinds of event. For more information see ``aioremootio.models.Event``.
    """

    STATE_CHANGE = "StateChange"
    RELAY_TRIGGER = "RelayTrigger"
    LEFT_OPEN = "LeftOpen"
    UNSUPPORTED = "Unsupported"

    @classmethod
    def _missing_(cls, value):
        return EventType.UNSUPPORTED


class KeyType(Enum):
    """
    Enumeration of possible kinds of keys. For more information see ``aioremootio.models.Key``.
    """

    MASTER_KEY = "master key"
    UNIQUE_KEY = "unique key"
    GUEST_KEY = "guest key"
    API_KEY = "api key"
    SMART_HOME = "smart home"
    AUTOMATION = "automation"
    UNSUPPORTED = "Unsupported"

    @classmethod
    def _missing_(cls, value):
        return KeyType.UNSUPPORTED


class DeviceType(Enum):
    REMOOTIO_1 = "remootio-1"
    REMOOTIO_2 = "remootio-2"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value):
        return DeviceType.UNKNOWN


class FrameType(Enum):
    ENCRYPTED = "ENCRYPTED"
    SERVER_HELLO = "SERVER_HELLO"
    PONG = "PONG"
    ERROR = "ERROR"
    CHALLENGE = "CHALLENGE"


class ErrorCode(Enum):
    RELAY_BUSY = "ERR_RELAY_BUSY"
    INVALID_REQUEST = "ERR_INVALID_REQUEST"
    NO_SENSOR = "ERR_NO_SENSOR"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value):
        return ErrorCode.UNKNOWN


class EventSource(Enum):
    """
    Enumeration of possible connection methods which can be used to trigger an event. For more information see
    ``aioremootio.models.Event``.
    """

    BLUETOOTH = "bluetooth"
    WIFI = "wifi"
    INTERNET = "internet"
    AUTOOPEN = "autoopen"
    UNKNOWN = "unknown"
    NONE = "none"

    @classmethod
    def _missing_(cls, value):
        return EventSource.UNKNOWN
