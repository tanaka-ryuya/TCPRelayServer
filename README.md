# TCP Relay Server

## Overview
The **TCP Relay Server** is a Python-based TCP relay tool that allows forwarding data between a source and a destination. It supports multiple modes, automatic reconnection, and optional data dumping for debugging.

## Features
- Supports **four relay modes**:
  - `connect-listen`: Connect to an upstream server and listen for downstream clients.
  - `listen-connect`: Listen for an upstream connection and connect to a downstream server.
  - `connect-connect`: Connect to both upstream and downstream servers.
  - `listen-listen`: Listen for both upstream and downstream connections.
- **Automatic reconnection** when a connection is lost.
- **Multiple client support** in `connect-listen` and `listen-listen` modes.
- **Data dumping** option to output transmitted data to stdout.
- **Graceful shutdown** using signal handling.

## Requirements
- Python 3.x

## Installation
Clone the repository and install any required dependencies if necessary:
```sh
$ git clone https://github.com/yourrepo/tcp-relay-server.git
$ cd tcp-relay-server
```

## Usage
Run the relay server with the required parameters:
```sh
$ python relay_server.py <source_address>:<source_port> <destination_address>:<destination_port> --mode <mode> [--dump]
```

### Arguments
| Argument | Description |
|----------|-------------|
| `<source_address>:<source_port>` | The address and port of the upstream source. |
| `<destination_address>:<destination_port>` | The address and port of the downstream destination. |
| `--mode` | Relay mode (one of `connect-listen`, `listen-connect`, `connect-connect`, `listen-listen`). Default: `connect-listen`. |
| `--dump` | Optional. Prints relayed data to stdout. |

### Example Usage
#### Example 1: Connect to an upstream server and listen for clients
```sh
$ python relay_server.py 127.0.0.1:5000 0.0.0.0:6000 --mode connect-listen
```
This setup connects to an upstream server at `127.0.0.1:5000` and listens for client connections on port `6000`.

#### Example 2: Listen for an upstream connection and connect to a downstream server
```sh
$ python relay_server.py 0.0.0.0:5000 192.168.1.100:6000 --mode listen-connect
```
Here, the relay server waits for an upstream connection on port `5000` and forwards the data to `192.168.1.100:6000`.

#### Example 3: Connect to both upstream and downstream
```sh
$ python relay_server.py 192.168.1.50:5000 192.168.1.100:6000 --mode connect-connect
```
This setup directly connects to both an upstream server at `192.168.1.50:5000` and a downstream server at `192.168.1.100:6000`.

#### Example 4: Listen for both upstream and downstream connections
```sh
$ python relay_server.py 0.0.0.0:5000 0.0.0.0:6000 --mode listen-listen
```
Here, the relay server listens for both upstream connections on `5000` and downstream connections on `6000`.

## Signal Handling
The relay server can be stopped gracefully using:
- `CTRL+C` (SIGINT)
- `kill <PID>` (SIGTERM)

Upon termination, all sockets will be closed properly.

## License
MIT License

## Author
[Tanaka RYUYA](https://github.com/tanaka-ryuya/TCPRelayServer)

