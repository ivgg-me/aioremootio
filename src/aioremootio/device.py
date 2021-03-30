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

import aiohttp
import logging
import json
from typing import Optional, NoReturn, Union
from asyncio import Task
from async_class import AsyncClass
from aiohttp import ClientWebSocketResponse
from base64 import b64encode, b64decode
from binascii import unhexlify
from Crypto.Hash import HMAC, SHA256
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from .enums import ActionType
from .models import ConnectionOptions
from .frames import \
    ActionRequestFrame, \
    EncryptedFrame, \
    ActionResponseFrame, \
    EventFrame, \
    ErrorFrame, \
    ServerHelloFrame, \
    HelloFrame, \
    ChallengeFrame, \
    AuthFrame, \
    AbstractFrame, \
    ensure_frame_type, \
    retrieve_frame_type, AbstractJSONHolderFrame
from .utils import Decrypter, Encrypter, ConnectionHolder, Listener, FrameSender
from .enums import State, FrameType
from .message_handler import MessageHandler
from .ping_sender import PingSender
from .constants import \
    ARGUMENT_CONNECTION_HOLDER, \
    ARGUMENT_FRAME_LISTENER, \
    ARGUMENT_FRAME_SENDER, \
    ARGUMENT_DECRYPTER, \
    ARGUMENT_HEARTBEAT, \
    ARGUMENT_LOGGER, \
    MESSAGE_HANDLER_HEARTBEAT, \
    PING_SENDER_HEARTBEAT, \
    CONNECTION_OPTION_KEY_IP_ADDRESS, \
    CONNECTION_OPTION_KEY_API_AUTH_KEY, \
    CONNECTION_OPTION_KEY_API_SECRET_KEY, \
    ENCODING


class Device(
    AsyncClass,
    Decrypter,
    Encrypter,
    ConnectionHolder,
    Listener[Union[ActionResponseFrame, EventFrame, ErrorFrame, ServerHelloFrame]],
    FrameSender
):
    """
    Class wich represents a Remootio device.
    """

    __connection_options: ConnectionOptions
    __client_session: aiohttp.ClientSession
    __logger: logging.Logger
    __state_listener: Optional[Listener[State]]
    __ws: Optional[aiohttp.ClientWebSocketResponse]
    __ip_address: str
    __api_version: Optional[int]
    __serial_number: Optional[str]
    __uptime: Optional[int]
    __state: State
    __session_key: Optional[str]
    __last_action_id: Optional[int]
    __message_handler: Optional[MessageHandler]
    __ping_sender: Optional[PingSender]
    __authentication_task: Optional[Task]

    def __init__(
            self,
            connection_options: Union[ConnectionOptions, dict],
            client_session: aiohttp.ClientSession,
            logger: Optional[logging.Logger] = None,
            state_listener: Optional[Listener[State]] = None
    ):
        """
        :param connection_options: The options using to connect to the device.
                                   If a dictionary it must contain the device's IP address with key as defined by
                                   the constant aioremootio.constants.CONNECTION_OPTION_KEY_IP_ADDRESS, the device's
                                   API Secret Key with key as defined by the constant
                                   aioremootio.constants.CONNECTION_OPTION_KEY_API_SECRET_KEY and the device's
                                   API Auth Key with key as defined by the constant
                                   aioremootio.constants.CONNECTION_OPTION_KEY_API_AUTH_KEY.
        :param client_session    : The aiohttp client session to be used by the device representation.
        :param logger            : The logger by the device representation.
        :param state_listener    : The state listener to be invoked if the state of the represented device changes.
        """
        super(Device, self).__init__()

        if type(connection_options) is dict:
            connection_option_keys = [
                CONNECTION_OPTION_KEY_IP_ADDRESS,
                CONNECTION_OPTION_KEY_API_SECRET_KEY,
                CONNECTION_OPTION_KEY_API_AUTH_KEY
            ]

            for connection_option_key in connection_option_keys:
                if connection_option_key not in connection_options:
                    raise ValueError(f"Option not defined: {connection_option_key}")

            connection_options = ConnectionOptions(
                connection_options[CONNECTION_OPTION_KEY_IP_ADDRESS],
                connection_options[CONNECTION_OPTION_KEY_API_SECRET_KEY],
                connection_options[CONNECTION_OPTION_KEY_API_AUTH_KEY]
            )

        if logger is None:
            logger = logging.getLogger(__name__)

        self.__connection_options = connection_options
        self.__client_session = client_session
        self.__logger = logger
        self.__state_listener = state_listener
        self.__ws = None
        self.__ip_address = self.__connection_options.ip_address
        self.__api_version = None
        self.__serial_number = None
        self.__uptime = None
        self.__state = State.UNKNOWN
        self.__session_key = None
        self.__last_action_id = None
        self.__message_handler = None
        self.__ping_sender = None
        self.__authentication_task = None

    async def __ainit__(self, *args, **kwargs) -> NoReturn:
        await super().__ainit__(*args, **kwargs)

        await self.initialize()

    async def __adel__(self) -> None:
        await super().__adel__()

        await self.terminate()

    async def initialize(self) -> NoReturn:
        """Initializes this device representation."""

        if self.__state_listener is not None:
            await self.__state_listener.execute(self.state)

        await self.open_connection()

        self.__message_handler = await MessageHandler(**{
            ARGUMENT_CONNECTION_HOLDER: self,
            ARGUMENT_DECRYPTER: self,
            ARGUMENT_FRAME_LISTENER: self,
            ARGUMENT_HEARTBEAT: MESSAGE_HANDLER_HEARTBEAT,
            ARGUMENT_LOGGER: self.__logger
        })

        self.__ping_sender = await PingSender(**{
            ARGUMENT_FRAME_SENDER: self,
            ARGUMENT_HEARTBEAT: PING_SENDER_HEARTBEAT,
            ARGUMENT_LOGGER: self.__logger
        })

        await self.send(HelloFrame())

    async def terminate(self) -> NoReturn:
        """Terminates this device representation."""

        if self.__message_handler is not None:
            await self.__message_handler.close()

        if self.__ping_sender is not None:
            await self.__ping_sender.close()

        await self.close_connection()

    async def open_connection(self) -> ClientWebSocketResponse:
        if not self.connected() or not self.authenticated():
            if self.connected():
                await self.close_connection()

            # Establishing connection
            try:
                self.__ws = await self.__client_session.ws_connect(f"ws://{self.__connection_options.ip_address}:8080/")
                self.__logger.info("Client has been connected to the device.")
            except:
                self.__logger.exception("Client is unable to establish connection to the device.")
                self.__ws = None

            # Authenticating
            if self.connected() and not self.authenticated():
                authentication_result: tuple = await self.__authenticate(self.__ws)

                self.__session_key = authentication_result[0]
                self.__last_action_id = authentication_result[1]

        return self.__ws

    async def close_connection(self) -> NoReturn:
        self.__session_key = None
        self.__last_action_id = None

        if self.__ws is not None:
            if not self.__ws.closed:
                await self.__ws.close()

            self.__ws = None

    def get_connection(self) -> ClientWebSocketResponse:
        return self.__ws

    def connected(self) -> bool:
        return self.__ws is not None and not self.__ws.closed

    def authenticated(self) -> bool:
        return self.__session_key is not None and self.__last_action_id is not None

    async def __authenticate(self, ws: ClientWebSocketResponse) -> tuple:
        session_key: Optional[str] = None
        action_id: Optional[int] = None

        await self.__send(AuthFrame(), ws)

        frame: [dict, AbstractFrame] = await ws.receive_json(timeout=30)
        ensure_frame_type(frame, FrameType.ENCRYPTED)

        frame = await self.decrypt(EncryptedFrame(frame))
        if isinstance(frame, ChallengeFrame):
            session_key = frame.session_key
            action_id = frame.initial_action_id
        else:
            raise RemootioClientError(self, "Received frame isn't the expected.")

        frame = await self.__encrypt(
            ActionRequestFrame(self.__calculate_next_action_id(action_id), ActionType.QUERY), b64decode(session_key))
        await self.__send(frame, ws)

        action_id = action_id + 1

        frame: [dict, AbstractFrame] = await ws.receive_json(timeout=30)
        ensure_frame_type(frame, FrameType.ENCRYPTED)

        frame = self.__decrypt(EncryptedFrame(frame), b64decode(session_key))

        if isinstance(frame, ActionResponseFrame):
            if frame.action_type != ActionType.QUERY:
                raise RemootioClientError(self, "Received frame isn't the expected.")

            self.__state = frame.state
            self.__uptime = frame.uptime

            if self.__state_listener is not None:
                await self.__state_listener.execute(self.state)
        else:
            raise RemootioClientError(self, "Received frame isn't the expected.")

        return session_key, action_id

    def __calculate_next_action_id(self, last_action_id) -> int:
        return (last_action_id + 1) % 0x7FFFFFFF

    async def decrypt(self, frame: EncryptedFrame) -> Union[ActionResponseFrame, EventFrame, ChallengeFrame]:
        return await self.__decrypt(frame, self.__retrieve_session_key())

    async def __decrypt(self, frame: EncryptedFrame, session_key: bytes) -> Union[ActionResponseFrame, EventFrame, ChallengeFrame]:
        result: Optional[Union[ActionResponseFrame, EventFrame, ChallengeFrame]] = None

        data: bytes = json.dumps(frame.data).encode(ENCODING)
        payload_bytes: bytes = b64decode(frame.payload)
        iv: bytes = b64decode(frame.iv)
        mac: bytes = b64decode(frame.mac)
        api_auth_key: bytes = bytes.fromhex(self.__connection_options.api_auth_key)

        # Verify mac
        calculated_mac = HMAC.new(key=api_auth_key, msg=data, digestmod=SHA256).digest()
        if frame.mac != b64encode(calculated_mac).decode(ENCODING):
            raise RemootioClientDecryptionError(
                self, "Frame can't be decrypted because mac verification was failed.")

        # Decrypt frame
        payload_bytes = unpad(AES.new(key=session_key, mode=AES.MODE_CBC, iv=iv).decrypt(payload_bytes), AES.block_size)
        payload_json: dict = json.loads(payload_bytes.decode(ENCODING))

        if "response" in payload_json:
            result = ActionResponseFrame(payload_json)
        elif "event" in payload_json:
            result = EventFrame(payload_json)
        elif retrieve_frame_type(payload_json) == FrameType.CHALLENGE:
            result = ChallengeFrame(payload_json)
        else:
            self.__logger.error("Frame can't be decrypted because encrypted payload can't be parsed.")
            raise RemootioClientDecryptionError(
                self, "Frame can't be decrypted because encrypted payload can't be parsed.")

        return result

    async def encrypt(self, frame: ActionRequestFrame) -> EncryptedFrame:
        return await self.__encrypt(frame, self.__retrieve_session_key())

    async def __encrypt(self, frame: ActionRequestFrame, session_key: bytes) -> EncryptedFrame:
        result: Optional[EncryptedFrame] = None

        api_auth_key: bytes = bytes.fromhex(self.__connection_options.api_auth_key)

        # Encrypt frame
        cipher: AES = AES.new(key=session_key, mode=AES.MODE_CBC)

        payload_bytes: bytes = json.dumps(frame.json).encode(ENCODING)
        payload_bytes = cipher.encrypt(pad(payload_bytes, AES.block_size))

        data: dict = {
            "payload": b64encode(payload_bytes).decode(ENCODING),
            "iv": b64encode(cipher.iv).decode(ENCODING)
        }
        data_bytes: bytes = json.dumps(data).encode(ENCODING)

        # Create mac
        mac_bytes: bytes = HMAC.new(api_auth_key, data_bytes, SHA256).digest()

        # Create encrypted frame
        result = EncryptedFrame({
            "data": data,
            "mac": b64encode(mac_bytes).decode(ENCODING)
        })

        return result

    def __retrieve_session_key(self) -> bytes:
        result = bytes.fromhex(self.__connection_options.api_secret_key)
        if self.__session_key is not None:
            result = b64decode(self.__session_key)

        return result

    async def execute(self, subject: Union[ActionResponseFrame, EventFrame, ErrorFrame, ServerHelloFrame]) -> NoReturn:
        if isinstance(subject, ServerHelloFrame):
            self.__api_version = subject.api_version
            self.__serial_number = subject.serial_number

        # TODO
        pass

    async def send(self, frame: AbstractJSONHolderFrame) -> NoReturn:
        ws: ClientWebSocketResponse = await self.open_connection()
        await self.__send(frame, ws)

    async def __send(self, frame: AbstractJSONHolderFrame, ws: ClientWebSocketResponse) -> NoReturn:
        await ws.send_json(frame.json)

    async def trigger(self) -> NoReturn:
        # TODO
        pass

    async def trigger_open(self) -> NoReturn:
        # TODO
        pass

    async def trigger_close(self) -> NoReturn:
        # TODO
        pass

    @property
    def ip_address(self) -> str:
        return self.__ip_address

    @property
    def api_version(self) -> Optional[int]:
        return self.__api_version

    @property
    def serial_number(self) -> Optional[str]:
        return self.__serial_number

    @property
    def uptime(self) -> Optional[int]:
        return self.__uptime

    @property
    def state(self) -> State:
        return self.__state


class RemootioError(Exception):
    """Base class for aioremootio errors."""

    def __init__(self, device: Device, message: str) -> None:
        super().__init__(message)
        self.__message = message
        self.__device = device

    @property
    def message(self):
        return self.__message

    @property
    def remootio_device(self) -> Device:
        return self.__device


class RemootioClientError(RemootioError):

    def __init__(self, device: Device, message: str) -> None:
        super().__init__(device, message)


class RemootioClientDecryptionError(RemootioClientError):

    def __init__(self, device: Device, message: str) -> None:
        super().__init__(device, message)


class RemootioClientEncryptionError(RemootioClientError):

    def __init__(self, device: Device, message: str) -> None:
        super().__init__(device, message)
