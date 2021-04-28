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

ARGUMENT_FRAME_SENDER = "frame_sender"
ARGUMENT_HEARTBEAT = "heartbeat"
ARGUMENT_LOGGER = "logger"

CONNECTION_OPTION_KEY_IP_ADDRESS = "ip_address"
CONNECTION_OPTION_KEY_API_SECRET_KEY = "api_secret_key"
CONNECTION_OPTION_KEY_API_AUTH_KEY = "api_auth_key"
DEVICE_CONNECTING_MAXIMUM_ATTEMPTS = 10
DEVICE_CONNECTING_HEARTBEAT = 2.5
MESSAGE_HANDLER_HEARTBEAT = 10
PING_SENDER_HEARTBEAT = 60
AUTHENTICATOR_HEARTBEAT = MESSAGE_HANDLER_HEARTBEAT
ENCODING = "latin-1"
