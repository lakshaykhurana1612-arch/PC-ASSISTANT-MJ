# Fix Gray Window - Implementation Steps

## Step 1: Edit avatar.tscn
- [x] Add ext_resource for `res://assets/mj.glb`
- [x] Remove empty `AvatarModel` node
- [x] Add `Mesh` node with GLB instance as child of MJ
- [x] Replace `OmniLight3D` with `DirectionalLight3D`

## Step 2: Edit avatar_controller.gd
- [x] Fix `@onready var avatar_model` path from `$AvatarModel` to `$Mesh`
- [x] Update `_load_model_and_animations()` to use scene-instanced GLB

## Step 3: Verify
- [x] Verify scene loads without errors
- [x] Verify model renders in viewport

