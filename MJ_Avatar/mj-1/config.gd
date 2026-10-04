extends Node

## ============================================================
## MJ Avatar — Global Configuration
## Centralised constants so no magic strings leak into logic.
## ============================================================

# ── Window ---------------------------------------------------
const WINDOW_TITLE: String = "MJ Avatar"
const WINDOW_WIDTH: int = 400
const WINDOW_HEIGHT: int = 600
const TRANSPARENT: bool = true
const ALWAYS_ON_TOP: bool = true
const CLICK_THROUGH: bool = false       # toggle at runtime

# ── Network --------------------------------------------------
const WS_PORT: int = 8765
const WS_HOST: String = "localhost"

# ── Idle Timing (seconds) ------------------------------------
const IDLE_STRETCH_TIME: float = 300.0   # 5 min → Arm Stretching
const IDLE_SLEEP_TIME: float = 600.0     # 10 min → Male Laying Pose

# ── Animation Priorities (higher = more important) -----------
const PRIORITY: Dictionary = {
	"SORRY":     100,
	"HAPPY":     90,
	"TALKING":   80,
	"THINKING":  70,
	"LISTENING": 60,
	"STRETCH":   30,
	"SLEEP":     20,
	"IDLE":      10,
}

# ── Crossfade Duration ---------------------------------------
const CROSSFADE_TIME: float = 0.25

# ── Random Idle Interval -------------------------------------
const RANDOM_IDLE_MIN: float = 8.0
const RANDOM_IDLE_MAX: float = 20.0

# ── Mouse Follow Settings ------------------------------------
const MOUSE_FOLLOW_SPEED: float = 2.0
const MOUSE_FOLLOW_LIMIT: float = 15.0   # degrees

# ── Eye LookAt -------------------------------------------------
const EYE_LOOK_SPEED: float = 3.0
const EYE_BLINK_INTERVAL: float = 4.0    # seconds
const EYE_BLINK_DURATION: float = 0.1

# ── Speech Bubble --------------------------------------------
const SPEECH_BUBBLE_DURATION: float = 5.0
const SPEECH_BUBBLE_FADE: float = 0.5

# ── Lip Sync -------------------------------------------------
const LIP_SYNC_SMOOTHING: float = 0.1
const LIP_OPEN_CLOSE_THRESHOLD: float = 0.3

