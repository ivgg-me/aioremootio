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

from typing import NoReturn, TYPE_CHECKING, List
from voluptuous import Invalid, MultipleInvalid
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
        return self.__message if self.__message is not None else "Unknown error."

    @property
    def remootio_device(self) -> 'RemootioClient':
        return self.__device

    def __repr__(self) -> str:
        return "%s{remootio_device:%s,message:%s}" % (
            self.__class__.__name__,
            repr(self.remootio_device) if self.remootio_device is not None else "N/A",
            self.message
        )

    def __str__(self) -> str:
        return "%s %s" % (
            self.message,
            str(self.remootio_device) if self.remootio_device is not None else "N/A"
        )


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


class RemootioClientUnsupportedOperationError(RemootioClientError):

    def __init__(self, device: 'RemootioClient', message: str) -> NoReturn:
        super().__init__(device, message)


class RemootioClientInvalidConfigurationError(RemootioClientError):
    def __init__(self, device: 'RemootioClient', details: Invalid) -> NoReturn:
        super().__init__(device, "Configuration appears to be invalid.")
        self.__details = details

    @property
    def details(self) -> Invalid:
        return self.__details

    def __details_to_str(self) -> str:
        result: str = "N/A"

        if self.details is not None:
            result = self.__multiple_invalid_to_str(self.details) \
                if isinstance(self.details, MultipleInvalid) else str(self.details)

        return result

    def __multiple_invalid_to_str(self, i: MultipleInvalid) -> str:
        result: str = ""

        for error in i.errors:
            if isinstance(error, MultipleInvalid):
                result = f"{result} {self.__multiple_invalid_to_str(error)}"
            else:
                result = f"{result} {str(error)}"

        return result

    def __repr__(self) -> str:
        return "%s{remootio_device:%s,message:%s,details:%s}" % (
            self.__class__.__name__,
            repr(self.remootio_device) if self.remootio_device is not None else "N/A",
            self.message,
            repr(self.details) if self.details is not None else "N/A"
        )

    def __str__(self) -> str:
        return "%s %s Details [%s]" % (
            self.message,
            str(self.remootio_device) if self.remootio_device is not None else "N/A",
            self.__details_to_str()
        )