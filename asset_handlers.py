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
ESCALATOR_BALUSTRADE_THICKNESS = 0.04
ESCALATOR_HANDRAIL_RADIUS = 0.035
ESCALATOR_MIN_STEP_WIDTH = 0.2


def _lerp_unclamped(a, b, t):
    return a + ((b - a) * t)


def _line_width_2d(a, b):
    return (b - a).to_2d().length


def _line_trimmed_to_width(a, b, target_width):
    """Return line endpoints centered on the original line with a fixed 2D width."""
    center = (a + b) * 0.5
    direction = b - a
    direction.z = 0.0
    if direction.length == 0:
        return a, b
    direction.normalize()
    half = target_width * 0.5
    return center - (direction * half), center + (direction * half)


def _escalator_step_width_from_outer_width(outer_width):
    """Return generator step width when JSON line width represents visual outer width."""
    side_extra = max(
        ESCALATOR_BALUSTRADE_THICKNESS,
        (ESCALATOR_BALUSTRADE_THICKNESS * 0.5) + ESCALATOR_HANDRAIL_RADIUS,
    )
    return max(ESCALATOR_MIN_STEP_WIDTH, outer_width - (side_extra * 2.0))


def _map_escalator_point_to_lines(point, start_a, start_b, end_a, end_b, run, width, local_rise):
    """Map a local escalator point onto the exact start/end line pair."""
    if run == 0:
        t = 0.0
    else:
        t = point.x / run
    if width == 0:
        u = 0.5
    else:
        u = (point.y / width) + 0.5

    start_cross = _lerp_unclamped(start_a, start_b, u)
    end_cross = _lerp_unclamped(end_a, end_b, u)
    base = _lerp_unclamped(start_cross, end_cross, t)
    ramp_z = local_rise * t
    vertical_offset = point.z - ramp_z
    return mathutils.Vector((base.x, base.y, base.z + vertical_offset))


def _warp_collection_to_escalator_lines(collection, start_a, start_b, end_a, end_b, run, width, local_rise):
    """Deform generated escalator objects so their lower and upper edges match JSON lines."""
    for obj in collection.objects:
        obj.matrix_world = mathutils.Matrix.Identity(4)
        if obj.type == "MESH":
            for vertex in obj.data.vertices:
                vertex.co = _map_escalator_point_to_lines(
                    vertex.co,
                    start_a,
                    start_b,
                    end_a,
                    end_b,
                    run,
                    width,
                    local_rise,
                )
            obj.data.update()
        elif obj.type == "CURVE":
            for spline in obj.data.splines:
                points = spline.bezier_points if spline.bezier_points else spline.points
                for point in points:
                    if hasattr(point, "co") and len(point.co) == 4:
                        mapped = _map_escalator_point_to_lines(
                            mathutils.Vector((point.co.x, point.co.y, point.co.z)),
                            start_a,
                            start_b,
                            end_a,
                            end_b,
                            run,
                            width,
                            local_rise,
                        )
                        point.co = (mapped.x, mapped.y, mapped.z, point.co.w)
                    else:
                        point.co = _map_escalator_point_to_lines(
                            point.co,
                            start_a,
                            start_b,
                            end_a,
                            end_b,
                            run,
                            width,
                            local_rise,
                        )


def escalator(item):
    """Create an escalator fitted exactly between start_line and end_line."""
    global ESCALATOR_COUNTER
    import escalator_generator

    start_a = mathutils.Vector(item["start_line"][0])
    start_b = mathutils.Vector(item["start_line"][1])
    end_a = mathutils.Vector(item["end_line"][0])
    end_b = mathutils.Vector(item["end_line"][1])

    start_center = (start_a + start_b) * 0.5
    end_center = (end_a + end_b) * 0.5

    rise = end_center.z - start_center.z
    local_rise = abs(rise)
    horizontal_run = (end_center - start_center).to_2d().length
    start_width = _line_width_2d(start_a, start_b)
    end_width = _line_width_2d(end_a, end_b)
    if start_center.z > end_center.z:
        outer_width = start_width
    else:
        outer_width = end_width
    if horizontal_run <= 0 or outer_width <= 0:
        print("Warning: escalator requires non-zero start/end distance and width")
        return
    step_width = _escalator_step_width_from_outer_width(outer_width)
    if start_center.z <= end_center.z:
        start_a, start_b = _line_trimmed_to_width(start_a, start_b, outer_width)
    else:
        end_a, end_b = _line_trimmed_to_width(end_a, end_b, outer_width)

    esc_name = f"Escalator_{ESCALATOR_COUNTER:03d}"
    ESCALATOR_COUNTER += 1

    escalator_generator.generate_escalator(
        name=esc_name,
        origin=(0.0, 0.0, 0.0),
        rise=local_rise,
        run=horizontal_run,
        rotation_z=0.0,
        width=step_width,
        top_landing=0.0,
        bot_landing=0.0,
        balustrade_thickness=ESCALATOR_BALUSTRADE_THICKNESS,
        handrail_radius=ESCALATOR_HANDRAIL_RADIUS,
        replace_existing=False
    )
    collection = bpy.data.collections.get(esc_name)
    if collection is None:
        print(f"Warning: escalator collection was not created: {esc_name}")
        return
    _warp_collection_to_escalator_lines(
        collection,
        start_a,
        start_b,
        end_a,
        end_b,
        horizontal_run,
        outer_width,
        local_rise,
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
    start_vec = mathutils.Vector(item["start"])
    end_vec = mathutils.Vector(item["end"])
    rot_z_deg = item.get("rotation_z", 0.0) # Defaults to 0 if missing

    # Location
    mid_vec = (start_vec + end_vec) * 0.5
    obj.location = mid_vec

    # Z rotation
    obj.rotation_euler[2] = math.radians(rot_z_deg)


    # --- 3. SCALE FACTORS ---
    # Original size of the asset
    NATIVE = { "length_x": 22.138, "width_y": 2.1082, "height_z": 1.359 }

    target_length, target_width, target_height = item["scale"]
    # Applying scale directly to the Empty container shapes the entire instanced collection
    scale_x = target_length / NATIVE["length_x"]
    scale_y = target_width  / NATIVE["width_y"]
    scale_z = target_height # / NATIVE["height_z"]

    obj.scale = (scale_x, scale_y * 2.0, scale_z)

def subway(item):

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
    start_vec = mathutils.Vector(item["start"])
    end_vec = mathutils.Vector(item["end"])
    rot_z_deg = item.get("rotation_z", 0.0) # Defaults to 0 if missing

    # Location
    mid_vec = (start_vec + end_vec) * 0.5
    obj.location = mid_vec

    # Z rotation
    obj.rotation_euler[2] = math.radians(rot_z_deg)


    # --- 3. SCALE FACTORS ---
    # Original size of the asset
    NATIVE = { "length_x": 22.2, "width_y": 3.17, "height_z": 3.52 }

    target_length, target_width, target_height = item["scale"]
    # Applying scale directly to the Empty container shapes the entire instanced collection
    scale_x = target_length / NATIVE["length_x"]
    scale_y = target_width  # / NATIVE["width_y"]
    scale_z = target_height # / NATIVE["height_z"]

    obj.scale = (scale_x, scale_y, scale_z)

def gate(item):

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

    # Z rotation
    obj.rotation_euler[2] = math.radians(rot_z_deg)


    # --- 3. SCALE FACTORS ---
    # Original size of the asset
    NATIVE = { "length_x": 0.654, "width_y": 1.9, "height_z": 1.05 }

    target_length, target_width, target_height = item["scale"]
    # Applying scale directly to the Empty container shapes the entire instanced collection
    scale_x = target_length # / NATIVE["length_x"]
    scale_y = target_width  # / NATIVE["width_y"]
    scale_z = target_height # / NATIVE["height_z"]

    obj.scale = (scale_x, scale_y, scale_z)

def toilet(item):

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

    # Z rotation
    obj.rotation_euler[2] = math.radians(rot_z_deg)


    # --- 3. SCALE FACTORS ---
    # Original size of the asset
    if collection_name == "toilet_both":
        NATIVE = { "length_x": 1.934, "width_y": 0.157, "height_z": 2.2 }
    else:
        NATIVE = { "length_x": 0.967, "width_y": 0.157, "height_z": 2.2 }

    target_length, target_width, target_height = item["scale"]
    # Applying scale directly to the Empty container shapes the entire instanced collection
    scale_x = target_length # / NATIVE["length_x"]
    scale_y = target_width  # / NATIVE["width_y"]
    scale_z = target_height # / NATIVE["height_z"]

    obj.scale = (scale_x, scale_y, scale_z)

def exit(item):

    # --- 1. HANDLE COLLECTION INSTANCING ---
    blend_file = os.path.join(BLEND_PATH, item["blend"])
    # 1-1. Get the suffix from JSON (e.g., "1" or "7-1")
    exit_number = item.get("number")

    # 1-2. Dynamically build the collection name: "Exit1", "Exit7-1", etc.
    # If no ID is found, it falls back to the blend file name.
    if exit_number:
        collection_name = f"Exit{exit_number}"
    else:
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

    # Z rotation
    obj.rotation_euler[2] = math.radians(rot_z_deg)


    # --- 3. SCALE FACTORS ---
    # Original size of the asset
    NATIVE = { "length_x": 2.0, "width_y": 2.0, "height_z": 2.0 }

    target_length, target_width, target_height = item["scale"]
    # Applying scale directly to the Empty container shapes the entire instanced collection
    scale_x = target_length # / NATIVE["length_x"]
    scale_y = target_width  # / NATIVE["width_y"]
    scale_z = target_height # / NATIVE["height_z"]

    obj.scale = (scale_x, scale_y, scale_z)

def generic(item, asset_name):
    """Assets that don't belong to any of previous ones are here"""
    pass
