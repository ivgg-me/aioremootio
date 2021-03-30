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
import json
from typing import NoReturn, Union
from async_class import AsyncClass
from aiohttp import WSMsgType, ClientWebSocketResponse
from .enums import ErrorType, FrameType
from .frames import ErrorFrame, ServerHelloFrame, EncryptedFrame, ActionResponseFrame, EventFrame, retrieve_frame_type
from .utils import ConnectionHolder, Listener, Decrypter
from .constants import \
    ARGUMENT_CONNECTION_HOLDER, \
    ARGUMENT_FRAME_LISTENER, \
    ARGUMENT_DECRYPTER, \
    ARGUMENT_HEARTBEAT, \
    ARGUMENT_LOGGER


class MessageHandler(AsyncClass):
    __connection_holder: ConnectionHolder
    __decrypter: Decrypter
    __frame_listener: Listener[Union[ActionResponseFrame, EventFrame, ErrorFrame, ServerHelloFrame]]
    __heartbeat: float
    __logger: logging.Logger

    async def __ainit__(self, *args, **kwargs) -> NoReturn:
        await super().__ainit__(*args, **kwargs)
        self.__connection_holder = kwargs[ARGUMENT_CONNECTION_HOLDER]
        self.__decrypter = kwargs[ARGUMENT_DECRYPTER]
        self.__frame_listener = kwargs[ARGUMENT_FRAME_LISTENER]
        self.__heartbeat = kwargs[ARGUMENT_HEARTBEAT]

        if ARGUMENT_LOGGER in kwargs:
            self.__logger = kwargs[ARGUMENT_LOGGER]
        else:
            self.__logger = logging.getLogger(__name__)

        self.create_task(self.__handle_messages)

    async def __handle_messages(self) -> NoReturn:
        try:
            while True:
                ws: ClientWebSocketResponse = await self.__connection_holder.open_connection()
                async for msg in ws:
                    try:
                        self.__logger.debug("Message received from device. Type [%s]", msg.type)

                        if msg.type == WSMsgType.TEXT:
                            frame: dict = msg.json()
                            self.__logger.debug(f"< {json.dumps(frame)}")

                            frame_type = retrieve_frame_type(frame)

                            if frame_type is None:
                                self.__logger.error("Failed to handle message. Unable to determine frame type.")
                            elif frame_type == FrameType.ERROR:
                                await self.__frame_listener.execute(ErrorFrame(ErrorType(frame["errorMessage"])))
                            elif frame_type == FrameType.PONG:
                                pass
                            elif frame_type == FrameType.SERVER_HELLO:
                                await self.__frame_listener.execute(ServerHelloFrame(frame))
                            elif frame_type == FrameType.ENCRYPTED:
                                await self.__handle_encrypted_frame(EncryptedFrame(frame))
                            else:
                                self.__logger.error(
                                    "Failed to handle message. Frame of type isn't supported. FrameType [%s]",
                                    frame_type
                                )
                        elif msg.type == WSMsgType.BINARY:
                            self.__logger.warning("Binary messages aren't supported.")
                        elif msg.type == WSMsgType.CLOSE:
                            self.__logger.info("Connection was closed.")
                            await self.__connection_holder.close_connection()
                        elif msg.type == WSMsgType.PING:
                            await ws.pong()
                        elif msg.type == WSMsgType.PONG:
                            pass
                        else:
                            pass
                    except BaseException:
                        self.__logger.exception("Failed to handle message.")
                else:
                    await asyncio.sleep(self.__heartbeat)
        except BaseException:
            self.__logger.exception("Error occurred during handling of messages.")
            raise

    async def __handle_encrypted_frame(self, frame: EncryptedFrame):
        decrypted_frame = await self.__decrypter.decrypt(frame)
        await self.__frame_listener.execute(decrypted_frame)
