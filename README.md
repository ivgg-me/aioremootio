# aioremootio - An asynchronous API client library for Remootio

_aioremootio_ is an asynchronous API client library for [Remootio](https://remootio.com/) written in Python 3 and 
based on [asyncio](https://docs.python.org/3/library/asyncio.html) and [aiohttp](https://pypi.org/project/aiohttp/).

## Supported functionalities of the device

With this client library is currently possible to listen to state changes of a [Remootio](https://remootio.com/) device, 
to listen to some events triggered by it, furthermore to operate the gate or garage door connected to it.

This client library supports currently the listening to following kind of events triggered by the device:
* `STATE_CHANGE` which is triggered by the device when its state changes
* `RELAY_TRIGGER` which is triggered by the device when its control output has been triggered to operate the 
  connected gate or garage door
* `LEFT_OPEN` which is triggered by the device when the connected gate or garage door has been left open

## Running the bundled example

To run the bundled example `example.py` you must 
1. enable the API on your [Remootio](https://remootio.com/) device to get the _API Secret Key_ and _API Auth Key_ of 
   it, and
2. add the source folder `./src` of this library to your `PYTHONPATH`.

About enabling the API on your device please consult the
[Remootio Websocket API documentation](https://github.com/remootio/remootio-api-documentation).

After the two steps described above you can run the bundled example `example.py` with the argument `--help` to show the 
usage information.

```
python example.py --help
```

## Running the bundled tests

To run the bundled tests you must create the `.\remootio_devices.configuration.json` file with a content according 
to the following template.

```
{
    "ip_address": "IP-ADDRESS-OF-YOUR-DEVICE",
    "api_secret_key": "API-SECRET-KEY-OF-YOUR-DEVICE",
    "api_auth_key": "API-AUTH-KEY-OF-YOUR-DEVICE",
    "api_version": API-VERSION-OF-YOUR-DEVICE
}
```

You can get the API version of your device based on the firmware version of it from the
[Remootio Websocket API documentation](https://github.com/remootio/remootio-api-documentation).

---

Copyright &copy; 2021 Gergö Gabor Ilyes-Veisz. 
Licensed under the [Apache License, Version 2.0](http://www.apache.org/licenses/LICENSE-2.0)