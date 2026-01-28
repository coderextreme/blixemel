import bpy
import xml.etree.ElementTree as ET

def get_prop_info(obj, prop_identifier, prop_def):
    try:
        val = getattr(obj, prop_identifier)
        if prop_def.type == 'POINTER':
            return (val.name, "POINTER") if val else ("None", "POINTER")
        if prop_def.type in {'FLOAT_ARRAY', 'INT_ARRAY', 'BOOLEAN_ARRAY'}:
            if hasattr(val, "__iter__"):
                return ",".join(map(str, val)), prop_def.type
            return str(val), prop_def.type
        return str(val), prop_def.type
    except:
        return "", "UNKNOWN"

def write_rna_properties(xml_element, blender_object):
    if hasattr(blender_object, "name"):
        xml_element.set("name", blender_object.name)
    if hasattr(blender_object, "type"):
        xml_element.set("type", blender_object.type)

    if not hasattr(blender_object, "bl_rna"):
        return

    props_container = ET.SubElement(xml_element, "Properties")
    for prop in blender_object.bl_rna.properties:
        if prop.is_readonly: continue

        val_str, type_str = get_prop_info(blender_object, prop.identifier, prop)

        # Optimization: Skip empty pointers and data pointers (handled explicitly)
        if type_str == 'POINTER' and (val_str == "None" or val_str == ""): continue
        if prop.identifier == 'data': continue

        ET.SubElement(props_container, "Prop", {
            "name": prop.identifier,
            "type": type_str,
            "value": val_str
        })

def traverse_mesh_geometry(mesh_data, parent_node):
    mesh_node = ET.SubElement(parent_node, "Geometry")
    verts_node = ET.SubElement(mesh_node, "Vertices", {"count": str(len(mesh_data.vertices))})
    for v in mesh_data.vertices:
        ET.SubElement(verts_node, "V", {"co": f"{v.co.x},{v.co.y},{v.co.z}"})
    polys_node = ET.SubElement(mesh_node, "Polygons", {"count": str(len(mesh_data.polygons))})
    for p in mesh_data.polygons:
        ET.SubElement(polys_node, "P", {"i": ",".join(map(str, p.vertices))})

def traverse_nla_tracks(obj, parent_node):
    """Exports NLA Tracks and Strips."""
    if not obj.animation_data or not obj.animation_data.nla_tracks:
        return

    nla_node = ET.SubElement(parent_node, "NLA")
    for track in obj.animation_data.nla_tracks:
        t_node = ET.SubElement(nla_node, "Track")
        write_rna_properties(t_node, track)

        for strip in track.strips:
            s_node = ET.SubElement(t_node, "Strip")
            write_rna_properties(s_node, strip)
            # Explicitly link the Action from the library
            if strip.action:
                s_node.set("action_name", strip.action.name)

def traverse_libraries(root):
    libs_node = ET.SubElement(root, "Libraries")

    # 1. Meshes
    meshes_node = ET.SubElement(libs_node, "Meshes")
    for mesh in bpy.data.meshes:
        m_node = ET.SubElement(meshes_node, "Mesh")
        write_rna_properties(m_node, mesh)
        traverse_mesh_geometry(mesh, m_node)

    # 2. Materials
    mats_node = ET.SubElement(libs_node, "Materials")
    for mat in bpy.data.materials:
        mat_node = ET.SubElement(mats_node, "Material")
        write_rna_properties(mat_node, mat)

    # 3. Lights
    lights_node = ET.SubElement(libs_node, "Lights")
    for light in bpy.data.lights:
        l_node = ET.SubElement(lights_node, "Light")
        write_rna_properties(l_node, light)

    # 4. Cameras
    cams_node = ET.SubElement(libs_node, "Cameras")
    for cam in bpy.data.cameras:
        c_node = ET.SubElement(cams_node, "Camera")
        write_rna_properties(c_node, cam)

    # 5. Armatures
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
            if hasattr(bone, "roll"):
                b_node.set("roll", str(bone.roll))

    # 6. Actions
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
                    ET.SubElement(fc_node, "KP", {"co": f"{kp.co.x},{kp.co.y}"})

def traverse_object(obj, parent_node):
    obj_node = ET.SubElement(parent_node, "Object")
    write_rna_properties(obj_node, obj)

    # Explicit Data Link
    if obj.data:
        obj_node.set("data_name", obj.data.name)

    # NLA Tracks (Restored)
    traverse_nla_tracks(obj, obj_node)

    # Vertex Groups
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

        # UNWRAP Master Collection:
        # Instead of calling traverse_collection on scene.collection (which creates a tag),
        # we iterate the master collection's contents directly into the Scene node.
        for obj in scene.collection.objects:
            if obj.parent is None:
                traverse_object(obj, s_node)

        for child_col in scene.collection.children:
            traverse_collection(child_col, s_node)

def traverse_collection(col, parent_node):
    col_node = ET.SubElement(parent_node, "Collection")
    write_rna_properties(col_node, col)
    for obj in col.objects:
        if obj.parent is None:
            traverse_object(obj, col_node)
    for child in col.children:
        traverse_collection(child, col_node)

def exportToXML(infile, outfile):
    bpy.ops.wm.open_mainfile(filepath=infile)
    root = ET.Element("BlenderData", source=infile)
    traverse_libraries(root)
    traverse_scenes(root)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    with open(outfile, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)

exportToXML("sandrunner_bike.blend", "sandrunner_bike.blxml")
