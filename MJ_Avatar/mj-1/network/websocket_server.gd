extends Node

## ============================================================
## MJ Avatar — WebSocket Server
## Listens on localhost:8765 for JSON state commands from Python.
## ============================================================

signal state_received(state_name: String)
signal message_received(raw_json: String)
signal client_connected()
signal client_disconnected()

const PORT: int = 8765
const HOST: String = "localhost"

var _server: WebSocketServer = WebSocketServer.new()
var _is_running: bool = false
var _client_id: int = -1


func _ready() -> void:
	_server.connect("client_connected", _on_client_connected)
	_server.connect("client_disconnected", _on_client_disconnected)
	_server.connect("data_received", _on_data_received)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

## Start the WebSocket server.
func start_server(port: int = PORT) -> bool:
	if _is_running:
		stop_server()

	var err: int = _server.listen(port, PackedStringArray(), false)
	if err != OK:
		push_error("WebSocketServer: failed to listen on port ", port, " — error ", err)
		return false

	_is_running = true
	print("WebSocketServer: listening on ws://", HOST, ":", port)
	return true


## Stop the server.
func stop_server() -> void:
	if _is_running:
		_server.stop()
		_is_running = false
		_client_id = -1
		print("WebSocketServer: stopped")


## Send a JSON message to the connected client.
func send_json(data: Dictionary) -> bool:
	if _client_id < 0:
		return false
	var json_str: String = JSON.stringify(data)
	var err: int = _server.get_peer(_client_id).put_packet(json_str.to_utf8_buffer())
	return err == OK


## Check if a client is connected.
func has_client() -> bool:
	return _client_id >= 0


## Check if server is running.
func is_running() -> bool:
	return _is_running


# ------------------------------------------------------------------
# Signal Handlers
# ------------------------------------------------------------------

func _on_client_connected(id: int) -> void:
	_client_id = id
	print("WebSocketServer: client connected — id=", id)
	client_connected.emit()


func _on_client_disconnected(id: int, was_clean_close: bool) -> void:
	if id == _client_id:
		_client_id = -1
	print("WebSocketServer: client disconnected — id=", id, " clean=", was_clean_close)
	client_disconnected.emit()


func _on_data_received(id: int) -> void:
	if id != _client_id:
		return

	var peer: WebSocketPeer = _server.get_peer(id)
	if peer.get_available_packet_count() == 0:
		return

	var packet: PackedByteArray = peer.get_packet()
	var raw: String = packet.get_string_from_utf8()
	message_received.emit(raw)

	# Parse JSON
	var json: JSON = JSON.new()
	var parse_err: Error = json.parse(raw)
	if parse_err != OK:
		push_warning("WebSocketServer: invalid JSON — ", raw)
		return

	var data: Variant = json.data
	if typeof(data) != TYPE_DICTIONARY:
		push_warning("WebSocketServer: expected JSON object, got ", typeof(data))
		return

	var dict: Dictionary = data as Dictionary
	if dict.has("state"):
		var state_name: String = str(dict["state"]).to_upper()
		state_received.emit(state_name)
	elif dict.has("animation"):
		# Legacy support — treat as state name
		var anim_name: String = str(dict["animation"]).to_upper()
		state_received.emit(anim_name)


func _process(_delta: float) -> void:
	if _is_running:
		_server.poll()

