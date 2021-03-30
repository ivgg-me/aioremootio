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
from typing import NoReturn, Generic, TypeVar, Union
from aiohttp import ClientWebSocketResponse
from .frames import EncryptedFrame, ActionRequestFrame, ActionResponseFrame, EventFrame, AbstractJSONHolderFrame

T = TypeVar('T')


class ConnectionHolder(ABC):

    @abstractmethod
    async def open_connection(self) -> ClientWebSocketResponse:
        pass

    @abstractmethod
    async def close_connection(self) -> NoReturn:
        pass

    @abstractmethod
    def get_connection(self) -> ClientWebSocketResponse:
        pass

    @abstractmethod
    def connected(self) -> bool:
        pass

    @abstractmethod
    def authenticated(self) -> bool:
        pass


class Listener(ABC, Generic[T]):

    @abstractmethod
    async def execute(self, subject: T) -> NoReturn:
        pass


class Decrypter(ABC):

    @abstractmethod
    async def decrypt(self, frame: EncryptedFrame) -> Union[ActionResponseFrame, EventFrame]:
        pass


class Encrypter(ABC):

    @abstractmethod
    async def encrypt(self, frame: ActionRequestFrame) -> EncryptedFrame:
        pass


class FrameSender(ABC):

    @abstractmethod
    async def send(self, frame: AbstractJSONHolderFrame) -> NoReturn:
        pass