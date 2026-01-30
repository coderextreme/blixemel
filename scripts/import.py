import bpy
import os
import xml.etree.ElementTree as ET
from mathutils import Vector, Euler, Quaternion, Matrix

HIERARCHY_MAP = {}
DEFERRED_POSES = []
DEFERRED_ACTIONS = []

def clean_scene():
    if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    for col in [bpy.data.meshes, bpy.data.materials, bpy.data.armatures,
                bpy.data.actions, bpy.data.cameras, bpy.data.lights, bpy.data.images]:
        for block in col: col.remove(block)

    for block in bpy.data.collections:
        if block.name != "Collection":
            bpy.data.collections.remove(block)

    if "Collection" in bpy.data.collections:
        default_col = bpy.data.collections["Collection"]
        for obj in default_col.objects: default_col.objects.unlink(obj)

    while len(bpy.data.scenes) > 1:
        bpy.data.scenes.remove(bpy.data.scenes[-1])

    global HIERARCHY_MAP, DEFERRED_POSES, DEFERRED_ACTIONS
    HIERARCHY_MAP = {}
    DEFERRED_POSES = []
    DEFERRED_ACTIONS = []

def parse_typed_value(value_str, type_str, struct_type):
    if value_str is None or value_str == "None": return None
    try:
        if struct_type == "VECTOR":
            return Vector([float(x) for x in value_str.split(',')])
        elif struct_type == "EULER":
            return Euler([float(x) for x in value_str.split(',')], 'XYZ')
        elif struct_type == "QUATERNION":
            return Quaternion([float(x) for x in value_str.split(',')])
        elif struct_type == "MATRIX_4X4":
            parts = [float(x) for x in value_str.split(',')]
            rows = [parts[i:i+4] for i in range(0, 16, 4)]
            return Matrix(rows)

        if type_str == 'STRING': return value_str
        elif type_str == 'BOOLEAN': return value_str == "True"
        elif type_str == 'INT': return int(value_str)
        elif type_str == 'FLOAT': return float(value_str)
        elif 'ARRAY' in type_str:
            if not value_str: return []
            parts = value_str.split(',')
            return [float(x) for x in parts] if 'FLOAT' in type_str else [int(x) for x in parts]
        elif type_str == 'POINTER': return value_str
        elif type_str == 'ENUM': return value_str
    except: return None
    return value_str

def apply_xml_properties(blender_obj, xml_node):
    props = xml_node.find("Properties")
    if not props: return
    prop_list = props.findall("Prop")

    if blender_obj not in HIERARCHY_MAP:
        HIERARCHY_MAP[blender_obj] = {'parent': None, 'type': None, 'bone': None, 'inv': None, 'transforms': []}

    for prop in prop_list:
        if prop.get("name") == "rotation_mode":
            try: setattr(blender_obj, "rotation_mode", prop.get("value"))
            except: pass

    for prop in prop_list:
        name = prop.get("name")
        typ = prop.get("type")
        struct = prop.get("structure_type", "")
        val = parse_typed_value(prop.get("value"), typ, struct)

        if name in ['name', 'type', 'is_readonly', 'data', 'rotation_mode', 'use_nodes',
                    'matrix_basis', 'matrix_local', 'matrix_world', 'matrix_custom', 'matrix',
                    'head', 'tail', 'roll']:
            continue

        if name == 'parent' and typ == 'POINTER':
            HIERARCHY_MAP[blender_obj]['parent'] = val
            continue
        if name == 'parent_type':
            HIERARCHY_MAP[blender_obj]['type'] = val
            continue
        if name == 'parent_bone':
            HIERARCHY_MAP[blender_obj]['bone'] = val
            continue

        # Capture Inverse Matrix (Crucial for "Keep Transform" offsets)
        if name == 'matrix_parent_inverse':
            HIERARCHY_MAP[blender_obj]['inv'] = val
            continue

        if name in ['location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale', 'dimensions',
                    'delta_location', 'delta_rotation_euler', 'delta_rotation_quaternion', 'delta_scale']:
            HIERARCHY_MAP[blender_obj]['transforms'].append((name, val))
            continue

        if typ == 'POINTER':
            target = bpy.data.objects.get(val) or \
                     bpy.data.meshes.get(val) or \
                     bpy.data.materials.get(val) or \
                     bpy.data.actions.get(val) or \
                     bpy.data.armatures.get(val) or \
                     bpy.data.cameras.get(val) or \
                     bpy.data.lights.get(val) or \
                     bpy.data.images.get(val)
            if target:
                try: setattr(blender_obj, name, target)
                except: pass
            continue

        try:
            if hasattr(blender_obj, name): setattr(blender_obj, name, val)
        except: pass

def reconstruct_material_nodes(mat, mat_node):
    graph = mat_node.find("ShaderGraph")
    if not graph: return
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    bsdf = tree.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    out = tree.nodes.new('ShaderNodeOutputMaterial')
    out.location = (300, 0)
    tree.links.new(bsdf.outputs[0], out.inputs[0])

    def setup_input(socket_name, xml_attr, is_data=False):
        img_name = graph.get(f"{xml_attr}_image")
        if img_name:
            img = bpy.data.images.get(img_name)
            if img:
                tex_node = tree.nodes.new('ShaderNodeTexImage')
                tex_node.image = img
                tex_node.location = (-300, 0 if socket_name=="Base Color" else -300)
                if is_data: tex_node.image.colorspace_settings.name = 'Non-Color'

                if xml_attr == 'normal':
                    norm_map = tree.nodes.new('ShaderNodeNormalMap')
                    norm_map.location = (-150, -100)
                    tree.links.new(tex_node.outputs['Color'], norm_map.inputs['Color'])
                    tree.links.new(norm_map.outputs['Normal'], bsdf.inputs['Normal'])
                else:
                    tree.links.new(tex_node.outputs['Color'], bsdf.inputs[socket_name])
            return

        val_str = graph.get(f"{xml_attr}_val")
        if val_str:
            sock = bsdf.inputs.get(socket_name)
            if sock:
                if "," in val_str: sock.default_value = [float(x) for x in val_str.split(',')]
                else: sock.default_value = float(val_str)

    setup_input("Base Color", "color")
    setup_input("Metallic", "metallic", is_data=True)
    setup_input("Roughness", "roughness", is_data=True)
    setup_input("Normal", "normal", is_data=True)
    setup_input("Emission Color", "emission")
    setup_input("Alpha", "alpha")

def import_libraries(root, xml_dir):
    libs = root.find("Libraries")
    if not libs: return

    if libs.find("Images"):
        for i_node in libs.find("Images").findall("Image"):
            rel_path = i_node.get("filepath")
            name = i_node.get("name")
            img = None
            if rel_path:
                abs_path = os.path.join(xml_dir, rel_path)
                if os.path.exists(abs_path):
                    try: img = bpy.data.images.load(abs_path); img.name = name
                    except: pass
            if not img: img = bpy.data.images.new(name, 32, 32)
            apply_xml_properties(img, i_node)

    if libs.find("Meshes"):
        for m_node in libs.find("Meshes").findall("Mesh"):
            mesh = bpy.data.meshes.new(m_node.get("name"))
            geo = m_node.find("Geometry")
            if geo:
                verts = [[float(x) for x in v.get("co").split(',')] for v in geo.find("Vertices").findall("V")]
                faces = [[int(x) for x in p.get("i").split(',')] for p in geo.find("Polygons").findall("P")]
                mesh.from_pydata(verts, [], faces)
                mesh.update()
            apply_xml_properties(mesh, m_node)

    if libs.find("Materials"):
        for mat_node in libs.find("Materials").findall("Material"):
            mat = bpy.data.materials.new(mat_node.get("name"))
            apply_xml_properties(mat, mat_node)
            reconstruct_material_nodes(mat, mat_node)

    for col_name, data_col, rna_type in [("Lights", bpy.data.lights, 'POINT'), ("Cameras", bpy.data.cameras, None)]:
        if libs.find(col_name):
            for node in libs.find(col_name):
                item = data_col.new(node.get("name"), rna_type) if rna_type else data_col.new(node.get("name"))
                apply_xml_properties(item, node)

    if libs.find("Armatures"):
        for arm_node in libs.find("Armatures").findall("ArmatureData"):
            arm = bpy.data.armatures.new(arm_node.get("name"))
            apply_xml_properties(arm, arm_node)
            temp = bpy.data.objects.new("Temp", arm)
            bpy.context.collection.objects.link(temp)
            bpy.context.view_layer.objects.active = temp
            bpy.ops.object.mode_set(mode='EDIT')

            if arm_node.find("Bones"):
                for b_node in arm_node.find("Bones").findall("Bone"):
                    arm.edit_bones.new(b_node.get("name"))

                for b_node in arm_node.find("Bones").findall("Bone"):
                    p_name = b_node.get("parent_name")
                    if p_name:
                         eb = arm.edit_bones.get(b_node.get("name"))
                         parent = arm.edit_bones.get(p_name)
                         if eb and parent: eb.parent = parent

                for b_node in arm_node.find("Bones").findall("Bone"):
                    eb = arm.edit_bones.get(b_node.get("name"))
                    if eb:
                        if not eb.use_connect:
                            eb.head = Vector([float(x) for x in b_node.get("head").split(',')])
                        eb.tail = Vector([float(x) for x in b_node.get("tail").split(',')])
                        if b_node.get("roll"): eb.roll = float(b_node.get("roll"))

                for b_node in arm_node.find("Bones").findall("Bone"):
                    eb = arm.edit_bones.get(b_node.get("name"))
                    if eb: apply_xml_properties(eb, b_node)

            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(temp)

    if libs.find("Actions"):
        for act_node in libs.find("Actions").findall("Action"):
            action = bpy.data.actions.new(act_node.get("name"))
            apply_xml_properties(action, act_node)
            for fc_node in act_node.findall("FCurve"):
                fcurve = action.fcurves.new(data_path=fc_node.get("data_path"), index=int(fc_node.get("array_index")))
                for kp_node in fc_node.findall("KP"):
                    co = [float(x) for x in kp_node.get("co").split(',')]

                    kp = fcurve.keyframe_points.insert(frame=co[0], value=co[1])
                    kp.interpolation = kp_node.get("interpolation", 'BEZIER')
                    # FIX: Force handles to FREE to prevent flat lines
                    kp.handle_left_type = 'FREE'
                    kp.handle_right_type = 'FREE'

                    if kp_node.get("hl"): kp.handle_left = [float(x) for x in kp_node.get("hl").split(',')]
                    if kp_node.get("hr"): kp.handle_right = [float(x) for x in kp_node.get("hr").split(',')]
            if hasattr(action, "fcurves"): action.fcurves.update()

def import_object(parent_node, collection):
    for obj_node in parent_node.findall("Object"):
        name = obj_node.get("name", "Obj")
        data_name = obj_node.get("data_name")
        data_block = None
        if data_name:
            data_block = bpy.data.meshes.get(data_name) or bpy.data.lights.get(data_name) or \
                         bpy.data.cameras.get(data_name) or bpy.data.armatures.get(data_name)

        obj = bpy.data.objects.new(name, data_block)
        collection.objects.link(obj)

        if obj.type == 'ARMATURE':
            obj.show_in_front = True
            obj.data.display_type = 'STICK'

        apply_xml_properties(obj, obj_node)

        if obj.type == 'ARMATURE' and obj_node.find("Pose"):
            DEFERRED_POSES.append((obj, obj_node.find("Pose")))

        if obj_node.get("active_action"):
            DEFERRED_ACTIONS.append((obj, obj_node.get("active_action")))

        if obj_node.find("NLA"):
            if not obj.animation_data: obj.animation_data_create()
            for t_node in obj_node.find("NLA").findall("Track"):
                track = obj.animation_data.nla_tracks.new()
                apply_xml_properties(track, t_node)
                for s_node in t_node.findall("Strip"):
                    act = bpy.data.actions.get(s_node.get("action_name"))
                    if act:
                        try:
                            start_f = float(s_node.find("Properties/Prop[@name='frame_start']").get("value"))
                            strip = track.strips.new(s_node.get("name"), int(start_f), act)
                            apply_xml_properties(strip, s_node)
                        except: pass

        if obj_node.find("VertexGroups"):
            for g_node in obj_node.find("VertexGroups").findall("Group"):
                vg = obj.vertex_groups.new(name=g_node.get("name"))
                if obj.type == 'MESH':
                    for vw in g_node.findall("VW"):
                        vg.add([int(vw.get("id"))], float(vw.get("w")), 'REPLACE')

        import_object(obj_node, collection)

def import_collections(parent_xml, parent_col):
    for col_node in parent_xml.findall("Collection"):
        name = col_node.get("name", "Col")
        existing = bpy.data.collections.get(name)
        if existing and parent_col.name == "Collection" and name == "Collection":
            import_object(col_node, existing)
            import_collections(col_node, existing)
        else:
            new_col = bpy.data.collections.new(name)
            parent_col.children.link(new_col)
            import_object(col_node, new_col)
            import_collections(col_node, new_col)

def apply_deferred_poses():
    print(f"Applying {len(DEFERRED_POSES)} deferred poses...")
    for obj, pose_node in DEFERRED_POSES:
        if not obj.pose: continue
        for pb_node in pose_node.findall("HBone"):
            pbone = obj.pose.bones.get(pb_node.get("name"))
            if pbone: apply_xml_properties(pbone, pb_node)

def apply_deferred_actions():
    print(f"Applying {len(DEFERRED_ACTIONS)} deferred actions...")
    for obj, act_name in DEFERRED_ACTIONS:
        act = bpy.data.actions.get(act_name)
        if act:
            if not obj.animation_data: obj.animation_data_create()
            obj.animation_data.action = act

def resolve_hierarchy():
    print(f"Resolving hierarchy for {len(HIERARCHY_MAP)} objects...")

    # 1. Parenting & Inverse Matrix (Fixes clumping/centering)
    for obj, data in HIERARCHY_MAP.items():
        if data['parent']:
            parent = bpy.data.objects.get(data['parent'])
            if parent:
                obj.parent = parent
                if data['type']: obj.parent_type = data['type']
                if data['bone']: obj.parent_bone = data['bone']
                # RESTORE INVERSE
                if data['inv']: obj.matrix_parent_inverse = data['inv']

    # 2. Local Transforms (Fixes Upside down / Delta issues)
    for obj, data in HIERARCHY_MAP.items():
        for prop_name, val in data['transforms']:
            try: setattr(obj, prop_name, val)
            except: pass

def importFromXML(infile):
    tree = ET.parse(infile)
    root = tree.getroot()
    clean_scene()
    import_libraries(root, os.path.dirname(infile))

    scenes = root.find("Scenes")
    if scenes:
        for s_node in scenes.findall("Scene"):
            scene = bpy.data.scenes.new(s_node.get("name")) if len(bpy.data.scenes)==0 else bpy.data.scenes[0]
            scene.name = s_node.get("name")
            if s_node.get("frame_start"): scene.frame_start = int(s_node.get("frame_start"))
            if s_node.get("frame_end"): scene.frame_end = int(s_node.get("frame_end"))

            bpy.context.window.scene = scene
            import_collections(s_node, scene.collection)
            import_object(s_node, scene.collection)
            apply_xml_properties(scene, s_node)

    resolve_hierarchy()

    bpy.context.view_layer.update()
    apply_deferred_poses()
    apply_deferred_actions()

    bpy.context.scene.frame_set(bpy.context.scene.frame_start)
    print("Import Complete.")

try:
    importFromXML(bpy.path.abspath("//sandrunner_bike.blxml"))
except:
    import traceback
    traceback.print_exc()
