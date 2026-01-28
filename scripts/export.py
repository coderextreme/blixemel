import bpy
import os
import xml.etree.ElementTree as ET

def write_rna_properties(xml_element, blender_object):
    """Iterates RNA properties and writes them as typed XML child nodes."""

    # 1. Write 'name' and specific IDs as attributes for easy access
    if hasattr(blender_object, "name"):
        xml_element.set("name", blender_object.name)

    if hasattr(blender_object, "type"):
        xml_element.set("type", blender_object.type)
        if blender_object.type == 'MESH':
            for attr in blender_object.data.attributes:
                xml_element.set(f"attr_{attr.name}", {
                    "domain": attr.domain,
                    "type": attr.data_type
                })

    if not hasattr(blender_object, "bl_rna"):
        return

    # 2. Write all other properties as children with Type info
    props_container = ET.SubElement(xml_element, "Properties")

    for prop in blender_object.bl_rna.properties:
        if prop.is_readonly:
            continue

        val_str, type_str = get_prop_info(blender_object, prop.identifier, prop)

        ET.SubElement(props_container, "Property", {
            "name": prop.identifier,
            "type": type_str,
            "value": val_str
        })

#def createBlenderHash(thing):
#    if hasattr(thing.bl_rna, "properties"):
#        rna_data = {p.identifier: get_serializable_value(thing, p.identifier)
#            for p in thing.bl_rna.properties
#            if not p.is_readonly}
#    else:
#        rna_data = {}
#    custom_data = {}
#    if hasattr(thing, "keys"):
#        try:
#            for key in thing.keys():
#                custom_data[f"custom_{key}"] = str(thing[key])
#        except TypeError:
#            # Catch cases where .keys() exists but is not for IDProperties
#            pass
#    attr_data = {}
#    if thing and hasattr(thing, "type") and thing.type == 'MESH':
#        attr_data = {
#            f"attr_{attr.name}": {
#                "domain": attr.domain,
#                "type": attr.data_type
#            } for attr in thing.data.attributes
#        }
#    thing_hash = {**rna_data, **custom_data, **attr_data }
#    return thing_hash

def traverse_bones(bone, bones_node):
    bone_node = ET.SubElement(bones_node, "Bone")
    write_rna_properties(bone_node, bone)
    for child in bone.children:
        traverse_bones(child, bone_node)

def traverse_armature(arm_obj, obj_node):
    bones_node = ET.SubElement(obj_node, "Armature")
    write_rna_properties(bones_node, arm_obj)
    if arm_obj and arm_obj.type == 'ARMATURE':
        for bone in arm_obj.data.bones:
            if bone.parent is None:
                traverse_bones(bone, bones_node)

def traverse_object(obj, scene_node):
    # Create the Object Node
    obj_node = ET.SubElement(scene_node, "Object")
    write_rna_properties(obj_node, obj) # Use the new typed property writer

    # --- EXPORT DATA BLOCK (The content inside the object) ---
    if obj.data:
        data_node = ET.SubElement(obj_node, "Data")
        # Write generic data properties (Energy for lights, Lens for cameras)
        write_rna_properties(data_node, obj.data)

        # If it is a Mesh, export the geometry geometry
        if obj.type == 'MESH':
            traverse_mesh_geometry(obj.data, data_node)

    # Existing traversals
    traverse_armature(obj, obj_node)
    traverse_weights(obj, obj_node)
    traverse_nla_tracks(obj, obj_node)
    traverse_nodes(obj, obj_node)

    for child in obj.children:
        traverse_object(child, obj_node)

#def traverse_object(obj, scene_node):
#    obj_node = ET.SubElement(scene_node, "Object", createBlenderHash(obj))
#    traverse_armature(obj, obj_node)
#    traverse_weights(obj, obj_node)
#    traverse_nla_tracks(obj, obj_node)
#    traverse_nodes(obj, obj_node)
#
#    for child in obj.children:
#        traverse_object(child, obj_node)

def traverse_collections(col, scene_node):
    col_node = ET.SubElement(scene_node, "Collection")
    write_rna_properties(col_node, col)
    for obj in col.objects:
        traverse_object(obj, col_node)
    for child in col.children:
        traverse_collections(child, col_node)

def get_xml_safe_value(node, prop):
    """Converts complex Blender types into XML-serializable strings."""
    try:
        # Get the actual value from the node instance
        value = getattr(node, prop.identifier)
        
        # 1. Handle PointerProperties (C++ references)
        if prop.type == 'POINTER':
            if value is None:
                return ""
            # Return the name of the referenced object (Object, Material, etc.)
            return getattr(value, "name", str(value))

        # 2. Handle Collections or Math types (Vectors, Colors)
        if prop.type in {'COLLECTION', 'FLOAT_ARRAY', 'INT_ARRAY'}:
            return str(list(value)) if hasattr(value, "__iter__") else str(value)

        # 3. Handle everything else as a simple string
        return str(value)
    except Exception:
        return "N/A"

def exportToXML(infile, outfile):
    bpy.ops.wm.open_mainfile(filepath=infile)
    root = ET.Element("BlenderData", source=infile)
    traverse_scenes(root)
    traverse_actions(root)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    with open(outfile, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)

def traverse_nla_tracks(obj, obj_node):
    if not (obj.animation_data and obj.animation_data.nla_tracks):
        return
    for track in obj.animation_data.nla_tracks:
        track_node = ET.SubElement(obj_node, "Track")
        write_rna_properties(track_node, track)
        for strip in track.strips:
            if not strip.action:
                continue
            strip_node = ET.SubElement(track_node, "Strip")
            write_rna_properties(strip_node, strip)
            if hasattr(strip.action, "fcurves"):
                for fcu in strip.action.fcurves:
                    channel_node = ET.SubElement(strip_node, "Channel")
                    write_rna_properties(channel_node, fcu)
                    for kfp in fcu.keyframe_points:
                        kfp_node = ET.SubElement(channel_node, "KeyframePoints")
                        write_rna_properties(kfp_node, kfp)

def traverse_actions(root):
    for action in bpy.data.actions:
        action_node = ET.SubElement(root, "Action")
        write_rna_properties(action_node, action)
        if hasattr(action, "fcurves"):
            for fcurve in action.fcurves:
                fcurve_node = ET.SubElement(action_node, "FCurve")
                write_rna_properties(fcurve_node, fcurve)
                for kfp in fcurve.keyframe_points:
                    kfp_node = ET.SubElement(fcurve_node, "KeyFramePoints")
                    write_rna_properties(kfp_node, kfp)


def get_prop_info(obj, prop_identifier, prop_def):
    """Returns a tuple: (value_string, type_string)"""
    try:
        val = getattr(obj, prop_identifier)

        # 1. Handle Pointers (Links to other objects/materials)
        if prop_def.type == 'POINTER':
            if val is None:
                return "None", "POINTER"
            return val.name, "POINTER" # We store the Name as the reference ID

        # 2. Handle Collections (Vectors, Colors, Matrices)
        if prop_def.type in {'FLOAT_ARRAY', 'INT_ARRAY', 'BOOLEAN_ARRAY'}:
            # Convert Vector((1, 2)) to "1,2" for easy parsing
            if hasattr(val, "__iter__"):
                return ",".join(map(str, val)), prop_def.type
            return str(val), prop_def.type

        # 3. Handle Enums, Strings, Numbers
        return str(val), prop_def.type

    except Exception:
        return "", "UNKNOWN"

#def get_serializable_value(obj, prop_id):
#    val = getattr(obj, prop_id)
#    # Check if the value is a Blender ID object (Object, Material, etc.)
#    if hasattr(val, "name"):
#        return val.name
#    # Handle math types (Vector, Color) which also fail XML serialization
#    if hasattr(val, "to_list"):
#        return str(val.to_list())
#    return str(val)

def traverse_node(node_tree, node_node):
    if node_tree is None:
        return
    node_tree_node = ET.SubElement(node_node, "NodeTree")
    write_rna_properties(node_tree_node, node_tree)
    for node in node_tree.nodes:
        node_node = ET.SubElement(node_tree_node, "Node")
        write_rna_properties(node_node, node)
        if node.type == 'GROUP' and node.node_tree:
            traverse_node(node.node_tree, node_node)

def traverse_nodes(obj, obj_node):
    if obj and obj.material_slots:
        slots_node = ET.SubElement(obj_node, "Slots")
        for slot in obj.material_slots:
            if slot.material and slot.material.use_nodes:
                traverse_node(slot.material.node_tree, slots_node)

def traverse_mesh_geometry(mesh_data, parent_node):
    """Exports actual vertices and faces."""
    mesh_node = ET.SubElement(parent_node, "MeshData", {"name": mesh_data.name})

    # 1. Export Vertices
    verts_node = ET.SubElement(mesh_node, "Vertices", {"count": str(len(mesh_data.vertices))})
    for v in mesh_data.vertices:
        # Coords are a vector
        co_str = f"{v.co.x},{v.co.y},{v.co.z}"
        ET.SubElement(verts_node, "V", {"co": co_str})

    # 2. Export Polygons (Faces)
    polys_node = ET.SubElement(mesh_node, "Polygons", {"count": str(len(mesh_data.polygons))})
    for p in mesh_data.polygons:
        # Vertex Indices list
        indices_str = ",".join(map(str, p.vertices))
        ET.SubElement(polys_node, "P", {"i": indices_str})

def traverse_weights(obj, obj_node):
    if not obj or obj.type != 'MESH':
        print("Please select a Mesh object.")
        return
    groups_node = ET.SubElement(obj_node, "VertexGroups")
    group_map = {g.index: g.name for g in obj.vertex_groups}
    for v in obj.data.vertices:
        for g_element in v.groups:
            group_name = group_map.get(g_element.group, "Unknown")
            group_node = groups_node.find(f"./Group[@name='{group_name}']")
            if group_node is None:
                group_node = ET.SubElement(groups_node, "Group", {
                    "name": group_name,
                    "index": str(g_element.group)
                })
            ET.SubElement(group_node, "Vertex", {
                "id": str(v.index),
                "weight": f"{g_element.weight:.4f}"
            })

def traverse_scene(scene, scenes_node):
    scene_node = ET.SubElement(scenes_node, "Scene")
    write_rna_properties(scene_node, scene)
    traverse_collections(scene.collection, scene_node)
    for obj in scene.objects:
        traverse_object(obj, scene_node)

def traverse_scenes(root):
    scenes_node = ET.SubElement(root, "Scenes")
    for scene in bpy.data.scenes:
        traverse_scene(scene, scenes_node)

exportToXML("sandrunner_bike.blend", "sandrunner_bike.blxml")

