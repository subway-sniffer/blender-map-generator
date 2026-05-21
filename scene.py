import bpy
import json
import os
import math
import mathutils
import bmesh
from pathlib import Path # for relative paths

def create_material(name, color_rgba):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    principled = nodes.get("Principled BSDF")
    if principled:
        principled.inputs[0].default_value = color_rgba
    return mat

# --- Setup Paths ---
BASE_DIR = Path(bpy.path.abspath("//"))
BLEND_PATH = BASE_DIR
JSON_PATH = BASE_DIR / "polygon_example.json"
#JSON_PATH = BASE_DIR / "scene1.json"

print(JSON_PATH)

with open(JSON_PATH) as file:
    data = json.load(file)

# =========================================================================
# STEP 1: GENERATE FLOORS AND CUT HOLES NATIVELY
# =========================================================================
if "planes" in data:
    for obj in data["planes"]:
        name = obj.get("name", "Unnamed_Plane")

        mesh = bpy.data.meshes.new(name)
        obj3d = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj3d)

        bm = bmesh.new()
        all_boundary_edges = []

        # Build Outer Perimeter
        outer_coords = obj["vertices"]
        outer_verts = [bm.verts.new(v) for v in outer_coords]
        for i in range(len(outer_verts)):
            edge = bm.edges.new((outer_verts[i], outer_verts[(i + 1) % len(outer_verts)]))
            all_boundary_edges.append(edge)

        # Build Inner Holes
        if "holes" in obj:
            for hole_coords in obj["holes"]:
                if len(hole_coords) >= 3:
                    hole_verts = [bm.verts.new(v) for v in hole_coords]
                    for i in range(len(hole_verts)):
                        edge = bm.edges.new((hole_verts[i], hole_verts[(i + 1) % len(hole_verts)]))
                        all_boundary_edges.append(edge)

        # Execute native triangle fill (Leaves holes perfectly empty)
        bmesh.ops.triangle_fill(bm, edges=all_boundary_edges, use_beauty=True)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

        # Add Thickness
        solidify_mod = obj3d.modifiers.new(name="Thickness", type='SOLIDIFY')
        solidify_mod.thickness = 0.2

        # Apply Colors
        color = obj.get("color", [1.0, 1.0, 1.0, 1.0])
        mat = create_material(f"Mat_{name}", color)
        obj3d.data.materials.append(mat)
        mat.diffuse_color = color

# =========================================================================
# STEP 2: PLACE & DYNAMICALLY SCALE ASSETS
# =========================================================================
if "assets" in data:
    for item in data["assets"]:
        # Isolate the name without extension and convert to lowercase
        asset_name_lower = os.path.splitext(item["blend"])[0].lower()

        # --- OPTION A: PROCEDURAL UNITY-COMPATIBLE STAIR ---
        if asset_name_lower == "stair":
            # 1. Parse JSON inputs into Blender Vector objects
            s1 = mathutils.Vector(item["start_line"][0])
            s2 = mathutils.Vector(item["start_line"][1])
            e1 = mathutils.Vector(item["end_line"][0])
            e2 = mathutils.Vector(item["end_line"][1])

            target_height = float(item["target_height"])

            # 2. Calculate spatial dimensions
            # Width is determined by the length of the start line
            stair_width = (s2 - s1).length

            # Find the center points of the start line and end line
            start_center = (s1 + s2) / 2.0
            end_center = (e1 + e2) / 2.0

            # Horizontal run vector (ignoring Z for the flat distance calculation)
            run_vector = mathutils.Vector((end_center.x - start_center.x, end_center.y - start_center.y, 0.0))
            total_run = run_vector.length

            # Calculate global Z rotation based on the direction the stair climbs
            rotation_z = math.atan2(run_vector.y, run_vector.x)

            # 3. Ergonomics & Step Math (Aiming for ~0.18m standard rise)
            ideal_rise = 0.18
            step_count = max(1, round(target_height / ideal_rise))

            step_height = target_height / step_count
            step_depth = total_run / step_count

            # --- CREATE VISUAL STAIRCASE ---
            # Create a base step (centered at origin momentarily for clean scaling)
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
            visual_stair = bpy.context.active_object
            visual_stair.name = "Staircase_Visual"

            # Scale dimensions (Cube size 1.0 means dimensions equal scale)
            visual_stair.dimensions = (step_depth, stair_width, step_height)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

            # Shift geometry data so the step pivots from its bottom-back-center edge
            for vertex in visual_stair.data.vertices:
                vertex.co.x += step_depth / 2.0
                vertex.co.z += step_height / 2.0

            # Add Array Modifier to build the rest of the steps
            array_mod = visual_stair.modifiers.new(name="Stair_Array", type='ARRAY')
            array_mod.count = step_count
            array_mod.use_relative_offset = False
            array_mod.use_constant_offset = True
            array_mod.constant_offset_displace = (step_depth, 0.0, step_height)

            # Position and rotate the final visual staircase asset globally
            visual_stair.location = start_center
            visual_stair.rotation_euler = (0.0, 0.0, rotation_z)

            # --- CREATE COLLIDER RAMP ---
            # Create a cube to reshape into a wedge/ramp
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
            collider_ramp = bpy.context.active_object
            collider_ramp.name = "Staircase_UCX"  # Unity auto-convex naming convention

            # Scale it to match the overall bounding box of the stairs
            # We add a small thickness (e.g., 0.1m) to give Unity physics a solid volume
            ramp_thickness = 0.1
            collider_ramp.dimensions = (total_run, stair_width, ramp_thickness)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

            # Shift geometry so it pivots properly from bottom-back-center
            for vertex in collider_ramp.data.vertices:
                vertex.co.x += total_run / 2.0
                # Shear vertices to match the incline angle perfectly
                progress_ratio = vertex.co.x / total_run
                vertex.co.z += (progress_ratio * target_height) - (ramp_thickness / 2.0)

            # Position and rotate the collider ramp to match the visual stairs perfectly
            collider_ramp.location = start_center
            collider_ramp.rotation_euler = (0.0, 0.0, rotation_z)

            # Deselect everything to finish cleanly
            bpy.ops.object.select_all(action='DESELECT')

        # --- OPTION B: STANDARD COLLECTION INSTANCING (Requires .blend files) ---
        else:
            blend_file = os.path.join(BLEND_PATH, item["blend"])
            collection_name = os.path.splitext(item["blend"])[0]

            coll = bpy.data.collections.get(collection_name)
            if not coll:
                if os.path.exists(blend_file):
                    with bpy.data.libraries.load(blend_file) as (data_from, data_to):
                        if collection_name in data_from.collections:
                            data_to.collections = [collection_name]
                    coll = bpy.data.collections.get(collection_name)
                else:
                    print(f"Warning: File missing at {blend_file}")
                    continue

            if coll:
                obj = bpy.data.objects.new(f"Inst_{collection_name}", None)
                obj.instance_type = 'COLLECTION'
                obj.instance_collection = coll
                bpy.context.collection.objects.link(obj)

                obj.location = item.get("location", [0, 0, 0])
                if "rotation_z" in item:
                    #obj.rotation_euler[2] = item["rotation_z"]
                    obj.rotation_euler[2] = math.radians(item["rotation_z"])
                elif "rotation" in item:
                    #obj.rotation_euler = [a for a in item["rotation"]]
                    obj.rotation_euler = [math.radians(a) for a in item["rotation"]]

                # Handle Scaling and Fallbacks safely
                base_scale = item.get("scale", [1.0, 1.0, 1.0])
                target_height_scale = item.get("target_height", 1.0)

                if asset_name_lower == "escalator":
                    # Smart uniform constraints for escalators
                    obj.scale = [target_height_scale, base_scale[1], target_height_scale]
                else:
                    # General stretch scaling for elevators/walkways
                    obj.scale = [base_scale[0], base_scale[1], target_height_scale]


#For Coordinate-Based Movement (NavMesh):
#
#    Select your imported stairs object.
#
#    Go to Window > AI > Navigation (or the NavMesh surface component if you are using modern Unity packages).
#
#    Check Navigation Static.
#
#    In the NavMesh settings, ensure your Max Slope value is set higher than the angle of your staircase (e.g., set Max Slope to 45 degrees). Unity will bake a clean, smooth ramp over your generated asset.
#
#For Coordinate-Based Movement (Direct Scripting / MoveTowards):
#
#    If you are manually calculating vectors using Vector3.MoveTowards(pointA, pointB) to move the player between coordinate nodes:
#
#    Keep a reference to the Y-coordinate of the smooth invisible collision ramp.
#
#    Add a Raycast to the bottom of your player script pointing straight down at the ground. As your script changes the player's X and Z coordinates, read the hit point distance on the ramp and adjust transform.position.y = raycastHit.point.y. Because the script generated a perfectly smooth slope alongside the steps, the character will never twitch or shake!
