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
from typing import Optional, NoReturn, Union, List
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
    ENCODING, \
    CONNECTING_LOCK_DELAY, \
    AUTHENTICATING_LOCK_DELAY, \
    TERMINATING_LOCK_DELAY, \
    INITIALIZING_LOCK_DELAY, \
    DISCONNECTING_LOCK_DELAY, \
    SAYING_HELLO_LOCK_DELAY, \
    UPDATING_LAST_ACTION_ID_LOCK_DELAY, \
    WAITING_FOR_SAID_HELLO_DELAY, \
    WAITING_FOR_DEVICE_ANSWERED_TO_HELLO_DELAY, \
    WAITING_FOR_CLIENT_IS_AUTHENTICATED_DELAY, \
    TASK_NAME_PING_SENDER, \
    TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER, \
    TASK_STOPPED_DELAY, \
    TASK_STARTED_DELAY, \
    ADDING_STATE_CHANGE_LISTENER_LOCK_DELAY, \
    ADDING_EVENT_LISTENERS_LOCK_DELAY


class RemootioClient(AsyncClass):
    """
    Class wich represents an Websocket API client of an Remootio device.
    """

    __connection_options: ConnectionOptions
    __client_session: aiohttp.ClientSession
    __logger: logging.Logger
    __state_change_listeners: List[Listener[StateChange]]
    __adding_state_change_listener_lock: asyncio.Lock
    __event_listeners: List[Listener[Event]]
    __adding_event_listener_lock: asyncio.Lock
    __ws: Optional[aiohttp.ClientWebSocketResponse]
    __ip_address: str
    __api_version: Optional[int]
    __serial_number: Optional[str]
    __uptime: Optional[int]
    __state: State
    __session_key: Optional[str]
    __updating_last_action_id_lock: asyncio.Lock
    __last_action_id: Optional[int]
    __connecting_lock: asyncio.Lock
    __disconnecting_lock: asyncio.Lock
    __authenticating_lock: asyncio.Lock
    __authenticated: bool
    __saying_hello_lock: asyncio.Lock
    __hello_said: bool
    __device_answered_to_hello: bool
    __terminating_lock: asyncio.Lock
    __terminated: bool
    __initializing_lock: asyncio.Lock
    __initialized: bool
    __do_receive_and_handle_messages: bool
    __receives_and_handles_messages: bool
    __do_send_pings: bool
    __sends_pings: bool

    def __init__(
            self,
            connection_options: Union[ConnectionOptions, dict],
            client_session: aiohttp.ClientSession,
            logger_configuration: Optional[LoggerConfiguration] = None,
            state_change_listeners: List[Listener[StateChange]] = [],
            event_listeners: List[Listener[Event]] = []
    ):
        """
        :param connection_options            : The options using to connect to the device.
                                               If a dictionary it must contain the device's IP address with key as
                                               defined by the constant
                                               ``aioremootio.constants.CONNECTION_OPTION_KEY_IP_ADDRESS``,
                                               the device's API Secret Key with key as defined by the constant
                                               ``aioremootio.constants.CONNECTION_OPTION_KEY_API_SECRET_KEY`` and
                                               the device's API Auth Key with key as defined by the constant
                                               ``aioremootio.constants.CONNECTION_OPTION_KEY_API_AUTH_KEY``.
                                               To get the API Secret Key and API Auth Key for the device,
                                               you must enable the API on the device. For more information please
                                               consult the Remootio Websocket API documentation at
                                               https://github.com/remootio/remootio-api-documentation.
        :param client_session                : The aiohttp client session to be used by the client.
        :param logger_configuration          : The logger configuration to be used by the client.
                                               If ``aioremootio.models.LoggerConfiguration.logger`` is set then a
                                               child with suffix ``__name__`` of it will be used, otherwise an logger
                                               instance will by instantiated and used.
                                               If ``aioremootio.models.LoggerConfiguration.level`` is set then this
                                               level will be used by the internally instantiated logger.
        :param state_change_listeners        : A list of
                                               ``aioremootio.listeners.Listener[aioremootio.models.StateChange]``
                                               instances to be invoked if the state of the device changes.
        :param event_listeners               : A list of
                                               ``aioremootio.listeners.Listener[aioremootio.models.Event]``
                                               instances to be invoked if an by the client supported event occurs on
                                               the device.
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
                logger = logger_configuration.logger.getChild(__name__)
        else:
            logger = logging.getLogger(__name__)

            handler: logging.Handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(handler)

        self.__connection_options = connection_options
        self.__client_session = client_session
        self.__logger = logger
        self.__state_change_listeners = []
        self.__adding_state_change_listener_lock = asyncio.Lock()
        self.__event_listeners = []
        self.__adding_event_listener_lock = asyncio.Lock()
        self.__ws = None
        self.__ip_address = self.__connection_options.ip_address
        self.__api_version = None
        self.__serial_number = None
        self.__uptime = None
        self.__state = State.UNKNOWN
        self.__session_key = None
        self.__updating_last_action_id_lock = asyncio.Lock()
        self.__last_action_id = None
        self.__connecting_lock = asyncio.Lock()
        self.__disconnecting_lock = asyncio.Lock()
        self.__authenticating_lock = asyncio.Lock()
        self.__authenticated = False
        self.__saying_hello_lock = asyncio.Lock()
        self.__hello_said = False
        self.__device_answered_to_hello = False
        self.__terminating_lock = asyncio.Lock()
        self.__terminated = False
        self.__initializing_lock = asyncio.Lock()
        self.__initialized = False
        self.__do_receive_and_handle_messages = True
        self.__receives_and_handles_messages = False
        self.__do_send_pings = True
        self.__sends_pings = False

        if state_change_listeners is not None:
            assert None not in state_change_listeners, "List of state change listeners contains invalid elements."
            self.__state_change_listeners.extend(state_change_listeners)

        if event_listeners is not None:
            assert None not in event_listeners, "List of state change listeners contains invalid elements."
            self.__event_listeners.extend(event_listeners)

    async def __ainit__(self, *args, **kwargs) -> NoReturn:
        await super().__ainit__(*args, **kwargs)

        await self.__initialize()

    async def __adel__(self) -> None:
        await self.__terminate()

        await super().__adel__()

    async def __aenter__(self) -> 'RemootioClient':
        await self.__initialize()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.close()

    async def __initialize(self) -> NoReturn:
        self.__logger.info("Initializing this client...")

        async with self.__initializing_lock:
            try:
                await self.__invoke_state_change_listeners(StateChange(None, self.state))

                await self.__open_connection(handle_connection_error=False)

                if await self.connected and await self.authenticated:
                    self.create_task(self.__receive_and_handle_messages(), name=TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER)\
                        .add_done_callback(self.__handle_task_done)
                    await self.__wait_for_task_started(TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER)

                    self.create_task(self.__send_pings(), name=TASK_NAME_PING_SENDER) \
                        .add_done_callback(self.__handle_task_done)
                    await self.__wait_for_task_started(TASK_NAME_PING_SENDER)
            except BaseException as ex:
                self.__logger.exception("Failed to initialize this client.")
                raise RemootioClientError(self, "Failed to initialize this client.") from ex
            else:
                self.__initialized = True

    async def __terminate(self) -> NoReturn:
        self.__logger.info("Terminating this client...")

        async with self.__terminating_lock:
            self.__do_receive_and_handle_messages = False
            self.__do_send_pings = False

            await self.__wait_for_task_stopped(TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER)
            await self.__wait_for_task_stopped(TASK_NAME_PING_SENDER)
            await self.__close_connection()

            self.__initialized = False
            self.__terminated = True

    async def __open_connection(self, handle_connection_error: bool = True) -> ClientWebSocketResponse:
        if not await self.terminated and (not await self.connected or not await self.authenticated):
            if await self.connected and not await self.authenticated:
                self.__logger.warning(
                    "Living connection to the device will be closed now, because this client isn't authenticated by "
                    "the device.")
                await self.__close_connection()

            # Establishing connection
            async with self.__connecting_lock:
                self.__logger.info("Establishing connection to the device...")
                try:
                    self.__ws = await self.__client_session.ws_connect(
                        f"ws://{self.__connection_options.ip_address}:8080/")
                    self.__logger.info("Connection to the device has been established successfully.")
                except BaseException as ex:
                    self.__ws = None
                    if handle_connection_error:
                        self.__logger.exception("Unable to establish connection to the device.")
                    else:
                        raise RemootioClientConnectionEstablishmentError(
                            self, "Unable to establish connection to the device.") from ex

            # Authenticating
            await self.__authenticate(self.__ws)

            # Say hello
            await self.__say_hello(self.__ws)

        return self.__ws

    async def __close_connection(self) -> NoReturn:
        await self.__wait_for_connecting()
        await self.__wait_for_authenticating()

        async with self.__disconnecting_lock:
            if self.__ws is not None and not self.__ws.closed:
                try:
                    self.__logger.info("Closing connection to the device...")
                    await self.__ws.close()
                except BaseException:
                    self.__logger.warning("Unable to close connection to the device because of an error.",
                                          exc_info=(self.__logger.getEffectiveLevel() == logging.DEBUG))

            self.__session_key = None
            self.__last_action_id = None
            self.__authenticated = False
            self.__ws = None

    async def __authenticate(self, ws: ClientWebSocketResponse) -> NoReturn:
        if not await self.terminated and await self.connected and not await self.authenticated:
            async with self.__authenticating_lock:
                self.__logger.info("Authenticating this client by the device...")

                try:
                    await self.__send_frame(AuthFrame(), ws=ws)

                    frame: [dict, AbstractFrame] = await ws.receive_json(timeout=30)
                    ensure_frame_type(frame, FrameType.ENCRYPTED)

                    frame = await self.__decrypt_frame(EncryptedFrame(json=frame))
                    if isinstance(frame, ChallengeFrame):
                        self.__session_key = frame.session_key
                        self.__last_action_id = frame.initial_action_id
                    else:
                        raise RemootioClientError(self, "Received frame isn't the expected.")

                    await self.__encrypt_and_send_frame(
                        ActionRequestFrame(await self.__calculate_next_action_id(), ActionType.QUERY), ws=ws)

                    frame = await ws.receive_json(timeout=30)
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

    async def __say_hello(self, ws: ClientWebSocketResponse):
        if not self.__hello_said:
            async with self.__saying_hello_lock:
                self.__logger.info("Saying hello to the device...")

                try:
                    await self.__send_frame(HelloFrame(), ws)

                    self.__hello_said = True
                except BaseException as ex:
                    self.__logger.exception("This client is unable to say hello to the device because of an error.")
                    raise RemootioClientError(
                        self, "This client is unable to say hello to the device because of an error.") from ex

    async def __send_frame(
            self, frame: AbstractJSONHolderFrame, ws: Optional[ClientWebSocketResponse] = None) -> NoReturn:
        if not await self.terminated:
            if ws is None:
                ws = await self.__open_connection()

            if ws is not None and not ws.closed:
                if isinstance(frame, HelloFrame) or isinstance(frame, PingFrame) or self.__authenticating_lock.locked():
                    pass
                else:
                    await self.__wait_for_said_hello()
                    await self.__wait_for_device_has_answered_to_hello()

                if self.__logger.getEffectiveLevel() == logging.DEBUG:
                    self.__logger.info("Sending frame... Frame [%s]", json.dumps(frame.json))
                else:
                    self.__logger.info("Sending frame...")

                try:
                    if isinstance(frame, HelloFrame) and self.__hello_said:
                        self.__logger.warning("Frame will be don't sent because this client has already said hello "
                                              "to the device.")
                    else:
                        await ws.send_json(frame.json)
                except BaseException as ex:
                    if self.__logger.getEffectiveLevel() == logging.DEBUG:
                        self.__logger.warning("Sending of frame has been failed.", exc_info=True)
                    else:
                        self.__logger.warning("Sending of frame has been failed.")

                    raise RemootioClientError(self, "Sending of frame has been failed.") from ex
            else:
                raise RemootioClientConnectionEstablishmentError(
                    self, "Sending of frame has been failed because connection to the device can't be established.")
        else:
            if self.__logger.getEffectiveLevel() == logging.DEBUG:
                self.__logger.warning("Frame will be don't sent because this client is already terminated. Frame [%s]",
                                      json.dumps(frame.json))
            else:
                self.__logger.warning("Frame will be don't sent because this client is already terminated.")

    async def __encrypt_and_send_frame(
            self, frame: ActionRequestFrame, ws: Optional[ClientWebSocketResponse] = None) -> NoReturn:
        self.__logger.info("Encrypting and sending ActionRequestFrame... ActionType [%s]", frame.action_type)

        encrypted_frame: EncryptedFrame = await self.__encrypt_frame(frame)
        await self.__send_frame(encrypted_frame, ws)

    async def __send_pings(self) -> NoReturn:
        try:
            while True:
                if not self.__terminating_lock.locked() and self.__do_send_pings:
                    self.__sends_pings = True

                    ws: Optional[ClientWebSocketResponse] = None
                    try:
                        ws = await self.__open_connection()
                    except BaseException:
                        self.__logger.warning("Sending PINGs by this client will be delayed "
                                              "because connection to the device can't be established.")
                        await asyncio.sleep(PING_SENDER_HEARTBEAT)
                        continue

                    if ws is not None and not ws.closed:
                        try:
                            await self.__send_frame(PingFrame(), ws)
                        except BaseException:
                            self.__logger.warning("Failed to send PING.")
                    else:
                        self.__logger.warning("Sending PINGs by this client will be delayed "
                                              "because connection to the device can't be established.")

                    await asyncio.sleep(PING_SENDER_HEARTBEAT)
                else:
                    self.__logger.info("Sending PINGs by this client will be now stopped because it is about to be "
                                       "terminated.")
                    return
        except CancelledError:
            self.__logger.info("Sending PINGs by this client will be now stopped because of cancelling the task.")
        except BaseException:
            self.__logger.exception("Sending PINGs by this client will be now stopped because of an error.")
            raise

    async def __receive_and_handle_messages(self) -> NoReturn:
        try:
            while True:
                if not self.__terminating_lock.locked() and self.__do_receive_and_handle_messages:
                    self.__receives_and_handles_messages = True

                    ws: Optional[ClientWebSocketResponse] = None
                    try:
                        ws = await self.__open_connection()
                    except BaseException:
                        self.__logger.warning("Receiving and handling of messages by this client will be delayed "
                                              "because connection to the device can't be established.")
                        await asyncio.sleep(MESSAGE_HANDLER_HEARTBEAT)
                        continue

                    if ws is not None and not ws.closed:
                        async for msg in ws:
                            try:
                                self.__logger.debug("Message received from device. Type [%s]", msg.type)

                                if msg.type == WSMsgType.TEXT:
                                    msg_json: dict = msg.json()
                                    self.__logger.debug(f"< {json.dumps(msg_json)}")

                                    frame_type = retrieve_frame_type(msg_json)

                                    if frame_type is None or frame_type == FrameType.UNKNOWN:
                                        self.__logger.error(
                                            "Failed to handle message. Unable to determine frame type.")
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
                                            "Failed to handle message. Frame of type isn't supported. "
                                            "FrameType [%s]", frame_type
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
                            except BaseException:
                                self.__logger.error("Failed to handle received message.")
                        else:
                            await asyncio.sleep(MESSAGE_HANDLER_HEARTBEAT)
                    else:
                        self.__logger.warning("Receiving and handling of messages by this client will be delayed "
                                              "because connection to the device can't be established.")
                        await asyncio.sleep(MESSAGE_HANDLER_HEARTBEAT)
                else:
                    self.__logger.info("Receiving and handling of messages by this client will be now stopped "
                                       "because it is about to be terminated.")
                    return
        except CancelledError:
            self.__logger.info("Receiving and handling of messages by this client will be now stopped "
                               "because of cancelling the task.")
        except BaseException:
            self.__logger.exception("Receiving and handling of messages by this client will be now stopped"
                                    "because of an error.")
            raise

    def __handle_task_done(self, task: asyncio.Task) -> NoReturn:
        if task.get_name() == TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER:
            self.__receives_and_handles_messages = False
        elif task.get_name() == TASK_NAME_PING_SENDER:
            self.__sends_pings = False

    async def __handle_error_frame(self, frame: ErrorFrame) -> NoReturn:
        self.__logger.debug("Handling received ErrorFrame...")
        self.__logger.error("An error has been occurred on the device. Type [%s]" % frame.error_type)

    async def __handle_server_hello_frame(self, frame: ServerHelloFrame) -> NoReturn:
        self.__logger.debug("Handling received ServerHelloFrame...")
        self.__api_version = frame.api_version
        self.__serial_number = frame.serial_number
        self.__device_answered_to_hello = True

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
        await self.__update_last_action_id(frame.action_id)

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
            if frame.event_type == EventType.RESTART or self.__uptime < frame.uptime:
                self.__logger.info(
                    "An event has been occurred on the device. EventType [%s] Key [%s] EventSource [%s]" %
                    (frame.event_type, frame.key, frame.event_source))

                self.__uptime = frame.uptime

                if frame.event_type == EventType.RELAY_TRIGGER:
                    state: State = frame.state
                    if state == State.OPEN:
                        state = State.CLOSING
                    elif state == State.CLOSED:
                        state = State.OPENING

                    await self.__change_state(state)
                elif frame.event_type == EventType.STATE_CHANGE:
                    await self.__change_state(frame.state)
                elif frame.event_type == EventType.LEFT_OPEN:
                    await self.__change_state(frame.state)
                elif frame.event_type == EventType.RESTART:
                    await self.__change_state(frame.state)

                await self.__invoke_event_listener(Event(frame.event_source, frame.event_type, frame.key))
            else:
                self.__logger.debug(
                    "An event has been occurred on the device but before this client has been connected to the device. "
                    "EventType [%s] Key [%s] EventSource [%s]" % (frame.event_type, frame.key, frame.event_source))
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

    async def __invoke_state_change_listeners(self, state_change: StateChange) -> NoReturn:
        await self.__wait_for_adding_state_change_listener()

        state_change_listeners = self.__state_change_listeners[:]

        if len(state_change_listeners) > 0:
            self.__logger.debug("Invoking state change listeners... OldState [%s] NewState [%s]",
                                state_change.old_state, state_change.new_state)

            for listener in state_change_listeners:
                try:
                    await listener.execute(self, state_change)
                except BaseException:
                    self.__logger.warning("An error has been occurred during invoking the state listener.",
                                          exc_info=True)

    async def __invoke_event_listener(self, event: Event) -> NoReturn:
        await self.__wait_for_adding_event_listener()

        event_listeners = self.__event_listeners[:]

        if len(event_listeners) > 0:
            self.__logger.debug("Invoking event listeners... Event [%s]", event)

            for listener in event_listeners:
                try:
                    await listener.execute(self, event)
                except BaseException:
                    self.__logger.warning("An error has been occurred during invoking the event listener.",
                                          exc_info=True)

    async def __change_state(self, new_state: State) -> NoReturn:
        old_state: State = self.__state

        do_change_state: bool = False
        if old_state == new_state:
            pass
        elif old_state == State.NO_SENSOR_INSTALLED:
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
                await self.__change_state(State.UNKNOWN)
                old_state = self.__state
                do_change_state = True
        elif old_state == State.OPEN:
            do_change_state = \
                (new_state == State.UNKNOWN) or \
                (new_state == State.NO_SENSOR_INSTALLED) or \
                (new_state == State.CLOSING) or \
                (new_state == State.CLOSED)

            if new_state == State.OPENING:
                await self.__change_state(State.UNKNOWN)
                old_state = self.__state
                do_change_state = True
        elif old_state == State.CLOSING:
            do_change_state = \
                (new_state == State.UNKNOWN) or \
                (new_state == State.NO_SENSOR_INSTALLED) or \
                (new_state == State.CLOSED)

            if new_state == State.OPENING:
                await self.__change_state(State.UNKNOWN)
                old_state = self.__state
                do_change_state = True
            elif new_state == State.OPEN:
                await self.__change_state(State.UNKNOWN)
                old_state = self.__state
                do_change_state = True
        elif old_state == State.OPENING:
            do_change_state = \
                (new_state == State.UNKNOWN) or \
                (new_state == State.NO_SENSOR_INSTALLED) or \
                (new_state == State.OPEN)

            if new_state == State.CLOSING:
                await self.__change_state(State.UNKNOWN)
                old_state = self.__state
                do_change_state = True
            elif new_state == State.CLOSED:
                await self.__change_state(State.UNKNOWN)
                old_state = self.__state
                do_change_state = True

        if do_change_state:
            self.__state = new_state

            self.__logger.info(
                "Last known state of the device has been changed. OldState [%s] NewState [%s]" %
                (old_state, self.state))

            await self.__invoke_state_change_listeners(StateChange(old_state, self.state))

    def __retrieve_session_key(self) -> Union[bytes, bytearray]:
        result = None

        if self.__session_key is not None:
            result = b64decode(self.__session_key)
            self.__logger.debug("API Session Key will be used during operation.")
        else:
            result = bytearray.fromhex(self.__connection_options.api_secret_key)
            self.__logger.debug("API Secret Key will be used during operation.")

        return result

    async def __calculate_next_action_id(self) -> int:
        await self.__wait_for_updating_last_action_id()

        self.__last_action_id = self.__last_action_id + 1
        return self.__last_action_id % 0x7FFFFFFF

    async def __update_last_action_id(self, new_last_action_id: int) -> NoReturn:
        if self.__last_action_id < new_last_action_id or \
                (new_last_action_id == 0 and self.__last_action_id == 0x7FFFFFFF):
            async with self.__updating_last_action_id_lock:
                old_last_action_id = self.__last_action_id
                self.__last_action_id = new_last_action_id

                self.__logger.debug(
                    "LastActionId was updated. OldValue [%s] NewValue [%s]" %
                    (old_last_action_id, self.__last_action_id))

    async def __wait_for_connecting(self):
        while self.__connecting_lock.locked():
            self.__logger.debug("This client does currently connecting to the device. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(CONNECTING_LOCK_DELAY)

    async def __wait_for_authenticating(self):
        while self.__authenticating_lock.locked():
            self.__logger.debug("This client does currently authenticating with the device. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(AUTHENTICATING_LOCK_DELAY)

    async def __wait_for_authenticated(self):
        while not self.__authenticated:
            self.__logger.debug("This client has not yet authenticated itself with the device. "
                                "Waiting until the authentication is done.")
            await asyncio.sleep(WAITING_FOR_CLIENT_IS_AUTHENTICATED_DELAY)

    async def __wait_for_disconnecting(self):
        while self.__disconnecting_lock.locked():
            self.__logger.debug("This client does currently disconnecting from the device. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(DISCONNECTING_LOCK_DELAY)

    async def __wait_for_terminating(self):
        while self.__terminating_lock.locked():
            self.__logger.debug("This client does currently terminating. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(TERMINATING_LOCK_DELAY)

    async def __wait_for_initializing(self):
        while self.__initializing_lock.locked():
            self.__logger.debug("This client does currently initializing. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(INITIALIZING_LOCK_DELAY)

    async def __wait_for_saying_hello(self):
        while self.__saying_hello_lock.locked():
            self.__logger.debug("This client is currently saying hello to the device. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(SAYING_HELLO_LOCK_DELAY)

    async def __wait_for_said_hello(self):
        while not self.__hello_said:
            self.__logger.debug("This client has not yet said hello to the device. "
                                "Waiting until it has sid hello.")
            await asyncio.sleep(WAITING_FOR_SAID_HELLO_DELAY)

    async def __wait_for_device_has_answered_to_hello(self):
        while not self.__device_answered_to_hello:
            self.__logger.debug("The device has not yet answered to the hello from this client. "
                                "Waiting until it has answered.")
            await asyncio.sleep(WAITING_FOR_DEVICE_ANSWERED_TO_HELLO_DELAY)

    async def __wait_for_updating_last_action_id(self):
        while self.__updating_last_action_id_lock.locked():
            self.__logger.debug("This client is currently updating the last action id. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(UPDATING_LAST_ACTION_ID_LOCK_DELAY)

    async def __wait_for_task_started(self, task_name: str):
        if task_name == TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER:
            while not self.__receives_and_handles_messages:
                self.__logger.debug("Task to receive and handle messages isn't started yet. "
                                    "Waiting as long as it is started.")
                await asyncio.sleep(TASK_STARTED_DELAY)
        elif task_name == TASK_NAME_PING_SENDER:
            while not self.__sends_pings:
                self.__logger.debug("Task to sending isn't started yet. "
                                    "Waiting as long as it is started.")
                await asyncio.sleep(TASK_STARTED_DELAY)

    async def __wait_for_task_stopped(self, task_name: str):
        if task_name == TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER:
            while self.__receives_and_handles_messages:
                self.__logger.debug("Task to receive and handle messages isn't stopped yet. "
                                    "Waiting as long as it is stopped.")
                await asyncio.sleep(TASK_STOPPED_DELAY)
        elif task_name == TASK_NAME_PING_SENDER:
            while self.__sends_pings:
                self.__logger.debug("Task to sending isn't stopped yet. "
                                    "Waiting as long as it is stopped.")
                await asyncio.sleep(TASK_STOPPED_DELAY)

    async def __wait_for_adding_state_change_listener(self):
        while self.__adding_state_change_listener_lock.locked():
            self.__logger.debug("A listener will be currently added to the list of state change listeners. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(ADDING_STATE_CHANGE_LISTENER_LOCK_DELAY)

    async def __wait_for_adding_event_listener(self):
        while self.__adding_event_listener_lock.locked():
            self.__logger.debug("A listener will be currently added to the list of event listeners. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(ADDING_EVENT_LISTENERS_LOCK_DELAY)

    async def __trigger(self, action_type: ActionType) -> NoReturn:
        if await self.terminated:
            raise RemootioClientError(
                self, "Unable to send frame because this client is already terminated. ActionType [%s]" % action_type)

        action_id: int = await self.__calculate_next_action_id()
        frame: ActionRequestFrame = ActionRequestFrame(action_id, action_type)

        await self.__encrypt_and_send_frame(frame)

    async def trigger(self) -> NoReturn:
        """
        Sends an ``TRIGGER`` action to the device to trigger the control output of it and thus operate the
        gate or garage door.
        # :raises ``aioremootio.errors.RemootioClientUnsupportedOperationError`` if the last known state of the device
        #         isn't ``aioremootio.enums.State.NO_SENSOR_INSTALLED``
        """
        self.__logger.info("Triggering the device to open/close the gate or garage door...")

        await self.__trigger(ActionType.TRIGGER)

    async def trigger_open(self) -> NoReturn:
        """
        Queues an ``OPEN`` action to the device to trigger the control output of it and open the gate or
        garage door if it was closed.
        :raises ``aioremootio.errors.RemootioClientUnsupportedOperationError`` if the last known state of the device is
                ``aioremootio.enums.State.NO_SENSOR_INSTALLED``
        """
        self.__logger.info("Triggering the device to open the gate or garage door...")

        if self.state == State.NO_SENSOR_INSTALLED:
            raise RemootioClientUnsupportedOperationError(
                self, "OPEN action can't be send to the device because it hasn't a sensor installed.")

        await self.__trigger(ActionType.OPEN)

    async def trigger_close(self) -> NoReturn:
        """
        Sends an ``CLOSE`` action to the device to trigger the control output of it and close the gate or
        garage door if it was open.
        :raises ``aioremootio.errors.RemootioClientUnsupportedOperationError`` if the last known state of the device is
               ``aioremootio.enums.State.NO_SENSOR_INSTALLED``
        """
        self.__logger.info("Triggering the device to close the gate or garage door...")

        if self.state == State.NO_SENSOR_INSTALLED:
            raise RemootioClientUnsupportedOperationError(
                self, "CLOSE action can't be send to the device because it hasn't a sensor installed.")

        await self.__trigger(ActionType.CLOSE)

    async def trigger_state_update(self) -> NoReturn:
        """
        Sends an ``QUERY`` action to the device to update the last known state of this client.
        """
        self.__logger.info("Triggering a state update from the device...")

        await self.__trigger(ActionType.QUERY)

    @property
    def ip_address(self) -> str:
        """
        :return: IP address of the device
        """
        return self.__ip_address

    @property
    async def api_version(self) -> int:
        """
        :return: API version supported by the device
        """

        await self.__wait_for_device_has_answered_to_hello()

        return self.__api_version

    @property
    async def serial_number(self) -> Optional[str]:
        """
        :return: Serial number of the device
        """

        await self.__wait_for_device_has_answered_to_hello()

        return self.__serial_number

    @property
    async def uptime(self) -> Optional[int]:
        """
        :return: Uptime of the device since last start/restart
        """

        if self.__uptime is None:
            await self.__wait_for_authenticated()

        return self.__uptime

    @property
    async def connected(self) -> bool:
        """
        Determines whether this client is connected to the device. This mains a WebSocket connection is successfully
        established to the device.
        :return: ``true`` if this client is connected to the device, otherwise ``false``
        """

        await self.__wait_for_disconnecting()
        await self.__wait_for_connecting()

        return self.__ws is not None and not self.__ws.closed

    @property
    async def authenticated(self) -> bool:
        """
        Determines whether this client is authenticated on the device.
        :return: ``true`` if this client is authenticated with the device, otherwise ``false``
        """

        await self.__wait_for_authenticating()

        return self.__authenticated

    @property
    async def said_hello(self):
        """
        Determines whether this client has already said hello during its initialization to the device and the device
        answered to it. This must be done before sending any action to the device.
        If any action will be send using this client to the device before the client says hello to the device and the
        device answers to it, then the sending of the action will be paused as so long as the before described progress
        isn't done.
        :return: ``true`` if this client has already said hello to the device and the device answered,
                 otherwise ``false``
        """

        await self.__wait_for_saying_hello()

        return self.__hello_said and self.__device_answered_to_hello

    @property
    async def terminated(self) -> bool:
        """
        Determines whether this client is terminated. This mains that background tasks created by this client are
        stopped and the WebSocket connection to the device is closed.
        :return: ``true`` if this client is terminated, otherwise ``false``
        """

        await self.__wait_for_terminating()

        return self.__terminated

    @property
    async def initialized(self) -> bool:
        """
        Determines whether this client is initialized. This mains that this client has successfully established a
        WebSocket connection to the device and is successfully authenticated on it, furthermore that all by the
        client needed background tasks are created and started.
        :return: ``true`` if this client is initialized, otherwise ``false``
        """

        await self.__wait_for_initializing()

        return self.__initialized

    @property
    def state(self) -> State:
        """
        :return: last known state of the device
        """
        return self.__state

    async def add_state_change_listener(self, state_change_listener: Listener[StateChange]) -> bool:
        """
        Adds the given ``aioremootio.listeners.Listener[aioremootio.models.StateChange]`` to the list of listeners to be
        invoked if the state of the device changes.
        :param state_change_listener: the ``aioremootio.listeners.Listener[aioremootio.models.StateChange]``
        :return: ``true`` if the listener was successfully added to the list of listeners, otherwise ``false``
        """

        result: bool = False

        async with self.__adding_state_change_listener_lock:
            if state_change_listener is not None and state_change_listener not in self.__state_change_listeners:
                self.__state_change_listeners.append(state_change_listener)
                result = True

        return result

    async def add_event_listener(self, event_listener: Listener[Event]) -> bool:
        """
        Adds the given ``aioremootio.listeners.Listener[aioremootio.models.Event]`` to the list of listeners to be
        invoked if an by the client supported event occurs on the device.
        :param event_listener: the ``aioremootio.listeners.Listener[aioremootio.models.Event]``
        :return: ``true`` if the listener was successfully added to the list of listeners, otherwise ``false``
        """

        result: bool = False

        async with self.__adding_event_listener_lock:
            if event_listener is not None and event_listener not in self.__event_listeners:
                self.__event_listeners.append(event_listener)
                result = True

        return result

