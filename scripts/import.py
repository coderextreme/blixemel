import bpy
import os
import xml.etree.ElementTree as ET
from mathutils import Vector, Euler, Quaternion, Matrix
from bpy_extras import image_utils

HIERARCHY_MAP = {}
DEFERRED_POSES = []
DEFERRED_ACTIONS = []
DEFERRED_LINKS = []

def clean_scene():
    print("Cleaning Scene...")
    if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    for col in [bpy.data.meshes, bpy.data.materials, bpy.data.armatures,
                bpy.data.actions, bpy.data.cameras, bpy.data.lights, bpy.data.images]:
        for block in col:
            col.remove(block)

    for block in bpy.data.collections:
        if block.name != "Collection":
            bpy.data.collections.remove(block)
    if "Collection" in bpy.data.collections:
        default_col = bpy.data.collections["Collection"]
        for obj in list(default_col.objects):
            default_col.objects.unlink(obj)
    while len(bpy.data.scenes) > 1:
        bpy.data.scenes.remove(bpy.data.scenes[-1])

    global HIERARCHY_MAP, DEFERRED_POSES, DEFERRED_ACTIONS, DEFERRED_LINKS
    HIERARCHY_MAP = {}
    DEFERRED_POSES = []
    DEFERRED_ACTIONS = []
    DEFERRED_LINKS = []

def parse_typed_value(value_str, type_str, struct_type):
    if value_str is None or value_str == "None":
        return None
    try:
        if struct_type == "VECTOR":
            return Vector([float(x) for x in value_str.split(',')])
        elif struct_type == "EULER":
            return Euler([float(x) for x in value_str.split(',')], 'XYZ')
        elif struct_type == "QUATERNION":
            return Quaternion([float(x) for x in value_str.split(',')])
        elif struct_type == "MATRIX_4X4":
            parts = [float(x) for x in value_str.split(',')]
            return Matrix([parts[i:i+4] for i in range(0, 16, 4)])
        if type_str == 'STRING':
            return value_str
        elif type_str == 'BOOLEAN':
            return value_str == "True"
        elif type_str == 'INT':
            return int(value_str)
        elif type_str == 'FLOAT':
            return float(value_str)
        elif 'ARRAY' in type_str:
            if not value_str:
                return []
            parts = value_str.split(',')
            return [float(x) for x in parts] if 'FLOAT' in type_str else [int(x) for x in parts]
    except:
        return None
    return value_str

def apply_xml_properties(blender_obj, xml_node):
    props = xml_node.find("Properties")
    if not props:
        return

    if blender_obj not in HIERARCHY_MAP:
        HIERARCHY_MAP[blender_obj] = {
            'parent': None,
            'type': None,
            'bone': None,
            'inv': None,
            'world_matrix': None,
            'transforms': [],
            'rotation_mode': None,
        }

    data = HIERARCHY_MAP[blender_obj]

    for prop in props.findall("Prop"):
        name = prop.get("name")
        val = parse_typed_value(prop.get("value"), prop.get("type"), prop.get("structure_type", ""))

        if name in ['name', 'type', 'is_readonly', 'data',
                    'matrix_basis', 'matrix_local', 'matrix_custom']:
            continue

        if name == 'parent':
            data['parent'] = val
        elif name == 'parent_type':
            data['type'] = val
        elif name == 'parent_bone':
            data['bone'] = val
        elif name == 'head':
            data['head'] = val
        elif name == 'tail':
            data['tail'] = val
        elif name == 'matrix_parent_inverse':
            data['inv'] = val
        elif name == 'matrix_world':
            data['world_matrix'] = val
        elif name == 'rotation_mode':
            data['rotation_mode'] = val
        elif name in ['location', 'rotation_euler', 'rotation_quaternion', 'scale']:
            # Option A: only store local transforms if no matrix_world
            if data['world_matrix'] is None:
                data['transforms'].append((name, val))
        elif prop.get("type") == 'POINTER':
            DEFERRED_LINKS.append((blender_obj, name, val))
        else:
            try:
                setattr(blender_obj, name, val)
            except:
                pass

def rebuild_action_from_baked_pose(arm_obj, baked_node, action_name="BakedFromXML"):
    scene = bpy.context.scene

    # Ensure animation_data exists
    if not arm_obj.animation_data:
        arm_obj.animation_data_create()

    action = bpy.data.actions.new(action_name)
    arm_obj.animation_data.action = action

    for frame_node in baked_node.findall("Frame"):
        f = int(float(frame_node.get("f", "0")))
        scene.frame_set(f)

        for bone_node in frame_node.findall("Bone"):
            name = bone_node.get("name")
            pbone = arm_obj.pose.bones.get(name)
            if not pbone:
                continue

            loc = [float(x) for x in bone_node.find("Loc").get("v").split(",")]
            rot = [float(x) for x in bone_node.find("RotQ").get("v").split(",")]
            scl = [float(x) for x in bone_node.find("Scale").get("v").split(",")]

            pbone.location = loc
            pbone.rotation_mode = 'QUATERNION'
            pbone.rotation_quaternion = rot
            pbone.scale = scl

            pbone.keyframe_insert(data_path="location", frame=f)
            pbone.keyframe_insert(data_path="rotation_quaternion", frame=f)
            pbone.keyframe_insert(data_path="scale", frame=f)

    return action

def rebuild_full_node_graph(mat, nodegraph_node):
    tree = mat.node_tree
    tree.nodes.clear()
    node_map = {}

    for n_el in nodegraph_node.findall("Node"):
        bl_idname = n_el.get("type")
        name = n_el.get("name", bl_idname)
        loc_str = n_el.get("loc", "0,0")

        try:
            node = tree.nodes.new(bl_idname)
        except:
            print(f"  [Mat: {mat.name}] Unknown node type: {bl_idname}")
            continue

        node.name = name
        try:
            x, y = [float(x) for x in loc_str.split(',')]
            node.location = (x, y)
        except:
            pass

        if node.type == 'TEX_IMAGE':
            img_name = n_el.get("image")
            if img_name and img_name in bpy.data.images:
                node.image = bpy.data.images[img_name]

        label = n_el.get("label")
        if label:
            node.label = label

        node_map[name] = node

    for l_el in nodegraph_node.findall("Link"):
        fn = node_map.get(l_el.get("from_node"))
        tn = node_map.get(l_el.get("to_node"))
        if not fn or not tn:
            continue

        fs = fn.outputs.get(l_el.get("from_socket"))
        ts = tn.inputs.get(l_el.get("to_socket"))
        if fs and ts:
            tree.links.new(fs, ts)

def reconstruct_material_nodes(mat, mat_node):
    graph = mat_node.find("ShaderGraph")
    nodegraph = mat_node.find("NodeGraph")
    tree = mat.node_tree

    if nodegraph is not None:
        rebuild_full_node_graph(mat, nodegraph)
        return

    tree.nodes.clear()

    bsdf = tree.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (10, 300)
    out = tree.nodes.new('ShaderNodeOutputMaterial')
    out.location = (300, 300)
    tree.links.new(bsdf.outputs[0], out.inputs[0])

    if 'Alpha' in bsdf.inputs:
        bsdf.inputs['Alpha'].default_value = 1.0

    if not graph:
        print(f"  [Mat: {mat.name}] No ShaderGraph data in XML.")
        return

    y_offset = 600

    def setup_input(socket_names, xml_attr, is_data=False):
        nonlocal y_offset
        img_name = graph.get(f"{xml_attr}_image")

        target_socket = None
        if isinstance(socket_names, list):
            for n in socket_names:
                if n in bsdf.inputs:
                    target_socket = bsdf.inputs[n]
                    break
        elif socket_names in bsdf.inputs:
            target_socket = bsdf.inputs[socket_names]

        if not target_socket:
            return

        if img_name:
            img = bpy.data.images.get(img_name)

            tex_node = tree.nodes.new('ShaderNodeTexImage')
            tex_node.location = (-350, y_offset)
            y_offset -= 300

            if img:
                tex_node.image = img
                if is_data:
                    try:
                        tex_node.image.colorspace_settings.name = 'Non-Color'
                    except:
                        pass
                print(f"    - Linked {xml_attr} -> {img.name}")
            else:
                tex_node.label = f"MISSING: {img_name}"
                print(f"    - FAILED linking {xml_attr}: Image '{img_name}' not loaded.")

            if xml_attr == 'normal':
                norm_map = tree.nodes.new('ShaderNodeNormalMap')
                norm_map.location = (-150, y_offset + 300)
                tree.links.new(tex_node.outputs['Color'], norm_map.inputs['Color'])
                tree.links.new(norm_map.outputs['Normal'], target_socket)
            else:
                tree.links.new(tex_node.outputs['Color'], target_socket)

            if xml_attr == 'alpha':
                mat.blend_method = 'HASHED'

        val_str = graph.get(f"{xml_attr}_val")
        if val_str and not img_name:
            if "," in val_str:
                target_socket.default_value = [float(x) for x in val_str.split(',')]
            else:
                target_socket.default_value = float(val_str)

    setup_input("Base Color", "color")
    setup_input("Metallic", "metallic", is_data=True)
    setup_input("Roughness", "roughness", is_data=True)
    setup_input("Normal", "normal", is_data=True)
    setup_input(["Emission Color", "Emission"], "emission")
    setup_input("Alpha", "alpha")

def rebuild_armature_from_xml(armature_data_node):
    from mathutils import Vector

    # Create armature data + object
    arm_name = armature_data_node.get("name", "Armature")
    arm_data = bpy.data.armatures.new(arm_name)
    arm_obj = bpy.data.objects.new(arm_name, arm_data)
    # Register armature object so resolve_hierarchy can find it
    HIERARCHY_MAP[arm_obj] = {
        'parent': None,
        'type': None,
        'bone': None,
        'inv': None,
        'world_matrix': None,
        'transforms': [],
        'rotation_mode': None,
    }
    HIERARCHY_MAP[arm_data] = {'object': arm_obj}

    bpy.context.scene.collection.objects.link(arm_obj)

    # Make active and enter edit mode
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')

    bones_node = armature_data_node.find("Bones")
    bone_map = {}

    # First pass: create all edit bones with exported world-space head/tail
    for bone_node in bones_node.iter("Bone"):
        name = bone_node.get("name")
        head = Vector(map(float, bone_node.get("head").split(",")))
        tail = Vector(map(float, bone_node.get("tail").split(",")))

        eb = arm_data.edit_bones.new(name)
        eb.head = head
        eb.tail = tail
        bone_map[name] = eb

    # Second pass: assign parents
    for bone_node in bones_node.iter("Bone"):
        name = bone_node.get("name")
        parent_name = bone_node.get("parent_name")
        if parent_name and parent_name in bone_map:
            bone_map[name].parent = bone_map[parent_name]
            print("Parenting bone ", name, "to bone:", parent_name)

    # Exit edit mode
    bpy.ops.object.mode_set(mode='OBJECT')

    baked_node = armature_data_node.find("BakedPose")
    if baked_node is not None:
        rebuild_action_from_baked_pose(arm_obj, baked_node, action_name="Armature|Idle_Object_7")

    return arm_obj

def import_libraries(root, xml_dir):
    libs = root.find("Libraries")
    if not libs:
        return

    tex_dir_abs = os.path.join(xml_dir, "textures")
    if os.path.exists(tex_dir_abs):
        print(f"Scanning textures in: {tex_dir_abs}")
    else:
        print(f"WARNING: Texture dir not found at: {tex_dir_abs}")

    if libs.find("Images"):
        for i_node in libs.find("Images").findall("Image"):
            rel_path = i_node.get("filepath")
            name = i_node.get("name")
            img = None

            if rel_path:
                filename = os.path.basename(rel_path)

                manual_path = os.path.join(tex_dir_abs, filename)
                if os.path.exists(manual_path):
                    try:
                        img = bpy.data.images.load(manual_path)
                    except:
                        pass

                if not img:
                    img = image_utils.load_image(filename, dirname=xml_dir, place_holder=False, recursive=True)

                if img:
                    img.name = name
                    print(f"Loaded Image: {filename} -> '{img.name}'")
                else:
                    print(f"FAILED to load Image: {filename}")

            if not img:
                img = bpy.data.images.new(name, 32, 32)
                img.generated_color = (1, 0, 1, 1)

    if libs.find("Materials"):
        for mat_node in libs.find("Materials").findall("Material"):
            mat = bpy.data.materials.new(mat_node.get("name"))
            reconstruct_material_nodes(mat, mat_node)
            apply_xml_properties(mat, mat_node)

    if libs.find("Meshes"):
        for m_node in libs.find("Meshes").findall("Mesh"):
            mesh = bpy.data.meshes.new(m_node.get("name"))
            geo = m_node.find("Geometry")
            if geo:
                verts = [[float(x) for x in v.get("co").split(',')]
                         for v in geo.find("Vertices").findall("V")]
                faces = []
                mat_indices = []
                for p in geo.find("Polygons").findall("P"):
                    faces.append([int(x) for x in p.get("i").split(',')])
                    mat_indices.append(int(p.get("m", 0)))
                mesh.from_pydata(verts, [], faces)

                slots = m_node.find("MaterialSlots")
                if slots:
                    for slot in slots.findall("Slot"):
                        mat = bpy.data.materials.get(slot.get("name"))
                        if not mat:
                            mat = bpy.data.materials.new(slot.get("name"))
                        mesh.materials.append(mat)

                if len(mat_indices) == len(mesh.polygons):
                    mesh.polygons.foreach_set("material_index", mat_indices)

                mesh.update()

                if geo.find("UVLayers"):
                    for layer_node in geo.find("UVLayers").findall("Layer"):
                        uv_layer = mesh.uv_layers.new(name=layer_node.get("name"))
                        uv_data = []
                        for d in layer_node.findall("d"):
                            uv_data.append([float(x) for x in d.get("uv").split(',')])

                        if len(uv_data) == len(mesh.loops):
                            for i, uv in enumerate(uv_data):
                                uv_layer.data[i].uv = uv
                        if layer_node.get("active") == "True":
                            mesh.uv_layers.active = uv_layer

                mesh.validate()
                mesh.update()
            apply_xml_properties(mesh, m_node)

    for col_name, data_col, rna_type in [
        ("Lights", bpy.data.lights, 'POINT'),
        ("Cameras", bpy.data.cameras, None)
    ]:
        if libs.find(col_name):
            for node in libs.find(col_name):
                item = data_col.new(node.get("name"), rna_type) if rna_type else data_col.new(node.get("name"))
                apply_xml_properties(item, node)

    if libs.find("Armatures"):
        for arm_node in libs.find("Armatures").findall("ArmatureData"):
            rebuild_armature_from_xml(arm_node)

#            arm = bpy.data.armatures.new(arm_node.get("name"))
#            apply_xml_properties(arm, arm_node)
#            temp = bpy.data.objects.new("Temp", arm)
#            bpy.context.collection.objects.link(temp)
#            bpy.context.view_layer.objects.active = temp
#            bpy.ops.object.mode_set(mode='EDIT')
#            if arm_node.find("Bones"):
#                for b_node in arm_node.find("Bones").findall("Bone"):
#                    arm.edit_bones.new(b_node.get("name"))
#                for b_node in arm_node.find("Bones").findall("Bone"):
#                    eb = arm.edit_bones.get(b_node.get("name"))
#                    if eb:
#                        if b_node.get("head"):
#                            eb.head = Vector([float(x) for x in b_node.get("head").split(',')])
#                        if b_node.get("tail"):
#                            eb.tail = Vector([float(x) for x in b_node.get("tail").split(',')])
#                        if b_node.get("roll"):
#                            eb.roll = float(b_node.get("roll"))
#                for b_node in arm_node.find("Bones").findall("Bone"):
#                    eb = arm.edit_bones.get(b_node.get("name"))
#                    p_name = b_node.get("parent_name")
#                    if p_name:
#                        parent = arm.edit_bones.get(p_name)
#                        if parent:
#                            eb.parent = parent
#                            eb.use_connect = False
#
#            bpy.ops.object.mode_set(mode='OBJECT')
#            bpy.data.objects.remove(temp)

    if libs.find("Actions"):
        for act_node in libs.find("Actions").findall("Action"):
            action = bpy.data.actions.new(act_node.get("name"))
            apply_xml_properties(action, act_node)
            for fc_node in act_node.findall("FCurve"):
                fcurve = action.fcurves.new(
                    data_path=fc_node.get("data_path"),
                    index=int(fc_node.get("array_index"))
                )
                for kp_node in fc_node.findall("KP"):
                    co = [float(x) for x in kp_node.get("co").split(',')]
                    kp = fcurve.keyframe_points.insert(frame=co[0], value=co[1])
                    kp.interpolation = kp_node.get("interpolation", 'BEZIER')
                    kp.handle_left_type = 'FREE'
                    kp.handle_right_type = 'FREE'
                    if kp_node.get("hl"):
                        kp.handle_left = [float(x) for x in kp_node.get("hl").split(',')]
                    if kp_node.get("hr"):
                        kp.handle_right = [float(x) for x in kp_node.get("hr").split(',')]

def import_object(parent_node, collection, parent_obj=None):
    for obj_node in parent_node.findall("Object"):
        name = obj_node.get("name", "Obj")
        data_name = obj_node.get("data_name")
        data_block = None
        if data_name:
            data_block = (bpy.data.meshes.get(data_name) or
                          bpy.data.lights.get(data_name) or
                          bpy.data.cameras.get(data_name) or
                          bpy.data.armatures.get(data_name))

        if data_name and data_name in bpy.data.armatures:
            arm_data = bpy.data.armatures[data_name]
            if arm_data in HIERARCHY_MAP and 'object' in HIERARCHY_MAP[arm_data]:
                obj = HIERARCHY_MAP[arm_data]['object']
                if obj.name not in collection.objects:
                    collection.objects.link(obj)

                if obj.type == 'ARMATURE' and obj_node.find("Pose"):
                    DEFERRED_POSES.append((obj, obj_node.find("Pose")))
                if obj_node.get("active_action"):
                    DEFERRED_ACTIONS.append((obj, obj_node.get("active_action")))

                apply_xml_properties(obj, obj_node)
                import_object(obj_node, collection, parent_obj=obj)
                return

        existing_obj = next((o for o in bpy.data.objects if o.name == name and o.data == data_block), None)
        if existing_obj:
            obj = existing_obj
        else:
            obj = bpy.data.objects.new(name, data_block)
            collection.objects.link(obj)

        HIERARCHY_MAP[obj] = {
            'parent': None,
            'type': None,
            'bone': None,
            'inv': None,
            'world_matrix': None,
            'transforms': [],
            'rotation_mode': None,
        }


        if parent_obj:
            obj.parent = parent_obj

        if obj.type == 'ARMATURE':
            obj.show_in_front = True
            obj.data.display_type = 'STICK'

        apply_xml_properties(obj, obj_node)

        mods_node = obj_node.find("Modifiers")
        if mods_node:
            for m_node in mods_node.findall("Modifier"):
                mod = obj.modifiers.new(name=m_node.get("name"), type=m_node.get("type"))
                apply_xml_properties(mod, m_node)

        if obj_node.find("NLA"):
            if not obj.animation_data:
                obj.animation_data_create()
            for t_node in obj_node.find("NLA").findall("Track"):
                track = obj.animation_data.nla_tracks.new()
                apply_xml_properties(track, t_node)
                for s_node in t_node.findall("Strip"):
                    act = bpy.data.actions.get(s_node.get("action_name"))
                    if act:
                        try:
                            start_f = float(
                                s_node.find("Properties/Prop[@name='frame_start']").get("value")
                            )
                            strip = track.strips.new(s_node.get("name"), int(start_f), act)
                            apply_xml_properties(strip, s_node)
                        except:
                            pass

        if obj_node.find("VertexGroups"):
            for g_node in obj_node.find("VertexGroups").findall("Group"):
                vg = obj.vertex_groups.new(name=g_node.get("name"))
                if obj.type == 'MESH':
                    for vw in g_node.findall("VW"):
                        vg.add([int(vw.get("id"))], float(vw.get("w")), 'REPLACE')

        import_object(obj_node, collection, parent_obj=obj)

def import_collections(parent_xml, parent_col):
    for col_node in parent_xml.findall("Collection"):
        name = col_node.get("name", "Collection")

        if name == parent_col.name:
            target_col = parent_col
        else:
            target_col = bpy.data.collections.get(name)
            if not target_col:
                target_col = bpy.data.collections.new(name)
                parent_col.children.link(target_col)

        import_object(col_node, target_col, parent_obj=None)
        import_collections(col_node, target_col)

def apply_deferred_poses():
    print(f"Applying {len(DEFERRED_POSES)} deferred poses...")
    for obj, pose_node in DEFERRED_POSES:
        if not obj.pose:
            continue
        for pb_node in pose_node.findall("HBone"):
            pbone = obj.pose.bones.get(pb_node.get("name"))
            if pbone:
                apply_xml_properties(pbone, pb_node)

def apply_deferred_actions():
    print(f"Applying {len(DEFERRED_ACTIONS)} deferred actions...")
    for obj, act_name in DEFERRED_ACTIONS:
        act = bpy.data.actions.get(act_name)
        if act:
            if not obj.animation_data:
                obj.animation_data_create()
            obj.animation_data.action = act
            print(f"settiing obj.animation_data.action = {act}")

def resolve_hierarchy():
    print(f"Resolving hierarchy for {len(HIERARCHY_MAP)} objects...")
    valid_objects = [o for o in HIERARCHY_MAP.keys() if isinstance(o, bpy.types.Object)]

    # Parent relationships from properties (if any)
    for obj in valid_objects:
        data = HIERARCHY_MAP[obj]
        if data['parent']:
            parent = bpy.data.objects.get(data['parent'])
            if parent:
                if parent and parent is not obj:
                    obj.parent = parent
                if data['type']:
                    obj.parent_type = data['type']
                if data['bone']:
                    obj.parent_type = 'BONE'
                    obj.parent_bone = data['bone']
                    print("Parenting", obj.name, "to bone:", obj.parent_bone)
                    if hasattr(obj, "head"):
                        obj.head = data['head']
                    if hasattr(obj, "tail"):
                        obj.tail = data['tail']
                if data['inv']:
                    obj.matrix_parent_inverse = data['inv']
            else:
                print(f"WARNING: Parent '{data['parent']}' not found for {obj.name}")

    # Transforms
    for obj in valid_objects:
        data = HIERARCHY_MAP[obj]

        if data['rotation_mode'] is not None:
            obj.rotation_mode = data['rotation_mode']

        if data['world_matrix'] is not None:
            # Option A: matrix_world wins, ignore local transforms
            try:
                obj.matrix_world = data['world_matrix']
            except Exception as e:
                print(f"Failed to set matrix_world on {obj.name}: {e}")
        else:
            for prop_name, val in data['transforms']:
                try:
                    setattr(obj, prop_name, val)
                except Exception as e:
                    print(f"Failed to set {prop_name} on {obj.name}: {e}")

def resolve_links():
    for obj, prop_name, target_name in DEFERRED_LINKS:
        target = (bpy.data.objects.get(target_name) or
                  bpy.data.meshes.get(target_name) or
                  bpy.data.materials.get(target_name) or
                  bpy.data.actions.get(target_name) or
                  bpy.data.armatures.get(target_name) or
                  bpy.data.cameras.get(target_name) or
                  bpy.data.lights.get(target_name) or
                  bpy.data.images.get(target_name))
        if target:
            try:
                setattr(obj, prop_name, target)
            except:
                pass

def importFromXML(filename):
    abs_path = os.path.abspath(filename)
    print(f"Importing from: {abs_path}")

    if not os.path.exists(abs_path):
        print(f"ERROR: XML file not found at {abs_path}")
        return

    tree = ET.parse(abs_path)
    root = tree.getroot()
    clean_scene()

    import_libraries(root, os.path.dirname(abs_path))

    scenes = root.find("Scenes")
    if scenes:
        for s_node in scenes.findall("Scene"):
            scene = bpy.data.scenes.new(s_node.get("name")) if len(bpy.data.scenes) == 0 else bpy.data.scenes[0]
            scene.name = s_node.get("name")
            if s_node.get("frame_start"):
                scene.frame_start = int(s_node.get("frame_start"))
            if s_node.get("frame_end"):
                scene.frame_end = int(s_node.get("frame_end"))

            bpy.context.window.scene = scene
            import_collections(s_node, scene.collection)
            apply_xml_properties(scene, s_node)

    resolve_hierarchy()
    resolve_links()
    bpy.context.view_layer.update()
    apply_deferred_poses()
    apply_deferred_actions()
    bpy.context.scene.frame_set(bpy.context.scene.frame_start)
    print("Import Complete.")

try:
    importFromXML("sandrunner_bike.blxml")
except:
    import traceback
    traceback.print_exc()
