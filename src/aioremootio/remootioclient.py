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
from __future__ import annotations

import asyncio
import aiohttp
import logging
import json
from typing import Optional, NoReturn, Union, List
from async_class import AsyncClass, TaskStore
from aiohttp import ClientWebSocketResponse, WSMsgType
from base64 import b64encode, b64decode
from voluptuous import Invalid
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
    RemootioClientUnsupportedOperationError, \
    RemootioClientInvalidConfigurationError
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
from .enums import State, FrameType, ActionType, EventType, ErrorCode, ErrorType, EventSource
from .constants import \
    MESSAGE_HANDLER_HEARTBEAT, \
    PING_SENDER_HEARTBEAT, \
    CONNECTION_OPTION_KEY_HOST, \
    CONNECTION_OPTION_KEY_API_AUTH_KEY, \
    CONNECTION_OPTION_KEY_API_SECRET_KEY, \
    CONNECTION_OPTION_KEY_CONNECT_AUTOMATICALLY, \
    CONNECTION_OPTIONS_VOLUPTUOUS_SCHEMA, \
    CONNECTION_OPTION_DEFAULT_VALUE_CONNECT_AUTOMATICALLY, \
    ENCODING, \
    LIFECYCLE_LOCK_DELAY, \
    UPDATING_LAST_ACTION_ID_LOCK_DELAY, \
    WAITING_FOR_SAID_HELLO_DELAY, \
    WAITING_FOR_DEVICE_ANSWERED_TO_HELLO_DELAY, \
    TASK_NAME_PING_SENDER, \
    TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER, \
    TASK_NAME_CONNECTOR, \
    TASK_NAME_DISCONNECTOR, \
    TASK_STOPPED_DELAY, \
    TASK_STARTED_DELAY, \
    TASK_STOPPED_TIMEOUT, \
    ADDING_STATE_CHANGE_LISTENER_LOCK_DELAY, \
    ADDING_EVENT_LISTENERS_LOCK_DELAY


class RemootioClient(AsyncClass):
    """
    Class wich represents a Websocket API client of a Remootio device.
    """

    __logger: logging.Logger
    __connection_options: ConnectionOptions
    __host: str
    __api_version: Optional[int]
    __serial_number: Optional[str]
    __uptime: Optional[int]
    __state: State
    __updating_last_action_id_lock: asyncio.Lock
    __last_action_id: Optional[int]
    __authenticating: bool
    __authenticated: bool
    __saying_hello: bool
    __said_hello: bool
    __device_answered_to_hello: bool

    # Lifecycle
    __lifecycle: asyncio.Condition
    __initializing: bool
    __initialized: bool
    __connecting: bool
    __disconnecting: bool
    __terminating: bool
    __terminated: bool

    # Websocket
    __client_session: aiohttp.ClientSession
    __ws: Optional[aiohttp.ClientWebSocketResponse]
    __session_key: Optional[str]

    # Tasks
    __task_store: TaskStore
    __do_receive_and_handle_messages: bool
    __receives_and_handles_messages: bool
    __do_send_pings: bool
    __sends_pings: bool

    # State change listeners
    __state_change_listeners: List[Listener[StateChange]]
    __modifying_state_change_listeners_lock: asyncio.Lock

    # Event listeners
    __event_listeners: List[Listener[Event]]
    __modifying_event_listeners_lock: asyncio.Lock

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
                                               If a dictionary it must contain the device's IP address or hostname with
                                               key as defined by the constant
                                               ``aioremootio.constants.CONNECTION_OPTION_KEY_HOSTNAME``,
                                               the device's API Secret Key with key as defined by the constant
                                               ``aioremootio.constants.CONNECTION_OPTION_KEY_API_SECRET_KEY`` and
                                               the device's API Auth Key with key as defined by the constant
                                               ``aioremootio.constants.CONNECTION_OPTION_KEY_API_AUTH_KEY``,
                                               furthermore it can contain a flag with a key as defined by the constant
                                               ``aioremootio.constants.CONNECTION_OPTION_KEY_CONNECT_AUTOMATICALLY``
                                               to control whether the client should establish a connection to the
                                               device during its initialization right after its construction or not.
                                               Default value for the latter optional flag is defined by the constant
                                               ``aioremootio.constants.CONNECTION_OPTION_DEFAULT_VALUE_CONNECT_AUTOMATICALLY``.
                                               To get the API Secret Key and API Auth Key for the device,
                                               you must enable the API on the device. For more information please
                                               consult the Remootio Websocket API documentation at
                                               https://github.com/remootio/remootio-api-documentation.
        :param client_session                : The aiohttp client session to be used by the client.
        :param logger_configuration          : The logger configuration to be used by the client.
                                               If ``aioremootio.models.LoggerConfiguration.logger`` is set then a
                                               child with suffix ``__name__`` of it will be used, otherwise a logger
                                               instance will be instantiated and used.
                                               If ``aioremootio.models.LoggerConfiguration.level`` is set then this
                                               level will be used by the internally instantiated logger.
        :param state_change_listeners        : A list of
                                               ``aioremootio.listeners.Listener[aioremootio.models.StateChange]``
                                               instances to be invoked if the state of the device changes.
        :param event_listeners               : A list of
                                               ``aioremootio.listeners.Listener[aioremootio.models.Event]``
                                               instances to be invoked if an event occurs on the device that is
                                               supported by the client.
        """
        super(RemootioClient, self).__init__()

        if type(connection_options) is dict:
            connection_option_keys = [
                CONNECTION_OPTION_KEY_HOST,
                CONNECTION_OPTION_KEY_API_SECRET_KEY,
                CONNECTION_OPTION_KEY_API_AUTH_KEY
            ]

            for connection_option_key in connection_option_keys:
                if connection_option_key not in connection_options:
                    raise ValueError(f"Option not defined: {connection_option_key}")

            connection_options = ConnectionOptions(
                connection_options[CONNECTION_OPTION_KEY_HOST],
                connection_options[CONNECTION_OPTION_KEY_API_SECRET_KEY],
                connection_options[CONNECTION_OPTION_KEY_API_AUTH_KEY],
                connection_options.get(
                    CONNECTION_OPTION_KEY_CONNECT_AUTOMATICALLY, CONNECTION_OPTION_DEFAULT_VALUE_CONNECT_AUTOMATICALLY)
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

        self.__logger = logger
        self.__connection_options = connection_options
        self.__host = self.__connection_options.host
        self.__api_version = None
        self.__serial_number = None
        self.__uptime = None
        self.__state = State.UNKNOWN
        self.__updating_last_action_id_lock = asyncio.Lock()
        self.__last_action_id = None
        self.__authenticating = False
        self.__authenticated = False
        self.__saying_hello = False
        self.__said_hello = False
        self.__device_answered_to_hello = False

        # Lifecycle
        self.__lifecycle = asyncio.Condition()
        self.__initializing = False
        self.__initialized = False
        self.__connecting = False
        self.__disconnecting = False
        self.__terminating = False
        self.__terminated = False

        # Websocket
        self.__client_session = client_session
        self.__ws = None
        self.__session_key = None

        # Tasks
        self.__task_store = TaskStore(self.loop)
        self.__do_receive_and_handle_messages = True
        self.__receives_and_handles_messages = False
        self.__do_send_pings = True
        self.__sends_pings = False

        # State change listeners
        self.__state_change_listeners = []
        self.__modifying_state_change_listeners_lock = asyncio.Lock()

        # Event listeners
        self.__event_listeners = []
        self.__modifying_event_listeners_lock = asyncio.Lock()

        try:
            CONNECTION_OPTIONS_VOLUPTUOUS_SCHEMA(connection_options.__dict__)
        except Invalid as e:
            raise RemootioClientInvalidConfigurationError(self, e) from e

        if state_change_listeners is not None:
            assert None not in state_change_listeners, "List of state change listeners contains invalid elements."
            self.__state_change_listeners.extend(state_change_listeners)

        if event_listeners is not None:
            assert None not in event_listeners, "List of state change listeners contains invalid elements."
            self.__event_listeners.extend(event_listeners)

    def __repr__(self) -> str:
        return "%s{host:%s,serial_number:%s,api_version:%s,state:%s}" % (
            self.__class__.__name__,
            self.__host if self.__host is not None else "N/A",
            self.__serial_number if self.__serial_number is not None else "N/A",
            self.__api_version if self.__api_version is not None else "N/A",
            self.__state if self.__state is not None else "N/A"
        )

    def __str__(self) -> str:
        return "Host [%s] SerialNumber [%s] ApiVersion [%s] State [%s]" % (
            self.__host if self.__host is not None else "N/A",
            self.__serial_number if self.__serial_number is not None else "N/A",
            self.__api_version if self.__api_version is not None else "N/A",
            self.__state if self.__state is not None else "N/A"
        )

    async def __ainit__(self, *args, **kwargs) -> NoReturn:
        await super().__ainit__(*args, **kwargs)
        await self.__initialize()

    async def __adel__(self) -> None:
        await self.__terminate()

    async def __aenter__(self) -> 'RemootioClient':
        await self.__initialize()
        
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.__terminate()

    # ----------------------------
    # Initialization & termination
    # ----------------------------

    async def __initialize(self) -> bool:
        self.__logger.info("Initializing this client...")

        self.__initializing = True
        try:
            await self.__invoke_state_change_listeners(StateChange(None, self.state))

            if self.__connection_options.connect_automatically:
                async with self.__lifecycle:
                    try:
                        connecting_task: asyncio.Task = await self.__start_connecting()
                        await self.__lifecycle.wait_for(lambda: self.connected)

                        if connecting_task.exception() is not None:
                            raise connecting_task.exception()

                        if self.connected:
                            await self.__start_tasks()
                    finally:
                        self.__lifecycle.notify_all()
            else:
                self.__do_receive_and_handle_messages = False
                self.__do_send_pings = False
        except BaseException as ex:
            self.__logger.exception("Failed to initialize this client.")
            raise RemootioClientError(self, "Failed to initialize this client.") from ex
        else:
            self.__initialized = True
        finally:
            self.__initializing = False

        return self.__initialized

    async def __wait_for_initializing(self) -> bool:
        while self.__lifecycle.locked() and self.__initializing:
            self.__logger.debug("This client does currently initializing. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(LIFECYCLE_LOCK_DELAY)

        return self.__initialized

    async def __terminate(self) -> bool:
        self.__logger.info("Terminating this client...")

        self.__terminating = True
        try:
            async with self.__lifecycle:
                try:
                    await self.__stop_tasks()
                    await self.remove_state_change_listeners()
                    await self.remove_event_listeners()

                    await self.__start_disconnecting()
                    await self.__lifecycle.wait_for(lambda: not self.connected)

                    await self.__task_store.close()
                finally:
                    self.__lifecycle.notify_all()
        except BaseException as ex:
            self.__logger.warning("Failed to terminate this client.", ex)
        else:
            self.__initialized = False
            self.__terminated = True
        finally:
            self.__terminating = False

        return self.__terminated

    async def __wait_for_terminating(self) -> bool:
        while self.__lifecycle.locked() and self.__terminating:
            self.__logger.debug("This client does currently terminating. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(LIFECYCLE_LOCK_DELAY)

        return self.__terminated

    # --------------------------
    # Connecting & disconnecting
    # --------------------------

    async def __connect(self, handle_connection_error: bool = True) -> ClientWebSocketResponse:
        if not self.connected:
            self.__connecting = True
            try:
                async with self.__lifecycle:
                    try:
                        if self.__ws is not None and not self.__ws.closed and not self.__authenticated:
                            self.__logger.warning(
                                "Living connection to the device will be closed now, because this client isn't "
                                "authenticated by the device.")
                            await self.__start_disconnecting()
                            await self.__lifecycle.wait_for(lambda: not self.connected)

                        if self.__ws is None:
                            # Establish connection to the device
                            self.__logger.info("Establishing connection to the device...")
                            try:
                                self.__ws = await self.__client_session.ws_connect(
                                    f"ws://{self.__connection_options.host}:8080/")
                                self.__logger.info("Connection to the device has been established successfully.")
                            except BaseException as ex:
                                self.__ws = None
                                if handle_connection_error:
                                    self.__logger.exception("Unable to establish connection to the device.")
                                else:
                                    raise RemootioClientConnectionEstablishmentError(
                                        self, "Unable to establish connection to the device.") from ex

                            if self.__is_ws_connected(self.__ws):
                                # Authenticate this client by the device
                                await self.__authenticate(self.__ws)

                        if self.__is_ws_connected(self.__ws) and self.__authenticated:
                            # Say hello to the device
                            await self.__say_hello(self.__ws)

                        if self.connected:
                            await self.__invoke_event_listeners(Event(EventSource.CLIENT, EventType.CONNECTED, None))
                    finally:
                        self.__lifecycle.notify_all()
            finally:
                self.__connecting = False

        return self.__ws

    async def __wait_for_connecting(self) -> bool:
        while self.__lifecycle.locked() and self.__connecting:
            self.__logger.debug("This client does currently connecting to the device. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(LIFECYCLE_LOCK_DELAY)

        return self.connected

    async def __authenticate(self, ws: ClientWebSocketResponse) -> NoReturn:
        self.__logger.info("Authenticating this client by the device...")

        self.__authenticating = True
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
        finally:
            self.__authenticating = False

    async def __say_hello(self, ws: ClientWebSocketResponse):
        self.__logger.info("Saying hello to the device...")

        if not self.__said_hello:
            self.__saying_hello = True
            try:
                await self.__send_frame(HelloFrame(), ws)

                self.__said_hello = True
            except BaseException as ex:
                self.__logger.exception("This client is unable to say hello to the device because of an error.")
                raise RemootioClientError(
                    self, "This client is unable to say hello to the device because of an error.") from ex
            finally:
                self.__saying_hello = False

        return self.connected

    async def __wait_for_said_hello(self):
        while not self.__said_hello:
            self.__logger.debug("This client has not yet said hello to the device. "
                                "Waiting until it has sid hello.")
            await asyncio.sleep(WAITING_FOR_SAID_HELLO_DELAY)

    async def __wait_for_device_has_answered_to_hello(self):
        while not self.__device_answered_to_hello:
            self.__logger.debug("The device has not yet answered to the hello from this client. "
                                "Waiting until it has answered.")
            await asyncio.sleep(WAITING_FOR_DEVICE_ANSWERED_TO_HELLO_DELAY)

    async def __disconnect(self) -> NoReturn:
        self.__disconnecting = True
        try:
            async with self.__lifecycle:
                try:
                    if self.__ws is not None and not self.__ws.closed:
                        try:
                            self.__logger.info("Disconnecting from the device...")
                            await self.__ws.close()
                        except BaseException:
                            self.__logger.warning("Unable to disconnect from the device because of an error.",
                                                  exc_info=(self.__logger.getEffectiveLevel() == logging.DEBUG))

                    self.__session_key = None
                    self.__last_action_id = None
                    self.__said_hello = False
                    self.__authenticated = False
                    self.__ws = None

                    if not self.connected:
                        await self.__invoke_event_listeners(Event(EventSource.CLIENT, EventType.DISCONNECTED, None))
                finally:
                    self.__lifecycle.notify_all()
        finally:
            self.__disconnecting = False

    async def __wait_for_disconnecting(self) -> bool:
        while self.__lifecycle.locked() and self.__disconnecting:
            self.__logger.debug("This client does currently disconnecting from the device. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(LIFECYCLE_LOCK_DELAY)

        return not self.connected

    # ---------------------
    # Tasks & task handling
    # ---------------------

    async def __start_tasks(self, force: bool = False) -> bool:
        result: bool = await self.__start_receiving_and_handling_of_messages(force) and \
                       await self.__start_sending_of_pings(force)

        if result:
            await self.__invoke_event_listeners(Event(EventSource.CLIENT, EventType.TASKS_STARTED, None))

        return result

    async def __start_receiving_and_handling_of_messages(self, force: bool = False) -> bool:
        result: bool = False

        if force:
            self.__do_receive_and_handle_messages = True

        if self.connected and self.__do_receive_and_handle_messages and not self.__receives_and_handles_messages:
            self.__task_store \
                .create_task(self.__receive_and_handle_messages(), name=TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER) \
                .add_done_callback(self.__handle_task_done)
            result = await self.__wait_for_task_started(TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER)

        return result

    async def __start_sending_of_pings(self, force: bool = False) -> bool:
        result: bool = False

        if force:
            self.__do_send_pings = True

        if self.connected and self.__do_send_pings and not self.__sends_pings:
            self.__task_store \
                .create_task(self.__send_pings(), name=TASK_NAME_PING_SENDER) \
                .add_done_callback(self.__handle_task_done)
            result = await self.__wait_for_task_started(TASK_NAME_PING_SENDER)

        return result

    async def __start_connecting(self) -> asyncio.Task:
        result: asyncio.Task = self.__task_store \
            .create_task(self.__connect(False), name=TASK_NAME_CONNECTOR)
        result.add_done_callback(self.__handle_task_done)

        await self.__wait_for_task_started(TASK_NAME_CONNECTOR)

        return result

    async def __start_disconnecting(self) -> asyncio.Task:
        result: asyncio.Task = self.__task_store \
            .create_task(self.__disconnect(), name=TASK_NAME_DISCONNECTOR)
        result.add_done_callback(self.__handle_task_done)

        await self.__wait_for_task_started(TASK_NAME_DISCONNECTOR)

        return result

    async def __wait_for_task_started(self, task_name: str) -> bool:
        result: bool = False

        if task_name == TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER:
            while not self.__receives_and_handles_messages:
                self.__logger.debug("Task to receive and handle messages isn't started yet. "
                                    "Waiting as long as it is started.")
                await asyncio.sleep(TASK_STARTED_DELAY)

            result = self.__receives_and_handles_messages
        elif task_name == TASK_NAME_PING_SENDER:
            while not self.__sends_pings:
                self.__logger.debug("Task to sending PINGs isn't started yet. "
                                    "Waiting as long as it is started.")
                await asyncio.sleep(TASK_STARTED_DELAY)

            result = self.__sends_pings
        elif task_name == TASK_NAME_CONNECTOR:
            while not self.__connecting:
                self.__logger.debug("Task to connect to the device isn't started yet. "
                                    "Waiting as long as it is started.")
                await asyncio.sleep(TASK_STARTED_DELAY)

            result = self.__connecting
        elif task_name == TASK_NAME_DISCONNECTOR:
            while not self.__disconnecting:
                self.__logger.debug("Task to disconnect from the device isn't started yet. "
                                    "Waiting as long as it is started.")
                await asyncio.sleep(TASK_STARTED_DELAY)

            result = self.__disconnecting

        return result

    async def __stop_tasks(self) -> bool:
        self.__do_receive_and_handle_messages = False
        self.__do_send_pings = False

        result: bool = await self.__stop_task(TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER) and \
            await self.__stop_task(TASK_NAME_PING_SENDER)

        if result:
            await self.__invoke_event_listeners(Event(EventSource.CLIENT, EventType.TASKS_STOPPED, None))

        return result

    async def __stop_task(self, name: str) -> bool:
        result: bool = False

        task: Optional[asyncio.Task] = self.__get_task(name)
        if task is not None:
            task.cancel()
            result = await asyncio.wait_for(self.__wait_for_task_stopped(task), TASK_STOPPED_TIMEOUT)

        return result

    async def __wait_for_task_stopped(self, task: [str | asyncio.Task]) -> bool:
        result: bool = False

        if isinstance(task, str):
            task = self.__get_task(task)

        if task is not None:
            while not task.done():
                self.__logger.debug("Task \"%s\" isn't sopped yet. Waiting as long as it is stopped.", task.get_name())
                await asyncio.sleep(TASK_STOPPED_DELAY)

            result = task.done()

        return result

    def __get_task(self, name: str) -> Optional[asyncio.Task]:
        result: Optional[asyncio.Task] = None

        for task in self.__task_store.tasks:
            if task.get_name() == name:
                result = task
                break

        return result

    async def __send_pings(self) -> NoReturn:
        try:
            while True:
                if self.__do_send_pings:
                    self.__sends_pings = True

                    ws: Optional[ClientWebSocketResponse] = None
                    try:
                        ws = await self.__connect()
                    except BaseException:
                        self.__logger.warning("Sending PINGs by this client will be delayed "
                                              "because connection to the device can't be established.")
                        await asyncio.sleep(PING_SENDER_HEARTBEAT)
                        continue

                    if self.__is_ws_connected(ws):
                        try:
                            await self.__send_frame(PingFrame(), ws)
                        except BaseException:
                            self.__logger.warning("Failed to send PING.")
                    else:
                        self.__logger.warning("Sending PINGs by this client will be delayed "
                                              "because connection to the device can't be established.")

                    await asyncio.sleep(PING_SENDER_HEARTBEAT)
                else:
                    self.__logger.info("Sending PINGs by this client will be now stopped.")
                    return
        except CancelledError:
            self.__logger.info("Sending PINGs by this client will be now stopped because of cancelling the task.")
            raise
        except BaseException:
            self.__logger.exception("Sending PINGs by this client will be now stopped because of an error.")
            raise

    async def __receive_and_handle_messages(self) -> NoReturn:
        try:
            while True:
                if self.__do_receive_and_handle_messages:
                    self.__receives_and_handles_messages = True

                    ws: Optional[ClientWebSocketResponse] = None
                    try:
                        ws = await self.__connect()
                    except BaseException:
                        self.__logger.warning("Receiving and handling of messages by this client will be delayed "
                                              "because connection to the device can't be established.")
                        await asyncio.sleep(MESSAGE_HANDLER_HEARTBEAT)
                        continue

                    if self.__is_ws_connected(ws):
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
                    self.__logger.info("Receiving and handling of messages by this client will be now stopped.")
                    return
        except CancelledError:
            self.__logger.info("Receiving and handling of messages by this client will be now stopped "
                               "because of cancelling the task.")
            raise
        except BaseException:
            self.__logger.exception("Receiving and handling of messages by this client will be now stopped"
                                    "because of an error.")
            raise

    def __handle_task_done(self, task: asyncio.Task) -> NoReturn:
        if task.get_name() == TASK_NAME_MESSAGE_RECEIVER_AND_HANDLER:
            self.__receives_and_handles_messages = False
        elif task.get_name() == TASK_NAME_PING_SENDER:
            self.__sends_pings = False
        elif task.get_name() == TASK_NAME_CONNECTOR:
            self.__connecting = False
        elif task.get_name() == TASK_NAME_DISCONNECTOR:
            self.__disconnecting = False

    # -------------------------------
    # Sending of frames to the device
    # -------------------------------

    async def __send_frame(
            self, frame: AbstractJSONHolderFrame, ws: Optional[ClientWebSocketResponse] = None) -> NoReturn:
        if not self.__terminated:
            if ws is None:
                ws = await self.__connect()

            if self.__is_ws_connected(ws):
                if isinstance(frame, HelloFrame) or isinstance(frame, PingFrame) or self.__authenticating:
                    pass
                else:
                    await self.__wait_for_said_hello()
                    await self.__wait_for_device_has_answered_to_hello()

                if self.__logger.getEffectiveLevel() == logging.DEBUG:
                    self.__logger.info("Sending frame... Frame [%s]", json.dumps(frame.json))
                else:
                    self.__logger.info("Sending frame...")

                try:
                    if isinstance(frame, HelloFrame) and self.__said_hello:
                        self.__logger.warning("Frame will be don't sent because this client has already said hello "
                                              "to the device.")
                    else:
                        await ws.send_json(frame.json)
                except BaseException as ex:
                    self.__logger.error("Sending of frame has been failed.",
                                        exc_info=(self.__logger.getEffectiveLevel() == logging.DEBUG))

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

    # ----------------------------------------
    # Handling frames received from the device
    # ----------------------------------------

    async def __handle_error_frame(self, frame: ErrorFrame) -> NoReturn:
        self.__logger.debug("Handling received ErrorFrame...")
        self.__logger.error("An error has been occurred on the device. Type [%s]" % frame.error_type)
        if frame.error_type == ErrorType.CONNECTION_TIMEOUT:
            await self.__disconnect()
        elif frame.error_type == ErrorType.AUTHENTICATION_TIMEOUT:
            await self.__disconnect()
        elif frame.error_type == ErrorType.AUTHENTICATION_TIMEOUT:
            await self.__disconnect()
        elif frame.error_type == ErrorType.ALREADY_AUTHENTICATED:
            self.__authenticated = True

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

                await self.__invoke_event_listeners(Event(frame.event_source, frame.event_type, frame.key))
            else:
                self.__logger.debug(
                    "An event has been occurred on the device but before this client has been connected to the device. "
                    "EventType [%s] Key [%s] EventSource [%s]" % (frame.event_type, frame.key, frame.event_source))
        else:
            self.__logger.debug("An unsupported event has been occurred on the device.")

    async def __handle_connection_closed(self):
        await self.__disconnect()

    # -----------------------------
    # Frame encryption & decryption
    # -----------------------------

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

    # ----------------------
    # State change listeners
    # ----------------------

    async def __invoke_state_change_listeners(self, state_change: StateChange) -> NoReturn:
        await self.__wait_for_modifying_state_change_listeners()

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

    async def __wait_for_modifying_state_change_listeners(self):
        while self.__modifying_state_change_listeners_lock.locked():
            self.__logger.debug("List of state change listeners will be currently modified. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(ADDING_STATE_CHANGE_LISTENER_LOCK_DELAY)

    # ---------------
    # Event listeners
    # ---------------

    async def __invoke_event_listeners(self, event: Event) -> NoReturn:
        await self.__wait_for_modifying_event_listeners()

        event_listeners = self.__event_listeners[:]

        if len(event_listeners) > 0:
            self.__logger.debug("Invoking event listeners... Event [%s]", event)

            for listener in event_listeners:
                try:
                    await listener.execute(self, event)
                except BaseException:
                    self.__logger.warning("An error has been occurred during invoking the event listener.",
                                          exc_info=True)

    async def __wait_for_modifying_event_listeners(self):
        while self.__modifying_event_listeners_lock.locked():
            self.__logger.debug("List of event listeners will be currently modified. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(ADDING_EVENT_LISTENERS_LOCK_DELAY)

    # --------------
    # State handling
    # --------------

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

    # --------------
    # Helper methods
    # --------------

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

    async def __wait_for_updating_last_action_id(self):
        while self.__updating_last_action_id_lock.locked():
            self.__logger.debug("This client is currently updating the last action id. "
                                "Waiting until the progress is done.")
            await asyncio.sleep(UPDATING_LAST_ACTION_ID_LOCK_DELAY)

    async def __trigger(self, action_type: ActionType) -> NoReturn:
        if await self.__wait_for_terminating():
            raise RemootioClientError(
                self, "Unable to send frame because this client is already terminated. ActionType [%s]" % action_type)

        await self.__wait_for_initializing()

        if not self.connected:
            await self.connect()

        action_id: int = await self.__calculate_next_action_id()
        frame: ActionRequestFrame = ActionRequestFrame(action_id, action_type)

        await self.__encrypt_and_send_frame(frame)

    # ----------------------------------------
    # Public accessible methods and properties
    # ----------------------------------------

    @property
    def terminated(self) -> bool:
        """
        Determines whether this client is terminated. That mains that background tasks created by this client are
        stopped and the WebSocket connection to the device is closed.
        :return: ``true`` if this client is terminated, otherwise ``false``
        """
        return self.__terminated

    async def terminate(self) -> bool:
        """
        Terminates this client. After the client is terminated it isn't possible to send any action to the Remootio
        device via it, furthermore the client doesn't receive and handles any messages sent by the Remootio device.
        :return: ``true`` if this client was terminated successfully, otherwise ``false``
        """
        result: bool = await self.__wait_for_terminating()

        if not result:
            result = await self.__terminate()

        return result

    def __is_ws_connected(self, ws: Optional[ClientWebSocketResponse] = None):
        if ws is None:
            ws = self.__ws

        return ws is not None and not ws.closed

    @property
    def connected(self) -> bool:
        """
        Determines whether this client is connected to the device. That mains a WebSocket connection is successfully
        established to the device, the client was successfully authenticated by the device, furthermore the client
        has said hello to the device.
        :return: ``true`` if this client is connected to the device, otherwise ``false``
        """
        return self.__is_ws_connected() and self.__authenticated and self.__said_hello

    async def connect(self) -> bool:
        """
        Connects this client to the device.
        :return: ``true`` if this client is connected to the device, otherwise ``false``
        """

        await self.__wait_for_initializing()
        await self.__wait_for_terminating()
        await self.__wait_for_disconnecting()

        result: bool = await self.__wait_for_connecting()

        if not self.__terminated and self.__initialized and not result:
            await self.__connect(False)
            await self.__start_tasks(True)

        return self.connected

    async def disconnect(self) -> bool:
        """
        Disconnects this client from the device.
        :return: ``true`` if this client is disconnected from the device, otherwise ``false``
        """

        await self.__wait_for_initializing()
        await self.__wait_for_terminating()
        await self.__wait_for_connecting()

        result: bool = await self.__wait_for_disconnecting()

        if not self.__terminated and self.__initialized and not result:
            await self.__stop_tasks()
            await self.__disconnect()

        return not self.connected

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
    def host(self) -> str:
        """
        :return: IP address or host name of the device
        """
        return self.__host

    @property
    def serial_number(self) -> Optional[str]:
        """
        :return: Serial number of the device
        """
        return self.__serial_number

    @property
    def api_version(self) -> int:
        """
        :return: API version supported by the device
        """
        return self.__api_version

    @property
    def state(self) -> State:
        """
        :return: last known state of the device
        """
        return self.__state

    @property
    def uptime(self) -> Optional[int]:
        """
        :return: Uptime of the device since last start/restart
        """
        return self.__uptime

    @property
    def said_hello(self):
        """
        Determines whether this client has already said hello during its initialization to the device and the device
        answered to it. This must be done before sending any action to the device.
        If any action should be sent using this client to the device before the client says hello to the device and the
        device answers to it, then the sending of the action will be paused as so long as the before described progress
        isn't done.
        :return: ``true`` if this client has already said hello to the device and the device answered,
                 otherwise ``false``
        """
        return self.__said_hello and self.__device_answered_to_hello

    async def add_state_change_listener(self, state_change_listener: Listener[StateChange]) -> bool:
        """
        Adds the given ``aioremootio.listeners.Listener[aioremootio.models.StateChange]`` to the list of listeners to be
        invoked if the state of the device changes.
        :param state_change_listener: the ``aioremootio.listeners.Listener[aioremootio.models.StateChange]``
        :return: ``true`` if the listener was successfully added to the list of listeners, otherwise ``false``
        """

        result: bool = False

        async with self.__modifying_state_change_listeners_lock:
            if state_change_listener is not None and state_change_listener not in self.__state_change_listeners:
                self.__state_change_listeners.append(state_change_listener)
                result = True

        return result

    async def remove_state_change_listener(self, state_change_listener: Listener[StateChange]) -> bool:
        """
        Removes the given ``aioremootio.listeners.Listener[aioremootio.models.StateChange]`` from the list of listeners
        to be invoked if the state of the device changes.
        :param state_change_listener: the ``aioremootio.listeners.Listener[aioremootio.models.StateChange]``
        :return: ``true`` if the listener was successfully removed from the list of listeners, otherwise ``false``
        """

        result: bool = False

        async with self.__modifying_state_change_listeners_lock:
            if state_change_listener is not None and state_change_listener in self.__state_change_listeners:
                self.__state_change_listeners.remove(state_change_listener)
                result = True

        return result

    def has_state_change_listener(self, state_change_listener: Listener[StateChange]) -> bool:
        """
        Determines whether the given ``aioremootio.listeners.Listener[aioremootio.models.StateChange]`` is already
        in the list of listeners to be invoked if the state of the device changes.
        :param state_change_listener: the ``aioremootio.listeners.Listener[aioremootio.models.StateChange]``
        :return: ``true`` if the listener is already in the list of listeners, otherwise ``false``
        """
        return state_change_listener in self.__state_change_listeners

    async def remove_state_change_listeners(self) -> int:
        """
        Removes all ``aioremootio.listeners.Listener[aioremootio.models.StateChange]`` instances from the list of
        listeners to be invoked if the state of the device changes.
        :return: number of removed ``aioremootio.listeners.Listener[aioremootio.models.StateChange]`` instances
        """

        result: int = 0

        if len(self.__state_change_listeners) > 0:
            result = len(self.__state_change_listeners)

            async with self.__modifying_state_change_listeners_lock:
                self.__state_change_listeners.clear()

        return result

    async def add_event_listener(self, event_listener: Listener[Event]) -> bool:
        """
        Adds the given ``aioremootio.listeners.Listener[aioremootio.models.Event]`` to the list of listeners to be
        invoked if an event occurs on the device that is supported by the client.
        :param event_listener: the ``aioremootio.listeners.Listener[aioremootio.models.Event]``
        :return: ``true`` if the listener was successfully added to the list of listeners, otherwise ``false``
        """

        result: bool = False

        async with self.__modifying_event_listeners_lock:
            if event_listener is not None and event_listener not in self.__event_listeners:
                self.__event_listeners.append(event_listener)
                result = True

        return result

    async def remove_event_listener(self, event_listener: Listener[Event]) -> bool:
        """
        Removes the given ``aioremootio.listeners.Listener[aioremootio.models.Event]`` from the list of listeners
        to be invoked if event occurs on the device that is supported by the client.
        :param event_listener: the ``aioremootio.listeners.Listener[aioremootio.models.Event]``
        :return: ``true`` if the listener was successfully removed from the list of listeners, otherwise ``false``
        """

        result: bool = False

        async with self.__modifying_event_listeners_lock:
            if event_listener is not None and event_listener in self.__event_listeners:
                self.__event_listeners.remove(event_listener)
                result = True

        return result

    def has_event_listener(self, event_listener: Listener[Event]) -> bool:
        """
        Determines whether the given ``aioremootio.listeners.Listener[aioremootio.models.Event]`` is already
        in the list of listeners to be invoked if an event occurs on the device that is supported by the client.
        :param event_listener: the ``aioremootio.listeners.Listener[aioremootio.models.StateChange]``
        :return: ``true`` if the listener is already in the list of listeners, otherwise ``false``
        """
        return event_listener in self.__event_listeners

    async def remove_event_listeners(self) -> int:
        """
        Removes all ``aioremootio.listeners.Listener[aioremootio.models.Event]`` instances from the list of
        listeners to be invoked if an event occurs on the device that is supported by the client.
        :return: number of removed ``aioremootio.listeners.Listener[aioremootio.models.Event]`` instances
        """

        result: int = 0

        if len(self.__event_listeners) > 0:
            result = len(self.__event_listeners)

            async with self.__modifying_event_listeners_lock:
                self.__event_listeners.clear()

        return result
