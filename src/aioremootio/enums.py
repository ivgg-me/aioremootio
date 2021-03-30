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
    CLOSED = "closed"
    OPEN = "open"
    CLOSING = "closing"
    OPENING = "opening"
    NO_SENSOR_INSTALLED = "no sensor"
    UNKNOWN = "unknown"


class ErrorType(Enum):
    JSON_ERROR = "json error"
    INPUT_ERROR = "input error"
    INTERNAL_ERROR = "internal error"
    CONNECTION_TIMEOUT = "connection timeout"
    AUTHENTICATION_TIMEOUT = "authentication timeout"
    AUTHENTICATION_ERROR = "authentication error"
    ALREADY_AUTHENTICATED = "already authenticated"


class ActionType(Enum):
    QUERY = "QUERY"
    TRIGGER = "TRIGGER"
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class EventType(Enum):
    STATE_CHANGE = "StateChange"
    RELAY_TRIGGER = "RelayTrigger"
    LEFT_OPEN = "LeftOpen"


class KeyType(Enum):
    MASTER_KEY = "master key"
    UNIQUE_KEY = "unique key"
    GUEST_KEY = "guest key"
    API_KEY = "api key"
    SMART_HOME = "smart home"


class DeviceType(Enum):
    REMOOTIO_1 = "remootio-1"
    REMOOTIO_2 = "remootio-2"


class FrameType(Enum):
    ENCRYPTED = "ENCRYPTED"
    SERVER_HELLO = "SERVER_HELLO"
    PONG = "PONG"
    ERROR = "ERROR"
    CHALLENGE = "CHALLENGE"
