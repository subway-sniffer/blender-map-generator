import bpy
import os
import bmesh
import math
import mathutils
import numpy as np # for escalators
from pathlib import Path # for relative paths

BASE_DIR = Path(bpy.path.abspath("//"))
BLEND_PATH = BASE_DIR

def stair(item):
    mesh = bpy.data.meshes.new("Dynamic_Stair")
    obj = bpy.data.objects.new("Dynamic_Stair_Obj", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()

    # 1. Parse your exact JSON inputs into clean mathutils Vector lists
    s1 = mathutils.Vector(item["start_line"][0])
    s2 = mathutils.Vector(item["start_line"][1])
    e1 = mathutils.Vector(item["end_line"][0])
    e2 = mathutils.Vector(item["end_line"][1])

    total_height = float(item.get("target_height", 5.0))
    step_height = 0.18

    num_steps = max(1, round(total_height / step_height))
    actual_h = total_height / num_steps

    # Setup Vertex Groups for Unity Engine separation
    visual_group = obj.vertex_groups.new(name="Visual_Steps")
    collision_group = obj.vertex_groups.new(name="Collision_Ramp")

    # 2. Generate the physical solid steps (Visuals)
    # Using linear interpolation (lerp) between start and end lines directly in world space
    for i in range(num_steps):
        ratio_start = i / num_steps
        ratio_end = (i + 1) / num_steps

        # Calculate the 4 base points on the ground level (Z = s1.z)
        p_start_1 = s1.lerp(e1, ratio_start)
        p_start_2 = s2.lerp(e2, ratio_start)
        p_end_1 = s1.lerp(e1, ratio_end)
        p_end_2 = s2.lerp(e2, ratio_end)

        # The 4 bottom corners of this specific step pillar (solid down to base Z)
        b_fl = (p_start_1.x, p_start_1.y, s1.z)
        b_fr = (p_start_2.x, p_start_2.y, s2.z)
        b_br = (p_end_2.x,   p_end_2.y,   s2.z)
        b_bl = (p_end_1.x,   p_end_1.y,   s1.z)

        # The 4 top corners of this specific step pillar
        z_top = s1.z + ((i + 1) * actual_h)
        t_fl = (p_start_1.x, p_start_1.y, z_top)
        t_fr = (p_start_2.x, p_start_2.y, z_top)
        t_br = (p_end_2.x,   p_end_2.y,   z_top)
        t_bl = (p_end_1.x,   p_end_1.y,   z_top)

        coords = [b_fl, b_fr, b_br, b_bl, t_fl, t_fr, t_br, t_bl]

        step_verts = [bm.verts.new(c) for c in coords]
        faces_indices = [(0,1,2,3), (4,5,6,7), (0,1,5,4), (2,3,7,6), (0,3,7,4), (1,2,6,5)]
        for f_idx in faces_indices:
            bm.faces.new([step_verts[j] for j in f_idx])

    # 3. Generate the flat hidden incline slope (Collision Ramp) using raw line endpoints
    ramp_coords = [
        (s1.x, s1.y, s1.z), (s2.x, s2.y, s2.z),
        (e2.x, e2.y, e2.z), (e1.x, e1.y, e1.z)
    ]
    ramp_verts = [bm.verts.new(c) for c in ramp_coords]
    bm.faces.new(ramp_verts)

    # Clean up the bmesh structure
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    # 4. Sort vertices into their respective Unity Engine groups based on the actual endpoints
    for vertex in obj.data.vertices:
        if math.isclose(vertex.co.x, e1.x, abs_tol=0.05) or math.isclose(vertex.co.x, e2.x, abs_tol=0.05):
            collision_group.add([vertex.index], 1.0, 'ADD')
        else:
            visual_group.add([vertex.index], 1.0, 'ADD')

ESCALATOR_COUNTER = 0
def escalator(item):
    global ESCALATOR_COUNTER
    """Pipeline entry point that dynamically imports the standalone builder."""
    # 1. Import from your separate PC file on demand
    import escalator_generator

    # 2. Extract calculations straight from raw vectors
    target_height = float(item.get("target_height", 4.0))

    start_a = mathutils.Vector(item["start_line"][0])
    start_b = mathutils.Vector(item["start_line"][1])

    end_a = mathutils.Vector(item["end_line"][0])
    end_b = mathutils.Vector(item["end_line"][1])

    # Centers
    start_center = (start_a + start_b) * 0.5
    end_center = (end_a + end_b) * 0.5

    # Width from start line
    width = (end_b - end_a).to_2d().length



    # 1. Get the direction vector of the end landing line itself
    end_line_vector = end_b - end_a

    # 2. Calculate the base perpendicular vector (facing the stairs' orientation)
    dir_end_perpendicular = mathutils.Vector((
        -end_line_vector.y,
        end_line_vector.x,
        0.0
    ))
    dir_end_perpendicular.normalize()

    # 3. Get the actual movement direction from start to end center
    travel_dir = mathutils.Vector((
        end_center.x - start_center.x,
        end_center.y - start_center.y,
        0.0
    ))

    horizontal_run = travel_dir.length
    travel_dir.normalize()

    # 4. Use a dot product to check if our perpendicular vector is pointing
    # the opposite way of our actual travel direction.
    # If the dot product is negative, they are facing away from each other.
    if dir_end_perpendicular.dot(travel_dir) < 0:
        # Flip it 180 degrees!
        dir_end_perpendicular = -dir_end_perpendicular

    # 5. Calculate final rotation based on the auto-corrected vector
    rotation_z = math.atan2(dir_end_perpendicular.y, dir_end_perpendicular.x)

    # Vertical rise
    rise = end_center.z - start_center.z

    # Determine horizontal run distance based on the vector length between vectors
    #horizontal_run = (end_center - start_center).to_2d().length

    esc_name = f"Escalator_{ESCALATOR_COUNTER:03d}"
    ESCALATOR_COUNTER += 1

    # 3. Trigger the standalone builder's main generation function
    escalator_generator.generate_escalator(
        name=esc_name,
        origin=start_center,
        rise=target_height,
        run=horizontal_run,
        rotation_z=rotation_z,
        width=width,
        replace_existing=False
    )

def elevator(item):
    # --- 1. HANDLE COLLECTION INSTANCING ---
    blend_file = os.path.join(BLEND_PATH, item["blend"])
    collection_name = os.path.splitext(item["blend"])[0]
    coll = bpy.data.collections.get(collection_name)

    # If the base collection isn't loaded yet, append it from the file
    if not coll:
        if os.path.exists(blend_file):
            with bpy.data.libraries.load(blend_file) as (data_from, data_to):
                if collection_name in data_from.collections:
                    data_to.collections = [collection_name]
            coll = bpy.data.collections.get(collection_name)
        else:
            print(f"Warning: File missing at {blend_file}")

    if coll:
        # Target unique name from JSON (fallback to unique instance name if not provided)
        target_name = item.get("name", f"Inst_{collection_name}")

        # Create the Empty object that acts as the instance container
        obj = bpy.data.objects.new(target_name, None)
        obj.instance_type = 'COLLECTION'
        obj.instance_collection = coll
        bpy.context.collection.objects.link(obj)

    else:
        print(f"Error: Collection '{collection_name}' not found. Make sure it is appended first.")

    # --- 2. APPLY LOCATION AND ROTATION ---
    # Extract position and rotation from JSON
    loc_data = item["location"]
    rot_z_deg = item.get("rotation_z", 0.0) # Defaults to 0 if missing

    # Apply location directly to the Empty container
    obj.location = mathutils.Vector((loc_data[0], loc_data[1], loc_data[2]))

    # Apply the Z rotation (converted to radians)
    obj.rotation_euler[2] = math.radians(rot_z_deg)

    # Scale (hardcoded)
    obj.scale = (1, 1, 1)

def moving_walkway(item):
    pass

def subway(item):
    pass

def gates(item):
    pass

def toilet(item):
    pass

def exit_number(item):
    pass

def generic(item, asset_name):
    """Assets that don't belong to any of previous ones are here"""
    pass

