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

from dataclasses import dataclass
from typing import Optional
from logging import Logger
from .enums import KeyType, EventType, EventSource, State


@dataclass(frozen=True)
class ConnectionOptions:
    """
    Connection options to be used by the client (``aioremootio.RemootioClient``) to connect to the device.

    The API Secret Key (``api_secret_key``) and the API Auth Key (``api_auth_key``) are needed to authenticate the
    client by the device. To get this information for the device, you must enable the API on the device. For more
    information please consult the Remootio Websocket API documentation at
    https://github.com/remootio/remootio-api-documentation.
    """

    ip_address: str
    api_secret_key: str
    api_auth_key: str


@dataclass(frozen=True)
class Key:
    """
    Holds additional information to an ``aioremootio.models.Event`` about the key which has operated the device.

    ``key_type`` is the kind of the key. ``key_number`` is the number of the key which can be found in the Remootio app.
    """

    key_type: KeyType
    key_number: int


class LoggerConfiguration:
    """
    Logger configuration to be used by the client (``aioremootio.RemootioClient``).

    Either ``logger`` or ``level`` can be set. For more information please consult the documentation of the client
    (``aioremootio.RemootioClient``).
    """

    logger: Optional[Logger]
    level: Optional[int]

    def __init__(self, logger: Optional[Logger] = None, level: Optional[int] = None):
        self.logger = logger
        self.level = level


@dataclass(frozen=True)
class Event:
    """
    Passed as subject to the event listener during invocation of it through the client (``aioremootio.RemootioClient``).

    It contains information about the connection method was used to trigger the event (``source``) the kind of the
    event (``type``) and optionally information about the key which has operated the device (``key``).
    """

    source: EventSource
    type: EventType
    key: Optional[Key]


@dataclass(frozen=True)
class StateChange:
    """
    Passed as subject to the state change listener during invocation of it through the client (
    ``aioremootio.RemootioClient``).

    It contains information about the state of the device before (``old_state``) and after (``new_state``) the state
    change.
    """

    old_state: Optional[State]
    new_state: State
