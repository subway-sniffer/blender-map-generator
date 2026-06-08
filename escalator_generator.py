"""
파라메트릭 에스컬레이터 제너레이터 (정적, 애니메이션 없음)
================================================================
사용법:
    1. Blender 열고 Scripting 워크스페이스 이동
    2. 이 파일 내용 전체를 텍스트 에디터에 붙여넣기
    3. 맨 아래 generate_escalator(...) 호출의 인자를 수정
    4. Run Script (Alt+P) 실행

생성되는 것:
    - 계단(treads + risers) + 상하단 랜딩 플랫폼
    - 양옆 발루스트레이드(side panels)
    - 핸드레일(handrails) — 곡선 + 베벨

지하철 역사용으로 export 할 때는 모든 객체 선택 → File → Export → glTF 2.0
"""

import bpy
import bmesh
from math import atan, degrees, sqrt
import mathutils


# ================================================================
# 머티리얼 헬퍼
# ================================================================
def get_material(name, color, metallic=0.6, roughness=0.35):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name=name)

    # IMPORTANT: viewport/solid mode color
    mat.diffuse_color = (*color, 1.0)

    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
    return mat


# ================================================================
# bmesh 헬퍼
# ================================================================
def add_box(bm, x0, x1, y0, y1, z0, z1):
    """축정렬 박스를 bmesh에 추가."""
    v = [
        bm.verts.new((x0, y0, z0)),
        bm.verts.new((x1, y0, z0)),
        bm.verts.new((x1, y1, z0)),
        bm.verts.new((x0, y1, z0)),
        bm.verts.new((x0, y0, z1)),
        bm.verts.new((x1, y0, z1)),
        bm.verts.new((x1, y1, z1)),
        bm.verts.new((x0, y1, z1)),
    ]
    # 6면 (winding은 마지막에 recalc로 정리)
    bm.faces.new([v[0], v[1], v[2], v[3]])
    bm.faces.new([v[4], v[5], v[6], v[7]])
    bm.faces.new([v[0], v[1], v[5], v[4]])
    bm.faces.new([v[1], v[2], v[6], v[5]])
    bm.faces.new([v[2], v[3], v[7], v[6]])
    bm.faces.new([v[3], v[0], v[4], v[7]])


def bm_to_object(bm, name, collection, materials=None):
    me = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    if materials:
        for mat in materials:
            me.materials.append(mat)
    return obj


# ================================================================
# 메인 제너레이터
# ================================================================
def generate_escalator(
    name="Escalator",
    origin=(0.0, 0.0, 0.0),
    rise=4.0,                # 수직 높이 (m)
    run=6.928,               # 경사 구간 수평 길이 (m)
                             #   30° → run = rise × 1.732
                             #   35° → run = rise × 1.428
    rotation_z=0,

    width=1.0,               # 스텝 폭 (m)
    top_landing=1.0,         # 상단 평탄 구간 길이 (m)
    bot_landing=1.0,         # 하단 평탄 구간 길이 (m)
    step_rise_target=0.4,    # 한 스텝 높이 목표 (실측 200mm) -> 400mm
    handrail_height=1.0,     # 발판 면에서 핸드레일까지 높이 (m)
    balustrade_thickness=0.04,
    handrail_radius=0.035,
    step_thickness=0.04,
    replace_existing=True
):
    """파라메트릭 정적 에스컬레이터 생성. 컬렉션 이름은 `name`."""

    # ---- 컬렉션 준비 ----
    if replace_existing and name in bpy.data.collections:
        old = bpy.data.collections[name]
        for o in list(old.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)

    # ---- 머티리얼 ----
    mat_step = get_material("Esc_Step", (0.02, 0.02, 0.02), metallic=0.7, roughness=0.25)
    # Yellow line for step
    mat_step_yellow = get_material("Esc_Step_Yellow", (1.0, 0.85, 0.0), metallic=0.2, roughness=0.45)
    mat_balu = get_material("Esc_Balustrade", (0.89, 0.89, 0.89), metallic=0.2, roughness=0.4)
    mat_rail = get_material("Esc_Handrail", (0.04, 0.04, 0.04), metallic=0.0, roughness=0.5)

    # ---- 기하 계산 ----
    angle = atan(rise / run)
    incline_len = sqrt(rise ** 2 + run ** 2)
    n_steps = max(1, round(rise / step_rise_target))
    s_rise = rise / n_steps
    s_run = run / n_steps

    print(f"[{name}] angle={degrees(angle):.1f}°, "
          f"incline={incline_len:.2f}m, "
          f"steps={n_steps} ({s_rise*1000:.0f}×{s_run*1000:.0f}mm)")

    # ================================================================
    # 1. 스텝 (treads + risers + landings)
    # ================================================================
    bm = bmesh.new()

    # 하단 랜딩
    add_box(bm,
            -bot_landing, 0,
            -width/2, width/2,
            -step_thickness, 0)

    # 경사 구간 스텝들
    for i in range(n_steps):
        z_top = (i + 1) * s_rise
        x0 = i * s_run
        x1 = (i + 1) * s_run

        # tread (수평 발판)
        tread_x0 = x0
        tread_x1 = x1
        tread_z0 = z_top - step_thickness
        tread_z1 = z_top

        before_faces = set(bm.faces)

        add_box(
            bm,
            tread_x0, tread_x1,
            -width/2, width/2,
            tread_z0, tread_z1
        )

        # newly created faces
        new_faces = [f for f in bm.faces if f not in before_faces]

        # default = black step material
        for f in new_faces:
            f.material_index = 0

        # ------------------------------------------------
        # yellow front safety strip
        # detect the FRONT vertical face of the tread
        # ------------------------------------------------
        front_face = min(
            new_faces,
            key=lambda f: f.calc_center_median().x
        )

        front_face.material_index = 1

        # riser (스텝 정면 수직면)
        z_bot = i * s_rise  # 이전 스텝 윗면 높이
        add_box(bm,
                x0 - 0.005, x0 + 0.005,
                -width/2, width/2,
                z_bot, z_top - step_thickness)

    # 상단 랜딩
    add_box(bm,
            run, run + top_landing,
            -width/2, width/2,
            rise - step_thickness, rise)

    bm_to_object(bm, f"{name}_Steps", coll, materials=[mat_step, mat_step_yellow])

    # ================================================================
    # 2. 발루스트레이드 (양옆 패널)
    # ================================================================
    def build_balustrade(side):
        bm = bmesh.new()
        y_in = side * width/2
        y_out = side * (width/2 + balustrade_thickness)

        # 측면 프로파일 (xz 평면, 시계방향으로 닫힌 폴리곤)
        bottom_path = [
            (-bot_landing, 0),
            (0, 0),
            (run, rise),
            (run + top_landing, rise),
        ]
        top_path = [(x, z + handrail_height) for (x, z) in bottom_path]
        outline = bottom_path + list(reversed(top_path))

        inner_verts = [bm.verts.new((x, y_in, z)) for (x, z) in outline]
        outer_verts = [bm.verts.new((x, y_out, z)) for (x, z) in outline]

        # 양쪽 평면 (n-gon)
        bm.faces.new(inner_verts)
        bm.faces.new(outer_verts)

        # 옆면 스트립
        n = len(outline)
        for i in range(n):
            ni = (i + 1) % n
            bm.faces.new([inner_verts[i], outer_verts[i],
                          outer_verts[ni], inner_verts[ni]])

        suffix = "L" if side > 0 else "R"
        bm_to_object(bm, f"{name}_Balustrade_{suffix}", coll, materials=[mat_balu])

    build_balustrade(+1)
    build_balustrade(-1)

    # ================================================================
    # 3. 핸드레일 (곡선 + 베벨)
    # ================================================================
    def build_handrail(side):
        suffix = "L" if side > 0 else "R"
        cu_name = f"{name}_Handrail_{suffix}"
        cu = bpy.data.curves.new(cu_name, type='CURVE')
        cu.dimensions = '3D'
        cu.bevel_depth = handrail_radius
        cu.bevel_resolution = 4
        cu.use_fill_caps = True

        y = side * (width/2 + balustrade_thickness/2)
        points = [
            (-bot_landing, y, handrail_height),
            (0, y, handrail_height),
            (run, y, rise + handrail_height),
            (run + top_landing, y, rise + handrail_height),
        ]
        sp = cu.splines.new('POLY')
        sp.points.add(len(points) - 1)
        for i, p in enumerate(points):
            sp.points[i].co = (p[0], p[1], p[2], 1)

        obj = bpy.data.objects.new(cu_name, cu)
        coll.objects.link(obj)
        cu.materials.append(mat_rail)

    build_handrail(+1)
    build_handrail(-1)

    # ================================================================
    # 4. 원점 이동
    # ================================================================

    # rotation_z must be added as a new parameter to the function
    # e.g., def generate_escalator(..., rotation_z=0.0):
    # rotation around Z in radians
    transform_matrix = (
        mathutils.Matrix.Translation(origin) @
        mathutils.Matrix.Rotation(rotation_z, 4, 'Z')
    )

    for obj in coll.objects:
        obj.matrix_world = transform_matrix @ obj.matrix_world


# ================================================================
# 실행
# ================================================================
if __name__ == "__main__":
    # 예시 1: 단일 에스컬레이터 (30°, 4m 상승)
    generate_escalator(
        name="Escalator_01",
        origin=(0, 0, 0),
        rise=4.0,
        run=6.928,        # rise * sqrt(3) = 30°
        width=1.0,
        top_landing=1.5,
        bot_landing=1.5,
        rotation_z=0
    )

    # 예시 2: 같은 위치에 반대쪽 에스컬레이터를 만들고 싶다면 (옆에 나란히)
    # generate_escalator(
    #     name="Escalator_02",
    #     origin=(0, 1.2, 0),
    #     rise=4.0,
    #     run=6.928,
    # )

    # 예시 3: 더 가파르고 짧은 거 (35°, 3m 상승)
    # generate_escalator(
    #     name="Escalator_Short",
    #     origin=(0, -3, 0),
    #     rise=3.0,
    #     run=4.285,     # rise / tan(35°)
    # )
