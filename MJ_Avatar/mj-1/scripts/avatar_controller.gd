extends Node3D

## ============================================================
## MJ Avatar — Main Controller (Orchestrator)
## Wires together StateMachine, AnimationManager, WebSocket,
## and future subsystems (lip sync, eye look-at, speech bubble).
## ============================================================

signal avatar_state_changed(state_name: String)
signal avatar_woke_up()
signal model_loaded(success: bool)

# ── Subsystem references (injected in _ready) ──────────────
var state_machine: Node
var animation_mgr: Node
var websocket: Node
var config: Node

@onready var anim_player: AnimationPlayer = $AnimationPlayer
@onready var anim_tree: AnimationTree = $AnimationTree
@onready var avatar_model: Node3D = $Mesh

# ── Animation file paths (FBX imported scenes) ────────────
const ANIMATION_SCENES: Dictionary = {
	"Standing Idle":   "res://Standing Idle.fbx",
	"Arm Stretching":  "res://Arm Stretching.fbx",
	"Male Laying Pose": "res://Male Laying Pose.fbx",
	"Excited":         "res://Excited.fbx",
	"Listening To Music": "res://Listening To Music.fbx",
	"Thinking":        "res://Thinking.fbx",
	"Talking On Phone": "res://Talking On Phone.fbx",
	"Praying":         "res://Praying.fbx",
}

# ── Idle config (read from config.gd at runtime) ──────────
var _stretch_time: float = 300.0
var _sleep_time: float = 600.0

# ── Wake system ────────────────────────────────────────────
var _wake_pending: bool = false
var _wake_anim_done: bool = false
var _pending_state_after_wake: String = ""


func _ready() -> void:
	# ── Load config singleton if available ───────────────
	if Engine.has_singleton("Config"):
		config = Engine.get_singleton("Config")
		_stretch_time = config.get("IDLE_STRETCH_TIME", 300.0)
		_sleep_time = config.get("IDLE_SLEEP_TIME", 600.0)

	# ── Load the 3D model and animations ──────────────────
	_load_model_and_animations()

	# ── Setup subsystems ─────────────────────────────────
	_setup_state_machine()
	_setup_animation_manager()
	_setup_websocket()
	_setup_window()

	# ── Start in IDLE ────────────────────────────────────
	state_machine.transition_to(state_machine.State.IDLE)


# ------------------------------------------------------------------
# Model & Animation Loading
# ------------------------------------------------------------------

func _load_model_and_animations() -> void:
	# The GLB model is already instanced in the scene as a child of $Mesh
	# (via the `instance` property in avatar.tscn). Use it directly.
	var model_root: Node3D = null

	# Check if the GLB is already instanced as a child of avatar_model
	if avatar_model.get_child_count() > 0:
		var first_child: Node = avatar_model.get_child(0)
		if first_child is Node3D:
			model_root = first_child as Node3D
			print("AvatarController: using scene-instanced GLB model: ", model_root.name)
	else:
		# Fallback: try to load assets/mj.glb at runtime
		var glb_path: String = "res://assets/mj.glb"
		var glb_scene: PackedScene = load(glb_path) as PackedScene
		if glb_scene:
			var model: Node3D = glb_scene.instantiate() as Node3D
			if model:
				avatar_model.add_child(model)
				model_root = model
				print("AvatarController: loaded model from ", glb_path)
			else:
				push_warning("AvatarController: assets/mj.glb is not a Node3D")
		else:
			push_warning("AvatarController: could not load ", glb_path,
				" — trying VRM fallback")
			# Fallback: try the VRM file
			var vrm_path: String = "res://assets/mj.vrm"
			if ResourceLoader.exists(vrm_path):
				var vrm_scene: PackedScene = load(vrm_path) as PackedScene
				if vrm_scene:
					var vrm_model: Node3D = vrm_scene.instantiate() as Node3D
					if vrm_model:
						avatar_model.add_child(vrm_model)
						model_root = vrm_model
						print("AvatarController: loaded model from ", vrm_path)

	# Load all animations from FBX .scn imports into the AnimationPlayer
	_load_animations_from_fbx()

	# CRITICAL FIX: Set AnimationPlayer's root_node to the loaded model's skeleton
	# so animation track bone paths resolve correctly.
	var skeleton: Skeleton3D = _find_skeleton(model_root)
	if skeleton:
		anim_player.root_node = anim_player.get_path_to(skeleton)
		print("AvatarController: AnimationPlayer.root_node set to ", anim_player.root_node)
	else:
		# Fallback: try to find any AnimationPlayer in the loaded model and use its root_node
		var model_anim_player: AnimationPlayer = _find_animation_player(model_root)
		if model_anim_player:
			anim_player.root_node = model_anim_player.root_node
			print("AvatarController: AnimationPlayer.root_node set from model's AnimationPlayer: ", anim_player.root_node)
		else:
			push_warning("AvatarController: No Skeleton3D found in model — using default root_node")
			anim_player.root_node = anim_player.get_path_to(avatar_model)

	# AnimationTree is disabled — no transitions configured in the state machine.
	# Using direct AnimationPlayer playback for reliable animation control.
	if anim_tree:
		anim_tree.active = false
		print("AvatarController: AnimationTree disabled — using AnimationPlayer directly")

	var anim_count: int = anim_player.get_animation_list().size()
	if anim_count == 0:
		push_error("AvatarController: ZERO animations loaded! Check FBX import settings.")
	else:
		print("AvatarController: ", anim_count, " animations ready for playback")


static func _find_skeleton(node: Node) -> Skeleton3D:
	if node is Skeleton3D:
		return node
	for child in node.get_children():
		var found: Skeleton3D = _find_skeleton(child)
		if found:
			return found
	return null


func _load_animations_from_fbx() -> void:
	# Each FBX file is imported as a PackedScene containing a mesh + animation.
	# We extract the animation library from each and add to our AnimationPlayer.
	# CRITICAL: Animation tracks from FBX reference bone paths within the FBX scene
	# hierarchy (e.g. "Armature/Skeleton3D/bone_name"). We must remap these to just
	# "bone_name" so they resolve correctly when root_node is set to the GLB skeleton.
	for anim_name in ANIMATION_SCENES:
		var fbx_path: String = ANIMATION_SCENES[anim_name]
		if not ResourceLoader.exists(fbx_path):
			push_warning("AvatarController: FBX not found — ", fbx_path)
			continue

		var scene: PackedScene = load(fbx_path) as PackedScene
		if not scene:
			push_warning("AvatarController: failed to load ", fbx_path)
			continue

		# Temporarily instance the FBX scene to grab its AnimationPlayer
		var temp: Node = scene.instantiate()
		add_child(temp)

		# Detect the skeleton node path within the FBX hierarchy
		var fbx_skeleton: Skeleton3D = _find_skeleton(temp)
		var fbx_skeleton_path: NodePath = NodePath()
		if fbx_skeleton:
			fbx_skeleton_path = temp.get_path_to(fbx_skeleton)

		# Find an AnimationPlayer in the FBX scene hierarchy
		var fbx_anim_player: AnimationPlayer = _find_animation_player(temp)
		if fbx_anim_player and fbx_anim_player.get_animation_list().size() > 0:
			var fbx_anims: PackedStringArray = fbx_anim_player.get_animation_list()
			for fbx_anim_name in fbx_anims:
				var anim: Animation = fbx_anim_player.get_animation(fbx_anim_name)
				if anim:
					# Deep-copy the animation and remap bone tracks
					var cloned_anim: Animation = _clone_and_remap_animation(anim, fbx_skeleton_path)
					if not anim_player.has_animation(anim_name):
						anim_player.add_animation(anim_name, cloned_anim)
						print("  + Loaded animation: ", anim_name, " (from ", fbx_anim_name, ")")
					else:
						anim_player.remove_animation(anim_name)
						anim_player.add_animation(anim_name, cloned_anim)
		else:
			# If no AnimationPlayer found, check for AnimationLibrary
			var fbx_lib: AnimationLibrary = _find_animation_library(temp)
			if fbx_lib and fbx_lib.get_animation_list().size() > 0:
				var lib_anims: PackedStringArray = fbx_lib.get_animation_list()
				for lib_anim_name in lib_anims:
					var anim: Animation = fbx_lib.get_animation(lib_anim_name)
					if anim:
						var cloned_anim: Animation = _clone_and_remap_animation(anim, fbx_skeleton_path)
						if not anim_player.has_animation(anim_name):
							anim_player.add_animation(anim_name, cloned_anim)
							print("  + Loaded animation: ", anim_name, " (from lib ", lib_anim_name, ")")

		remove_child(temp)
		temp.queue_free()

	print("AvatarController: total animations loaded: ", anim_player.get_animation_list().size())


## Clone an Animation resource and remap its bone track paths.
## FBX tracks reference paths like "Armature/Skeleton3D/bone_name" relative to FBX root.
## We remap these to just "bone_name" so they resolve against root_node (GLB skeleton).
static func _clone_and_remap_animation(src_anim: Animation, fbx_skeleton_path: NodePath) -> Animation:
	var new_anim: Animation = src_anim.duplicate(true)
	var track_count: int = new_anim.get_track_count()

	for i in range(track_count):
		var track_path: NodePath = new_anim.track_get_path(i)
		var path_str: String = track_path

		# If the path contains the skeleton path prefix, strip it
		if fbx_skeleton_path != NodePath() and path_str.begins_with(fbx_skeleton_path):
			# Strip skeleton path prefix + "/" to leave just "bone_name"
			var stripped: String = path_str.trim_prefix(fbx_skeleton_path)
			if stripped.begins_with("/"):
				stripped = stripped.substr(1)
			# The remaining path is just the bone name relative to skeleton
			new_anim.track_set_path(i, NodePath(stripped))
			print("    Remapped track: '", path_str, "' → '", stripped, "'")
		else:
			# If path doesn't contain skeleton prefix, try to extract just the last segment (bone name)
			var last_slash: int = path_str.rfind("/")
			if last_slash >= 0:
				var bone_only: String = path_str.substr(last_slash + 1)
				# Only remap if it looks like a bone name (no sub-path)
				if "/" not in bone_only and not bone_only.is_empty():
					new_anim.track_set_path(i, NodePath(bone_only))
					print("    Remapped track (fallback): '", path_str, "' → '", bone_only, "'")

	return new_anim


static func _find_animation_player(node: Node) -> AnimationPlayer:
	if node is AnimationPlayer:
		return node
	for child in node.get_children():
		var found: AnimationPlayer = _find_animation_player(child)
		if found:
			return found
	return null


static func _find_animation_library(node: Node) -> AnimationLibrary:
	# Check node itself
	if node.has_method("get_animation_list"):
		var lib: AnimationLibrary = node.get("animation_library") as AnimationLibrary
		if lib:
			return lib
	# Check children
	for child in node.get_children():
		var found: AnimationLibrary = _find_animation_library(child)
		if found:
			return found
	return null


func _process(delta: float) -> void:
	# Tick idle logic via state machine
	state_machine.tick_idle(delta)

	# Wake sequence: Excited → Standing Idle → requested state
	if _wake_pending:
		_execute_wake(delta)


# ------------------------------------------------------------------
# Subsystem Setup
# ------------------------------------------------------------------

func _setup_state_machine() -> void:
	state_machine = $StateMachine
	if not state_machine:
		state_machine = Node.new()
		state_machine.set_script(preload("res://scripts/state_machine.gd"))
		add_child(state_machine)
		state_machine.owner = self

	state_machine.state_changed.connect(_on_state_changed)
	state_machine._stretch_time = _stretch_time
	state_machine._sleep_time = _sleep_time


func _setup_animation_manager() -> void:
	animation_mgr = $AnimationManager
	if not animation_mgr:
		animation_mgr = Node.new()
		animation_mgr.set_script(preload("res://scripts/animation_manager.gd"))
		add_child(animation_mgr)
		animation_mgr.owner = self

	# Build anim map from StateMachine's enum → animation name
	var anim_map: Dictionary = {
		"IDLE":      "Standing Idle",
		"LISTENING": "Listening To Music",
		"THINKING":  "Thinking",
		"TALKING":   "Talking On Phone",
		"HAPPY":     "Excited",
		"STRETCH":   "Arm Stretching",
		"SLEEP":     "Male Laying Pose",
		"SORRY":     "Praying",
	}

	var priorities: Dictionary = {
		"SORRY":     100,
		"HAPPY":     90,
		"TALKING":   80,
		"THINKING":  70,
		"LISTENING": 60,
		"STRETCH":   30,
		"SLEEP":     20,
		"IDLE":      10,
	}

	var fade: float = 0.25
	if config:
		fade = config.get("CROSSFADE_TIME", 0.25)

	animation_mgr.setup(anim_player, anim_tree, anim_map, priorities, fade)

	# Connect animation finished → state machine
	animation_mgr.animation_finished.connect(_on_anim_finished)

	# Set random idle animations (from the IDLE-related pool)
	animation_mgr.set_random_idle_anims(["Standing Idle"])


func _setup_websocket() -> void:
	websocket = $WebSocketServer
	if not websocket:
		websocket = preload("res://network/websocket_server.gd").new()
		websocket.name = "WebSocketServer"
		add_child(websocket)
		websocket.owner = self

	websocket.state_received.connect(_on_websocket_state)
	var port: int = 8765
	if config:
		port = config.get("WS_PORT", 8765)
	websocket.start_server(port)


func _setup_window() -> void:
	var window: Window = get_window()
	if not window:
		return

	window.title = "MJ Avatar"
	window.min_size = Vector2i(400, 600)

	if config:
		if config.get("TRANSPARENT", true):
			# Enable transparent background (requires Per-Pixel Transparency)
			window.transparent = true
			window.transparent_bg = true
		if config.get("ALWAYS_ON_TOP", true):
			window.always_on_top = true


# ------------------------------------------------------------------
# State Handling
# ------------------------------------------------------------------

func _on_state_changed(from: String, to: String) -> void:
	# Forward to animation manager (with priority queue)
	animation_mgr.request(to)

	avatar_state_changed.emit(to)
	print("MJ Avatar: ", from, " → ", to)


func _on_anim_finished(state_name: String, anim_name: String) -> void:
	# Let state machine chain idle behaviours
	state_machine.on_animation_done(state_name)


# ------------------------------------------------------------------
# Wake System
# When Python sends a state while avatar is SLEEP or STRETCH:
#   1. Play Excited (wake up)
#   2. Play Standing Idle
#   3. Play requested animation
# ------------------------------------------------------------------

func _on_websocket_state(state_name: String) -> void:
	var current_state: String = state_machine.get_current_name()

	# If sleeping or stretching → execute wake sequence
	if current_state == "SLEEP" or current_state == "STRETCH":
		_wake_pending = true
		_wake_anim_done = false
		_pending_state_after_wake = state_name
		animation_mgr.request("HAPPY", true)  # override queue
		avatar_woke_up.emit()
		return

	# Normal path — directly request the state
	state_machine.transition_to_name(state_name)
	animation_mgr.request(state_name)


func _execute_wake(_delta: float) -> void:
	if not _wake_anim_done:
		# Wait for Excited to finish
		if not animation_mgr.is_playing:
			_wake_anim_done = true
			# Transition to IDLE (Standing Idle) as a short pause
			state_machine.transition_to(state_machine.State.IDLE)
			animation_mgr.request("IDLE", true)
	else:
		# Wait for Standing Idle to finish
		if not animation_mgr.is_playing:
			_wake_pending = false
			# Now play the requested state
			state_machine.transition_to_name(_pending_state_after_wake)
			animation_mgr.request(_pending_state_after_wake, true)


# ------------------------------------------------------------------
# Future-Readiness Stubs
# ------------------------------------------------------------------

## Lip Sync — feed audio amplitude (0.0 – 1.0)
func set_lip_sync(amplitude: float) -> void:
	# TODO: Drive blendshape based on amplitude
	pass

## Emotion — set a facial expression blendshape
func set_emotion(emotion_name: String, weight: float = 1.0) -> void:
	# TODO: Drive blendshape on mesh
	pass

## Speech Bubble — show text above avatar
func show_speech(text: String, duration: float = 5.0) -> void:
	# TODO: Spawn speech bubble
	pass

## Mouse Follow — enable/disable
func set_mouse_follow(enabled: bool) -> void:
	# TODO: Rotate avatar toward mouse in 2D space
	pass

## Click Through — toggle window pass-through
func set_click_through(enabled: bool) -> void:
	if get_window():
		get_window().transparent_input = enabled
