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

from typing import NoReturn, TypeVar, Generic, TYPE_CHECKING
from abc import ABC, abstractmethod
if TYPE_CHECKING:
    from .remootioclient import RemootioClient

T = TypeVar('T')


class Listener(ABC, Generic[T]):
    """
    Abstract class for listener implementations which will be invoked by the client (``aioremootio.RemootioClient``).
    """

    @abstractmethod
    async def execute(self, client: 'RemootioClient', subject: T) -> NoReturn:
        """
        Method called by the client.
        :param client: the ``aioremootio.RemootioClient`` which has invoked this listener
        :param subject: the subject because of the ``aioremootio.RemootioClient`` has invoked the listener
        """
        pass
