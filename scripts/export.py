import bpy
import xml.etree.ElementTree as ET
import os
import mathutils

def get_prop_info(obj, prop_identifier, prop_def):
    try:
        val = getattr(obj, prop_identifier)
        structure_type = ""

        if isinstance(val, mathutils.Vector):
            structure_type = "VECTOR"
            val_str = ",".join(map(str, val[:]))
        elif isinstance(val, mathutils.Euler):
            structure_type = "EULER"
            val_str = ",".join(map(str, val[:]))
        elif isinstance(val, mathutils.Quaternion):
            structure_type = "QUATERNION"
            val_str = ",".join(map(str, val[:]))
        elif isinstance(val, mathutils.Matrix):
            structure_type = "MATRIX_4X4" if len(val) == 4 else "MATRIX"
            flat_list = [col for row in val for col in row]
            val_str = ",".join(map(str, flat_list))
        elif prop_def.type == 'POINTER':
            val_str = val.name if val else "None"
        elif prop_def.type in {'FLOAT_ARRAY', 'INT_ARRAY', 'BOOLEAN_ARRAY'}:
            if hasattr(val, "__iter__"):
                val_str = ",".join(map(str, val))
            else:
                val_str = str(val)
        else:
            val_str = str(val)

        return val_str, prop_def.type, structure_type
    except:
        return "", "UNKNOWN", ""

def write_rna_properties(xml_element, blender_object):
    if hasattr(blender_object, "name"):
        xml_element.set("name", blender_object.name)
    if hasattr(blender_object, "type"):
        xml_element.set("type", blender_object.type)

    if not hasattr(blender_object, "bl_rna"):
        return

    props_container = ET.SubElement(xml_element, "Properties")

    rot_mode = getattr(blender_object, "rotation_mode", "XYZ")

    # Exclude calculated matrices. Keep Deltas and Parent Inverse.
    skip_props = {
        'matrix_basis', 'matrix_local', 'matrix_world', 'matrix_custom', 'matrix',
        'is_readonly', 'data'
    }

    if rot_mode == 'QUATERNION':
        skip_props.update({'rotation_euler', 'rotation_axis_angle'})
    elif rot_mode == 'AXIS_ANGLE':
        skip_props.update({'rotation_euler', 'rotation_quaternion'})
    else:
        skip_props.update({'rotation_quaternion', 'rotation_axis_angle'})

    for prop in blender_object.bl_rna.properties:
        if prop.is_readonly: continue
        if prop.identifier in skip_props: continue

        val_str, type_str, struct_type = get_prop_info(blender_object, prop.identifier, prop)
        if type_str == 'POINTER' and (val_str == "None" or val_str == ""): continue

        attrs = {
            "name": prop.identifier,
            "type": type_str,
            "value": val_str
        }
        if struct_type: attrs["structure_type"] = struct_type

        ET.SubElement(props_container, "Prop", attrs)

def traverse_mesh_geometry(mesh_data, parent_node):
    mesh_node = ET.SubElement(parent_node, "Geometry")
    verts_node = ET.SubElement(mesh_node, "Vertices", {"count": str(len(mesh_data.vertices))})
    for v in mesh_data.vertices:
        ET.SubElement(verts_node, "V", {"co": f"{v.co.x},{v.co.y},{v.co.z}"})
    polys_node = ET.SubElement(mesh_node, "Polygons", {"count": str(len(mesh_data.polygons))})
    for p in mesh_data.polygons:
        ET.SubElement(polys_node, "P", {"i": ",".join(map(str, p.vertices))})

def export_material_nodes(mat, mat_node):
    if not mat.use_nodes or not mat.node_tree: return
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not bsdf: return

    shader_node = ET.SubElement(mat_node, "ShaderGraph", {"type": "PRINCIPLED"})

    def export_socket(sock_name, xml_attr):
        sock = bsdf.inputs.get(sock_name)
        if not sock: return
        if sock.is_linked:
            link = sock.links[0]
            if link.from_node.type == 'TEX_IMAGE' and link.from_node.image:
                shader_node.set(f"{xml_attr}_image", link.from_node.image.name)
        else:
            val = sock.default_value
            if hasattr(val, "__iter__"):
                shader_node.set(f"{xml_attr}_val", ",".join(map(str, val)))
            else:
                shader_node.set(f"{xml_attr}_val", str(val))

    export_socket("Base Color", "color")
    export_socket("Metallic", "metallic")
    export_socket("Roughness", "roughness")
    export_socket("Emission Color", "emission")
    export_socket("Alpha", "alpha")

    norm_sock = bsdf.inputs.get("Normal")
    if norm_sock and norm_sock.is_linked:
        link = norm_sock.links[0]
        if link.from_node.type == 'NORMAL_MAP':
            color_sock = link.from_node.inputs.get("Color")
            if color_sock and color_sock.is_linked:
                 if color_sock.links[0].from_node.type == 'TEX_IMAGE':
                     img = color_sock.links[0].from_node.image
                     if img: shader_node.set("normal_image", img.name)

def traverse_nla_tracks(obj, parent_node):
    if not obj.animation_data or not obj.animation_data.nla_tracks: return
    nla_node = ET.SubElement(parent_node, "NLA")
    for track in obj.animation_data.nla_tracks:
        t_node = ET.SubElement(nla_node, "Track")
        write_rna_properties(t_node, track)
        for strip in track.strips:
            s_node = ET.SubElement(t_node, "Strip")
            write_rna_properties(s_node, strip)
            if strip.action: s_node.set("action_name", strip.action.name)

def traverse_libraries(root, base_path):
    libs_node = ET.SubElement(root, "Libraries")

    # Images
    imgs_node = ET.SubElement(libs_node, "Images")
    tex_dir = os.path.join(os.path.dirname(base_path), "textures")
    if not os.path.exists(tex_dir): os.makedirs(tex_dir)

    for img in bpy.data.images:
        if img.type == 'IMAGE' and img.name not in ['Render Result', 'Viewer Node']:
            i_node = ET.SubElement(imgs_node, "Image")
            write_rna_properties(i_node, img)
            try:
                safe_name = "".join([c for c in img.name if c.isalpha() or c.isdigit() or c=='_']).rstrip()
                if not safe_name: safe_name = "texture"
                filename = f"{safe_name}.png"
                abs_filepath = os.path.join(tex_dir, filename)
                rel_filepath = f"textures/{filename}"
                img.save_render(filepath=abs_filepath)
                i_node.set("filepath", rel_filepath)
                props = i_node.find("Properties")
                if props:
                    for p in props.findall("Prop"):
                        if p.get("name") == "filepath": p.set("value", rel_filepath)
            except: pass

    # Meshes
    meshes_node = ET.SubElement(libs_node, "Meshes")
    for mesh in bpy.data.meshes:
        m_node = ET.SubElement(meshes_node, "Mesh")
        write_rna_properties(m_node, mesh)
        traverse_mesh_geometry(mesh, m_node)

    # Materials
    mats_node = ET.SubElement(libs_node, "Materials")
    for mat in bpy.data.materials:
        mat_node = ET.SubElement(mats_node, "Material")
        write_rna_properties(mat_node, mat)
        export_material_nodes(mat, mat_node)

    # Lights & Cameras
    for col_name, data_col, tag in [("Lights", bpy.data.lights, "Light"), ("Cameras", bpy.data.cameras, "Camera")]:
        node = ET.SubElement(libs_node, col_name)
        for item in data_col:
            write_rna_properties(ET.SubElement(node, tag), item)

    # Armatures
    arm_node = ET.SubElement(libs_node, "Armatures")
    for arm in bpy.data.armatures:
        a_node = ET.SubElement(arm_node, "ArmatureData")
        write_rna_properties(a_node, arm)
        bones_container = ET.SubElement(a_node, "Bones")
        for bone in arm.bones:
            b_node = ET.SubElement(bones_container, "Bone")
            write_rna_properties(b_node, bone)
            if bone.parent: b_node.set("parent_name", bone.parent.name)
            b_node.set("head", f"{bone.head.x},{bone.head.y},{bone.head.z}")
            b_node.set("tail", f"{bone.tail.x},{bone.tail.y},{bone.tail.z}")
            if hasattr(bone, "roll"): b_node.set("roll", str(bone.roll))

    # Actions
    actions_node = ET.SubElement(libs_node, "Actions")
    for action in bpy.data.actions:
        act_node = ET.SubElement(actions_node, "Action")
        write_rna_properties(act_node, action)
        if hasattr(action, "fcurves"):
            for fcurve in action.fcurves:
                fc_node = ET.SubElement(act_node, "FCurve", {
                    "data_path": fcurve.data_path,
                    "array_index": str(fcurve.array_index)
                })
                for kp in fcurve.keyframe_points:
                    ET.SubElement(fc_node, "KP", {
                        "co": f"{kp.co.x},{kp.co.y}",
                        "hl": f"{kp.handle_left.x},{kp.handle_left.y}",
                        "hr": f"{kp.handle_right.x},{kp.handle_right.y}",
                        "interpolation": kp.interpolation
                    })

def traverse_object(obj, parent_node):
    obj_node = ET.SubElement(parent_node, "Object")
    write_rna_properties(obj_node, obj)
    if obj.data: obj_node.set("data_name", obj.data.name)
    if obj.animation_data and obj.animation_data.action:
        obj_node.set("active_action", obj.animation_data.action.name)

    if obj.type == 'ARMATURE' and obj.pose:
        pose_node = ET.SubElement(obj_node, "Pose")
        for pbone in obj.pose.bones:
            pb_node = ET.SubElement(pose_node, "HBone", {"name": pbone.name})
            write_rna_properties(pb_node, pbone)

    traverse_nla_tracks(obj, obj_node)

    if obj.vertex_groups:
        vg_node = ET.SubElement(obj_node, "VertexGroups")
        for vg in obj.vertex_groups:
            g_node = ET.SubElement(vg_node, "Group", {"name": vg.name})
            if obj.type == 'MESH' and obj.data:
                for v in obj.data.vertices:
                    for g in v.groups:
                        if g.group == vg.index:
                            ET.SubElement(g_node, "VW", {"id": str(v.index), "w": f"{g.weight:.4f}"})

    for child in obj.children:
        traverse_object(child, obj_node)

def traverse_scenes(root):
    scenes_node = ET.SubElement(root, "Scenes")
    for scene in bpy.data.scenes:
        s_node = ET.SubElement(scenes_node, "Scene")
        write_rna_properties(s_node, scene)

        s_node.set("frame_start", str(scene.frame_start))
        s_node.set("frame_end", str(scene.frame_end))

        for obj in scene.collection.objects:
            if obj.parent is None: traverse_object(obj, s_node)
        for child_col in scene.collection.children: traverse_collection(child_col, s_node)

def traverse_collection(col, parent_node):
    col_node = ET.SubElement(parent_node, "Collection")
    write_rna_properties(col_node, col)
    for obj in col.objects:
        if obj.parent is None: traverse_object(obj, col_node)
    for child in col.children: traverse_collection(child, col_node)

def exportToXML(infile, outfile):
    bpy.ops.wm.open_mainfile(filepath=infile)
    abs_outfile = os.path.abspath(outfile)
    root = ET.Element("BlenderData", source=infile)
    traverse_libraries(root, abs_outfile)
    traverse_scenes(root)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    with open(abs_outfile, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)

exportToXML("sandrunner_bike.blend", "sandrunner_bike.blxml")
