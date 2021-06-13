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

from typing import NoReturn, TYPE_CHECKING
if TYPE_CHECKING:
    from .remootioclient import RemootioClient


class RemootioError(Exception):
    """Base class for aioremootio errors."""

    def __init__(self, device: 'RemootioClient', message: str) -> NoReturn:
        super().__init__(message)
        self.__message = message
        self.__device = device

    @property
    def message(self):
        return self.__message

    @property
    def remootio_device(self) -> 'RemootioClient':
        return self.__device


class RemootioClientError(RemootioError):

    def __init__(self, device: 'RemootioClient', message: str) -> NoReturn:
        super().__init__(device, message)


class RemootioClientConnectionEstablishmentError(RemootioClientError):

    def __init__(self, device: 'RemootioClient', message: str) -> NoReturn:
        super().__init__(device, message)


class RemootioClientAuthenticationError(RemootioClientError):

    def __init__(self, device: 'RemootioClient', message: str) -> NoReturn:
        super().__init__(device, message)


class RemootioClientDecryptionError(RemootioClientError):

    def __init__(self, device: 'RemootioClient', message: str) -> NoReturn:
        super().__init__(device, message)


class RemootioClientEncryptionError(RemootioClientError):

    def __init__(self, device: 'RemootioClient', message: str) -> NoReturn:
        super().__init__(device, message)


class RemootioClientUnsupportedOperationError(RemootioError):

    def __init__(self, device: 'RemootioClient', message: str) -> NoReturn:
        super().__init__(device, message)
