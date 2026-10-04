extends Node

## ============================================================
## MJ Avatar — Animation Manager
## Uses AnimationTree + AnimationPlayer with crossfade, priority
## queue, and no hardcoded animation names.
## ============================================================

signal animation_started(state_name: String, anim_name: String)
signal animation_finished(state_name: String, anim_name: String)
signal queue_cleared()

# ── Dependencies (injected by AvatarController) ────────────
var animation_player: AnimationPlayer
var animation_tree: AnimationTree

# ── State → Animation mapping (only source of truth) ──────
var state_anim_map: Dictionary = {}

# ── Priority table ─────────────────────────────────────────
var priorities: Dictionary = {}

# ── Queue ──────────────────────────────────────────────────
var anim_queue: Array[Dictionary] = []
var current_state_name: String = ""
var current_anim_name: String = ""
var is_playing: bool = false
var crossfade_time: float = 0.25

# ── Random idle ────────────────────────────────────────────
var random_idle_enabled: bool = true
var _random_idle_timer: Timer
var _random_idle_anims: Array[String] = []

# ── Idle auto-transition config ────────────────────────────
var stretch_time: float = 300.0
var sleep_time: float = 600.0


func _ready() -> void:
	_random_idle_timer = Timer.new()
	_random_idle_timer.one_shot = true
	_random_idle_timer.timeout.connect(_on_random_idle_timeout)
	add_child(_random_idle_timer)


# ------------------------------------------------------------------
# Initialisation
# ------------------------------------------------------------------

func setup(player: AnimationPlayer, tree: AnimationTree, anim_map: Dictionary,
			prio: Dictionary, fade: float = 0.25) -> void:
	animation_player = player
	animation_tree = tree
	state_anim_map = anim_map
	priorities = prio
	crossfade_time = fade

	# Connect AnimationPlayer signals
	if animation_player.animation_finished.is_connected(_on_anim_finished):
		animation_player.animation_finished.disconnect(_on_anim_finished)
	animation_player.animation_finished.connect(_on_anim_finished)

	# AnimationTree is disabled (no transitions configured).
	# Keeping it inactive to avoid conflicts with AnimationPlayer playback.
	if animation_tree:
		animation_tree.active = false


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

## Play a state's animation with priority-based queuing.
## Returns true if the animation was accepted/enqueued.
func request(state_name: String, override_queue: bool = false) -> bool:
	if not state_anim_map.has(state_name):
		push_warning("AnimationManager: unknown state — ", state_name)
		return false

	var anim_name: String = state_anim_map[state_name]
	var priority: int = priorities.get(state_name, 0)

	# If this animation is already playing, skip
	if is_playing and current_state_name == state_name:
		return true

	# If queue is not empty and we're not overriding, enqueue
	if not override_queue and anim_queue.size() > 0:
		# Don't enqueue duplicates
		for entry in anim_queue:
			if entry.state == state_name:
				return true
		anim_queue.append({"state": state_name, "anim": anim_name, "priority": priority})
		return true

	# Check priority — can we interrupt current?
	if is_playing:
		var current_priority: int = priorities.get(current_state_name, 0)
		if priority <= current_priority and not override_queue:
			# Enqueue instead
			for entry in anim_queue:
				if entry.state == state_name:
					return true
			anim_queue.append({"state": state_name, "anim": anim_name, "priority": priority})
			return true

	# Play now (interrupt if lower priority or override)
	_play_immediate(state_name, anim_name)
	return true


## Clear all queued animations.
func clear_queue() -> void:
	anim_queue.clear()
	queue_cleared.emit()


## Get the list of animation names for random idle.
func set_random_idle_anims(anims: Array[String]) -> void:
	_random_idle_anims = anims


## Get current state name.
func get_current_state() -> String:
	return current_state_name


## Get current animation name.
func get_current_animation() -> String:
	return current_anim_name


# ------------------------------------------------------------------
# Internal
# ------------------------------------------------------------------

func _play_immediate(state_name: String, anim_name: String) -> void:
	# Stop random idle timer
	if _random_idle_timer.is_stopped() == false:
		_random_idle_timer.stop()

	current_state_name = state_name
	current_anim_name = anim_name
	is_playing = true

	# Direct AnimationPlayer playback (AnimationTree is disabled — no transitions configured)
	var played: bool = false
	if animation_player:
		if animation_player.has_animation(anim_name):
			animation_player.play(anim_name, crossfade_time)
			played = true
			print("AnimationManager: playing '", anim_name, "' for state '", state_name, "'")
		else:
			# Try alternate naming: animation may be stored under slightly different name
			push_warning("AnimationManager: animation '", anim_name, "' not found in AnimationPlayer")
			var anim_list: PackedStringArray = animation_player.get_animation_list()
			print("AnimationManager: available animations: ", anim_list)
			if anim_list.size() > 0:
				# Try to find a matching animation by scanning state_anim_map values
				var found_match: bool = false
				for entry_anim in state_anim_map.values():
					if animation_player.has_animation(entry_anim):
						animation_player.play(entry_anim, crossfade_time)
						print("AnimationManager: playing fallback '", entry_anim, "' instead of '", anim_name, "'")
						played = true
						found_match = true
						break
				if not found_match:
					animation_player.play(anim_list[0], crossfade_time)
					print("AnimationManager: playing first available '", anim_list[0], "' as fallback")
					played = true

	if not played:
		is_playing = false
		push_error("AnimationManager: failed to play any animation for state '", state_name, "'")
		return

	animation_started.emit(state_name, anim_name)


# Helper: get list of animation node names in AnimationTree state machine
func _get_tree_node_names() -> Array[String]:
	if not animation_tree or not animation_tree.tree_root:
		return []
	var root: AnimationNodeStateMachine = animation_tree.tree_root as AnimationNodeStateMachine
	if not root:
		return []
	var names: Array[String] = []
	for node_name in root.get_node_list():
		names.append(node_name)
	return names


func _on_anim_finished(anim_name: String) -> void:
	is_playing = false
	animation_finished.emit(current_state_name, anim_name)

	# Process next in queue
	if anim_queue.size() > 0:
		var next: Dictionary = anim_queue.pop_front()
		_play_immediate(next.state, next.anim)
	else:
		# Start random idle timer if enabled and in IDLE
		if current_state_name == "IDLE" and random_idle_enabled and _random_idle_anims.size() > 0:
			_random_idle_timer.start(randf_range(8.0, 20.0))


func _on_random_idle_timeout() -> void:
	if not random_idle_enabled or _random_idle_anims.is_empty():
		return
	if current_state_name != "IDLE":
		return
	var random_anim: String = _random_idle_anims.pick_random()
	animation_player.play(random_anim, crossfade_time)

