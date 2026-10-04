# Animation Fix — Task List

- [x] 1. **avatar.tscn** — Removed `active = false` so AnimationTree is enabled
- [x] 2. **avatar_controller.gd** — 
  - Set `anim_player.root_node` to the loaded model's skeleton
  - Added `_find_skeleton()` helper to locate Skeleton3D in model hierarchy
  - Added `_clone_and_remap_animation()` to strip FBX skeleton prefix from track paths
  - Animation loading now uses cloned+remapped animations so bone paths resolve vs GLB skeleton
- [x] 3. **animation_manager.gd** — No changes needed; already uses `animation_player.play()` correctly

## Summary of Changes

### Root Cause
The FBX animation files contain bone track paths relative to their own FBX scene hierarchy (e.g. `Armature/Skeleton3D/bone_name`). When copied into the main AnimationPlayer, these paths didn't match the GLB model's skeleton structure → animation played but bones weren't found → model stayed in default pose.

### Fix Applied
1. **avatar.tscn**: Removed `active = false` from AnimationTree
2. **avatar_controller.gd**:
   - `_load_model_and_animations()`: After loading GLB/VRM model, finds its Skeleton3D and sets `anim_player.root_node` to it
   - `_load_animations_from_fbx()`: Before adding FBX animations, clones and remaps each animation's bone track paths to strip the FBX skeleton prefix
   - `_clone_and_remap_animation()`: New function that duplicates an animation and rewrites all tracks that reference the FBX skeleton path to use just the bone name
