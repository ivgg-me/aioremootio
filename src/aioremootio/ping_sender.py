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

import logging
import asyncio
from async_class import AsyncClass
from typing import NoReturn
from .utils import FrameSender
from .frames import PingFrame
from .constants import \
    ARGUMENT_FRAME_SENDER, \
    ARGUMENT_HEARTBEAT, \
    ARGUMENT_LOGGER


class PingSender(AsyncClass):
    __frame_sender: FrameSender
    __heartbeat: float
    __logger: logging.Logger

    async def __ainit__(self, *args, **kwargs) -> NoReturn:
        await super().__ainit__(*args, **kwargs)
        self.__frame_sender = kwargs[ARGUMENT_FRAME_SENDER]
        self.__heartbeat = kwargs[ARGUMENT_HEARTBEAT]

        if ARGUMENT_LOGGER in kwargs:
            self.__logger = kwargs[ARGUMENT_LOGGER]
        else:
            self.__logger = logging.getLogger(__name__)

        self.create_task(self.__send_pings)

    async def __send_pings(self) -> NoReturn:
        try:
            while True:
                await self.__frame_sender.send(PingFrame())
                await asyncio.sleep(self.__heartbeat)
        except BaseException:
            self.__logger.exception("Error occurred during sending pings.")
            raise
