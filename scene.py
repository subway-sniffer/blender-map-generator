import bpy
import json
import os
import sys
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
JSON_PATH = BASE_DIR / "scene.json"

# Convert the Path object to a string and add it to Python's search path
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

import asset_handlers

with open(JSON_PATH) as file:
    data = json.load(file)


# --- MAIN LOOP ---
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
        plane_solidify = obj3d.modifiers.new(name="Thickness", type='SOLIDIFY')
        plane_solidify.thickness = 0.15

        # Apply Colors
        color = obj.get("color", [1.0, 1.0, 1.0, 1.0])
        mat = create_material(f"Mat_{name}", color)
        obj3d.data.materials.append(mat)
        mat.diffuse_color = color

# =========================================================================
# STEP 2: PLACE & DYNAMICALLY SCALE ASSETS
# =========================================================================
# --- THE REGISTRY MAP ---
ASSET_REGISTRY = {
    "stair": asset_handlers.stair,
    "escalator": asset_handlers.escalator,
    "elevator": asset_handlers.elevator,
    "movingwalkway": asset_handlers.moving_walkway,
    "subway": asset_handlers.subway,
    "gate": asset_handlers.gate,
    "toilet": asset_handlers.toilet,
    "exit": asset_handlers.exit
}

if "assets" in data:
    for item in data["assets"]:
        asset_name = os.path.splitext(item["blend"])[0].lower()

        if asset_name in ASSET_REGISTRY:
            ASSET_REGISTRY[asset_name](item)
        else:
            asset_handlers.generic(item, asset_name)
            #print(f"Warning: No match found for '{asset_name}'")


# =========================================================================
# STEP 3: PLACE WALLS for TICKET GATES
# =========================================================================
if "walls" in data:
    for item in data["walls"]:
        # Extract properties from the JSON item
        name = item.get("name", "Unnamed_Wall")
        vertices_list = item.get("vertices", [])
        color = item.get("color", [1.0, 1.0, 1.0, 1.0])  # Fallback to white if missing

        # Skip if vertices data is missing or incomplete
        if len(vertices_list) < 4:
            print(f"Skipping {name}: A wall needs exactly 4 vertices.")
            continue

        # 1. Create a new empty mesh and object container
        mesh_data = bpy.data.meshes.new(f"{name}_mesh")
        wall_obj = bpy.data.objects.new(name, mesh_data)

        # 2. Link the new wall object to your active scene collection
        bpy.context.collection.objects.link(wall_obj)

        # 3. Define the face connection loop (0 -> 1 -> 2 -> 3)
        faces = [(0, 1, 2, 3)]
        edges = []

        # 4. Generate the actual wall geometry
        mesh_data.from_pydata(vertices_list, edges, faces)
        mesh_data.update()

        # 5. Create and assign the material using the JSON color
        mat = bpy.data.materials.new(name=f"Mat_{name}")

        # Set the viewport color so it is visible right away in Solid View!
        mat.diffuse_color = color

        # Set the actual material node color (for Material Preview / Render modes)
        if mat.use_nodes and mat.node_tree:
            nodes = mat.node_tree.nodes
            principled = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if principled:
                principled.inputs['Base Color'].default_value = color

        # Append the completed material to the wall mesh
        wall_obj.data.materials.append(mat)

        # 6. Add Thickness specifically for Walls (Kept separate from planes)
        wall_solidify = wall_obj.modifiers.new(name="Wall_Thickness_Mod", type='SOLIDIFY')
        wall_solidify.thickness = 0.1
        wall_solidify.offset = 0.0  # Centers the thickness on the vertices


    # print("All walls from data successfully generated with custom viewport colors!")
