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
import asyncio

import aiohttp
import logging
import json
from typing import Optional, NoReturn, Union
from async_class import AsyncClass
from aiohttp import ClientWebSocketResponse, WSMsgType
from base64 import b64encode, b64decode
from asyncio.exceptions import CancelledError
from Crypto.Hash import HMAC, SHA256
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes
from .listeners import Listener
from .errors import \
    RemootioError, \
    RemootioClientError, \
    RemootioClientConnectionEstablishmentError, \
    RemootioClientAuthenticationError, \
    RemootioClientDecryptionError, \
    RemootioClientEncryptionError, \
    RemootioClientUnsupportedOperationError
from .models import ConnectionOptions, LoggerConfiguration, Event, StateChange
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
    retrieve_frame_type, AbstractJSONHolderFrame, PingFrame
from .enums import State, FrameType, ActionType, EventType, ErrorCode
from .constants import \
    MESSAGE_HANDLER_HEARTBEAT, \
    PING_SENDER_HEARTBEAT, \
    CONNECTION_OPTION_KEY_IP_ADDRESS, \
    CONNECTION_OPTION_KEY_API_AUTH_KEY, \
    CONNECTION_OPTION_KEY_API_SECRET_KEY, \
    ENCODING


class RemootioClient(AsyncClass):
    """
    Class wich represents an Websocket API client of an Remootio device.
    """

    __connection_options: ConnectionOptions
    __client_session: aiohttp.ClientSession
    __logger: logging.Logger
    __state_change_listener: Optional[Listener[StateChange]]
    __event_listener: Optional[Listener[Event]]
    __ws: Optional[aiohttp.ClientWebSocketResponse]
    __ip_address: str
    __api_version: Optional[int]
    __serial_number: Optional[str]
    __uptime: Optional[int]
    __state: State
    __session_key: Optional[str]
    __last_action_id: Optional[int]
    __authenticated: bool
    __terminating: bool

    def __init__(
            self,
            connection_options: Union[ConnectionOptions, dict],
            client_session: aiohttp.ClientSession,
            logger_configuration: Optional[LoggerConfiguration] = None,
            state_change_listener: Optional[Listener[StateChange]] = None,
            event_listener: Optional[Listener[Event]] = None
    ):
        """
        :param connection_options   : The options using to connect to the device.
                                      If a dictionary it must contain the device's
                                      IP address with key as defined by the constant
                                      ``aioremootio.constants.CONNECTION_OPTION_KEY_IP_ADDRESS``,
                                      the device's API Secret Key with key as defined by the constant
                                      ``aioremootio.constants.CONNECTION_OPTION_KEY_API_SECRET_KEY`` and
                                      the device's API Auth Key with key as defined by the constant
                                      ``aioremootio.constants.CONNECTION_OPTION_KEY_API_AUTH_KEY``.
                                      To get the API Secret Key and API Auth Key for the device, you must enable
                                      the API on the device. For more information please consult the Remootio
                                      Websocket API documentation at
                                      https://github.com/remootio/remootio-api-documentation.
        :param client_session       : The aiohttp client session to be used by the client.
        :param logger_configuration : The logger configuration to be used by the client.
                                      If ``aioremootio.models.LoggerConfiguration.logger`` is set then this logger
                                      will be used, otherwise an logger instance will by instantiated and used.
                                      If ``aioremootio.models.LoggerConfiguration.level`` is set then this level
                                      will be used by the internally instantiated logger.
        :param state_change_listener: An ``aioremootio.listeners.Listener[aioremootio.models.StateChange]`` to be
                                      invoked if the state of the device changes.
        :param event_listener       : An ``aioremootio.listeners.Listener[aioremootio.models.Event]`` to be invoked if
                                      an event occurs on the device.
        """
        super(RemootioClient, self).__init__()

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

        logger: Optional[logging.Logger] = None
        if logger_configuration is not None:
            if logger_configuration.logger is None:
                logger = logging.getLogger(__name__)

                handler: logging.Handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s"))
                logger.addHandler(handler)

                if logger_configuration.level is not None:
                    logger.setLevel(logger_configuration.level)
                else:
                    logger.setLevel(logging.INFO)
            else:
                logger = logger_configuration.logger
        else:
            logger = logging.getLogger(__name__)

            handler: logging.Handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(handler)

        self.__connection_options = connection_options
        self.__client_session = client_session
        self.__logger = logger
        self.__state_change_listener = state_change_listener
        self.__event_listener = event_listener
        self.__ws = None
        self.__ip_address = self.__connection_options.ip_address
        self.__api_version = None
        self.__serial_number = None
        self.__uptime = None
        self.__state = State.UNKNOWN
        self.__session_key = None
        self.__last_action_id = None
        self.__authenticated = False
        self.__terminating = False

    async def __ainit__(self, *args, **kwargs) -> NoReturn:
        await super().__ainit__(*args, **kwargs)

        await self.__initialize()

    async def __adel__(self) -> None:
        self.__terminating = True

        try:
            await self.__terminate()

            await super().__adel__()
        finally:
            self.__terminating = False

    async def __initialize(self) -> NoReturn:
        self.__logger.info("Initializing this client...")

        try:
            await self.__invoke_state_listener(StateChange(None, self.state))

            await self.__open_connection(handle_connection_error=False)

            if self.connected and self.authenticated:
                self.create_task(self.__receive_and_handle_messages())

                self.create_task(self.__send_pings())

                await self.__send_frame(HelloFrame())
        except BaseException as ex:
            self.__logger.exception("Failed to initialize this client.")
            raise RemootioClientError(self, "Failed to initialize this client.") from ex

    async def __terminate(self) -> NoReturn:
        self.__logger.info("Terminating this client...")

        await self.__close_connection()

    async def __open_connection(self, handle_connection_error: bool = True) -> ClientWebSocketResponse:
        if not self.connected or not self.authenticated:
            if self.connected and not self.authenticated:
                self.__logger.warning(
                    "Living connection to the device will be closed now, because this client isn't authenticated by "
                    "the device.")
                await self.__close_connection()

            # Establishing connection
            self.__logger.info("Establishing connection to the device...")
            try:
                self.__ws = await self.__client_session.ws_connect(f"ws://{self.__connection_options.ip_address}:8080/")
                self.__logger.info("Connection to the device has been established successfully.")
            except BaseException as ex:
                self.__ws = None
                if handle_connection_error:
                    self.__logger.exception("Unable to establish connection to the device.")
                else:
                    raise RemootioClientConnectionEstablishmentError(
                        self, "Unable to establish connection to the device.") from ex

            # Authenticating
            if self.connected and not self.authenticated:
                await self.__authenticate(self.__ws)

        return self.__ws

    async def __close_connection(self) -> NoReturn:
        try:
            if self.connected:
                self.__logger.info("Closing connection to the device...")
                await self.__ws.close()
        except:
            self.__logger.exception("Unable to close connection to the device because of an error.")

        self.__session_key = None
        self.__last_action_id = None
        self.__authenticated = False
        self.__ws = None

    async def __authenticate(self, ws: ClientWebSocketResponse) -> NoReturn:
        self.__logger.info("Authenticating this client by the device...")

        try:
            await self.__send_frame(AuthFrame(), ws)

            frame: [dict, AbstractFrame] = await ws.receive_json(timeout=30)
            ensure_frame_type(frame, FrameType.ENCRYPTED)

            frame = await self.__decrypt_frame(EncryptedFrame(json=frame))
            if isinstance(frame, ChallengeFrame):
                self.__session_key = frame.session_key
                self.__last_action_id = frame.initial_action_id
            else:
                raise RemootioClientError(self, "Received frame isn't the expected.")

            await self.__encrypt_and_send_frame(
                ActionRequestFrame(self.__calculate_next_action_id(), ActionType.QUERY), ws)

            frame: [dict, AbstractFrame] = await ws.receive_json(timeout=30)
            frame_type: FrameType = retrieve_frame_type(frame)
            if frame_type == FrameType.ERROR:
                frame = ErrorFrame(json=frame)
                raise RemootioClientAuthenticationError(
                    self, "An error has been occurred on the device during the authentication. Error [%s]" %
                          frame.error_type)
            elif frame_type == FrameType.ENCRYPTED:
                frame = EncryptedFrame(json=frame)
            else:
                raise RemootioClientError(self, "Unsupported frame was received.")

            frame = await self.__decrypt_frame(frame)

            if isinstance(frame, ActionResponseFrame):
                if frame.action_type != ActionType.QUERY:
                    raise RemootioClientError(self, "Received frame isn't the expected.")

                await self.__handle_action_response_frame(frame)
            else:
                raise RemootioClientError(self, "Received frame isn't the expected.")

            self.__authenticated = True
        except RemootioClientAuthenticationError as ex:
            self.__logger.exception(ex.message)
            self.__session_key = None
            self.__last_action_id = None
            raise ex
        except BaseException as ex:
            self.__logger.exception("Unable to authenticate this client by the device because of an error.")
            self.__session_key = None
            self.__last_action_id = None
            raise RemootioClientAuthenticationError(
                self, "Unable to authenticate this client by the device because of an error.") from ex

    async def __send_frame(self, frame: AbstractJSONHolderFrame, ws: Optional[ClientWebSocketResponse] = None) -> NoReturn:
        if ws is None:
            ws = await self.__open_connection()

        if self.__logger.getEffectiveLevel() == logging.DEBUG:
            self.__logger.debug("Sending frame... Frame [%s]", json.dumps(frame.json))
        else:
            self.__logger.info("Sending frame...")

        try:
            await ws.send_json(frame.json)
        except BaseException as ex:
            if self.__logger.getEffectiveLevel() == logging.DEBUG:
                self.__logger.warning("Sending of frame has been failed.", exc_info=True)
            else:
                self.__logger.warning("Sending of frame has been failed.")

            raise RemootioClientError(self, "Sending of frame has been failed.") from ex

    async def __encrypt_and_send_frame(
            self, frame: ActionRequestFrame, ws: Optional[ClientWebSocketResponse] = None) -> NoReturn:
        self.__logger.info("Encrypting and sending ActionRequestFrame... ActionType [%s]", frame.action_type)

        encrypted_frame: EncryptedFrame = await self.__encrypt_frame(frame);
        await self.__send_frame(encrypted_frame, ws)

    async def __send_pings(self) -> NoReturn:
        try:
            while True:
                if not self.__terminating:
                    ws: ClientWebSocketResponse = await self.__open_connection()

                    if ws is not None:
                        try:
                            await self.__send_frame(PingFrame(), ws)
                        except:
                            self.__logger.warning("Failed to send PING.")
                    else:
                        self.__logger.warning("Sending PINGs by this client will be delayed "
                                              "because connection to the device can't be established.")

                    await asyncio.sleep(PING_SENDER_HEARTBEAT)
                else:
                    self.__logger.warning("Sending PINGs by this client will be now stopped because it is about to "
                                          "be terminated.")
                    return
        except CancelledError:
            self.__logger.info("Sending PINGs by this client will be now stopped because of cancelling the task.")
        except:
            self.__logger.exception("Sending PINGs by this client will be now stopped because of an error.")
            raise

    async def __receive_and_handle_messages(self) -> NoReturn:
        try:
            while True:
                if not self.__terminating:
                    ws: ClientWebSocketResponse = await self.__open_connection()

                    if ws is not None:
                        async for msg in ws:
                            try:
                                self.__logger.debug("Message received from device. Type [%s]", msg.type)

                                if msg.type == WSMsgType.TEXT:
                                    msg_json: dict = msg.json()
                                    self.__logger.debug(f"< {json.dumps(msg_json)}")

                                    frame_type = retrieve_frame_type(msg_json)

                                    if frame_type is None:
                                        self.__logger.error("Failed to handle message. Unable to determine frame type.")
                                    elif frame_type == FrameType.ERROR:
                                        await self.__handle_error_frame(ErrorFrame(json=msg_json))
                                    elif frame_type == FrameType.PONG:
                                        pass
                                    elif frame_type == FrameType.SERVER_HELLO:
                                        await self.__handle_server_hello_frame(ServerHelloFrame(msg_json))
                                    elif frame_type == FrameType.ENCRYPTED:
                                        await self.__handle_encrypted_frame(EncryptedFrame(msg_json))
                                    else:
                                        self.__logger.error(
                                            "Failed to handle message. Frame of type isn't supported. FrameType [%s]",
                                            frame_type
                                        )
                                elif msg.type == WSMsgType.BINARY:
                                    self.__logger.warning("Binary messages aren't supported.")
                                elif msg.type == WSMsgType.CLOSE:
                                    self.__logger.info("Connection was closed by the device.")
                                    await self.__handle_connection_closed()
                                elif msg.type == WSMsgType.PING:
                                    await ws.pong()
                                elif msg.type == WSMsgType.PONG:
                                    pass
                                else:
                                    pass
                            except:
                                self.__logger.error("Failed to handle received message.")
                        else:
                            await asyncio.sleep(MESSAGE_HANDLER_HEARTBEAT)
                    else:
                        self.__logger.warning("Receiving and handling of messages by this client will be delayed "
                                              "because connection to the device can't be established.")
                        await asyncio.sleep(MESSAGE_HANDLER_HEARTBEAT)
                else:
                    self.__logger.warning("Receiving and handling of messages by this client will be now stopped "
                                          "because it is about to be terminated.")
                    return
        except CancelledError:
            self.__logger.info("Receiving and handling of messages by this client will be now stopped "
                               "because of cancelling the task.")
        except BaseException:
            self.__logger.exception("Receiving and handling of messages by this client will be now stopped"
                                    "because of an error.")
            raise

    async def __handle_error_frame(self, frame: ErrorFrame) -> NoReturn:
        self.__logger.debug("Handling received ErrorFrame...")
        self.__logger.error("An error has been occurred on the device. Type [%s]" % frame.error_type)

    async def __handle_server_hello_frame(self, frame: ServerHelloFrame) -> NoReturn:
        self.__logger.debug("Handling received ServerHelloFrame...")
        self.__api_version = frame.api_version
        self.__serial_number = frame.serial_number

    async def __handle_encrypted_frame(self, frame: EncryptedFrame) -> NoReturn:
        self.__logger.debug("Handling received EncryptedFrame...")
        decrypted_frame: Union[ActionResponseFrame, EventFrame, ChallengeFrame] = await self.__decrypt_frame(frame)

        if isinstance(decrypted_frame, ActionResponseFrame):
            await self.__handle_action_response_frame(decrypted_frame)
        elif isinstance(decrypted_frame, EventFrame):
            await self.__handle_event_frame(decrypted_frame)
        elif isinstance(decrypted_frame, ChallengeFrame):
            self.__logger.warning("Unexpected ChallengeFrame was received.")

    async def __handle_action_response_frame(self, frame: ActionResponseFrame) -> NoReturn:
        self.__logger.debug("Handling received ActionResponseFrame... ActionType [%s]" % frame.action_type)

        self.__uptime = frame.uptime
        self.__update_last_action_id(frame.action_id)

        if frame.action_type != ActionType.UNSUPPORTED:
            if frame.success:
                if frame.relay_triggered:
                    self.__logger.info(
                        "The device has taken an action. "
                        "ActionId [%s] ActionType [%s] State [%s] RelayTriggered [%s]" %
                        (frame.action_id, frame.action_type, frame.state, frame.relay_triggered))
                else:
                    self.__logger.info(
                        "The device has taken an action but the relay wasn't triggered. "
                        "ActionId [%s] ActionType [%s] State [%s] RelayTriggered [%s]" %
                        (frame.action_id, frame.action_type, frame.state, frame.relay_triggered))

                new_state: State = frame.state

                await self.__change_state(new_state)

                if frame.action_type == ActionType.OPEN and frame.relay_triggered:
                    await self.__change_state(State.OPENING)
                elif frame.action_type == ActionType.CLOSE and frame.relay_triggered:
                    await self.__change_state(State.CLOSING)
            else:
                if frame.error_code != ErrorCode.UNKNOWN:
                    self.__logger.warning(
                        "The device has taken an action which has been failed. "
                        "ActionId [%s] ActionType [%s] ErrorCode [%s] RelayTriggered [%s]" %
                        (frame.action_id, frame.action_type, frame.error_code, frame.relay_triggered))
                else:
                    self.__logger.error(
                        "The device has taken an action which has been failed. "
                        "ActionId [%s] ActionType [%s] ErrorCode [%s] RelayTriggered [%s]" %
                        (frame.action_id, frame.action_type, frame.error_code, frame.relay_triggered))
        else:
            self.__logger.debug(
                "The device has taken an unsupported action. "
                "ActionId [%s] State [%s] RelayTriggered [%s]" %
                (frame.action_id, frame.state, frame.relay_triggered))

    async def __handle_event_frame(self, frame: EventFrame) -> NoReturn:
        self.__logger.debug("Handling received EventFrame... EventType [%s]" % frame.event_type)

        if frame.event_type != EventType.UNSUPPORTED:
            self.__logger.info(
                "An event has been occurred on the device. EventType [%s] Key [%s] EventSource [%s]" %
                (frame.event_type, frame.key, frame.event_source))

            self.__uptime = frame.uptime

            if frame.event_type == EventType.STATE_CHANGE:
                await self.__change_state(frame.state)

            await self.__invoke_event_listener(Event(frame.event_source, frame.event_type, frame.key))
        else:
            self.__logger.debug("An unsupported event has been occurred on the device.")

    async def __handle_connection_closed(self):
        await self.__close_connection()

    async def __decrypt_frame(self, frame: EncryptedFrame) -> Union[ActionResponseFrame, EventFrame, ChallengeFrame]:
        self.__logger.debug("Decrypting frame... Frame [%s]", frame.json)
        result: Optional[Union[ActionResponseFrame, EventFrame, ChallengeFrame]] = None

        try:
            session_key: Union[bytes, bytearray] = self.__retrieve_session_key()
            api_auth_key: bytearray = bytearray.fromhex(self.__connection_options.api_auth_key)
            data: bytearray = bytearray(json.dumps(frame.data, separators=(',', ':')), ENCODING)
            payload_bytes: bytes = b64decode(frame.payload)
            iv: bytes = b64decode(frame.iv)
            mac: bytes = b64decode(frame.mac)

            # Verify mac
            hmac: HMAC = HMAC.new(key=api_auth_key, digestmod=SHA256)
            hmac = hmac.update(data)

            calculated_mac = hmac.digest()
            if frame.mac != str(b64encode(calculated_mac), ENCODING):
                raise RemootioClientDecryptionError(
                    self, "Frame can't be decrypted because mac verification was failed.")

            # Decrypt frame
            cipher: AES = AES.new(key=session_key, mode=AES.MODE_CBC, iv=iv)
            payload_bytes = cipher.decrypt(payload_bytes)
            payload_bytes = unpad(payload_bytes, AES.block_size)
            payload_json: dict = json.loads(payload_bytes)

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
        except RemootioError:
            raise
        except BaseException as ex:
            self.__logger.exception("Frame can't be decrypted because of an error.")
            raise RemootioClientDecryptionError(self, "Frame can't be decrypted because of an error.") from ex

        self.__logger.debug("Frame decrypted successfully. Frame [%s] DecryptedFrame [%s]", frame.json, result.json)
        return result

    async def __encrypt_frame(self, frame: ActionRequestFrame) -> EncryptedFrame:
        self.__logger.debug("Encrypting frame... Frame [%s]", frame.json)
        result: Optional[EncryptedFrame] = None

        try:
            session_key: Union[bytes, bytearray] = self.__retrieve_session_key()
            api_auth_key: bytearray = bytearray.fromhex(self.__connection_options.api_auth_key)

            # Encrypt frame
            iv_bytes: bytes = get_random_bytes(AES.block_size)
            cipher: AES = AES.new(key=session_key, mode=AES.MODE_CBC, iv=iv_bytes)

            payload_bytes: bytes = bytearray(json.dumps(frame.json), ENCODING)
            payload_bytes = pad(payload_bytes, AES.block_size)
            payload_bytes = cipher.encrypt(payload_bytes)

            # ATTENTION: Order of entries in the following dictionary is important for calculating of the mac.
            data: dict = {
                'iv': b64encode(iv_bytes).decode(),
                'payload': b64encode(payload_bytes).decode()
            }
            data_str: str = json.dumps(data, separators=(",", ":"))
            data_bytes: bytearray = bytearray(data_str, ENCODING)

            # Create mac
            hmac: HMAC = HMAC.new(key=api_auth_key, digestmod=SHA256)
            hmac = hmac.update(data_bytes)
            mac_bytes: bytes = hmac.digest()

            # Create encrypted frame
            result = EncryptedFrame(payload=data["payload"], iv=data["iv"], mac=str(b64encode(mac_bytes), ENCODING))
        except RemootioError:
            raise
        except BaseException as ex:
            self.__logger.exception("Frame can't be encrypted because of an error.")
            raise RemootioClientEncryptionError(self, "Frame can't be encrypted because of an error.") from ex

        self.__logger.debug("Frame encrypted successfully. Frame [%s] EncryptedFrame [%s]", frame.json, result.json)
        return result

    async def __invoke_state_listener(self, state_change: StateChange) -> NoReturn:
        if self.__state_change_listener is not None:
            self.__logger.debug("Invoking state change listener... OldState [%s] NewState [%s]",
                                state_change.old_state, state_change.new_state)
            try:
                await self.__state_change_listener.execute(self, state_change)
            except:
                self.__logger.warning("An error has been occurred during executing the state listener.",
                                      exc_info=True)

    async def __invoke_event_listener(self, event: Event) -> NoReturn:
        if self.__event_listener is not None:
            self.__logger.debug("Invoking event listener... Event [%s]", event)
            try:
                await self.__event_listener.execute(self, event)
            except:
                self.__logger.warning("An error has been occurred during executing the event listener.",
                                      exc_info=True)

    async def __change_state(self, new_state: State) -> NoReturn:
        old_state: State = self.__state

        do_change_state: bool = False
        if old_state == State.NO_SENSOR_INSTALLED:
            do_change_state = new_state != State.NO_SENSOR_INSTALLED
        elif old_state == State.UNKNOWN:
            do_change_state = new_state != State.UNKNOWN
        elif old_state == State.CLOSED:
            do_change_state = \
                (new_state == State.UNKNOWN) or \
                (new_state == State.NO_SENSOR_INSTALLED) or \
                (new_state == State.OPENING) or \
                (new_state == State.OPEN)

            if new_state == State.CLOSING:
                new_state = State.UNKNOWN
                do_change_state = True
        elif old_state == State.OPEN:
            do_change_state = \
                (new_state == State.UNKNOWN) or \
                (new_state == State.NO_SENSOR_INSTALLED) or \
                (new_state == State.CLOSING) or \
                (new_state == State.CLOSED)

            if new_state == State.OPENING:
                new_state = State.UNKNOWN
                do_change_state = True
        elif old_state == State.CLOSING:
            do_change_state = \
                (new_state == State.UNKNOWN) or \
                (new_state == State.NO_SENSOR_INSTALLED) or \
                (new_state == State.CLOSED)

            if new_state == State.OPENING:
                new_state = State.UNKNOWN
                do_change_state = True
            elif new_state == State.OPEN:
                await self.__change_state(State.UNKNOWN)
                do_change_state = True
        elif old_state == State.OPENING:
            do_change_state = \
                (new_state == State.UNKNOWN) or \
                (new_state == State.NO_SENSOR_INSTALLED) or \
                (new_state == State.OPEN)

            if new_state == State.CLOSING:
                new_state = State.UNKNOWN
                do_change_state = True
            elif new_state == State.CLOSED:
                await self.__change_state(State.UNKNOWN)
                do_change_state = True

        if do_change_state:
            self.__state = new_state

            self.__logger.info(
                "Last known state of the device has been changed. OldState [%s] NewState [%s]" %
                (old_state, self.state))

            await self.__invoke_state_listener(StateChange(old_state, self.state))

    def __retrieve_session_key(self) -> Union[bytes, bytearray]:
        result = None

        if self.__session_key is not None:
            result = b64decode(self.__session_key)
            self.__logger.debug("API Session Key will be used during operation.")
        else:
            result = bytearray.fromhex(self.__connection_options.api_secret_key)
            self.__logger.debug("API Secret Key will be used during operation.")

        return result

    def __calculate_next_action_id(self) -> int:
        self.__last_action_id = self.__last_action_id + 1
        return self.__last_action_id % 0x7FFFFFFF

    def __update_last_action_id(self, new_last_action_id: int) -> NoReturn:
        if self.__last_action_id < new_last_action_id or \
                (new_last_action_id == 0 and self.__last_action_id == 0x7FFFFFFF):
            old_last_action_id = self.__last_action_id
            self.__last_action_id = new_last_action_id

            self.__logger.debug(
                "LastActionId was updated. OldValue [%s] NewValue [%s]" % (old_last_action_id, self.__last_action_id))

    async def trigger(self) -> bool:
        """
        Sends an ``TRIGGER`` action to the device to trigger the control output of it and thus operate the gate or
        garage door.
        :return ``True`` if the action was sent successfully to the device, otherwise ``False``
        # :raises ``aioremootio.errors.RemootioClientUnsupportedOperationError`` if the last known state of the device
        #         isn't ``aioremootio.enums.State.NO_SENSOR_INSTALLED``
        """
        self.__logger.info("Triggering the device to open/close the gate or garage door...")

        result: bool = True

        try:
            await self.__encrypt_and_send_frame(
                ActionRequestFrame(self.__calculate_next_action_id(), ActionType.TRIGGER))
        except:
            result = False
            self.__logger.exception("Failed to send TRIGGER action to the device.")

        return result


    async def trigger_open(self) -> bool:
        """
        Sends an ``OPEN`` action to the device to trigger the control output of it and open the gate or
        garage door if it was closed.
        :return ``True`` if the action was sent successfully to the device, otherwise ``False``
        :raises ``aioremootio.errors.RemootioClientUnsupportedOperationError`` if the last known state of the device is
                ``aioremootio.enums.State.NO_SENSOR_INSTALLED``
        """
        self.__logger.info("Triggering the device to open the gate or garage door...")

        if self.state == State.NO_SENSOR_INSTALLED:
            raise RemootioClientUnsupportedOperationError(
                self, "OPEN action can't be send to the device because it hasn't a sensor installed.")

        result: bool = True

        try:
            await self.__encrypt_and_send_frame(
                ActionRequestFrame(self.__calculate_next_action_id(), ActionType.OPEN))
        except:
            result = False
            self.__logger.exception("Failed to send OPEN action to the device.")

        return result

    async def trigger_close(self) -> bool:
        """
        Sends an ``CLOSE`` action to the device to trigger the control output of it and close the gate or
        garage door if it was open.
        :return ``True`` if the action was sent successfully to the device, otherwise ``False``
        :raises ``aioremootio.errors.RemootioClientUnsupportedOperationError`` if the last known state of the device is
               ``aioremootio.enums.State.NO_SENSOR_INSTALLED``
        """
        self.__logger.info("Triggering the device to close the gate or garage door...")

        if self.state == State.NO_SENSOR_INSTALLED:
            raise RemootioClientUnsupportedOperationError(
                self, "CLOSE action can't be send to the device because it hasn't a sensor installed.")

        result: bool = True

        try:
            await self.__encrypt_and_send_frame(
                ActionRequestFrame(self.__calculate_next_action_id(), ActionType.CLOSE))
        except:
            result = False
            self.__logger.exception("Failed to send CLOSE action to the device.")

        return result

    async def trigger_state_update(self) -> bool:
        """
        Sends an ``QUERY`` action to the device to update the last known state of this client.
        :return ``True`` if the action was sent successfully to the device, otherwise ``False``
        """
        self.__logger.info("Triggering a state update from the device...")

        result: bool = True

        try:
            await self.__encrypt_and_send_frame(
                ActionRequestFrame(self.__calculate_next_action_id(), ActionType.QUERY))
        except:
            result = False
            self.__logger.exception("Failed to send QUERY action to the device.")

        return result

    @property
    def ip_address(self) -> str:
        """
        :return: IP address of the device
        """
        return self.__ip_address

    @property
    def api_version(self) -> Optional[int]:
        """
        :return: API version supported by the device
        """
        return self.__api_version

    @property
    def serial_number(self) -> Optional[str]:
        """
        :return: Serial number of the device
        """
        return self.__serial_number

    @property
    def uptime(self) -> Optional[int]:
        """
        :return: Uptime of the device since last start/restart
        """
        return self.__uptime

    @property
    def connected(self) -> bool:
        """
        :return: ``true`` if this client is connected to the device, otherwise ``false``
        """
        return self.__ws is not None and not self.__ws.closed

    @property
    def authenticated(self) -> bool:
        """
        :return: ``true`` if this client is authenticated by the device, otherwise ``false``
        """
        return self.__authenticated

    @property
    def state(self) -> State:
        """
        :return: last known state of the device
        """
        return self.__state
