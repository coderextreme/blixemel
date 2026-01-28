import bpy
import xml.etree.ElementTree as ET
from mathutils import Vector

DEFERRED_LINKS = []

def clean_scene():
    if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    for col in [bpy.data.meshes, bpy.data.materials, bpy.data.armatures,
                bpy.data.actions, bpy.data.cameras, bpy.data.lights]:
        for block in col: col.remove(block)
    for block in bpy.data.collections:
        if block.name != "Collection": bpy.data.collections.remove(block)

    global DEFERRED_LINKS
    DEFERRED_LINKS = []

def parse_typed_value(value_str, type_str):
    if value_str is None or value_str == "None": return None
    try:
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

    for prop in props.findall("Prop"):
        name = prop.get("name")
        typ = prop.get("type")
        val = parse_typed_value(prop.get("value"), typ)
        if name in ['name', 'type', 'is_readonly', 'data']: continue

        if typ == 'POINTER':
            if val and val != "None":
                DEFERRED_LINKS.append((blender_obj, name, val))
        else:
            try:
                if hasattr(blender_obj, name): setattr(blender_obj, name, val)
            except: pass

def import_libraries(root):
    libs = root.find("Libraries")
    if not libs: return

    # Meshes
    if libs.find("Meshes"):
        for m_node in libs.find("Meshes").findall("Mesh"):
            mesh = bpy.data.meshes.new(m_node.get("name"))
            geo = m_node.find("Geometry")
            if geo:
                verts = []
                for v in geo.find("Vertices").findall("V"):
                    verts.append([float(x) for x in v.get("co").split(',')])
                faces = []
                for p in geo.find("Polygons").findall("P"):
                    faces.append([int(x) for x in p.get("i").split(',')])
                mesh.from_pydata(verts, [], faces)
                mesh.update()
            apply_xml_properties(mesh, m_node)

    # Materials
    if libs.find("Materials"):
        for mat_node in libs.find("Materials").findall("Material"):
            mat = bpy.data.materials.new(mat_node.get("name"))
            apply_xml_properties(mat, mat_node)

    # Lights
    if libs.find("Lights"):
        for l_node in libs.find("Lights").findall("Light"):
            light = bpy.data.lights.new(l_node.get("name"), type='POINT')
            apply_xml_properties(light, l_node)

    # Cameras
    if libs.find("Cameras"):
        for c_node in libs.find("Cameras").findall("Camera"):
            cam = bpy.data.cameras.new(c_node.get("name"))
            apply_xml_properties(cam, c_node)

    # Armatures
    if libs.find("Armatures"):
        for arm_node in libs.find("Armatures").findall("ArmatureData"):
            arm = bpy.data.armatures.new(arm_node.get("name"))
            apply_xml_properties(arm, arm_node)

            temp_obj = bpy.data.objects.new("TempArmature", arm)
            bpy.context.collection.objects.link(temp_obj)
            bpy.context.view_layer.objects.active = temp_obj
            bpy.ops.object.mode_set(mode='EDIT')

            bones_node = arm_node.find("Bones")
            if bones_node:
                for b_node in bones_node.findall("Bone"):
                    eb = arm.edit_bones.new(b_node.get("name"))
                    if b_node.get("head"): eb.head = Vector([float(x) for x in b_node.get("head").split(',')])
                    if b_node.get("tail"): eb.tail = Vector([float(x) for x in b_node.get("tail").split(',')])
                    if b_node.get("roll"): eb.roll = float(b_node.get("roll"))

                for b_node in bones_node.findall("Bone"):
                    p_name = b_node.get("parent_name")
                    if p_name and p_name in arm.edit_bones:
                        arm.edit_bones[b_node.get("name")].parent = arm.edit_bones[p_name]

            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(temp_obj)

    # Actions
    if libs.find("Actions"):
        for act_node in libs.find("Actions").findall("Action"):
            action = bpy.data.actions.new(act_node.get("name"))
            apply_xml_properties(action, act_node)
            for fc_node in act_node.findall("FCurve"):
                dp = fc_node.get("data_path")
                idx = int(fc_node.get("array_index"))
                fcurve = action.fcurves.new(data_path=dp, index=idx)
                for kp in fc_node.findall("KP"):
                    co = [float(x) for x in kp.get("co").split(',')]
                    fcurve.keyframe_points.insert(frame=co[0], value=co[1])

def import_nla(obj, obj_node):
    nla_node = obj_node.find("NLA")
    if not nla_node: return

    if not obj.animation_data:
        obj.animation_data_create()

    for t_node in nla_node.findall("Track"):
        track = obj.animation_data.nla_tracks.new()
        apply_xml_properties(track, t_node)

        for s_node in t_node.findall("Strip"):
            act_name = s_node.get("action_name")
            action = bpy.data.actions.get(act_name)
            if action:
                # We need start frame from properties to create strip
                start_frame = 1
                props = s_node.find("Properties")
                if props:
                    val = props.find("Prop[@name='frame_start']")
                    if val: start_frame = float(val.get("value"))

                try:
                    strip = track.strips.new(s_node.get("name"), int(start_frame), action)
                    apply_xml_properties(strip, s_node)
                except:
                    print(f"Failed to create strip for {act_name}")

def import_object(parent_node, collection):
    for obj_node in parent_node.findall("Object"):
        name = obj_node.get("name", "Obj")
        data_name = obj_node.get("data_name")
        data_block = None

        if data_name:
            data_block = bpy.data.meshes.get(data_name) or \
                         bpy.data.lights.get(data_name) or \
                         bpy.data.cameras.get(data_name) or \
                         bpy.data.armatures.get(data_name)

        obj = bpy.data.objects.new(name, data_block)
        collection.objects.link(obj)
        apply_xml_properties(obj, obj_node)

        # NLA Import
        import_nla(obj, obj_node)

        # Vertex Groups
        vg_node = obj_node.find("VertexGroups")
        if vg_node:
            for g_node in vg_node.findall("Group"):
                vg = obj.vertex_groups.new(name=g_node.get("name"))
                if obj.type == 'MESH':
                    for vw in g_node.findall("VW"):
                        try: vg.add([int(vw.get("id"))], float(vw.get("w")), 'REPLACE')
                        except: pass

        import_object(obj_node, collection)

def import_collections(parent_xml, parent_col):
    for col_node in parent_xml.findall("Collection"):
        name = col_node.get("name", "Col")
        new_col = bpy.data.collections.new(name)
        parent_col.children.link(new_col)
        import_object(col_node, new_col)
        import_collections(col_node, new_col)

def resolve_deferred_links():
    print(f"Resolving {len(DEFERRED_LINKS)} links...")
    for obj, prop_name, target_name in DEFERRED_LINKS:
        target = bpy.data.objects.get(target_name) or \
                 bpy.data.meshes.get(target_name) or \
                 bpy.data.materials.get(target_name) or \
                 bpy.data.actions.get(target_name) or \
                 bpy.data.armatures.get(target_name) or \
                 bpy.data.cameras.get(target_name) or \
                 bpy.data.lights.get(target_name)

        if target:
            try: setattr(obj, prop_name, target)
            except: pass

def importFromXML(infile):
    tree = ET.parse(infile)
    root = tree.getroot()
    clean_scene()

    import_libraries(root)

    scenes = root.find("Scenes")
    if scenes:
        for s_node in scenes.findall("Scene"):
            scene = bpy.data.scenes.new(s_node.get("name"))
            bpy.context.window.scene = scene

            # UNWRAPPED Import:
            # 1. Import Sub-collections
            import_collections(s_node, scene.collection)
            # 2. Import Root Objects directly into scene.collection
            import_object(s_node, scene.collection)

            apply_xml_properties(scene, s_node)

    resolve_deferred_links()
    print("Import Complete.")

import_file_path = "sandrunner_bike.blxml"
import_path_abs = bpy.path.abspath("//" + import_file_path)

try:
    importFromXML(import_path_abs)
except Exception as e:
    import traceback
    traceback.print_exc()
