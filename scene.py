import bpy
import json
import os
import math
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
#JSON_PATH = BASE_DIR / "scene.json"

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

        # --- OPTION A: PROCEDURAL UNITY-COMPATIBLE STAIR (Changed name string to 'stair') ---
        if asset_name_lower == "stair":
            mesh = bpy.data.meshes.new("Dynamic_Stair")
            obj = bpy.data.objects.new("Dynamic_Stair_Obj", mesh)
            bpy.context.collection.objects.link(obj)

            bm = bmesh.new()

            total_height = item.get("target_height", 2.7)
            step_height = 0.18
            step_depth = 0.28
            width = 1.2

            num_steps = max(1, round(total_height / step_height))
            actual_h = total_height / num_steps

            # Setup Vertex Groups for Unity Engine separation
            visual_group = obj.vertex_groups.new(name="Visual_Steps")
            collision_group = obj.vertex_groups.new(name="Collision_Ramp")

            # 1. Generate the physical steps (Visuals)
            for i in range(num_steps):
                y_start = i * step_depth
                y_end = (i + 1) * step_depth
                z_end = (i + 1) * actual_h

                coords = [
                    (0, y_start, 0), (width, y_start, 0), (width, y_end, 0), (0, y_end, 0),
                    (0, y_start, z_end), (width, y_start, z_end), (width, y_end, z_end), (0, y_end, z_end)
                ]
                step_verts = [bm.verts.new(c) for c in coords]
                faces_indices = [(0,1,2,3), (4,5,6,7), (0,1,5,4), (2,3,7,6), (0,3,7,4), (1,2,6,5)]
                for f_idx in faces_indices:
                    bm.faces.new([step_verts[j] for j in f_idx])

            # 2. Generate the flat hidden incline slope (For smooth Unity Pathfinding/Raycasting)
            total_depth = num_steps * step_depth
            ramp_coords = [
                (0, 0, 0), (width, 0, 0),
                (width, total_depth, total_height), (0, total_depth, total_height)
            ]
            ramp_verts = [bm.verts.new(c) for c in ramp_coords]
            bm.faces.new(ramp_verts)

            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(mesh)
            bm.free()
            mesh.update()

            # 3. Sort vertices into their respective Unity Engine groups
            for vertex in obj.data.vertices:
                if math.isclose(vertex.co.y, total_depth, abs_tol=0.01) and math.isclose(vertex.co.z, total_height, abs_tol=0.01):
                    collision_group.add([vertex.index], 1.0, 'ADD')
                else:
                    visual_group.add([vertex.index], 1.0, 'ADD')

            # Global positioning
            obj.location = item.get("location", [0, 0, 0])
            if "rotation_z" in item:
                obj.rotation_euler[2] = item["rotation_z"]
                #obj.rotation_euler[2] = math.radians(item["rotation_z"])

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
                    obj.rotation_euler[2] = item["rotation_z"]
                    #obj.rotation_euler[2] = math.radians(item["rotation_z"])
                elif "rotation" in item:
                    obj.rotation_euler = [a for a in item["rotation"]]
                    #obj.rotation_euler = [math.radians(a) for a in item["rotation"]]

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
