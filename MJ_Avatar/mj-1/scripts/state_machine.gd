extends Node

## ============================================================
## MJ Avatar — Finite State Machine
## Lightweight FSM that manages state transitions, idle levels,
## and wake-from-sleep logic.
## ============================================================

signal state_changed(from: String, to: String)

# ── State enum matching MJ's behaviour modes ───────────────
enum State {
	IDLE,
	LISTENING,
	THINKING,
	TALKING,
	HAPPY,
	STRETCH,
	SLEEP,
	SORRY,
}

# ── Human-readable names (keep in sync with enum) ─────────
const STATE_NAMES: Dictionary = {
	State.IDLE:      "IDLE",
	State.LISTENING: "LISTENING",
	State.THINKING:  "THINKING",
	State.TALKING:   "TALKING",
	State.HAPPY:     "HAPPY",
	State.STRETCH:   "STRETCH",
	State.SLEEP:     "SLEEP",
	State.SORRY:     "SORRY",
}

const NAME_TO_STATE: Dictionary = {
	"IDLE":      State.IDLE,
	"LISTENING": State.LISTENING,
	"THINKING":  State.THINKING,
	"TALKING":   State.TALKING,
	"HAPPY":     State.HAPPY,
	"STRETCH":   State.STRETCH,
	"SLEEP":     State.SLEEP,
	"SORRY":     State.SORRY,
}

# ── Idle level tracking ────────────────────────────────────
# Level 0 = Standing Idle
# Level 1 = After 5 min idle → Arm Stretching → back to idle
# Level 2 = After 10 min idle → Male Laying Pose

var current: State = State.IDLE
var previous: State = State.IDLE

# Idle timers
var _idle_elapsed: float = 0.0
var _stretch_time: float = 300.0
var _sleep_time: float = 600.0
var _has_stretched: bool = false
var _has_slept: bool = false

# Wake tracking — when a non-idle state arrives from outside
var _external_message_received: bool = false


func _ready() -> void:
	_reset_idle()


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

## Transition to a new state.  Returns the state name string.
func transition_to(new_state: State) -> String:
	if new_state == current:
		return STATE_NAMES[current]

	previous = current
	current = new_state

	# Track external messages (from WebSocket / Python)
	if new_state != State.IDLE and new_state != State.STRETCH and new_state != State.SLEEP:
		_external_message_received = true

	# Reset idle tracking when we go IDLE or receive external state
	if new_state == State.IDLE:
		_reset_idle()
	elif new_state != State.STRETCH and new_state != State.SLEEP:
		_idle_elapsed = 0.0
		_has_stretched = false
		_has_slept = false

	state_changed.emit(STATE_NAMES[previous], STATE_NAMES[current])
	return STATE_NAMES[current]


## Convenience: pass a string like "THINKING" → auto-transition.
func transition_to_name(state_name: String) -> bool:
	var upper: String = state_name.to_upper()
	if NAME_TO_STATE.has(upper):
		transition_to(NAME_TO_STATE[upper])
		return true
	push_warning("StateMachine: unknown state name — ", state_name)
	return false


## Get current state as a string.
func get_current_name() -> String:
	return STATE_NAMES[current]


## Get previous state as a string.
func get_previous_name() -> String:
	return STATE_NAMES[previous]


## Check if state is idle or idle-derived (stretch/sleep).
func is_idle_related() -> bool:
	return current == State.IDLE or current == State.STRETCH or current == State.SLEEP


## Called every frame by AvatarController to tick idle logic.
func tick_idle(delta: float) -> void:
	if current != State.IDLE:
		return

	_idle_elapsed += delta

	# Level 1: 5 min → Stretch
	if not _has_stretched and _idle_elapsed >= _stretch_time:
		_has_stretched = true
		transition_to(State.STRETCH)
		return

	# Level 2: 10 min → Sleep
	if not _has_slept and _idle_elapsed >= _sleep_time:
		_has_slept = true
		transition_to(State.SLEEP)


## Called when animation finishes — chain idle behaviours.
func on_animation_done(state_name: String) -> void:
	if state_name == "STRETCH":
		transition_to(State.SLEEP)
	elif state_name == "SLEEP":
		transition_to(State.IDLE)


## Did an external message arrive since last check?
func consume_external_wake_flag() -> bool:
	var ret: bool = _external_message_received
	_external_message_received = false
	return ret


# ------------------------------------------------------------------
# Internal
# ------------------------------------------------------------------

func _reset_idle() -> void:
	_idle_elapsed = 0.0
	_has_stretched = false
	_has_slept = false
	_external_message_received = false

