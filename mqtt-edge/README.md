# MQTT Edge Forwarding Prototype

This directory contains an experimental MQTT edge broker that filters incoming messages using a Mosquitto plugin and forwards approved data to a main broker through a FIFO queue.

## Directory layout
- `config/` – Mosquitto configurations that load the plugin.
- `plugin/` – C source and Makefile for building `simple_edge_plugin_2.so`.
- `forwarder/` – programs and scripts that read the FIFO and publish to the main broker.
- `logs/` – default location for plugin and forwarder logs (created at runtime).
- `setup_ip_isolation.sh` – creates an isolated network namespace for the forwarder.
- `test_mqtt_connection.sh` – verifies connectivity from the isolated namespace.

## Prerequisites
- Mosquitto with plugin support
- GCC, `pkg-config`, and development headers for `libmosquitto`, `libcurl`, and `json-c`
- Paho MQTT C client (`libpaho-mqtt3c`), `jq`, and `mosquitto-clients`
- Root privileges to create network namespaces

## Build and install the plugin
```bash
cd plugin
make               # builds simple_edge_plugin_2.so from time_delta_edge_plugin_fifo.c
sudo make install  # copies the plugin to /usr/lib/mosquitto/plugins/
```

## Set up network isolation
Run once to create namespace `ns_forwarder` with IP `192.168.100.2`:
```bash
sudo ./setup_ip_isolation.sh
```
Test the setup:
```bash
sudo ./test_mqtt_connection.sh
```

## Run the edge broker
Start Mosquitto with the provided configuration which loads the plugin and listens on port 1883:
```bash
mosquitto -c config/mosquitto.conf -v
```
The plugin:
1. receives messages,
2. queries the policy API,
3. appends log entries to `logs/edge_plugin.csv`, and
4. enqueues approved messages as JSON lines into `forwarder/message_queue.fifo`.

## Forward queued messages
Run a forwarder inside the isolated namespace to publish to the main broker (`192.168.254.139:1884`):
```bash
sudo ip netns exec ns_forwarder ./forwarder/forwarder_paho
# or use the shell implementation
sudo ip netns exec ns_forwarder ./forwarder/isolated_forwarder.sh
```
The forwarder reads from `forwarder/message_queue.fifo` and logs results to `logs/forwarder_performance.csv`.

## Notes
Paths in the source files assume the project resides at `/home/jason/mqtt-edge`. Update the macros or create the expected directories/symlinks if your environment differs.
